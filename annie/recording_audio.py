"""Disk-backed lecture audio and bounded utterance segmentation."""
from collections import deque
from pathlib import Path
import struct
import threading
import time


class DiskAudioSpool:
    """One capture writer and one transcription reader, with a valid WAV file.

    Inference can lag without retaining the recording in RAM. The WAV header is
    checkpointed every second and finalized when acquisition stops.
    """

    sample_rate = 16000
    bytes_per_second = sample_rate * 2

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = self.path.open('xb', buffering=0)
        self._written = 0
        self._read = 0
        self._closed = False
        self._condition = threading.Condition()
        self._checkpoint = time.monotonic()
        self._write_header()
        self._reader = self.path.open('rb', buffering=0)

    def _write_header(self):
        header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + self._written,
                             b'WAVE', b'fmt ', 16, 1, 1, self.sample_rate,
                             self.bytes_per_second, 2, 16, b'data', self._written)
        self._writer.seek(0)
        self._writer.write(header)
        self._writer.seek(44 + self._written)

    @property
    def backlog_seconds(self):
        with self._condition:
            return (self._written - self._read) / self.bytes_per_second

    @property
    def duration_seconds(self):
        with self._condition:
            return self._written / self.bytes_per_second

    def append(self, data):
        if len(data) % 2:
            raise ValueError('Incomplete int16 audio sample')
        if self._closed:
            raise RuntimeError('Recording has already finished')
        if self._written + len(data) > 0xFFFFFFFF - 36:
            raise RuntimeError('Recording exceeds WAV size limit')
        # Only the writer thread touches this handle. Never called in PortAudio.
        view = memoryview(data)
        while view:
            count = self._writer.write(view)
            if not count:
                raise OSError('Could not write recording audio')
            view = view[count:]
        with self._condition:
            self._written += len(data)
            self._condition.notify_all()
        if time.monotonic() - self._checkpoint >= 1:
            self._write_header()
            self._checkpoint = time.monotonic()

    def read(self, size=2048):
        if size < 2 or size % 2:
            raise ValueError('Read size must contain complete int16 samples')
        with self._condition:
            self._condition.wait_for(lambda: self._read < self._written or self._closed)
            if self._read >= self._written:
                return None
            count = min(size, self._written - self._read)
            offset = self._read
        self._reader.seek(44 + offset)
        data = self._reader.read(count)
        if len(data) != count:
            raise OSError('Incomplete audio read from recording file')
        with self._condition:
            self._read += count
        return data

    def finish(self):
        if self._closed:
            return
        try:
            self._write_header()
        finally:
            self._writer.close()
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    def close_reader(self):
        self._reader.close()


class UtteranceSegmenter:
    """Finish on silence or a hard duration limit, including short words."""

    def __init__(self, max_samples=144000, silence_frames=7, min_speech_frames=3):
        self.max_samples = max_samples
        self.silence_frames = silence_frames
        self.min_speech_frames = min_speech_frames
        self._pre = deque(maxlen=6)
        self._chunks = []
        self._samples = 0
        self._speech = 0
        self._silence = 0

    @property
    def buffered_samples(self):
        return self._samples

    def push(self, pcm, is_speech):
        if not self._chunks and not is_speech:
            self._pre.append(pcm)
            return None
        if not self._chunks:
            self._chunks.extend(self._pre)
            self._samples = sum(len(chunk) // 2 for chunk in self._pre)
            self._pre.clear()
        self._chunks.append(pcm)
        self._samples += len(pcm) // 2
        if is_speech:
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self.silence_frames or self._samples >= self.max_samples:
            return self.flush()
        return None

    def flush(self):
        result = b''.join(self._chunks) if self._speech >= self.min_speech_frames else None
        self._chunks.clear()
        self._samples = self._speech = self._silence = 0
        self._pre.clear()
        return result
