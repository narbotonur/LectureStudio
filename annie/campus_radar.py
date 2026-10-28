"""Local Campus Radar snapshots and observed changes, with no remote access.

A successful local capture is not proof that a connector saw an entire course.
Sources declare assignment/course scope. Missing observations never close or
delete assignments; unknown dates remain unknown, with the original due text.
"""
from contextlib import contextmanager
import datetime as dt
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


KINDS = ('webwork', 'moodle', 'gmail')
SCOPES = ('assignment', 'course')
STATUSES = ('open', 'closed', 'unknown')
SOURCE_FIELDS = {'source_id', 'kind', 'name', 'url', 'scope'}
ITEM_FIELDS = {'external_id', 'title', 'course', 'due_at', 'raw_due_text', 'source_url', 'status'}
OPTIONAL_ITEM_FIELDS = {'closes_at', 'raw_close_text'}
MAX_ITEMS = 500


def _text(value, maximum, label, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip())):
        raise ValueError('Invalid Radar ' + label + '.')
    return value.strip()


def _source_id(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value) is None:
        raise ValueError('Use a short non-secret Radar source ID.')
    return value


def _raw_text(value, maximum, label):
    _text(value, maximum, label, empty=True)
    return value


def _with_close_defaults(item):
    return {'closes_at': None, 'raw_close_text': '', **item}


def _https_url(value):
    """Normalize a public link; never retain auth query parameters or userinfo."""
    value = _text(value, 2048, 'source URL')
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError('Use a canonical HTTPS source URL without credentials.')
    try:
        parts = urlsplit(value)
        if (parts.scheme.lower() != 'https' or not parts.hostname
                or parts.username is not None or parts.password is not None):
            raise ValueError
        host = parts.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            host = '[' + ipaddress.IPv6Address(host).compressed + ']'
        elif re.fullmatch(r'[a-z0-9.-]+', host) is None:
            raise ValueError
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        netloc = host + (':' + str(port) if port not in (None, 443) else '')
        safe = {}
        for key, item in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=40):
            normalized = re.sub(r'[^a-z0-9]', '', key.casefold())
            if any(secret in normalized for secret in (
                    'key', 'token', 'user', 'pass', 'session', 'sesskey', 'secret',
                    'auth', 'credential', 'signature', 'ticket', 'jwt')) or normalized in ('code', 'sso'):
                raise ValueError('Credential-bearing source links are not stored. Use a clean HTTPS URL.')
            if key.casefold() in ('id', 'course', 'set'):
                canonical_key = key.casefold()
                if (canonical_key in safe or len(item) > 200
                        or re.fullmatch(r'[A-Za-z0-9_.~ -]*', item) is None):
                    raise ValueError('Use a short, unambiguous public source identifier.')
                safe[canonical_key] = item
        return urlunsplit(('https', netloc, parts.path or '/', urlencode(sorted(safe.items())), ''))
    except (UnicodeError, ValueError):
        raise ValueError('Use a clean HTTPS source URL without credentials or authentication parameters.') from None


def _date(value, *, nullable=False, checked=False):
    if value is None:
        if nullable:
            return None
        if checked:
            return dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        parsed = value if checked and isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            _text(value, 50, 'timestamp'))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Radar timestamps require an explicit timezone.') from None


def _source(source_id, kind, name, url, scope):
    if kind not in KINDS or scope not in SCOPES:
        raise ValueError('Choose a supported source kind and an explicit assignment or course scope.')
    return {'source_id': _source_id(source_id), 'kind': kind,
            'name': _text(name, 200, 'source name'), 'url': _https_url(url), 'scope': scope}


def _items(items):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError('Use a list of at most 500 Radar items.')
    normalized, seen = [], set()
    for item in items:
        if (not isinstance(item, dict) or not ITEM_FIELDS.issubset(item)
                or set(item) - ITEM_FIELDS - OPTIONAL_ITEM_FIELDS):
            raise ValueError('Each Radar item requires the declared snapshot fields only.')
        external_id = _text(item['external_id'], 200, 'external item ID')
        if external_id in seen:
            raise ValueError('A source snapshot cannot repeat an external item ID.')
        if item['status'] not in STATUSES:
            raise ValueError('Radar item status must be open, closed or unknown.')
        normalized.append({'external_id': external_id,
            'title': _text(item['title'], 240, 'item title'),
            'course': _text(item['course'], 120, 'course', empty=True),
            'due_at': _date(item['due_at'], nullable=True),
            'raw_due_text': _raw_text(item['raw_due_text'], 1500, 'original due text'),
            'closes_at': _date(item.get('closes_at'), nullable=True),
            'raw_close_text': _raw_text(item.get('raw_close_text', ''), 1500, 'original close text'),
            'source_url': _https_url(item['source_url']), 'status': item['status']})
        seen.add(external_id)
    if len(json.dumps(normalized, ensure_ascii=False).encode('utf-8')) > 1_000_000:
        raise ValueError('Use a Radar snapshot smaller than one megabyte.')
    return normalized


