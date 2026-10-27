import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import wave

from annie.meta_voice import MetaVoiceBackend, VoiceTurns, VoiceUnavailable, transcribe_file
from annie.recording_audio import DiskAudioSpool, UtteranceSegmenter
from annie.transcription import TranscriptSegment
from annie.whisper_runtime import record_session, transcribe_phrase


class TranscriptContractTests(unittest.TestCase):
    def test_segment_identity_and_invalid_timing(self):
        a = TranscriptSegment.create(2, 3, ' hello ', 'lecture.wav')
        self.assertEqual(a, TranscriptSegment.create(2, 3, 'hello', 'lecture.wav'))
        for start, end in ((-1, 2), (3, 2), (float('nan'), 3)):
            with self.assertRaises(ValueError):
                TranscriptSegment.create(start, end, 'hello', 'lecture.wav')

    def test_segmenter_times_include_silence_and_pre_roll(self):
        segmenter = UtteranceSegmenter(max_samples=16000)
        silence = bytes(2048)
        speech = b'\xe8\x03' * 1024
        for _ in range(10):
            segmenter.push(silence, False)
        for _ in range(8):
            segmenter.push(speech, True)
        chunk = segmenter.flush()
        self.assertEqual(segmenter.last_start_sample, 4 * 1024)
        self.assertEqual(segmenter.last_end_sample, 18 * 1024)
        self.assertEqual(len(chunk) // 2, 14 * 1024)

    def test_local_timestamps_include_utterance_offset_and_language(self):
        model = Mock()
        model.transcribe.return_value = ([types.SimpleNamespace(text='Exam tomorrow', start=.1, end=.9)], None)
        events = []
        transcribe_phrase(model, b'\xe8\x03' * 16000, None, str,
                          lambda kind, **data: events.append((kind, data)),
                          offset=12, source='lecture.wav', language='en')
        segment = next(data['segment'] for kind, data in events if kind == 'transcript_segment')
        self.assertEqual((segment['start'], segment['end']), (12.1, 12.9))
        self.assertEqual(model.transcribe.call_args.kwargs['language'], 'en')
        self.assertTrue(any(kind == 'metrics' and 'real_time_factor' in data for kind, data in events))


class VoiceEventTests(unittest.TestCase):
    def test_stream_handshake_binary_pcm_and_half_close_are_documented_protocol(self):
        class NormalClose(Exception):
            rcvd = types.SimpleNamespace(code=1000)

        class Socket:
            def __init__(self):
                self.sent = []
                self.messages = [{'sessionId': 'fixture-session'},
                                 {'type': 'speechStart', 'turnId': 1, 'audioProcessedMs': 0},
                                 {'type': 'transcript', 'transcript': 'hello'},
                                 {'type': 'speechEnd', 'turnId': 1, 'audioProcessedMs': 64},
                                 {'type': 'speechComplete', 'turnId': 1, 'transcript': 'Hello.', 'audioProcessedMs': 64}]
                self.finished = threading.Event()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def send(self, message):
                self.sent.append(message)
                if isinstance(message, str) and json.loads(message).get('type') == 'endStream':
                    self.finished.set()

            def recv(self, timeout):
                if self.messages:
                    return json.dumps(self.messages.pop(0))
                if self.finished.wait(timeout):
                    raise NormalClose()
                raise TimeoutError()

            def close(self):
                pass

        socket = Socket()
        connector = Mock(return_value=socket)
        events = []
        with tempfile.TemporaryDirectory() as directory:
            spool = DiskAudioSpool(Path(directory) / 'lecture.wav')
            pcm = b'\xe8\x03' * 1024
            spool.append(pcm)
            spool.finish()
            backend = MetaVoiceBackend(api_key='fixture-key', connector=connector)
            backend.stream(spool, lambda kind, **data: events.append((kind, data)), 'lecture.wav')
            spool.close_reader()
        self.assertTrue(connector.call_args.args[0].startswith('wss://api.meta.ai/v1/asr/realtime?sessionId='))
        handshake = json.loads(socket.sent[0])
        self.assertEqual(handshake['authorization']['accessToken'], 'Bearer fixture-key')
        self.assertEqual(handshake['audioEncoding'], 'PCM_16KHZ')
        self.assertEqual(handshake['mode'], 'ENDPOINTING')
        self.assertEqual(socket.sent[1], pcm)
        self.assertEqual(json.loads(socket.sent[-1]), {'type': 'endStream'})
        self.assertEqual([d['text'] for k, d in events if k == 'transcript'], ['Hello.'])

    def test_cumulative_partials_and_out_of_order_finalization(self):
        events = []
        state = VoiceTurns(lambda kind, **data: events.append((kind, data)), 'lecture.wav', offset=60)
        for item in (
            {'type': 'speechStart', 'turnId': 1, 'audioProcessedMs': 100},
            {'type': 'transcript', 'transcript': 'first'},
            {'type': 'transcript', 'transcript': 'revised first'},
            {'type': 'speechEnd', 'turnId': 1, 'audioProcessedMs': 900},
            {'type': 'speechStart', 'turnId': 2, 'audioProcessedMs': 1000},
            {'type': 'speechEnd', 'turnId': 2, 'audioProcessedMs': 1900},
            {'type': 'speechComplete', 'turnId': 2, 'transcript': 'Second.', 'audioProcessedMs': 2100},
        ):
            state.handle(item)
        self.assertFalse(any(kind == 'transcript' for kind, _ in events))
        self.assertEqual(state.committed_seconds, 60)
        state.handle({'type': 'speechComplete', 'turnId': 1, 'transcript': 'First.', 'audioProcessedMs': 2400})
        state.handle({'type': 'speechComplete', 'turnId': 1, 'transcript': 'First.', 'audioProcessedMs': 2400})
        self.assertEqual([d['text'] for k, d in events if k == 'transcript'], ['First.', 'Second.'])
        self.assertEqual(state.committed_seconds, 61.9)
        segments = [d['segment'] for k, d in events if k == 'transcript_segment']
        self.assertEqual((segments[0]['start'], segments[0]['end']), (60.1, 60.9))

    def test_undocumented_languages_use_local_instead(self):
        for lang in ('ru', 'Russian', 'kk', 'Kazakh'):
            with self.assertRaisesRegex(VoiceUnavailable, 'not documented'):
                MetaVoiceBackend(api_key='test', language=lang)
        self.assertEqual(MetaVoiceBackend(api_key='test', language='en').language, 'English')

    def test_cloud_failure_rewinds_saved_audio_for_local_fallback(self):
        class FailedCloud:
            name = 'meta_voice'
            committed_seconds = 0

            def stream(self, spool, emit, source):
                spool.read()
                raise VoiceUnavailable('offline')

        def capture(device, stop, deliver):
            for _ in range(8):
                deliver(b'\xe8\x03' * 1024)

        model = Mock()
        model.transcribe.return_value = ([types.SimpleNamespace(text='Recovered.', start=0, end=.4)], None)
        events = []
        with tempfile.TemporaryDirectory() as directory, patch('annie.whisper_runtime.load_model', return_value=(model, 'CPU')):
            path = Path(directory) / 'lecture.wav'
            result = record_session({'recording_path': str(path), 'agc': False}, FailedCloud(),
                                    threading.Event(), lambda kind, **data: events.append((kind, data)),
                                    str, capture=capture)
            self.assertFalse(result['had_error'])
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), 8 * 1024)
        self.assertEqual([d['text'] for k, d in events if k == 'transcript'], ['Recovered.'])
        self.assertTrue(any(k == 'warning' for k, _ in events))

    def test_file_endpoint_uses_wav_multipart_and_final_turn_timing(self):
        events = []
        response = Mock()
        response.json.return_value = {'turns': [{'turnId': 1, 'startMs': 10, 'endMs': 100, 'transcript': 'Exam Friday.'}]}
        request = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lecture.wav'
            with wave.open(str(path), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(bytes(3200))
            result = transcribe_file(path, MetaVoiceBackend(api_key='test-key'), threading.Event(),
                                     lambda kind, **data: events.append((kind, data)), request=request)
        self.assertFalse(result['cancelled'])
        settings = json.loads(request.call_args.kwargs['files']['request'][1])
        self.assertEqual(settings['mode'], 'ENDPOINTING')
        self.assertEqual(request.call_args.args[0], 'https://api.meta.ai/v1/asr/transcribe')
        self.assertEqual(request.call_args.kwargs['files']['audio'][1][:4], b'RIFF')
        segment = next(d['segment'] for k, d in events if k == 'transcript_segment')
        self.assertEqual((segment['start'], segment['end']), (.01, .1))


if __name__ == '__main__':
    unittest.main()
