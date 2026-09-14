"""Opt-in per-user startup. macOS changes apply at the next login."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE = 'AnnieLectureStudio'
MAC_LABEL = 'local.annie.lecture-studio.watcher'


def studio_arguments():
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    executable = str(Path(sys.executable).with_name('pythonw.exe')) if sys.platform == 'win32' else sys.executable
    return [executable, str(Path(__file__).resolve().parents[1] / 'lecture_studio_entry.py')]


def startup_arguments():
    return studio_arguments() + ['--watch']


class StudioLauncher:
    """Launch current files, never the UI imported by a long-lived watcher."""
    def __init__(self):
        self.process = None

    def __call__(self):
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(
                studio_arguments(), cwd=str(Path(__file__).resolve().parents[1]),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)


def outdated_watcher_pids():
    """Identify this source installation's pre-update watchers, without stopping them.

    A watcher can survive source updates for days. Its imported code cannot be
    fixed by starting another Python process. Never inspect another user's app
    or use this development check for frozen releases.
    """
    if getattr(sys, 'frozen', False):
        return []
    import psutil
    root = Path(__file__).resolve().parents[1]
    revision_time = max((root / 'annie' / name).stat().st_mtime for name in
                        ('workstation_main.py', 'studio_router.py'))
    user = psutil.Process().username()
    stale = []
    # Reading command lines for every process is slow on Windows. Inspect only
    # Python candidates, and tolerate processes exiting during the check.
    for process in psutil.process_iter(['pid', 'name']):
        info = process.info
        if info['pid'] == os.getpid() or not (info.get('name') or '').lower().startswith('python'):
            continue
        try:
            args = process.cmdline()
            if ('--watch' not in args or process.username() != user
                    or not any(arg == 'annie.workstation_main' or
                               Path(arg).name == 'lecture_studio_entry.py' for arg in args)
                    or process.create_time() >= revision_time):
                continue
            if Path(process.cwd()).resolve() == root:
                stale.append(info['pid'])
        except (psutil.Error, OSError):
            continue
    return stale


def _launch_agent_path():
    return Path.home() / 'Library/LaunchAgents' / (MAC_LABEL + '.plist')


def _launch_agent():
    result = {'Label': MAC_LABEL, 'ProgramArguments': startup_arguments(),
              'RunAtLoad': True, 'LimitLoadToSessionType': 'Aqua', 'ProcessType': 'Interactive'}
    if os.environ.get('ANNIE_DATA_DIR'):
        result['EnvironmentVariables'] = {'ANNIE_DATA_DIR': str(Path(os.environ['ANNIE_DATA_DIR']).resolve())}
    return result


def _read_agent(path):
    try:
        return plistlib.loads(path.read_bytes())
    except (FileNotFoundError, ValueError, plistlib.InvalidFileException):
        return None


def _owns_agent(value):
    expected = _launch_agent()
    return (isinstance(value, dict) and value.get('Label') == MAC_LABEL and
            value.get('ProgramArguments') == expected['ProgramArguments'] and
            value.get('EnvironmentVariables', {}) == expected.get('EnvironmentVariables', {}))


def startup_command():
    return subprocess.list2cmdline(startup_arguments())


def enabled():
    if sys.platform == 'darwin':
        return _owns_agent(_read_agent(_launch_agent_path()))
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE)[0] == startup_command()
    except FileNotFoundError:
        return False


def set_enabled(value):
    if sys.platform == 'darwin':
        from annie.secure_storage import atomic_write
        path = _launch_agent_path()
        current = _read_agent(path)
        if value:
            if path.exists() and not _owns_agent(current):
                raise RuntimeError('A different Lecture Studio installation owns login startup. Disable it there first.')
            atomic_write(path, plistlib.dumps(_launch_agent()))
        elif _owns_agent(current):
            # Do not stop an active watcher/recording; the current session is
            # managed by its menu-bar Quit watcher action. No KeepAlive job.
            path.unlink()
        return
    if sys.platform != 'win32':
        raise RuntimeError('Login startup is not supported on this platform.')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if value:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                # Do not remove a different installation's entry.
                if winreg.QueryValueEx(key, VALUE)[0] == startup_command():
                    winreg.DeleteValue(key, VALUE)
            except FileNotFoundError:
                pass
