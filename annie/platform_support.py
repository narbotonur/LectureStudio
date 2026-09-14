"""Small, testable platform decisions; no native imports at module load."""
import os
from pathlib import Path
import sys


def user_data_dir(platform=None, home=None, environ=None):
    platform = platform or sys.platform
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    if platform == 'darwin':
        return home / 'Library/Application Support/Annie/LectureStudio'
    if platform == 'win32':
        return Path(environ.get('LOCALAPPDATA', home / 'AppData/Local')) / 'Annie/LectureStudio'
    return Path(environ.get('XDG_DATA_HOME', home / '.local/share')) / 'annie/lecture-studio'


def audio_sources(platform=None):
    options = (('Microphone', 'default'), ('System audio', 'system'),
               ('Mic + system', 'dual'), ('Wireless mic', 'phone'))
    return options


def validate_audio_source(source, platform=None):
    if source not in ('default', 'phone', 'system', 'loopback', 'computer', 'dual', 'mix'):
        try:
            if int(source) < 0:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('Choose a valid audio source or input device.') from None


def worker_command(executable=None, packaged=None, platform=None):
    executable = executable or sys.executable
    packaged = bool(getattr(sys, 'frozen', False)) if packaged is None else packaged
    platform = platform or sys.platform
    if packaged:
        name = 'LectureStudioWorker.exe' if platform == 'win32' else 'LectureStudioWorker'
        return [str(Path(executable).with_name(name)), '--whisper-service']
    return [executable, '-u', '-m', 'annie.whisper_worker', '--service']
