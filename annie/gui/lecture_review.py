"""Review source evidence before creating a local deadline or study action."""
import datetime as dt
import sqlite3

from PyQt5.QtCore import QThread, Qt, pyqtSignal, QDateTime
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QListWidget,
                            QListWidgetItem, QPushButton, QSplitter, QTextEdit,
                            QVBoxLayout, QWidget, QCheckBox, QDateTimeEdit)

from annie.gui.design import label, role
from annie.lecture_actions import (ActionStore, extract_actions, normalize_segments,
                                   transcript_fingerprint)
from annie.lecture_reconciliation import analyze_lecture
from annie.obligations import ObligationStore


def _clock(seconds):
    seconds = int(seconds)
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class LectureActionScan(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, segments, course, source_name, lecture_date, generator=None, parent=None,
                 *, reconcile=False, current=()):
        super().__init__(parent)
        self.segments, self.course, self.source_name = segments, course, source_name
        self.lecture_date, self.generator = lecture_date, generator
        self.reconcile, self.current = reconcile, current

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            if self.reconcile:
                result = analyze_lecture(self.segments, self.course, self.source_name,
                    self.lecture_date, current=self.current, generator=self.generator)
            else:
                result = extract_actions(self.segments, self.course, self.source_name,
                                         self.generator, self.lecture_date)
            if not self.isInterruptionRequested():
                self.result.emit(result)
        except Exception as exc:
            # Network exceptions can contain request headers and credentials.
            self.error.emit(str(exc) if isinstance(exc, ValueError) else
                            'Lecture analysis failed. Your transcript is preserved; try again.')


