"""Editable TSV flashcards with local, persistent FSRS review state."""
import csv
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import sqlite3
from contextlib import closing

from annie.lecture_archive import library_entries


def parse_cards(text):
    if '```tsv' in text.casefold():
        start = text.casefold().index('```tsv') + len('```tsv')
        text = text[start:].split('```', 1)[0]
    text = text.strip()
    if '\t' not in text:
        text = text.replace('\\t', '\t')
    rows = []
    for fields in csv.reader(io.StringIO(text), delimiter='\t'):
        if len(fields) < 2 or not fields[0].strip() or not fields[1].strip():
            continue
        front, back = (field.strip() for field in fields[:2])
        if (front.casefold(), back.casefold()) in (('front', 'back'), ('<front>', '<back>')):
            continue
        rows.append((front, back, fields[2].strip() if len(fields) > 2 else ''))
    return rows


def export_tsv(rows):
    output = io.StringIO(newline='')
    csv.writer(output, delimiter='\t', lineterminator='\n').writerows(rows)
    return output.getvalue()


def _cards(document):
    for front, back, tags in parse_cards(document.get('cards', '')):
        identity = hashlib.sha256(f"{document['id']}\0{front}\0{back}".encode()).hexdigest()
        yield {'id': identity, 'front': front, 'back': back, 'tags': tags,
               'title': document.get('title') or document['source_name']}


class CardReviews:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'card-reviews.sqlite3'

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS card_schedule (id TEXT PRIMARY KEY, state TEXT, due TEXT);
            CREATE TABLE IF NOT EXISTS card_reviews (id TEXT, reviewed TEXT, rating INTEGER);
        """)
        return db

    def due(self, now=None):
        now = now or datetime.now(timezone.utc)
        seen = set()
        with closing(self._connect()) as db:
            future = {row[0] for row in db.execute('SELECT id FROM card_schedule WHERE due > ?', (now.isoformat(),))}
        for _, document in library_entries(self.root):
            for card in _cards(document):
                if card['id'] not in future and card['id'] not in seen:
                    seen.add(card['id'])
                    yield card

    def rate(self, identity, rating, now=None):
        from fsrs import Card, Rating, Scheduler
        now = now or datetime.now(timezone.utc)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM card_schedule WHERE id=?', (identity,)).fetchone()
            card = Card.from_json(row[0]) if row else Card(card_id=int(identity[:12], 16), due=now)
            card, log = Scheduler().review_card(card, Rating(rating), now)
            db.execute('INSERT OR REPLACE INTO card_schedule VALUES (?,?,?)',
                       (identity, card.to_json(), card.due.isoformat()))
            db.execute('INSERT INTO card_reviews VALUES (?,?,?)',
                       (identity, log.review_datetime.isoformat(), int(log.rating)))
            return card.due
