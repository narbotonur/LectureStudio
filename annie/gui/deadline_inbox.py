"""Review-first syllabus and assignment deadline capture."""
import datetime as dt
from pathlib import Path
import sqlite3

from PyQt5.QtCore import QDateTime, QThread, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDateTimeEdit, QDialog, QFileDialog,
                            QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
                            QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from annie.deadlines import DeadlineCandidate, DeadlineStore, TZ, extract_deadlines
from annie.gui.design import apply_theme, label, role
from annie.obligations import ObligationStore
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
    saved_changed = pyqtSignal()

    def __init__(self, parent=None, store=None, *, open_drafts=False):
        super().__init__(parent)
        self.store = store or DeadlineStore()
        self.obligations = ObligationStore(self.store.path.parent)
        self._worker = None
        self._file = ''
        self._source_name = ''
        self.setWindowTitle('Lecture Studio · Deadline Inbox')
        self.resize(900, 700)
        self.setMinimumSize(650, 520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(label('Deadline Inbox', 'title'))
        switcher = QHBoxLayout()
        self.tabs = QStackedWidget()
        self.tabs.addWidget(self._saved_page())
        import_page = QWidget()
        self.tabs.addWidget(import_page)
        views = QButtonGroup(self)
        for index, title in enumerate(('Saved deadlines', 'Import from a source')):
            button = role(QPushButton(title), 'nav')
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked, page=index: self.tabs.setCurrentIndex(page))
            views.addButton(button)
            switcher.addWidget(button)
        switcher.addStretch()
        layout.addLayout(switcher)
        layout.addWidget(self.tabs, 1)
        self.close_button = QPushButton('Done')
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button, 0, Qt.AlignRight)
        layout = QVBoxLayout(import_page)
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
        self.save_button = role(QPushButton('Save selected'), 'primary')
        self.save_button.clicked.connect(self._save)
        self.save_button.setEnabled(False)
        layout.addWidget(self.save_button, 0, Qt.AlignLeft)
        self._reload_saved()
        if open_drafts:
            self.view_filter.setCurrentIndex(self.view_filter.findData('draft'))
        apply_theme(self)

    def _saved_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        self.view_filter = QComboBox()
        for title, value in (('Open', 'open'), ('Drafts', 'draft'), ('Completed', 'done'),
                             ('Archived', 'archived'), ('All', '')):
            self.view_filter.addItem(title, value)
        self.view_filter.currentIndexChanged.connect(self._reload_saved)
        toolbar.addWidget(self.view_filter)
        toolbar.addStretch()
        add = role(QPushButton('Add deadline'), 'primary')
        add.clicked.connect(lambda: self._edit_saved(None))
        toolbar.addWidget(add)
        layout.addLayout(toolbar)
        self.saved_table = QTableWidget(0, 4)
        self.saved_table.setHorizontalHeaderLabels(['Deadline', 'Course', 'Due (UTC+05)', 'Status'])
        self.saved_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.saved_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.saved_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.saved_table.verticalHeader().hide()
        self.saved_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.saved_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.saved_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.saved_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.saved_table.itemSelectionChanged.connect(self._inspect_saved)
        self.saved_table.cellDoubleClicked.connect(lambda *_: self._edit_saved(self._selected_saved()))
        layout.addWidget(self.saved_table, 2)
        self.saved_details = QTextEdit()
        self.saved_details.setReadOnly(True)
        self.saved_details.setPlaceholderText('Select a deadline to see its source and history.')
        layout.addWidget(self.saved_details, 1)
        actions = QHBoxLayout()
        self.edit_saved = QPushButton('Edit')
        self.edit_saved.clicked.connect(lambda: self._edit_saved(self._selected_saved()))
        self.complete_saved = QPushButton('Mark complete')
        self.complete_saved.clicked.connect(self._complete_saved)
        self.archive_saved = QPushButton('Archive')
        self.archive_saved.clicked.connect(lambda: self._change_status('archived'))
        self.open_source = QPushButton('Open source')
        self.open_source.clicked.connect(self._open_saved_source)
        for button in (self.edit_saved, self.complete_saved, self.archive_saved, self.open_source):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.saved_message = label('')
        self.saved_message.setWordWrap(True)
        layout.addWidget(self.saved_message)
        return page

    def _reload_saved(self, *_):
        try:
            self.obligations.drain_outbox()
            rows = self.store.load()
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.saved_message.setText(str(exc))
            return
        status = self.view_filter.currentData()
        selected = self._selected_saved()
        visible = [row for row in rows if not status or row.get('status', 'open') == status]
        self.saved_table.setRowCount(0)
        for row in sorted(visible, key=lambda item: item.get('due_at', '')):
            index = self.saved_table.rowCount()
            self.saved_table.insertRow(index)
            due = row.get('due_at', '')
            try:
                due = dt.datetime.fromisoformat(due).astimezone(TZ).strftime('%d %b %Y %H:%M')
            except (ValueError, TypeError):
                due = 'Invalid date'
            for column, value in enumerate((row.get('title', ''), row.get('course', ''), due,
                                            row.get('status', 'open').title())):
                item = QTableWidgetItem(value)
                self.saved_table.setItem(index, column, item)
            self.saved_table.item(index, 0).setData(Qt.UserRole, row)
            if selected and selected['id'] == row['id']:
                self.saved_table.selectRow(index)
        if not self.saved_table.selectedItems() and visible:
            self.saved_table.selectRow(0)
        self.saved_message.setText(f'{len(visible)} deadlines shown.' if visible else 'No deadlines match this view.')
        self._inspect_saved()

    def _selected_saved(self):
        item = self.saved_table.item(self.saved_table.currentRow(), 0)
        return item.data(Qt.UserRole) if item and self.saved_table.selectedItems() else None

    def _inspect_saved(self):
        entry = self._selected_saved()
        self.edit_saved.setEnabled(entry is not None)
        self.complete_saved.setEnabled(entry is not None)
        status = entry.get('status', 'open') if entry else ''
        self.complete_saved.setText({'open': 'Mark complete', 'draft': 'Review & confirm'}.get(status, 'Reopen'))
        self.edit_saved.setVisible(status != 'draft')
        self.open_source.setEnabled(bool(entry and entry.get('source_url')))
        self.archive_saved.setEnabled(bool(entry and status != 'archived'))
        if not entry:
            self.saved_details.clear()
            return
        details = [entry.get('source_name') or 'Manual entry', entry.get('evidence') or 'No source text saved.']
        history = [*entry.get('origin_history', []), *entry.get('edit_history', [])]
        if history:
            details.extend(['', 'Previous versions'])
            details.extend(f"{version.get('title', '')} · {version.get('course') or 'No course'} · "
                           f"{version.get('due_at', '')} · {version.get('status') or 'Earlier date'}"
                           for version in history)
        self.saved_details.setPlainText('\n'.join(details))

    def _edit_saved(self, entry):
        dialog = QDialog(self)
        draft = bool(entry and entry.get('status') == 'draft')
        dialog.setWindowTitle('Confirm observed deadline' if draft else 'Edit deadline' if entry else 'Add deadline')
        form = QFormLayout(dialog)
        title = QLineEdit(entry.get('title', '') if entry else '')
        title.setMaxLength(160)
        course = QLineEdit(entry.get('course', '') if entry else '')
        course.setMaxLength(100)
        due = QDateTimeEdit()
        due.setCalendarPopup(True)
        due.setDisplayFormat('dd MMM yyyy HH:mm')
        raw = entry.get('due_at', '') if entry else dt.datetime.now(TZ).isoformat()
        initial = QDateTime.fromString(raw[:16], 'yyyy-MM-ddTHH:mm')
        due.setDateTime(initial if initial.isValid() else QDateTime.currentDateTime())
        form.addRow('Title', title)
        form.addRow('Course', course)
        form.addRow('Due (UTC+05)', due)
        message = label('')
        message.setWordWrap(True)
        form.addRow(message)
        save = role(QPushButton('Confirm deadline' if draft else 'Save deadline'), 'primary')
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(dialog.reject)
        actions = QHBoxLayout()
        actions.addWidget(cancel)
        actions.addWidget(save)
        form.addRow(actions)

        def commit():
            values = {'title': title.text(), 'course': course.text(),
                      'due_at': due.dateTime().toString('yyyy-MM-ddTHH:mm') + '+05:00'}
            try:
                if draft:
                    self.store.confirm_draft(entry['id'], **values)
                elif entry and entry.get('origin_assignment_id'):
                    revision = self.obligations.edit_assignment(entry['origin_assignment_id'],
                                                               entry['origin_revision'], **values)
                    latest = next((item for item in self.store.load() if item['id'] == entry['id']), {})
                    if latest.get('origin_revision') != revision:
                        message.setText('Edit saved. Inbox delivery is pending. Close and reopen to retry.')
                        return
                elif entry:
                    self.store.update(entry['id'], **values)
                else:
                    self.store.create(**values)
                dialog.accept()
            except (OSError, ValueError, sqlite3.Error) as exc:
                message.setText(str(exc))
        save.clicked.connect(commit)
        apply_theme(dialog)
        if dialog.exec_() == QDialog.Accepted:
            self._reload_saved()
            self.saved_changed.emit()

    def _complete_saved(self):
        entry = self._selected_saved()
        if entry:
            if entry.get('status') == 'draft':
                self._edit_saved(entry)
            else:
                status = 'done' if entry.get('status', 'open') == 'open' else 'open'
                if entry.get('confidence') == 'observed':
                    status = 'draft'
                self._change_status(status)

    def _open_saved_source(self):
        entry = self._selected_saved()
        if entry:
            from annie.gui.campus_radar import _safe_url
            try:
                url = _safe_url(entry.get('source_url'))
                if not QDesktopServices.openUrl(QUrl(url)):
                    raise ValueError
            except ValueError:
                self.saved_message.setText('The saved source link could not be opened.')

    def _change_status(self, status):
        entry = self._selected_saved()
        if not entry:
            return
        try:
            self.store.set_status(entry['id'], status)
        except (OSError, ValueError) as exc:
            self.saved_message.setText(str(exc))
            return
        self._reload_saved()
        self.saved_changed.emit()

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
            if added:
                self._reload_saved()
                self.saved_changed.emit()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def reject(self):
        if not self._worker:
            super().reject()

    def closeEvent(self, event):
        if self._worker:
            event.ignore()
        else:
            super().closeEvent(event)
