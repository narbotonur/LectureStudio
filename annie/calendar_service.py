"""
Annie Google Calendar Service Module
Connects to the Google Calendar account authorized by this user:
- Lists upcoming events (today, tomorrow, this week)
- Adds events and meetings by voice
- Checks for upcoming events within T-10m and T-1h thresholds for proactive speech alerts
"""
import os
import json
import datetime
import re
from typing import Optional, List, Dict, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import httplib2
from google_auth_httplib2 import AuthorizedHttp

from annie.config import DATA_DIR, PRIVATE_PROFILE
from annie.secure_storage import read_secret, write_secret

# Google Calendar Read/Write Scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

TOKEN_PATH = os.path.join(DATA_DIR, 'calendar.dpapi' if PRIVATE_PROFILE else 'token.json')
CREDENTIALS_PATH = os.path.join(DATA_DIR, 'credentials.json')
CLIENT_PATH = os.path.join(DATA_DIR, 'google-client.dpapi')


def _read_token():
    if PRIVATE_PROFILE:
        return Credentials.from_authorized_user_info(read_secret(TOKEN_PATH), SCOPES)
    return Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)


def _write_token(creds):
    if PRIVATE_PROFILE:
        write_secret(TOKEN_PATH, json.loads(creds.to_json()))
    else:
        from annie.secure_storage import atomic_write
        atomic_write(TOKEN_PATH, creds.to_json().encode('utf-8'))


def import_client(path):
    """Accept only Google's desktop OAuth configuration, never account tokens."""
    with open(path, encoding='utf-8-sig') as stream:
        data = json.load(stream)
    client = data.get('installed', {})
    if (not client.get('client_id', '').endswith('.apps.googleusercontent.com') or
            not client.get('client_secret') or
            client.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or
            client.get('token_uri') != 'https://oauth2.googleapis.com/token'):
        raise ValueError('Choose a Google Desktop app OAuth client JSON, not a login token or service account.')
    write_secret(CLIENT_PATH, {'installed': client})


def has_client():
    return os.path.exists(CLIENT_PATH) or (not PRIVATE_PROFILE and os.path.exists(CREDENTIALS_PATH))

# Cache for announced reminders: {(event_id, '10m'): timestamp, (event_id, '1h'): timestamp}
_announced_reminders = set()


def get_calendar_credentials(interactive: bool = True) -> Optional[Credentials]:
    """Gets valid user credentials from token.json or runs OAuth flow if credentials.json is present."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = _read_token()
        except Exception as e:
            print(f"  [CALENDAR] Error loading token.json: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                request = Request()
                creds.refresh(lambda *args, **kwargs: request(
                    *args, **{**kwargs, 'timeout': 10}))
                _write_token(creds)
                print("  [CALENDAR] Token refreshed successfully.")
            except Exception as e:
                print(f"  [CALENDAR] Token refresh failed: {e}")
                creds = None

        if creds and not creds.valid:
            creds = None

        if interactive and not creds and has_client():
            try:
                if os.path.exists(CLIENT_PATH):
                    flow = InstalledAppFlow.from_client_config(read_secret(CLIENT_PATH), SCOPES)
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0, timeout_seconds=180,
                                             prompt='select_account', access_type='offline')
                _write_token(creds)
                print("  [CALENDAR] New token generated and saved to token.json.")
            except Exception as e:
                print(f"  [CALENDAR] OAuth authorization failed: {e}")
                creds = None

    return creds


def is_connected() -> bool:
    """Checks if Google Calendar is authorized and connected."""
    if os.path.exists(TOKEN_PATH):
        try:
            creds = _read_token()
            return creds.valid or (creds.expired and bool(creds.refresh_token))
        except Exception:
            return False
    return False


def get_service(interactive: bool = True):
    """Builds and returns Google Calendar API service client."""
    creds = get_calendar_credentials(interactive=interactive)
    if creds:
        try:
            transport = AuthorizedHttp(creds, http=httplib2.Http(timeout=10))
            return build('calendar', 'v3', http=transport, cache_discovery=False)
        except Exception as e:
            print(f"  [CALENDAR] Build service error: {e}")
    return None


def list_events(time_min: Optional[datetime.datetime] = None,
                time_max: Optional[datetime.datetime] = None,
                max_results: int = 250,
                interactive: bool = True,
                raise_errors: bool = False,
                paginate: bool = False) -> List[Dict]:
    """
    Fetches events from the primary calendar within the specified time range.
    """
    service = get_service(interactive=interactive)
    if not service:
        if raise_errors:
            raise RuntimeError('Calendar is not connected')
        return []

    tz = datetime.timezone(datetime.timedelta(hours=5))
    if time_min is None:
        time_min = datetime.datetime.now(tz)

    iso_min = time_min.isoformat()
    kwargs = {
        'calendarId': 'primary',
        'timeMin': iso_min,
        'maxResults': max_results,
        'singleEvents': True,
        'orderBy': 'startTime'
    }
    if time_max:
        kwargs['timeMax'] = time_max.isoformat()

    try:
        events = []
        while True:
            events_result = service.events().list(**kwargs).execute()
            events.extend(events_result.get('items', []))
            page = events_result.get('nextPageToken')
            if not paginate or not page:
                return events
            kwargs['pageToken'] = page
    except Exception as e:
        if raise_errors:
            raise
        print(f"  [CALENDAR] Fetch events error: {e}")
        return []


def get_events_for_date(target_date: datetime.date) -> List[Dict]:
    """Gets all events scheduled for a specific date in local Asia/Almaty time (+05:00)."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    start_of_day = datetime.datetime.combine(target_date, datetime.time.min).replace(tzinfo=tz)
    end_of_day = datetime.datetime.combine(target_date, datetime.time.max).replace(tzinfo=tz)
    return list_events(time_min=start_of_day, time_max=end_of_day, max_results=250)