class LectureReviewPage(QWidget):
    actions_changed = pyqtSignal()
    evidence_requested = pyqtSignal(float)

    def __init__(self, parent=None, store=None, generator=None):
        super().__init__(parent)
        self.store = store or ActionStore()
        self.obligations = ObligationStore(self.store.root)
        self.generator = generator
        # The old injected generator remains usable by existing offline fixtures.
        # Production uses the combined source-checked reconciliation response.
        self.analysis_generator = None
        self._worker = None
        self._segments, self._fingerprint = [], ''
        self._course, self._source_name, self._lecture_date = '', 'Lecture', None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        heading = QHBoxLayout()
        heading.addWidget(label('Review lecture actions', 'title'), 1)
        self.scan_button = role(QPushButton('Analyze current lecture'), 'primary')
        self.scan_button.clicked.connect(self.analyze)
        self.scan_button.setEnabled(False)
        heading.addWidget(self.scan_button)
        layout.addLayout(heading)
        intro = label('Muse Spark proposes actions. Check the transcript quote and interpretation before approving. '
                      'Approved items stay local; deadlines appear in your Inbox and study actions in Today.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.source_label = label('Record or import a timestamped lecture to begin.', 'muted')
        self.source_label.setTextFormat(Qt.PlainText)
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.filter = QComboBox()
        self.filter.addItem('Pending review', 'pending')
        self.filter.addItem('Approved', 'approved')
        self.filter.addItem('Rejected', 'rejected')
        self.filter.addItem('All findings', None)
        self.filter.currentIndexChanged.connect(self.reload)
        layout.addWidget(self.filter)
        splitter = QSplitter(Qt.Horizontal)
        self.findings = QListWidget()
        self.findings.setWordWrap(True)
        self.findings.setTextElideMode(Qt.ElideNone)
        self.findings.currentItemChanged.connect(self._selected)
        splitter.addWidget(self.findings)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self.evidence = QTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setPlaceholderText('Choose a finding to inspect its exact evidence.')
        detail_layout.addWidget(self.evidence, 1)
        self.date_input = QLineEdit()
        self.date_input.setPlaceholderText('Confirm due date: 2026-11-03T17:00+05:00')
        self.date_input.setAccessibleName('Confirmed deadline date and time')
        detail_layout.addWidget(self.date_input)
        self.due_editor = QDateTimeEdit()
        self.due_editor.setCalendarPopup(True)
        self.due_editor.setDisplayFormat('dd MMM yyyy  HH:mm')
        self.due_editor.setAccessibleName('Confirmed deadline date and time, UTC plus five')
        self.due_editor.dateTimeChanged.connect(self._date_changed)
        detail_layout.addWidget(self.due_editor)
        self.confirm_date = QCheckBox('I checked the assignment and confirmed this date and time (UTC+05).')
        self.confirm_date.setAccessibleName('Confirm assignment identity and deadline date')
        detail_layout.addWidget(self.confirm_date)
        actions = QHBoxLayout()
        self.evidence_button = QPushButton('Go to transcript time')
        self.evidence_button.clicked.connect(self._open_evidence)
        self.approve_button = role(QPushButton('Approve'), 'primary')
        self.approve_button.clicked.connect(self._approve)
        self.reject_button = QPushButton('Reject')
        self.reject_button.clicked.connect(self._reject)
        for button in (self.evidence_button, self.approve_button, self.reject_button):
            actions.addWidget(button)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.status = label('No analysis has been run. Cloud analysis sends this lecture text to Meta.', 'muted')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.reload()

    def set_transcript(self, segments, course='', source_name='Lecture', lecture_date=None):
        if not segments:
            self._segments, self._fingerprint = [], ''
            self.scan_button.setEnabled(False)
            self.source_label.setText('Record or import a timestamped lecture to begin.')
            return
        normalized = normalize_segments(segments)
        self._segments = normalized
        self._fingerprint = transcript_fingerprint(normalized)
        self._course, self._source_name, self._lecture_date = course, source_name, lecture_date
        self.source_label.setText(f'{course or "Unspecified course"} · {source_name} · '
                                  f'{len(normalized)} timestamped segments. Analysis sends text to Meta.')
        self.scan_button.setEnabled(not self.has_running_job())

    def _current(self):
        item = self.findings.currentItem()
        return item.data(Qt.UserRole) if item else None

    def reload(self, *_):
        previous = (self._current() or {}).get('id')
        self.findings.clear()
        try:
            rows = self.store.list_actions(self.filter.currentData())
            self.obligations.drain_outbox()
            proposals = self.obligations.list_proposals(self.filter.currentData())
            for proposal in proposals:
                ref = proposal['evidence'][-1]
                rows.insert(0, {**proposal, '_obligation': True, 'summary': proposal['title'],
                    'type': 'deadline', 't_start': ref['start'], 't_end': ref['end'],
                    'source': ref['source'], 'due_at': proposal.get('confirmed_due_at') or proposal['proposed_due_at']})
        except (ValueError, OSError):
            self.status.setText('Could not read the local review queue.')
            rows = []
        for action in rows:
            relationship = (' · ' + action['relation'].replace('_', ' ')) if action.get('_obligation') else ''
            item = QListWidgetItem(f'{action["summary"]}\n'
                                   f'{action["course"] or "Lecture"} · {action["type"].replace("_", " ")} '
                                   f'· {_clock(action["t_start"])} · {action["status"]}{relationship}')
            item.setData(Qt.UserRole, action)
            self.findings.addItem(item)
            if action['id'] == previous:
                self.findings.setCurrentItem(item)
        if self.findings.currentRow() < 0 and rows:
            self.findings.setCurrentRow(0)
        self._selected()

    def _selected(self, *_):
        action = self._current()
        pending = bool(action and action['status'] == 'pending')
        self.approve_button.setEnabled(pending)
        self.reject_button.setEnabled(pending)
        self.evidence_button.setEnabled(bool(action))
        deadline = bool(action and action['type'] == 'deadline')
        obligation = bool(action and action.get('_obligation'))
        self.date_input.setVisible(deadline and not obligation)
        self.date_input.setEnabled(pending)
        self.date_input.setText(action.get('due_at') or '' if action else '')
        self.due_editor.setVisible(obligation)
        self.confirm_date.setVisible(obligation)
        self.due_editor.setEnabled(pending)
        self.confirm_date.setChecked(False)
        self._manual_date_selected = bool(action and action.get('due_at'))
        if obligation:
            due = QDateTime.fromString((action.get('due_at') or '')[:16], 'yyyy-MM-ddTHH:mm')
            if not due.isValid():
                due = QDateTime.fromString(dt.datetime.now().strftime('%Y-%m-%dT17:00'), 'yyyy-MM-ddTHH:mm')
            self.due_editor.blockSignals(True)
            self.due_editor.setDateTime(due)
            self.due_editor.blockSignals(False)
            self.confirm_date.setEnabled(pending and self._manual_date_selected)
        self.approve_button.setText('Confirm deadline' if obligation else 'Approve')
        if not action:
            self.evidence.clear()
            return
        if obligation:
            details = [action['title'], '',
                'Relationship: ' + action['relation'].replace('_', ' '),
                'Previously confirmed' if action.get('assignment_id') else 'Earlier statement',
                action.get('previous_due_at') or 'No previously confirmed date', '',
                'Proposed: ' + (action['proposed_due_at'] or 'Unresolved — choose and confirm a date'),
                '', action['reason'], '', 'TRANSCRIPT EVIDENCE']
            for ref in action.get('previous_evidence', []):
                details += [f'Previous source: {ref["source"]} · {_clock(ref["start"])}', ref['quote'], '']
            for index, ref in enumerate(action['evidence'], 1):
                details += [f'{index}. {ref["source"]} · {_clock(ref["start"])} – {_clock(ref["end"])}', ref['quote'], '']
            details += ['Quotes are checked against the saved transcript. Interpretation still needs your review.',
                'On confirmation: one active deadline in your local Inbox; earlier versions remain in history.']
            if not self._manual_date_selected:
                details += ['No reliable date was found. Choose a date/time before confirming; the picker is only an unconfirmed starting value.']
            if action.get('delivery_pending'):
                details += ['Confirmed, syncing to Inbox. Retry delivery or reopen Review to recover.']
            self.evidence.setPlainText('\n'.join(details))
            return
        details = [action['summary'], '', f'Source: {action["source_name"]} / {action["source"]}',
                   f'Transcript time: {_clock(action["t_start"])} – {_clock(action["t_end"])}',
                   '', action['quote'], '', action['evidence_check'],
                   f'Model confidence (not calibrated): {action["confidence"]:.0%}', '',
                   f'Suggested action: {action["suggested_action"]}',
                   f'Estimated study time: {action["minutes"]} min']
        if action.get('needs_date'):
            details += ['', 'The date was ambiguous or unsupported. Enter a confirmed date and time to approve.']
        elif deadline:
            details += ['', f'Proposed due date: {action["due_at"]}. Check the date and time against the source.']
        self.evidence.setPlainText('\n'.join(details))

    def analyze(self):
        if self.has_running_job() or not self._segments:
            return
        self.scan_button.setEnabled(False)
        self.status.setText('Sending the current transcript to Meta and checking the returned evidence…')
        try:
            current = self.obligations.list_current(self._course or 'Unspecified course')
        except (ValueError, OSError, sqlite3.Error):
            self.status.setText('Could not read confirmed deadlines. Analysis was not sent.')
            self.scan_button.setEnabled(True)
            return
        reconcile = self.generator is None or self.analysis_generator is not None
        generator = self.analysis_generator if reconcile else self.generator
        self._worker = LectureActionScan(list(self._segments), self._course, self._source_name,
            self._lecture_date, generator, self, reconcile=reconcile, current=current)
        self._worker.result.connect(self._result)
        self._worker.error.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _result(self, result):
        worker = self._worker
        if (worker is None or result.fingerprint != self._fingerprint
                or worker.course != self._course or worker.source_name != self._source_name):
            self.status.setText('The transcript changed during analysis. Analyze it again to review current evidence.')
            return
        try:
            scan = result.study_scan if hasattr(result, 'study_scan') else result
            added = self.store.add_scan(scan, worker.segments, worker.course, worker.source_name, worker.lecture_date)
            if hasattr(result, 'proposals'):
                for proposal in result.proposals:
                    self.obligations.propose(proposal)
                added += len(result.proposals)
            self.status.setText(f'{added} new finding(s) awaiting review; '
                                f'{result.rejected_count} unsupported item(s) discarded. '
                                'Quote checks confirm the transcript location, not the interpretation.')
            self.reload()
            self.actions_changed.emit()
        except ValueError as exc:
            self.status.setText(str(exc))
        except (OSError, sqlite3.Error):
            self.status.setText('Could not save the local review queue. Check available disk space and try again.')

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker:
            worker.deleteLater()
        self.scan_button.setEnabled(bool(self._segments))

    def _approve(self):
        action = self._current()
        if not action:
            return
        try:
            # Historical findings retain their own immutable transcript snapshot.
            # For findings from the active source, reject stale revisions.
            expected = self._fingerprint if self._segments and action['source_name'] == self._source_name else None
            if action.get('_obligation'):
                if not self.confirm_date.isChecked() or not self._manual_date_selected:
                    self.status.setText('Check the assignment, choose a date/time, and tick the confirmation before saving.')
                    return
                due = self.due_editor.dateTime().toString('yyyy-MM-ddTHH:mm') + '+05:00'
                saved = self.obligations.approve(action['id'], due_at=due, expected_fingerprint=expected)
                self.status.setText('Confirmed, syncing to Inbox. Reopen Review to retry delivery.'
                    if saved.get('delivery_pending') else 'Saved to Inbox. One active deadline; previous versions are retained.')
                self.reload()
                self.actions_changed.emit()
                return
            due = self.date_input.text().strip() if action['type'] == 'deadline' else None
            self.store.approve(action['id'], expected_fingerprint=expected, due_at=due or None)
            self.status.setText('Approved locally. The deadline is in Inbox or the study action is in Today.')
            self.reload()
            self.actions_changed.emit()
        except ValueError as exc:
            self.status.setText(str(exc))
        except (OSError, sqlite3.Error):
            self.status.setText('Could not save this approval. The finding remains available for review.')

    def _reject(self):
        action = self._current()
        if action:
            try:
                (self.obligations if action.get('_obligation') else self.store).reject(action['id'])
                self.reload()
                self.actions_changed.emit()
            except ValueError as exc:
                self.status.setText(str(exc))

    def _open_evidence(self):
        action = self._current()
        if action:
            self.evidence_requested.emit(action['t_start'])

    def has_running_job(self):
        return self._worker is not None

    def _date_changed(self, *_):
        self._manual_date_selected = True
        self.confirm_date.setChecked(False)
        self.confirm_date.setEnabled(True)

    def stop_background(self):
        # The owner uses has_running_job() to keep the page alive until the
        # bounded network call finishes. Never terminate a Python worker thread.
        if self._worker:
            self._worker.requestInterruption()
