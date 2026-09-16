"""Explicit Moodle calendar connection checks; no browser cookies or password login.

Step one only previews event titles. It does not expand recurrences, infer which
events are deadlines, or publish anything to the user's other calendars.
"""
import datetime as dt
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests

from annie.secure_storage import delete_secret, read_secret, write_secret

MAX_BYTES = 2 * 1024 * 1024


class MoodleError(ValueError):
    pass


def validate_url(value):
    value = value.strip()
    try:
        parts = urlsplit(value)
        port = parts.port
        valid = (parts.scheme == 'https' and parts.hostname and not parts.username
                 and not parts.password and not parts.fragment
                 and (port is None or 1 <= port <= 65535)
                 and not re.search(r'\s', value))
    except ValueError:
        valid = False
    if not valid:
        raise MoodleError('Paste the full HTTPS calendar export URL from Moodle, not your password.')
    return value


def preview_calendar(raw):
    """Validate the calendar envelope and preview SUMMARY fields, not deadlines."""
    if len(raw) > MAX_BYTES:
        raise MoodleError('This calendar is too large. Export a shorter date range in Moodle.')
    try:
        source = raw.decode('utf-8-sig')
    except UnicodeError:
        raise MoodleError('Moodle did not return a UTF-8 calendar file.') from None
    source = source.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not source.startswith('BEGIN:VCALENDAR\n'):
        raise MoodleError('This link returned a page instead of a calendar. Sign in to Moodle in your browser, then use Export calendar > Get calendar URL.')
    lines = re.sub(r'\n[ \t]', '', source).split('\n')
    stack, titles = [], []
    version, closed, summary = False, False, ''
    for line in lines:
        if not line:
            continue
        key, colon, value = line.partition(':')
        if not colon or closed:
            raise MoodleError('The calendar file is incomplete or invalid. Generate a fresh export URL.')
        prop = key.split(';', 1)[0].upper()
        if prop == 'BEGIN':
            if (not stack and value != 'VCALENDAR') or (stack and value == 'VCALENDAR'):
                raise MoodleError('The calendar file has an invalid structure.')
            if value == 'VEVENT':
                if stack != ['VCALENDAR']:
                    raise MoodleError('The calendar file has an invalid event structure.')
                summary = ''
            stack.append(value)
        elif prop == 'END':
            if not stack or stack.pop() != value:
                raise MoodleError('The calendar file is incomplete or invalid.')
            if value == 'VEVENT':
                titles.append(summary or '(Untitled event)')
            if not stack:
                closed = True
        elif stack == ['VCALENDAR'] and prop == 'VERSION':
            version = value == '2.0'
        elif stack == ['VCALENDAR', 'VEVENT'] and prop == 'SUMMARY':
            summary = re.sub(r'\\([nN,;\\])', lambda m: '\n' if m[1] in 'nN' else m[1], value)
            summary = ' '.join(summary.split())[:300]
    if stack or not closed or not version:
        raise MoodleError('The calendar file is incomplete or is not iCalendar 2.0.')
    return {'count': len(titles), 'titles': titles[:50]}


def fetch_preview(url):
    url = validate_url(url)
    try:
        # Do not inherit credentials from .netrc or browser sessions. Redirects
        # may lead to SSO; never forward the private export token there.
        with requests.Session() as session:
            session.trust_env = False
            started = time.monotonic()
            with session.get(url, timeout=(5, 10), stream=True, allow_redirects=False,
                             headers={'Accept': 'text/calendar'}) as response:
                if response.status_code in (401, 403) or 300 <= response.status_code < 400:
                    raise MoodleError('This URL requires sign-in or redirects to another page. Use the direct URL from Moodle > Calendar > Export calendar. Your university may restrict calendar exports.')
                if response.status_code != 200:
                    raise MoodleError('Moodle could not provide the calendar. Try again later or generate a fresh export URL.')
                raw = bytearray()
                for chunk in response.iter_content(16384):
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise MoodleError('This calendar is too large. Export a shorter date range in Moodle.')
                    if time.monotonic() - started > 25:
                        raise MoodleError('Moodle is responding too slowly. Please try again.')
                return preview_calendar(raw)
    except requests.RequestException:
        # Requests errors can contain the URL and its private token.
        raise MoodleError('Could not reach Moodle securely. Check your connection and try again.') from None


class MoodleConnection:
    def __init__(self, root=None):
        if root is None:
            from annie.paths import DATA_DIR
            root = DATA_DIR
        self.path = Path(root) / 'moodle-calendar.dpapi'

    def read(self):
        if not self.path.exists():
            return None
        try:
            data = read_secret(self.path)
            validate_url(data['url'])
            preview = data['preview']
            if (not isinstance(preview['titles'], list)
                    or not all(isinstance(title, str) for title in preview['titles'])
                    or not isinstance(preview['count'], int)
                    or preview['count'] < len(preview['titles'])
                    or len(preview['titles']) > 50
                    or dt.datetime.fromisoformat(data['checked_at']).tzinfo is None):
                raise ValueError
            return data
        except Exception:
            raise MoodleError('Could not read the saved Moodle connection. Paste your export URL to reconnect.') from None

    def check(self, url=''):
        if not url.strip():
            saved = self.read()
            if not saved:
                raise MoodleError('Paste your Moodle calendar export URL first.')
            url = saved['url']
        url = validate_url(url)
        preview = fetch_preview(url)
        data = {'url': url, 'preview': preview,
                'checked_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            write_secret(self.path, data)
        except Exception:
            raise MoodleError('The calendar was verified, but could not be saved securely. Please try again.') from None
        return data

    def disconnect(self):
        try:
            delete_secret(self.path)
        except Exception:
            raise MoodleError('Could not remove this laptop\'s saved connection. Please try again.') from None
