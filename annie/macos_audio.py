"""Native Mac system audio + selected CoreAudio microphone, aligned to one timeline.

Only instantiated after an explicit recording request. All sources become mono
PCM16/16 kHz before entering Studio's existing disk spool and transcription path.
"""
import base64
from contextlib import ExitStack
import json
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import numpy as np

RATE = 16000
BLOCK = 320  # 20 ms output; a short jitter buffer aligns independently-clocked sources.


def helper_path():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).with_name('LectureAudioCapture')
    return Path(__file__).resolve().parents[1] / 'native/macos/bin/LectureAudioCapture'


def check_helper():
    path = helper_path()
    if not path.is_file():
        raise RuntimeError('The macOS audio helper is missing. Reinstall Lecture Studio, or '
                           'run python tools/build_macos_audio.py when launching from source.')
    return path


def decode_packet(message):
    if not isinstance(message, dict):
        raise ValueError('Invalid native audio message.')
    if message.get('type') != 'pcm':
        return None
    timestamp = float(message['time'])
    data = base64.b64decode(message['data'], validate=True)
    if not math.isfinite(timestamp) or not data or len(data) % 2 or len(data) > RATE * 2:
        raise ValueError('Invalid native PCM packet.')
    return timestamp, data


class TimelineMixer:
    """Bounded sample-index mixer; gaps are silence, simultaneous sources are added.

    Timestamp continuity smooths small callback jitter. Large discontinuities
    resynchronize instead of accumulating latency indefinitely.
    """
    def __init__(self, origin, gain=1.0, backlog_seconds=2):
        self.origin = origin
        self.gain = gain
        self.cursor = 0
        self.limit = int(backlog_seconds * RATE)
        self.blocks = {}
        self.next_frame = {}
        self.lost = 0

    def push(self, source, timestamp, data):
        samples = np.frombuffer(data, dtype='<i2').astype(np.float32)
        start = round((timestamp - self.origin) * RATE)
        expected = self.next_frame.get(source)
        if expected is not None and abs(start - expected) < RATE // 20:
            start = expected
        self.next_frame[source] = start + len(samples)
        left = max(start, self.cursor)
        right = min(start + len(samples), self.cursor + self.limit)
        if right <= left:
            self.lost += 1
            return
        if left > start or right < start + len(samples):
            self.lost += 1
        while left < right:
            block_start = (left // BLOCK) * BLOCK
            count = min(right - left, BLOCK - (left - block_start))
            buffer = self.blocks.setdefault(block_start, np.zeros(BLOCK, dtype=np.float32))
            offset = left - block_start
            buffer[offset:offset + count] += samples[left - start:left - start + count] * self.gain
            left += count

    def drain(self, until):
        end = max(0, int((until - self.origin) * RATE) // BLOCK * BLOCK)
        if end - self.cursor > self.limit:
            self.cursor = end - self.limit
            self.cursor = self.cursor // BLOCK * BLOCK
            self.blocks = {key: value for key, value in self.blocks.items() if key >= self.cursor}
            self.lost += 1
        while self.cursor < end:
            buffer = self.blocks.pop(self.cursor, None)
            self.cursor += BLOCK
            if buffer is None:
                yield bytes(BLOCK * 2)
            else:
                yield np.clip(np.rint(buffer), -32768, 32767).astype('<i2').tobytes()


class SystemAudioSource:
    def __init__(self, command=None):
        self.command = command or [str(check_helper()), '--capture']
        self.packets = queue.Queue(maxsize=128)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.clock_offset = 0.0
        self.started_at = None
        self.dropped = 0
        self.proc = None
        self.reader = None
        self.closing = False

    def __enter__(self):
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=64 * 1024)
        self.reader = threading.Thread(target=self._read, name='mac-system-audio', daemon=True)
        self.reader.start()
        return self

    def _read(self):
        try:
            for line in iter(lambda: self.proc.stdout.readline(128 * 1024), b''):
                if not line.endswith(b'\n'):
                    raise ValueError('Native audio protocol exceeded its message limit.')
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('Invalid native audio event.')
                kind = event.get('type')
                if kind == 'ready':
                    if self.ready.is_set() or (event.get('protocol'), event.get('rate'), event.get('channels'), event.get('bits')) != (1, RATE, 1, 16):
                        raise ValueError('Unsupported native audio protocol or format.')
                    clock = float(event['clock'])
                    if not math.isfinite(clock):
                        raise ValueError('Invalid native audio clock.')
                    self.started_at = time.monotonic()
                    self.clock_offset = self.started_at - clock
                    self.ready.set()
                elif kind == 'pcm':
                    if not self.ready.is_set():
                        raise ValueError('Native audio arrived before its format handshake.')
                    timestamp, data = decode_packet(event)
                    timestamp += self.clock_offset
                    if abs(timestamp - time.monotonic()) > 10:
                        raise ValueError('Native audio clock was discontinuous. Restart recording.')
                    try:
                        self.packets.put_nowait((timestamp, data))
                    except queue.Full:
                        self.dropped += 1
                elif kind == 'gap':
                    self.dropped += max(1, min(100000, int(event.get('count', 1))))
                elif kind == 'error':
                    self.error = str(event.get('text', 'System audio capture failed.'))[:2000]
                elif kind != 'stopped':
                    raise ValueError('Unknown native audio protocol message.')
        except Exception as exc:
            if not self.closing:
                self.error = f'System audio: {exc}'
        finally:
            self.done.set()

    def wait_ready(self, stop, timeout=90):
        deadline = time.monotonic() + timeout
        while not self.ready.wait(0.05):
            if stop.is_set():
                return False
            if self.done.is_set() or self.error:
                raise RuntimeError(self.error or 'The system-audio helper exited before capture started.')
            if time.monotonic() >= deadline:
                raise TimeoutError('Waiting for macOS recording permission timed out. Check Privacy & Security settings.')
        return not stop.is_set()

    def __exit__(self, *_):
        self.closing = True
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write(b'stop\n')
                    self.proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=2)
        finally:
            self.reader.join(timeout=2)
            self.proc.stdout.close()
            self.proc.stdin.close()


