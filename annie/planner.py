"""Deterministic weekly planning around fixed commitments and personal goals."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from annie.secure_storage import atomic_write

TZ = dt.timezone(dt.timedelta(hours=5))
DEFAULT_SETTINGS = {
    'day_start': '08:00', 'day_end': '22:00', 'preferred_study': '17:00',
    'block_minutes': 50, 'break_minutes': 10, 'weekly_study_minutes': 600,
    'weekday_max_minutes': 180, 'weekend_max_minutes': 240,
    'prayer_block_minutes': 30, 'jumuah_enabled': True,
    'jumuah_start': '12:30', 'jumuah_end': '14:00',
}


def _clock(value):
    try:
        parsed = dt.time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('Planner times must use HH:MM.') from None
    return parsed.hour * 60 + parsed.minute


def validate_settings(settings):
    result = {**DEFAULT_SETTINGS, **(settings or {})}
    for key in ('day_start', 'day_end', 'preferred_study', 'jumuah_start', 'jumuah_end'):
        if not isinstance(result[key], str):
            raise ValueError('Planner times must use HH:MM.')
        _clock(result[key])
    if _clock(result['day_end']) - _clock(result['day_start']) < 180:
        raise ValueError('The planning day must be at least three hours long.')
    if _clock(result['jumuah_end']) <= _clock(result['jumuah_start']):
        raise ValueError('Jumuah end time must be after its start time.')
    limits = {
        'block_minutes': (20, 120), 'break_minutes': (0, 60),
        'weekly_study_minutes': (0, 3000), 'weekday_max_minutes': (0, 720),
        'weekend_max_minutes': (0, 720), 'prayer_block_minutes': (10, 90),
    }
    for key, (low, high) in limits.items():
        value = result[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key.replace("_", " ").title()} must be between {low} and {high}.')
    result['jumuah_enabled'] = bool(result['jumuah_enabled'])
    return result


class PlannerStore:
    def __init__(self, root=None):
        if root is None:
            from annie.paths import DATA_DIR
            root = DATA_DIR
        self.path = Path(root) / 'weekly-plans.json'

    def _data(self):
        if not self.path.exists():
            return {'version': 1, 'settings': dict(DEFAULT_SETTINGS), 'weeks': {}}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('weeks'), dict):
                raise ValueError
            data['settings'] = validate_settings(data.get('settings'))
            return data
        except Exception:
            raise ValueError('Saved weekly plans are unreadable. The file was left unchanged.') from None

    def settings(self):
        return validate_settings(self._data()['settings'])

    def save_settings(self, settings):
        data = self._data()
        data['settings'] = validate_settings(settings)
        self._write(data)

    def week(self, monday):
        data = self._data()
        blocks = data['weeks'].get(monday.isoformat(), {}).get('blocks', [])
        return self._validated_blocks(blocks, monday)

    def save_week(self, monday, blocks, generated_at=None):
        data = self._data()
        blocks = self._validated_blocks(blocks, monday)
        data['weeks'][monday.isoformat()] = {
            'generated_at': (generated_at or dt.datetime.now(dt.timezone.utc)).isoformat(),
            'blocks': blocks,
        }
        # Keep the profile small while preserving nearby plans.
        for key in sorted(data['weeks'])[:-12]:
            del data['weeks'][key]
        self._write(data)

    @staticmethod
    def _validated_blocks(blocks, monday):
        if not isinstance(blocks, list) or len(blocks) > 500:
            raise ValueError('The saved weekly plan has an invalid block list.')
        result = []
        week_end = monday + dt.timedelta(days=7)
        for block in blocks:
            try:
                start = dt.datetime.fromisoformat(block['start'])
                end = dt.datetime.fromisoformat(block['end'])
                valid = (isinstance(block, dict) and block['kind'] in
                         ('study', 'habit', 'prayer', 'jumuah')
                         and isinstance(block['title'], str) and 0 < len(block['title']) <= 200
                         and isinstance(block['id'], str) and len(block['id']) == 24
                         and start.utcoffset() is not None and end > start
                         and monday <= start.astimezone(TZ).date() < week_end)
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                raise ValueError('The saved weekly plan contains an invalid block.')
            result.append(dict(block))
        return result

    def _write(self, data):
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))


def _event_interval(event):
    try:
        start_data, end_data = event['start'], event['end']
        if 'dateTime' not in start_data or 'dateTime' not in end_data:
            return None
        start = dt.datetime.fromisoformat(start_data['dateTime'].replace('Z', '+00:00'))
        end = dt.datetime.fromisoformat(end_data['dateTime'].replace('Z', '+00:00'))
        start = start.replace(tzinfo=TZ) if start.tzinfo is None else start.astimezone(TZ)
        end = end.replace(tzinfo=TZ) if end.tzinfo is None else end.astimezone(TZ)
        return (start, end) if end > start else None
    except (KeyError, TypeError, ValueError):
        return None


def _overlaps(start, end, occupied):
    return any(start < right and end > left for left, right in occupied)


def _identifier(kind, title, start):
    raw = f'{kind}|{title}|{start.isoformat()}'.encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _block(kind, title, start, end, detail=''):
    return {'id': _identifier(kind, title, start), 'kind': kind, 'title': title,
            'start': start.isoformat(timespec='minutes'),
            'end': end.isoformat(timespec='minutes'), 'detail': detail}


def blocks_as_events(blocks):
    colors = {'study': 'Study plan', 'habit': 'Habit', 'prayer': 'Prayer', 'jumuah': 'Jumuah'}
    return [{'id': 'annieplan' + item['id'], 'summary': item['title'],
             'description': item.get('detail', ''),
             'start': {'dateTime': item['start']}, 'end': {'dateTime': item['end']},
             'extendedProperties': {'private': {'anniePlanBlock': item['id'],
                                                'anniePlanKind': item['kind']}},
             'location': colors.get(item['kind'], '')} for item in blocks]


def _free_slot(day, minutes, settings, occupied, now):
    start_limit = _clock(settings['day_start'])
    end_limit = _clock(settings['day_end'])
    preferred = max(start_limit, min(end_limit, _clock(settings['preferred_study'])))
    if day == now.date():
        current = now.hour * 60 + now.minute
        start_limit = max(start_limit, int(math.ceil((current + 10) / 10) * 10))
    candidates = list(range(max(start_limit, preferred), end_limit - minutes + 1, 10))
    candidates += list(range(start_limit, min(preferred, end_limit - minutes + 1), 10))
    midnight = dt.datetime.combine(day, dt.time(), TZ)
    for minute in candidates:
        start = midnight + dt.timedelta(minutes=minute)
        end = start + dt.timedelta(minutes=minutes)
        if not _overlaps(start, end, occupied):
            return start, end
    return None


def _deadline_date(item):
    try:
        return dt.datetime.fromisoformat(item['due_at']).astimezone(TZ).date()
    except (KeyError, TypeError, ValueError):
        return None


def _subjects(courses, deadlines, monday):
    open_deadlines = [item for item in deadlines if item.get('status', 'open') == 'open'
                      and _deadline_date(item)]
    result = []
    known = set()
    for course in courses:
        current = course.get('current_percent')
        gap = course['target_percent'] - current if current is not None else 5
        priority = max(1.0, course['credits'] / 2 + max(0, gap) / 5)
        matching = [item for item in open_deadlines
                    if item.get('course', '').casefold() == course['name'].casefold()
                    or course['name'].casefold() in item.get('title', '').casefold()]
        due = min((_deadline_date(item) for item in matching), default=None)
        if due:
            distance = (due - monday).days
            priority += 8 if distance <= 2 else 5 if distance <= 7 else 2 if distance <= 14 else 0
        result.append({'name': course['name'], 'priority': priority, 'due': due,
                       'deadline': matching[0]['title'] if matching else '', 'allocated': 0})
        known.add(course['name'].casefold())
    for item in open_deadlines:
        name = ' '.join(item.get('course', '').split())
        if not name or name.casefold() in known:
            continue
        result.append({'name': name, 'priority': 8, 'due': _deadline_date(item),
                       'deadline': item.get('title', ''), 'allocated': 0})
        known.add(name.casefold())
    return result


def generate_week(monday, settings, calendar_events=(), prayer_days=None,
                  habits=(), courses=(), deadlines=(), now=None):
    settings = validate_settings(settings)
    now = now or dt.datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    prayer_days = prayer_days or {}
    days = [monday + dt.timedelta(days=index) for index in range(7)]
    occupied = {day: [] for day in days}
    for event in calendar_events:
        interval = _event_interval(event)
        if not interval or event.get('status') == 'cancelled':
            continue
        start, end = interval
        for day in days:
            left = dt.datetime.combine(day, dt.time(), TZ)
            right = left + dt.timedelta(days=1)
            if start < right and end > left:
                occupied[day].append((max(start, left), min(end, right)))
    blocks, warnings = [], []
    day_start, day_end = _clock(settings['day_start']), _clock(settings['day_end'])

    # Prayer and Jumuah are fixed constraints and visible in the resulting plan.
    for day in days:
        if day < now.date():
            continue
        midnight = dt.datetime.combine(day, dt.time(), TZ)
        times = prayer_days.get(day, {})
        for prayer in ('Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha'):
            if day.weekday() == 4 and prayer == 'Dhuhr' and settings['jumuah_enabled']:
                continue
            try:
                when = dt.datetime.fromisoformat(times[prayer]).astimezone(TZ)
            except (KeyError, TypeError, ValueError):
                continue
            minute = when.hour * 60 + when.minute
            if minute < day_start or minute >= day_end:
                continue
            start = when - dt.timedelta(minutes=5)
            end = start + dt.timedelta(minutes=settings['prayer_block_minutes'])
            if end <= now:
                continue
            occupied[day].append((start, end))
            blocks.append(_block('prayer', f'Prayer · {prayer}', start, end,
                                 'Calculated from your prayer widget settings.'))
        if day.weekday() == 4 and settings['jumuah_enabled']:
            start = midnight + dt.timedelta(minutes=_clock(settings['jumuah_start']))
            end = midnight + dt.timedelta(minutes=_clock(settings['jumuah_end']))
            if end <= now:
                continue
            occupied[day].append((start, end))
            blocks.append(_block('jumuah', 'Jumuah', start, end,
                                 'Protected time including the configured travel window.'))

    # Scheduled habits get their preferred time first; otherwise the first free slot.
    for habit in habits:
        created = dt.datetime.fromtimestamp(habit['created'], TZ).date()
        for day in days:
            if day < max(created, now.date()) or not (habit['days_mask'] & (1 << day.weekday())):
                continue
            duration = (min(120, max(10, round(habit['target'])))
                        if habit['kind'] == 'minutes' else 30 if habit['kind'] == 'count' else 15)
            midnight = dt.datetime.combine(day, dt.time(), TZ)
            slot = None
            if habit.get('preferred_time'):
                minute = _clock(habit['preferred_time'])
                start, end = midnight + dt.timedelta(minutes=minute), midnight + dt.timedelta(minutes=minute + duration)
                if day == now.date() and start <= now + dt.timedelta(minutes=10):
                    pass
                elif day_start <= minute and minute + duration <= day_end and not _overlaps(start, end, occupied[day]):
                    slot = start, end
            slot = slot or _free_slot(day, duration, settings, occupied[day], now)
            if not slot:
                warnings.append(f"No free time for habit: {habit['name']} ({day:%a}).")
                continue
            start, end = slot
            occupied[day].append((start, end))
            blocks.append(_block('habit', f"Habit · {habit['name']}", start, end,
                                 f"Daily goal: {habit['target']:g} {habit['unit'] or 'done'}"))

    subjects = _subjects(courses, deadlines, monday)
    if not subjects and settings['weekly_study_minutes']:
        warnings.append('Add courses in GPA to generate focused study blocks.')
    remaining = settings['weekly_study_minutes']
    study_by_day = {day: 0 for day in days}
    active_days = [day for day in days if day >= now.date()]
    while remaining > 0 and subjects and active_days:
        progress = False
        for day in list(active_days):
            daily_limit = settings['weekend_max_minutes'] if day.weekday() >= 5 else settings['weekday_max_minutes']
            duration = min(settings['block_minutes'], remaining, daily_limit - study_by_day[day])
            if duration <= 0:
                active_days.remove(day)
                continue
            eligible = [subject for subject in subjects if subject['due'] is None or day <= subject['due']]
            if not eligible:
                eligible = subjects
            subject = min(eligible, key=lambda item: (item['allocated'] / item['priority'],
                                                       -item['priority'], item['name']))
            slot = _free_slot(day, duration, settings, occupied[day], now)
            if not slot:
                active_days.remove(day)
                continue
            start, end = slot
            title = f"Study · {subject['name']}"
            detail = (f"Priority uses credits, current GPA gap"
                      + (f" and deadline: {subject['deadline']}" if subject['deadline'] else '') + '.')
            blocks.append(_block('study', title, start, end, detail))
            occupied[day].append((start, end + dt.timedelta(minutes=settings['break_minutes'])))
            study_by_day[day] += duration
            subject['allocated'] += duration
            remaining -= duration
            progress = True
            if remaining <= 0:
                break
        if not progress:
            break
    if remaining > 0 and subjects:
        warnings.append(f'{remaining} study minutes did not fit inside the configured limits.')
    blocks.sort(key=lambda item: item['start'])
    return {'blocks': blocks, 'warnings': warnings,
            'planned_study_minutes': settings['weekly_study_minutes'] - remaining}
