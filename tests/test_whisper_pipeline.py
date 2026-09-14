import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from annie.recording_audio import DiskAudioSpool, UtteranceSegmenter
from annie.whisper_events import consume_session
from annie.whisper_runtime import ModelCache, StreamingPCM16Resampler, record_session
from annie.whisper_service import WhisperService


class SpoolTests(unittest.TestCase):
    def test_audio_backlog_lives_on_disk_and_final_wav_is_readable(self):
        import wave
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            spool = DiskAudioSpool(path)
            pcm = b'\xe8\x03' * 16000
            spool.append(pcm)
            self.assertEqual(spool.backlog_seconds, 1)
            spool.finish()
            self.assertEqual(spool.read(32000), pcm)
            self.assertIsNone(spool.read())
            self.assertEqual(spool.backlog_seconds, 0)
            spool.close_reader()
            with wave.open(str(path)) as saved:
                self.assertEqual(saved.getframerate(), 16000)
                self.assertEqual(saved.getnchannels(), 1)
                self.assertEqual(saved.getnframes(), 16000)
                self.assertEqual(saved.readframes(16000), pcm)

    def test_reader_waits_for_capture_and_wakes_on_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = DiskAudioSpool(Path(directory) / 'lecture.wav')
            received = []
            reader = threading.Thread(target=lambda: received.append(spool.read()))
            reader.start()
            spool.append(b'abcd')
            reader.join(timeout=1)
            self.assertEqual(received, [b'abcd'])
            waiter = threading.Thread(target=lambda: received.append(spool.read()))
            waiter.start()
            spool.finish()
            waiter.join(timeout=1)
            self.assertEqual(received[-1], None)
            spool.close_reader()

    def test_does_not_overwrite_an_existing_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            path.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                DiskAudioSpool(path)
            self.assertEqual(path.read_bytes(), b'keep')


class PipelineTests(unittest.TestCase):
    def test_phone_pcm_resampler_converts_44100_hz_to_16000_hz(self):
        import numpy as np

        converter = StreamingPCM16Resampler(44100, channels=1)
        source = np.full(44100, 1234, dtype=np.int16)
        parts = []
        for start in range(0, len(source), 997):
            parts.append(converter.process(source[start:start + 997].tobytes()))
        output = np.frombuffer(b''.join(parts), dtype=np.int16)

        self.assertIn(len(output), (15999, 16000))
        self.assertTrue(np.all(output == 1234))

    def test_phone_pcm_resampler_downmixes_stereo(self):
        import numpy as np

        converter = StreamingPCM16Resampler(16000, channels=2)
        stereo = np.array([[1000, 3000], [-3000, -1000]], dtype=np.int16)
        output = np.frombuffer(converter.process(stereo.tobytes()), dtype=np.int16)
        np.testing.assert_array_equal(output, np.array([2000, -2000], dtype=np.int16))

    def test_capture_failure_preserves_and_transcribes_audio_already_received(self):
        def capture(device, stop, deliver):
            for _ in range(8):
                deliver(b'\xe8\x03' * 1024)
            raise OSError('test device disconnected')

        class Model:
            def transcribe(self, *args, **kwargs):
                return [types.SimpleNamespace(text='saved tail')], None

        events = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            result = record_session({'recording_path': str(path), 'agc': False},
                                    Model(), threading.Event(),
                                    lambda kind, **data: events.append((kind, data)),
                                    lambda text: text, capture=capture)
            self.assertTrue(result['had_error'])
            self.assertEqual(path.stat().st_size, 44 + 8 * 2048)
            self.assertIn(('transcript', {'text': 'saved tail'}), events)

    def test_single_input_overflow_warns_and_keeps_recording(self):
        import wave

        speech = b'\xe8\x03' * 1024

        def capture(device, stop, deliver):
            for _ in range(4):
                deliver(speech)
            deliver(None)  # PortAudio input-overflow status.
            self.assertFalse(stop.is_set())
            for _ in range(4):
                deliver(speech)

        class Model:
            def transcribe(self, *args, **kwargs):
                return [types.SimpleNamespace(text='lecture continued')], None

        events = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            result = record_session({'recording_path': str(path), 'agc': False},
                                    Model(), threading.Event(),
                                    lambda kind, **data: events.append((kind, data)),
                                    lambda text: text, capture=capture)
            self.assertFalse(result['had_error'])
            self.assertEqual(result['capture_overflows'], 1)
            self.assertEqual(result['lost_chunks'], 1)
            self.assertTrue(any(kind == 'warning' for kind, _ in events))
            with wave.open(str(path)) as saved:
                self.assertEqual(saved.getnframes(), 8 * 1024)

    def test_disk_failure_stops_capture_and_does_not_hang_reader(self):
        def capture(device, stop, deliver):
            for _ in range(8):
                if stop.is_set():
                    break
                deliver(bytes(2048))

        events = []
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(DiskAudioSpool, 'append', side_effect=OSError('test disk full')):
            result = record_session({'recording_path': str(Path(directory) / 'lecture.wav')},
                                    object(), threading.Event(),
                                    lambda kind, **data: events.append((kind, data)),
                                    lambda text: text, capture=capture)
        self.assertTrue(result['had_error'])
        self.assertTrue(any(kind == 'error' and 'disk full' in data['text'] for kind, data in events))

    def test_inference_failure_closes_capture_and_finalizes_saved_wav(self):
        import wave

        def capture(device, stop, deliver):
            for _ in range(8):
                deliver(b'\xe8\x03' * 1024)

        class Model:
            def transcribe(self, *args, **kwargs):
                raise RuntimeError('test inference failure')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            with self.assertRaisesRegex(RuntimeError, 'test inference failure'):
                record_session({'recording_path': str(path), 'agc': False}, Model(),
                               threading.Event(), lambda *args, **kwargs: None,
                               lambda text: text, capture=capture)
            with wave.open(str(path)) as saved:
                self.assertEqual(saved.getnframes(), 8 * 1024)

    def test_stop_flushes_tail_while_slow_inference_does_not_block_capture(self):
        import wave
        speech = b'\xe8\x03' * 1024
        chunks = [speech] * 8 + [bytes(2048)] * 7 + [speech] * 8
        stop = threading.Event()
        captured = threading.Event()
        inference_observations = []
        events = []

        def capture(device, stopping, deliver):
            for chunk in chunks:
                deliver(chunk)
                time.sleep(0.001)
            stopping.set()  # Stop without the silence needed for ordinary flush.
            captured.set()

        class SlowModel:
            def transcribe(self, audio, **kwargs):
                def segments():
                    # Capture must be able to finish while inference is waiting.
                    inference_observations.append(captured.wait(timeout=1))
                    yield types.SimpleNamespace(text='preserved speech')
                return segments(), None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            result = record_session({'recording_path': str(path), 'agc': False},
                                    SlowModel(), stop,
                                    lambda kind, **data: events.append((kind, data)),
                                    lambda text: text, capture=capture)
            self.assertEqual(inference_observations, [True, True])
            transcripts = [data['text'] for kind, data in events if kind == 'transcript']
            self.assertEqual(transcripts, ['preserved speech', 'preserved speech'])
            self.assertEqual(result['lost_chunks'], 0)
            self.assertFalse(result['had_error'])
            with wave.open(str(path)) as saved:
                self.assertEqual(saved.getnframes(), len(chunks) * 1024)
                self.assertEqual(saved.readframes(saved.getnframes()), b''.join(chunks))

    def test_end_of_recording_flushes_short_word_only_once(self):
        segmenter = UtteranceSegmenter()
        for _ in range(8):
            self.assertIsNone(segmenter.push(b'ab' * 1024, True))
        self.assertEqual(len(segmenter.flush()), 8 * 2048)
        self.assertIsNone(segmenter.flush())

    def test_model_cache_reuses_same_model_and_releases_old_selection(self):
        loads = []

        def load(name):
            model = object()
            loads.append((name, model))
            return model, 'CPU'

        cache = ModelCache(load)
        first, _, reused = cache.get('small')
        self.assertFalse(reused)
        second, _, reused = cache.get('small')
        self.assertTrue(reused)
        self.assertIs(first, second)
        third, _, reused = cache.get('large-v3-turbo')
        self.assertFalse(reused)
        self.assertIsNot(first, third)
        self.assertEqual(len(loads), 2)


