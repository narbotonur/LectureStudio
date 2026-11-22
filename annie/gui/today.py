"""Daily workflow assembled from local trackers and reviewed lecture actions."""
import datetime as dt
from pathlib import Path
import sqlite3

from PyQt5.QtCore import QDateTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QDateTimeEdit, QDialog, QFormLayout, QFrame, QHBoxLayout,
                            QLineEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from annie.daily_plan import DailyPlanStore, suggest_today
from annie.gui.design import apply_theme, label, role
from annie.planner import TZ


class TodayPage(QWidget):
    navigate = pyqtSignal(int)
    library_requested = pyqtSignal()
    study_requested = pyqtSignal(str)
    lab_requested = pyqtSignal(str)
    inbox_requested = pyqtSignal()

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.events = []
        self.store = DailyPlanStore(root)
        self.root = root
        self.clock = lambda: dt.datetime.now(TZ)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        top = QHBoxLayout()
        top.addWidget(label('Today', 'title'), 1)
        add = role(QPushButton('Add study block'), 'primary')
        add.clicked.connect(lambda: self._edit_block())
        top.addWidget(add)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.date_label = label('', 'muted')
        layout.addWidget(self.date_label)
        links = QHBoxLayout()
        for text, open_page in (('Record or import', lambda: self.navigate.emit(0)),
                                ('Lecture library', self.library_requested.emit),
                                ('Study timer', lambda: self.navigate.emit(5))):
            button = QPushButton(text)
            button.clicked.connect(open_page)
            links.addWidget(button)
        inbox = QPushButton('Deadlines')
        inbox.clicked.connect(self.inbox_requested.emit)
        links.addWidget(inbox)
        layout.addLayout(links)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('homeContent')
        self.body = QVBoxLayout(body)
        self.body.setSpacing(12)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.feedback = label('')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.reload()

    def set_events(self, events):
        self.events = list(events)
        self.reload()

    def _text(self, text, style=''):
        result = label(text, style)
        result.setTextFormat(Qt.PlainText)
        result.setWordWrap(True)
        return result

    def reload(self):
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        now = self.clock()
        self.date_label.setText(f'{now:%A, %d %B} · UTC+05')
        try:
            self._populate(now)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.feedback.setText(str(exc))
        self.body.addStretch()

    def _populate(self, now):
        from annie.deadlines import DeadlineStore
        from annie.gpa_tracker import GpaStore
        from annie.habits import HabitStore
        from annie.gui.habit_tracker import CompactRoutineWidget
        from annie.lecture_actions import ActionStore
        from annie.obligations import ObligationStore
        from annie.planner import PlannerStore, _event_interval
        from annie.paths import DATA_DIR
        root = Path(self.root or DATA_DIR)
        from annie.campus_radar import RadarStore
        radar = RadarStore(root)
        unread = len(radar.events(unread_only=True))
        radar_button = QPushButton(f'Campus Radar · {unread} unreviewed change(s)' if unread else 'Campus Radar · check source coverage')
        radar_button.setMinimumHeight(32)
        radar_button.clicked.connect(lambda: self.navigate.emit(12))
        self.body.addWidget(radar_button)
        obligations = ObligationStore(root)
        pending_count = len(obligations.list_proposals('pending')) + len(ActionStore(root).list_actions('pending'))
        if pending_count:
            review = role(QPushButton(f'{pending_count} finding(s) need review — check assignments and deadline changes'), 'primary')
            review.setMinimumHeight(32)
            review.clicked.connect(lambda: self.navigate.emit(10))
            self.body.addWidget(review)
        self.body.addWidget(self._text('Up next', 'section'))
        upcoming = []
        for event in self.events:
            interval = _event_interval(event)
            if interval and interval[1] > now and interval[0].date() == now.date() and event.get('status') != 'cancelled':
                upcoming.append((interval[0], event.get('summary', 'Class')))
        if upcoming:
            for start, title in sorted(upcoming)[:1]:
                self.body.addWidget(self._text(f'{start:%H:%M} · {title}'))
        else:
            self.body.addWidget(self._text('No upcoming classes in the loaded calendar. Open Schedule to refresh.', 'muted'))
        deadlines = DeadlineStore(root).load()
        pending = []
        for deadline in deadlines:
            if deadline.get('status', 'open') != 'open':
                continue
            try:
                due = dt.datetime.fromisoformat(deadline['due_at']).astimezone(TZ)
            except (ValueError, KeyError):
                continue
            pending.append((due, deadline))
        for due, item in sorted(pending, key=lambda pair: pair[0])[:2]:
            self.body.addWidget(self._text(f"{'Overdue' if due < now else 'Due'} {due:%d %b %H:%M} · {item['title']}"))
        self.body.addWidget(self._text('Your next study actions', 'section'))
        actions = ActionStore(root)
        gpa = GpaStore(root / 'gpa_tracker.sqlite3')
        courses = [gpa.summary(item['id']) for item in gpa.courses()]
        prayers = {}
        prayer_source = ''
        try:
            from annie.prayer_times import PrayerStore
            prayer_store = PrayerStore(root)
            cache = prayer_store.cache(prayer_store.settings())
            day = next((entry for entry in (cache or {}).get('days', [])
                        if entry.get('date') == now.date().isoformat()), {})
            prayers = day.get('times', {})
            if prayers:
                fetched = (cache.get('fetched_at') or '')[:10]
                provider = cache.get('source') or 'Prayer calendar'
                prayer_source = f"{provider} · {day['date']}" + (f' · cached {fetched}' if fetched else '')
        except (TypeError, AttributeError, ValueError):
            pass
        suggestions, warnings = suggest_today(courses, deadlines, actions.approved_tasks(), self.events,
                                               prayers, PlannerStore(root).settings(), self.store.decisions(), now,
                                               habits=HabitStore(root / 'habits.sqlite3').habits())
        for item in suggestions:
            card = role(QFrame(), 'panel')
            box = QVBoxLayout(card)
            box.addWidget(self._text(item['title'], 'section'))
            when = dt.datetime.fromisoformat(item['start']).strftime('%H:%M') if item.get('start') else 'Choose a time'
            pin = ' · Pinned' if item.get('pinned') else ''
            box.addWidget(self._text(f"{when} · {item['minutes']} min{pin}"))
            box.addWidget(self._text(item['reason'], 'muted'))
            if item.get('conflict'):
                box.addWidget(self._text(item['conflict'], 'section'))
            buttons = QHBoxLayout()
            if item['status'] == 'suggested':
                accept = QPushButton('Add to today')
                accept.clicked.connect(lambda checked=False, value=item: self._decide(value, 'accepted'))
                buttons.addWidget(accept)
            else:
                start = role(QPushButton('Start studying'), 'primary')
                start.clicked.connect(lambda checked=False, value=item: self.study_requested.emit(value['course'] or value['title']))
                buttons.addWidget(start)
                done = QPushButton('Done')
                done.clicked.connect(lambda checked=False, value=item: self._complete(value))
                buttons.addWidget(done)
            move = QPushButton('Edit / move')
            move.clicked.connect(lambda checked=False, value=item: self._edit_block(value))
            skip = QPushButton('Skip')
            skip.clicked.connect(lambda checked=False, value=item: self._decide(value, 'skipped'))
            buttons.addWidget(move)
            buttons.addWidget(skip)
            box.addLayout(buttons)
            if item.get('action_id'):
                import re
                if re.search(r'\bbfs\b|breadth[ -]first', item['title'] + ' ' + item['reason'], re.I):
                    lab = QPushButton('Open executable lab')
                    lab.clicked.connect(lambda checked=False, identity=item['action_id']: self.lab_requested.emit(identity))
                    box.addWidget(lab)
            self.body.addWidget(card)
        closed = {item.get('origin_assignment_id') or item['id'] for item in deadlines
                  if item.get('status', 'open') != 'open'}
        live_actions = {item['id'] for item in actions.approved_tasks()}
        missed = [item for item in self.store.missed(now.date())
                  if item.get('deadline_id') not in closed
                  and (not item.get('action_id') or item['action_id'] in live_actions)]
        if missed:
            self.body.addWidget(self._text('Unfinished plans', 'section'))
            for item in missed:
                move = QPushButton(f"Reschedule {item['title']} · {item['day']}")
                move.clicked.connect(lambda checked=False, value=item: self._edit_block(value))
                self.body.addWidget(move)
        if not suggestions:
            self.body.addWidget(self._text('No additional study block fits today. Use Review to keep track of approved lecture actions.'
                                          if actions.approved_tasks() or courses else
                                          'Approve a lecture action in Review or add a course in Academics.', 'muted'))
        self.feedback.setText(' '.join(warnings) or 'Suggested times use your loaded calendar and cached prayer times. Accepted actions stay local.')
        if prayer_source:
            self.feedback.setText(self.feedback.text() + f' Prayer times: {prayer_source}.')
        else:
            self.feedback.setText(self.feedback.text() + ' Prayer times are not cached for today; check them before accepting a slot.')
        self.body.addWidget(self._text('Daily routines', 'section'))
        manage = QPushButton('Manage routines')
        manage.setMinimumHeight(32)
        manage.clicked.connect(lambda: self.navigate.emit(7))
        self.body.addWidget(manage)
        routines = CompactRoutineWidget(store=HabitStore(root / 'habits.sqlite3'))
        self.body.addWidget(routines)

    def _decide(self, item, status):
        try:
            self.store.decide(item, status)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.feedback.setText(str(exc))
            return
        self.reload()

    def _edit_block(self, item=None):
        dialog = QDialog(self)
        dialog.setWindowTitle('Edit study block' if item else 'Add study block')
        form = QFormLayout(dialog)
        title = QLineEdit(item.get('title', '') if item else '')
        title.setMaxLength(160)
        course = QLineEdit(item.get('course', '') if item else '')
        course.setMaxLength(100)
        start = QDateTimeEdit()
        start.setCalendarPopup(True)
        start.setDisplayFormat('dd MMM yyyy HH:mm')
        now = self.clock()
        initial = now + dt.timedelta(minutes=10)
        if item and item.get('start') and item['day'] >= now.date().isoformat():
            initial = dt.datetime.fromisoformat(item['start']).astimezone(TZ)
        start.setDateTime(QDateTime.fromString(initial.strftime('%Y-%m-%dT%H:%M'), 'yyyy-MM-ddTHH:mm'))
        minutes = QSpinBox()
        minutes.setRange(1, 720)
        minutes.setSuffix(' min')
        minutes.setValue(item['minutes'] if item else 25)
        pinned = QCheckBox('Pin in the weekly plan')
        pinned.setChecked(bool(item and item.get('pinned')))
        form.addRow('Title', title)
        form.addRow('Course', course)
        form.addRow('Starts (UTC+05)', start)
        form.addRow('Duration', minutes)
        form.addRow(pinned)
        message = label('')
        message.setWordWrap(True)
        form.addRow(message)
        actions = QHBoxLayout()
        save = role(QPushButton('Save study block'), 'primary')
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        actions.addWidget(save)
        form.addRow(actions)

        def commit():
            try:
                self.store.schedule(item, title=title.text(), course=course.text(),
                                    start=start.dateTime().toString('yyyy-MM-ddTHH:mm') + '+05:00',
                                    minutes=minutes.value(), pinned=pinned.isChecked())
            except (ValueError, OSError, sqlite3.Error) as exc:
                message.setText(str(exc))
                return
            dialog.accept()
        save.clicked.connect(commit)
        apply_theme(dialog)
        if dialog.exec_() == QDialog.Accepted:
            self.reload()

    def _complete(self, item):
        if item.get('action_id'):
            from annie.lecture_actions import ActionStore
            ActionStore(self.root).mark_task_done(item['action_id'])
        self._decide(item, 'done')
