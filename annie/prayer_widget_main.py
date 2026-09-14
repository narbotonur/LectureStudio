"""Independent prayer widget entry: no Studio, Whisper, camera or microphone."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile

from PyQt5.QtCore import QLockFile, QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from annie.paths import DATA_DIR


class WidgetInstance(QObject):
    show_requested = pyqtSignal()
    secondary_done = pyqtSignal()

    def __init__(self, parent, name=None):
        super().__init__(parent)
        identity = os.path.normcase(str(Path(DATA_DIR).resolve()))
        self.name = name or 'annie-prayer-' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        self.lock = QLockFile(str(Path(tempfile.gettempdir()) / (self.name + '.lock')))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.peers = set()
        self.client = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._finish_secondary)

    def acquire(self):
        if not self.lock.tryLock(0):
            # Keep the secondary event loop alive until the owner acknowledges
            # the request; exiting immediately can drop a named-pipe message.
            self.client = QLocalSocket(self)
            self.client.readyRead.connect(self._finish_secondary)
            self.client.errorOccurred.connect(self._finish_secondary)
            self.timeout.start(2000)
            self.client.connectToServer(self.name)
            return False
        # We hold the OS lock; only a stale socket pathname can remain on macOS.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            QTimer.singleShot(0, self.secondary_done.emit)
            return False
        return True

    def _finish_secondary(self, *_):
        if not self.timeout.isActive():
            # timeout itself has already become inactive when it fires.
            if self.client is None:
                return
        self.timeout.stop()
        if self.client:
            socket, self.client = self.client, None
            socket.abort()
            socket.deleteLater()
        self.secondary_done.emit()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.peers.add(socket)
            socket.disconnected.connect(lambda s=socket: self._drop(s))
            self.show_requested.emit()
            socket.write(b'ok\n')
            socket.disconnectFromServer()

    def _drop(self, socket):
        self.peers.discard(socket)
        socket.deleteLater()

    def close(self):
        self.timeout.stop()
        if self.client:
            self.client.abort()
        self.server.close()
        for socket in list(self.peers):
            socket.abort()
        self.lock.unlock()


def main():
    from annie.desktop_pin import enable_widget_dpi
    if QApplication.instance() is None:
        enable_widget_dpi()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    if sys.platform == 'darwin':
        from annie.macos_support import set_accessory_mode
        set_accessory_mode()
    instance = WidgetInstance(app)
    instance.secondary_done.connect(lambda: QTimer.singleShot(0, app.quit))
    if not instance.acquire():
        return app.exec_()
    from annie.gui.prayer_widget import PrayerWidget
    widget = PrayerWidget()

    def show():
        widget.show()
        if not widget.settings.desktop_pinned:
            widget.raise_()

    instance.show_requested.connect(show)
    tray = QSystemTrayIcon(app.style().standardIcon(QStyle.SP_ComputerIcon), app)
    tray.setToolTip('Намаз · виджет на рабочем столе')
    menu = QMenu()
    menu.addAction('Показать виджет', show)
    menu.addAction('Настройки…', widget.open_settings)
    if sys.platform == 'win32':
        pin = menu.addAction('Закрепить на рабочем столе')
        pin.setCheckable(True)
        pin.triggered.connect(widget.set_pinned)
        menu.aboutToShow.connect(lambda: pin.setChecked(widget.settings.desktop_pinned))
    menu.addAction('Обновить расписание', lambda: widget.refresh(True))
    menu.addSeparator()

    def quit_widget():
        widget.shutdown(app.quit)

    menu.addAction('Выйти', quit_widget)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: show() if reason == QSystemTrayIcon.DoubleClick else None)
    widget.quit_requested.connect(quit_widget)
    app.aboutToQuit.connect(instance.close)
    app.aboutToQuit.connect(tray.hide)
    tray.show()
    widget.show()
    return app.exec_()
