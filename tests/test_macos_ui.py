"""Studio feature/UX contracts, without loading the Windows-only Annie assistant."""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')
from PyQt5.QtCore import QPoint, QPointF, Qt, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication
from annie.gui.meeting_window import MeetingWindow
from annie.gui.week_calendar import WeekGrid


class MacStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_all_tabs_and_audio_sources_exist(self):
        with tempfile.TemporaryDirectory() as temporary, patch('annie.config.DATA_DIR', temporary), \
             patch('annie.calendar_service.is_connected', return_value=False):
            window = MeetingWindow()
            window.setAttribute(Qt.WA_DontShowOnScreen)
            window.show()
            try:
                self.assertEqual(window.stack.count(), 9)
                for index in range(9):
                    window._switch_tab(index)
                    self.app.processEvents()
                    self.assertEqual(window.stack.currentIndex(), index)
                for source in ('default', 'system', 'dual', 'phone'):
                    self.assertGreaterEqual(window.audio_source_picker.findData(source), 0)
                self.assertTrue(window.study_page.store is not None)
            finally:
                window.close()
                self.app.processEvents()

    def test_trackpad_pixel_scrolling_preserves_exact_displacement(self):
        grid = WeekGrid()
        grid.resize(800, 500)
        grid.setAttribute(Qt.WA_DontShowOnScreen)
        grid.show()
        self.app.processEvents()
        try:
            grid.verticalScrollBar().setValue(200)
            event = QWheelEvent(QPointF(50, 100), QPointF(50, 100), QPoint(0, 37),
                                QPoint(0, 0), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
            grid.wheelEvent(event)
            self.assertEqual(grid.verticalScrollBar().value(), 163)
            self.assertTrue(event.isAccepted())
        finally:
            grid.close()

    def test_activation_policy_switches_between_studio_and_silent_watcher(self):
        from annie.macos_support import set_studio_visible
        fake = Mock()
        fake.NSApplicationActivationPolicyRegular = 0
        fake.NSApplicationActivationPolicyAccessory = 1
        with patch.dict(sys.modules, {'AppKit': fake}):
            set_studio_visible(False)
            fake.NSApplication.sharedApplication().setActivationPolicy_.assert_called_with(1)
            set_studio_visible(True)
            fake.NSApplication.sharedApplication().setActivationPolicy_.assert_called_with(0)

    def test_meeting_scan_keeps_gui_responsive_and_stop_discards_late_results(self):
        from annie import meeting_prompt
        controller = meeting_prompt.MeetingPromptController(self.app, Mock())
        beats = []
        scan_started = threading.Event()
        release_scan = threading.Event()
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(True))

        def slow_scan():
            scan_started.set()
            release_scan.wait(1)
            return meeting_prompt.ConferenceWindow('Zoom', 'Zoom Meeting', 'zoom.us', 1)

        with patch.object(meeting_prompt, 'detect_conference_window', side_effect=slow_scan), \
             patch.object(meeting_prompt, '_release_monitor_mutex'):
            try:
                controller._started = True
                timer.start(10)
                controller._check_conference()
                deadline = time.monotonic() + 1
                while (not scan_started.is_set() or not beats) and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertTrue(beats)
                self.assertTrue(controller.has_running_job())
                controller.stop()
                release_scan.set()
                QTest.qWait(180)
                self.assertFalse(controller.prompt.isVisible())
                self.assertFalse(controller.has_running_job())
            finally:
                release_scan.set()
                timer.stop()
                controller.stop()
                if controller._conference_worker:
                    controller._conference_worker.wait(1000)
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
