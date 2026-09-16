import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from annie.secure_storage import read_secret, write_secret
from tools.build_studio_release import stage, validate_source, DENIED


class DistributionTests(unittest.TestCase):
    def test_secret_roundtrip_is_not_plaintext_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'key.dpapi'
            write_secret(path, {'api_key': 'test-secret-123'})
            self.assertNotIn(b'test-secret-123', path.read_bytes())
            self.assertEqual(read_secret(path)['api_key'], 'test-secret-123')
            path.write_bytes(b'not encrypted')
            with self.assertRaises(ValueError):
                read_secret(path)

    def test_staging_allowlist_excludes_all_personal_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage(root)
            names = {path.name for path in root.rglob('*') if path.is_file()}
            self.assertFalse(names.intersection(DENIED))
            self.assertNotIn('recordings', {p.name for p in root.iterdir()})
            self.assertTrue((root / 'annie/gui/studio_setup.py').is_file())
            self.assertTrue((root / 'annie/gui/moodle_setup.py').is_file())
            self.assertTrue((root / 'annie/moodle_calendar.py').is_file())
            self.assertTrue((root / 'annie/gui/deadline_inbox.py').is_file())
            self.assertTrue((root / 'annie/deadlines.py').is_file())
            self.assertTrue((root / 'annie/gui/gpa_tracker.py').is_file())
            self.assertTrue((root / 'annie/gpa_tracker.py').is_file())
            self.assertFalse((root / 'annie/skills').exists())

    def test_build_refuses_embedded_keys_and_personal_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'unsafe.py'
            for source in ('GEMINI_API_KEY = "example-not-a-real-key"', 'LIBCAL_EMAIL = "person@example.com"'):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    validate_source(path)

    def test_private_profile_does_not_inherit_developer_settings_and_saves_encrypted(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = '''from pathlib import Path
from annie import config as cfg
from annie.secure_storage import read_secret
assert not cfg.GEMINI_API_KEY and not cfg.GROQ_API_KEY
assert not cfg.LIBCAL_EMAIL
cfg.GEMINI_API_KEY = 'test-key-not-real'
cfg.save_settings()
assert 'test-key-not-real' not in Path(cfg.SETTINGS_FILE).read_text()
assert read_secret(cfg.SECRETS_FILE)['gemini_api_key'] == 'test-key-not-real'
'''
            result = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'ANNIE_DATA_DIR': temporary},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_google_client_import_rejects_tokens_web_clients_and_other_endpoints(self):
        from annie.calendar_service import import_client
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'client.json'
            for value in ({'refresh_token': 'test'}, {'web': {}}, {'installed': {
                    'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'test',
                    'auth_uri': 'https://evil.example', 'token_uri': 'https://oauth2.googleapis.com/token'}}):
                path.write_text(json.dumps(value))
                with patch('annie.calendar_service.write_secret') as write:
                    with self.assertRaises(ValueError):
                        import_client(path)
                    write.assert_not_called()

    def test_packaged_worker_uses_console_worker_executable(self):
        from annie.whisper_service import WhisperService
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', 'C:/Annie/LectureStudio.exe'):
            service = WhisperService()
            self.assertEqual(Path(service.command[0]).name, 'LectureStudioWorker.exe')
            self.assertEqual(service.command[1], '--whisper-service')

    def test_missing_cuda_libraries_choose_cpu_before_inference(self):
        from annie.whisper_runtime import load_model
        import faster_whisper
        from unittest.mock import Mock
        fake_model = Mock()
        with patch('ctranslate2.get_cuda_device_count', return_value=1), \
                patch('annie.whisper_models.resolve_model', return_value='/cached/base'), \
                patch.object(faster_whisper, 'WhisperModel', fake_model), \
                patch('ctypes.WinDLL', side_effect=OSError('CUDA not installed')):
            model, device = load_model('base')
            self.assertEqual(device, 'CPU')
            self.assertEqual(fake_model.call_args.kwargs['device'], 'cpu')

    def test_frozen_checks_are_not_removed_by_python_optimization(self):
        from annie.release_check import check
        with self.assertRaises(RuntimeError):
            check(False, 'check remains active')


if __name__ == '__main__':
    unittest.main()
