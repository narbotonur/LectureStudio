"""Local recurring habits with progress measured against planned days."""
from contextlib import contextmanager
import datetime as dt
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from annie.config import DATA_DIR

HABIT_DB_PATH = Path(DATA_DIR) / 'habits.sqlite3'
TZ = dt.timezone(dt.timedelta(hours=5))
DAY_NAMES = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
KINDS = ('done', 'minutes', 'count')
ROUTINES = ('morning', 'evening', 'flexible')
ANCHORS = ('', 'after_fajr', 'after_maghrib', 'before_sleep', 'commute')
ANCHOR_LABELS = {'': 'Any time', 'after_fajr': 'After Fajr',
                 'after_maghrib': 'After Maghrib', 'before_sleep': 'Before sleep',
                 'commute': 'On the commute'}


def _routine_settings(kind, target, routine, anchor, minimum, ideal, duration):
    if routine not in ROUTINES:
        raise ValueError('Choose Morning, Evening, or Flexible.')
    if anchor not in ANCHORS:
        raise ValueError('Choose a supported routine anchor.')
    minimum = target if minimum is None else _number(minimum, .1, target, 'Minimum target')
    ideal = target if ideal is None else _number(ideal, target, 1_000_000, 'Ideal target')
    if kind == 'done':
        minimum = ideal = 1.0
    duration = (target if kind == 'minutes' else 30 if kind == 'count' else 15
                ) if duration is None else _number(duration, 1, 1440, 'Duration')
    return routine, anchor, minimum, ideal, duration


def progress_level(habit, value):
    """Progress has useful milestones without treating minimum as a missed day."""
    if value >= habit.get('ideal_target', habit['target']):
        return 'ideal' if habit.get('ideal_target', habit['target']) > habit['target'] else 'normal'
    if value >= habit['target']:
        return 'normal'
    if value >= habit.get('minimum_target', habit['target']):
        return 'minimum'
    return 'started' if value else 'pending'


def _clean_name(value):
    value = ' '.join(str(value or '').split())
    if not value or len(value) > 100:
        raise ValueError('Enter a habit name between 1 and 100 characters.')
    return value


def _number(value, minimum, maximum, label):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a number.') from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be between {minimum:g} and {maximum:g}.')
    return value


def _settings(name, kind, target, unit, days_mask, preferred_time):
    name = _clean_name(name)
    if kind not in KINDS:
        raise ValueError('Choose Done, Minutes, or Count.')
    try:
        days_mask = int(days_mask)
    except (TypeError, ValueError):
        raise ValueError('Choose at least one day.') from None
    if not 1 <= days_mask <= 127:
        raise ValueError('Choose at least one day.')
    if kind == 'done':
        target, unit = 1.0, ''
    elif kind == 'minutes':
        target, unit = _number(target, 1, 1440, 'Daily target'), 'min'
    else:
        target = _number(target, .1, 1_000_000, 'Daily target')
        unit = ' '.join(str(unit or '').split())[:24]
        if not unit:
            raise ValueError('Enter a unit, for example pages or problems.')
    preferred_time = str(preferred_time or '').strip()
    if preferred_time and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', preferred_time):
        raise ValueError('Preferred time must use HH:MM.')
    return name, kind, target, unit, days_mask, preferred_time


def scheduled(habit, day):
    mask, _ = schedule_for(habit, day)
    return bool(mask & (1 << day.weekday())) and not paused(habit, day)


def schedule_for(habit, day):
    """Resolve the planned days and time effective on a particular date."""
    for effective, mask, preferred_time in reversed(habit.get('schedule_changes', ())):
        if effective <= day:
            return mask, preferred_time
    return habit.get('days_mask', 127), habit.get('preferred_time', '')


def paused(habit, day):
    return any(start <= day <= end for start, end in habit.get('pause_periods', ()))


def schedule_text(mask):
    if mask == 127:
        return 'Every day'
    if mask == 31:
        return 'Weekdays'
    if mask == 96:
        return 'Weekend'
    return ' · '.join(name for index, name in enumerate(DAY_NAMES)
                      if mask & (1 << index))


