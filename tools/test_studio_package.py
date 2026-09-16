"""Exercise a packaged worker against synthetic silence, never a live microphone."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--model', type=Path, required=True, help='Existing public Whisper model directory; no download')
    parser.add_argument('--speech', action='store_true', help='Generate a spoken fixture with Windows SAPI, without speaker playback')
    options = parser.parse_args()
    worker = options.package.resolve() / ('Contents/MacOS/LectureStudioWorker' if sys.platform == 'darwin' else 'LectureStudioWorker.exe')
    model = options.model.resolve()
    if not (model / 'model.bin').is_file():
        raise ValueError('Expected a downloaded CTranslate2 Whisper model.')
    with tempfile.TemporaryDirectory(prefix='annie-packaged-worker-test-') as temporary:
        data = Path(temporary)
        audio = data / 'synthetic-silence.wav'
        if options.speech and sys.platform == 'darwin':
            audio = data / 'synthetic-speech.aiff'
            subprocess.run(['/usr/bin/say', '-o', str(audio),
                            'This lecture is about discrete mathematics. A graph contains vertices and edges. '
                            'We will study these definitions before the next exam.'], check=True, timeout=30)
        elif options.speech:
            import win32com.client
            stream = win32com.client.Dispatch('SAPI.SpFileStream')
            stream.Open(str(audio), 3)
            speaker = win32com.client.Dispatch('SAPI.SpVoice')
            english = speaker.GetVoices('Language=409')
            if english.Count:
                speaker.Voice = english.Item(0)
            speaker.AudioOutputStream = stream
            speaker.Speak('This is a test lecture about discrete mathematics. A graph contains vertices and edges. We will study these definitions before the next exam.')
            stream.Close()
        else:
            with wave.open(str(audio), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b'\x00\x00' * 16000 * 2)
        process = subprocess.Popen([str(worker), '--whisper-service'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            env={**os.environ, 'ANNIE_DATA_DIR': temporary, 'HF_HUB_OFFLINE': '1',
                 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output = queue.Queue()
        reader_done = threading.Event()

        def read():
            try:
                for line in process.stdout:
                    output.put(line)
                output.put(None)
            finally:
                reader_done.set()
        reader = threading.Thread(target=read, name='packaged-worker-output', daemon=True)
        reader.start()
        try:
            command = {'action': 'start', 'session_id': 'release-test', 'mode': 'file',
                       'model_name': str(model), 'file_path': str(audio)}
            process.stdin.write(json.dumps(command) + '\n')
            process.stdin.flush()
            deadline = time.monotonic() + 120
            done = None
            transcript = []
            while time.monotonic() < deadline:
                try:
                    line = output.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError('Packaged worker exited before session completion.')
                print(line.rstrip(), flush=True)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'session_done':
                    done = event
                    break
                if event.get('type') == 'transcript':
                    transcript.append(event.get('text', ''))
            if done is None or done.get('had_error') or done.get('cancelled'):
                raise RuntimeError('Packaged file transcription failed or timed out.')
            if options.speech and not ''.join(transcript).strip():
                raise RuntimeError('No transcript was produced for the generated speech fixture.')
            process.stdin.write('{"action":"shutdown"}\n')
            process.stdin.flush()
            # Closing the command pipe guarantees EOF even if a packaged runtime
            # misses the explicit shutdown message during interpreter teardown.
            process.stdin.close()
            process.wait(timeout=30)
            if process.returncode:
                raise RuntimeError('Worker shutdown was not clean.')
            # Descendants of a frozen runtime can briefly retain the inherited
            # stdout descriptor after the worker itself has exited. The worker's
            # zero return code is authoritative; the daemon reader is best-effort.
            reader_done.wait(1)
            print('PASS: frozen backend loaded a real cached model, processed synthetic audio and shut down cleanly.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            reader_done.wait(.2)
            reader.join(timeout=.2)


if __name__ == '__main__':
    main()
