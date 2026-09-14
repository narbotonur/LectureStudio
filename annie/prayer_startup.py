"""Separate opt-in login item: prayer widgets never start Studio or recording."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from annie.startup import RUN_KEY, studio_arguments
from annie.secure_storage import atomic_write

VALUE = 'AnniePrayerWidget'
LABEL = 'local.annie.prayer-widget'


def arguments():
    return studio_arguments() + ['--prayer-widget']


def command():
    return subprocess.list2cmdline(arguments())


def agent_path():
    return Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')


def agent():
    result = {'Label': LABEL, 'ProgramArguments': arguments(), 'RunAtLoad': True,
              'LimitLoadToSessionType': 'Aqua', 'ProcessType': 'Interactive'}
    if os.environ.get('ANNIE_DATA_DIR'):
        result['EnvironmentVariables'] = {'ANNIE_DATA_DIR': str(Path(os.environ['ANNIE_DATA_DIR']).resolve())}
    return result


def enabled():
    if sys.platform == 'darwin':
        try:
            return plistlib.loads(agent_path().read_bytes()) == agent()
        except (OSError, ValueError):
            return False
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return winreg.QueryValueEx(key, VALUE)[0] == command()
        except FileNotFoundError:
            return False
    return False


def set_enabled(value):
    if sys.platform == 'darwin':
        path = agent_path()
        if value:
            if path.exists() and not enabled():
                raise RuntimeError('Другой экземпляр виджета уже настроил автозапуск.')
            atomic_write(path, plistlib.dumps(agent()))
        elif enabled():
            path.unlink()
    elif sys.platform == 'win32':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if value:
                winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
            elif enabled():
                winreg.DeleteValue(key, VALUE)
    elif value:
        raise RuntimeError('Автозапуск поддерживается в Windows и macOS.')


def launch():
    subprocess.Popen(arguments(), cwd=str(Path(__file__).resolve().parents[1]),
                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
