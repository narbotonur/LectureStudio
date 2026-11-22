"""Optional offline speaker diarization in an isolated process."""
import argparse
from bisect import bisect_right
from collections import defaultdict
from importlib.util import find_spec
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class DiarizationError(RuntimeError):
    """Diarization did not produce a usable result."""


class DiarizationCancelled(DiarizationError):
    """Diarization was cancelled by the request owner."""


_SHERPA_FILES = ('segmentation.onnx', 'embedding.onnx')
_COMMUNITY_FILES = ('config.yaml', 'embedding/pytorch_model.bin', 'segmentation/pytorch_model.bin',
                    'plda/plda.npz', 'plda/xvec_transform.npz')
_SAMPLE_RATE = 16000


def diarization_model_dir(model_path=None):
    """Return the explicit model directory or the optional profile location."""
    if model_path or os.environ.get('ANNIE_DIARIZATION_MODEL_DIR'):
        return Path(model_path or os.environ['ANNIE_DIARIZATION_MODEL_DIR']).expanduser().resolve()
    from annie.paths import DATA_DIR
    return DATA_DIR / 'models' / 'diarization'


def _has_files(model_path, files):
    return all((model_path / name).is_file() for name in files)


def _available_backend(model_path):
    if _has_files(model_path, _SHERPA_FILES) and find_spec('sherpa_onnx') is not None:
        return 'sherpa'
    if (_has_files(model_path, _COMMUNITY_FILES) and find_spec('pyannote') is not None
            and find_spec('torch') is not None):
        return 'community'
    return ''


def diarization_ready(model_path=None):
    """Check for models and a runtime without importing native libraries."""
    try:
        return bool(_available_backend(diarization_model_dir(model_path)))
    except (OSError, ValueError):
        return False


def _backend(model_path):
    backend = _available_backend(model_path)
    if backend:
        return backend
    if _has_files(model_path, _SHERPA_FILES):
        raise DiarizationError('Install the optional sherpa-onnx runtime to use these speaker models.')
    if _has_files(model_path, _COMMUNITY_FILES):
        raise DiarizationError('Install pyannote.audio 4 and its PyTorch runtime to use Community-1.')
    raise DiarizationError('Choose a folder with local speaker models. See the speaker model setup guide.')


def _check_cancelled(stop):
    if stop is not None and stop.is_set():
        raise DiarizationCancelled('Speaker analysis was cancelled.')


def _worker_command():
    if getattr(sys, 'frozen', False):
        from annie.platform_support import worker_command
        return [worker_command()[0], '--diarization-worker']
    return [sys.executable, '-m', 'annie.diarization']


def diarize(audio_path, *, model_path=None, speaker_count=None, stop=None):
    """Return sorted speaker turns in seconds, retaining overlaps and recurring identities."""
    _check_cancelled(stop)
    audio_path = Path(audio_path).expanduser().resolve()
    if not audio_path.is_file():
        raise DiarizationError('The linked recording could not be found. Link the audio again to separate speakers.')
    if speaker_count is not None and (type(speaker_count) is not int or speaker_count < 1):
        raise DiarizationError('The number of speakers must be a positive integer.')
    model_path = diarization_model_dir(model_path)
    backend = _backend(model_path)
    with tempfile.TemporaryDirectory(prefix='studio-speaker-analysis-') as temporary:
        result = Path(temporary) / 'turns.json'
        command = _worker_command() + [str(audio_path), str(model_path), backend, str(result)]
        if speaker_count is not None:
            command.extend(('--speaker-count', str(speaker_count)))
        try:
            worker = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[1],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                env={**os.environ, 'HF_HUB_OFFLINE': '1', 'PYANNOTE_METRICS_ENABLED': '0'},
            )
        except OSError as exc:
            raise DiarizationError('Could not start the local speaker analysis worker.') from exc
        try:
            while True:
                _check_cancelled(stop)
                try:
                    worker.wait(timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    continue
            _check_cancelled(stop)
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
        try:
            reply = json.loads(result.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise DiarizationError(
                'The speaker worker stopped before completing analysis. Check the local model files and try again.'
            ) from None
        if worker.returncode:
            raise DiarizationError(reply.get('error', 'Local speaker analysis failed.'))
        return reply['turns']


def _sherpa_turns(audio, model_path, speaker_count):
    import sherpa_onnx

    segmentation = sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=str(model_path / _SHERPA_FILES[0])),
        num_threads=2,
    )
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=segmentation,
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path / _SHERPA_FILES[1]), num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speaker_count or -1),
    )
    if not config.validate():
        raise DiarizationError('The sherpa-onnx speaker model configuration is invalid.')
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    return [(turn.start, turn.end, str(turn.speaker))
            for turn in diarizer.process(audio).sort_by_start_time()]


