"""Reviewable local weekly plan built around calendar and prayer constraints."""
import datetime as dt

from PyQt5.QtCore import QThread, QTime, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                            QFormLayout, QFrame, QHBoxLayout, QPushButton, QSpinBox,
                            QTimeEdit, QVBoxLayout, QWidget)

from annie.gui.design import label, role
from annie.gui.week_calendar import TZ, WeekGrid
from annie.planner import (PlannerStore, blocks_as_events, generate_week,
                           validate_settings)


def _metric(title):
    card = role(QFrame(), 'panel')
    box = QVBoxLayout(card)
    box.setContentsMargins(14, 10, 14, 10)
    box.addWidget(label(title, 'muted'))
    value = label('—', 'section')
    box.addWidget(value)
    return card, value


class PlannerSettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Weekly planner settings')
        layout = QVBoxLayout(self)
        form = QFormLayout()

        def time_field(value):
            field = QTimeEdit()
            field.setDisplayFormat('HH:mm')
            field.setTime(QTime.fromString(value, 'HH:mm'))
            return field

        self.day_start = time_field(settings['day_start'])
        self.day_end = time_field(settings['day_end'])
        self.preferred = time_field(settings['preferred_study'])
        self.weekly = QDoubleSpinBox()
        self.weekly.setRange(0, 50)
        self.weekly.setSingleStep(.5)
        self.weekly.setSuffix(' h')
        self.weekly.setValue(settings['weekly_study_minutes'] / 60)
        self.block = QSpinBox()
        self.block.setRange(20, 120)
        self.block.setSuffix(' min')
        self.block.setValue(settings['block_minutes'])
        self.break_time = QSpinBox()
        self.break_time.setRange(0, 60)
        self.break_time.setSuffix(' min')
        self.break_time.setValue(settings['break_minutes'])
        self.weekday_max = QDoubleSpinBox()
        self.weekday_max.setRange(0, 12)
        self.weekday_max.setSingleStep(.5)
        self.weekday_max.setSuffix(' h')
        self.weekday_max.setValue(settings['weekday_max_minutes'] / 60)
        self.weekend_max = QDoubleSpinBox()
        self.weekend_max.setRange(0, 12)
        self.weekend_max.setSingleStep(.5)
        self.weekend_max.setSuffix(' h')
        self.weekend_max.setValue(settings['weekend_max_minutes'] / 60)
        self.prayer = QSpinBox()
        self.prayer.setRange(10, 90)
        self.prayer.setSuffix(' min')
        self.prayer.setValue(settings['prayer_block_minutes'])
        form.addRow('Plan from', self.day_start)
        form.addRow('Plan until', self.day_end)
        form.addRow('Prefer study after', self.preferred)
        form.addRow('Weekly study target', self.weekly)
        form.addRow('Focus block', self.block)
        form.addRow('Break between blocks', self.break_time)
        form.addRow('Weekday maximum', self.weekday_max)
        form.addRow('Weekend maximum', self.weekend_max)
        form.addRow('Prayer window', self.prayer)
        layout.addLayout(form)
        self.jumuah = QCheckBox('Protect Friday Jumuah and travel time')
        self.jumuah.setChecked(settings['jumuah_enabled'])
        layout.addWidget(self.jumuah)
        jumuah_row = QHBoxLayout()
        self.jumuah_start = time_field(settings['jumuah_start'])
        self.jumuah_end = time_field(settings['jumuah_end'])
        jumuah_row.addWidget(label('From'))
        jumuah_row.addWidget(self.jumuah_start)
        jumuah_row.addWidget(label('to'))
        jumuah_row.addWidget(self.jumuah_end)
        layout.addLayout(jumuah_row)
        note = label('Planner uses configured prayer-widget city, method and madhhab. It never moves calendar events or changes prayer settings.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        clock = lambda field: field.time().toString('HH:mm')
        return validate_settings({
            'day_start': clock(self.day_start), 'day_end': clock(self.day_end),
            'preferred_study': clock(self.preferred),
            'weekly_study_minutes': round(self.weekly.value() * 60),
            'block_minutes': self.block.value(), 'break_minutes': self.break_time.value(),
            'weekday_max_minutes': round(self.weekday_max.value() * 60),
            'weekend_max_minutes': round(self.weekend_max.value() * 60),
            'prayer_block_minutes': self.prayer.value(),
            'jumuah_enabled': self.jumuah.isChecked(),
            'jumuah_start': clock(self.jumuah_start), 'jumuah_end': clock(self.jumuah_end),
        })


class PlannerWorker(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, monday, settings, parent=None):
        super().__init__(parent)
        self.monday, self.settings = monday, settings

    def run(self):
        notes, events, prayers = [], [], {}
        end = self.monday + dt.timedelta(days=6)
        try:
            from annie.calendar_service import is_connected, list_events
            if is_connected():
                start_dt = dt.datetime.combine(self.monday, dt.time(), TZ)
                events = list_events(start_dt, start_dt + dt.timedelta(days=7),
                                     interactive=False, raise_errors=True, paginate=True)
            else:
                notes.append('Google Calendar is not connected; classes were not blocked.')
        except Exception:
            notes.append('Calendar could not refresh; the plan was built without its events.')
        if self.isInterruptionRequested():
            return
        try:
            from annie.prayer_times import PrayerStore, fetch_date_range
            prayer_store = PrayerStore()
            prayer_settings = prayer_store.settings()
            if prayer_settings.city and prayer_settings.country:
                cached = prayer_store.cache(prayer_settings)
                try:
                    result = fetch_date_range(
                        prayer_settings, self.monday, end,
                        cancelled=self.isInterruptionRequested)
                    prayers = result['days']
                except InterruptedError:
                    raise
                except Exception:
                    for day in (cached or {}).get('days', []):
                        parsed = dt.date.fromisoformat(day['date'])
                        if self.monday <= parsed <= end:
                            prayers[parsed] = day['times']
                    if prayers:
                        notes.append('Prayer API was unavailable; cached prayer times protect only the available days.')
                    else:
                        notes.append('Prayer times could not refresh; only the Jumuah window was protected.')
            else:
                notes.append('Set a city in the prayer widget to protect prayer times.')
        except InterruptedError:
            return
        except Exception:
            notes.append('Prayer settings could not be read; only the Jumuah window was protected.')
        if self.isInterruptionRequested():
            return
        try:
            from annie.habits import HabitStore
            habits = HabitStore().habits()
        except Exception:
            habits = []
            notes.append('Habits could not be loaded.')
        try:
            from annie.gpa_tracker import GpaStore
            gpa = GpaStore()
            courses = [gpa.summary(course['id']) for course in gpa.courses()]
        except Exception:
            courses = []
            notes.append('Courses could not be loaded.')
        try:
            from annie.deadlines import DeadlineStore
            deadlines = DeadlineStore().load()
        except Exception:
            deadlines = []
            notes.append('Deadline Inbox could not be loaded.')
        try:
            result = generate_week(self.monday, self.settings, events, prayers,
                                   habits, courses, deadlines)
        except Exception:
            self.loaded.emit({'error': 'Could not build this week. Check the planner settings and try again.'})
            return
        result['warnings'] = notes + result['warnings']
        result['calendar_events'] = events
        if not self.isInterruptionRequested():
            self.loaded.emit(result)


class WeeklyPlannerPage(QWidget):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or PlannerStore()
        today = dt.datetime.now(TZ).date()
        self.monday = today - dt.timedelta(days=today.weekday())
        self._worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label('Weekly planner', 'title'))
        self.range_label = label('', 'muted')
        titles.addWidget(self.range_label)
        heading.addLayout(titles, 1)
        self.previous = QPushButton('‹')
        self.previous.clicked.connect(lambda: self._change_week(-1))
        self.today_button = QPushButton('Today')
        self.today_button.clicked.connect(self._today)
        self.next = QPushButton('›')
        self.next.clicked.connect(lambda: self._change_week(1))
        self.settings_button = QPushButton('Settings')
        self.settings_button.clicked.connect(self._settings)
        self.generate_button = role(QPushButton('Build my week'), 'primary')
        self.generate_button.clicked.connect(self.generate)
        for button in (self.previous, self.today_button, self.next,
                       self.settings_button, self.generate_button):
            heading.addWidget(button)
        layout.addLayout(heading)
        stats = QHBoxLayout()
        self.study_card, self.study_value = _metric('Planned study')
        self.habit_card, self.habit_value = _metric('Habit blocks')
        self.prayer_card, self.prayer_value = _metric('Protected prayer blocks')
        for card in (self.study_card, self.habit_card, self.prayer_card):
            stats.addWidget(card, 1)
        layout.addLayout(stats)
        self.status = label('Build the week after adding courses and habits.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.grid = WeekGrid()
        layout.addWidget(self.grid, 1)
        legend = label('Calendar classes remain fixed · generated blocks are stored locally · Build my week replaces only this week’s generated plan.')
        legend.setWordWrap(True)
        layout.addWidget(legend)
        self.reload()

    def _update_range(self):
        end = self.monday + dt.timedelta(days=6)
        self.range_label.setText(f'{self.monday:%d %b} – {end:%d %b %Y}')

    def reload(self):
        self._update_range()
        try:
            blocks = self.store.week(self.monday)
            self._display(blocks, [])
            self.status.setText('Saved local plan.' if blocks else 'No plan saved for this week.')
        except ValueError as exc:
            self._display([], [])
            self.status.setText(str(exc))

    def _display(self, blocks, calendar_events):
        self.grid.set_events(list(calendar_events) + blocks_as_events(blocks), self.monday)
        study = [block for block in blocks if block['kind'] == 'study']
        minutes = sum((dt.datetime.fromisoformat(block['end']) -
                       dt.datetime.fromisoformat(block['start'])).total_seconds() / 60
                      for block in study)
        self.study_value.setText(f'{minutes / 60:.1f} h')
        self.habit_value.setText(str(sum(block['kind'] == 'habit' for block in blocks)))
        self.prayer_value.setText(str(sum(block['kind'] in ('prayer', 'jumuah') for block in blocks)))
        focus = [dt.datetime.fromisoformat(block['start']) for block in blocks
                 if block['kind'] in ('study', 'habit')]
        minute = min((value.hour * 60 + value.minute for value in focus), default=8 * 60)
        self.grid.verticalScrollBar().setValue(max(7 * self.grid.HOUR,
                                                   int((minute / 60 - 1) * self.grid.HOUR)))

    def _change_week(self, direction):
        if self._worker:
            return
        self.monday += dt.timedelta(days=7 * direction)
        self.reload()

    def _today(self):
        today = dt.datetime.now(TZ).date()
        self.monday = today - dt.timedelta(days=today.weekday())
        self.reload()

    def _settings(self):
        if self._worker:
            return
        try:
            settings = self.store.settings()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        dialog = PlannerSettingsDialog(settings, self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.store.save_settings(dialog.value())
                self.status.setText('Settings saved. Rebuild the week to apply them.')
            except ValueError as exc:
                self.status.setText(str(exc))

    def _busy(self, busy):
        for widget in (self.previous, self.today_button, self.next,
                       self.settings_button, self.generate_button):
            widget.setEnabled(not busy)
        self.generate_button.setText('Building…' if busy else 'Build my week')

    def generate(self):
        if self._worker:
            return
        today = dt.datetime.now(TZ).date()
        if self.monday + dt.timedelta(days=6) < today:
            self.status.setText('Past weeks are read-only. Choose this week or a future week.')
            return
        try:
            settings = self.store.settings()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText('Reading calendar, prayer settings, habits and course priorities…')
        self._busy(True)
        self._worker = PlannerWorker(self.monday, settings, self)
        self._worker.loaded.connect(self._loaded)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _loaded(self, result):
        if result.get('error'):
            self.status.setText(result['error'])
            return
        try:
            self.store.save_week(self.monday, result['blocks'])
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._display(result['blocks'], result['calendar_events'])
        study = result['planned_study_minutes']
        message = f'Plan saved locally · {study // 60}h {study % 60:02}m of focused study.'
        if result['warnings']:
            message += ' ' + ' '.join(result['warnings'])
        self.status.setText(message)

    def _finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        self._busy(False)

    def has_running_job(self):
        return self._worker is not None

    def stop_background(self):
        if self._worker:
            self._worker.requestInterruption()
