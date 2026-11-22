from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from annie import audio_setup
from annie.diarization import (DiarizationCancelled, DiarizationError, _normalize_turns,
                               assign_speaker_words, assign_speakers, diarization_ready,
                               diarize, overlap_windows, overlapping_passages, speaker_voice_sample,
                               worker_main)
from annie.whisper_worker import clean_stray_scripts


class SpeakerAssignmentTests(unittest.TestCase):
    def test_overlap_review_excludes_duplicate_and_touching_turns(self):
        turns = _normalize_turns([(0, 6, 'a'), (1, 5, 'a'), (3, 4, 'b'),
                                  (6, 8, 'b'), (10, 18, 'a')], 20)
        windows = overlap_windows(turns)
        self.assertEqual(windows, [(3, 4)])
        rows = [{'id': 'clear', 'start': 0, 'end': 3, 'speaker': 'speaker-1'},
                {'id': 'busy', 'start': 3.5, 'end': 6, 'speaker': 'speaker-1'},
                {'id': 'returns', 'start': 10, 'end': 18, 'speaker': 'speaker-1'}]
        self.assertEqual(overlapping_passages(rows, windows), {'busy'})
        self.assertEqual(speaker_voice_sample(rows, 'speaker-1', windows), (10, 15))

    def test_returning_label_and_overlapping_turns(self):
        turns = _normalize_turns([(65, 70, 'x'), (4, 6, 'y'), (0, 3, 'x'),
                                  (5, 7, 'z'), (90, 105, 'y')], 100)
        self.assertEqual(turns[-1], {'start': 90, 'end': 100, 'speaker': 'speaker-2'})
        self.assertEqual(turns[3]['speaker'], turns[0]['speaker'])
        self.assertEqual(assign_speakers([
            {'id': 'first', 'start': 0, 'end': 3},
            {'id': 'second', 'start': 4, 'end': 5},
            {'id': 'ambiguous', 'start': 5, 'end': 6},
            {'id': 'quiet', 'start': 15, 'end': 20},
            {'id': 'return', 'start': 65, 'end': 70},
        ], turns), {'first': 'speaker-1', 'second': 'speaker-2', 'return': 'speaker-1'})

    def test_duplicate_turns_never_inflate_coverage(self):
        turns = [
            {'start': 0, 'end': 2, 'speaker': 'a'},
            {'start': 0, 'end': 2, 'speaker': 'a'},
            {'start': 0, 'end': 2, 'speaker': 'b'},
        ]
        self.assertEqual(assign_speakers([{'id': 'one', 'start': 0, 'end': 2}], turns), {})

    def test_timed_words_preserve_speaker_changes_in_one_segment(self):
        segment = {'id': 'mixed', 'start': 0, 'end': 9, 'words': [
            {'start': 1, 'end': 2, 'text': 'Hello'},
            {'start': 8, 'end': 9, 'text': 'Yes'},
        ]}
        turns = [{'start': 1, 'end': 2, 'speaker': 'a'}, {'start': 8, 'end': 9, 'speaker': 'b'}]
        self.assertEqual([word['speaker'] for word in assign_speaker_words([segment], turns)['mixed']],
                         ['a', 'b'])
        self.assertEqual(assign_speakers([segment], turns), {})
        self.assertTrue(all('speaker' not in word for word in segment['words']))

    def test_transcript_cleanup_keeps_kazakh_specific_letters(self):
        text = 'Әә Ғғ Ққ Ңң Өө Ұұ Үү Һһ Іі data structure'
        self.assertEqual(clean_stray_scripts(text + ' 字'), text)


