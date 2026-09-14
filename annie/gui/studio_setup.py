"""First-run onboarding and standalone account/device settings."""
import json
from pathlib import Path
import webbrowser
import sys

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QWidget,
                            QScrollArea, QLineEdit, QPushButton, QCheckBox, QComboBox,
                            QFileDialog, QMessageBox)
from annie import config as cfg
from annie.gui.design import apply_theme, label, role
from annie.secure_storage import atomic_write

SETUP_MARKER = Path(cfg.DATA_DIR) / 'setup-complete.json'


class ConnectGoogle(QThread):
    result = pyqtSignal(bool)

    def run(self):
        try:
            from annie.calendar_service import get_calendar_credentials
            self.result.emit(get_calendar_credentials(interactive=True) is not None)
        except Exception:
            self.result.emit(False)


class StudioSetup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.setWindowTitle('Lecture Studio · Accounts & Setup')
        self.resize(620, 720)
        self.setMinimumSize(480, 500)
        outer = QVBoxLayout(self)
        outer.addWidget(label('Make Studio yours', 'title'))
        intro = label('Your accounts stay on your user profile, protected by macOS Keychain or Windows encryption. No accounts or recordings from the app publisher are included.')
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('homeContent')
        content = QVBoxLayout(body)
        content.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        content.addWidget(label('1 · AI features', 'section'))
        self.key = QLineEdit(cfg.GEMINI_API_KEY)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText('Your Gemini API key (optional for local recording/timers)')
        content.addWidget(self.key)
        self.model = QLineEdit(cfg.GEMINI_MODEL)
        self.model.setPlaceholderText('Gemini model available to your account')
        form = QFormLayout()
        form.addRow('AI model', self.model)
        content.addLayout(form)
        get_key = QPushButton('Get my API key ↗')
        get_key.clicked.connect(lambda: webbrowser.open('https://aistudio.google.com/apikey'))
        content.addWidget(get_key)
        self.consent = QCheckBox('Enable cloud AI using my key')
        self.consent.setChecked(bool(cfg.GEMINI_API_KEY))
        content.addWidget(self.consent)
        privacy = label('AI requests send the selected lecture text, slides or uploaded materials to Google. Usage limits and charges belong to your account. Local Whisper transcription and study timers do not need an AI key.')
        privacy.setWordWrap(True)
        content.addWidget(privacy)
        content.addWidget(label('2 · Google Calendar', 'section'))
        self.calendar_status = label('')
        self.calendar_status.setWordWrap(True)
        content.addWidget(self.calendar_status)
        buttons = QHBoxLayout()
        self.import_button = QPushButton('Import Google client JSON')
        self.import_button.clicked.connect(self._import_google)
        self.connect_button = QPushButton('Connect Google')
        self.connect_button.clicked.connect(self._connect_google)
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.connect_button)
        content.addLayout(buttons)
        self.disconnect_button = QPushButton('Disconnect this Google account')
        self.disconnect_button.clicked.connect(self._disconnect_google)
        content.addWidget(self.disconnect_button)
        help_button = QPushButton('Google setup instructions ↗')
        help_button.clicked.connect(lambda: webbrowser.open('https://developers.google.com/workspace/calendar/api/quickstart/python#set_up_your_environment'))
        content.addWidget(help_button)
        help_text = label('Create a Google Cloud project, enable Calendar API, configure the consent screen, and download a Desktop app OAuth client JSON. Add your email as a test user if the project is in Testing. Then connect in your browser. Sessions sync to that account’s primary calendar. You can skip this and use the local calendar.')
        help_text.setWordWrap(True)
        content.addWidget(help_text)
        content.addWidget(label('3 · Microphone & phone', 'section'))
        devices = QFormLayout()
        self.microphone = QComboBox()
        self.microphone.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setMinimumContentsLength(12)
        self.microphone.addItem('Default system microphone', None)
        try:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device.get('max_input_channels', 0):
                    self.microphone.addItem(device['name'], index)
        except Exception:
            pass
        self.microphone.setCurrentIndex(max(0, self.microphone.findData(cfg.AUDIO_INPUT_DEVICE)))
        self.phone = QLineEdit(cfg.PHONE_IP)
        self.phone.setPlaceholderText('192.168.1.50')
        self.port = QLineEdit(str(cfg.PHONE_PORT))
        devices.addRow('Microphone', self.microphone)
        self.whisper = QComboBox()
        self.whisper.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.whisper.setMinimumContentsLength(12)
        for title, value in (('Base · fastest / smaller download', 'base'),
                             ('Small · balanced', 'small'), ('Large v3 turbo · highest accuracy / larger download', 'large-v3-turbo')):
            self.whisper.addItem(title, value)
        self.whisper.setCurrentIndex(max(0, self.whisper.findData(cfg.WHISPER_MODEL)))
        devices.addRow('Local transcription', self.whisper)
        devices.addRow('Phone IP / host', self.phone)
        devices.addRow('Phone port', self.port)
        content.addLayout(devices)
        note = label('Portal buttons use your default browser, where you sign into your own university account. The first local transcription downloads a Whisper model; CPU transcription works without an NVIDIA GPU.')
        note.setWordWrap(True)
        content.addWidget(note)
        if sys.platform == 'darwin':
            mac_note = label('macOS: local transcription uses the CPU. Microphone, system audio, combined audio and phone input are available. '
                             'Allow Microphone for your voice and Screen & System Audio Recording for meeting sound. '
                             'System audio uses Apple ScreenCaptureKit; no virtual audio driver is needed. '
                             'Meeting detection reads window titles, not screen images. Calendar reminders need neither recording permission.')
            mac_note.setWordWrap(True)
            content.addWidget(mac_note)
            permission = QPushButton('Allow meeting detection & system audio')
            permission.clicked.connect(self._mac_meeting_permission)
            content.addWidget(permission)
        self.prompts = QCheckBox('Show meeting and lecture reminders while Studio is running')
        self.prompts.setChecked(cfg.MEETING_PROMPTS_ENABLED)
        content.addWidget(self.prompts)
        from annie.startup import enabled
        self.autostart = QCheckBox('Start the silent watcher at login (takes effect next login)')
        self.autostart.setChecked(enabled())
        content.addWidget(self.autostart)
        self.feedback = label('You can change these settings later from More → Accounts & Setup.')
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = role(QPushButton('Save & open Studio'), 'primary')
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)
        self._calendar_state()
        apply_theme(self)

    def _mac_meeting_permission(self):
        try:
            from annie.macos_support import request_meeting_permission
            granted = request_meeting_permission()
            self.feedback.setText('Permission granted. Restart Studio if meeting titles are still unavailable.' if granted else
                                  'Allow Lecture Studio in System Settings > Privacy & Security > Screen Recording, then restart Studio.')
        except Exception:
            self.feedback.setText('macOS permission support is unavailable. Install the macOS dependencies and try again.')

    def _calendar_state(self):
        from annie.calendar_service import is_connected, has_client
        connected = is_connected()
        self.calendar_status.setText('Google Calendar connected on this laptop.' if connected else
                                     'Client configured. Connect your Google account.' if has_client() else
                                     'Not connected. Import your Google Desktop app client JSON first.')
        self.connect_button.setEnabled(has_client() and not connected)
        self.disconnect_button.setEnabled(connected)

    def _disconnect_google(self):
        if self._worker:
            return
        answer = QMessageBox.question(self, 'Disconnect Google Calendar?',
            'Remove this laptop’s saved Google login? Existing calendar events will not be deleted. '
            'Pending study sessions will sync to whichever account you connect next. '
            'You can revoke the app’s Google access separately in your Google account.')
        if answer != QMessageBox.Yes:
            return
        try:
            from annie import calendar_service as calendar
            from annie.secure_storage import write_secret
            if calendar.PRIVATE_PROFILE:
                write_secret(calendar.TOKEN_PATH, {})
            else:
                atomic_write(calendar.TOKEN_PATH, b'{}')
            atomic_write(Path(cfg.DATA_DIR) / 'lecture_schedule_cache.json', b'{}')
            self.feedback.setText('Saved login removed from this laptop. Connect again to sign into another account.')
            self._calendar_state()
        except Exception:
            self.feedback.setText('Could not remove the saved login. Please try again.')

    def _import_google(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Google Desktop app OAuth client', '', 'Google client (*.json)')
        if path:
            try:
                from annie.calendar_service import import_client, is_connected
                if is_connected():
                    self.feedback.setText('Already connected. Disconnect in your Google account before replacing its client configuration.')
                    return
                import_client(path)
                self._calendar_state()
            except Exception as exc:
                self.feedback.setText(str(exc))

    def _connect_google(self):
        if self._worker:
            return
        self.feedback.setText('Complete sign-in in your browser. This step times out after 3 minutes.')
        for button in (self.save_button, self.cancel_button, self.import_button, self.connect_button, self.disconnect_button):
            button.setEnabled(False)
        self._worker = ConnectGoogle(self)
        self._worker.result.connect(lambda ok: self.feedback.setText(
            'Google Calendar connected.' if ok else 'Could not connect. Check your client configuration/test users and try again.'))
        self._worker.finished.connect(self._connected)
        self._worker.start()

    def _connected(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        for button in (self.save_button, self.cancel_button, self.import_button):
            button.setEnabled(True)
        self._calendar_state()

    def reject(self):
        if not self._worker:
            super().reject()

    def closeEvent(self, event):
        if self._worker:
            event.ignore()
        else:
            super().closeEvent(event)

    def _save(self):
        try:
            port = int(self.port.text())
            if not 1 <= port <= 65535:
                raise ValueError('Phone port must be between 1 and 65535.')
            host = self.phone.text().strip()
            if '/' in host or ':' in host:
                raise ValueError('Enter only the phone IP/host; use the separate port field.')
            if self.key.text().strip() and not self.consent.isChecked():
                raise ValueError('Enable cloud AI to use this key, or clear it to continue locally.')
            cfg.GEMINI_API_KEY = self.key.text().strip()
            cfg.GEMINI_MODEL = self.model.text().strip() or cfg.GEMINI_MODEL
            cfg.PHONE_IP, cfg.PHONE_PORT = host, port
            cfg.AUDIO_INPUT_DEVICE = self.microphone.currentData()
            cfg.AUDIO_INPUT_DEVICE_NAME = self.microphone.currentText()
            cfg.WHISPER_MODEL = self.whisper.currentData()
            cfg.MEETING_PROMPTS_ENABLED = self.prompts.isChecked()
            cfg.save_settings()
            from annie.startup import set_enabled
            set_enabled(self.autostart.isChecked())
            atomic_write(SETUP_MARKER, json.dumps({'version': 1}).encode())
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))