def _community_turns(audio, model_path, speaker_count):
    import torch
    from pyannote.audio import Pipeline

    if not _has_files(model_path, _COMMUNITY_FILES):
        raise DiarizationError('The Community-1 folder is missing one or more local weights.')
    pipeline = Pipeline.from_pretrained(model_path, token=False)
    if pipeline is None:
        raise DiarizationError('Could not load the Community-1 pipeline from the local model folder.')
    options = {'num_speakers': speaker_count} if speaker_count is not None else {}
    result = pipeline({'waveform': torch.from_numpy(audio).unsqueeze(0), 'sample_rate': _SAMPLE_RATE},
                      **options)
    return [(turn.start, turn.end, speaker) for turn, speaker in result.speaker_diarization]


def _normalize_turns(turns, duration):
    labels = {}
    result = []
    for start, end, label in sorted(turns):
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start, end = max(0.0, start), min(duration, end)
        if end > start:
            if label not in labels:
                labels[label] = f'speaker-{len(labels) + 1}'
            result.append({'start': start, 'end': end, 'speaker': labels[label]})
    return result


def overlap_windows(turns):
    """Return intervals where the model reports at least two distinct speakers."""
    events = defaultdict(list)
    if not isinstance(turns, (list, tuple)):
        return []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        start, end, speaker = turn.get('start'), turn.get('end'), turn.get('speaker')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not 0 <= start < end or not math.isfinite(end) or not isinstance(speaker, str) or not speaker):
            continue
        events[start].append((speaker, 1))
        events[end].append((speaker, -1))
    active = defaultdict(int)
    windows = []
    opened = None
    for when, changes in sorted(events.items()):
        for speaker, change in changes:
            active[speaker] += change
            if not active[speaker]:
                del active[speaker]
        if len(active) >= 2 and opened is None:
            opened = when
        elif len(active) < 2 and opened is not None:
            windows.append((opened, when))
            opened = None
    return windows


def overlapping_passages(segments, windows):
    ends = [end for _, end in windows]
    result = set()
    for row in segments:
        index = bisect_right(ends, row['start'])
        if index < len(windows) and windows[index][0] < row['end']:
            result.add(row['id'])
    return result


def speaker_voice_sample(segments, speaker, windows, max_seconds=5):
    """Use the longest clean excerpt of that speaker's current passage labels."""
    ends = [end for _, end in windows]
    best = None
    best_length = 0.0
    for row in segments:
        if row.get('speaker') != speaker:
            continue
        cursor, end = row['start'], row['end']
        index = bisect_right(ends, cursor)
        while index < len(windows):
            left, right = windows[index]
            if left >= end:
                break
            duration = min(max_seconds, left - cursor)
            if duration > best_length:
                best, best_length = (cursor, cursor + duration), duration
            cursor = max(cursor, right)
            index += 1
        duration = min(max_seconds, end - cursor)
        if duration > best_length:
            best, best_length = (cursor, cursor + duration), duration
        if best_length >= max_seconds:
            break
    return best if best_length >= 0.2 else None


