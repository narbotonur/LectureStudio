"""Durable study subjects, session timestamps and active-time accounting."""
from contextlib import contextmanager
import datetime as dt
from pathlib import Path
import sqlite3
import time
import uuid

from annie.config import DATA_DIR

STUDY_DB_PATH = Path(DATA_DIR) / 'study_sessions.sqlite3'
TZ = dt.timezone(dt.timedelta(hours=5))


def duration_text(seconds, clock=False):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}' if clock else f'{hours}h {minutes:02}m'


class StudyStore:
    def __init__(self, path=None):
        self.path = Path(path or STUDY_DB_PATH)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS subjects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE, last_used REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(id),
                    started REAL NOT NULL, ended REAL, state TEXT NOT NULL,
                    sync_state TEXT NOT NULL DEFAULT 'local', sync_error TEXT NOT NULL DEFAULT '');
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_study_session
                    ON sessions((1)) WHERE ended IS NULL;
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    started REAL NOT NULL, ended REAL);
                CREATE INDEX IF NOT EXISTS segment_session ON segments(session_id);
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

    def subjects(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM subjects ORDER BY last_used DESC, name')]

    def add_subject(self, name, now=None):
        name = ' '.join(name.split())
        if not name or len(name) > 100:
            raise ValueError('Enter a subject name between 1 and 100 characters.')
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO subjects VALUES (?, ?, ?, ?)',
                       (uuid.uuid4().hex, name, name.casefold(), now))
            return dict(db.execute('SELECT * FROM subjects WHERE name_key=?', (name.casefold(),)).fetchone())

    @staticmethod
    def _row(db, session_id=None):
        query = '''SELECT sessions.*, subjects.name AS subject FROM sessions
                   JOIN subjects ON subjects.id=sessions.subject_id'''
        row = db.execute(query + (' WHERE sessions.id=?' if session_id else ' WHERE ended IS NULL'),
                         (session_id,) if session_id else ()).fetchone()
        return dict(row) if row else None

    def active(self):
        with self.connection() as db:
            return self._row(db)

    def start(self, subject_id, sync=False, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._row(db):
                raise ValueError('End the current session before starting another one.')
            if not db.execute('SELECT 1 FROM subjects WHERE id=?', (subject_id,)).fetchone():
                raise ValueError('Choose a saved subject first.')
            session_id = uuid.uuid4().hex
            db.execute('INSERT INTO sessions(id,subject_id,started,state,sync_state) VALUES (?,?,?,?,?)',
                       (session_id, subject_id, now, 'running', 'pending' if sync else 'local'))
            db.execute('INSERT INTO segments(session_id,started) VALUES (?,?)', (session_id, now))
            db.execute('UPDATE subjects SET last_used=? WHERE id=?', (now, subject_id))
            return self._row(db, session_id)

    def transition(self, session_id, action, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            session = self._row(db, session_id)
            if not session:
                raise ValueError('Study session was not found.')
            if session['ended'] is not None:
                return session  # Repeated End clicks never create another entry.
            if action not in ('pause', 'resume', 'end'):
                raise ValueError('Unknown study timer action.')
            latest = db.execute('SELECT MAX(COALESCE(ended,started)) FROM segments WHERE session_id=?',
                                (session_id,)).fetchone()[0]
            if now < latest:
                raise ValueError('The system clock moved backwards. Correct the clock and try again.')
            if action == 'resume' and session['state'] == 'paused':
                db.execute('INSERT INTO segments(session_id,started) VALUES (?,?)', (session_id, now))
                db.execute("UPDATE sessions SET state='running' WHERE id=?", (session_id,))
            elif action in ('pause', 'end'):
                db.execute('UPDATE segments SET ended=? WHERE session_id=? AND ended IS NULL', (now, session_id))
                db.execute('UPDATE sessions SET state=?, ended=? WHERE id=?',
                           ('finished' if action == 'end' else 'paused', now if action == 'end' else None, session_id))
            return self._row(db, session_id)

    def elapsed(self, session_id, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            return db.execute('SELECT COALESCE(SUM(MAX(0,COALESCE(ended,?)-started)),0) FROM segments WHERE session_id=?',
                              (now, session_id)).fetchone()[0]

    def totals(self, start=0, end=None):
        end = time.time() if end is None else end
        with self.connection() as db:
            return db.execute('''SELECT COALESCE(SUM(MAX(0,MIN(COALESCE(ended,?),?)-MAX(started,?))),0)
                                 FROM segments WHERE started<? AND COALESCE(ended,?)>?''',
                              (end, end, start, end, end, start)).fetchone()[0]

    def history(self, limit=100):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''
                SELECT s.*, subjects.name AS subject,
                COALESCE((SELECT SUM(MAX(0,segments.ended-segments.started)) FROM segments
                          WHERE segments.session_id=s.id),0) AS seconds
                FROM sessions s JOIN subjects ON subjects.id=s.subject_id
                WHERE s.ended IS NOT NULL ORDER BY s.started DESC LIMIT ?''', (limit,))]

    def calendar_events(self, start_date, end_date):
        start = dt.datetime.combine(start_date, dt.time(), TZ).timestamp()
        end = dt.datetime.combine(end_date, dt.time(), TZ).timestamp()
        with self.connection() as db:
            rows = db.execute('''SELECT s.*, subjects.name AS subject,
                COALESCE((SELECT SUM(MAX(0,segments.ended-segments.started)) FROM segments
                          WHERE segments.session_id=s.id),0) AS seconds FROM sessions s
                JOIN subjects ON subjects.id=s.subject_id
                WHERE s.ended IS NOT NULL AND s.started<? AND s.ended>? ORDER BY s.started''', (end, start)).fetchall()
            return [self.event_body(dict(row)) for row in rows]

    def event_body(self, session):
        seconds = session['seconds'] if 'seconds' in session else self.elapsed(session['id'])
        return {
            'id': 'annie' + session['id'],
            'summary': 'Study · ' + session['subject'],
            'description': f"Active study time: {duration_text(seconds)}\nBreaks excluded from study totals. Calendar block shows start to end.\nTracked in Annie Lecture Studio.",
            'start': {'dateTime': dt.datetime.fromtimestamp(session['started'], TZ).isoformat()},
            'end': {'dateTime': dt.datetime.fromtimestamp(session['ended'], TZ).isoformat()},
            'extendedProperties': {'private': {'annieStudySession': session['id']}},
            'reminders': {'useDefault': False},
        }

    def pending_sync(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''SELECT s.*, subjects.name AS subject FROM sessions s
                JOIN subjects ON subjects.id=s.subject_id
                WHERE s.ended IS NOT NULL AND s.sync_state='pending' ORDER BY s.started LIMIT 50''')]

    def mark_sync(self, session_id, error=''):
        with self.connection() as db:
            db.execute('UPDATE sessions SET sync_state=?, sync_error=? WHERE id=?',
                       ('pending' if error else 'synced', error, session_id))
