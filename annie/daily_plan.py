"""Small, reviewable daily suggestions; no calendar writes or background inference."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import uuid

from annie.planner import TZ, _clock, _event_interval, _free_slot, _overlaps, _subjects, validate_settings
from annie.habits import schedule_for, scheduled


def _identity(day, key):
    return hashlib.sha256(f"{day}:{key}".encode()).hexdigest()[:24]


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
            payload['id'] = _identity(target, item['key'])
        with self._connect() as db:
            query = ('INSERT INTO decisions VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                     'day=excluded.day,status=excluded.status,payload=excluded.payload')
            if status == 'tomorrow':
                db.execute(query, (item['id'], item['day'], 'skipped', json.dumps(origin)))
            db.execute(query, (payload['id'], target.isoformat(), status, json.dumps(payload)))

    def schedule(self, item=None, *, title, course='', start, minutes, pinned=False):
        """Add or move a block. Moving suppresses the old suggestion atomically."""
        if not title.strip() or len(title) > 160 or len(course) > 100:
            raise ValueError('Enter a title up to 160 characters and a course up to 100.')
        if type(minutes) is not int or not 1 <= minutes <= 720:
            raise ValueError('Choose a duration between 1 and 720 minutes.')
        start = _local_time(start)
        end = start + dt.timedelta(minutes=minutes)
        if end.date() > start.date() and end.time() != dt.time():
            raise ValueError('The plan block must finish on the same day.')
        day = start.date().isoformat()
        key = item['key'] if item else f'manual:{uuid.uuid4().hex}'
        payload = {**(item or {'reason': 'Manual study block', 'action_id': ''}),
                   'id': _identity(day, key), 'key': key, 'day': day, 'title': title.strip(),
                   'course': course.strip(), 'start': start.isoformat(), 'end': end.isoformat(),
                   'minutes': minutes, 'pinned': bool(pinned)}
        if item and title.strip() != item.get('title'):
            payload['custom_title'] = True
        with self._connect() as db:
            query = ('INSERT INTO decisions VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                     'day=excluded.day,status=excluded.status,payload=excluded.payload')
            if item and item['id'] != payload['id']:
                db.execute(query, (item['id'], item['day'], 'skipped', json.dumps(item)))
            db.execute(query, (payload['id'], day, 'accepted', json.dumps(payload)))
        return payload

    def missed(self, day):
        """Return the most recent unfinished decision for each key before day."""
        latest = {}
        for item in sorted(self.decisions().values(), key=lambda item: item['day']):
            latest[item['key']] = item
        return [item for item in reversed(list(latest.values()))
                if item['day'] < day.isoformat() and item['status'] in ('accepted', 'tomorrow')]

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
        if not scheduled(habit, day):
            continue
        minute = None
        anchor = habit.get('anchor', '')
        prayer = {'after_fajr': 'Fajr', 'after_maghrib': 'Maghrib'}.get(anchor)
        if prayer and (prayers or {}).get(prayer):
            value = _local_time(prayers[prayer]) + dt.timedelta(minutes=settings['prayer_block_minutes'])
            minute = value.hour * 60 + value.minute
        else:
            _, preferred = schedule_for(habit, day)
            if preferred:
                minute = _clock(preferred)
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
    result, warnings = [], []
    closed = {deadline.get('origin_assignment_id') or deadline.get('id') for deadline in deadlines
              if deadline.get('status', 'open') != 'open'}
    closed.discard(None)
    for saved in decisions.values():
        if saved['day'] == day.isoformat() and saved['status'] in ('accepted', 'tomorrow'):
            if saved.get('deadline_id') in closed:
                continue
            saved = dict(saved)
            if saved.get('start') and saved.get('end'):
                start, end = _local_time(saved['start']), _local_time(saved['end'])
                if _overlaps(start, end, occupied):
                    saved['conflict'] = 'Overlaps a calendar event, protected time, or another study block.'
                occupied.append((start, end))
            result.append(saved)
    candidates = []
    for task in tasks:
        candidates.append({'key': f"task:{task['id']}", 'title': task['summary'],
                           'course': task.get('course', ''), 'minutes': task.get('minutes') or 30,
                           'reason': task.get('suggested_action') or 'Approved lecture action',
                           'action_id': task['id']})
    specific_courses = {task.get('course', '').casefold() for task in tasks}
    # A reviewed deadline is useful even before the user configures GPA courses.
    # This is a suggested work block, not an invented instruction from a lecturer.
    dated = []
    for deadline in deadlines:
        if deadline.get('status', 'open') != 'open' or not deadline.get('id') or not deadline.get('title'):
            continue
        try:
            due = _local_time(deadline['due_at'])
        except (ValueError, TypeError, KeyError):
            continue
        dated.append((due, deadline))
    for due, deadline in sorted(dated, key=lambda item: item[0]):
        origin = deadline.get('origin_assignment_id') or deadline['id']
        title = ('Follow up on overdue ' if due <= now else 'Work on ') + deadline['title']
        reason = f"{'Overdue' if due <= now else 'Due'} {due:%d %b %H:%M} · confirmed local deadline"
        existing = next((item for item in result if item.get('deadline_id') == origin), None)
        if existing is not None:
            if not existing.get('custom_title'):
                existing['title'] = title
            existing['reason'] = reason
            if existing.get('end') and _local_time(existing['end']) > due:
                conflict = 'This study block ends after the deadline.'
                existing['conflict'] = ' '.join(filter(None, (existing.get('conflict'), conflict)))
        candidates.append({'key': f'deadline:{origin}', 'title': title,
                           'course': deadline.get('course', ''), 'minutes': 10 if due <= now else 25,
                           'reason': reason, 'action_id': '', 'deadline_id': origin,
                           'due_at': due.isoformat() if due > now else None})
        specific_courses.add(deadline.get('course', '').casefold())
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
    warnings.extend(item['title'] + ' · ' + item['conflict'] for item in result if item.get('conflict'))
    for candidate in candidates:
        identity = _identity(day, candidate['key'])
        if identity in decisions or candidate['key'] in decided_keys:
            continue
        if len(result) >= 3:
            break
        minutes = min(60, max(10, int(candidate['minutes'])))
        if allocated + minutes > limit:
            warnings.append('Some study blocks exceed the remaining daily limit.')
            continue
        due = _local_time(candidate['due_at']) if candidate.get('due_at') else None
        slot = _free_slot(day, minutes, settings, occupied, now, due_at=due)
        if slot is None:
            if due and due.date() == day:
                warnings.append(f"No free {minutes}-minute slot for {candidate['title'].removeprefix('Work on ')} "
                                f"before {due:%H:%M}.")
            else:
                warnings.append('Some study blocks do not fit in the remaining free time.')
            continue
        start, end = slot
        result.append({**candidate, 'id': identity, 'day': day.isoformat(), 'minutes': minutes,
                       'start': start.isoformat(), 'end': end.isoformat(), 'status': 'suggested'})
        occupied.append((start, end + dt.timedelta(minutes=settings['break_minutes'])))
        allocated += minutes
    return sorted(result, key=lambda item: (not item.get('pinned'), item.get('start') or '')), list(dict.fromkeys(warnings))
