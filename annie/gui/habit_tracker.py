"""Daily habit check-in and current-week consistency view."""
import datetime as dt

from PyQt5.QtCore import QTime, Qt
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                            QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                            QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
                            QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                            QTimeEdit, QVBoxLayout, QWidget)

from annie.gui.design import label, role
from annie.habits import DAY_NAMES, HabitStore, TZ, schedule_text, scheduled


def _metric(title):
    card = role(QFrame(), 'panel')
    box = QVBoxLayout(card)
    box.setContentsMargins(14, 10, 14, 10)
    box.addWidget(label(title, 'muted'))
    value = label('—', 'section')
    box.addWidget(value)
    return card, value


class HabitDialog(QDialog):
    def __init__(self, parent=None, habit=None):
        super().__init__(parent)
        self.setWindowTitle('Edit habit' if habit else 'Add habit')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(habit['name'] if habit else '')
        self.name.setPlaceholderText('Review lecture notes')
        self.kind = QComboBox()
        self.kind.addItem('Done / not done', 'done')
        self.kind.addItem('Minutes', 'minutes')
        self.kind.addItem('Count', 'count')
        if habit:
            self.kind.setCurrentIndex(self.kind.findData(habit['kind']))
        self.target = QDoubleSpinBox()
        self.target.setRange(.1, 1_000_000)
        self.target.setDecimals(1)
        self.target.setValue(habit['target'] if habit else 1)
        self.unit = QLineEdit(habit['unit'] if habit and habit['kind'] == 'count' else '')
        self.unit.setPlaceholderText('pages, problems, glasses…')
        form.addRow('Habit', self.name)
        form.addRow('Measure', self.kind)
        form.addRow('Daily target', self.target)
        form.addRow('Unit', self.unit)
        layout.addLayout(form)
        layout.addWidget(label('Planned days', 'section'))
        days = QHBoxLayout()
        self.days = []
        mask = habit['days_mask'] if habit else 127
        for index, name in enumerate(DAY_NAMES):
            box = QCheckBox(name)
            box.setChecked(bool(mask & (1 << index)))
            self.days.append(box)
            days.addWidget(box)
        layout.addLayout(days)
        timing = QHBoxLayout()
        self.timed = QCheckBox('Preferred time')
        preferred = habit['preferred_time'] if habit else ''
        self.timed.setChecked(bool(preferred))
        self.time = QTimeEdit()
        self.time.setDisplayFormat('HH:mm')
        self.time.setTime(QTime.fromString(preferred, 'HH:mm') if preferred else QTime(18, 0))
        self.time.setEnabled(self.timed.isChecked())
        self.timed.toggled.connect(self.time.setEnabled)
        timing.addWidget(self.timed)
        timing.addWidget(self.time)
        timing.addStretch()
        layout.addLayout(timing)
        note = label('Preferred time will be used later when Studio builds your weekly study plan.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _kind_changed(self):
        kind = self.kind.currentData()
        self.target.setEnabled(kind != 'done')
        self.unit.setEnabled(kind == 'count')
        self.target.setSuffix(' min' if kind == 'minutes' else '')
        if kind == 'done':
            self.target.setValue(1)

    def values(self):
        mask = sum(1 << index for index, box in enumerate(self.days) if box.isChecked())
        preferred = self.time.time().toString('HH:mm') if self.timed.isChecked() else ''
        return (self.name.text(), self.kind.currentData(), self.target.value(),
                self.unit.text(), mask, preferred)


class HabitTrackerPage(QWidget):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or HabitStore()
        self.today = dt.datetime.now(TZ).date()
        self._week = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label('Habits', 'title'))
        subtitle = label('Keep the week realistic. Progress counts only the days you planned, up to today.')
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        heading.addLayout(titles, 1)
        self.add_button = role(QPushButton('+ Add habit'), 'primary')
        self.add_button.clicked.connect(self._add)
        heading.addWidget(self.add_button)
        layout.addLayout(heading)
        stats = QHBoxLayout()
        self.today_card, self.today_value = _metric('Today')
        self.week_card, self.week_value = _metric('This week')
        self.count_card, self.count_value = _metric('Active habits')
        for card in (self.today_card, self.week_card, self.count_card):
            stats.addWidget(card, 1)
        layout.addLayout(stats)
        today_header = QHBoxLayout()
        today_header.addWidget(label('Today’s check-in', 'section'), 1)
        self.edit_button = QPushButton('Edit selected')
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = QPushButton('Delete selected')
        self.delete_button.clicked.connect(self._delete)
        today_header.addWidget(self.edit_button)
        today_header.addWidget(self.delete_button)
        layout.addLayout(today_header)
        self.today_table = QTableWidget(0, 5)
        self.today_table.setHorizontalHeaderLabels(['Habit', 'Schedule', 'Goal', 'Today', 'Check in'])
        self.today_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.today_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.today_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.today_table.doubleClicked.connect(self._edit)
        self.today_table.verticalHeader().hide()
        self.today_table.verticalHeader().setDefaultSectionSize(44)
        header = self.today_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        self.today_table.setColumnWidth(4, 230)
        self.today_table.setMinimumHeight(160)
        layout.addWidget(self.today_table, 1)
        layout.addWidget(label('Week at a glance', 'section'))
        self.week_table = QTableWidget(0, 8)
        self.week_table.setHorizontalHeaderLabels(['Habit', *DAY_NAMES])
        self.week_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.week_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.week_table.verticalHeader().hide()
        self.week_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 8):
            self.week_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.week_table.setMinimumHeight(135)
        layout.addWidget(self.week_table, 1)
        self.feedback = label('Progress is saved locally on this laptop.')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.reload()

    @staticmethod
    def _goal(habit):
        if habit['kind'] == 'done':
            return 'Done'
        return f"{habit['target']:g} {habit['unit']}"

    @staticmethod
    def _value(habit, value):
        if habit['kind'] == 'done':
            return 'Done' if value else 'Not done'
        return f"{value:g} {habit['unit']}"

    def reload(self, select_id=None):
        current_row = self.today_table.currentRow()
        if select_id is None and self._week and 0 <= current_row < len(self._week['habits']):
            select_id = self._week['habits'][current_row]['id']
        self.today = dt.datetime.now(TZ).date()
        self._week = self.store.week(self.today)
        habits = self._week['habits']
        today_rate = self._week['today_rate']
        week_rate = self._week['week_rate']
        self.today_value.setText('Free day' if today_rate is None else f'{today_rate * 100:.0f}%')
        self.week_value.setText('—' if week_rate is None else f'{week_rate * 100:.0f}%')
        self.count_value.setText(str(len(habits)))
        self.today_table.setRowCount(0)
        selected_row = -1
        for row, habit in enumerate(habits):
            self.today_table.insertRow(row)
            self.today_table.setItem(row, 0, QTableWidgetItem(habit['name']))
            self.today_table.setItem(row, 1, QTableWidgetItem(schedule_text(habit['days_mask'])))
            self.today_table.setItem(row, 2, QTableWidgetItem(self._goal(habit)))
            value = habit['values'].get(self.today, 0)
            self.today_table.setItem(row, 3, QTableWidgetItem(self._value(habit, value)))
            if scheduled(habit, self.today):
                self.today_table.setCellWidget(row, 4, self._checkin_widget(habit, value))
            else:
                off = QPushButton('Not planned')
                off.setEnabled(False)
                self.today_table.setCellWidget(row, 4, off)
            if habit['id'] == select_id:
                selected_row = row
        if habits:
            self.today_table.selectRow(selected_row if selected_row >= 0 else 0)
        self.week_table.setRowCount(len(habits))
        for row, habit in enumerate(habits):
            self.week_table.setItem(row, 0, QTableWidgetItem(habit['name']))
            for column, day in enumerate(self._week['days'], 1):
                if day < habit['created_day'] or not scheduled(habit, day):
                    text = '—'
                elif day > self.today:
                    text = '○'
                else:
                    value = habit['values'].get(day, 0)
                    ratio = min(1, value / habit['target'])
                    if ratio >= 1:
                        text = '✓'
                    elif value:
                        text = f'{ratio * 100:.0f}%'
                    else:
                        text = '·'
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.week_table.setItem(row, column, item)
        enabled = bool(habits)
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _checkin_widget(self, habit, value):
        if habit['kind'] == 'done':
            button = QPushButton('Undo' if value else 'Mark done')
            button.setMinimumWidth(140)
            button.clicked.connect(lambda checked=False, h=habit, v=value:
                                   self._save_progress(h, 0 if v else 1))
            return button
        holder = QWidget()
        holder.setMinimumWidth(220)
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        amount = QDoubleSpinBox()
        amount.setRange(0, 1_000_000)
        amount.setDecimals(1)
        amount.setValue(value)
        amount.setSuffix(' ' + habit['unit'])
        amount.setMinimumWidth(135)
        save = QPushButton('Save')
        save.setMinimumWidth(64)
        save.clicked.connect(lambda checked=False, h=habit, field=amount:
                             self._save_progress(h, field.value()))
        box.addWidget(amount)
        box.addWidget(save)
        return holder

    def _save_progress(self, habit, value):
        try:
            self.store.set_progress(habit['id'], self.today, value)
            self.feedback.setText(f"Saved today’s progress for {habit['name']}.")
            self.reload(habit['id'])
        except ValueError as exc:
            self.feedback.setText(str(exc))

    def _selected(self):
        row = self.today_table.currentRow()
        habits = self._week['habits'] if self._week else []
        return habits[row] if 0 <= row < len(habits) else None

    def _add(self):
        dialog = HabitDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                habit = self.store.add(*dialog.values())
                self.reload(habit['id'])
            except ValueError as exc:
                QMessageBox.warning(self, 'Could not save', str(exc))

    def _edit(self, *_):
        habit = self._selected()
        if not habit:
            return
        dialog = HabitDialog(self, habit)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.update(habit['id'], *dialog.values())
                self.reload(habit['id'])
            except ValueError as exc:
                QMessageBox.warning(self, 'Could not save', str(exc))

    def _delete(self):
        habit = self._selected()
        if not habit:
            return
        if QMessageBox.question(self, 'Delete habit?',
                                f"Delete {habit['name']} and its progress history?") == QMessageBox.Yes:
            self.store.delete(habit['id'])
            self.reload()
