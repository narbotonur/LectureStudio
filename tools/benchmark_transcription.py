"""Measure a WAV on Local Whisper or explicitly selected Muse Voice.

Default fixture mode uses fake speech/model outputs and measures pipeline
integrity only. It makes no model-quality or hardware-speed claims.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(args):
    from annie.whisper_runtime import file_session, load_model, record_session
    events = []
    emit = lambda kind, **data: events.append((kind, data))
    started = time.monotonic()
    audio_seconds = None
    if args.audio:
        try:
            with wave.open(args.audio, 'rb') as audio:
                audio_seconds = audio.getnframes() / audio.getframerate()
        except (wave.Error, OSError):
            pass
        if args.backend == 'meta_voice':
            from annie.meta_voice import MetaVoiceBackend
            model = MetaVoiceBackend(language=args.language)
            device = 'Cloud'
        else:
            model, device = load_model(args.model)
        result = file_session({'file_path': args.audio, 'language': args.language}, model,
                              threading.Event(), emit, str)
        mode = 'real_audio'
    else:
        class FixtureModel:
            def transcribe(self, *unused, **kwargs):
                return [types.SimpleNamespace(text='Fixture transcript.', start=0, end=.4)], None
        def capture(device, stop, deliver):
            for _ in range(8):
                deliver(b'\xe8\x03' * 1024)
        with tempfile.TemporaryDirectory(prefix='studio-benchmark-audio-') as directory:
            result = record_session({'recording_path': str(Path(directory) / 'fixture.wav'), 'agc': False},
                                    FixtureModel(), threading.Event(), emit, str, capture=capture)
        device, mode = 'Fixture', 'offline_pipeline_fixture'
    segments = [d['segment'] for k, d in events if k == 'transcript_segment']
    diagnostics = {}
    if args.audio and args.backend == 'local':
        import ctranslate2
        diagnostics['cuda_devices'] = ctranslate2.get_cuda_device_count()
        if sys.platform == 'win32':
            import ctypes.util
            diagnostics['cuda_libraries'] = {name: bool(ctypes.util.find_library(name)) for name in
                                             ('cublasLt64_12.dll', 'cublas64_12.dll', 'cudnn64_9.dll')}
    print(json.dumps({'mode': mode, 'backend': args.backend if args.audio else 'fixture',
                      'device': device, 'elapsed_seconds': round(time.monotonic() - started, 3),
                      'audio_seconds': audio_seconds, 'diagnostics': diagnostics,
                      'segments': len(segments), 'result': result,
                      'metrics': [d for k, d in events if k == 'metrics'],
                      'note': ('Fixture mode verifies plumbing only, not speech recognition accuracy.'
                               if mode == 'offline_pipeline_fixture' else
                               'Single-file measurement; not a live microphone or classroom accuracy test.')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', help='An audio file you have permission to process; Meta needs PCM WAV.')
    parser.add_argument('--backend', choices=('local', 'meta_voice'), default='local')
    parser.add_argument('--model', default='small')
    parser.add_argument('--language', default='')
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='studio-benchmark-profile-') as profile:
        os.environ['ANNIE_DATA_DIR'] = profile
        run(options)
