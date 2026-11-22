"""Short input tests and explicit installation of the optional speaker models."""
from hashlib import sha256
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from urllib.request import Request, urlopen
import wave


_SHERPA_RELEASES = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
_SEGMENTATION_FOLDER = 'sherpa-onnx-pyannote-segmentation-3-0'
_SEGMENTATION_URL = _SHERPA_RELEASES + f'speaker-segmentation-models/{_SEGMENTATION_FOLDER}.tar.bz2'
_EMBEDDING_URL = (_SHERPA_RELEASES + 'speaker-recongition-models/'
                  '3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx')
_ARCHIVE_BYTES = 6_958_444
_EMBEDDING_BYTES = 39_593_762
_SEGMENTATION_BYTES = 1_540_506
_ARCHIVE_HASH = '24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488'
_SEGMENTATION_HASH = 'd582f4b4c6b48205de7e0643c57df0df5615a3c176189be3fc461e9d18827b5d'
_EMBEDDING_HASH = 'f1ee61be04000b50392a63442e5dd9feaea7e81dddd494d3647cf1c3d88a1498'
SPEAKER_DOWNLOAD_BYTES = _ARCHIVE_BYTES + _EMBEDDING_BYTES
MIC_TEST_SECONDS = 5
_RATE = 16_000


class SetupCancelled(Exception):
    """The user stopped the setup operation."""


def _check_cancel(cancel):
    if cancel.is_set():
        raise SetupCancelled


def record_input_sample(device, path, cancel, progress, *, capture=None):
    """Write up to five seconds of PCM using Studio's selected input."""
    import numpy as np
    if capture is None:
        from annie.whisper_runtime import capture_audio as capture
    pcm = bytearray()
    capture_stop = Event()
    peak = 0
    limit = MIC_TEST_SECONDS * _RATE * 2
    next_report = 0

    def deliver(data):
        nonlocal peak, next_report
        if cancel.is_set() or capture_stop.is_set():
            capture_stop.set()
            return
        if not data:
            return
        block = data[:limit - len(pcm)]
        pcm.extend(block)
        samples = np.frombuffer(block, dtype='<i2').astype(np.int32)
        peak = max(peak, int(np.max(np.abs(samples))))
        if len(pcm) >= next_report:
            progress(len(pcm) // 2 * 1000 // _RATE, peak / 32768)
            next_report = len(pcm) + _RATE // 4
        if len(pcm) >= limit:
            capture_stop.set()

    _check_cancel(cancel)
    # Some sources can open without delivering samples. Bound the wait as well
    # as the amount of audio, and give the backend time to close its own stream.
    def watch_capture():
        deadline = monotonic() + MIC_TEST_SECONDS + 3
        while not capture_stop.wait(0.1):
            if cancel.is_set() or monotonic() >= deadline:
                capture_stop.set()

    stopper = Thread(target=watch_capture, name='input-test-timeout')
    stopper.start()
    try:
        capture(str(device), capture_stop, deliver)
    finally:
        capture_stop.set()
        stopper.join()
    _check_cancel(cancel)
    if not pcm:
        raise RuntimeError('No audio arrived. Check the selected source and its permissions.')
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, _RATE, 0, 'NONE', 'not compressed'))
        audio.writeframes(pcm)
    return len(pcm) / (2 * _RATE), peak / 32768


def _copy_response(stream, destination, expected_size, cancel, tick):
    digest = sha256()
    received = 0
    with destination.open('wb') as output:
        while True:
            _check_cancel(cancel)
            block = stream.read(128 * 1024)
            if not block:
                break
            received += len(block)
            if received > expected_size:
                raise ValueError('The model file exceeded its expected size.')
            digest.update(block)
            output.write(block)
            tick(received)
    if received != expected_size:
        raise ValueError('The model file was incomplete. Retry the download.')
    return digest.hexdigest()


def _valid_file(path, digest):
    try:
        with path.open('rb') as stream:
            return sha256_stream(stream) == digest
    except OSError:
        return False


def sha256_stream(stream):
    digest = sha256()
    for block in iter(lambda: stream.read(128 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def install_speaker_models(profile, cancel, progress, *, open_url=urlopen):
    """Download a verified pair and publish the directory in one rename."""
    root = Path(profile) / 'models'
    root.mkdir(parents=True, exist_ok=True)
    version = 'sherpa-3.0-eres2net'

    def installed(folder):
        return (_valid_file(folder / 'segmentation.onnx', _SEGMENTATION_HASH)
                and _valid_file(folder / 'embedding.onnx', _EMBEDDING_HASH))

    target = root / version
    _check_cancel(cancel)
    if installed(target):
        return target
    with TemporaryDirectory(prefix='.speaker-download-', dir=root) as staging:
        stage = Path(staging)
        pair = stage / 'models'
        pair.mkdir()
        archive = stage / 'segmentation.tar.bz2'
        for url, path, size, digest, offset in (
            (_SEGMENTATION_URL, archive, _ARCHIVE_BYTES, _ARCHIVE_HASH, 0),
            (_EMBEDDING_URL, pair / 'embedding.onnx', _EMBEDDING_BYTES, _EMBEDDING_HASH, _ARCHIVE_BYTES),
        ):
            _check_cancel(cancel)
            request = Request(url, headers={'User-Agent': 'LectureStudio'})
            with open_url(request, timeout=15) as response:
                actual = _copy_response(response, path, size, cancel,
                                        lambda received: progress(offset + received, SPEAKER_DOWNLOAD_BYTES))
            if actual != digest:
                raise ValueError('The speaker model download failed its integrity check.')
        with tarfile.open(archive, 'r:bz2') as packed:
            member = packed.getmember(f'{_SEGMENTATION_FOLDER}/model.int8.onnx')
            if not member.isfile() or member.size != _SEGMENTATION_BYTES:
                raise ValueError('The speaker segmentation archive is invalid.')
            with packed.extractfile(member) as stream:
                actual = _copy_response(stream, pair / 'segmentation.onnx', _SEGMENTATION_BYTES,
                                        cancel, lambda _: None)
            if actual != _SEGMENTATION_HASH:
                raise ValueError('The speaker segmentation failed its integrity check.')
            license_info = packed.getmember(f'{_SEGMENTATION_FOLDER}/LICENSE')
            if license_info.isfile() and 0 < license_info.size <= 32_768:
                with packed.extractfile(license_info) as stream:
                    (pair / 'SEGMENTATION-LICENSE.txt').write_bytes(stream.read())
        _check_cancel(cancel)
        for attempt in range(1, 100):
            target = root / (version if attempt == 1 else f'{version}-{attempt}')
            try:
                pair.rename(target)
            except OSError:
                if not target.exists():
                    raise
                if installed(target):
                    return target
            else:
                return target
        raise OSError('Could not allocate a folder for the speaker models.')
