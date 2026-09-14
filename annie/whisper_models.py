"""Resolve public Whisper weights locally before allowing a download.

Moving Studio profiles must not silently redownload gigabytes that already exist
in the user's Hugging Face cache. Never modify or copy shared cache entries.
"""
from contextlib import contextmanager
from pathlib import Path
import threading
import time


def complete_model(path):
    path = Path(path)
    required = ('model.bin', 'config.json', 'tokenizer.json')
    try:
        return (all((path / name).is_file() and (path / name).stat().st_size > 0 for name in required)
                and any(item.is_file() and item.stat().st_size > 0 for item in path.glob('vocabulary.*')))
    except OSError:
        return False


def resolve_model(name, report=None):
    from annie import config as cfg
    from faster_whisper.utils import download_model
    from huggingface_hub.constants import HF_HUB_CACHE

    report = report or (lambda text: None)
    explicit = Path(name).expanduser()
    local = Path(cfg.MODELS_DIR) / name
    for candidate in (explicit, local):
        if complete_model(candidate):
            report(f'Using existing Whisper files ({name}); no download needed')
            return str(candidate.resolve())
    if explicit.is_absolute() or explicit.is_dir():
        raise ValueError('The selected Whisper folder is incomplete. It needs model.bin, config.json, '
                         'tokenizer.json and vocabulary files. Choose a complete model folder.')

    cache_dir = Path(cfg.DATA_DIR) / 'model-cache'
    roots = (cache_dir, Path(HF_HUB_CACHE), Path.home() / '.cache/huggingface/hub')
    seen = set()
    for root in roots:
        identity = str(root.resolve())
        if identity in seen:
            continue
        seen.add(identity)
        try:
            # A snapshot directory can exist with only JSON files while model.bin
            # is still downloading. local_files_only by itself is not enough.
            candidate = download_model(name, cache_dir=str(root), local_files_only=True)
        except (OSError, ValueError):
            continue
        if complete_model(candidate):
            report(f'Using cached Whisper ({name}); no download needed')
            return str(Path(candidate).resolve())

    report(f'Downloading Whisper ({name}) for first use. Large models can take several minutes; audio capture has not started')
    candidate = download_model(name, cache_dir=str(cache_dir))
    if not complete_model(candidate):
        raise RuntimeError('Whisper download is incomplete. Check your connection and available disk space, then retry.')
    return str(Path(candidate).resolve())


@contextmanager
def preparation_status(name, emit, interval=2.0):
    """Keep model startup visibly alive without inventing download percentages."""
    started = time.monotonic()
    finished = threading.Event()
    lock = threading.Lock()
    phase = [f'Checking cached Whisper ({name})']

    def report(text):
        with lock:
            phase[0] = text
            emit('status', text=text)

    def heartbeat():
        while not finished.wait(interval):
            with lock:
                elapsed = int(time.monotonic() - started)
                emit('status', text=f'{phase[0]} — {elapsed}s elapsed')

    report(phase[0])
    thread = threading.Thread(target=heartbeat, name='whisper-load-status', daemon=True)
    thread.start()
    try:
        yield report
    finally:
        finished.set()
        thread.join()
