"""Non-modal update notice and release notes, using the Studio visual system."""
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit,
                            QVBoxLayout, QProgressBar, QMessageBox)

from annie.gui.design import ACCENT, BORDER, STYLE, SURFACE, label, role
from annie.updates import RELEASES_URL, UpdateService, select_download
from annie.version import VERSION
from annie.update_download import DownloadService, installed_windows_directory, launch_windows_install


class UpdateDialog(QDialog):
    def __init__(self, service, downloads, parent=None):
        super().__init__(parent)
        self.service = service
        self.downloads = downloads
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
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f'QProgressBar {{ background: {SURFACE}; border: 1px solid {BORDER}; '
            f'border-radius: 6px; text-align: center; min-height: 18px; }} '
            f'QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}')
        layout.addWidget(self.progress)
        self.transfer_status = QLabel()
        self.transfer_status.setWordWrap(True)
        self.transfer_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.transfer_status)
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
        self.cancel_download = QPushButton('Cancel download')
        self.cancel_download.clicked.connect(downloads.cancel)
        actions.addWidget(self.cancel_download)
        layout.addLayout(actions)
        service.changed.connect(self.refresh)
        downloads.changed.connect(self.refresh_transfer)
        self.refresh()

    def refresh(self):
        state = self.service.state
        release = state.get('release')
        busy = self.service.worker is not None
        self.retry.setEnabled(not busy and self.downloads.worker is None)
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
            hint = 'Download here, then open the DMG and replace Lecture Studio in Applications. Finish your recording and quit Studio and the watcher before replacing it.'
        elif installed_windows_directory() is not None:
            hint = 'Download here, then choose Install and restart. Quit the watcher first. The previous app is kept as a backup; your profile stays in place.'
        else:
            hint = 'Download and open the ZIP, quit Studio and the watcher, then replace your app folder with the LectureStudio folder from the archive. Your profile stays in place.'
        if self.service.available and not select_download(release):
            hint = 'No installer for this device is attached yet. Open the release for available files.\n' + hint
        self.help.setText(hint)
        self.refresh_transfer()

    def refresh_transfer(self):
        busy = self.downloads.worker is not None
        result = self.downloads.result
        release = self.service.state.get('release')
        if result and release and result['tag'] != release['tag_name']:
            self.downloads.result = result = None
            self.downloads.error = 'A newer release is available. Download the latest version.'
        self.retry.setEnabled(not busy and self.service.worker is None)
        self.download.setEnabled(not busy and self.service.worker is None)
        self.cancel_download.setVisible(busy)
        self.progress.setVisible(busy)
        if result:
            self.download.setVisible(True)
            self.download.setText('Install and restart' if result.get('staged') else
                                  'Open DMG' if result['path'].lower().endswith('.dmg') else 'Open downloaded ZIP')
            self.transfer_status.setText(f"{result['tag']} downloaded and verified. Ready to install.")
        elif busy:
            done, total = self.downloads.done, self.downloads.total
            self.progress.setRange(0, 1000 if total else 0)
            if total:
                self.progress.setValue(min(1000, int(done * 1000 / total)))
            suffix = f' / {total / 1024**2:.1f} MB' if total else ' MB'
            self.transfer_status.setText(f'Downloaded {done / 1024**2:.1f}{suffix}' +
                                         (' · Verifying and preparing…' if total and done == total else ''))
            self.download.setText('Downloading…')
        else:
            self.download.setText('Download update')
            self.transfer_status.setText(self.downloads.error)

    def open_release(self):
        release = self.service.state.get('release')
        QDesktopServices.openUrl(QUrl(release['html_url'] if release else RELEASES_URL))

    def open_download(self):
        if self.downloads.worker:
            return
        if self.downloads.result:
            self.install_download()
            return
        release = self.service.state.get('release')
        asset = select_download(release) if release else None
        if asset:
            self.downloads.start(release)

    def install_download(self):
        result = self.downloads.result
        studio = self.parentWidget()
        if studio and ((hasattr(studio, 'is_active') and studio.is_active()) or
                       (hasattr(studio, 'has_running_jobs') and studio.has_running_jobs())):
            QMessageBox.information(self, 'Finish your current task',
                                    'Finish recording or generation before installing this update.')
            return
        if not result.get('staged'):
            path = Path(result['path'])
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                QMessageBox.information(self, 'Downloaded update', f'Open the installer from:\n{path}')
            return
        answer = QMessageBox.question(self, 'Install update',
            'Quit the watcher from its tray menu first. Studio will close, replace its app files and restart. '
            'Your previous app will be kept as a backup. Install now?', QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            launch_windows_install(result['staged'], result['target'], Path(result['path']).parent)
        except Exception as error:
            QMessageBox.warning(self, 'Could not start installation', str(error))
            return
        studio.close()


class UpdatePanel(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        role(self, 'panel')
        self.service = UpdateService(self)
        self.downloads = DownloadService(self.service.path.parent / 'updates', self)
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
            self.dialog = UpdateDialog(self.service, self.downloads, self.window())
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def check_manually(self):
        self.show_details()
        if not self.downloads.worker:
            self.service.check(manual=True)
