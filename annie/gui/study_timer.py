"""Study-session page, with one-second display ticks and background calendar sync."""
import datetime as dt
import sqlite3
import time

from PyQt5.QtCore import QDate, QDateTime, Qt, QThread, QTime, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                            QPushButton, QComboBox, QInputDialog, QScrollArea, QDialog,
                            QFormLayout, QDateTimeEdit, QSpinBox, QCheckBox, QDialogButtonBox,
                            QMessageBox,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

from annie.gui.design import apply_theme, role, label
from annie.study_sessions import StudyStore, TZ, duration_text


class StudySyncThread(QThread):
    synced = pyqtSignal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

    def run(self):
        try:
            from annie.calendar_service import get_service
            from googleapiclient.errors import HttpError
            service = get_service(interactive=False)
            if service is None:
                raise RuntimeError('Connect Google Calendar to sync your sessions.')
            for session in self.store.pending_sync():
                if self.isInterruptionRequested():
                    return
                body = self.store.event_body(session)
                try:
                    service.events().insert(calendarId='primary', body=body).execute()
                except HttpError as exc:
                    if exc.resp.status != 409:
                        raise
                    # A previous request may have succeeded before losing its reply.
                    existing = service.events().get(calendarId='primary', eventId=body['id']).execute()
                    if existing.get('extendedProperties', {}).get('private', {}).get('annieStudySession') != session['id']:
                        raise RuntimeError('Calendar event ID conflict; session remains saved locally.')
                    changed = _calendar_changes(existing, body)
                    if changed:
                        service.events().patch(calendarId='primary', eventId=body['id'], body=changed).execute()
                self.store.mark_sync(session['id'], revision=session['sync_revision'])
            self.synced.emit('Synced to Google Calendar.')
        except Exception as exc:
            message = str(exc)
            for session in self.store.pending_sync():
                self.store.mark_sync(session['id'], message, revision=session['sync_revision'])
            self.synced.emit('Saved locally · Google Calendar sync pending. You can retry below.')


def _calendar_changes(existing, body):
    changed = {key: body[key] for key in ('summary', 'description') if existing.get(key) != body[key]}
    for key in ('start', 'end'):
        raw = existing.get(key, {}).get('dateTime')
        try:
            same_time = dt.datetime.fromisoformat(raw) == dt.datetime.fromisoformat(body[key]['dateTime'])
        except (ValueError, TypeError):
            same_time = False
        if not same_time:
            changed[key] = body[key]
    return changed


class CompletedSessionDialog(QDialog):
    def __init__(self, subjects, session=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit study session' if session else 'Add completed session')
        self.session = session
        form = QFormLayout(self)
        self.subject = QComboBox()
        for row in subjects:
            self.subject.addItem(row['name'], row['id'])
        if session:
            self.subject.setCurrentIndex(self.subject.findData(session['subject_id']))
        form.addRow('Subject', self.subject)
        self.started = None
        self.sync = None
        if not session:
            start = dt.datetime.now(TZ) - dt.timedelta(minutes=25)
            self.started = QDateTimeEdit(QDateTime(QDate(start.year, start.month, start.day),
                                                   QTime(start.hour, start.minute, start.second)))
            self.started.setCalendarPopup(True)
            self.started.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
            form.addRow('Start (UTC+05)', self.started)
            self.sync = QCheckBox('Sync this session to Google Calendar')
            form.addRow(self.sync)
        initial = max(0, int(session['seconds'])) if session else 25 * 60
        self.original_duration = divmod(initial, 60)
        self.minutes = QSpinBox()
        self.minutes.setMaximum(max(525600, self.original_duration[0]))
        self.minutes.setValue(self.original_duration[0])
        self.minutes.setSuffix(' min')
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 59)
        self.seconds.setValue(self.original_duration[1])
        self.seconds.setSuffix(' s')
        fields = QHBoxLayout()
        fields.addWidget(self.minutes)
        fields.addWidget(self.seconds)
        form.addRow('Active time', fields)
        if session:
            hint = label('A duration correction records one continuous block from the original start.')
            hint.setWordWrap(True)
            form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setEnabled(bool(subjects))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        apply_theme(self)

    def values(self):
        duration = (self.minutes.value(), self.seconds.value())
        seconds = duration[0] * 60 + duration[1]
        if self.session:
            return self.subject.currentData(), None, None if duration == self.original_duration else seconds, False
        when = dt.datetime.combine(self.started.date().toPyDate(), self.started.time().toPyTime(), TZ)
        return self.subject.currentData(), when.timestamp(), seconds, self.sync.isChecked()


