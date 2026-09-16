"""Verified release downloads and staged Windows installation; never overwrite live code."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlsplit
import zipfile

import requests
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from annie.updates import UpdateError, parse_release, release_url, select_download

MAX_DOWNLOAD = 2 * 1024**3
MAX_EXTRACTED = 6 * 1024**3
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com',
                  'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}


class DownloadCancelled(UpdateError):
    pass


def safe_filename(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,220}', name):
        raise UpdateError('Invalid update filename.')
    return name


def open_asset(url):
    if not release_url(url, download=True):
        raise UpdateError('Invalid download link.')
    for _ in range(6):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc not in DOWNLOAD_HOSTS:
            raise UpdateError('The download redirected outside GitHub.')
        response = requests.get(url, stream=True, timeout=(5, 15), allow_redirects=False,
                                headers={'Accept': 'application/octet-stream'})
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get('Location', '')
            response.close()
            if not location:
                break
            url = urljoin(url, location)
            continue
        if response.status_code != 200:
            response.close()
            raise UpdateError('Could not download this release. Please try again later.')
        return response
    raise UpdateError('Too many download redirects.')


def expected_checksum(release, asset):
    digest = asset.get('digest') or ''
    if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        return digest.split(':')[1].lower()
    checksum = next((a for a in release['assets'] if a['name'] == asset['name'] + '.sha256'), None)
    if checksum is None:
        raise UpdateError('This release has no SHA-256 checksum. Ask the publisher to attach the .sha256 file.')
    with open_asset(checksum['browser_download_url']) as response:
        data = bytearray()
        for chunk in response.iter_content(1024):
            data.extend(chunk)
            if len(data) > 4096:
                raise UpdateError('Invalid checksum file.')
    try:
        text = data.decode('ascii').strip()
    except UnicodeError as error:
        raise UpdateError('Invalid checksum file.') from error
    match = re.fullmatch(r'([0-9a-fA-F]{64})(?:\s+\*?([^\r\n]+))?', text)
    if not match or (match[2] is not None and match[2] != asset['name']):
        raise UpdateError('The checksum does not identify this installer.')
    return match[1].lower()


def download_release(release, folder, progress=lambda done, total: None, cancelled=lambda: False):
    release = parse_release(release)
    asset = select_download(release)
    if not asset:
        raise UpdateError('No installer for this computer is attached to the release.')
    name = safe_filename(asset['name'])
    digest = expected_checksum(release, asset)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    size = asset.get('size') or 0
    if size > MAX_DOWNLOAD or shutil.disk_usage(folder).free < (size or MAX_DOWNLOAD) + 64 * 1024**2:
        raise UpdateError('Not enough space for this update, or the installer is too large.')
    destination = Path(tempfile.mkdtemp(prefix='release-', dir=folder)) / name
    partial = destination.with_suffix(destination.suffix + '.part')
    downloaded = 0
    deadline = time.monotonic() + 3600
    hasher = hashlib.sha256()
    try:
        with open_asset(asset['browser_download_url']) as response, partial.open('xb') as stream:
            progress(0, size)
            for chunk in response.iter_content(256 * 1024):
                if cancelled():
                    raise DownloadCancelled('Download cancelled. You can try again later.')
                if time.monotonic() > deadline:
                    raise UpdateError('The download timed out. Please try again.')
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD or (size and downloaded > size):
                    raise UpdateError('The download size does not match the release.')
                stream.write(chunk)
                hasher.update(chunk)
                progress(downloaded, size)
        if cancelled():
            raise DownloadCancelled('Download cancelled. You can try again later.')
        if not downloaded or (size and downloaded != size) or hasher.hexdigest() != digest:
            raise UpdateError('Checksum verification failed. The file was discarded; please retry.')
        if sys.platform == 'darwin':
            # Preserve the normal downloaded-file prompt when Finder opens the DMG.
            subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine',
                            f'0081;{int(time.time()):x};Lecture Studio;', str(partial)],
                           check=True, timeout=10, capture_output=True)
        partial.replace(destination)
        return {'path': str(destination), 'sha256': digest, 'tag': release['tag_name']}
    finally:
        partial.unlink(missing_ok=True)


def installed_windows_directory():
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return None
    directory = Path(sys.executable).resolve().parent
    # Restrict directory replacement to the canonical portable bundle, never a
    # Desktop/Downloads root or source checkout containing other user files.
    if directory.name != 'LectureStudio' or Path(sys.executable).name != 'LectureStudio.exe':
        return None
    if not (directory / 'LectureStudioWorker.exe').is_file() or not (directory / '_internal').is_dir():
        return None
    from annie.paths import DATA_DIR
    if DATA_DIR.resolve().is_relative_to(directory):
        return None
    return directory


def stage_windows(archive, install_dir, cancelled=lambda: False):
    install_dir = Path(install_dir).resolve()
    if install_dir.name != 'LectureStudio' or not (install_dir / 'LectureStudio.exe').is_file():
        raise UpdateError('This installation must be updated manually.')
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if not entries or len(entries) > 20000:
            raise UpdateError('Invalid update archive.')
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or not path.parts or path.parts[0] != 'LectureStudio'
                    or any(part in ('.', '..') or re.search(r'[<>:"|?*\\\x00-\x1f]', part)
                           or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)
                           or part.endswith((' ', '.')) for part in path.parts)
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise UpdateError('Unsafe path in the update archive.')
            key = str(path).casefold()
            if key in seen:
                raise UpdateError('Duplicate file in the update archive.')
            seen.add(key)
        total = sum(entry.file_size for entry in entries)
        if total > MAX_EXTRACTED or shutil.disk_usage(install_dir.parent).free < total + 64 * 1024**2:
            raise UpdateError('Not enough space to prepare the update.')
        for required in ('lecturestudio/lecturestudio.exe', 'lecturestudio/lecturestudioworker.exe'):
            if required not in seen:
                raise UpdateError('This archive is not a Lecture Studio installation.')
        stage = Path(tempfile.mkdtemp(prefix='LectureStudio-update-', dir=install_dir.parent))
        # All paths have been validated before any member is extracted.
        for entry in entries:
            if cancelled():
                raise DownloadCancelled('Update preparation cancelled. No application files were replaced.')
            target = stage.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, target.open('xb') as dest:
                    shutil.copyfileobj(source, dest, 1024 * 1024)
        if not (stage / 'LectureStudio/_internal').is_dir():
            raise UpdateError('The installer is missing its runtime.')
        return stage / 'LectureStudio'


def launch_windows_install(staged, target, working_folder):
    import psutil
    target = Path(target).resolve()
    # Old watchers keep code loaded. Let the user quit them through their menu.
    for process in psutil.process_iter(['pid', 'name']):
        if process.pid == os.getpid() or 'lecturestudio' not in (process.info['name'] or '').lower():
            continue
        try:
            if Path(process.exe()).resolve().is_relative_to(target):
                args = process.cmdline()
                if '--watch' in args or '--prayer-widget' in args:
                    raise UpdateError('Quit the watcher and prayer widget from their tray menus, then click Install and restart again.')
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    helper = Path(working_folder) / 'install-update.ps1'
    shutil.copy2(Path(__file__).with_name('update_install.ps1'), helper)
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                      '-File', str(helper), '-InstallDir', str(target), '-StagedDir', str(staged),
                      '-WaitPid', str(os.getpid())], cwd=str(working_folder),
                     creationflags=subprocess.CREATE_NO_WINDOW)


class DownloadThread(QThread):
    progress = pyqtSignal(object, object)
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, release, folder, parent=None):
        super().__init__(parent)
        self.release, self.folder = release, folder

    def run(self):
        try:
            result = download_release(self.release, self.folder, self.progress.emit, self.isInterruptionRequested)
            target = installed_windows_directory()
            if target:
                result['staged'] = str(stage_windows(result['path'], target, self.isInterruptionRequested))
                result['target'] = str(target)
            self.ready.emit(result)
        except (UpdateError, OSError, requests.RequestException, zipfile.BadZipFile) as error:
            message = str(error) if isinstance(error, UpdateError) else 'Download or preparation failed. Check your connection and free disk space, then retry.'
            self.failed.emit(message)
        except Exception:
            self.failed.emit('Could not prepare the update. Please retry or open the release page.')


class DownloadService(QObject):
    changed = pyqtSignal()

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.worker = None
        self.result = None
        self.error = ''
        self.done = self.total = 0

    def start(self, release):
        if self.worker:
            return
        self.result = None
        self.error = ''
        self.done = self.total = 0
        self.worker = DownloadThread(release, self.folder, self)
        self.worker.progress.connect(self._progress)
        self.worker.ready.connect(self._ready)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()
        self.changed.emit()

    def _progress(self, done, total):
        self.done, self.total = done, total
        self.changed.emit()

    def _ready(self, result):
        self.result = result

    def _failed(self, error):
        self.error = error

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.changed.emit()

    def cancel(self):
        if self.worker:
            self.worker.requestInterruption()

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()
