"""Review-first syllabus and assignment deadline capture."""
import datetime as dt
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout,
                            QHeaderView, QLineEdit, QPushButton, QTableWidget,
                            QTableWidgetItem, QTextEdit, QVBoxLayout)

from annie.deadlines import DeadlineCandidate, DeadlineStore, TZ, extract_deadlines
from annie.gui.design import apply_theme, label, role
from annie.study_guide import SUPPORTED_EXTENSIONS, extract_study_source


class DeadlineScan(QThread):
    result = pyqtSignal(object, str, str)

    def __init__(self, course, text='', path='', parent=None):
        super().__init__(parent)
        self.course, self.text, self.path = course, text, path

    def run(self):
        try:
            if self.path:
                source = extract_study_source(self.path)
            else:
                source = type('Source', (), {'name': 'Pasted assignment text',
                                             'text': self.text})()
            candidates = extract_deadlines(source.name, source.text, self.course)
            self.result.emit(candidates, source.name, '')
        except Exception as exc:
            # Cloud/client exceptions can include implementation details or keys.
            message = str(exc) if isinstance(exc, ValueError) else 'Could not analyze this source. Check your AI setup and try again.'
            self.result.emit([], '', message)
        finally:
            self.text = ''


class DeadlineInbox(QDialog):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or DeadlineStore()
        self._worker = None
        self._file = ''
        self._source_name = ''
        self.setWindowTitle('Lecture Studio · Deadline Inbox')
        self.resize(900, 700)
        self.setMinimumSize(650, 520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(label('Deadline Inbox', 'title'))
        intro = label('Import a syllabus or paste the visible text from an Assignment or Quiz page. Review every date before saving it.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.course = QLineEdit()
        self.course.setPlaceholderText('Course, for example MATH 251')
        layout.addWidget(self.course)
        source_actions = QHBoxLayout()
        self.file_button = QPushButton('Choose syllabus…')
        self.file_button.clicked.connect(self._choose_file)
        source_actions.addWidget(self.file_button)
        self.clear_file_button = QPushButton('Use pasted text')
        self.clear_file_button.clicked.connect(self._clear_file)
        source_actions.addWidget(self.clear_file_button)
        self.file_label = label('No syllabus selected')
        source_actions.addWidget(self.file_label, 1)
        layout.addLayout(source_actions)
        self.text = QTextEdit()
        self.text.setPlaceholderText('Paste the assignment or quiz description here. You can copy the visible page text after signing in to Moodle in your browser.')
        self.text.setMaximumHeight(150)
        layout.addWidget(self.text)
        self.scan_button = role(QPushButton('Find deadline candidates'), 'primary')
        self.scan_button.clicked.connect(self._scan)
        layout.addWidget(self.scan_button)
        self.status = label('Nothing has been analyzed yet.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Add', 'Title', 'Due (UTC+05)', 'Certainty', 'Source evidence'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        help_text = label('Double-click a title or date to correct it. “Assumed time” means the source gave a date but no clock time, so Studio uses 23:59. Saved items remain local in this step.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        actions = QHBoxLayout()
        self.save_button = role(QPushButton('Save selected'), 'primary')
        self.save_button.clicked.connect(self._save)
        self.save_button.setEnabled(False)
        actions.addWidget(self.save_button)
        self.close_button = QPushButton('Done')
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        apply_theme(self)

    def _choose_file(self):
        extensions = ' '.join('*' + ext for ext in sorted(SUPPORTED_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, 'Choose syllabus', '',
                                              f'Study files ({extensions});;All files (*)')
        if path:
            self._file = path
            self.file_label.setText(Path(path).name)
            self.text.setEnabled(False)

    def _clear_file(self):
        self._file = ''
        self.file_label.setText('Using pasted assignment text')
        self.text.setEnabled(True)
        self.text.setFocus()

    def _set_busy(self, busy):
        for widget in (self.course, self.file_button, self.clear_file_button,
                       self.text, self.scan_button, self.close_button):
            widget.setEnabled(not busy)
        if not busy and self._file:
            self.text.setEnabled(False)

    def _scan(self):
        if self._worker:
            return
        pasted = self.text.toPlainText().strip()
        if not self._file and not pasted:
            self.status.setText('Choose a syllabus or paste assignment text first.')
            return
        self.table.setRowCount(0)
        self.save_button.setEnabled(False)
        self.status.setText('Reading the source and checking dates…')
        self._set_busy(True)
        self._worker = DeadlineScan(self.course.text(), pasted, self._file, self)
        self._worker.result.connect(self._result)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _result(self, candidates, source_name, error):
        if error:
            self.status.setText(error)
            return
        self._source_name = source_name
        for row, candidate in enumerate(candidates):
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(candidate.title))
            due = dt.datetime.fromisoformat(candidate.due_at).astimezone(TZ)
            self.table.setItem(row, 2, QTableWidgetItem(due.strftime('%Y-%m-%d %H:%M')))
            certainty = 'Assumed time' if candidate.time_assumed else candidate.confidence.title()
            self.table.setItem(row, 3, QTableWidgetItem(certainty))
            evidence = QTableWidgetItem(candidate.evidence)
            evidence.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            evidence.setData(Qt.UserRole, candidate)
            self.table.setItem(row, 4, evidence)
        self.status.setText(f'Found {len(candidates)} candidate(s). Review the title, date and source quote.' if candidates else
                            'No supported deadline was found. You can paste a more complete assignment description or add it manually later.')
        self.save_button.setEnabled(bool(candidates))

    def _finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        self._set_busy(False)

    def _selected(self):
        result = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() != Qt.Checked:
                continue
            original = self.table.item(row, 4).data(Qt.UserRole)
            title = ' '.join(self.table.item(row, 1).text().split())
            try:
                due = dt.datetime.strptime(self.table.item(row, 2).text().strip(), '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
            except ValueError:
                raise ValueError(f'Row {row + 1}: use date format YYYY-MM-DD HH:MM.') from None
            if not title:
                raise ValueError(f'Row {row + 1}: enter a title.')
            result.append(DeadlineCandidate(title[:160], due.isoformat(timespec='minutes'),
                                            original.evidence, original.confidence,
                                            original.time_assumed))
        return result

    def _save(self):
        try:
            selected = self._selected()
            if not selected:
                raise ValueError('Select at least one deadline to save.')
            added = self.store.add(self.course.text(), self._source_name, selected)
            self.status.setText(f'Saved {added} new deadline(s) locally.' if added else
                                'These deadlines are already in your local Inbox.')
        except ValueError as exc:
            self.status.setText(str(exc))

    def reject(self):
        if not self._worker:
            super().reject()

    def closeEvent(self, event):
        if self._worker:
            event.ignore()
        else:
            super().closeEvent(event)
