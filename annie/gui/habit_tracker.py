"""Daily habit check-in and current-week consistency view."""
import datetime as dt

from PyQt5.QtCore import QDate, QTime, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                            QDateEdit, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                            QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
                            QMenu, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                            QTimeEdit, QVBoxLayout, QWidget)

from annie.gui.design import TEXT, apply_theme, label, role
from annie.habits import (ANCHOR_LABELS, DAY_NAMES, ROUTINES, HabitStore, TZ,
                         paused, progress_level, schedule_for, schedule_text, scheduled)


def _metric(title):
    card = role(QFrame(), 'panel')
    box = QVBoxLayout(card)
    box.setContentsMargins(14, 10, 14, 10)
    box.addWidget(label(title, 'muted'))
    value = label('—', 'section')
    box.addWidget(value)
    return card, value


def _date_edit(day):
    field = QDateEdit(QDate(day.year, day.month, day.day))
    field.setCalendarPopup(True)
    field.setDisplayFormat('yyyy-MM-dd')
    return field


class HabitDialog(QDialog):
    def __init__(self, parent=None, habit=None):
        super().__init__(parent)
        self.setWindowTitle('Edit habit' if habit else 'Add habit')
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
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
        self.minimum = QDoubleSpinBox()
        self.ideal = QDoubleSpinBox()
        for field in (self.minimum, self.ideal):
            field.setRange(.1, 1_000_000)
            field.setDecimals(1)
        self.minimum.setValue(habit.get('minimum_target', habit['target']) if habit else 1)
        self.ideal.setValue(habit.get('ideal_target', habit['target']) if habit else 1)
        self.routine = QComboBox()
        for value in ROUTINES:
            self.routine.addItem(value.title(), value)
        self.routine.setCurrentIndex(self.routine.findData(habit.get('routine', 'flexible') if habit else 'flexible'))
        self.anchor = QComboBox()
        for value, title in ANCHOR_LABELS.items():
            self.anchor.addItem(title, value)
        self.anchor.setCurrentIndex(self.anchor.findData(habit.get('anchor', '') if habit else ''))
        self.duration = QDoubleSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setSuffix(' min')
        self.duration.setValue(habit.get('duration_minutes', 15) if habit else 15)
        form.addRow('Minimum on a busy day', self.minimum)
        form.addRow('Ideal target', self.ideal)
        form.addRow('Routine', self.routine)
        form.addRow('Anchor', self.anchor)
        form.addRow('Time to reserve', self.duration)
        layout.addLayout(form)
        layout.addWidget(label('Planned days', 'section'))
        today = dt.datetime.now(TZ).date()
        self.effective = _date_edit(today) if habit else None
        if habit:
            earliest = habit.get('created_day', today)
            self.effective.setMinimumDate(QDate(earliest.year, earliest.month, earliest.day))
            layout.addWidget(label('Apply schedule changes from'))
            layout.addWidget(self.effective)
            for effective, _, _ in habit.get('schedule_changes', ()):
                if effective > today:
                    layout.addWidget(label(f'A schedule change is already saved for {effective:%d %b %Y}.'))
                    break
        days = QHBoxLayout()
        self.days = []
        mask, preferred = schedule_for(habit, today) if habit else (127, '')
        for index, name in enumerate(DAY_NAMES):
            box = QCheckBox(name)
            box.setChecked(bool(mask & (1 << index)))
            self.days.append(box)
            days.addWidget(box)
        layout.addLayout(days)
        timing = QHBoxLayout()
        self.timed = QCheckBox('Preferred time')
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
        note = label('Minimum ≤ daily target ≤ ideal. Time to reserve is independent of pages or repetitions. Anchors group your routine; preferred time is optional.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.target.valueChanged.connect(self._target_changed)
        self._kind_changed()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        available = self.screen().availableGeometry()
        self.resize(min(500, available.width() - 28), min(665, available.height() - 48))
        apply_theme(self)

    def _kind_changed(self):
        kind = self.kind.currentData()
        self.target.setEnabled(kind != 'done')
        self.minimum.setEnabled(kind != 'done')
        self.ideal.setEnabled(kind != 'done')
        self.unit.setEnabled(kind == 'count')
        self.target.setSuffix(' min' if kind == 'minutes' else '')
        if kind == 'done':
            self.target.setValue(1)
            self.minimum.setValue(1)
            self.ideal.setValue(1)

    def _target_changed(self, value):
        if self.minimum.value() > value:
            self.minimum.setValue(value)
        if self.ideal.value() < value:
            self.ideal.setValue(value)

    def values(self):
        mask = sum(1 << index for index, box in enumerate(self.days) if box.isChecked())
        preferred = self.time.time().toString('HH:mm') if self.timed.isChecked() else ''
        return (self.name.text(), self.kind.currentData(), self.target.value(),
                self.unit.text(), mask, preferred)

    def routine_values(self):
        return {'routine': self.routine.currentData(), 'anchor': self.anchor.currentData(),
                'minimum_target': self.minimum.value(), 'ideal_target': self.ideal.value(),
                'duration_minutes': self.duration.value()}

    def schedule_date(self):
        return self.effective.date().toPyDate() if self.effective else None


class CheckInDialog(QDialog):
    def __init__(self, habit, day, today, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit routine check-in')
        self.habit, self.store = habit, store
        form = QFormLayout(self)
        name = label('')
        name.setTextFormat(Qt.PlainText)
        name.setText(habit['name'])
        form.addRow(name)
        self.when = _date_edit(day)
        first = habit['created_day']
        self.when.setMinimumDate(QDate(first.year, first.month, first.day))
        self.when.setMaximumDate(QDate(today.year, today.month, today.day))
        form.addRow('Date', self.when)
        if habit['kind'] == 'done':
            self.amount = QCheckBox('Done')
            form.addRow(self.amount)
        else:
            self.amount = QDoubleSpinBox()
            self.amount.setRange(0, 1_000_000)
            self.amount.setDecimals(1)
            self.amount.setSuffix(' ' + habit['unit'])
            form.addRow('Total progress', self.amount)
        self.status = label('')
        self.status.setWordWrap(True)
        form.addRow(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.when.dateChanged.connect(self._load_day)
        self._load_day()
        apply_theme(self)

    def _load_day(self):
        day = self.when.date().toPyDate()
        try:
            value = self.store.progress(self.habit['id'], day, day + dt.timedelta(days=1)).get(day, 0)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if self.habit['kind'] == 'done':
            self.amount.setChecked(bool(value))
        else:
            self.amount.setValue(value)
        self.status.setText('This date is outside the planned schedule. You can still save a check-in.'
                            if not scheduled(self.habit, day) else '')

    def _save(self):
        value = self.amount.isChecked() if self.habit['kind'] == 'done' else self.amount.value()
        try:
            self.store.set_progress(self.habit['id'], self.when.date().toPyDate(), value)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.accept()


class CompactRoutineWidget(QWidget):
    """Quick check-ins shared by the Today workspace and the full habit manager."""
    changed = pyqtSignal()

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or HabitStore()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)
        self.reload()

    def reload(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.today = dt.datetime.now(TZ).date()
        self.groups = self.store.today_routines(self.today)
        populated = False
        for group, habits in self.groups.items():
            if not habits:
                continue
            populated = True
            self.box.addWidget(label(group.title(), 'eyebrow'))
            for habit in habits:
                row = QWidget()
                line = QHBoxLayout(row)
                line.setContentsMargins(0, 0, 0, 0)
                text = f"{habit['name']} · {habit['value']:g}/{habit['target']:g} {habit['unit']}"
                if habit['anchor']:
                    text += ' · ' + ANCHOR_LABELS[habit['anchor']]
                name = label(text)
                name.setWordWrap(True)
                line.addWidget(name, 1)
                amount = 5 if habit['kind'] == 'minutes' else 1
                done = habit['kind'] == 'done'
                action = QPushButton(('Undo' if habit['value'] else 'Done') if done else f'+{amount:g}')
                action.setAccessibleName(f"{habit['name']}: {action.text()}")
                action.clicked.connect(lambda checked=False, h=habit, a=amount: self._checkin(h, a))
                line.addWidget(action)
                self.box.addWidget(row)
        if not populated:
            self.box.addWidget(label('No routines planned today. Add habits from Manage routines.'))

    def _checkin(self, habit, amount):
        try:
            if habit['kind'] == 'done':
                self.store.set_progress(habit['id'], self.today, 0 if habit['value'] else 1)
            else:
                self.store.increment_progress(habit['id'], self.today, amount)
            self.reload()
            self.changed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, 'Could not save check-in', str(exc))


class HabitTrackerPage(QWidget):
    changed = pyqtSignal()
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
        titles.addWidget(label('Routines', 'title'))
        subtitle = label('Keep a minimum for busy days and a normal goal for steady progress.')
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        heading.addLayout(titles, 1)
        self.add_button = role(QPushButton('+ Add habit'), 'primary')
        self.add_button.clicked.connect(self._add)
        heading.addWidget(self.add_button)
        layout.addLayout(heading)
        stats = QHBoxLayout()
        self.today_card, self.today_value = _metric('Minimum met today')
        self.week_card, self.week_value = _metric('Normal goal met today')
        self.count_card, self.count_value = _metric('Active habits')
        for card in (self.today_card, self.week_card, self.count_card):
            stats.addWidget(card, 1)
        layout.addLayout(stats)
        today_header = QHBoxLayout()
        today_header.addWidget(label('Today’s check-in', 'section'), 1)
        self.edit_button = QPushButton('Edit selected')
        self.edit_button.clicked.connect(self._edit)
        self.manage_button = QPushButton('More')
        menu = QMenu(self.manage_button)
        menu.addAction('Edit past check-in…', self._past_checkin)
        menu.addAction('Pause habit…', self._pause)
        self.resume_action = menu.addAction('Resume today', self._resume)
        menu.addSeparator()
        menu.addAction('Delete selected…', self._delete)
        self.manage_button.setMenu(menu)
        today_header.addWidget(self.edit_button)
        today_header.addWidget(self.manage_button)
        layout.addLayout(today_header)
        self.today_table = QTableWidget(0, 5)
        self.today_table.setHorizontalHeaderLabels(['Habit', 'Routine', 'Goals', 'Today', 'Check in'])
        self.today_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.today_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.today_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.today_table.setTextElideMode(Qt.ElideNone)
        self.today_table.setWordWrap(True)
        self.today_table.doubleClicked.connect(self._edit)
        self.today_table.itemSelectionChanged.connect(self._refresh_actions)
        self.today_table.verticalHeader().hide()
        self.today_table.verticalHeader().setDefaultSectionSize(44)
        header = self.today_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        self.today_table.setColumnWidth(2, 122)
        self.today_table.setColumnWidth(4, 160)
        self.today_table.setMinimumHeight(160)
        layout.addWidget(self.today_table, 1)
        self.week_toggle = QPushButton('Show this week')
        self.week_toggle.setCheckable(True)
        layout.addWidget(self.week_toggle)
        self.week_table = QTableWidget(0, 8)
        self.week_table.setHorizontalHeaderLabels(['Habit', *DAY_NAMES])
        self.week_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.week_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.week_table.verticalHeader().hide()
        self.week_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 8):
            self.week_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.week_table.setMinimumHeight(135)
        self.week_table.setVisible(False)
        self.week_toggle.toggled.connect(self.week_table.setVisible)
        self.week_toggle.toggled.connect(lambda checked: self.week_toggle.setText('Hide this week' if checked else 'Show this week'))
        layout.addWidget(self.week_table, 1)
        self.feedback = label('Progress is saved locally on this laptop.')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.reload()

    @staticmethod
    def _goal(habit):
        if habit['kind'] == 'done':
            return 'Done'
        return (f"Min {habit['minimum_target']:g} · Goal {habit['target']:g}\n"
                f"Ideal {habit['ideal_target']:g} {habit['unit']}")

    @staticmethod
    def _value(habit, value):
        if habit['kind'] == 'done':
            return 'Done' if value else 'Not done'
        return f"{value:g} {habit['unit']} · {progress_level(habit, value)}"

    def reload(self, select_id=None):
        current_row = self.today_table.currentRow()
        if select_id is None and self._week and 0 <= current_row < len(self._week['habits']):
            select_id = self._week['habits'][current_row]['id']
        self.today = dt.datetime.now(TZ).date()
        self._week = self.store.week(self.today)
        habits = sorted(self._week['habits'], key=lambda h: (ROUTINES.index(h['routine']),
                        schedule_for(h, self.today)[1] or '99:99', h['name'].casefold()))
        self._week['habits'] = habits
        due = [h for h in habits if scheduled(h, self.today) and h['created_day'] <= self.today]
        minimum = sum(h['values'].get(self.today, 0) >= h['minimum_target'] for h in due)
        normal = sum(h['values'].get(self.today, 0) >= h['target'] for h in due)
        self.today_value.setText(f'{minimum} / {len(due)}' if due else 'Free day')
        self.week_value.setText(f'{normal} / {len(due)}' if due else '—')
        self.count_value.setText(str(len(habits)))
        self.today_table.setRowCount(0)
        selected_row = -1
        for row, habit in enumerate(habits):
            self.today_table.insertRow(row)
            item = QTableWidgetItem(habit['name'])
            item.setToolTip(habit['name'])
            self.today_table.setItem(row, 0, item)
            routine = habit['routine'].title()
            if habit['anchor']:
                routine += '\n' + ANCHOR_LABELS[habit['anchor']]
            self.today_table.setItem(row, 1, QTableWidgetItem(routine))
            goal = QTableWidgetItem(self._goal(habit))
            days, _ = schedule_for(habit, self.today)
            goal.setToolTip(f"Minimum / normal / ideal. {schedule_text(days)}. Reserve {habit['duration_minutes']:g} min.")
            self.today_table.setItem(row, 2, goal)
            value = habit['values'].get(self.today, 0)
            self.today_table.setItem(row, 3, QTableWidgetItem(self._value(habit, value)))
            if scheduled(habit, self.today):
                self.today_table.setCellWidget(row, 4, self._checkin_widget(habit, value))
            else:
                off = QPushButton('Paused' if paused(habit, self.today) else 'Not planned')
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
                    value = habit['values'].get(day, 0)
                    text = self._value(habit, value) if value else '—'
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
        self._refresh_actions()
        self.today_table.resizeRowsToContents()
        for row in range(self.today_table.rowCount()):
            self.today_table.setRowHeight(row, max(56, self.today_table.rowHeight(row)))
            for column in range(4):
                self.today_table.item(row, column).setForeground(QColor(TEXT))
        for row in range(self.week_table.rowCount()):
            for column in range(self.week_table.columnCount()):
                self.week_table.item(row, column).setForeground(QColor(TEXT))

    def _checkin_widget(self, habit, value):
        if habit['kind'] == 'done':
            button = QPushButton('Undo' if value else 'Mark done')
            button.clicked.connect(lambda checked=False, h=habit, v=value:
                                   self._save_progress(h, 0 if v else 1))
            return button
        holder = QWidget()
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        increment = 5 if habit['kind'] == 'minutes' else 1
        quick = QPushButton(f'+{increment:g}')
        quick.setAccessibleName(f"Add {increment:g} {habit['unit']} to {habit['name']}")
        quick.clicked.connect(lambda checked=False, h=habit, a=increment: self._increment(h, a))
        save = QPushButton('Set…')
        save.setAccessibleName(f"Set progress for {habit['name']}")
        save.clicked.connect(lambda checked=False, h=habit: self._edit_checkin(h, self.today))
        box.addWidget(quick)
        box.addWidget(save)
        return holder

    def _increment(self, habit, amount):
        try:
            self.store.increment_progress(habit['id'], self.today, amount)
            self.reload(habit['id'])
            self.changed.emit()
        except ValueError as exc:
            self.feedback.setText(str(exc))

    def _save_progress(self, habit, value):
        try:
            self.store.set_progress(habit['id'], self.today, value)
            self.feedback.setText(f"Saved today’s progress for {habit['name']}.")
            self.reload(habit['id'])
            self.changed.emit()
        except ValueError as exc:
            self.feedback.setText(str(exc))

    def _selected(self):
        row = self.today_table.currentRow()
        habits = self._week['habits'] if self._week else []
        return habits[row] if 0 <= row < len(habits) else None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'today_table'):
            self.today_table.setColumnHidden(1, event.size().width() < 620)
            self.today_table.resizeRowsToContents()

    def _refresh_actions(self):
        habit = self._selected()
        self.edit_button.setEnabled(bool(habit))
        self.manage_button.setEnabled(bool(habit))
        self.resume_action.setEnabled(bool(habit and paused(habit, self.today)))

    def _past_checkin(self):
        habit = self._selected()
        if habit:
            self._edit_checkin(habit, max(habit['created_day'], self.today - dt.timedelta(days=1)))

    def _edit_checkin(self, habit, day):
        dialog = CheckInDialog(habit, day, self.today, self.store, self)
        if dialog.exec_() == QDialog.Accepted:
            selected = dialog.when.date().toPyDate()
            self.feedback.setText(f'Check-in saved for {selected:%d %b %Y}.')
            self.reload(habit['id'])
            self.changed.emit()

    def _pause(self):
        habit = self._selected()
        if not habit:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Pause habit')
        form = QFormLayout(dialog)
        start = _date_edit(self.today)
        end = _date_edit(self.today + dt.timedelta(days=6))
        form.addRow('First day off', start)
        form.addRow('Last day off', end)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        apply_theme(dialog)
        while dialog.exec_() == QDialog.Accepted:
            try:
                self.store.pause(habit['id'], start.date().toPyDate(), end.date().toPyDate())
            except ValueError as exc:
                QMessageBox.warning(dialog, 'Could not pause habit', str(exc))
                continue
            self.feedback.setText(f"Habit pause saved for {habit['name']}.")
            self.reload(habit['id'])
            self.changed.emit()
            return

    def _resume(self):
        habit = self._selected()
        if habit:
            self.store.resume(habit['id'], self.today)
            self.feedback.setText(f"Habit resumed for {habit['name']}.")
            self.reload(habit['id'])
            self.changed.emit()

    def _add(self):
        dialog = HabitDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                habit = self.store.add(*dialog.values(), **dialog.routine_values())
                self.reload(habit['id'])
                self.changed.emit()
            except ValueError as exc:
                QMessageBox.warning(self, 'Could not save', str(exc))

    def _edit(self, *_):
        habit = self._selected()
        if not habit:
            return
        dialog = HabitDialog(self, habit)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.update(habit['id'], *dialog.values(), **dialog.routine_values(),
                                  schedule_effective_day=dialog.schedule_date())
                self.reload(habit['id'])
                self.changed.emit()
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
            self.changed.emit()