def get_events_for_range(start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
    """Gets all events between start_date and end_date inclusive."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    start_dt = datetime.datetime.combine(start_date, datetime.time.min).replace(tzinfo=tz)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max).replace(tzinfo=tz)
    return list_events(time_min=start_dt, time_max=end_dt, max_results=250)


def get_week_schedule(target_date: Optional[datetime.date] = None) -> Dict[str, List[Dict]]:
    """
    Fetches full schedule for Monday-Sunday of the week containing target_date.
    Returns dictionary with days 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'.
    """
    tz = datetime.timezone(datetime.timedelta(hours=5))
    base = target_date or datetime.datetime.now(tz).date()
    monday = base - datetime.timedelta(days=base.weekday())
    sunday = monday + datetime.timedelta(days=6)

    start_dt = datetime.datetime.combine(monday, datetime.time.min).replace(tzinfo=tz)
    end_dt = datetime.datetime.combine(sunday, datetime.time.max).replace(tzinfo=tz)

    all_events = list_events(time_min=start_dt, time_max=end_dt, max_results=250)
    
    day_map = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}
    schedule = {d: [] for d in day_map.values()}

    for ev in all_events:
        st = ev.get('start', {})
        dt_str = st.get('dateTime') or st.get('date')
        if dt_str:
            try:
                if 'T' in dt_str:
                    event_dt = datetime.datetime.fromisoformat(dt_str)
                    ev_date = event_dt.date()
                else:
                    ev_date = datetime.date.fromisoformat(dt_str)
                w_day = ev_date.weekday()
                if w_day in day_map:
                    schedule[day_map[w_day]].append(ev)
            except Exception:
                pass

    return schedule


def get_all_upcoming_events(days: int = 30) -> List[Dict]:
    """Fetches all upcoming events for the next N days."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    now = datetime.datetime.now(tz)
    end = now + datetime.timedelta(days=days)
    return list_events(time_min=now, time_max=end, max_results=250)


def get_today_events() -> List[Dict]:
    """Gets all events scheduled for today (full day 00:00 to 23:59)."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    today = datetime.datetime.now(tz).date()
    return get_events_for_date(today)


def get_tomorrow_events() -> List[Dict]:
    """Gets all events scheduled for tomorrow (full day 00:00 to 23:59)."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    tomorrow = datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
    return get_events_for_date(tomorrow)


def create_event(summary: str,
                 start_dt: datetime.datetime,
                 end_dt: Optional[datetime.datetime] = None,
                 description: str = "",
                 location: str = "") -> Tuple[bool, str]:
    """
    Creates a new event in Google Calendar.
    """
    service = get_service()
    if not service:
        return False, "Google Calendar не подключен. Пожалуйста, авторизуйтесь через credentials.json."

    if end_dt is None:
        end_dt = start_dt + datetime.timedelta(hours=1)

    event_body = {
        'summary': summary,
        'description': description,
        'location': location,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Asia/Almaty',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Asia/Almaty',
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 10},
                {'method': 'popup', 'minutes': 60},
            ],
        },
    }

    try:
        created = service.events().insert(calendarId='primary', body=event_body).execute()
        time_str = start_dt.strftime("%H:%M")
        date_str = start_dt.strftime("%d.%m")
        return True, f"Событие '{summary}' успешно добавлено в Google Calendar на {date_str} в {time_str}."
    except Exception as e:
        print(f"  [CALENDAR] Create event error: {e}")
        return False, f"Не удалось добавить событие: {e}"


