"""Course, component-grade and credit-weighted GPA workspace."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                            QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                            QHBoxLayout, QHeaderView, QLineEdit, QListWidget,
                            QListWidgetItem, QMessageBox, QPushButton, QSplitter,
                            QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from annie.gpa_tracker import GRADE_SCALE, GpaStore
from annie.gui.design import label, role


def _metric(title):
    card = role(QFrame(), 'panel')
    box = QVBoxLayout(card)
    box.setContentsMargins(14, 10, 14, 10)
    box.addWidget(label(title, 'muted'))
    value = label('—', 'section')
    box.addWidget(value)
    return card, value


class CourseDialog(QDialog):
    def __init__(self, parent=None, course=None):
        super().__init__(parent)
        self.setWindowTitle('Edit course' if course else 'Add course')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(course['name'] if course else '')
        self.name.setPlaceholderText('MATH 251')
        self.credits = QDoubleSpinBox()
        self.credits.setRange(.5, 30)
        self.credits.setSingleStep(.5)
        self.credits.setDecimals(1)
        self.credits.setValue(course['credits'] if course else 5)
        self.target = QComboBox()
        for letter, minimum, points in GRADE_SCALE[:-1]:
            self.target.addItem(f'{letter} · at least {minimum:g}% · {points:.2f} GPA', minimum)
        target = course['target_percent'] if course else 85
        self.target.setCurrentIndex(max(0, self.target.findData(target)))
        form.addRow('Course', self.name)
        form.addRow('Credits', self.credits)
        form.addRow('Target', self.target)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return self.name.text(), self.credits.value(), self.target.currentData()


class ComponentDialog(QDialog):
    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.setWindowTitle('Edit grade component' if item else 'Add grade component')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(item['name'] if item else '')
        self.name.setPlaceholderText('Midterm 1')
        self.weight = QDoubleSpinBox()
        self.weight.setRange(.01, 100)
        self.weight.setDecimals(2)
        self.weight.setSuffix(' %')
        self.weight.setValue(item['weight'] if item else 10)
        self.graded = QCheckBox('A score has been posted')
        self.graded.setChecked(bool(item and item['score'] is not None))
        self.score = QDoubleSpinBox()
        self.score.setRange(0, 100)
        self.score.setDecimals(2)
        self.score.setSuffix(' %')
        self.score.setValue(item['score'] if item and item['score'] is not None else 0)
        self.score.setEnabled(self.graded.isChecked())
        self.graded.toggled.connect(self.score.setEnabled)
        form.addRow('Component', self.name)
        form.addRow('Course weight', self.weight)
        form.addRow('', self.graded)
        form.addRow('Your score', self.score)
        layout.addLayout(form)
        note = label('Leave the score unchecked for upcoming work. Weights across a course cannot exceed 100%.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return self.name.text(), self.weight.value(), self.score.value() if self.graded.isChecked() else None


class GpaTrackerPage(QWidget):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or GpaStore()
        self._courses = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label('Courses & GPA', 'title'))
        subtitle = label('Track assessed work, estimate your semester GPA, and see what your target requires.')
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        heading.addLayout(titles, 1)
        self.add_course_button = role(QPushButton('+ Add course'), 'primary')
        self.add_course_button.clicked.connect(self._add_course)
        heading.addWidget(self.add_course_button)
        layout.addLayout(heading)

        stats = QHBoxLayout()
        self.gpa_card, self.gpa_value = _metric('Estimated semester GPA')
        self.target_card, self.target_value = _metric('Target GPA')
        self.credit_card, self.credit_value = _metric('Tracked credits')
        for card in (self.gpa_card, self.target_card, self.credit_card):
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        split = QSplitter(Qt.Horizontal)
        courses_panel = role(QFrame(), 'panel')
        courses_layout = QVBoxLayout(courses_panel)
        courses_layout.addWidget(label('Courses', 'section'))
        self.course_list = QListWidget()
        self.course_list.setAccessibleName('Tracked courses')
        self.course_list.currentRowChanged.connect(self._course_selected)
        courses_layout.addWidget(self.course_list, 1)
        course_actions = QHBoxLayout()
        self.edit_course_button = QPushButton('Edit')
        self.edit_course_button.clicked.connect(self._edit_course)
        self.delete_course_button = QPushButton('Delete')
        self.delete_course_button.clicked.connect(self._delete_course)
        course_actions.addWidget(self.edit_course_button)
        course_actions.addWidget(self.delete_course_button)
        courses_layout.addLayout(course_actions)
        split.addWidget(courses_panel)

        detail_panel = role(QFrame(), 'panel')
        detail_layout = QVBoxLayout(detail_panel)
        self.course_title = label('Choose a course', 'section')
        detail_layout.addWidget(self.course_title)
        course_stats = QHBoxLayout()
        self.current_card, self.current_value = _metric('Current estimate')
        self.goal_card, self.goal_value = _metric('Target')
        self.need_card, self.need_value = _metric('Needed on remaining work')
        for card in (self.current_card, self.goal_card, self.need_card):
            course_stats.addWidget(card, 1)
        detail_layout.addLayout(course_stats)
        self.course_status = label('Add a course to begin.')
        self.course_status.setWordWrap(True)
        detail_layout.addWidget(self.course_status)
        component_header = QHBoxLayout()
        component_header.addWidget(label('Grade components', 'section'), 1)
        self.add_component_button = QPushButton('+ Add component')
        self.add_component_button.clicked.connect(self._add_component)
        component_header.addWidget(self.add_component_button)
        detail_layout.addLayout(component_header)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Component', 'Weight', 'Score', 'Contribution'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(self._edit_component)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        detail_layout.addWidget(self.table, 1)
        component_actions = QHBoxLayout()
        component_actions.addStretch()
        self.edit_component_button = QPushButton('Edit component')
        self.edit_component_button.clicked.connect(self._edit_component)
        self.delete_component_button = QPushButton('Delete component')
        self.delete_component_button.clicked.connect(self._delete_component)
        component_actions.addWidget(self.edit_component_button)
        component_actions.addWidget(self.delete_component_button)
        detail_layout.addLayout(component_actions)
        split.addWidget(detail_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([260, 760])
        layout.addWidget(split, 1)
        footer = label('Estimates use the NU undergraduate common grading scale. Official grades and GPA come from your instructor and the Registrar.')
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.reload()

    def _selected_course(self):
        row = self.course_list.currentRow()
        return self._courses[row] if 0 <= row < len(self._courses) else None

    def _selected_component(self):
        course = self._selected_course()
        row = self.table.currentRow()
        if course and row >= 0:
            items = self.store.assessments(course['id'])
            return items[row] if row < len(items) else None
        return None

    def reload(self, select_id=None):
        previous = select_id or (self._selected_course() or {}).get('id')
        self._courses = self.store.courses()
        self.course_list.blockSignals(True)
        self.course_list.clear()
        selected_row = -1
        for row, course in enumerate(self._courses):
            summary = self.store.summary(course['id'])
            current = ('No grades' if summary['current_percent'] is None else
                       f"{summary['current_letter']} · {summary['current_percent']:.1f}%")
            item = QListWidgetItem(f"{course['name']}\n{course['credits']:g} credits · {current}")
            self.course_list.addItem(item)
            if course['id'] == previous:
                selected_row = row
        self.course_list.blockSignals(False)
        semester = self.store.semester_summary()
        self.gpa_value.setText('—' if semester['estimated_gpa'] is None else f"{semester['estimated_gpa']:.2f} / 4.00")
        self.target_value.setText('—' if semester['target_gpa'] is None else f"{semester['target_gpa']:.2f} / 4.00")
        self.credit_value.setText(f"{semester['credits']:g}")
        if self._courses:
            self.course_list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self.course_list.setCurrentRow(-1)
            self._course_selected(-1)

    def _course_selected(self, row):
        course = self._selected_course()
        enabled = course is not None
        for widget in (self.edit_course_button, self.delete_course_button,
                       self.add_component_button, self.edit_component_button,
                       self.delete_component_button):
            widget.setEnabled(enabled)
        self.table.setRowCount(0)
        if not course:
            self.course_title.setText('Choose a course')
            self.current_value.setText('—')
            self.goal_value.setText('—')
            self.need_value.setText('—')
            self.course_status.setText('Add a course to begin.')
            return
        summary = self.store.summary(course['id'])
        self.course_title.setText(f"{course['name']} · {course['credits']:g} credits")
        if summary['current_percent'] is None:
            self.current_value.setText('—')
        else:
            self.current_value.setText(f"{summary['current_letter']} · {summary['current_percent']:.1f}%")
        self.goal_value.setText(f"{summary['target_letter']} · {summary['target_percent']:g}%")
        required = summary['required_percent']
        if required is None:
            self.need_value.setText('Course complete')
        elif required <= 0:
            self.need_value.setText('Target secured')
        elif required > 100:
            self.need_value.setText(f'{required:.1f}% · out of reach')
        else:
            self.need_value.setText(f'{required:.1f}%')
        missing = 100 - summary['total_weight']
        status = (f"Entered components: {summary['total_weight']:.1f}% · "
                  f"graded so far: {summary['graded_weight']:.1f}%.")
        if missing > .001:
            status += f' Add the remaining {missing:.1f}% when you know the course breakdown.'
        if required is not None and required > 100:
            status += ' The selected target cannot be reached with the recorded scores.'
        self.course_status.setText(status)
        for row, item in enumerate(summary['items']):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item['name']))
            self.table.setItem(row, 1, QTableWidgetItem(f"{item['weight']:g}%"))
            if item['score'] is None:
                score, contribution = 'Not graded', '—'
            else:
                score = f"{item['score']:g}%"
                contribution = f"{item['weight'] * item['score'] / 100:.2f} / {item['weight']:g}"
            self.table.setItem(row, 2, QTableWidgetItem(score))
            self.table.setItem(row, 3, QTableWidgetItem(contribution))
        if summary['items']:
            self.table.selectRow(0)

    def _show_error(self, error):
        QMessageBox.warning(self, 'Could not save', str(error))

    def _add_course(self):
        dialog = CourseDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                course = self.store.add_course(*dialog.values())
                self.reload(course['id'])
            except ValueError as exc:
                self._show_error(exc)

    def _edit_course(self):
        course = self._selected_course()
        if not course:
            return
        dialog = CourseDialog(self, course)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.update_course(course['id'], *dialog.values())
                self.reload(course['id'])
            except ValueError as exc:
                self._show_error(exc)

    def _delete_course(self):
        course = self._selected_course()
        if not course:
            return
        answer = QMessageBox.question(self, 'Delete course?',
            f"Delete {course['name']} and all of its grade components? This does not change Registrar records.")
        if answer == QMessageBox.Yes:
            self.store.delete_course(course['id'])
            self.reload()

    def _add_component(self):
        course = self._selected_course()
        if not course:
            return
        dialog = ComponentDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.add_assessment(course['id'], *dialog.values())
                self.reload(course['id'])
            except ValueError as exc:
                self._show_error(exc)

    def _edit_component(self, *_):
        course, item = self._selected_course(), self._selected_component()
        if not course or not item:
            return
        dialog = ComponentDialog(self, item)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.update_assessment(item['id'], *dialog.values())
                self.reload(course['id'])
            except ValueError as exc:
                self._show_error(exc)

    def _delete_component(self):
        course, item = self._selected_course(), self._selected_component()
        if not course or not item:
            return
        answer = QMessageBox.question(self, 'Delete component?',
                                      f"Delete {item['name']} from this estimate?")
        if answer == QMessageBox.Yes:
            self.store.delete_assessment(item['id'])
            self.reload(course['id'])
