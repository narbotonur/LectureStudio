"""Persistent isolated Whisper process shared by recording and file imports."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid
from annie.platform_support import worker_command


class WhisperService:
    def __init__(self, command=None):
        self.command = command or worker_command()
        self._lock = threading.RLock()
        self._proc = None
        self._active = None
        self._events = None
        self._closing = False
        self._shutdown_timer = None

    def _write(self, message):
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                raise RuntimeError('Whisper process is not running')
            self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self._proc.stdin.flush()

    def _ensure_process(self):
        if self._closing:
            raise RuntimeError('Whisper is shutting down')
        if self._proc and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
            bufsize=1, cwd=str(Path(__file__).resolve().parents[1]),
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0,
        )
        threading.Thread(target=self._read_output, args=(self._proc,), daemon=True).start()

    def start(self, **options):
        with self._lock:
            if self._active is not None:
                raise RuntimeError('A Whisper recording or import is already active')
            self._ensure_process()
            session_id = uuid.uuid4().hex
            events = queue.Queue(maxsize=512)
            self._active, self._events = session_id, events
            try:
                self._write({'action': 'start', 'session_id': session_id, **options})
            except Exception:
                self._active = self._events = None
                raise
            return session_id, events

    def stop(self, session_id):
        with self._lock:
            if session_id != self._active:
                return
            try:
                self._write({'action': 'stop', 'session_id': session_id})
            except (OSError, RuntimeError):
                pass  # The output reader reports process failure to the caller.

    def release(self, session_id):
        with self._lock:
            if self._active == session_id:
                self._active = self._events = None

    def _deliver(self, message):
        with self._lock:
            session_id = message.get('session_id')
            if not session_id or session_id != self._active:
                return
            events = self._events
        if message.get('type') in ('level', 'metrics'):
            try:
                events.put_nowait(message)
            except queue.Full:
                pass
            return
        while True:
            try:
                events.put(message, timeout=0.2)
                return
            except queue.Full:
                with self._lock:
                    if session_id != self._active:
                        return

    def _read_output(self, proc):
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue  # Native-library diagnostics share the drained pipe.
                if isinstance(message, dict):
                    self._deliver(message)
        finally:
            proc.wait()
            with self._lock:
                session_id = self._active if self._proc is proc else None
            if session_id:
                self._deliver({'session_id': session_id, 'type': 'process_exit',
                               'text': f'Whisper process exited ({proc.returncode}).'})
            proc.stdout.close()
            proc.stdin.close()

    @property
    def is_running(self):
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def shutdown(self):
        with self._lock:
            if self._closing:
                return
            self._closing = True
            if not self.is_running:
                return
            proc = self._proc
            try:
                self._write({'action': 'shutdown'})
            except (OSError, RuntimeError):
                pass
            # A stuck native inference/download cannot be cancelled from Python.
            # Allow draining first; saved WAV audio survives a forced process exit.
            self._shutdown_timer = threading.Timer(30, self._terminate_if_alive, args=(proc,))
            self._shutdown_timer.daemon = True
            self._shutdown_timer.start()

    @staticmethod
    def _terminate_if_alive(proc):
        if proc.poll() is None:
            proc.terminate()


_service = WhisperService()


def get_whisper_service():
    return _service


def shutdown_whisper_service():
    _service.shutdown()


def whisper_service_is_running():
    return _service.is_running


def _cleanup_at_exit():
    _service.shutdown()
    proc = _service._proc
    if proc and proc.poll() is None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()


atexit.register(_cleanup_at_exit)
