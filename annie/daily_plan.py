"""Small, reviewable daily suggestions; no calendar writes or background inference."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from annie.planner import TZ, _clock, _event_interval, _free_slot, _subjects, validate_settings


class DailyPlanStore:
    def __init__(self, root=None):
        if root is None:
            from annie.paths import DATA_DIR
            root = DATA_DIR
        self.path = Path(root) / 'daily-plan.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, '
                       'day TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def decide(self, item, status, day=None):
        if status not in ('accepted', 'skipped', 'done', 'tomorrow'):
            raise ValueError('Unknown daily plan action.')
        target = day or dt.date.fromisoformat(item['day'])
        payload = dict(item)
        origin = dict(item)
        if status == 'tomorrow':
            target += dt.timedelta(days=1)
            payload['start'] = payload['end'] = ''
            payload['day'] = target.isoformat()
            payload['id'] = hashlib.sha256(f"{target}:{item['key']}".encode()).hexdigest()[:24]
        with self._connect() as db:
            query = ('INSERT INTO decisions VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                     'day=excluded.day,status=excluded.status,payload=excluded.payload')
            if status == 'tomorrow':
                db.execute(query, (item['id'], item['day'], 'skipped', json.dumps(origin)))
            db.execute(query, (payload['id'], target.isoformat(), status, json.dumps(payload)))

    def decisions(self):
        with self._connect() as db:
            return {row['id']: {**json.loads(row['payload']), 'status': row['status'],
                                'day': row['day']} for row in db.execute('SELECT * FROM decisions')}


def _local_time(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timezone is required.')
    return parsed.astimezone(TZ)


def suggest_today(courses=(), deadlines=(), tasks=(), events=(), prayers=None,
                  settings=None, decisions=None, now=None, habits=()):
    now = now or dt.datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    day = now.date()
    settings = validate_settings(settings)
    decisions = decisions or {}
    occupied = []
    for event in events:
        if event.get('status') != 'cancelled':
            interval = _event_interval(event)
            if interval:
                occupied.append(interval)
    for name, value in (prayers or {}).items():
        if name not in ('Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha'):
            continue
        try:
            start = _local_time(value) - dt.timedelta(minutes=5)
            occupied.append((start, start + dt.timedelta(minutes=settings['prayer_block_minutes'])))
        except (ValueError, TypeError):
            pass
    for habit in habits:
        if not habit.get('days_mask', 127) & (1 << day.weekday()):
            continue
        minute = None
        anchor = habit.get('anchor', '')
        prayer = {'after_fajr': 'Fajr', 'after_maghrib': 'Maghrib'}.get(anchor)
        if prayer and (prayers or {}).get(prayer):
            value = _local_time(prayers[prayer]) + dt.timedelta(minutes=settings['prayer_block_minutes'])
            minute = value.hour * 60 + value.minute
        elif habit.get('preferred_time'):
            minute = _clock(habit['preferred_time'])
        duration = max(1, int(habit.get('duration_minutes') or 15))
        if anchor == 'before_sleep':
            minute = _clock(settings['day_end']) - duration
        if minute is not None:
            start = dt.datetime.combine(day, dt.time(), TZ) + dt.timedelta(minutes=minute)
            occupied.append((start, start + dt.timedelta(minutes=duration)))
    if day.weekday() == 4 and settings['jumuah_enabled']:
        midnight = dt.datetime.combine(day, dt.time(), TZ)
        occupied.append((midnight + dt.timedelta(minutes=_clock(settings['jumuah_start'])),
                         midnight + dt.timedelta(minutes=_clock(settings['jumuah_end']))))
    result = []
    for saved in decisions.values():
        if saved['day'] == day.isoformat() and saved['status'] in ('accepted', 'tomorrow'):
            if saved.get('start') and saved.get('end'):
                occupied.append((_local_time(saved['start']), _local_time(saved['end'])))
            result.append(saved)
    candidates = []
    for task in tasks:
        candidates.append({'key': f"task:{task['id']}", 'title': task['summary'],
                           'course': task.get('course', ''), 'minutes': task.get('minutes') or 30,
                           'reason': task.get('suggested_action') or 'Approved lecture action',
                           'action_id': task['id']})
    specific_courses = {task.get('course', '').casefold() for task in tasks}
    for subject in sorted(_subjects(courses, deadlines, day), key=lambda s: -s['priority']):
        if subject['name'].casefold() in specific_courses:
            continue
        candidates.append({'key': f"course:{subject['name']}", 'title': f"Review {subject['name']}",
                           'course': subject['name'], 'minutes': 30,
                           'reason': (f"Prepare for {subject['deadline']}" if subject['deadline'] else
                                      'Review course concepts and solve one practice problem.'),
                           'action_id': ''})
    limit = settings['weekend_max_minutes'] if day.weekday() >= 5 else settings['weekday_max_minutes']
    allocated = sum(int(item['minutes']) for item in result)
    allocated += sum(int(item['minutes']) for item in decisions.values()
                     if item['day'] == day.isoformat() and item['status'] == 'done')
    decided_keys = {item.get('key') for item in decisions.values() if item['day'] == day.isoformat()}
    warnings = []
    for candidate in candidates:
        identity = hashlib.sha256(f"{day}:{candidate['key']}".encode()).hexdigest()[:24]
        if identity in decisions or candidate['key'] in decided_keys:
            continue
        if len(result) >= 3:
            break
        minutes = min(60, max(10, int(candidate['minutes'])))
        if allocated + minutes > limit:
            warnings.append('Daily study limit reached. Move extra work to another day.')
            break
        slot = _free_slot(day, minutes, settings, occupied, now)
        if slot is None:
            warnings.append('No free study slot inside your day. Review your commitments or move work to tomorrow.')
            break
        start, end = slot
        result.append({**candidate, 'id': identity, 'day': day.isoformat(), 'minutes': minutes,
                       'start': start.isoformat(), 'end': end.isoformat(), 'status': 'suggested'})
        occupied.append((start, end + dt.timedelta(minutes=settings['break_minutes'])))
        allocated += minutes
    return result, warnings
