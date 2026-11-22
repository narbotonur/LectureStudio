"""Versioned local lecture documents and backward-compatible transcript archives."""
from contextlib import closing
from dataclasses import asdict, is_dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from annie.lecture_actions import _seconds
from annie.secure_storage import atomic_write
from annie.transcription import TranscriptSegment

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
LECTURE_ID = re.compile(r'[a-f0-9]{24,32}')


def lecture_identity(source_name):
    return hashlib.sha256(source_name.encode('utf-8')).hexdigest()[:24]


def archive_path(root, identity):
    if not isinstance(identity, str) or not LECTURE_ID.fullmatch(identity):
        raise ValueError('Invalid lecture ID.')
    return Path(root) / 'transcripts' / f'lecture-{identity}.json'


def archive_segments(segments):
    result = []
    seen = set()
    for item in segments:
        row = asdict(item) if is_dataclass(item) else dict(item)
        if row.get('final', True) is False:
            continue
        start, end = _seconds(row['start']), _seconds(row['end'])
        if end <= start or not isinstance(row['text'], str) or not row['text'].strip():
            raise ValueError('Invalid transcript segment.')
        segment = TranscriptSegment.create(start, end, row['text'],
                                          row.get('source') or 'Lecture transcript',
                                          row.get('backend', 'local'), row.get('speaker', ''))
        identity = row.get('id') or segment.id
        if not isinstance(identity, str):
            raise ValueError('Invalid transcript segment ID.')
        base = identity
        serial = 2
        while identity in seen:
            identity = f'{base}-{serial}'
            serial += 1
        seen.add(identity)
        result.append({**row, **segment.to_dict(), 'id': identity,
                       'start': start, 'end': end, 'text': row['text']})
    return sorted(result, key=lambda row: (row['start'], row['end']))


def save_lecture(root, document):
    path = archive_path(root, document['id'])
    payload = {**document, 'version': 2, 'segments': archive_segments(document['segments'])}
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError('The lecture exceeds the local archive size limit.')
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, data)
    return path


def save_transcript(root, segments, source_name, course='', complete=True, lecture_date=None):
    identity = lecture_identity(source_name)
    return save_lecture(root, {'id': identity, 'source_name': source_name, 'course': course,
                               'complete': bool(complete), 'lecture_date': lecture_date.isoformat() if lecture_date else None,
                               'segments': segments})


def _validate_document(payload):
    for key in ('title', 'course', 'audio_path', 'notes', 'scratchpad', 'cards', 'chat_context'):
        if not isinstance(payload.get(key, ''), str):
            raise ValueError
    for key in ('tags',):
        if not isinstance(payload.get(key, []), list) or any(not isinstance(item, str) for item in payload.get(key, [])):
            raise ValueError
    names = payload.get('speaker_names', {})
    if not isinstance(names, dict) or any(not isinstance(name, str) for name in names.values()):
        raise ValueError
    bookmarks = payload.get('bookmarks', [])
    if not isinstance(bookmarks, list):
        raise ValueError
    for mark in bookmarks:
        if not isinstance(mark, dict) or not isinstance(mark.get('title'), str) or not mark['title'].strip():
            raise ValueError
        _seconds(mark.get('start'))
    for key in ('segments', 'source_segments'):
        rows = payload.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        for row in rows:
            if any(not isinstance(row.get(field, ''), str) for field in ('edited_text', 'speaker', 'source', 'backend')):
                raise ValueError
            words = row.get('words', [])
            if not isinstance(words, list) or any(not isinstance(word, dict) or any(field not in word for field in
                    ('start', 'end', 'text')) or not isinstance(word['text'], str) for word in words):
                raise ValueError
    history = payload.get('revisions', [])
    if not isinstance(history, list):
        raise ValueError
    for revision in history:
        if not isinstance(revision, dict) or not isinstance(revision.get('saved_at'), str):
            raise ValueError
        _validate_document({field: revision[field] for field in ('segments', 'speaker_names', 'notes', 'scratchpad', 'cards')
                            if field in revision})
    past = payload.get('past_chats', [])
    if not isinstance(past, list) or any(not isinstance(item, dict) or not isinstance(item.get('context'), str)
                                        or not isinstance(item.get('chat'), list) or not item['chat'] for item in past):
        raise ValueError
    chat = payload.get('chat', [])
    if not isinstance(chat, list):
        raise ValueError
    for session in (chat, *(item['chat'] for item in past)):
        for row in session:
            if not isinstance(row, dict) or row.get('role') not in ('user', 'assistant') or not isinstance(row.get('text'), str):
                raise ValueError