def microphone_permission(stop):
    import AVFoundation as av
    status = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeAudio)
    if status == av.AVAuthorizationStatusAuthorized:
        return True
    if status == av.AVAuthorizationStatusNotDetermined:
        finished = threading.Event()
        granted = []

        def completed(allowed):
            granted.append(bool(allowed))
            finished.set()

        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeAudio, completed)
        deadline = time.monotonic() + 90
        while not finished.wait(0.05):
            if stop.is_set():
                return False
            if time.monotonic() >= deadline:
                raise TimeoutError('Microphone permission timed out. Check System Settings > Privacy & Security > Microphone.')
        if granted and granted[0]:
            return not stop.is_set()
    raise PermissionError('Allow Lecture Studio in System Settings > Privacy & Security > Microphone, then restart Studio.')


def capture_audio(device, stop, deliver):
    from annie import config as cfg
    from annie.whisper_runtime import StreamingPCM16Resampler
    import sounddevice as sd

    if stop.is_set():
        return

    want_system = device in ('system', 'loopback', 'computer', 'dual', 'mix')
    want_mic = device not in ('system', 'loopback', 'computer')
    if want_mic and not microphone_permission(stop):
        return
    microphone = queue.Queue(maxsize=128)
    lost_mic = [0]
    with ExitStack() as stack:
        system = stack.enter_context(SystemAudioSource()) if want_system else None
        if system and not system.wait_ready(stop):
            return
        origin = system.started_at if system else time.monotonic()
        mixer = TimelineMixer(origin, gain=0.8 if want_system and want_mic else 1.0)
        resampler = None
        mic_stream = None
        last_mic = [time.monotonic()]
        if want_mic:
            index = cfg.AUDIO_INPUT_DEVICE if device in ('default', 'dual', 'mix') else int(device)
            info = sd.query_devices(index, 'input')
            rate = int(info['default_samplerate'])
            resampler = StreamingPCM16Resampler(rate)

            def callback(indata, frames, timing, status):
                if status.input_overflow:
                    lost_mic[0] += 1
                if stop.is_set():
                    return
                now = time.monotonic()
                last_mic[0] = now
                age = float(timing.currentTime - timing.inputBufferAdcTime)
                timestamp = now - age if math.isfinite(age) and 0 <= age < 5 else now - frames / rate
                try:
                    microphone.put_nowait((timestamp, bytes(indata)))
                except queue.Full:
                    lost_mic[0] += 1

            mic_stream = stack.enter_context(sd.RawInputStream(samplerate=rate, blocksize=max(1, round(rate * 0.02)),
                                channels=1, dtype='int16', device=index, callback=callback, latency='high'))

        reported = 0

        def drain_sources():
            for name, packets in (('system', system.packets if system else None), ('mic', microphone)):
                if packets is None:
                    continue
                # Bound each pass so continuous capture cannot starve Stop.
                for _ in range(128):
                    try:
                        timestamp, data = packets.get_nowait()
                    except queue.Empty:
                        break
                    if name == 'mic':
                        data = resampler.process(data)
                    if data:
                        mixer.push(name, timestamp, data)

        try:
            while not stop.is_set():
                drain_sources()
                for data in mixer.drain(time.monotonic() - 0.2):
                    deliver(data)
                losses = lost_mic[0] + (system.dropped if system else 0) + mixer.lost
                if losses > reported:
                    deliver(None)
                    reported = losses
                if system and (system.error or system.done.is_set()):
                    raise RuntimeError(system.error or 'The system-audio helper stopped unexpectedly.')
                if mic_stream and (not mic_stream.active or time.monotonic() - last_mic[0] > 5):
                    raise RuntimeError('The microphone stopped delivering audio. Check the selected input device.')
                stop.wait(0.01)
        finally:
            # Flush queued audio and the jitter buffer into the recoverable WAV.
            ended_at = time.monotonic()
            stack.close()
            drain_sources()
            for data in mixer.drain(ended_at):
                deliver(data)
