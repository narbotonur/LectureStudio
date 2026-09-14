import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.export_studio_repository import export, audit


class StandaloneExportTests(unittest.TestCase):
    def test_export_is_complete_private_and_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = export(Path(temporary) / 'Studio', initialize_git=False)
            self.assertTrue((root / 'lecture-studio.standalone').is_file())
            self.assertTrue((root / 'native/macos/LectureAudioCapture.swift').is_file())
            self.assertTrue((root / 'packaging/START_HERE.md').is_file())
            self.assertFalse((root / 'annie/live_runtime.py').exists())
            self.assertFalse((root / 'models').exists())
            self.assertFalse((root / 'recordings').exists())
            self.assertNotIn('Jarvis', (root / 'run_studio.bat').read_text())
            profile = Path(temporary) / 'profile'
            environment = {**os.environ, 'ANNIE_DATA_DIR': str(profile), 'PYTHONDONTWRITEBYTECODE': '1'}
            environment.pop('PYTHONPATH', None)
            result = subprocess.run([sys.executable, '-B', '-c',
                'from annie.paths import PRIVATE_PROFILE, DATA_DIR; '
                'from annie import config; '
                'assert PRIVATE_PROFILE; assert not config.GEMINI_API_KEY; '
                'import annie.workstation_main; '
                'import sys; assert "annie.live_runtime" not in sys.modules'],
                cwd=root, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Without an override, the marker still prevents writes in source.
            environment.pop('ANNIE_DATA_DIR')
            result = subprocess.run([sys.executable, '-B', '-c',
                'from annie.paths import PRIVATE_PROFILE, DATA_DIR, APP_DIR; '
                'assert PRIVATE_PROFILE and DATA_DIR != APP_DIR'],
                cwd=root, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            with self.assertRaises(FileExistsError):
                export(root, initialize_git=False)

    def test_audit_rejects_missing_internal_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bad.py').write_text('import annie.missing_module')
            with self.assertRaisesRegex(ValueError, 'Missing Studio dependency'):
                audit(root)


if __name__ == '__main__':
    unittest.main()