def load_transcript(path):
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('This lecture exceeds the local archive size limit.')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('version') not in (1, 2):
            raise ValueError
        if not isinstance(payload.get('source_name'), str) or not isinstance(payload.get('course', ''), str):
            raise ValueError
        if payload.get('lecture_date'):
            date.fromisoformat(payload['lecture_date'])
        _validate_document(payload)
        identity = payload.get('id') or path.stem.removeprefix('lecture-')
        if not isinstance(identity, str) or not LECTURE_ID.fullmatch(identity):
            identity = lecture_identity(payload['source_name'])
        if 'source_segments' in payload:
            payload['source_segments'] = archive_segments(payload['source_segments'])
        for revision in payload.get('revisions', ()):
            if 'segments' in revision:
                revision['segments'] = archive_segments(revision['segments'])
        return {**payload, 'id': identity, 'segments': archive_segments(payload['segments'])}
    except (ValueError, KeyError, TypeError, OverflowError):
        raise ValueError('Choose a valid Lecture Studio transcript archive.') from None


def library_entries(root):
    for path in (Path(root) / 'transcripts').glob('lecture-*.json'):
        try:
            yield path, load_transcript(path)
        except (OSError, ValueError):
            continue


def search_library(entries, query):
    """Return one matching source per lecture. Rebuild from durable files on open."""
    terms = re.findall(r'[^\W_]+', query, re.UNICODE)
    if not terms:
        return [(path, document, None) for path, document in entries]
    entries = list(entries)
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE VIRTUAL TABLE content USING fts5(body, lecture UNINDEXED, segment UNINDEXED)')
            for offset, (_, document) in enumerate(entries):
                common = ' '.join(str(document.get(key, '')) for key in (
                    'title', 'source_name', 'course', 'lecture_date', 'tags'))
                db.execute('INSERT INTO content VALUES (?,?,?)', (
                    ' '.join((common, document.get('notes', ''), document.get('scratchpad', ''), document.get('cards', ''))),
                    offset, -1))
                db.executemany('INSERT INTO content VALUES (?,?,?)', (
                    (common + ' ' + row.get('edited_text', row['text']), offset, position)
                    for position, row in enumerate(document['segments'])))
            query_text = ' AND '.join(f'"{term}"*' for term in terms)
            hits = list(db.execute('SELECT lecture,segment FROM content WHERE content MATCH ? '
                                   'ORDER BY bm25(content), segment DESC', (query_text,)))
    except sqlite3.OperationalError as exc:
        if 'no such module' not in str(exc):
            raise
        hits = []
        lowered = [term.casefold() for term in terms]
        for offset, (_, document) in enumerate(entries):
            candidates = [row.get('edited_text', row['text']) for row in document['segments']]
            candidates.append(' '.join(str(document.get(key, '')) for key in (
                'title', 'source_name', 'course', 'lecture_date', 'tags', 'notes', 'scratchpad', 'cards')))
            for position, body in enumerate(candidates):
                if all(term in body.casefold() for term in lowered):
                    hits.append((offset, position if position < len(candidates) - 1 else -1))
                    break
    matches = {}
    for index, segment in hits:
        if index not in matches or matches[index] == -1:
            matches[index] = segment
    return [(entries[index][0], entries[index][1],
             entries[index][1]['segments'][segment]['start'] if segment >= 0 else None)
            for index, segment in matches.items()]
