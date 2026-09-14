import os
import subprocess
import sys
import time
import types
import unittest
import uuid
from unittest.mock import Mock, patch

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie.studio_router import StudioRouter


def fake_studio():
    studio = types.SimpleNamespace(active=False, starts=0, shows=0, worker=None, tab=0)
    studio.audio_source_picker = types.SimpleNamespace(findData=lambda _: 0, setCurrentIndex=lambda _: None)
    studio.subject_input = types.SimpleNamespace(text=lambda: '', setText=lambda _: None)
    studio.is_active = lambda: studio.active
    studio.isMinimized = lambda: False
    studio.show = lambda: setattr(studio, 'shows', studio.shows + 1)
    studio.raise_ = lambda: None
    studio.activateWindow = lambda: None
    studio._switch_tab = lambda tab: setattr(studio, 'tab', tab)

    def start():
        studio.active = True
        studio.starts += 1
    studio._toggle_recording = start
    return studio


class StudioRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.name = 'annie-test-' + uuid.uuid4().hex
        self.studio = fake_studio()
        self.created = []

        def factory():
            self.created.append(True)
            return self.studio
        self.owner = StudioRouter(self.app, factory, self.name)
        self.routers = [self.owner]

    def tearDown(self):
        for router in self.routers:
            router.close()
            router.deleteLater()
        self.app.processEvents()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_simultaneous_launches_have_one_owner_and_repeated_start_is_idempotent(self):
        remote_creations = []
        remote = StudioRouter(self.app, lambda: remote_creations.append(True) or fake_studio(), self.name)
        self.routers.append(remote)
        self.owner.request('show')
        remote.request('start', context='MATH 251')
        self.wait_until(lambda: self.owner._studio is not None or remote._studio is not None)
        self.wait_until(lambda: self.owner.is_recording() or remote.is_recording())
        self.assertEqual(len(self.created) + len(remote_creations), 1)
        owned = self.owner._studio or remote._studio
        remote.request('start')
        self.owner.request('start')
        QTest.qWait(200)
        self.assertEqual(owned.starts, 1)

    def test_busy_owner_does_not_create_another_window_or_restart_worker(self):
        self.owner.request('show')
        self.wait_until(lambda: bool(self.created))
        self.studio.worker = types.SimpleNamespace(isRunning=lambda: True)
        errors = []
        self.owner.error.connect(errors.append)
        self.owner.request('start')
        self.assertEqual(self.studio.starts, 0)
        self.assertEqual(len(self.created), 1)
        self.assertTrue(errors)

    def test_watcher_launches_fresh_owner_without_creating_local_ui(self):
        launch = Mock(side_effect=lambda: self.owner.request('show'))
        forbidden = Mock(side_effect=AssertionError('Watcher imported the UI'))
        watcher = StudioRouter(self.app, forbidden, self.name, launch_owner=launch)
        self.routers.append(watcher)
        watcher.request('start')
        self.wait_until(lambda: self.studio.starts == 1)
        launch.assert_called_once()
        forbidden.assert_not_called()
        self.assertFalse(watcher._server.isListening())

    def test_watcher_reuses_open_owner_without_launching_process(self):
        self.owner.request('show')
        self.wait_until(lambda: bool(self.created))
        launch = Mock()
        watcher = StudioRouter(self.app, Mock(), self.name, launch_owner=launch)
        self.routers.append(watcher)
        watcher.request('start')
        self.wait_until(lambda: self.studio.starts == 1)
        launch.assert_not_called()

    def test_idle_status_never_launches_a_window(self):
        launch = Mock()
        watcher = StudioRouter(self.app, Mock(), self.name, launch_owner=launch)
        self.routers.append(watcher)
        watcher._poll_status()
        QTest.qWait(100)
        launch.assert_not_called()
        self.assertFalse(watcher._server.isListening())

    def test_launch_error_does_not_fall_back_to_watcher_ui(self):
        forbidden = Mock()
        watcher = StudioRouter(self.app, forbidden, self.name,
                               launch_owner=Mock(side_effect=OSError('missing executable')))
        self.routers.append(watcher)
        errors = []
        watcher.error.connect(errors.append)
        watcher.request('show')
        self.wait_until(lambda: bool(errors))
        forbidden.assert_not_called()
        self.assertIn('missing executable', errors[0])

    def test_legacy_watcher_blocks_launch_before_a_process_is_spawned(self):
        launch, factory = Mock(), Mock()
        watcher = StudioRouter(self.app, factory, self.name, launch_owner=launch)
        self.routers.append(watcher)
        errors = []
        watcher.error.connect(errors.append)
        with patch.object(watcher, '_legacy_launch_error', return_value='Quit watcher first'):
            watcher.request('start')
            self.wait_until(lambda: bool(errors))
        launch.assert_not_called()
        factory.assert_not_called()
        self.assertFalse(watcher._server.isListening())

    def test_existing_owner_is_used_without_legacy_scan_or_second_start(self):
        self.owner.request('show')
        self.wait_until(lambda: bool(self.created))
        launch, factory = Mock(), Mock()
        watcher = StudioRouter(self.app, factory, self.name, launch_owner=launch)
        self.routers.append(watcher)
        with patch.object(watcher, '_legacy_launch_error', side_effect=AssertionError('Unnecessary scan')):
            watcher.request('start')
            self.wait_until(lambda: self.studio.starts == 1)
            watcher.request('start')
            QTest.qWait(150)
        self.assertEqual(self.studio.starts, 1)
        self.assertEqual(len(self.created), 1)
        launch.assert_not_called()
        factory.assert_not_called()

    def test_outdated_watchers_are_scoped_to_user_installation_and_start_time(self):
        from pathlib import Path
        from annie import startup
        root = str(Path(startup.__file__).resolve().parents[1])

        def process(pid, cwd=root, user='test-user', started=1, args=None):
            result = Mock()
            result.info = dict(pid=pid, name='pythonw.exe')
            result.username.return_value = user
            result.create_time.return_value = started
            result.cmdline.return_value = args or ['pythonw', '-m', 'annie.workstation_main', '--watch']
            result.cwd.return_value = cwd
            return result

        processes = [process(101), process(102, cwd=str(Path(root).parent)),
                     process(103, user='someone-else'), process(104, started=float('inf')),
                     process(105, args=['pythonw', 'something_else.py', '--watch'])]
        with patch('psutil.Process') as current, patch('psutil.process_iter', return_value=processes), \
             patch.object(sys, 'frozen', False, create=True):
            current.return_value.username.return_value = 'test-user'
            self.assertEqual(startup.outdated_watcher_pids(), [101])

    def test_frozen_release_does_not_use_source_update_detection(self):
        from annie.startup import outdated_watcher_pids
        with patch.object(sys, 'frozen', True, create=True), patch('psutil.process_iter') as scan:
            self.assertEqual(outdated_watcher_pids(), [])
            scan.assert_not_called()

    def test_process_launcher_is_quiet_absolute_and_deduplicated(self):
        from pathlib import Path
        from annie.startup import StudioLauncher
        with patch('annie.startup.subprocess.Popen') as popen:
            popen.return_value.poll.return_value = None
            launcher = StudioLauncher()
            launcher()
            launcher()
            popen.assert_called_once()
            args = popen.call_args.args[0]
            self.assertTrue(Path(args[1]).is_absolute())
            self.assertEqual(Path(args[1]).name, 'lecture_studio_entry.py')
            self.assertNotIn('--watch', args)
            popen.return_value.poll.return_value = 0
            launcher()
            self.assertEqual(popen.call_count, 2)

    def test_packaged_launcher_uses_current_executable(self):
        from annie.startup import studio_arguments, startup_arguments
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', 'C:/Studio/LectureStudio.exe'):
            self.assertEqual(studio_arguments(), ['C:/Studio/LectureStudio.exe'])
            self.assertEqual(startup_arguments(), ['C:/Studio/LectureStudio.exe', '--watch'])

    def test_watcher_entry_does_not_import_studio_ui(self):
        result = subprocess.run(
            [sys.executable, '-c', "import sys; import annie.workstation_main; "
             "assert 'annie.gui.meeting_window' not in sys.modules"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_command_from_separate_process_reaches_existing_studio(self):
        self.owner.request('show')
        self.wait_until(lambda: bool(self.created))
        code = '''
import sys
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from annie.studio_router import StudioRouter
app = QApplication([])
def forbidden():
    raise RuntimeError('Duplicate studio creation')
r = StudioRouter(app, forbidden, sys.argv[1])
r.delivered.connect(lambda action: app.exit(0))
r.error.connect(lambda error: (print(error), app.exit(2)))
QTimer.singleShot(0, lambda: r.request('start', context='CSCI 235'))
QTimer.singleShot(5000, lambda: app.exit(3))
sys.exit(app.exec_())
'''
        child = subprocess.Popen([sys.executable, '-c', code, self.name],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            self.wait_until(lambda: child.poll() is not None)
            stdout, stderr = child.communicate(timeout=1)
            self.assertEqual(child.returncode, 0, (stdout, stderr))
            self.assertEqual(self.studio.starts, 1)
            self.assertEqual(len(self.created), 1)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
