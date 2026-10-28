"""Explicitly enabled, authenticated loopback bridge for Campus Radar."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit

from annie.campus_radar import RadarStore
from annie.secure_storage import read_secret, write_secret

PORT = 8768
LIMIT = 1_000_000


def pairing_token(root):
    path = root / 'campus-pairing.dpapi'
    if path.exists():
        token = read_secret(path)['token']
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError('Invalid protected pairing record.')
        return token
    token = secrets.token_urlsafe(32)
    write_secret(path, {'token': token})
    return token


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key.')
        result[key] = value
    return result


def _course_url(value):
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.netloc != 'webwork-new.nu.edu.kz'
            or parts.query or parts.fragment
            or not re.fullmatch(r'/webwork2/[A-Za-z0-9_-]{1,80}/?', parts.path)):
        raise ValueError('Only canonical NU WeBWorK course captures are supported.')
    return parts.path.strip('/').split('/')[1]


def validate_capture(data):
    source = data['source']
    course = _course_url(source['url'])
    if (source['source_id'] != 'ww.' + course or source['kind'] != 'webwork'
            or source['scope'] != 'course'):
        raise ValueError('Unexpected course identity.')
    for item in data['items']:
        parts = urlsplit(item['source_url'])
        if (parts.scheme != 'https' or parts.netloc != 'webwork-new.nu.edu.kz'
                or parts.query or parts.fragment
                or not re.fullmatch(re.escape('/webwork2/' + course + '/') + r'[A-Za-z0-9_-]{1,100}/?', parts.path)):
            raise ValueError('Unexpected assignment URL.')


class CampusReceiver:
    def __init__(self, store, token, on_change=lambda: None, port=PORT):
        self.store, self.token, self.on_change, self.port = store, token, on_change, port
        self.server = None
        self.thread = None

    def start(self):
        if self.server is not None:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5

            def log_message(self, *_):
                pass  # Authorization headers and captured data never enter HTTP logs.

            def valid_origin(self):
                origin = self.headers.get('Origin')
                return origin is None or re.fullmatch(r'chrome-extension://[a-p]{32}', origin) is not None

            def valid_host(self):
                return self.headers.get('Host') == '127.0.0.1:' + str(owner.server.server_port)

            def reply(self, status, data):
                raw = json.dumps(data).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                origin = self.headers.get('Origin')
                if origin and self.valid_origin():
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                self.end_headers()
                self.wfile.write(raw)
                self.close_connection = True

            def do_OPTIONS(self):
                if not self.valid_host() or not self.valid_origin():
                    return self.reply(403, {'error': 'Forbidden'})
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', 'null'))
                self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self):
                if not self.valid_host() or not self.valid_origin():
                    return self.reply(403, {'error': 'Forbidden'})
                self.reply(200 if self.path == '/health' else 404, {'service': 'Campus Radar'})

            def do_POST(self):
                if not self.valid_host() or not self.valid_origin():
                    return self.reply(403, {'error': 'Forbidden'})
                auth = self.headers.get('Authorization', '')
                if not hmac.compare_digest(auth.encode('utf-8'), ('Bearer ' + owner.token).encode('utf-8')):
                    return self.reply(401, {'error': 'Pairing required'})
                if self.path not in ('/capture', '/failure'):
                    return self.reply(404, {'error': 'Not found'})
                try:
                    if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                        raise ValueError('JSON required')
                    length = int(self.headers.get('Content-Length', '-1'))
                    if not 0 < length <= LIMIT:
                        return self.reply(413, {'error': 'Invalid capture size'})
                    data = json.loads(self.rfile.read(length).decode('utf-8'), object_pairs_hook=_unique,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if self.path == '/capture':
                        validate_capture(data)
                        events = owner.store.import_snapshot(data)
                    else:
                        if set(data) != {'source_id', 'reason', 'checked_at'}:
                            raise ValueError('Invalid failure envelope')
                        owner.store.record_failure(**data)
                        events = []
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                    return self.reply(400, {'error': 'Invalid capture; no successful check recorded'})
                except (OSError, sqlite3.Error):
                    return self.reply(503, {'error': 'Local storage unavailable'})
                # Signal only; Qt widgets must be updated by the GUI thread.
                owner.on_change()
                self.reply(200, {'accepted': True, 'changes': len(events)})

        self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='campus-receiver')
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.thread.join(timeout=2)


class NotificationLedger:
    """Delivery attempts are separate from the student's review state."""
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS radar_delivery (event_id TEXT PRIMARY KEY)')

    def deliver(self, send):
        with self.store.connection() as db:
            seen = {row[0] for row in db.execute('SELECT event_id FROM radar_delivery')}
        events = [e for e in self.store.events() if e['id'] not in seen]
        groups = {}
        for event in events:
            groups.setdefault(event['source_id'], []).append(event)
        for group in groups.values():
            changes = [e for e in group if e['type'] != 'first_seen']
            if changes:
                title = f'Campus Radar: {len(changes)} coursework change(s)'
                names = {'discovered': 'Newly observed', 'due_changed': 'Due date changed',
                         'closes_changed': 'Closing time changed', 'status_changed': 'Status changed'}
                body = '\n'.join(names.get(e['type'], 'Changed') + ': ' + e['title'] for e in changes[:3])
            else:
                title = 'Campus Radar: course baseline recorded'
                body = f'{len(group)} assignment(s) first observed. Open Campus Radar to review dates.'
            if send(title, body):
                with self.store.connection() as db:
                    db.executemany('INSERT OR IGNORE INTO radar_delivery VALUES (?)', [(e['id'],) for e in group])
