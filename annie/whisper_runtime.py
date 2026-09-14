"""Whisper service runtime. Kept out of the Qt process."""
import gc
import json
from pathlib import Path
import queue
import sys
import threading
import time
import urllib.request
import wave

import numpy as np
import sounddevice as sd

from annie import config as cfg
from annie.dsp import AudioEnhancer
from annie.recording_audio import DiskAudioSpool, UtteranceSegmenter

_output_lock = threading.Lock()


class StreamingPCM16Resampler:
    """Convert streamed PCM16 audio to mono at a target sample rate."""

    def __init__(self, source_rate, channels=1, target_rate=16000):
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError('Audio sample rates must be positive')
        if channels <= 0:
            raise ValueError('Audio channel count must be positive')
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self.channels = int(channels)
        self._step = self.source_rate / self.target_rate
        self._next_output_position = 0.0
        self._source_samples = 0
        self._tail = np.empty(0, dtype=np.float32)

    def process(self, pcm):
        samples = np.frombuffer(pcm, dtype='<i2')
        complete = len(samples) - (len(samples) % self.channels)
        if not complete:
            return b''
        samples = samples[:complete].reshape(-1, self.channels)
        mono = samples.astype(np.float32).mean(axis=1)
        if self.source_rate == self.target_rate:
            return np.clip(mono, -32768, 32767).astype('<i2').tobytes()

        if self._tail.size:
            buffer = np.concatenate((self._tail, mono))
            buffer_start = self._source_samples - 1
        else:
            buffer = mono
            buffer_start = self._source_samples
        self._source_samples += len(mono)
        self._tail = mono[-1:].copy()

        last_position = self._source_samples - 1
        if len(buffer) < 2 or self._next_output_position >= last_position:
            return b''

        positions = np.arange(self._next_output_position, last_position, self._step)
        relative = positions - buffer_start
        indexes = relative.astype(np.int64)
        fractions = relative - indexes
        output = (buffer[indexes] * (1.0 - fractions)
                  + buffer[indexes + 1] * fractions)

        self._next_output_position = float(positions[-1] + self._step)
        return np.clip(np.rint(output), -32768, 32767).astype('<i2').tobytes()


def send(message):
    with _output_lock:
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
        sys.stdout.flush()


def load_model(name, report=None):
    from faster_whisper import WhisperModel
    import ctranslate2
    from annie.whisper_models import resolve_model
    report = report or (lambda text: None)
    # Resolve/download ONCE, outside the GPU fallback. Network failures must not
    # trigger another identical download disguised as a CPU retry.
    target = resolve_model(name, report)
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            if sys.platform == 'win32':
                # A GPU can be visible while the optional CUDA libraries are
                # absent. CTranslate2 otherwise fails only on first inference.
                import ctypes
                for library in ('cublasLt64_12.dll', 'cublas64_12.dll', 'cudnn64_9.dll'):
                    ctypes.WinDLL(library)
            report(f'Loading cached Whisper ({name}) into GPU memory; audio capture has not started')
            return WhisperModel(target, device='cuda', compute_type='float16', local_files_only=True), 'GPU'
    except Exception:
        report('GPU initialization unavailable; loading Whisper on CPU')
    report(f'Loading cached Whisper ({name}) into CPU memory; audio capture has not started')
    return WhisperModel(target, device='cpu', compute_type='int8', cpu_threads=4,
                        local_files_only=True), 'CPU'


class ModelCache:
    """Retain one model across sessions without accumulating models in VRAM."""
    def __init__(self, loader=None):
        self.loader = loader or load_model
        self._reports = loader is None
        self.name = None
        self.model = None
        self.device = None

    def get(self, name, report=None):
        reused = self.model is not None and name == self.name
        if not reused:
            self.model = None
            self.name = None
            self.device = None
            gc.collect()
            self.model, self.device = (self.loader(name, report=report) if self._reports else self.loader(name))
            self.name = name
        return self.model, self.device, reused


