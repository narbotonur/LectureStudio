"""Versioned, human-approved obligations with a recoverable Inbox projection.

SQLite owns confirmed versions and an outbox. The existing JSON deadline Inbox is
an idempotent projection. They are deliberately not described as one transaction.
Transcript grounding is checked by the caller; this store validates the bounded
payload and preserves evidence rather than asserting semantic truth.
"""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from annie.deadlines import DeadlineStore, TZ

RELATIONS = ('new', 'unchanged', 'explicit_correction', 'unresolved_conflict')
STATUSES = ('pending', 'approved', 'rejected', 'stale')


def _assignment_name(value):
    """Match formatting variants without prefix-matching numbered assignments."""
    value = re.sub(r'(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])', ' ', value.casefold())
    return ' '.join(re.findall(r'[^\W_]+', value))


def _text(value, maximum, name, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f'Invalid {name}.')
    return ' '.join(value.split())


def _date(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        if not isinstance(value, str) or len(value) > 50:
            raise ValueError
        parsed = dt.datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(TZ).isoformat(timespec='minutes')
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Use a date and time with timezone.') from None


def _references(evidence, *, required=True):
    if not isinstance(evidence, list) or not (1 if required else 0) <= len(evidence) <= 8:
        raise ValueError('Provide one to eight evidence quotes.')
    cleaned = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError('Invalid evidence reference.')
        start, end = item.get('start'), item.get('end')
        try:
            valid = all(not isinstance(v, bool) and isinstance(v, (int, float))
                        and math.isfinite(v) for v in (start, end))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError('Evidence timestamps must be finite numbers.')
        if start < 0 or end <= start or end - start > 180:
            raise ValueError('Invalid evidence interval.')
        quote = _text(item.get('quote'), 1500, 'evidence quote')
        if len(quote) < 8:
            raise ValueError('Evidence quote is too short.')
        cleaned.append({'quote': quote, 'start': float(start), 'end': float(end),
                        'source': _text(item.get('source'), 200, 'evidence source')})
    return cleaned


def _validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('A deadline proposal is required.')
    relation = payload.get('relation')
    if relation not in RELATIONS:
        raise ValueError('Unknown deadline relationship.')
    revision = payload.get('expected_revision', 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError('A nonnegative assignment revision is required.')
    identity = payload.get('assignment_id')
    if identity is not None:
        identity = _text(identity, 128, 'assignment identity')
        if not revision:
            raise ValueError('An existing assignment requires its current revision.')
    elif revision:
        raise ValueError('A new assignment starts at revision zero.')
    if relation == 'unchanged' and identity is None:
        raise ValueError('An unchanged proposal requires an existing assignment.')
    cleaned = _references(payload.get('evidence'))
    return {'course': _text(payload.get('course', ''), 100, 'course', empty=True),
            'title': _text(payload.get('title'), 160, 'assignment title'),
            'assignment_id': identity, 'expected_revision': revision,
            'relation': relation,
            'proposed_due_at': _date(payload.get('proposed_due_at'), optional=True),
            'previous_due_at': _date(payload.get('previous_due_at'), optional=True),
            'reason': _text(payload.get('reason'), 1500, 'proposal reason'),
            'fingerprint': _text(payload.get('fingerprint'), 128, 'transcript fingerprint'),
            'source_name': _text(payload.get('source_name', cleaned[0]['source']), 200, 'source name'),
            'evidence': cleaned,
            'previous_evidence': _references(payload.get('previous_evidence', []), required=False)}


class ObligationStore:
    def __init__(self, root=None):
        if root is None:
            from annie.paths import DATA_DIR
            root = DATA_DIR
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'obligations.sqlite3'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY, course TEXT NOT NULL,
                    title TEXT NOT NULL, due_at TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL,
                    approved_at REAL, applied_assignment_id TEXT, applied_revision INTEGER,
                    confirmed_due_at TEXT);
                CREATE TABLE IF NOT EXISTS obligation_versions (
                    assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
                    revision INTEGER NOT NULL, course TEXT NOT NULL, title TEXT NOT NULL,
                    due_at TEXT NOT NULL, proposal_id TEXT NOT NULL REFERENCES proposals(id),
                    previous_revision INTEGER, approved_at REAL NOT NULL,
                    PRIMARY KEY(assignment_id,revision));
                CREATE TABLE IF NOT EXISTS obligation_outbox (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0);
            ''')
        self.drain_outbox()

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

    def _proposal(self, row, db):
        item = dict(row)
        result = json.loads(item.pop('payload'))
        result.update(item)
        if item['applied_assignment_id']:
            result['assignment_id'] = item['applied_assignment_id']
        result['delivery_pending'] = bool(db.execute(
            'SELECT 1 FROM obligation_outbox o JOIN proposals p ON p.id=o.operation_id '
            'WHERE p.applied_assignment_id=? AND o.delivered=0',
            (result['assignment_id'],)).fetchone())
        return result

    def list_current(self, course=None):
        with self.connection() as db:
            if course is None:
                rows = db.execute('SELECT * FROM assignments ORDER BY course,title,assignment_id')
            else:
                wanted = _text(course, 100, 'course', empty=True).casefold()
                rows = [row for row in db.execute('SELECT * FROM assignments ORDER BY title,assignment_id')
                        if row['course'].casefold() == wanted]
            result = []
            for row in rows:
                item = dict(row)
                payload_row = db.execute('SELECT p.payload FROM obligation_versions v JOIN proposals p '
                                         'ON p.id=v.proposal_id WHERE v.assignment_id=? AND v.revision=?',
                                         (item['assignment_id'], item['revision'])).fetchone()
                if payload_row:
                    payload = json.loads(payload_row['payload'])
                    item.update({key: payload.get(key) for key in ('evidence', 'reason', 'fingerprint')})
                result.append(item)
            return result

    def propose(self, payload):
        payload = _validate(payload)
        # Reasons may vary on another inference, but the same fact in the same
        # snapshot is one immutable proposal. Never silently rewrite old evidence.
        key = [payload['course'].casefold(), _assignment_name(payload['title'])] + [payload[k] for k in (
            'fingerprint', 'assignment_id', 'expected_revision', 'proposed_due_at')]
        identity = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode('utf-8')).hexdigest()
        with self.connection() as db:
            if payload['assignment_id']:
                assignment = db.execute('SELECT * FROM assignments WHERE assignment_id=?',
                                        (payload['assignment_id'],)).fetchone()
                if assignment is None or assignment['course'].casefold() != payload['course'].casefold():
                    raise ValueError('Choose an existing assignment in this course.')
                if _assignment_name(assignment['title']) != _assignment_name(payload['title']):
                    raise ValueError('The proposed title does not match the selected assignment.')
                prior = db.execute('SELECT p.payload FROM obligation_versions v JOIN proposals p '
                                   'ON p.id=v.proposal_id WHERE v.assignment_id=? AND v.revision=?',
                                   (payload['assignment_id'], payload['expected_revision'])).fetchone()
                if prior is None:
                    raise ValueError('The proposed assignment revision was not found.')
                # Previously approved evidence comes from our immutable history,
                # not from a model or a caller's reconstruction of the old quote.
                payload['previous_evidence'] = json.loads(prior['payload'])['evidence']
            db.execute('INSERT OR IGNORE INTO proposals(id,payload,created) VALUES(?,?,?)',
                       (identity, json.dumps(payload, ensure_ascii=False), time.time()))
            return self._proposal(db.execute('SELECT * FROM proposals WHERE id=?', (identity,)).fetchone(), db)

    def list_proposals(self, status=None):
        if status is not None and status not in STATUSES:
            raise ValueError('Unknown proposal status.')
        with self.connection() as db:
            rows = db.execute('SELECT * FROM proposals' + (' WHERE status=?' if status else '')
                              + ' ORDER BY created DESC,id', (status,) if status else ())
            return [self._proposal(row, db) for row in rows]

    def get_proposal(self, identity):
        with self.connection() as db:
            row = db.execute('SELECT * FROM proposals WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise ValueError('This proposal was not found.')
            return self._proposal(row, db)

    def approve(self, identity, *, due_at=None, expected_fingerprint=None):
        stale = False
        stale_message = 'This assignment changed. Review a new proposal before replacing its deadline.'
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM proposals WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise ValueError('This proposal was not found.')
            payload = _validate(json.loads(row['payload']))
            if expected_fingerprint is not None and payload['fingerprint'] != expected_fingerprint:
                raise ValueError('The transcript changed. Review the current evidence first.')
            if row['status'] in ('rejected', 'stale'):
                raise ValueError('This proposal is no longer pending. Analyze the lecture again.')
            if row['status'] == 'approved':
                # No second version or operation: recovery below can still finish
                # a projection interrupted after its SQLite commit.
                pass
            else:
                confirmed = _date(due_at) if due_at is not None else payload['proposed_due_at']
                if not confirmed or (payload['relation'] == 'unresolved_conflict' and due_at is None):
                    raise ValueError('Choose and confirm a deadline date and time first.')
                assignment_id = payload['assignment_id']
                current = (db.execute('SELECT * FROM assignments WHERE assignment_id=?',
                                      (assignment_id,)).fetchone() if assignment_id else None)
                collision = (not assignment_id and any(
                    candidate['course'].casefold() == payload['course'].casefold()
                    and _assignment_name(candidate['title']) == _assignment_name(payload['title'])
                    for candidate in db.execute('SELECT course,title FROM assignments')))
                legacy_collision = False
                if not assignment_id and not collision:
                    for legacy in DeadlineStore(self.root).load():
                        if legacy.get('origin_assignment_id'):
                            continue
                        legacy_course, legacy_title = legacy.get('course', ''), legacy.get('title', '')
                        if not isinstance(legacy_course, str) or not isinstance(legacy_title, str):
                            raise ValueError('The legacy Inbox has unreadable assignment fields. Review it before approving.')
                        if (legacy_course.casefold() == payload['course'].casefold()
                                and _assignment_name(legacy_title) == _assignment_name(payload['title'])):
                            legacy_collision = True
                            break
                if collision:
                    db.execute("UPDATE proposals SET status='stale' WHERE id=?", (identity,))
                    stale = True
                    stale_message = ('An assignment with this title already exists in this course. '
                                     'Analyze again and link the existing assignment, or use a distinct title.')
                elif legacy_collision:
                    db.execute("UPDATE proposals SET status='stale' WHERE id=?", (identity,))
                    stale = True
                    stale_message = ('A legacy Inbox item already exists for this assignment and is preserved. '
                                     'Linking or migration is required before a versioned deadline change.')
                elif assignment_id and (current is None
                        or current['revision'] != payload['expected_revision']
                        or current['course'].casefold() != payload['course'].casefold()
                        or _assignment_name(current['title']) != _assignment_name(payload['title'])
                        or (payload['previous_due_at'] is not None
                            and current['due_at'] != payload['previous_due_at'])):
                    db.execute("UPDATE proposals SET status='stale' WHERE id=?", (identity,))
                    stale = True
                else:
                    now = time.time()
                    if current and current['due_at'] == confirmed:
                        # Already current: approval is recorded but not a new
                        # historical change, even if a model called it correction.
                        db.execute("UPDATE proposals SET status='approved',approved_at=?,"
                                   'applied_assignment_id=?,applied_revision=?,confirmed_due_at=? WHERE id=?',
                                   (now, assignment_id, current['revision'], confirmed, identity))
                    else:
                        assignment_id = assignment_id or uuid.uuid4().hex
                        revision = current['revision'] + 1 if current else 1
                        db.execute('INSERT INTO assignments(assignment_id,course,title,due_at,revision) '
                                   'VALUES(?,?,?,?,?) ON CONFLICT(assignment_id) DO UPDATE SET '
                                   'title=excluded.title,due_at=excluded.due_at,revision=excluded.revision',
                                   (assignment_id, payload['course'], payload['title'], confirmed, revision))
                        db.execute('INSERT INTO obligation_versions VALUES(?,?,?,?,?,?,?,?)',
                                   (assignment_id, revision, payload['course'], payload['title'], confirmed,
                                    identity, current['revision'] if current else None, now))
                        event = {'origin_assignment_id': assignment_id, 'revision': revision,
                                 'course': payload['course'], 'title': payload['title'], 'due_at': confirmed,
                                 'evidence': '\n'.join(item['quote'] for item in payload['evidence']),
                                 'source_name': payload['source_name']}
                        db.execute('INSERT INTO obligation_outbox(operation_id,payload) VALUES(?,?)',
                                   (identity, json.dumps(event, ensure_ascii=False)))
                        db.execute("UPDATE proposals SET status='approved',approved_at=?,"
                                   'applied_assignment_id=?,applied_revision=?,confirmed_due_at=? WHERE id=?',
                                   (now, assignment_id, revision, confirmed, identity))
        if stale:
            raise ValueError(stale_message)
        self.drain_outbox()
        return self.get_proposal(identity)

    def reject(self, identity):
        with self.connection() as db:
            if not db.execute("UPDATE proposals SET status='rejected' WHERE id=? AND status='pending'",
                              (identity,)).rowcount:
                raise ValueError('Only pending proposals can be rejected.')
        return self.get_proposal(identity)

    def history(self, assignment_id):
        with self.connection() as db:
            rows = db.execute('SELECT v.*,p.payload FROM obligation_versions v JOIN proposals p '
                              'ON p.id=v.proposal_id WHERE v.assignment_id=? ORDER BY v.revision',
                              (assignment_id,))
            result = []
            for row in rows:
                item = dict(row)
                item['evidence'] = json.loads(item.pop('payload'))['evidence']
                result.append(item)
            return result

    def drain_outbox(self):
        delivered = 0
        # Competing drainers may read the same operation. Inbox revision checks
        # make repetition safe, and a crash before marking delivery is recoverable.
        with self.connection() as db:
            pending = [dict(row) for row in db.execute(
                'SELECT * FROM obligation_outbox WHERE delivered=0 ORDER BY sequence')]
        for event in pending:
            try:
                DeadlineStore(self.root).upsert_origin(**json.loads(event['payload']))
                self._mark_delivered(event['operation_id'])
                delivered += 1
            except (OSError, ValueError, sqlite3.Error):
                # The authoritative version is confirmed; leave the durable event
                # pending rather than reporting an unsaved deadline or losing it.
                break
        return delivered

    def _mark_delivered(self, operation_id):
        with self.connection() as db:
            db.execute('UPDATE obligation_outbox SET delivered=1 WHERE operation_id=?', (operation_id,))
