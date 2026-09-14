"""Bounded handoff buffers for PortAudio callbacks and the live event loop."""
import asyncio
from collections import deque
import threading
import time


class AudioInputBuffer:
    """Receive audio on a device thread; consume it on one asyncio loop.

    Notifications are coalesced so a stalled event loop cannot accumulate an
    unlimited number of callbacks. On overflow, retain the most recent audio.
    """

    def __init__(self, loop, max_chunks=4):
        if max_chunks < 1:
            raise ValueError('max_chunks must be positive')
        self._loop = loop
        self._max_chunks = max_chunks
        self._chunks = deque()
        self._lock = threading.Lock()
        self._ready = asyncio.Event()
        self._notification_pending = False
        self._closed = False
        self.dropped_chunks = 0

    def _notify(self):
        with self._lock:
            self._notification_pending = False
        self._ready.set()

    def _schedule_notification(self):
        with self._lock:
            if self._notification_pending:
                return
            self._notification_pending = True
        try:
            self._loop.call_soon_threadsafe(self._notify)
        except RuntimeError:
            # The device may deliver its final callback after loop shutdown.
            with self._lock:
                self._notification_pending = False

    def put(self, data):
        with self._lock:
            if self._closed:
                return
            if len(self._chunks) == self._max_chunks:
                self._chunks.popleft()
                self.dropped_chunks += 1
            self._chunks.append(data)
        self._schedule_notification()

    async def get(self):
        while True:
            self._ready.clear()
            with self._lock:
                if self._chunks:
                    return self._chunks.popleft()
                if self._closed:
                    raise EOFError('Audio input closed')
            await self._ready.wait()

    def clear(self):
        with self._lock:
            self._chunks.clear()

    def close(self):
        with self._lock:
            self._closed = True
            self._chunks.clear()
        self._schedule_notification()


class PCMPlaybackBuffer:
    """Ordered PCM playback, lossless by default with optional startup buffering.

    Generated speech may arrive faster than realtime. Dropping older samples to
    limit latency corrupts words, so only explicitly bounded callers drop audio.
    """

    def __init__(self, max_bytes=None, prebuffer_seconds=0.0, bytes_per_second=48000):
        if max_bytes is not None and (max_bytes < 2 or max_bytes % 2):
            raise ValueError('max_bytes must be a positive number of int16 samples')
        if prebuffer_seconds < 0 or bytes_per_second <= 0:
            raise ValueError('Invalid playback timing')
        self._max_bytes = max_bytes
        self._prebuffer_seconds = prebuffer_seconds
        self._prebuffer_bytes = int(prebuffer_seconds * bytes_per_second)
        self._buffering_since = None
        self._chunks = deque()
        self._size = 0
        self._lock = threading.Lock()
        self.dropped_bytes = 0

    @property
    def queued_bytes(self):
        with self._lock:
            return self._size

    def put(self, data):
        if not data:
            return
        if len(data) % 2:
            raise ValueError('PCM data must contain complete int16 samples')
        with self._lock:
            if self._size == 0:
                self._buffering_since = time.monotonic()
            if self._max_bytes is not None and len(data) > self._max_bytes:
                self.dropped_bytes += len(data) - self._max_bytes
                data = data[-self._max_bytes:]
            self._chunks.append(memoryview(bytes(data)))
            self._size += len(data)
            excess = max(0, self._size - self._max_bytes) if self._max_bytes is not None else 0
            self.dropped_bytes += excess
            self._discard(excess)

    def _discard(self, count):
        while count:
            chunk = self._chunks.popleft()
            consumed = min(count, len(chunk))
            if consumed < len(chunk):
                self._chunks.appendleft(chunk[consumed:])
            self._size -= consumed
            count -= consumed

    def fill(self, output):
        target = memoryview(output).cast('B')
        target[:] = bytes(len(target))
        offset = 0
        with self._lock:
            if self._buffering_since is not None:
                if (self._size < self._prebuffer_bytes
                        and time.monotonic() - self._buffering_since < self._prebuffer_seconds):
                    return
                self._buffering_since = None
            while self._chunks and offset < len(target):
                chunk = self._chunks.popleft()
                count = min(len(chunk), len(target) - offset)
                target[offset:offset + count] = chunk[:count]
                if count < len(chunk):
                    self._chunks.appendleft(chunk[count:])
                self._size -= count
                offset += count

    def clear(self):
        with self._lock:
            self._chunks.clear()
            self._size = 0
            self._buffering_since = None