class StudyTimerPage(QWidget):
    sessions_changed = pyqtSignal()
    timer_changed = pyqtSignal(str)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or StudyStore()
        self._active = self.store.active()
        self._sync_worker = None
        self._stopping = False
        self._totals_base = (0, 0, 0)
        self._totals_time = 0
        self._totals_day = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName('homeContent')
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)
        layout.addWidget(label('Study time', 'title'))
        subtitle = label('Choose your subject, settle in, and track the time you actually study.')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        stats = QHBoxLayout()
        self.total_labels = []
        for title in ('Today', 'This week', 'Total study hours'):
            card = role(QFrame(), 'panel')
            box = QVBoxLayout(card)
            box.setContentsMargins(14, 10, 14, 10)
            box.addWidget(label(title, 'muted'))
            value = label('0h 00m', 'section')
            self.total_labels.append(value)
            box.addWidget(value)
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        self.timer_card = role(QFrame(), 'panel')
        timer_layout = QVBoxLayout(self.timer_card)
        timer_layout.setContentsMargins(20, 18, 20, 18)
        timer_layout.setSpacing(10)
        selection = QHBoxLayout()
        self.subject_picker = QComboBox()
        self.subject_picker.setMinimumWidth(100)
        self.subject_picker.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.subject_picker.setAccessibleName('Study subject')
        self.subject_picker.currentIndexChanged.connect(self._selection_changed)
        selection.addWidget(self.subject_picker, 1)
        self.add_button = QPushButton('+ New subject')
        self.add_button.clicked.connect(self._add_subject)
        selection.addWidget(self.add_button)
        timer_layout.addLayout(selection)
        self.elapsed_label = label('00:00:00', 'studyClock')
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        self.elapsed_label.setAccessibleName('Active study time')
        timer_layout.addWidget(self.elapsed_label)
        self.session_status = label('Ready for your next session.', 'muted')
        self.session_status.setAlignment(Qt.AlignCenter)
        self.session_status.setWordWrap(True)
        timer_layout.addWidget(self.session_status)
        controls = QHBoxLayout()
        self.start_button = role(QPushButton('Start studying'), 'primary')
        self.start_button.setMinimumHeight(40)
        self.start_button.clicked.connect(self._start)
        self.pause_button = QPushButton('Pause')
        self.pause_button.setMinimumHeight(40)
        self.pause_button.clicked.connect(self._pause_resume)
        self.end_button = role(QPushButton('End session'), 'warmAction')
        self.end_button.setMinimumHeight(40)
        self.end_button.clicked.connect(self._end)
        for button in (self.start_button, self.pause_button, self.end_button):
            controls.addWidget(button, 1)
        timer_layout.addLayout(controls)
        detail = label('Pause for breaks. Running timers continue while Studio is closed.\n'
                       'Completed sessions appear in Schedule. Pending sessions sync when Google Calendar is connected.')
        detail.setAlignment(Qt.AlignCenter)
        detail.setWordWrap(True)
        timer_layout.addWidget(detail)
        layout.addWidget(self.timer_card)

        feedback = QHBoxLayout()
        self.feedback = label('Your progress is saved on this laptop.')
        self.feedback.setWordWrap(True)
        feedback.addWidget(self.feedback, 1)
        self.retry_button = QPushButton('Retry sync')
        self.retry_button.clicked.connect(self.sync_pending)
        feedback.addWidget(self.retry_button)
        layout.addLayout(feedback)
        history_header = QHBoxLayout()
        history_header.addWidget(label('Recent sessions', 'section'), 1)
        self.add_history_button = QPushButton('Add completed session')
        self.add_history_button.clicked.connect(lambda: self._edit_history())
        history_header.addWidget(self.add_history_button)
        self.edit_history_button = QPushButton('Edit session')
        self.edit_history_button.setEnabled(False)
        self.edit_history_button.clicked.connect(self._edit_selected_history)
        history_header.addWidget(self.edit_history_button)
        layout.addLayout(history_header)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(['Subject', 'Started', 'Ended', 'Study time', 'Sync'])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(36)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.itemSelectionChanged.connect(
            lambda: self.edit_history_button.setEnabled(self._selected_history() is not None))
        self.history_table.doubleClicked.connect(lambda: self._edit_selected_history())
        self.history_table.setMinimumHeight(155)
        self.history_table.setMaximumHeight(260)
        self.history_table.setAccessibleName('Completed study sessions')
        layout.addWidget(self.history_table)
        self.empty_history = label('Your first completed session will appear here. Choose a subject above to begin.')
        self.empty_history.setWordWrap(True)
        layout.addWidget(self.empty_history)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(60000)
        self._retry_timer.timeout.connect(self.sync_pending)
        self._retry_timer.start()
        self._load_subjects()
        self._refresh()
        QTimer.singleShot(1000, self.sync_pending)

    def _load_subjects(self, selected=None):
        selected = selected or (self._active['subject_id'] if self._active else self.subject_picker.currentData())
        self.subject_picker.blockSignals(True)
        self.subject_picker.clear()
        self.subject_picker.addItem('Choose what you are studying…', None)
        for subject in self.store.subjects():
            self.subject_picker.addItem(subject['name'], subject['id'])
        self.subject_picker.setCurrentIndex(max(0, self.subject_picker.findData(selected)))
        self.subject_picker.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self):
        if hasattr(self, 'start_button'):
            self.start_button.setEnabled(bool(self.subject_picker.currentData()) and not self._active)

    def _add_subject(self):
        name, accepted = QInputDialog.getText(self, 'New study subject', 'What are you studying?')
        if accepted:
            try:
                subject = self.store.add_subject(name)
                self._load_subjects(subject['id'])
            except Exception as exc:
                self.feedback.setText(str(exc))

    def _start(self):
        try:
            self._active = self.store.start(self.subject_picker.currentData(), sync=True)
            self.feedback.setText('Session started. Pause whenever you take a break.')
            self._refresh()
        except Exception as exc:
            self.feedback.setText(str(exc))

    def _pause_resume(self):
        if self._active:
            self._transition('pause' if self._active['state'] == 'running' else 'resume')

    def _transition(self, action):
        try:
            self.store.transition(self._active['id'], action)
            self._refresh()
        except Exception as exc:
            self.feedback.setText(str(exc))

    def _end(self):
        if not self._active:
            return
        try:
            session = self.store.transition(self._active['id'], 'end')
            seconds = self.store.elapsed(session['id'])
            self.feedback.setText(f"Saved · {session['subject']} · {duration_text(seconds)}")
            self._refresh()
            self.sessions_changed.emit()
            self.sync_pending()
        except Exception as exc:
            self.feedback.setText(str(exc))

    def _refresh(self):
        self._active = self.store.active()
        active = self._active is not None
        self.subject_picker.setEnabled(not active)
        self.add_button.setEnabled(not active)
        self.start_button.setVisible(not active)
        self.pause_button.setVisible(active)
        self.end_button.setVisible(active)
        self._selection_changed()
        if active:
            self.pause_button.setText('Resume' if self._active['state'] == 'paused' else 'Pause')
            started = dt.datetime.fromtimestamp(self._active['started'], TZ)
            self.session_status.setText(f"{'Paused · breaks are excluded' if self._active['state'] == 'paused' else 'Studying'} · Started {started:%d %b, %H:%M}")
            self._elapsed_base = self.store.elapsed(self._active['id'])
        else:
            self._elapsed_base = 0
            self.session_status.setText('Ready for your next session.')
        self._elapsed_time = time.time()
        self._refresh_totals()
        self._refresh_history()
        self._tick()

    def _refresh_totals(self):
        now = time.time()
        date = dt.datetime.fromtimestamp(now, TZ).date()
        day_start = dt.datetime.combine(date, dt.time(), TZ).timestamp()
        week_start = dt.datetime.combine(date - dt.timedelta(days=date.weekday()), dt.time(), TZ).timestamp()
        self._totals_base = tuple(self.store.totals(start, now) for start in (day_start, week_start, 0))
        self._totals_time = now
        self._totals_day = date

    def _tick(self):
        now = time.time()
        if dt.datetime.fromtimestamp(now, TZ).date() != self._totals_day:
            self._refresh_totals()
        running = self._active is not None and self._active['state'] == 'running'
        seconds = self._elapsed_base + (max(0, now - self._elapsed_time) if running else 0)
        self.elapsed_label.setText(duration_text(seconds, clock=True))
        delta = max(0, now - self._totals_time) if running else 0
        for widget, total in zip(self.total_labels, self._totals_base):
            widget.setText(duration_text(total + delta))
        text = ('Paused · ' if self._active and not running else 'Study · ') + duration_text(seconds, clock=True)
        self.timer_changed.emit(text if self._active else '')

    def _refresh_history(self):
        selected = self._selected_history()
        sessions = self.store.history(50)
        self.history_table.setVisible(bool(sessions))
        self.empty_history.setVisible(not sessions)
        self.history_table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            values = (session['subject'], dt.datetime.fromtimestamp(session['started'], TZ).strftime('%d %b %H:%M'),
                      dt.datetime.fromtimestamp(session['ended'], TZ).strftime('%d %b %H:%M'),
                      duration_text(session['seconds']), session['sync_state'].capitalize())
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip('Google Calendar: ' + session['sync_state'])
                if column == 0:
                    item.setData(Qt.UserRole, session)
                self.history_table.setItem(row, column, item)
            if selected and selected['id'] == session['id']:
                self.history_table.selectRow(row)
        self.retry_button.setVisible(bool(self.store.pending_sync()))

    def _selected_history(self):
        row = self.history_table.currentRow()
        item = self.history_table.item(row, 0)
        return item.data(Qt.UserRole) if item and item.isSelected() else None

    def _edit_selected_history(self):
        session = self._selected_history()
        if session:
            self._edit_history(session)

    def _edit_history(self, session=None):
        subjects = self.store.subjects()
        if not subjects:
            QMessageBox.information(self, 'Add a study subject', 'Create a subject before logging a completed session.')
            return
        dialog = CompletedSessionDialog(subjects, session, self)
        while dialog.exec_() == QDialog.Accepted:
            subject, started, seconds, sync = dialog.values()
            try:
                updated = (self.store.update_completed(session['id'], subject, seconds)
                           if session else self.store.record_completed(subject, started, seconds, sync=sync))
            except (ValueError, OSError, sqlite3.Error) as exc:
                QMessageBox.warning(dialog, 'Could not save session', str(exc))
                continue
            self.feedback.setText(f"Saved completed session · {updated['subject']}")
            self._refresh()
            self.sessions_changed.emit()
            self.sync_pending()
            return

    def sync_pending(self):
        if self._stopping or self._sync_worker is not None or not self.store.pending_sync():
            return
        self.retry_button.setEnabled(False)
        self._sync_worker = StudySyncThread(self.store, self)
        self._sync_worker.synced.connect(self._sync_result)
        self._sync_worker.finished.connect(self._sync_finished)
        self._sync_worker.start()

    def _sync_result(self, message):
        self.feedback.setText(message)
        self._refresh_history()
        self.sessions_changed.emit()

    def _sync_finished(self):
        worker = self._sync_worker
        self._sync_worker = None
        self.retry_button.setEnabled(True)
        if worker:
            worker.deleteLater()

    def has_running_job(self):
        return self._sync_worker is not None

    def stop_background(self):
        self._stopping = True
        self._timer.stop()
        self._retry_timer.stop()
        if self._sync_worker:
            self._sync_worker.requestInterruption()

    def resume_background(self):
        self._stopping = False
        self._timer.start()
        self._retry_timer.start()
        self._refresh()
        self.sync_pending()