def worker_main(argv=None):
    parser = argparse.ArgumentParser(description='Run local speaker analysis on one recording.')
    parser.add_argument('audio', type=Path)
    parser.add_argument('models', type=Path)
    parser.add_argument('backend', choices=('sherpa', 'community'))
    parser.add_argument('result', type=Path)
    parser.add_argument('--speaker-count', type=int)
    args = parser.parse_args(argv)
    from faster_whisper.audio import decode_audio

    # Passing an open file keeps the decoder on this local input.
    try:
        with args.audio.open('rb') as source:
            audio = decode_audio(source, sampling_rate=_SAMPLE_RATE)
    except Exception:
        args.result.write_text(json.dumps({'error': 'The recording could not be decoded.'}), encoding='utf-8')
        return 1
    try:
        turns = []
        if audio.size and audio.any():
            engine = _sherpa_turns if args.backend == 'sherpa' else _community_turns
            turns = _normalize_turns(engine(audio, args.models, args.speaker_count),
                                     len(audio) / _SAMPLE_RATE)
        reply = {'turns': turns}
    except DiarizationError as exc:
        reply = {'error': str(exc)}
    except Exception:
        reply = {'error': 'Local speaker analysis failed. Check the installed model and runtime versions.'}
    args.result.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
    return int('error' in reply)


def _interval_assignments(segments, turns):
    # Union each speaker's timeline so repeated intervals never double-count.
    by_speaker = defaultdict(list)
    for turn in sorted(turns, key=lambda item: (item['start'], item['end'])):
        windows = by_speaker[turn['speaker']]
        start, end = turn['start'], turn['end']
        if windows and start <= windows[-1][1]:
            previous_start, previous_end = windows[-1]
            windows[-1] = (previous_start, max(previous_end, end))
        else:
            windows.append((start, end))

    indices = dict.fromkeys(by_speaker, 0)
    assignments = {}
    for segment in sorted(segments, key=lambda item: item['start']):
        start, end = segment['start'], segment['end']
        duration = end - start
        if duration <= 0 or not segment.get('id'):
            continue
        coverage = []
        for speaker, windows in by_speaker.items():
            i = indices[speaker]
            while i < len(windows) and windows[i][1] <= start:
                i += 1
            indices[speaker] = i
            covered = 0.0
            while i < len(windows) and windows[i][0] < end:
                left, right = windows[i]
                covered += min(end, right) - max(start, left)
                i += 1
            if covered > 0:
                coverage.append((covered, speaker))
        coverage.sort(reverse=True)
        if coverage:
            best, speaker = coverage[0]
            next_best = coverage[1][0] if len(coverage) > 1 else 0.0
            if best >= duration * 0.45 and best - next_best >= duration * 0.1:
                assignments[segment['id']] = speaker
    return assignments


def assign_speaker_words(segments, turns):
    """Return copies of timed words with speaker labels, keyed by segment ID."""
    intervals = []
    words = {}
    for segment in segments:
        identity = segment.get('id')
        if not identity:
            continue
        for word in segment.get('words') or ():
            if not isinstance(word, dict):
                continue
            start, end = word.get('start'), word.get('end')
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or end <= start):
                continue
            group = words.setdefault(identity, [])
            key = (identity, len(group))
            group.append({**word, 'speaker': ''})
            intervals.append({'id': key, 'start': start, 'end': end})
    for (identity, index), speaker in _interval_assignments(intervals, turns).items():
        words[identity][index]['speaker'] = speaker
    return words


def assign_speakers(segments, turns):
    """Assign a whole segment to one clear speaker, using timed words when available."""
    segments = list(segments)
    turns = list(turns)
    words_by_segment = assign_speaker_words(segments, turns)
    assignments = _interval_assignments((row for row in segments if row.get('id') not in words_by_segment), turns)
    for identity, words in words_by_segment.items():
        duration = 0.0
        totals = defaultdict(float)
        for word in words:
            seconds = word['end'] - word['start']
            duration += seconds
            if word['speaker']:
                totals[word['speaker']] += seconds
        # Keep a mixed transcript segment unassigned if there is no majority.
        for speaker, seconds in totals.items():
            if seconds > duration / 2:
                assignments[identity] = speaker
                break
    return assignments


if __name__ == '__main__':
    raise SystemExit(worker_main())
