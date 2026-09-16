"""Non-modal update notice and release notes, using the Studio visual system."""
import sys

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from annie.gui.design import STYLE, label, role
from annie.updates import RELEASES_URL, UpdateService, select_download
from annie.version import VERSION


class UpdateDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle('Lecture Studio · Updates')
        self.setStyleSheet(STYLE)
        self.resize(560, 490)
        self.setMinimumSize(380, 350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        self.heading = label('Check for updates', 'title')
        layout.addWidget(self.heading)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        layout.addWidget(self.summary)
        layout.addWidget(label("What's new", 'section'))
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes, 1)
        self.help = label('', 'muted')
        self.help.setWordWrap(True)
        layout.addWidget(self.help)
        actions = QHBoxLayout()
        self.retry = QPushButton('Check again')
        self.retry.clicked.connect(lambda: service.check(manual=True))
        actions.addWidget(self.retry)
        self.release_button = QPushButton('Open release')
        self.release_button.clicked.connect(self.open_release)
        actions.addWidget(self.release_button)
        self.download = role(QPushButton('Download update'), 'primary')
        self.download.clicked.connect(self.open_download)
        actions.addWidget(self.download)
        layout.addLayout(actions)
        service.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        state = self.service.state
        release = state.get('release')
        busy = self.service.worker is not None
        self.retry.setEnabled(not busy)
        self.download.setVisible(self.service.available and select_download(release) is not None)
        if busy:
            self.heading.setText('Checking for updates…')
        elif state.get('error'):
            self.heading.setText('Could not check for updates')
        elif self.service.available:
            self.heading.setText('Update is available')
        elif release:
            self.heading.setText("You're up to date")
        else:
            self.heading.setText('No published release yet')
        newest = f" · Latest: {release['tag_name']}" if release else ''
        self.summary.setText(f'Installed: {VERSION}{newest}' +
                             (f"\n{state['error']}" if state.get('error') else ''))
        # Release text is untrusted. Plain text prevents hidden remote images or HTML.
        self.notes.setPlainText((release.get('body') or 'No release notes were provided.') if release
                                else 'Changes will appear here when a release is published.')
        if not getattr(sys, 'frozen', False):
            hint = 'Running from source? Update your Git checkout and dependencies, or install the app from the release.'
        elif sys.platform == 'darwin':
            hint = 'Download the DMG, finish your recording, quit Studio and the watcher, then replace Lecture Studio in Applications. Your profile stays in place.'
        else:
            hint = 'Finish your recording and quit Studio and the watcher before installing the update. Your profile stays in place.'
        if self.service.available and not select_download(release):
            hint = 'No installer for this device is attached yet. Open the release for available files.\n' + hint
        self.help.setText(hint)

    def open_release(self):
        release = self.service.state.get('release')
        QDesktopServices.openUrl(QUrl(release['html_url'] if release else RELEASES_URL))

    def open_download(self):
        release = self.service.state.get('release')
        asset = select_download(release) if release else None
        if asset:
            QDesktopServices.openUrl(QUrl(asset['browser_download_url']))


class UpdatePanel(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        role(self, 'panel')
        self.service = UpdateService(self)
        self.dialog = None
        self.check_button = QPushButton('Check for updates', parent)
        self.check_button.setToolTip(f'Lecture Studio {VERSION}')
        self.check_button.clicked.connect(self.check_manually)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        row.addWidget(self.message, 1)
        details = role(QPushButton("What's new"), 'primary')
        details.clicked.connect(self.show_details)
        row.addWidget(details)
        self.service.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        available = self.service.available
        self.setVisible(available)
        if available:
            self.message.setText(f"Update is available · {self.service.state['release']['tag_name']}")
        self.check_button.setEnabled(self.service.worker is None)
        self.check_button.setText('Checking…' if self.service.worker else 'Check for updates')

    def show_details(self):
        if self.dialog is None:
            self.dialog = UpdateDialog(self.service, self.window())
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def check_manually(self):
        self.show_details()
        self.service.check(manual=True)
