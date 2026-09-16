"""Portable contract tests. Native Mac smoke tests remain a separate gate."""
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from annie import secure_storage, startup
from annie.platform_support import user_data_dir, audio_sources, validate_audio_source, worker_command


class PlatformTests(unittest.TestCase):
    def test_mac_data_is_in_application_support(self):
        home = Path('/Users/Student')
        self.assertEqual(user_data_dir('darwin', home, {}), home / 'Library/Application Support/Annie/LectureStudio')

    def test_windows_data_location_is_preserved(self):
        self.assertEqual(user_data_dir('win32', '/unused', {'LOCALAPPDATA': '/profile/Local'}),
                         Path('/profile/Local/Annie/LectureStudio'))

    def test_worker_names_and_source_command(self):
        self.assertEqual(Path(worker_command('/Applications/Lecture Studio.app/Contents/MacOS/LectureStudio', True, 'darwin')[0]).name,
                         'LectureStudioWorker')
        self.assertEqual(Path(worker_command('C:/Studio/LectureStudio.exe', True, 'win32')[0]).name,
                         'LectureStudioWorker.exe')
        self.assertEqual(worker_command('/venv/bin/python', False, 'darwin'),
                         ['/venv/bin/python', '-u', '-m', 'annie.whisper_worker', '--service'])

    def test_mac_audio_is_explicit_and_windows_options_unchanged(self):
        self.assertEqual([value for _, value in audio_sources('darwin')], ['default', 'system', 'dual', 'phone'])
        self.assertEqual(len(audio_sources('win32')), 4)
        for source in ('system', 'dual', 'loopback', 'computer', 'mix'):
            validate_audio_source(source, 'darwin')
        for source in ('invalid', '-1'):
            with self.assertRaises(ValueError):
                validate_audio_source(source, 'darwin')
        for source in ('default', 'phone', '3'):
            validate_audio_source(source, 'darwin')


class MemoryKeychain:
    def __init__(self):
        self.items = {}

    def get_password(self, service, account):
        return self.items.get((service, account))

    def set_password(self, service, account, value):
        self.items[service, account] = value

    def delete_password(self, service, account):
        del self.items[service, account]


class KeychainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'accounts.dpapi'
        self.backend = MemoryKeychain()
        platform_patch = patch.object(sys, 'platform', 'darwin')
        backend_patch = patch.object(secure_storage, '_keychain', return_value=self.backend)
        platform_patch.start()
        backend_patch.start()
        self.addCleanup(platform_patch.stop)
        self.addCleanup(backend_patch.stop)

    def test_roundtrip_writes_only_reference_and_delete_cleans_keychain(self):
        value = {'key': 'dummy-secret-not-real', 'unicode': '\u041f\u0440\u0438\u0432\u0435\u0442'}
        secure_storage.write_secret(self.path, value)
        self.assertNotIn(b'dummy-secret', self.path.read_bytes())
        self.assertEqual(secure_storage.read_secret(self.path), value)
        secure_storage.delete_secret(self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.backend.items)

    def test_profiles_have_distinct_keychain_items(self):
        other = self.path.parent / 'other/accounts.dpapi'
        secure_storage.write_secret(self.path, {'key': 'first'})
        secure_storage.write_secret(other, {'key': 'second'})
        self.assertEqual(len(self.backend.items), 2)
        self.assertEqual(secure_storage.read_secret(self.path), {'key': 'first'})

    def test_corruption_and_moved_references_are_refused(self):
        secure_storage.write_secret(self.path, {'key': 'test'})
        other = self.path.with_name('copied.dpapi')
        other.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError):
            secure_storage.read_secret(other)
        self.path.write_bytes(b'not encrypted')
        with self.assertRaises(ValueError):
            secure_storage.read_secret(self.path)
        with self.assertRaises(ValueError):
            secure_storage.delete_secret(self.path)

    def test_missing_keychain_item_is_not_treated_as_empty_login(self):
        secure_storage.write_secret(self.path, {'key': 'test'})
        self.backend.items.clear()
        with self.assertRaisesRegex(ValueError, 'not found'):
            secure_storage.read_secret(self.path)

    def test_locked_keychain_never_falls_back_to_disk(self):
        with patch.object(secure_storage, '_keychain', side_effect=RuntimeError('locked')):
            with self.assertRaisesRegex(RuntimeError, 'locked'):
                secure_storage.write_secret(self.path, {'key': 'test'})
        self.assertFalse(self.path.exists())

    def test_reference_failure_rolls_back_new_or_existing_keychain_item(self):
        with patch.object(secure_storage, 'atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                secure_storage.write_secret(self.path, {'key': 'new'})
        self.assertFalse(self.backend.items)
        secure_storage.write_secret(self.path, {'key': 'old'})
        with patch.object(secure_storage, 'atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                secure_storage.write_secret(self.path, {'key': 'replacement'})
        self.assertEqual(secure_storage.read_secret(self.path), {'key': 'old'})


class LoginTests(unittest.TestCase):
    def test_launchagent_roundtrip_preserves_spaces_without_shell_or_immediate_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'watcher.plist'
            with patch.object(sys, 'platform', 'darwin'), \
                 patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', '/Applications/Lecture Studio.app/Contents/MacOS/LectureStudio'), \
                 patch.object(startup, '_launch_agent_path', return_value=path), \
                 patch('subprocess.run') as run:
                self.assertFalse(startup.enabled())
                startup.set_enabled(True)
                self.assertTrue(startup.enabled())
                data = plistlib.loads(path.read_bytes())
                self.assertEqual(data['ProgramArguments'], [sys.executable, '--watch'])
                self.assertNotIn('KeepAlive', data)
                self.assertTrue(data['RunAtLoad'])
                run.assert_not_called()
                startup.set_enabled(False)
                self.assertFalse(path.exists())

    def test_different_installation_or_malformed_agent_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'watcher.plist'
            with patch.object(sys, 'platform', 'darwin'), patch.object(startup, '_launch_agent_path', return_value=path):
                for payload in (plistlib.dumps({'Label': startup.MAC_LABEL, 'ProgramArguments': ['/other/app', '--watch']}), b'broken plist'):
                    path.write_bytes(payload)
                    self.assertFalse(startup.enabled())
                    startup.set_enabled(False)
                    self.assertEqual(path.read_bytes(), payload)
                    with self.assertRaises(RuntimeError):
                        startup.set_enabled(True)


class MacWindowTests(unittest.TestCase):
    def test_mac_prompt_offers_only_supported_audio(self):
        from PyQt5.QtWidgets import QApplication
        from annie.meeting_prompt import AudioSourceButton
        app = QApplication.instance() or QApplication([])
        with patch.object(sys, 'platform', 'darwin'):
            button = AudioSourceButton()
        self.assertEqual(button.currentData(), 'default')
        self.assertGreaterEqual(button.findData('system'), 0)
        self.assertGreaterEqual(button.findData('dual'), 0)
        button.setCurrentIndex(button.findData('phone'))
        self.assertEqual(button.currentData(), 'phone')
        button.deleteLater()
        app.processEvents()

    def test_non_windows_watcher_lock_excludes_other_processes(self):
        from PyQt5.QtCore import QLockFile
        from annie import meeting_prompt
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / 'lecture-watcher.lock')
            lock = QLockFile(path)
            self.assertTrue(lock.tryLock(0))
            code = ('from PyQt5.QtCore import QLockFile; import sys; '
                    'lock = QLockFile(sys.argv[1]); '
                    'sys.exit(1 if lock.tryLock(0) else 0)')
            try:
                result = subprocess.run([sys.executable, '-c', code, path], capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                with patch.object(sys, 'platform', 'darwin'), \
                     patch.object(meeting_prompt.cfg, 'DATA_DIR', temporary), \
                     patch.object(meeting_prompt, '_monitor_mutex', None):
                    self.assertFalse(meeting_prompt._acquire_monitor_mutex())
                    lock.unlock()
                    self.assertTrue(meeting_prompt._acquire_monitor_mutex())
                    self.assertFalse(meeting_prompt._acquire_monitor_mutex())
                    meeting_prompt._release_monitor_mutex()
                    self.assertTrue(lock.tryLock(0))
            finally:
                lock.unlock()

    def test_permission_denied_scan_never_requests_permission(self):
        from annie.macos_support import visible_windows
        quartz = Mock()
        quartz.CGPreflightScreenCaptureAccess.return_value = False
        with patch.dict(sys.modules, {'Quartz': quartz}):
            self.assertEqual(visible_windows(), [])
        quartz.CGRequestScreenCaptureAccess.assert_not_called()
        quartz.CGWindowListCopyWindowInfo.assert_not_called()

    def test_only_ordinary_visible_window_metadata_is_returned(self):
        from annie.macos_support import visible_windows
        quartz = types.SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True,
            kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=2, kCGNullWindowID=0,
            kCGWindowLayer='layer', kCGWindowName='title', kCGWindowOwnerName='owner', kCGWindowOwnerPID='pid',
            CGWindowListCopyWindowInfo=Mock(return_value=[
                {'layer': 0, 'title': 'Zoom Meeting', 'owner': 'zoom.us', 'pid': 12},
                {'layer': 4, 'title': 'Overlay', 'owner': 'Other', 'pid': 13},
                {'layer': 0, 'owner': 'No title', 'pid': 14}]))
        with patch.dict(sys.modules, {'Quartz': quartz}):
            self.assertEqual(visible_windows(), [('Zoom Meeting', 'zoom.us', 12)])

    def test_mac_process_names_match_conferences_not_generic_teams(self):
        from annie.meeting_prompt import detect_conference_window
        for title, process, expected in (
            ('Zoom Meeting', 'zoom.us', 'Zoom'),
            ('Math meeting | Microsoft Teams', 'Microsoft Teams', 'Microsoft Teams'),
            ('abc-defg-hij - Google Meet', 'Safari', 'Google Meet')):
            self.assertEqual(detect_conference_window([(title, process, 1)]).provider, expected)
        self.assertIsNone(detect_conference_window([('Chat | Microsoft Teams', 'Microsoft Teams', 1)]))
        self.assertIsNone(detect_conference_window([('MATH 251 Lecture', 'Microsoft Teams', 1)]))
        meeting = detect_conference_window([('MATH 251 Lecture', 'Microsoft Teams', 1)], {'Microsoft Teams'})
        self.assertEqual(meeting.provider, 'Microsoft Teams')
        self.assertEqual(detect_conference_window([('Meet - abc-defg-hij', 'Safari', 1)]).provider, 'Google Meet')


class BundleTests(unittest.TestCase):
    def test_notarization_requires_explicit_accepted_status(self):
        from tools.build_studio_macos import submit_notarization
        for status, accepted in (('Accepted', True), ('Invalid', False), ('In Progress', False)):
            result = types.SimpleNamespace(stdout=json.dumps({'status': status, 'id': 'test-job'}))
            with patch('tools.build_studio_macos.subprocess.run', return_value=result) as run:
                if accepted:
                    submit_notarization(Path('/tmp/test-app.zip'), 'test-profile')
                else:
                    with self.assertRaises(RuntimeError):
                        submit_notarization(Path('/tmp/test-app.zip'), 'test-profile')
                self.assertIn('--keychain-profile', run.call_args.args[0])

    def test_mac_spec_bundles_audio_executable_and_preserves_quiet_launch(self):
        root = Path(__file__).resolve().parents[1]
        code = (root / 'packaging/lecture_studio_macos.spec').read_text(encoding='utf-8')
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_all = lambda _: ([], [], [])
        hooks.collect_dynamic_libs = lambda _: []
        hooks.collect_data_files = Mock(return_value=[])
        hooks.copy_metadata = lambda _: []
        analysis = types.SimpleNamespace(pure=[], scripts=[], datas=[],
            binaries=[('LectureAudioCapture', '/test/helper', 'BINARY')])
        exes = []

        def exe(*args, **kwargs):
            value = types.SimpleNamespace(**kwargs)
            exes.append(value)
            return value

        bundle = Mock()
        with patch.object(sys, 'platform', 'darwin'), patch.object(Path, 'is_file', return_value=True), \
             patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks}):
            exec(compile(code, 'lecture_studio_macos.spec', 'exec'), {
                'SPECPATH': str(root / 'packaging'), 'Analysis': lambda *a, **kw: analysis,
                'PYZ': lambda *a: None, 'EXE': exe, 'COLLECT': lambda *a, **kw: object(), 'BUNDLE': bundle})
        self.assertEqual(analysis.binaries[0][2], 'EXECUTABLE')
        self.assertFalse(exes[0].console)
        self.assertTrue(exes[1].console)
        self.assertIs(bundle.call_args.args[-1], exes[0])
        plist = bundle.call_args.kwargs['info_plist']
        self.assertTrue(plist['LSUIElement'])
        self.assertIn('NSMicrophoneUsageDescription', plist)
        hooks.collect_data_files.assert_called_with('tzdata')

    def test_source_kit_contains_mac_backend_build_files_and_no_personal_data(self):
        from tools.build_studio_macos import stage_macos
        from tools.build_studio_release import DENIED
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage_macos(root)
            names = {item.name for item in root.rglob('*') if item.is_file()}
            self.assertFalse(set(DENIED).intersection(names))
            for name in ('macos_support.py', 'platform_support.py', 'lecture_studio_macos.spec', 'requirements-macos.txt', 'MACOS.md'):
                self.assertIn(name, names)
            self.assertNotIn('annie_settings.json', names)

    def test_intel_mac_uses_portable_cryptography_wheel(self):
        root = Path(__file__).resolve().parents[1]
        requirements = (root / 'packaging/requirements-macos.txt').read_text(encoding='utf-8')
        self.assertIn("cryptography==46.0.7; sys_platform == 'darwin'", requirements)


if __name__ == '__main__':
    unittest.main()