FIXTURE = r'''
import json,sys
loaded = set()
active = None
def send(kind, **data):
    print(json.dumps({'session_id': active, 'type': kind, **data}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    if command['action'] == 'start':
        active = command['session_id']
        model = command.get('model_name', 'small')
        reused = model in loaded
        loaded.add(model)
        send('status', text='reused' if reused else 'loaded')
        send('transcript', text='первая phrase →')
    elif command['action'] == 'stop':
        send('transcript', text='final phrase')
        send('session_done')
        active = None
    elif command['action'] == 'shutdown':
        break
'''


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        script = Path(self.directory.name) / 'fake_whisper.py'
        script.write_text(FIXTURE, encoding='utf-8')
        self.service = WhisperService([sys.executable, '-u', str(script)])

    def tearDown(self):
        self.service.shutdown()
        if self.service._proc:
            try:
                self.service._proc.wait(timeout=3)
            finally:
                self.service._terminate_if_alive(self.service._proc)
        if self.service._shutdown_timer:
            self.service._shutdown_timer.cancel()
        self.directory.cleanup()

    def test_process_reused_and_sessions_are_isolated(self):
        first, events = self.service.start(model_name='small')
        proc = self.service._proc
        self.assertEqual(events.get(timeout=2)['text'], 'loaded')
        self.assertEqual(events.get(timeout=2)['text'], 'первая phrase →')
        with self.assertRaises(RuntimeError):
            self.service.start(model_name='small')
        self.service.stop(first)
        self.assertEqual(events.get(timeout=2)['text'], 'final phrase')
        self.assertEqual(events.get(timeout=2)['type'], 'session_done')
        self.service.release(first)
        second, events = self.service.start(model_name='small')
        self.assertNotEqual(first, second)
        self.assertIs(self.service._proc, proc)
        self.assertEqual(events.get(timeout=2)['text'], 'reused')
        self.service.stop(second)
        while events.get(timeout=2)['type'] != 'session_done':
            pass
        self.service.release(second)

    def test_parent_drains_final_transcript_after_stop_flag(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, message):
                self.messages.append(message)

        worker = types.SimpleNamespace(
            _service=self.service, _session_id=None, _running=True,
            full_transcript=[], last_metrics={}, last_error='',
            status_changed=Signal(), transcript_updated=Signal(),
        )
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(consume_session(worker, mode='record')))
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while not worker.full_transcript and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(worker.full_transcript, ['первая phrase → '])
            worker._running = False
            self.service.stop(worker._session_id)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worker.full_transcript, ['первая phrase → ', 'final phrase '])
            self.assertEqual(outcome[0]['type'], 'session_done')
        finally:
            self.service.shutdown()
            thread.join(timeout=2)

    def test_child_exit_is_reported_to_active_session(self):
        session_id, events = self.service.start()
        self.service._proc.terminate()
        while True:
            event = events.get(timeout=2)
            if event['type'] == 'process_exit':
                self.assertEqual(event['session_id'], session_id)
                break
        self.service.release(session_id)


if __name__ == '__main__':
    unittest.main()