class HabitStore:
    def __init__(self, path=None):
        self.path = Path(path or HABIT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS habits (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                    target REAL NOT NULL, unit TEXT NOT NULL,
                    days_mask INTEGER NOT NULL, preferred_time TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS habit_logs (
                    habit_id TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                    day TEXT NOT NULL, value REAL NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(habit_id, day));
                CREATE INDEX IF NOT EXISTS habit_log_day ON habit_logs(day);
                CREATE TABLE IF NOT EXISTS habit_schedules (
                    habit_id TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                    effective_day TEXT NOT NULL, days_mask INTEGER NOT NULL,
                    preferred_time TEXT NOT NULL, PRIMARY KEY(habit_id, effective_day));
                CREATE TABLE IF NOT EXISTS habit_pauses (
                    id INTEGER PRIMARY KEY, habit_id TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                    start_day TEXT NOT NULL, end_day TEXT NOT NULL);
            ''')
            # Add columns in place. Existing goals, logs and preferred times stay intact.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(habits)')}
            additions = {'routine': "TEXT NOT NULL DEFAULT 'flexible'",
                         'anchor': "TEXT NOT NULL DEFAULT ''",
                         'minimum_target': 'REAL', 'ideal_target': 'REAL',
                         'duration_minutes': 'REAL'}
            for name, declaration in additions.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE habits ADD COLUMN {name} {declaration}')
            db.execute('UPDATE habits SET minimum_target=target WHERE minimum_target IS NULL')
            db.execute('UPDATE habits SET ideal_target=target WHERE ideal_target IS NULL')
            db.execute("""UPDATE habits SET duration_minutes=CASE kind
                       WHEN 'minutes' THEN target WHEN 'count' THEN 30 ELSE 15 END
                       WHERE duration_minutes IS NULL""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _habit(db, habit_id):
        row = db.execute('SELECT * FROM habits WHERE id=?', (habit_id,)).fetchone()
        if not row:
            raise ValueError('Habit was not found.')
        return dict(row)

    def habits(self, active_only=True):
        query = 'SELECT * FROM habits'
        if active_only:
            query += ' WHERE active=1'
        query += ' ORDER BY preferred_time="", preferred_time, name_key'
        with self.connection() as db:
            habits = [dict(row) for row in db.execute(query)]
            by_id = {habit['id']: habit for habit in habits}
            for row in db.execute('SELECT * FROM habit_schedules ORDER BY effective_day'):
                habit = by_id.get(row['habit_id'])
                if habit is not None:
                    habit.setdefault('schedule_changes', []).append((
                        dt.date.fromisoformat(row['effective_day']), row['days_mask'], row['preferred_time']))
            for row in db.execute('SELECT * FROM habit_pauses ORDER BY start_day'):
                habit = by_id.get(row['habit_id'])
                if habit is not None:
                    habit.setdefault('pause_periods', []).append((
                        dt.date.fromisoformat(row['start_day']), dt.date.fromisoformat(row['end_day'])))
            return habits

    def add(self, name, kind='done', target=1, unit='', days_mask=127,
            preferred_time='', now=None, *, routine='flexible', anchor='',
            minimum_target=None, ideal_target=None, duration_minutes=None):
        values = _settings(name, kind, target, unit, days_mask, preferred_time)
        routine_values = _routine_settings(values[1], values[2], routine, anchor,
                                          minimum_target, ideal_target, duration_minutes)
        try:
            with self.connection() as db:
                habit_id = uuid.uuid4().hex
                db.execute('''INSERT INTO habits
                           (id,name,name_key,kind,target,unit,days_mask,preferred_time,
                            active,created,routine,anchor,minimum_target,ideal_target,duration_minutes)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (habit_id, values[0], values[0].casefold(), *values[1:], 1,
                            time.time() if now is None else now, *routine_values))
                return self._habit(db, habit_id)
        except sqlite3.IntegrityError:
            raise ValueError('A habit with this name already exists.') from None

    def update(self, habit_id, name, kind, target, unit, days_mask,
               preferred_time='', active=True, *, routine=None, anchor=None,
               minimum_target=None, ideal_target=None, duration_minutes=None, schedule_effective_day=None):
        values = _settings(name, kind, target, unit, days_mask, preferred_time)
        try:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                previous = self._habit(db, habit_id)
                if ((previous['kind'], previous['unit'].casefold()) != (values[1], values[3].casefold())
                        and db.execute('SELECT 1 FROM habit_logs WHERE habit_id=? LIMIT 1', (habit_id,)).fetchone()):
                    raise ValueError('This habit has logged progress. Create a new habit to use a different measure or unit.')
                base_schedule = values[4:6]
                if schedule_effective_day is not None:
                    effective = self._habit_day(previous, schedule_effective_day, 'Schedule')
                    db.execute('''INSERT INTO habit_schedules VALUES (?,?,?,?)
                                  ON CONFLICT(habit_id,effective_day) DO UPDATE SET
                                  days_mask=excluded.days_mask, preferred_time=excluded.preferred_time''',
                               (habit_id, effective.isoformat(), *base_schedule))
                    base_schedule = previous['days_mask'], previous['preferred_time']
                same_goal = previous['kind'] == values[1] and previous['target'] == values[2]
                routine_values = _routine_settings(
                    values[1], values[2], previous['routine'] if routine is None else routine,
                    previous['anchor'] if anchor is None else anchor,
                    previous['minimum_target'] if minimum_target is None and same_goal else minimum_target,
                    previous['ideal_target'] if ideal_target is None and same_goal else ideal_target,
                    previous['duration_minutes'] if duration_minutes is None and same_goal else duration_minutes)
                db.execute('''UPDATE habits SET name=?,name_key=?,kind=?,target=?,unit=?,
                              days_mask=?,preferred_time=?,active=?,routine=?,anchor=?,
                              minimum_target=?,ideal_target=?,duration_minutes=? WHERE id=?''',
                           (values[0], values[0].casefold(), *values[1:4], *base_schedule, int(bool(active)),
                            *routine_values, habit_id))
                return self._habit(db, habit_id)
        except sqlite3.IntegrityError:
            raise ValueError('A habit with this name already exists.') from None

    @staticmethod
    def _habit_day(habit, day, label):
        if type(day) is not dt.date:
            raise ValueError(f'{label} date is invalid.')
        if day < dt.datetime.fromtimestamp(habit['created'], TZ).date():
            raise ValueError(f'{label} date precedes the creation of this habit.')
        return day

    def pause(self, habit_id, start, end):
        with self.connection() as db:
            habit = self._habit(db, habit_id)
            start, end = (self._habit_day(habit, day, 'Pause') for day in (start, end))
            if start > end:
                raise ValueError('The pause must end on or after its start date.')
            db.execute('INSERT INTO habit_pauses(habit_id,start_day,end_day) VALUES (?,?,?)',
                       (habit_id, start.isoformat(), end.isoformat()))

    def resume(self, habit_id, day):
        with self.connection() as db:
            habit = self._habit(db, habit_id)
            day = self._habit_day(habit, day, 'Resume')
            date = day.isoformat()
            db.execute('UPDATE habit_pauses SET end_day=? WHERE habit_id=? AND start_day<? AND end_day>=?',
                       ((day - dt.timedelta(days=1)).isoformat(), habit_id, date, date))
            db.execute('DELETE FROM habit_pauses WHERE habit_id=? AND start_day=?', (habit_id, date))

    def delete(self, habit_id):
        with self.connection() as db:
            self._habit(db, habit_id)
            db.execute('DELETE FROM habits WHERE id=?', (habit_id,))

    def set_progress(self, habit_id, day, value, now=None):
        if isinstance(day, str):
            try:
                day = dt.date.fromisoformat(day)
            except ValueError:
                raise ValueError('Progress date is invalid.') from None
        if not isinstance(day, dt.date):
            raise ValueError('Progress date is invalid.')
        value = _number(value, 0, 1_000_000, 'Progress')
        with self.connection() as db:
            habit = self._habit(db, habit_id)
            if habit['kind'] == 'done':
                value = 1.0 if value else 0.0
            if value == 0:
                db.execute('DELETE FROM habit_logs WHERE habit_id=? AND day=?',
                           (habit_id, day.isoformat()))
            else:
                db.execute('''INSERT INTO habit_logs VALUES (?,?,?,?)
                              ON CONFLICT(habit_id,day) DO UPDATE SET
                              value=excluded.value,updated=excluded.updated''',
                           (habit_id, day.isoformat(), value,
                            time.time() if now is None else now))
        return value

    def progress(self, habit_id, start, end):
        with self.connection() as db:
            self._habit(db, habit_id)
            return {dt.date.fromisoformat(row['day']): row['value'] for row in db.execute(
                'SELECT day,value FROM habit_logs WHERE habit_id=? AND day>=? AND day<?',
                (habit_id, start.isoformat(), end.isoformat()))}

    def increment_progress(self, habit_id, day, amount):
        """A quick-add is atomic and cannot overwrite another check-in."""
        if isinstance(day, str):
            try:
                day = dt.date.fromisoformat(day)
            except ValueError:
                raise ValueError('Progress date is invalid.') from None
        if not isinstance(day, dt.date):
            raise ValueError('Progress date is invalid.')
        amount = _number(amount, .1, 1_000_000, 'Increment')
        with self.connection() as db:
            habit = self._habit(db, habit_id)
            if habit['kind'] == 'done':
                amount = 1.0
            cap = 1.0 if habit['kind'] == 'done' else 1_000_000
            db.execute('''INSERT INTO habit_logs VALUES (?,?,?,?)
                       ON CONFLICT(habit_id,day) DO UPDATE SET
                       value=MIN(?,habit_logs.value+excluded.value),updated=excluded.updated''',
                       (habit_id, day.isoformat(), min(cap, amount), time.time(), cap))
            value = db.execute('SELECT value FROM habit_logs WHERE habit_id=? AND day=?',
                               (habit_id, day.isoformat())).fetchone()['value']
        return value

    def today_routines(self, today=None):
        """Small reusable view model for Today; goals are never calendar durations."""
        today = today or dt.datetime.now(TZ).date()
        groups = {name: [] for name in ROUTINES}
        for habit in self.week(today)['habits']:
            if not scheduled(habit, today) or today < habit['created_day']:
                continue
            value = habit['values'].get(today, 0)
            groups[habit['routine']].append({**habit, 'value': value,
                                           'level': progress_level(habit, value)})
        return groups

    def week(self, today=None):
        today = today or dt.datetime.now(TZ).date()
        monday = today - dt.timedelta(days=today.weekday())
        days = [monday + dt.timedelta(days=index) for index in range(7)]
        habits = self.habits()
        rows, achieved, opportunities = [], 0.0, 0
        today_achieved, today_opportunities = 0.0, 0
        with self.connection() as db:
            for habit in habits:
                created_day = dt.datetime.fromtimestamp(habit['created'], TZ).date()
                values = {dt.date.fromisoformat(row['day']): row['value'] for row in db.execute(
                    'SELECT day,value FROM habit_logs WHERE habit_id=? AND day>=? AND day<?',
                    (habit['id'], monday.isoformat(), (monday + dt.timedelta(days=7)).isoformat()))}
                row = {**habit, 'values': values, 'created_day': created_day}
                rows.append(row)
                for day in days:
                    if day > today or day < created_day or not scheduled(habit, day):
                        continue
                    ratio = min(1.0, values.get(day, 0) / habit['target'])
                    achieved += ratio
                    opportunities += 1
                    if day == today:
                        today_achieved += ratio
                        today_opportunities += 1
        return {'monday': monday, 'days': days, 'habits': rows,
                'week_rate': achieved / opportunities if opportunities else None,
                'week_opportunities': opportunities,
                'today_rate': today_achieved / today_opportunities if today_opportunities else None,
                'today_opportunities': today_opportunities}