class LocalSpeakerWorkerTests(unittest.TestCase):
    def test_missing_models_report_a_recoverable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'recording.wav'
            audio.touch()
            self.assertFalse(diarization_ready(root))
            with self.assertRaisesRegex(DiarizationError, 'local speaker models'):
                diarize(audio, model_path=root)

    def test_silent_wav_does_not_need_model_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'silent.wav'
            result = root / 'turns.json'
            with wave.open(str(audio), 'wb') as stream:
                stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                stream.writeframes(bytes(16000 * 2))
            with patch('annie.diarization._sherpa_turns') as engine:
                self.assertEqual(worker_main([str(audio), str(root), 'sherpa', str(result)]), 0)
                engine.assert_not_called()
            self.assertEqual(result.read_text(encoding='utf-8'), '{"turns": []}')

    def test_cancellation_reaps_started_worker(self):
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'recording.wav'
            audio.touch()
            with patch('annie.diarization._backend', return_value='sherpa'), \
                    patch('annie.diarization.subprocess.Popen') as spawn:
                worker = spawn.return_value
                worker.poll.return_value = None

                def wait(timeout=None):
                    if timeout is not None:
                        stop.set()
                        raise subprocess.TimeoutExpired('diarize', timeout)
                    return 0

                worker.wait.side_effect = wait
                with self.assertRaises(DiarizationCancelled):
                    diarize(audio, model_path=root, stop=stop)
                worker.kill.assert_called_once_with()
                worker.wait.assert_called_with()


class AudioSetupTests(unittest.TestCase):
    def test_input_check_caps_sample_and_obeys_cancellation(self):
        def deliver_pcm(device, stop, deliver):
            self.assertEqual(device, 'dual')
            deliver(struct.pack('<h', -32768) * 96_000)
            self.assertTrue(stop.is_set())
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / 'test.wav'
            cancel = threading.Event()
            seconds, peak = audio_setup.record_input_sample(
                'dual', sample, cancel, lambda *_: None, capture=deliver_pcm)
            self.assertEqual((seconds, peak), (5, 1))
            with wave.open(str(sample)) as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getnframes()), (16000, 1, 80_000))
            cancel.set()
            sample.unlink()
            with self.assertRaises(audio_setup.SetupCancelled):
                audio_setup.record_input_sample('dual', sample, cancel, lambda *_: None, capture=deliver_pcm)
            self.assertFalse(sample.exists())

    def test_speaker_setup_only_publishes_a_verified_complete_pair(self):
        segmentation = b'test segmentation'
        embedding = b'test embedding'
        tar = BytesIO()
        with tarfile.open(fileobj=tar, mode='w:bz2') as archive:
            for name, data in (('model.int8.onnx', segmentation), ('LICENSE', b'fixture')):
                member = tarfile.TarInfo(f'{audio_setup._SEGMENTATION_FOLDER}/{name}')
                member.size = len(data)
                archive.addfile(member, BytesIO(data))
        compressed = tar.getvalue()
        expected_bytes = len(compressed) + len(embedding)
        events = []
        with tempfile.TemporaryDirectory() as directory, patch.multiple(audio_setup,
                _ARCHIVE_BYTES=len(compressed), _EMBEDDING_BYTES=len(embedding),
                _SEGMENTATION_BYTES=len(segmentation), _ARCHIVE_HASH=sha256(compressed).hexdigest(),
                _SEGMENTATION_HASH=sha256(segmentation).hexdigest(), _EMBEDDING_HASH=sha256(embedding).hexdigest(),
                SPEAKER_DOWNLOAD_BYTES=expected_bytes):
            def download(returned_embedding):
                def open_url(request, *, timeout):
                    return BytesIO(compressed if request.full_url.endswith('.tar.bz2') else returned_embedding)
                return open_url

            cancel = threading.Event()
            with self.assertRaisesRegex(ValueError, 'integrity'):
                audio_setup.install_speaker_models(directory, cancel, lambda *_: None,
                                                   open_url=download(b'x' * len(embedding)))
            self.assertEqual(list((Path(directory) / 'models').iterdir()), [])
            result = audio_setup.install_speaker_models(directory, cancel, lambda done, total: events.append((done, total)),
                                                        open_url=download(embedding))
            self.assertEqual((result / 'embedding.onnx').read_bytes(), embedding)
            self.assertEqual((result / 'segmentation.onnx').read_bytes(), segmentation)
            self.assertEqual(events[-1], (expected_bytes, expected_bytes))


if __name__ == '__main__':
    unittest.main()
