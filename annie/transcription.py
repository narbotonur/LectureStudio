"""Provider-neutral, timestamped transcript values used by review and evidence."""
from dataclasses import asdict, dataclass
import hashlib
import math


@dataclass(frozen=True)
class TranscriptSegment:
    id: str
    start: float
    end: float
    text: str
    source: str
    backend: str
    speaker: str = ''
    final: bool = True

    @classmethod
    def create(cls, start, end, text, source, backend='local', speaker=''):
        start, end = float(start), float(end)
        text = str(text).strip()
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError('Transcript timestamps must be finite and ordered.')
        if not text:
            raise ValueError('Transcript segment must contain text.')
        identity = f'{source}|{backend}|{start:.3f}|{end:.3f}|{text}'
        key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        return cls(key, round(start, 3), round(end, 3), text, str(source), backend, speaker)

    def to_dict(self):
        return asdict(self)


def emit_segment(emit, start, end, text, source, backend='local', speaker=''):
    value = TranscriptSegment.create(start, end, text, source, backend, speaker)
    emit('transcript_segment', segment=value.to_dict())
    return value
