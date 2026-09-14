import asyncio
import threading
import unittest

from annie.audio_io import AudioInputBuffer, PCMPlaybackBuffer


class InputTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_thread_wakes_waiter(self):
        buffer = AudioInputBuffer(asyncio.get_running_loop())
        waiting = asyncio.create_task(buffer.get())
        await asyncio.sleep(0)
        thread = threading.Thread(target=lambda: buffer.put(b'pcm'))
        thread.start()
        thread.join()
        self.assertEqual(await asyncio.wait_for(waiting, 0.5), b'pcm')

    async def test_overflow_keeps_recent_chunks_and_counts_loss(self):
        buffer = AudioInputBuffer(asyncio.get_running_loop(), max_chunks=2)
        for value in [b'old', b'new', b'newest']:
            buffer.put(value)
        self.assertEqual(buffer.dropped_chunks, 1)
        self.assertEqual(await buffer.get(), b'new')
        self.assertEqual(await buffer.get(), b'newest')

    async def test_close_wakes_empty_waiter_and_rejects_late_audio(self):
        buffer = AudioInputBuffer(asyncio.get_running_loop())
        waiting = asyncio.create_task(buffer.get())
        await asyncio.sleep(0)
        buffer.close()
        buffer.put(b'late')
        with self.assertRaises(EOFError):
            await asyncio.wait_for(waiting, 0.5)

    async def test_capture_flood_coalesces_loop_notifications(self):
        class Loop:
            def __init__(self):
                self.callbacks = []

            def call_soon_threadsafe(self, callback):
                self.callbacks.append(callback)

        loop = Loop()
        buffer = AudioInputBuffer(loop, max_chunks=4)
        for _ in range(1000):
            buffer.put(b'pcm')
        self.assertEqual(len(loop.callbacks), 1)
        self.assertEqual(buffer.dropped_chunks, 996)


class PlaybackTests(unittest.TestCase):
    def test_generated_speech_burst_preserves_every_sample(self):
        buffer = PCMPlaybackBuffer()
        speech = bytes(range(256)) * 2000
        for offset in range(0, len(speech), 4096):
            buffer.put(speech[offset:offset + 4096])
        output = bytearray(len(speech))
        buffer.fill(output)
        self.assertEqual(output, speech)
        self.assertEqual(buffer.dropped_bytes, 0)

    def test_short_reply_plays_after_prebuffer_deadline(self):
        from unittest.mock import patch
        buffer = PCMPlaybackBuffer(prebuffer_seconds=0.12)
        with patch('annie.audio_io.time.monotonic', return_value=10.0):
            buffer.put(b'abcd')
            output = bytearray(8)
            buffer.fill(output)
            self.assertEqual(output, bytes(8))
        with patch('annie.audio_io.time.monotonic', return_value=10.13):
            buffer.fill(output)
            self.assertEqual(output, b'abcd' + bytes(4))

    def test_interruption_discards_prebuffered_speech(self):
        buffer = PCMPlaybackBuffer(prebuffer_seconds=0.12)
        buffer.put(b'abcd')
        buffer.clear()
        output = bytearray(8)
        buffer.fill(output)
        self.assertEqual(output, bytes(8))

    def test_partial_reads_preserve_order_and_zero_fill(self):
        buffer = PCMPlaybackBuffer(max_bytes=16)
        buffer.put(b'abcdefgh')
        buffer.put(b'ij')
        first = bytearray(6)
        second = bytearray(b'xxxxxxxx')
        buffer.fill(first)
        buffer.fill(second)
        self.assertEqual(first, b'abcdef')
        self.assertEqual(second, b'ghij\x00\x00\x00\x00')
        self.assertEqual(buffer.queued_bytes, 0)

    def test_overflow_and_clear(self):
        buffer = PCMPlaybackBuffer(max_bytes=8)
        buffer.put(b'abcdef')
        buffer.put(b'ghijkl')
        output = bytearray(8)
        buffer.fill(output)
        self.assertEqual(output, b'efghijkl')
        self.assertEqual(buffer.dropped_bytes, 4)
        buffer.put(b'mnop')
        buffer.clear()
        buffer.fill(output)
        self.assertEqual(output, bytes(8))

    def test_oversized_chunk_has_a_hard_memory_limit(self):
        buffer = PCMPlaybackBuffer(max_bytes=8)
        buffer.put(b'ab' * 10000)
        self.assertEqual(buffer.queued_bytes, 8)
        self.assertEqual(buffer.dropped_bytes, 19992)
        self.assertEqual(len(buffer._chunks[0].obj), 8)


if __name__ == '__main__':
    unittest.main()
