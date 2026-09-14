import base64
import json
from pathlib import Path
import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
from annie import macos_audio as audio


def pcm(value, frames=320):
    return np.full(frames, value, dtype='<i2').tobytes()


class MixerTests(unittest.TestCase):
    def test_simultaneous_sources_are_mixed_not_concatenated(self):
        mixer = audio.TimelineMixer(100, gain=0.8)
        mixer.push('mic', 100, pcm(1000))
        mixer.push('system', 100, pcm(2000))
        chunks = list(mixer.drain(100.021))
        self.assertEqual(len(chunks), 1)
        np.testing.assert_array_equal(np.frombuffer(chunks[0], '<i2'), np.full(320, 2400))

    def test_audio_spans_blocks_and_gaps_preserve_elapsed_time(self):
        mixer = audio.TimelineMixer(0)
        mixer.push('system', 0.01, pcm(700, 640))
        result = np.frombuffer(b''.join(mixer.drain(0.1)), '<i2')
        self.assertEqual(len(result), 1600)
        np.testing.assert_array_equal(result[:160], np.zeros(160))
        np.testing.assert_array_equal(result[160:800], np.full(640, 700))
        np.testing.assert_array_equal(result[800:], np.zeros(800))

    def test_mixer_saturates_instead_of_wrapping_int16(self):
        mixer = audio.TimelineMixer(0)
        mixer.push('mic', 0, pcm(30000))
        mixer.push('system', 0, pcm(30000))
        self.assertTrue(np.all(np.frombuffer(b''.join(mixer.drain(.021)), '<i2') == 32767))

    def test_small_callback_jitter_does_not_create_duplicate_audio(self):
        mixer = audio.TimelineMixer(0)
        mixer.push('mic', 0, pcm(100))
        mixer.push('mic', .022, pcm(200))
        samples = np.frombuffer(b''.join(mixer.drain(.041)), '<i2')
        self.assertTrue(np.all(samples[:320] == 100))
        self.assertTrue(np.all(samples[320:] == 200))

    def test_stalled_writer_and_future_packets_have_bounded_memory(self):
        mixer = audio.TimelineMixer(0)
        for second in range(1000):
            mixer.push('system', second, pcm(100, 16000))
        self.assertLessEqual(len(mixer.blocks), 100)
        self.assertLessEqual(len(list(mixer.drain(1000))), 100)
        self.assertGreater(mixer.lost, 0)

    def test_late_packets_cannot_rewrite_audio_already_delivered(self):
        mixer = audio.TimelineMixer(0)
        list(mixer.drain(1))
        mixer.push('mic', .01, pcm(100))
        self.assertFalse(mixer.blocks)
        self.assertGreater(mixer.lost, 0)


