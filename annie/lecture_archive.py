"""Durable timestamped transcripts, independent from cloud note generation."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from annie.lecture_actions import normalize_segments
from annie.secure_storage import atomic_write


def save_transcript(root, segments, source_name, course='', complete=True, lecture_date=None):
    normalized = normalize_segments(segments)
    identity = hashlib.sha256(source_name.encode('utf-8')).hexdigest()[:24]
    path = Path(root) / 'transcripts' / f'lecture-{identity}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'version': 1, 'source_name': source_name[:200], 'course': course[:100],
               'complete': bool(complete), 'lecture_date': lecture_date.isoformat() if lecture_date else None,
               'segments': [asdict(segment) for segment in normalized]}
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
    return path


def load_transcript(path):
    path = Path(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError('This transcript is too large. Open a shorter lecture excerpt.')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('version') != 1:
            raise ValueError
        payload['segments'] = [asdict(item) for item in normalize_segments(payload['segments'])]
        if not isinstance(payload.get('source_name'), str) or not isinstance(payload.get('course', ''), str):
            raise ValueError
        return payload
    except (ValueError, KeyError, TypeError):
        raise ValueError('Choose a timestamped Lecture Studio transcript archive.') from None
