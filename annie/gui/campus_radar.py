"""Native coursework review and explicitly enabled local browser receiver."""
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qsl, urlsplit

from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QHeaderView,
    QListWidget, QListWidgetItem, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QApplication, QLineEdit,
    QSystemTrayIcon, QStyle)

from annie.gui.design import label, role


_KINDS = {'webwork': 'WeBWorK', 'moodle': 'Moodle', 'gmail': 'Gmail'}
_STATES = {'unverified': 'Not checked', 'success': 'Successful capture',
           'ok': 'Successful capture', 'partial': 'Partial capture', 'error': 'Check failed'}
_EVENTS = {'first_seen': 'First observed', 'discovered': 'Newly observed item',
           'due_changed': 'Due date changed', 'closes_changed': 'Closing time changed',
           'status_changed': 'Status changed'}
_TZ = dt.timezone(dt.timedelta(hours=5))


def _safe_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2000 or any(ord(c) < 32 for c in value):
        raise ValueError('A valid HTTPS source link is required.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        banned = {'token', 'access_token', 'refresh_token', 'id_token', 'auth', 'authorization',
                  'session', 'sessionid', 'sesskey', 'password', 'passwd', 'api_key', 'apikey', 'key', 'code'}
        if any(key.casefold() in banned for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ValueError
    except ValueError:
        raise ValueError('Use an ordinary HTTPS source link without login credentials or authentication tokens.') from None
    return value


def _when(value):
    if value is None or value == '':
        return 'Never / unknown'
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(_TZ).strftime('%d %b %Y %H:%M') + ' UTC+05'
    except (TypeError, ValueError):
        return 'Unknown check time'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('The captured snapshot contains duplicate JSON keys.')
        result[key] = value
    return result


def read_captured_snapshot(path):
    """Strict local envelope, checked before any metadata or item is persisted."""
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError('Choose a captured snapshot smaller than 1 MB.')
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError('Choose a captured snapshot smaller than 1 MB.')
    try:
        text = raw.decode('utf-8-sig')
        data = json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number.')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('Choose a UTF-8 captured coursework snapshot JSON file.') from None
    if not isinstance(data, dict) or set(data) != {'source', 'checked_at', 'complete', 'items'}:
        raise ValueError('A captured snapshot needs source, checked_at, complete and items only.')
    source = data['source']
    if (not isinstance(source, dict) or set(source) != {'source_id', 'kind', 'name', 'url', 'scope'}
            or not isinstance(source['kind'], str) or source['kind'] not in _KINDS
            or not isinstance(source['scope'], str) or source['scope'] not in ('assignment', 'course')):
        raise ValueError('Choose a supported source with an explicit assignment or course scope.')
    for name, maximum in (('source_id', 128), ('name', 200)):
        if not isinstance(source[name], str) or not source[name].strip() or len(source[name]) > maximum:
            raise ValueError('Invalid captured source metadata.')
    _safe_url(source['url'])
    if not isinstance(data['complete'], bool):
        raise ValueError('The complete field must be a boolean.')
    try:
        checked_at = dt.datetime.fromisoformat(data['checked_at'])
        if checked_at.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('The captured check time needs an ISO date/time with timezone.') from None
    if not isinstance(data['items'], list) or len(data['items']) > 500:
        raise ValueError('A captured snapshot may contain at most 500 items.')
    item_keys = {'external_id', 'title', 'course', 'due_at', 'raw_due_text', 'source_url', 'status'}
    for item in data['items']:
        if (not isinstance(item, dict) or not item_keys.issubset(item)
                or set(item) - item_keys - {'closes_at', 'raw_close_text'}):
            raise ValueError('Every captured item needs exactly the documented coursework fields.')
        for field, maximum, empty in (('external_id', 200, False), ('title', 300, False),
                                      ('course', 200, True), ('raw_due_text', 1500, True), ('status', 100, False)):
            value = item[field]
            if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
                raise ValueError('A captured coursework item has invalid text fields.')
        _safe_url(item['source_url'])
        if ('raw_close_text' in item and (not isinstance(item['raw_close_text'], str)
                or len(item['raw_close_text']) > 1500)):
            raise ValueError('A captured closing-time quote must be bounded plain text.')
        for field in ('due_at', 'closes_at'):
            if item.get(field) is not None:
                try:
                    parsed = dt.datetime.fromisoformat(item[field])
                    if parsed.utcoffset() is None:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValueError(f'Use a timezone-aware {field}, or null when the source date is unknown.') from None
    # Captures contain coursework, never copied credentials or authentication headers.
    if re.search(r'LLM_\d{10,}_[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{25,}|Bearer\s+[A-Za-z0-9._-]{20,}', text):
        raise ValueError('Remove credentials and authentication data from this captured snapshot.')
    return data


class RadarPage(QWidget):
    changes_updated = pyqtSignal()
    capture_received = pyqtSignal()

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.setObjectName('annieSurface')
        from annie.campus_radar import RadarStore
        try:
            self.store = RadarStore(root)
        except (ValueError, OSError, sqlite3.Error):
            self.store = None
        self._sources, self._events = [], []
        self._selected = None
        self._selected_kind = None
        self.receiver = None
        self.tray = None
        self.capture_received.connect(self._received)
        self.delivery_timer = QTimer(self)
        self.delivery_timer.setInterval(10000)
        self.delivery_timer.timeout.connect(self._deliver)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        heading = QHBoxLayout()
        heading.addWidget(label('Campus Radar', 'title'), 1)
        self.refresh_button = QPushButton('Refresh local view')
        self.refresh_button.clicked.connect(self.reload)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)
        self.intro = label('Watch selected WebWork courses with the browser extension, or import a captured snapshot manually. Review exactly what changed and when the source was last checked.', 'muted')
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        connection = QHBoxLayout()
        self.receiver_button = QPushButton('Enable browser receiver')
        self.receiver_button.clicked.connect(self.toggle_receiver)
        connection.addWidget(self.receiver_button)
        self.pairing = QLineEdit()
        self.pairing.setReadOnly(True)
        self.pairing.setEchoMode(QLineEdit.Password)
        self.pairing.setPlaceholderText('Enable receiver to get a pairing code')
        self.pairing.setAccessibleName('Browser pairing code')
        connection.addWidget(self.pairing, 1)
        self.copy_pairing = QPushButton('Copy pairing code')
        self.copy_pairing.setEnabled(False)
        self.copy_pairing.clicked.connect(lambda: QApplication.clipboard().setText(self.pairing.text()))
        connection.addWidget(self.copy_pairing)
        layout.addLayout(connection)
        self.connection_status = label('Receiver off. Automatic capture needs the Campus Radar Chrome extension, an explicitly watched course, a signed-in course tab and this app running.', 'muted')
        self.connection_status.setWordWrap(True)
        self.connection_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.connection_status)
        self.coverage_label = label('', 'muted')
        self.coverage_label.setWordWrap(True)
        layout.addWidget(self.coverage_label)
        layout.addWidget(label('Source coverage and freshness', 'section'))
        self.sources_table = QTableWidget(0, 4)
        self.sources_table.setHorizontalHeaderLabels(['Source', 'Scope', 'Last success', 'Current state'])
        self.sources_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sources_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sources_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sources_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sources_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.sources_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.sources_table.setMinimumHeight(100)
        self.sources_table.setMaximumHeight(190)
        self.sources_table.itemSelectionChanged.connect(self._source_selected)
        layout.addWidget(self.sources_table)
        changes_header = QHBoxLayout()
        changes_header.addWidget(label('Recorded changes', 'section'), 1)
        self.unread_only = QCheckBox('Unreviewed only')
        self.unread_only.setChecked(True)
        self.unread_only.toggled.connect(self.reload)
        changes_header.addWidget(self.unread_only)
        layout.addLayout(changes_header)
        split = QSplitter(Qt.Horizontal)
        self.events_list = QListWidget()
        self.events_list.setWordWrap(True)
        self.events_list.setTextElideMode(Qt.ElideNone)
        self.events_list.currentItemChanged.connect(self._event_selected)
        split.addWidget(self.events_list)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Choose a source to inspect freshness, or a change to inspect old/new values and evidence.')
        split.addWidget(self.details)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)
        actions = QHBoxLayout()
        self.mark_button = role(QPushButton('Mark change reviewed'), 'primary')
        self.mark_button.setEnabled(False)
        self.mark_button.clicked.connect(self.mark_reviewed)
        actions.addWidget(self.mark_button)
        self.open_button = QPushButton('Open source')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_source)
        actions.addWidget(self.open_button)
        self.import_button = QPushButton('Import manually captured snapshot…')
        self.import_button.clicked.connect(self.choose_snapshot)
        actions.addWidget(self.import_button)
        layout.addLayout(actions)
        self.status = label('', 'muted')
        self.status.setWordWrap(True)
        for widget in (self.intro, self.coverage_label, self.status):
            widget.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.reload()

    def toggle_receiver(self):
        if self.receiver is not None:
            self.stop_receiver()
            return
        try:
            from annie.campus_receiver import CampusReceiver, NotificationLedger, pairing_token
            if self.store is None:
                raise ValueError('Storage unavailable')
            token = pairing_token(self.store.root)
            self.ledger = NotificationLedger(self.store)
            receiver = CampusReceiver(self.store, token, self.capture_received.emit)
            receiver.start()
        except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error):
            self.connection_status.setText('Receiver could not start. Another Studio instance may use port 8768, or protected pairing storage is unavailable. No monitoring started.')
            return
        self.receiver = receiver
        self.pairing.setText(token)
        self.copy_pairing.setEnabled(True)
        self.receiver_button.setText('Disable browser receiver')
        self.connection_status.setText('Receiver ready on this computer. Pair the Chrome extension and choose Watch this course. Windows alerts are requested while this app runs; Windows notification settings can suppress them. Closing Studio stops this receiver.')
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
            self.tray.setToolTip('Lecture Studio · Campus Radar')
            self.tray.messageClicked.connect(self._open_radar)
            self.tray.activated.connect(lambda _: self._open_radar())
        self.tray.show()
        self.delivery_timer.start()

    def _open_radar(self):
        window = self.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        if hasattr(window, '_switch_tab'):
            window._switch_tab(12)

    def stop_receiver(self):
        self.delivery_timer.stop()
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver = None
        if self.tray is not None:
            self.tray.hide()
        self.pairing.clear()
        self.copy_pairing.setEnabled(False)
        self.receiver_button.setText('Enable browser receiver')
        self.connection_status.setText('Receiver off. No automatic captures or Windows alerts will be delivered until enabled again.')

    def _received(self):
        self.reload()
        self.changes_updated.emit()
        self._deliver()

    def _deliver(self):
        if self.receiver is None:
            return
        try:
            self.ledger.deliver(self._notify)
        except (OSError, sqlite3.Error):
            self.connection_status.setText('Notification delivery could not read local storage. Review Campus Radar for recorded changes.')

    def _notify(self, title, body):
        if self.tray is None or not QSystemTrayIcon.isSystemTrayAvailable() or not QSystemTrayIcon.supportsMessages():
            self.connection_status.setText('Course captures are saved, but Windows tray notifications are disabled or unavailable. Changes remain unreviewed in Campus Radar; delivery will retry while the receiver runs. No Windows settings were changed by Studio.')
            return False
        self.tray.showMessage(title, body, QSystemTrayIcon.Information, 10000)
        return True  # Request accepted by Qt; this cannot prove Windows displayed it.

    def reload(self, *_):
        selected_id = self._selected.get('id') if self._selected_kind == 'event' and self._selected else None
        self._selected = None
        self.mark_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.sources_table.setRowCount(0)
        self.events_list.clear()
        self.details.clear()
        try:
            if self.store is None:
                raise ValueError('Radar storage is unavailable.')
            self._sources = self.store.sources()
            self._events = self.store.events(unread_only=self.unread_only.isChecked())
            # Baseline history should not bury the currently open assignment.
            self._events.sort(key=lambda e: (0 if e['type'] != 'first_seen' else
                1 if e.get('new_status') == 'open' else 3 if e.get('new_status') == 'closed' else 2))
            coverage = self.store.coverage()
        except (ValueError, OSError, sqlite3.Error):
            self.coverage_label.setText('Source coverage is unavailable. This is not evidence that coursework has not changed.')
            self.status.setText('Local Radar data could not be read. Existing records were left unchanged.')
            return
        assignment_count = sum(s['scope'] == 'assignment' for s in self._sources)
        self.coverage_label.setText(f'{len(self._sources)} source(s) · {assignment_count} assignment-scoped · '
            f'{len(self._sources)-assignment_count} course-scoped. Coverage applies only to each recorded source and capture.')
        self.sources_table.setRowCount(len(self._sources))
        for row, source in enumerate(self._sources):
            cells = [f"{source['name']} · {_KINDS.get(source['kind'], source['kind'])}",
                'Assignment only' if source['scope'] == 'assignment' else 'Course source',
                _when(source.get('last_success_at')), _STATES.get(source['state'], source['state'])]
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.UserRole, source)
                self.sources_table.setItem(row, column, cell)
        self.sources_table.resizeRowsToContents()
        for event in self._events[:200]:
            closes = ('\nCloses: ' + _when(event['new_closes_at'])) if event.get('new_closes_at') else ''
            entry = QListWidgetItem(f"{event['title']}\n{_EVENTS.get(event['type'], event['type'])} · "
                f"{event.get('course') or 'Course unspecified'} · {_when(event.get('observed_at'))}{closes}")
            entry.setData(Qt.UserRole, event)
            self.events_list.addItem(entry)
            if event['id'] == selected_id:
                self.events_list.setCurrentItem(entry)
        errors = sum(source['state'] == 'error' for source in self._sources)
        partial = sum(source['state'] == 'partial' for source in self._sources)
        if errors or partial:
            self.status.setText(f'{errors} source check(s) failed; {partial} capture(s) are partial. '
                'Some coursework may be unknown. Review source freshness; absence of a change is not a clean check.')
        elif not self._sources:
            self.status.setText('No sources have been recorded. Pair the extension and watch a course, or import a manually captured snapshot. No course has been successfully checked yet.')
        elif not self._events:
            self.status.setText('No recorded changes match this local filter. Check source freshness and coverage; this does not establish that there is no new coursework.')
        else:
            self.status.setText(f'Showing {min(200, len(self._events))} recorded change(s). '
                'First observed means first captured here, not newly published by the instructor.')
        if self.events_list.count() and self.events_list.currentRow() < 0:
            self.events_list.setCurrentRow(0)

    def _source_selected(self):
        rows = self.sources_table.selectionModel().selectedRows()
        if not rows:
            return
        source = self.sources_table.item(rows[0].row(), 0).data(Qt.UserRole)
        self._selected, self._selected_kind = source, 'source'
        self.mark_button.setEnabled(False)
        self.open_button.setEnabled(bool(source.get('url')))
        lines = [source['name'], f"Platform: {_KINDS.get(source['kind'], source['kind'])}",
            'Scope: assignment only — this does not cover the whole course.' if source['scope'] == 'assignment'
            else 'Scope: course source — coverage still depends on a complete, successful capture.',
            '', 'Current state: ' + _STATES.get(source['state'], source['state']),
            'Last successful capture: ' + _when(source.get('last_success_at')),
            'Last attempted capture: ' + _when(source.get('last_attempt_at'))]
        if source.get('last_error'):
            lines += ['', 'Check error:', source['last_error']]
        if source['state'] in ('error', 'partial', 'unverified'):
            lines += ['', 'Coverage is incomplete or unverified. This source cannot establish that no coursework changed.']
        lines += ['', 'Source link:', source['url']]
        self.details.setPlainText('\n'.join(lines))

    def _event_selected(self, *_):
        entry = self.events_list.currentItem()
        if entry is None:
            return
        event = entry.data(Qt.UserRole)
        self._selected, self._selected_kind = event, 'event'
        self.mark_button.setEnabled(bool(event.get('unread')))
        self.open_button.setEnabled(bool(event.get('source_url')))
        lines = [event['title'], f"Course: {event.get('course') or 'Unspecified'}",
            'Change: ' + _EVENTS.get(event['type'], event['type']),
            'Observed here: ' + _when(event.get('observed_at')), '']
        if event.get('old_due_at') is not None or event.get('new_due_at') is not None:
            lines += ['Previously recorded due date: ' + _when(event.get('old_due_at')),
                      'Newly recorded due date: ' + _when(event.get('new_due_at'))]
        else:
            lines += ['Due date: not supplied by the captured source.']
        if event.get('old_closes_at') is not None or event.get('new_closes_at') is not None:
            lines += ['Previously recorded closing time: ' + _when(event.get('old_closes_at')),
                      'Newly recorded closing time: ' + _when(event.get('new_closes_at')),
                      'A closing time is not treated as a due date.']
        if event.get('new_raw_close_text'):
            lines += ['Captured closing-time text: ' + event['new_raw_close_text']]
        lines += ['Previous status: ' + (event.get('old_status') or 'Unknown'),
            'New status: ' + (event.get('new_status') or 'Unknown'), '', 'CAPTURED SOURCE EVIDENCE',
            event.get('evidence') or 'No additional source evidence was captured.']
        if event['type'] == 'first_seen':
            lines += ['', 'This is the first local observation, not proof that the assignment was just published.']
        lines += ['', 'Marking reviewed does not complete the assignment or change its due or closing time.',
                  '', 'Source link:', event.get('source_url') or 'No source link recorded.']
        self.details.setPlainText('\n'.join(lines))

    def mark_reviewed(self):
        if self._selected_kind != 'event' or not self._selected or self.store is None:
            return
        try:
            self.store.mark_read(self._selected['id'])
            self.reload()
            self.status.setText('Change marked reviewed locally. The assignment itself was not completed or modified.')
            self.changes_updated.emit()
        except (ValueError, OSError, sqlite3.Error):
            self.status.setText('Could not save the reviewed state. The change remains available.')

    def open_source(self):
        if not self._selected:
            return
        link = self._selected.get('url' if self._selected_kind == 'source' else 'source_url')
        try:
            link = _safe_url(link)
            if not QDesktopServices.openUrl(QUrl(link)):
                raise ValueError
        except ValueError:
            self.status.setText('The source link could not be opened. Use an ordinary HTTPS link without authentication tokens.')

    def choose_snapshot(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import manually captured coursework snapshot', '',
                                            'Captured snapshot (*.json)')
        if path:
            self.import_snapshot(path)

    def import_snapshot(self, path):
        try:
            if self.store is None:
                raise ValueError('Radar storage is unavailable; no snapshot was imported.')
            data = read_captured_snapshot(path)
            events = self.store.import_snapshot(data)
            self.reload()
            self.status.setText(f'Manually captured snapshot imported; {len(events)} recorded change(s). '
                'This did not check the website or start automatic monitoring.'
                + (' This capture is partial; missing items remain unknown.' if not data['complete'] else ''))
            self.changes_updated.emit()
            return True
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else
                                'The captured snapshot could not be read or saved. No automatic website check was performed.')
            return False