def _clean_title(text: str) -> str:
    if not text:
        return "Без названия"
    # Replace unicode replacement character or weird dashes
    text = text.replace('\ufffd', '-').replace('\u2013', '-').replace('\u2014', '-')
    text = "".join(ch for ch in text if ch.isprintable())
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def format_events_speech(events: List[Dict], day_label: str = "сегодня") -> str:
    """Formats a list of Google Calendar events into natural Russian speech."""
    if not events:
        return f"Сэр, на {day_label} в вашем календаре ничего не запланировано."

    count = len(events)
    if count == 1:
        prefix = f"Сэр, на {day_label} у вас запланировано 1 событие:"
    elif count in [2, 3, 4]:
        prefix = f"Сэр, на {day_label} у вас запланировано {count} события:"
    else:
        prefix = f"Сэр, на {day_label} у вас запланировано {count} событий:"

    items = []
    for ev in events:
        summary = _clean_title(ev.get('summary', 'Без названия'))
        start = ev.get('start', {})
        dt_str = start.get('dateTime') or start.get('date')
        if dt_str:
            try:
                if 'T' in dt_str:
                    dt = datetime.datetime.fromisoformat(dt_str)
                    time_part = dt.strftime("%H:%M")
                    items.append(f"в {time_part} — {summary}")
                else:
                    items.append(f"весь день — {summary}")
            except Exception:
                items.append(summary)
        else:
            items.append(summary)

    return prefix + " " + ", ".join(items) + "."


def check_upcoming_reminders() -> List[str]:
    """
    Checks events starting in the next ~10 minutes or ~1 hour.
    Returns a list of Russian spoken alert phrases for unannounced events.
    """
    global _announced_reminders
    now = datetime.datetime.now(datetime.timezone.utc)
    lookahead = now + datetime.timedelta(minutes=75)

    events = list_events(time_min=now, time_max=lookahead, max_results=10,
                         interactive=False)
    alerts = []

    for ev in events:
        ev_id = ev.get('id')
        summary = ev.get('summary', 'событие')
        start = ev.get('start', {})
        dt_str = start.get('dateTime')

        if not ev_id or not dt_str:
            continue

        try:
            start_dt = datetime.datetime.fromisoformat(dt_str)
            delta_minutes = (start_dt - now).total_seconds() / 60.0

            # 1. Check ~10 minutes threshold (8 to 12 minutes)
            if 7.0 <= delta_minutes <= 12.0:
                key = (ev_id, '10m')
                if key not in _announced_reminders:
                    _announced_reminders.add(key)
                    alerts.append(f"Сэр, вы в курсе, что через 10 минут у вас начинается {summary}?")

            # 2. Check ~1 hour threshold (55 to 65 minutes)
            elif 53.0 <= delta_minutes <= 65.0:
                key = (ev_id, '1h')
                if key not in _announced_reminders:
                    _announced_reminders.add(key)
                    alerts.append(f"Сэр, напоминаю: через один час у вас запланировано {summary}.")

        except Exception as e:
            print(f"  [CALENDAR REMINDER] Parse error for event {ev_id}: {e}")

    return alerts


def _looks_like_lecture_event(event: Dict) -> bool:
    """Return whether a calendar item looks like a university class."""
    title = _clean_title(event.get('summary', 'Lecture'))
    class_words = (
        'lecture', 'class', 'seminar', 'tutorial', 'lab', 'course',
        'лекц', 'занят', 'семинар', 'лаборатор',
    )
    return (bool(re.search(r'\b[A-Za-z]{2,}\s*[- ]?\d{2,4}\b', title)) or
            any(word in title.lower() for word in class_words))


def get_daily_lecture_schedule(
        target_date: Optional[datetime.date] = None) -> List[Dict]:
    """Download the timed, class-like events for one local calendar day."""
    tz = datetime.timezone(datetime.timedelta(hours=5))
    day = target_date or datetime.datetime.now(tz).date()
    start = datetime.datetime.combine(day, datetime.time.min).replace(tzinfo=tz)
    end = datetime.datetime.combine(day, datetime.time.max).replace(tzinfo=tz)
    events = list_events(
        time_min=start,
        time_max=end,
        max_results=250,
        interactive=False,
    )
    return [
        event for event in events
        if event.get('start', {}).get('dateTime') and _looks_like_lecture_event(event)
    ]


def get_starting_lecture_events(window_before_minutes: float = 2.0,
                                window_after_minutes: float = 3.0) -> List[Dict]:
    """Return class-like timed events whose start time is effectively now."""
    now = datetime.datetime.now(datetime.timezone.utc)
    events = list_events(
        time_min=now - datetime.timedelta(minutes=window_after_minutes),
        time_max=now + datetime.timedelta(minutes=window_before_minutes),
        max_results=20,
        interactive=False,
    )
    result = []
    for event in events:
        start_text = event.get('start', {}).get('dateTime')
        if not start_text:
            continue
        if not _looks_like_lecture_event(event):
            continue
        try:
            start = datetime.datetime.fromisoformat(start_text.replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=datetime.timezone.utc)
            delta = (start.astimezone(datetime.timezone.utc) - now).total_seconds() / 60
            if -window_after_minutes <= delta <= window_before_minutes:
                result.append(event)
        except (TypeError, ValueError):
            continue
    return result