def _safe_error(reason):
    reason = _text(reason, 1200, 'failure reason')
    # A connector error can contain a credential-bearing request URL. Retain a
    # useful failure state without persisting that URL, headers or token value.
    reason = re.sub(r'https?://\S+', '[source URL omitted]', reason)
    reason = re.sub(r'(?i)\b(?:bearer|basic)\s+\S+', '[credential omitted]', reason)
    reason = re.sub(r'''(?ix)["']?\b[\w-]*(?:token|password|passwd|secret|sesskey|api[\s_-]?key|session)[\w-]*
                    ["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|\S+)''', '[credential omitted]', reason)
    reason = re.sub(r'\bLLM_[A-Za-z0-9_]+\b', '[credential omitted]', reason)
    return reason


class RadarStore:
    def __init__(self, root=None):
        if root is None:
            from annie.paths import DATA_DIR
            root = DATA_DIR
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'campus_radar.sqlite3'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS radar_sources (
                    source_id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                    url TEXT NOT NULL, scope TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'unverified',
                    last_success_at TEXT, last_attempt_at TEXT, last_error TEXT,
                    has_baseline INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS radar_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL REFERENCES radar_sources(source_id),
                    checked_at TEXT NOT NULL, complete INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS radar_items (
                    item_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES radar_sources(source_id),
                    external_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    availability TEXT NOT NULL, last_observed_at TEXT NOT NULL,
                    UNIQUE(source_id,external_id));
                CREATE TABLE IF NOT EXISTS radar_item_versions (
                    item_id TEXT NOT NULL REFERENCES radar_items(item_id), revision INTEGER NOT NULL,
                    snapshot_id INTEGER NOT NULL REFERENCES radar_snapshots(snapshot_id),
                    observed_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(item_id,revision));
                CREATE TABLE IF NOT EXISTS radar_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    item_id TEXT NOT NULL REFERENCES radar_items(item_id), payload TEXT NOT NULL,
                    unread INTEGER NOT NULL DEFAULT 1);
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
    def _registered(db, source_id):
        row = db.execute('SELECT * FROM radar_sources WHERE source_id=?', (source_id,)).fetchone()
        if row is None:
            raise ValueError('Register this Radar source before recording a check.')
        return dict(row)

    def _register(self, db, source):
        existing = db.execute('SELECT * FROM radar_sources WHERE source_id=?', (source['source_id'],)).fetchone()
        if existing:
            if any(existing[key] != source[key] for key in ('kind', 'url', 'scope')):
                raise ValueError('Use a new source ID when changing the source URL, kind or scope.')
            db.execute('UPDATE radar_sources SET name=? WHERE source_id=?', (source['name'], source['source_id']))
        else:
            db.execute('INSERT INTO radar_sources(source_id,kind,name,url,scope) VALUES(?,?,?,?,?)',
                       tuple(source[key] for key in ('source_id', 'kind', 'name', 'url', 'scope')))

    def register_source(self, source_id, kind, name, url, scope='assignment'):
        source = _source(source_id, kind, name, url, scope)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._register(db, source)
            return self._public_source(self._registered(db, source_id))

    @staticmethod
    def _public_source(source):
        return {key: value for key, value in source.items() if key != 'has_baseline'}

    def sources(self):
        with self.connection() as db:
            return [self._public_source(dict(row)) for row in db.execute(
                'SELECT * FROM radar_sources ORDER BY source_id')]

    @staticmethod
    def _check_order(source, checked_at):
        if (source['last_attempt_at'] is not None
                and dt.datetime.fromisoformat(checked_at) < dt.datetime.fromisoformat(source['last_attempt_at'])):
            raise ValueError('This capture is older than the last Radar check. Import a newer snapshot.')

    def record_check(self, source_id, items, *, checked_at=None, complete=True):
        source_id = _source_id(source_id)
        normalized = _items(items)
        checked_at = _date(checked_at, checked=True)
        if not isinstance(complete, bool):
            raise ValueError('Radar completeness must be an explicit boolean.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._record_check(db, source_id, normalized, checked_at, complete)

    def import_snapshot(self, snapshot):
        """Validate and atomically register/import a complete capture envelope."""
        if not isinstance(snapshot, dict) or set(snapshot) != {'source', 'checked_at', 'complete', 'items'}:
            raise ValueError('Use the declared Radar snapshot envelope only.')
        if not isinstance(snapshot['source'], dict) or set(snapshot['source']) != SOURCE_FIELDS:
            raise ValueError('The Radar snapshot must declare its complete source and scope.')
        source = _source(**snapshot['source'])
        normalized = _items(snapshot['items'])
        if snapshot['checked_at'] is None:
            raise ValueError('An imported capture requires its actual timezone-aware check time.')
        checked_at = _date(snapshot['checked_at'], checked=True)
        if not isinstance(snapshot['complete'], bool):
            raise ValueError('Radar completeness must be an explicit boolean.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._register(db, source)
            return self._record_check(db, source['source_id'], normalized, checked_at, snapshot['complete'])

    def _record_check(self, db, source_id, items, checked_at, complete):
        source = self._registered(db, source_id)
        self._check_order(source, checked_at)
        snapshot_id = db.execute('INSERT INTO radar_snapshots(source_id,checked_at,complete,payload) '
            'VALUES(?,?,?,?)', (source_id, checked_at, int(complete), json.dumps(items, ensure_ascii=False))).lastrowid
        current = {row['external_id']: dict(row) for row in db.execute(
            'SELECT * FROM radar_items WHERE source_id=?', (source_id,))}
        observed, created = set(), []
        for item in items:
            external_id = item['external_id']
            observed.add(external_id)
            old = current.get(external_id)
            old_item = _with_close_defaults(json.loads(old['payload'])) if old else None
            identity = old['item_id'] if old else hashlib.sha256(
                json.dumps([source_id, external_id]).encode('utf-8')).hexdigest()
            changed = old is None or old_item != item
            revision = (old['revision'] + 1 if old else 1) if changed else old['revision']
            if changed:
                db.execute('INSERT INTO radar_items VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id) '
                    'DO UPDATE SET revision=excluded.revision,payload=excluded.payload,'
                    'availability=excluded.availability,last_observed_at=excluded.last_observed_at',
                    (identity, source_id, external_id, revision, json.dumps(item, ensure_ascii=False),
                     'observed', checked_at))
                db.execute('INSERT INTO radar_item_versions VALUES(?,?,?,?,?)',
                    (identity, revision, snapshot_id, checked_at, json.dumps(item, ensure_ascii=False)))
            else:
                db.execute("UPDATE radar_items SET availability='observed',last_observed_at=? WHERE item_id=?",
                           (checked_at, identity))
            types = []
            if old is None:
                types.append('discovered' if source['has_baseline'] else 'first_seen')
            else:
                if (old_item['due_at'], old_item['raw_due_text']) != (item['due_at'], item['raw_due_text']):
                    types.append('due_changed')
                if (old_item['closes_at'], old_item['raw_close_text']) != (item['closes_at'], item['raw_close_text']):
                    types.append('closes_changed')
                if old_item['status'] != item['status']:
                    types.append('status_changed')
            for kind in types:
                event_id = hashlib.sha256(json.dumps([identity, revision, kind]).encode('utf-8')).hexdigest()
                evidence = ('Initial observation; original creation time is unknown.' if kind == 'first_seen' else
                    'First observation after a complete baseline; original creation time is unknown.' if kind == 'discovered' else
                    'Previous observed due field: ' + old_item['raw_due_text'] + '\nCurrent observed due field: '
                    + item['raw_due_text'] if kind == 'due_changed' else
                    'Previous observed close field: ' + old_item['raw_close_text'] + '\nCurrent observed close field: '
                    + item['raw_close_text'] if kind == 'closes_changed' else
                    'Observed status changed from ' + old_item['status'] + ' to ' + item['status'] + '.')
                event = {'id': event_id, 'type': kind, 'source_id': source_id,
                    'external_id': external_id, 'item_id': identity, 'revision': revision,
                    'title': item['title'], 'course': item['course'], 'source_url': item['source_url'],
                    'old_due_at': old_item['due_at'] if old_item else None, 'new_due_at': item['due_at'],
                    'old_raw_due_text': old_item['raw_due_text'] if old_item else None,
                    'new_raw_due_text': item['raw_due_text'],
                    'old_closes_at': old_item['closes_at'] if old_item else None,
                    'new_closes_at': item['closes_at'],
                    'old_raw_close_text': old_item['raw_close_text'] if old_item else None,
                    'new_raw_close_text': item['raw_close_text'],
                    'old_status': old_item['status'] if old_item else None, 'new_status': item['status'],
                    'evidence': evidence, 'observed_at': checked_at, 'unread': True}
                db.execute('INSERT INTO radar_events(id,item_id,payload) VALUES(?,?,?)',
                           (event_id, identity, json.dumps(event, ensure_ascii=False)))
                created.append(event)
        missing = set(current) - observed
        for external_id in missing:
            db.execute("UPDATE radar_items SET availability='unknown' WHERE item_id=?", (current[external_id]['item_id'],))
        success = complete and not missing
        db.execute('UPDATE radar_sources SET state=?,last_attempt_at=?,last_success_at=?,'
                   'last_error=NULL,has_baseline=? WHERE source_id=?',
                   ('success' if success else 'partial', checked_at,
                    checked_at if success else source['last_success_at'],
                    int(bool(source['has_baseline'] or complete)), source_id))
        return created

    def record_failure(self, source_id, reason, *, checked_at=None):
        source_id = _source_id(source_id)
        checked_at, reason = _date(checked_at, checked=True), _safe_error(reason)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            source = self._registered(db, source_id)
            self._check_order(source, checked_at)
            db.execute("UPDATE radar_sources SET state='error',last_attempt_at=?,last_error=? WHERE source_id=?",
                       (checked_at, reason, source_id))
            db.execute("UPDATE radar_items SET availability='unknown' WHERE source_id=?", (source_id,))

    def items(self, source_id=None):
        with self.connection() as db:
            if source_id is not None:
                source_id = _source_id(source_id)
                self._registered(db, source_id)
            rows = db.execute('SELECT * FROM radar_items' + (' WHERE source_id=?' if source_id else '')
                              + ' ORDER BY source_id,external_id', (source_id,) if source_id else ())
            result = []
            for row in rows:
                item = _with_close_defaults(json.loads(row['payload']))
                item.update({key: row[key] for key in ('item_id', 'source_id', 'revision', 'availability', 'last_observed_at')})
                item['due_versions'] = []
                item['closes_versions'] = []
                for version in db.execute('SELECT * FROM radar_item_versions WHERE item_id=? ORDER BY revision',
                                          (row['item_id'],)):
                    prior = _with_close_defaults(json.loads(version['payload']))
                    item['due_versions'].append({'revision': version['revision'], 'observed_at': version['observed_at'],
                        'due_at': prior['due_at'], 'raw_due_text': prior['raw_due_text'],
                        'closes_at': prior['closes_at'], 'raw_close_text': prior['raw_close_text']})
                    item['closes_versions'].append({'revision': version['revision'], 'observed_at': version['observed_at'],
                        'closes_at': prior['closes_at'], 'raw_close_text': prior['raw_close_text']})
                result.append(item)
            return result

    def events(self, unread_only=False):
        if not isinstance(unread_only, bool):
            raise ValueError('The unread filter must be a boolean.')
        with self.connection() as db:
            rows = db.execute('SELECT * FROM radar_events' + (' WHERE unread=1' if unread_only else '')
                              + ' ORDER BY sequence DESC')
            return [{**json.loads(row['payload']), 'unread': bool(row['unread'])} for row in rows]

    def mark_read(self, event_id):
        event_id = _text(event_id, 128, 'event identity')
        with self.connection() as db:
            if not db.execute('UPDATE radar_events SET unread=0 WHERE id=?', (event_id,)).rowcount:
                raise ValueError('This Radar event was not found.')

    def coverage(self):
        # One read transaction keeps source health and availability counts from
        # different checks from being combined during a concurrent capture.
        with self.connection() as db:
            db.execute('BEGIN')
            sources = [self._public_source(dict(row)) for row in db.execute(
                'SELECT * FROM radar_sources ORDER BY source_id')]
            items = [dict(row) for row in db.execute('SELECT source_id,availability FROM radar_items')]
            unread_count = db.execute('SELECT COUNT(*) FROM radar_events WHERE unread=1').fetchone()[0]
        result = {'sources': [], 'source_count': len(sources), 'success_count': 0,
            'partial_count': 0, 'error_count': 0, 'unverified_count': 0,
            'unread_count': unread_count, 'assignment_source_count': 0,
            'full_course_source_count': 0, 'has_unknown_items': False,
            'coverage_basis': 'local_snapshots_only', 'full_course_coverage_verified': False}
        for source in sources:
            known = [item for item in items if item['source_id'] == source['source_id']]
            unknown = sum(item['availability'] == 'unknown' for item in known)
            entry = {**source, 'observed_count': len(known) - unknown, 'unknown_count': unknown,
                     'note': ('Assignment scope only; other course work is not covered.' if source['scope'] == 'assignment'
                              else 'Declared course scope; completeness is based on the imported capture, not independently verified access.')}
            result['sources'].append(entry)
            result[source['state'] + '_count'] += 1
            result['assignment_source_count'] += source['scope'] == 'assignment'
            result['full_course_source_count'] += source['scope'] == 'course' and source['state'] == 'success'
            result['has_unknown_items'] |= bool(unknown)
        return result
