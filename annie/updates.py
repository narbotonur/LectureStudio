"""Public GitHub releases, bounded background checks and a shared profile cache."""
import json
import platform
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PyQt5.QtCore import QObject, QLockFile, QThread, QTimer, pyqtSignal

from annie.secure_storage import atomic_write
from annie.version import REPOSITORY, VERSION

RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
CHECK_INTERVAL = 24 * 60 * 60
MAX_RESPONSE = 1024 * 1024


class UpdateError(ValueError):
    """A safe message intended for the update dialog."""


def version_tuple(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', str(value))
    if not match:
        raise ValueError('Expected a stable version such as v0.2.0.')
    return tuple(map(int, match.groups()))


def release_url(value, download=False):
    if not isinstance(value, str):
        return ''
    parsed = urlsplit(value)
    prefix = f'/{REPOSITORY}/releases/' + ('download/' if download else 'tag/')
    if (parsed.scheme == 'https' and parsed.netloc == 'github.com'
            and parsed.path.startswith(prefix) and not parsed.query and not parsed.fragment):
        return value
    return ''


def parse_release(payload):
    if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
        raise ValueError('The release is not a published stable version.')
    tag = payload.get('tag_name', '')
    version_tuple(tag)
    url = release_url(payload.get('html_url'))
    if not url:
        raise ValueError('The release link is invalid.')
    assets = []
    raw_assets = payload.get('assets', [])
    if not isinstance(raw_assets, list):
        raise ValueError('Invalid release assets.')
    for asset in raw_assets[:100]:
        if not isinstance(asset, dict):
            continue
        name = asset.get('name')
        link = release_url(asset.get('browser_download_url'), download=True)
        if isinstance(name, str) and link and asset.get('state', 'uploaded') == 'uploaded':
            assets.append({'name': name[:250], 'browser_download_url': link})
    body = payload.get('body')
    return {'tag_name': tag, 'html_url': url,
            'body': body[:60000] if isinstance(body, str) else '', 'assets': assets}


def select_download(release, system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    if system == 'darwin':
        if machine in ('arm64', 'aarch64'):
            markers = ('-arm64-', '-aarch64-', '-universal-')
        elif machine in ('x86_64', 'amd64'):
            markers = ('-x86_64-', '-x64-', '-universal-')
        else:
            return None
        matches = [a for a in release['assets'] if a['name'].lower().startswith('lecturestudio-macos-')
                   and any(marker in a['name'].lower() for marker in markers)
                   and a['name'].lower().endswith('.dmg')]
    elif system == 'win32' and machine in ('amd64', 'x86_64'):
        matches = [a for a in release['assets'] if a['name'].lower().startswith('lecturestudio-windows-')
                   and a['name'].lower().endswith('.zip') and 'source' not in a['name'].lower()]
    else:
        matches = []
    return matches[0] if matches else None


def read_cache(path):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('checked_at'), (int, float)):
            return {}
        if data.get('release') is not None:
            data['release'] = parse_release(data['release'])
        return data
    except (OSError, ValueError, TypeError):
        return {}


def check_release(path, manual=False, now=None):
    now = time.time() if now is None else now
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(path) + '.lock')
    if not lock.tryLock(0):
        return {**read_cache(path), 'error': 'Another update check is in progress. Try again shortly.'}
    try:
        cached = read_cache(path)
        age = now - cached.get('checked_at', 0)
        if not manual and 0 <= age < CHECK_INTERVAL:
            return cached
        result = {**cached, 'checked_at': now, 'error': ''}
        try:
            with requests.get(API_URL, headers={
                'Accept': 'application/vnd.github+json',
                'User-Agent': f'LectureStudio/{VERSION}',
            }, timeout=(5, 10), stream=True, allow_redirects=False) as response:
                if response.status_code == 404:
                    result['release'] = None
                elif response.status_code in (403, 429):
                    raise UpdateError('GitHub is limiting requests. Please try again later.')
                else:
                    if response.status_code != 200:
                        raise UpdateError('The update service is temporarily unavailable.')
                    raw = bytearray()
                    deadline = time.monotonic() + 15
                    for chunk in response.iter_content(8192):
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE or time.monotonic() > deadline:
                            raise UpdateError('The update response is too large or too slow.')
                    result['release'] = parse_release(json.loads(raw))
        except requests.RequestException:
            result['error'] = 'Could not check for updates. Check your connection and try again.'
        except UpdateError as error:
            result['error'] = str(error)
        except (ValueError, TypeError):
            result['error'] = 'Could not read a stable release. Try again later or open GitHub Releases.'
        atomic_write(path, json.dumps(result).encode('utf-8'))
        return result
    finally:
        lock.unlock()


class _CheckThread(QThread):
    result_ready = pyqtSignal(object)

    def __init__(self, path, manual, parent):
        super().__init__(parent)
        self.path, self.manual = path, manual

    def run(self):
        try:
            result = check_release(self.path, self.manual)
        except Exception:
            result = {'error': 'Could not check for updates. Please try again.'}
        self.result_ready.emit(result)


class UpdateService(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None, cache_path=None):
        super().__init__(parent)
        if cache_path is None:
            from annie.paths import DATA_DIR
            cache_path = DATA_DIR / 'update-check.json'
        self.path = Path(cache_path)
        self.state = read_cache(self.path)
        self.worker = None
        self.stopped = False
        # File-only polling lets an already open Studio see the watcher's result.
        self.cache_timer = QTimer(self)
        self.cache_timer.setInterval(15000)
        self.cache_timer.timeout.connect(self.reload_cache)
        self.cache_timer.start()
        self.automatic_timer = QTimer(self)
        self.automatic_timer.setInterval(CHECK_INTERVAL * 1000)
        self.automatic_timer.timeout.connect(self.check)

    def start_automatic(self):
        QTimer.singleShot(5000, self.check)
        self.automatic_timer.start()

    @property
    def available(self):
        release = self.state.get('release')
        return bool(release and version_tuple(release['tag_name']) > version_tuple(VERSION))

    def reload_cache(self):
        if self.worker or self.stopped:
            return
        state = read_cache(self.path)
        if state and state != self.state:
            self.state = state
            self.changed.emit()

    def check(self, manual=False):
        if self.worker or self.stopped:
            return
        self.worker = _CheckThread(self.path, manual, self)
        self.worker.result_ready.connect(self._result)
        self.worker.finished.connect(self._finished)
        self.changed.emit()
        self.worker.start()

    def _result(self, result):
        if not self.stopped:
            self.state = result
            self.changed.emit()

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        if not self.stopped:
            self.changed.emit()

    def stop(self):
        self.stopped = True
        self.cache_timer.stop()
        self.automatic_timer.stop()

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()