def capture_audio(device, stop, deliver):
    """Only acquisition; never model inference or disk writes in a callback."""
    device = str(device)
    from annie.platform_support import validate_audio_source
    validate_audio_source(device)
    if sys.platform == 'darwin' and device != 'phone':
        from annie.macos_audio import capture_audio as capture_mac
        return capture_mac(device, stop, deliver)
    if device in ('system', 'loopback', 'computer', 'dual', 'mix'):
        import soundcard as sc
        speaker = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
        with speaker.recorder(samplerate=16000, channels=1, blocksize=1024) as output:
            if device in ('dual', 'mix'):
                with sc.default_microphone().recorder(samplerate=16000, channels=1, blocksize=1024) as microphone:
                    while not stop.is_set():
                        samples = output.record(numframes=1024) * 0.9 + microphone.record(numframes=1024) * 0.9
                        deliver((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
            else:
                while not stop.is_set():
                    samples = output.record(numframes=1024)
                    deliver((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
        return
    if device == 'phone':
        url = f'http://{cfg.PHONE_IP}:{cfg.PHONE_PORT}/audio.wav'
        request = urllib.request.Request(url, headers={'User-Agent': 'Annie/5.0'})
        with urllib.request.urlopen(request, timeout=10) as response, wave.open(response, 'rb') as audio:
            source_rate = audio.getframerate()
            channels = audio.getnchannels()
            if audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
                raise ValueError('Phone audio must be uncompressed 16-bit PCM WAV')
            resampler = StreamingPCM16Resampler(source_rate, channels)
            while not stop.is_set():
                chunk = audio.readframes(4096)
                if not chunk:
                    break
                converted = resampler.process(chunk)
                if converted:
                    deliver(converted)
        return

    device_index = cfg.AUDIO_INPUT_DEVICE if device == 'default' else int(device)

    def callback(indata, frames, time_info, status):
        if getattr(status, 'input_overflow', False):
            deliver(None)  # Surface hardware loss rather than hiding it.
        if not stop.is_set():
            deliver(bytes(indata))

    # Use PortAudio's larger latency budget for long-running lecture capture.
    # A transcription workload can briefly saturate the machine; the callback
    # must have enough headroom to survive those scheduling stalls.
    with sd.RawInputStream(samplerate=16000, blocksize=1024, channels=1,
                           dtype='int16', device=device_index, callback=callback,
                           latency='high'):
        stop.wait()


def transcribe_phrase(model, pcm, prompt, clean_text, emit):
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.005:
        return
    audio = np.clip(audio * min(8.0, 0.75 / peak), -1, 1)
    started = time.monotonic()
    segments, _ = model.transcribe(
        audio, language=None, initial_prompt=prompt, vad_filter=True,
        vad_parameters={'min_silence_duration_ms': 400, 'speech_pad_ms': 200},
        no_speech_threshold=0.6, log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4, hallucination_silence_threshold=2.0,
        beam_size=1, condition_on_previous_text=False,
    )
    phrases = [clean_text(segment.text.strip()) for segment in segments]
    text = ' '.join(part for part in phrases if part)
    if text:
        emit('transcript', text=text)
    duration = len(audio) / 16000
    emit('metrics', inference_seconds=time.monotonic() - started, audio_seconds=duration)


def record_session(options, model, stop, emit, clean_text, capture=capture_audio):
    path = options['recording_path']
    spool = DiskAudioSpool(path)
    incoming = queue.Queue(maxsize=128)  # At most ~8 seconds/256 KiB of capture RAM.
    capture_done = threading.Event()
    capture_overflows = 0
    queue_drops = 0
    errors = []
    prompt = options.get('subject_context', '').strip() or None
    enhancer = AudioEnhancer() if options.get('agc', True) else None

    def deliver(data):
        nonlocal capture_overflows, queue_drops
        if data is None:
            # PortAudio reports that audio was lost before this callback.  It is
            # a gap, not a reason to throw away the remainder of the lecture.
            capture_overflows += 1
            return
        try:
            incoming.put_nowait(data)
        except queue.Full:
            # Disk writes normally outpace 32 KiB/s by orders of magnitude. If
            # the writer is briefly starved, lose one block rather than ending
            # the entire recording.
            queue_drops += 1

    def acquire():
        try:
            capture(options.get('device', 'default'), stop, deliver)
        except Exception as exc:
            errors.append(str(exc))
            emit('error', text=f'Audio capture failed: {exc}')
            stop.set()
        finally:
            capture_done.set()
            emit('capture_stopped')

    def write_recording():
        frames = 0
        try:
            while not capture_done.is_set() or not incoming.empty():
                try:
                    data = incoming.get(timeout=0.1)
                except queue.Empty:
                    continue
                spool.append(data)
                frames += 1
                if frames % 3 == 0:
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(samples ** 2) + 1e-6))
                    emit('level', rms=rms, is_hearing=rms > 12)
                if frames % 16 == 0:
                    emit('metrics', backlog_seconds=spool.backlog_seconds,
                         recorded_seconds=spool.duration_seconds,
                         audio_interruptions=capture_overflows + queue_drops)
        except Exception as exc:
            errors.append(str(exc))
            emit('error', text=f'Recording write failed: {exc}')
            stop.set()
        finally:
            try:
                spool.finish()
            except Exception as exc:
                errors.append(str(exc))
                emit('error', text=f'Recording finalization failed: {exc}')

    writer = threading.Thread(target=write_recording, name='lecture-writer')
    recorder = threading.Thread(target=acquire, name='lecture-capture')
    emit('recording_saved', path=str(spool.path))
    emit('status', text='Recording lecture...')
    writer.start()
    recorder.start()
    segmenter = UtteranceSegmenter()
    try:
        while True:
            raw = spool.read()
            if raw is None:
                break
            pcm = enhancer.process(raw) if enhancer else raw
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples ** 2) + 1e-6))
            phrase = segmenter.push(pcm, rms > 12)
            if phrase:
                transcribe_phrase(model, phrase, prompt, clean_text, emit)
                emit('metrics', backlog_seconds=spool.backlog_seconds)
        tail = segmenter.flush()
        if tail:
            transcribe_phrase(model, tail, prompt, clean_text, emit)
    finally:
        stop.set()
        recorder.join()
        writer.join()
        spool.close_reader()
    lost_chunks = capture_overflows + queue_drops
    warning = ''
    if lost_chunks:
        warning = (f'Recording continued with {lost_chunks} brief audio '
                   f'interruption(s); the rest of the lecture was preserved.')
        emit('warning', text=warning)
    return {'recording_path': str(spool.path), 'recorded_seconds': spool.duration_seconds,
            'lost_chunks': lost_chunks, 'capture_overflows': capture_overflows,
            'queue_drops': queue_drops, 'warning': warning,
            'had_error': bool(errors)}


