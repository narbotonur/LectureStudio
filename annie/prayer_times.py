"""Opt-in, city-based AlAdhan schedules. No GPS, IP lookup or account access.

Calculation conventions are explicit, not presented as an official mosque
timetable. API school=1 is the two-shadow Hanafi Asr; school=0 is the standard
one-shadow Asr used here for Shafi'i, Maliki and Hanbali (excluding noon shadow).
Source: https://aladhan.com/prayer-times-api and /v1/methods.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from annie.paths import DATA_DIR
from annie.secure_storage import atomic_write

PRAYERS = ('Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha')
DISPLAY_TIMES = ('Fajr', 'Sunrise', 'Dhuhr', 'Asr', 'Maghrib', 'Isha')
NAMES = dict(zip(DISPLAY_TIMES, ('Фаджр', 'Восход', 'Зухр', 'Аср', 'Магриб', 'Иша')))
MADHHABS = {'hanafi': 'Ханафитский', 'shafii': 'Шафиитский',
            'maliki': 'Маликитский', 'hanbali': 'Ханбалитский'}
METHODS = {1: 'Karachi · Фаджр 18° / Иша 18°', 3: 'Muslim World League · 18° / 17°',
           2: 'ISNA · 15° / 15°', 5: 'Egyptian Survey · 19.5° / 17.5°',
           4: 'Umm al-Qura · Makkah', 14: 'ДУМ России · 16° / 15°',
           15: 'Moonsighting Committee Worldwide'}


@dataclass
class PrayerSettings:
    city: str = ''
    country: str = ''
    madhhab: str = 'hanafi'
    method: int = 1
    adjustments: dict = field(default_factory=lambda: {name: 0 for name in DISPLAY_TIMES})
    compact: bool = False
    always_on_top: bool = False
    desktop_pinned: bool = False
    position: list = field(default_factory=list)

    def validate(self, require_city=True):
        self.city, self.country = self.city.strip(), self.country.strip()
        if require_city and (not self.city or not self.country):
            raise ValueError('Укажите город и страну. Автоопределение местоположения не используется.')
        if len(self.city) > 120 or len(self.country) > 120:
            raise ValueError('Название города или страны слишком длинное.')
        if self.desktop_pinned:
            self.always_on_top = False
        if self.madhhab not in MADHHABS or self.method not in METHODS:
            raise ValueError('Выберите мазхаб и метод расчёта из списка.')
        if not isinstance(self.adjustments, dict):
            raise ValueError('Некорректные поправки времени.')
        for name in DISPLAY_TIMES:
            value = self.adjustments.get(name, 0)
            if type(value) is not int or not -60 <= value <= 60:
                raise ValueError('Поправки должны быть от −60 до +60 минут.')
        if (not isinstance(self.position, list) or len(self.position) not in (0, 2)
                or any(type(v) is not int for v in self.position)):
            self.position = []
        return self

    @property
    def school(self):
        return 1 if self.madhhab == 'hanafi' else 0

    @property
    def signature(self):
        data = [self.city.casefold().strip(), self.country.casefold().strip(),
                self.school, self.method, self.adjustments]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class PrayerStore:
    def __init__(self, directory=None):
        self.root = Path(directory) if directory is not None else Path(DATA_DIR)
        self.settings_path = self.root / 'prayer-widget.json'
        self.cache_path = self.root / 'prayer-times-cache.json'

    def settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            return PrayerSettings(**{key: value for key, value in data.items()
                                     if key in PrayerSettings.__dataclass_fields__}).validate(False)
        except (OSError, ValueError, TypeError, AttributeError):
            return PrayerSettings()

    def save_settings(self, settings):
        settings.validate()
        atomic_write(self.settings_path, json.dumps(asdict(settings), ensure_ascii=False).encode('utf-8'))

    def cache(self, settings):
        try:
            data = json.loads(self.cache_path.read_text(encoding='utf-8'))
            if data.get('signature') != settings.signature:
                return None
            ZoneInfo(data['timezone'])
            for day in data['days']:
                for name in DISPLAY_TIMES:
                    if datetime.fromisoformat(day['times'][name]).utcoffset() is None:
                        return None
            if not data['days']:
                return None
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_cache(self, data):
        atomic_write(self.cache_path, json.dumps(data, ensure_ascii=False).encode('utf-8'))


def local_now(data=None, now=None):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError('A timezone-aware clock is required.')
    return now.astimezone(ZoneInfo(data['timezone'])) if data else now.astimezone()


def today_schedule(data, now=None):
    if not data:
        return None
    today = local_now(data, now).date().isoformat()
    return next((day for day in data['days'] if day['date'] == today), None)


def next_prayer(data, now=None):
    """Sunrise is informational, never one of the five obligatory prayers."""
    if not data or not today_schedule(data, now):
        return None
    now = now or datetime.now(timezone.utc)
    upcoming = [(datetime.fromisoformat(day['times'][name]), name)
                for day in data['days'] for name in PRAYERS
                if datetime.fromisoformat(day['times'][name]) > now]
    return min(upcoming) if upcoming else None


def fetch_schedule(settings, old=None, now=None, get=None, cancelled=None):
    """Fetch today + tomorrow once per refresh, preserving tomorrow's actual Fajr.

    ISO timestamps retain offsets across DST. Failed/partial responses never
    replace the cache. No inference from yesterday's times or zero placeholders.
    """
    settings.validate()
    now = now or datetime.now(timezone.utc)
    get = get or requests.get
    cancelled = cancelled or (lambda: False)

    def fetch(day):
        if cancelled():
            raise InterruptedError('Обновление отменено.')
        response = get('https://api.aladhan.com/v1/timingsByCity/' + day.strftime('%d-%m-%Y'),
                       params={'city': settings.city, 'country': settings.country,
                               'method': settings.method, 'school': settings.school,
                               'latitudeAdjustmentMethod': 3, 'iso8601': 'true'}, timeout=(5, 15))
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 200:
            raise ValueError('Источник не вернул расписание для этого города.')
        raw = result['data']
        zone = ZoneInfo(raw['meta']['timezone'])
        returned_day = datetime.strptime(raw['date']['gregorian']['date'], '%d-%m-%Y').date()
        if returned_day != day:
            raise ValueError('Источник вернул расписание на другую дату.')
        times = {}
        for name in DISPLAY_TIMES:
            value = datetime.fromisoformat(raw['timings'][name])
            if value.utcoffset() is None:
                raise ValueError('Источник не указал часовой пояс времени намаза.')
            times[name] = (value + timedelta(minutes=settings.adjustments.get(name, 0))).isoformat()
        ordered = [datetime.fromisoformat(times[name]) for name in DISPLAY_TIMES]
        if any(right <= left for left, right in zip(ordered, ordered[1:])):
            raise ValueError('Времена нарушают порядок молитв. Проверьте метод и поправки.')
        hijri = raw['date'].get('hijri', {})
        hijri_text = ' '.join(str(v) for v in (hijri.get('day', ''),
                           hijri.get('month', {}).get('en', ''), hijri.get('year', ''))).strip()
        return {'date': day.isoformat(), 'times': times, 'hijri': hijri_text}, zone.key

    day = local_now(old, now).date()
    first, zone = fetch(day)
    actual_day = now.astimezone(ZoneInfo(zone)).date()
    if actual_day != day:
        day = actual_day
        first, zone = fetch(day)
    second, second_zone = fetch(day + timedelta(days=1))
    if second_zone != zone or cancelled():
        raise ValueError('Обновление отменено или часовой пояс источника изменился.')
    return {'signature': settings.signature, 'timezone': zone, 'fetched_at': now.isoformat(),
            'refresh_day': day.isoformat(), 'source': 'AlAdhan', 'method': settings.method,
            'city': settings.city, 'country': settings.country, 'days': [first, second]}


def refresh_due(data, now=None):
    return not data or data.get('refresh_day') != local_now(data, now).date().isoformat()
