"""A small, on-demand connection check before enabling Moodle planning features."""
import datetime as dt
import webbrowser

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                            QPushButton, QListWidget)

from annie.gui.design import apply_theme, label, role
from annie.moodle_calendar import MoodleConnection, MoodleError


class MoodleCheck(QThread):
    result = pyqtSignal(object, str)

    def __init__(self, connection, url, parent=None):
        super().__init__(parent)
        self.connection, self.url = connection, url

    def run(self):
        try:
            self.result.emit(self.connection.check(self.url), '')
        except MoodleError as exc:
            self.result.emit(None, str(exc))
        except Exception:
            self.result.emit(None, 'Could not check the calendar. Please try again.')
        finally:
            self.url = ''


class MoodleSetup(QDialog):
    def __init__(self, parent=None, connection=None):
        super().__init__(parent)
        self.connection = connection or MoodleConnection()
        self._worker = None
        self.setWindowTitle('Lecture Studio · Moodle calendar')
        self.resize(620, 610)
        self.setMinimumSize(450, 480)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label('Connect your Moodle calendar', 'title'))
        instructions = label(
            '1. Open Moodle and sign in as usual in your browser.\n'
            '2. Open Calendar → Export calendar.\n'
            '3. Choose All events and Recent and next 60 days.\n'
            '4. Choose Get calendar URL and paste it below.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        browser = QHBoxLayout()
        open_moodle = QPushButton('Open NU Moodle calendar ↗')
        open_moodle.clicked.connect(lambda: webbrowser.open('https://moodle.nu.edu.kz/calendar/view.php'))
        browser.addWidget(open_moodle)
        help_button = QPushButton('Export help ↗')
        help_button.clicked.connect(lambda: webbrowser.open('https://docs.moodle.org/en/Using_Calendar#Calendar_export'))
        browser.addWidget(help_button)
        layout.addLayout(browser)
        self.url = QLineEdit()
        self.url.setEchoMode(QLineEdit.Password)
        self.url.setAccessibleName('Private Moodle calendar export URL')
        self.url.setPlaceholderText('Paste private calendar URL — not your Moodle password')
        self.url.returnPressed.connect(self._check)
        layout.addWidget(self.url)
        privacy = label('The calendar link grants access to your events. It is saved using Windows encryption or macOS Keychain. Your Moodle password is not needed here.')
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        actions = QHBoxLayout()
        self.check_button = role(QPushButton('Check & connect'), 'primary')
        self.check_button.clicked.connect(self._check)
        actions.addWidget(self.check_button, 1)
        self.disconnect_button = QPushButton('Disconnect')
        self.disconnect_button.clicked.connect(self._disconnect)
        actions.addWidget(self.disconnect_button)
        layout.addLayout(actions)
        self.status = label('Not connected yet.')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(label('Calendar events · preview', 'section'))
        self.preview = QListWidget()
        self.preview.setAccessibleName('Preview of up to 50 calendar event titles')
        layout.addWidget(self.preview, 1)
        note = label('This first step checks access and previews event names. Events may include classes, opening dates and deadlines. Automatic syncing and reminders are not enabled yet.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.close_button = QPushButton('Done')
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        self.disconnect_button.setEnabled(self.connection.path.exists())
        try:
            saved = self.connection.read()
            if saved:
                self._display(saved, cached=True)
        except MoodleError as exc:
            self.status.setText(str(exc))
        apply_theme(self)

    def _display(self, data, cached=False):
        preview = data['preview']
        self.preview.clear()
        self.preview.addItems(preview['titles'])
        checked = dt.datetime.fromisoformat(data['checked_at']).astimezone().strftime('%d %b, %H:%M')
        text = f"{'Saved preview' if cached else 'Connected'} · {preview['count']} events · Checked {checked}."
        if not preview['count']:
            text += ' The calendar is valid but empty. Check the export filters and date range in Moodle.'
        elif preview['count'] > 50:
            text += ' Showing the first 50 names in export order.'
        self.status.setText(text)
        self.check_button.setText('Refresh / connect new URL')

    def _check(self):
        if self._worker:
            return
        url = self.url.text().strip()
        self.status.setText('Checking Moodle calendar…')
        for widget in (self.url, self.check_button, self.disconnect_button, self.close_button):
            widget.setEnabled(False)
        self._worker = MoodleCheck(self.connection, url, self)
        self._worker.result.connect(self._result)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _result(self, data, error):
        if error:
            self.status.setText(error + (' Saved connection and preview were kept.' if self.connection.path.exists() else ''))
        else:
            self.url.clear()
            self._display(data)

    def _finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        for widget in (self.url, self.check_button, self.close_button):
            widget.setEnabled(True)
        self.disconnect_button.setEnabled(self.connection.path.exists())

    def _disconnect(self):
        if self._worker:
            return
        try:
            self.connection.disconnect()
            self.url.clear()
            self.preview.clear()
            self.status.setText('Disconnected on this laptop. Moodle events were not changed.')
            self.check_button.setText('Check & connect')
            self.disconnect_button.setEnabled(False)
        except MoodleError as exc:
            self.status.setText(str(exc))

    def reject(self):
        if not self._worker:
            super().reject()

    def closeEvent(self, event):
        if self._worker:
            event.ignore()
        else:
            super().closeEvent(event)