class ProtocolTests(unittest.TestCase):
    def test_packet_roundtrip_and_invalid_packets(self):
        value = {'type': 'pcm', 'time': 123.0, 'data': base64.b64encode(pcm(25)).decode()}
        self.assertEqual(audio.decode_packet(value), (123, pcm(25)))
        for update in ({'time': float('nan')}, {'data': '??'},
                       {'data': base64.b64encode(b'abc').decode()},
                       {'data': base64.b64encode(bytes(40000)).decode()}):
            with self.assertRaises(ValueError):
                audio.decode_packet({**value, **update})

    def test_native_helper_is_beside_frozen_worker(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/App/Contents/MacOS/LectureStudioWorker'):
            self.assertEqual(audio.helper_path(), Path('/App/Contents/MacOS/LectureAudioCapture'))

    def test_real_pipe_handshake_pcm_and_stop_cleanup(self):
        code = '''import json, sys, time, base64
print(json.dumps({'type':'ready','protocol':1,'rate':16000,'channels':1,'bits':16,'clock':time.monotonic()}),flush=True)
print(json.dumps({'type':'pcm','time':time.monotonic(),'data':base64.b64encode(bytes(640)).decode()}),flush=True)
sys.stdin.readline()
print(json.dumps({'type':'stopped'}),flush=True)
'''
        source = audio.SystemAudioSource([sys.executable, '-u', '-c', code])
        with source:
            self.assertTrue(source.wait_ready(threading.Event(), timeout=5))
            timestamp, data = source.packets.get(timeout=5)
            self.assertEqual(len(data), 640)
            self.assertLess(abs(timestamp - time.monotonic()), 2)
        self.assertEqual(source.proc.returncode, 0)
        self.assertFalse(source.reader.is_alive())

    def test_native_permission_error_is_visible_and_process_is_reaped(self):
        code = 'import json; print(json.dumps({"type":"error","text":"permission denied"}),flush=True)'
        source = audio.SystemAudioSource([sys.executable, '-u', '-c', code])
        with source:
            with self.assertRaisesRegex(RuntimeError, 'permission denied'):
                source.wait_ready(threading.Event(), timeout=5)
        self.assertIsNotNone(source.proc.returncode)

    def test_incompatible_format_is_not_treated_as_audio(self):
        code = 'import json; print(json.dumps({"type":"ready","protocol":1,"rate":48000,"channels":2,"bits":32}),flush=True)'
        with audio.SystemAudioSource([sys.executable, '-u', '-c', code]) as source:
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                source.wait_ready(threading.Event(), timeout=5)

    def test_cancellation_during_permission_wait_does_not_hang(self):
        code = 'import sys; sys.stdin.readline()'
        stop = threading.Event()
        stop.set()
        with audio.SystemAudioSource([sys.executable, '-u', '-c', code]) as source:
            self.assertFalse(source.wait_ready(stop, timeout=5))
        self.assertEqual(source.proc.returncode, 0)


class CaptureTests(unittest.TestCase):
    def test_native_rate_microphone_is_resampled_and_device_zero_is_preserved(self):
        from annie import config as cfg
        import sounddevice as sd
        stop = threading.Event()
        now = [100.0]
        output = []
        selected = []

        class Stream:
            active = True

            def __init__(self, **options):
                selected.append(options)
                self.options = options

            def __enter__(self):
                now[0] = 100.02
                self.options['callback'](pcm(1000, 960), 960,
                    types.SimpleNamespace(currentTime=1.02, inputBufferAdcTime=1.0),
                    types.SimpleNamespace(input_overflow=False))
                now[0] = 100.3
                stop.set()
                return self

            def __exit__(self, *_):
                self.active = False

        with patch.object(audio, 'microphone_permission', return_value=True), \
             patch.object(cfg, 'AUDIO_INPUT_DEVICE', 0), \
             patch.object(sd, 'query_devices', return_value={'default_samplerate': 48000}), \
             patch.object(sd, 'RawInputStream', Stream), patch.object(audio.time, 'monotonic', side_effect=lambda: now[0]):
            audio.capture_audio('default', stop, output.append)
        self.assertEqual(selected[0]['samplerate'], 48000)
        self.assertEqual(selected[0]['device'], 0)
        samples = np.frombuffer(b''.join(chunk for chunk in output if chunk is not None), '<i2')
        self.assertGreater(np.count_nonzero(samples), 300)
        self.assertLessEqual(np.count_nonzero(samples), 320)

    def test_permissions_are_requested_only_for_an_explicit_mic_capture(self):
        av = types.SimpleNamespace(AVMediaTypeAudio='audio', AVAuthorizationStatusAuthorized=3,
            AVAuthorizationStatusNotDetermined=0, AVCaptureDevice=Mock())
        av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 3
        with patch.dict(sys.modules, {'AVFoundation': av}):
            self.assertTrue(audio.microphone_permission(threading.Event()))
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()
        av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 2
        with patch.dict(sys.modules, {'AVFoundation': av}):
            with self.assertRaisesRegex(PermissionError, 'Microphone'):
                audio.microphone_permission(threading.Event())
        av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 0
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.side_effect = lambda _, callback: callback(True)
        with patch.dict(sys.modules, {'AVFoundation': av}):
            self.assertTrue(audio.microphone_permission(threading.Event()))

    def test_mac_runtime_routes_all_non_phone_sources_to_native_capture(self):
        from annie import whisper_runtime
        with patch.object(sys, 'platform', 'darwin'), patch.object(audio, 'capture_audio') as capture:
            for source in ('default', 'system', 'dual', '0'):
                stop, deliver = threading.Event(), Mock()
                whisper_runtime.capture_audio(source, stop, deliver)
                capture.assert_called_with(source, stop, deliver)

    def test_missing_helper_is_actionable_not_a_silent_mic_fallback(self):
        with patch.object(audio, 'helper_path', return_value=Path('/does-not-exist/annie-audio-helper')):
            with self.assertRaisesRegex(RuntimeError, 'helper is missing'):
                audio.check_helper()


if __name__ == '__main__':
    unittest.main()
