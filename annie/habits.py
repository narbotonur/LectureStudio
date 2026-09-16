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
    return bool(habit['days_mask'] & (1 << day.weekday()))


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
            ''')

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
            return [dict(row) for row in db.execute(query)]

    def add(self, name, kind='done', target=1, unit='', days_mask=127,
            preferred_time='', now=None):
        values = _settings(name, kind, target, unit, days_mask, preferred_time)
        try:
            with self.connection() as db:
                habit_id = uuid.uuid4().hex
                db.execute('INSERT INTO habits VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (habit_id, values[0], values[0].casefold(), *values[1:], 1,
                            time.time() if now is None else now))
                return self._habit(db, habit_id)
        except sqlite3.IntegrityError:
            raise ValueError('A habit with this name already exists.') from None

    def update(self, habit_id, name, kind, target, unit, days_mask,
               preferred_time='', active=True):
        values = _settings(name, kind, target, unit, days_mask, preferred_time)
        try:
            with self.connection() as db:
                self._habit(db, habit_id)
                db.execute('''UPDATE habits SET name=?,name_key=?,kind=?,target=?,unit=?,
                              days_mask=?,preferred_time=?,active=? WHERE id=?''',
                           (values[0], values[0].casefold(), *values[1:], int(bool(active)), habit_id))
                return self._habit(db, habit_id)
        except sqlite3.IntegrityError:
            raise ValueError('A habit with this name already exists.') from None

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
