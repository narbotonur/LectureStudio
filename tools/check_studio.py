"""Run the Studio suite without reading or writing the real user profile."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='lecture-studio-tests-') as temporary:
        environment = {**os.environ, 'ANNIE_DATA_DIR': temporary,
                       'PYTHONDONTWRITEBYTECODE': '1'}
        environment.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')
        result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests'],
                                cwd=Path(__file__).resolve().parents[1], env=environment)
        raise SystemExit(result.returncode)
