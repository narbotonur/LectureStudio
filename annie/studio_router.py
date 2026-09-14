"""One Lecture Studio owner across the assistant, launcher and watcher processes."""
import hashlib
import json
import os
import tempfile
import uuid

from PyQt5.QtCore import QObject, QLockFile, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

from annie.config import DATA_DIR


def endpoint_name():
    identity = '|'.join((os.environ.get('USERDOMAIN', ''), os.environ.get('USERNAME', ''),
                         os.path.normcase(os.path.abspath(DATA_DIR))))
    return 'annie-studio-' + hashlib.sha256(identity.encode()).hexdigest()[:20]


class StudioRouter(QObject):
    """Asynchronous local commands; an OS lock arbitrates simultaneous launches."""
    delivered = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent, get_studio, name=None, launch_owner=None):
        super().__init__(parent)
        self.get_studio = get_studio
        self.launch_owner = launch_owner
        self.name = name or endpoint_name()
        self._lock = QLockFile(os.path.join(tempfile.gettempdir(), self.name + '.lock'))
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._accept)
        self._studio = None
        self._closing = False
        self._seen = set()
        self._requests = set()
        self._peers = set()
        self._remote_recording = False
        self._legacy_found = False
        self._poll = QTimer(self)
        self._poll.setInterval(2500)
        self._poll.timeout.connect(self._poll_status)
        self._poll.start()
        parent.aboutToQuit.connect(self.close)

    def is_recording(self):
        return self._studio.is_active() if self._studio is not None else self._remote_recording

    def request(self, action='show', source=None, context='', tab=0):
        if source is None:
            from annie import config as cfg
            source = cfg.MEETING_PROMPT_AUDIO_SOURCE
        message = dict(action=action, source=source, context=context, tab=tab,
                       request_id=uuid.uuid4().hex)
        self._send(message)

    def _poll_status(self):
        if not self._closing and not self._server.isListening() and not self._requests:
            self._send({'action': 'status', 'request_id': uuid.uuid4().hex})

    def _claim(self):
        if not self._lock.tryLock(0):
            return False
        self._legacy_found = self.name == endpoint_name() and self._older_studio_exists()
        if self._legacy_found:
            self._lock.unlock()
            return False
        if self._server.listen(self.name):
            return True
        self._lock.unlock()
        return False

    def _legacy_launch_error(self):
        if self.name != endpoint_name():
            return ''
        from annie.startup import outdated_watcher_pids
        if outdated_watcher_pids():
            return ('A watcher from before the update is still running. Finish any recording or other work, '
                    'then use its tray menu > Quit watcher and reopen Lecture Studio. '
                    'The silent startup watcher will return at the next login. No second Studio was opened.')
        if self._older_studio_exists():
            return ('An older Lecture Studio is already open but cannot receive commands. '
                    'Finish its work, then close it and reopen Lecture Studio. No second Studio was opened.')
        return ''

    @staticmethod
    def _older_studio_exists():
        """Do not create a duplicate beside a pre-update Studio without IPC."""
        if os.name != 'nt':
            return False
        try:
            import win32gui
            import win32process
            found = []

            def visit(hwnd, _):
                title = win32gui.GetWindowText(hwnd).lower()
                if (title.startswith('annie') and 'lecture studio' in title
                        and win32gui.GetClassName(hwnd).startswith('Qt')
                        and win32process.GetWindowThreadProcessId(hwnd)[1] != os.getpid()):
                    found.append(hwnd)
            win32gui.EnumWindows(visit, None)
            return bool(found)
        except Exception:
            return False

    def _send(self, message, attempt=0):
        if self._closing:
            return
        if self._server.isListening():
            self._deliver_local(message)
            return
        socket = QLocalSocket(self)
        self._requests.add(socket)
        timeout = QTimer(socket)
        timeout.setSingleShot(True)
        buffer = bytearray()
        done = False

        def finish():
            nonlocal done
            if done:
                return
            done = True
            timeout.stop()
            self._requests.discard(socket)
            socket.abort()
            socket.deleteLater()

        def failed(code):
            if done:
                return
            finish()
            if message['action'] == 'status':
                self._remote_recording = False
                return
            # Only a definite missing endpoint permits claiming ownership.
            if code in (QLocalSocket.ServerNotFoundError, QLocalSocket.ConnectionRefusedError):
                try:
                    legacy_error = self._legacy_launch_error()
                except Exception as exc:
                    self.error.emit(f'Could not check the existing Studio instance: {exc}. No second Studio was opened.')
                    return
                if legacy_error:
                    self.error.emit(legacy_error)
                    return
                if self.launch_owner is not None:
                    # A watcher is only a client. A fresh standalone process
                    # loads the current UI and arbitrates ownership as usual.
                    if attempt == 0:
                        try:
                            self.launch_owner()
                        except Exception as exc:
                            self.error.emit(f'Could not launch Lecture Studio: {exc}')
                            return
                    if attempt < 80:
                        QTimer.singleShot(150, lambda: self._send(message, attempt + 1))
                        return
                    self.error.emit('Lecture Studio did not finish opening. Try again shortly.')
                    return
                if self._claim():
                    self._deliver_local(message)
                    return
                if self._legacy_found:
                    self.error.emit('An older Lecture Studio is already open. Finish its recording, then restart Studio and the watcher to apply the update.')
                    return
                if attempt < 8:
                    QTimer.singleShot(150, lambda: self._send(message, attempt + 1))
                    return
            self.error.emit('Lecture Studio is not responding. No second recording was started.')

        def received():
            buffer.extend(bytes(socket.readAll()))
            if b'\n' not in buffer:
                return
            try:
                reply = json.loads(buffer.split(b'\n', 1)[0])
                self._remote_recording = bool(reply.get('recording'))
                ok = reply.get('ok', False)
            except (ValueError, TypeError):
                ok = False
            finish()
            if ok:
                self.delivered.emit(message['action'])
            elif message['action'] != 'status':
                self.error.emit('Lecture Studio is busy finishing work. Try again shortly.')

        socket.connected.connect(lambda: socket.write(json.dumps(message).encode() + b'\n'))
        socket.readyRead.connect(received)
        socket.errorOccurred.connect(failed)
        timeout.timeout.connect(lambda: failed(QLocalSocket.SocketTimeoutError))
        timeout.start(2500 if message['action'] == 'status' else 15000)
        socket.connectToServer(self.name)

    def _accept(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._peers.add(socket)
            socket.disconnected.connect(lambda s=socket: self._drop_peer(s))
            buffer = bytearray()

            def read(s=socket, data=buffer):
                data.extend(bytes(s.readAll()))
                if len(data) > 16384:
                    s.abort()
                    return
                if b'\n' not in data:
                    return
                try:
                    message = json.loads(data.split(b'\n', 1)[0])
                    ok = self._handle(message)
                except Exception:
                    ok = False
                s.write(json.dumps({'ok': ok, 'recording': self.is_recording()}).encode() + b'\n')
                s.disconnectFromServer()

            socket.readyRead.connect(read)
            if socket.bytesAvailable():
                read()

    def _drop_peer(self, socket):
        self._peers.discard(socket)
        socket.deleteLater()

    def _deliver_local(self, message):
        try:
            ok = self._handle(message)
        except Exception as exc:
            self.error.emit(f'Could not open Lecture Studio: {exc}')
            return
        if ok:
            self.delivered.emit(message['action'])
        else:
            self.error.emit('Lecture Studio is busy finishing work. Try again shortly.')

    def _handle(self, message):
        action = message.get('action')
        if self._closing or action not in ('show', 'start', 'status'):
            return False
        if action == 'status':
            return True
        request_id = message.get('request_id')
        if request_id in self._seen:
            return True
        if self._studio is None:
            self._studio = self.get_studio()
        studio = self._studio
        if action == 'start':
            if studio.is_active():
                return True
            if studio.worker is not None and studio.worker.isRunning():
                return False
            from annie.meeting_prompt import start_studio_transcription
            start_studio_transcription(studio, message.get('source', 'dual'), message.get('context', ''))
        else:
            studio._switch_tab(max(0, min(5, int(message.get('tab', 0)))))
            if studio.isMinimized():
                studio.showNormal()
            else:
                studio.show()
            studio.raise_()
            studio.activateWindow()
        self._seen.add(request_id)
        if len(self._seen) > 1024:
            self._seen = {request_id}
        return True

    def begin_shutdown(self):
        self._closing = True
        self._poll.stop()

    def close(self):
        self.begin_shutdown()
        self._server.close()
        for socket in list(self._requests | self._peers):
            socket.abort()
        self._lock.unlock()