def file_session(options, model, stop, emit, clean_text):
    path = options['file_path']
    segments, info = model.transcribe(path, beam_size=2, vad_filter=True,
                                      initial_prompt=options.get('subject_context') or None)
    for segment in segments:
        if stop.is_set():
            break
        text = clean_text(segment.text.strip())
        if text:
            start = f'{int(segment.start // 60):02d}:{int(segment.start % 60):02d}'
            end = f'{int(segment.end // 60):02d}:{int(segment.end % 60):02d}'
            emit('transcript', text=f'[{start} → {end}] {text}\n')
        emit('progress', percent=min(100, int(segment.end / max(info.duration, 1) * 100)))
    return {'cancelled': stop.is_set()}


def serve(clean_text, commands_input=None, cache=None):
    commands_input = commands_input if commands_input is not None else sys.stdin
    cache = cache if cache is not None else ModelCache()
    commands = queue.Queue()
    sessions = {}
    lock = threading.Lock()
    shutting_down = threading.Event()

    def read_commands():
        try:
            for line in commands_input:
                try:
                    command = json.loads(line)
                except ValueError:
                    continue
                action = command.get('action')
                session_id = command.get('session_id')
                with lock:
                    if action == 'start' and session_id:
                        event = threading.Event()
                        sessions[session_id] = event
                        commands.put((command, event))
                    elif action == 'stop' and session_id in sessions:
                        sessions[session_id].set()
                    elif action == 'shutdown':
                        break
        finally:
            shutting_down.set()
            with lock:
                for event in sessions.values():
                    event.set()
            commands.put(None)

    threading.Thread(target=read_commands, name='whisper-commands', daemon=True).start()
    while True:
        item = commands.get()
        if item is None:
            break
        options, stop = item
        cfg.load_settings()
        session_id = options['session_id']

        def emit(kind, **data):
            send({'session_id': session_id, 'type': kind, **data})

        result = {}
        model = None
        try:
            if stop.is_set():
                result['cancelled'] = True
                continue
            name = options.get('model_name', 'small')
            from annie.whisper_models import preparation_status
            with preparation_status(name, emit) as report:
                model, device, reused = cache.get(name, report=report)
            emit('status', text=f"Whisper ready [{device}] ({'reused' if reused else 'loaded'} {name})")
            if stop.is_set():
                result['cancelled'] = True
                continue
            if options.get('mode') == 'file':
                result = file_session(options, model, stop, emit, clean_text)
            else:
                result = record_session(options, model, stop, emit, clean_text)
            del model  # Cache alone owns the warm model between sessions.
        except Exception as exc:
            result['had_error'] = True
            emit('error', text=str(exc))
        finally:
            model = None
            emit('session_done', **result)
            with lock:
                sessions.pop(session_id, None)
        if shutting_down.is_set():
            break


def main(clean_text):
    if '--service' in sys.argv[1:]:
        serve(clean_text)
    else:
        print('Run this worker with --service; recordings are controlled by the Annie app.', file=sys.stderr)
        return 2
