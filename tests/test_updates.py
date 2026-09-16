import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PyQt5.QtCore import QLockFile, QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout

from annie.updates import (CHECK_INTERVAL, RELEASES_URL, UpdateService, check_release,
                           parse_release, read_cache, select_download, version_tuple)
from annie.version import VERSION

os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')


def release(tag='v99.0.0'):
    names = ['LectureStudio-macOS-arm64-UNNOTARIZED-test.dmg',
             'LectureStudio-macOS-x86_64-UNNOTARIZED-test.dmg',
             'LectureStudio-Windows-x64-test.zip']
    return {'tag_name': tag, 'html_url': f'{RELEASES_URL}/tag/{tag}',
            'body': '## Improvements\n- Better lecture recording',
            'assets': [{'name': name, 'browser_download_url': f'{RELEASES_URL}/download/{tag}/{name}'}
                       for name in names]}


def response(payload=None, status=200):
    result = Mock(status_code=status)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = [json.dumps(payload).encode()]
    return result


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'update-check.json'

    def test_versions_are_numeric_and_preview_releases_are_rejected(self):
        self.assertGreater(version_tuple('v0.10.0'), version_tuple('0.9.9'))
        for tag in ('main', 'v1.0.0-beta', '1.2', '1.01.0'):
            with self.assertRaises(ValueError):
                version_tuple(tag)
        for flag in ('draft', 'prerelease'):
            with self.assertRaises(ValueError):
                parse_release({**release(), flag: True})

    def test_download_uses_platform_architecture_and_only_repository_urls(self):
        data = parse_release(release())
        self.assertIn('-arm64-', select_download(data, 'darwin', 'arm64')['name'])
        self.assertIn('-x86_64-', select_download(data, 'darwin', 'x86_64')['name'])
        self.assertIn('-Windows-', select_download(data, 'win32', 'AMD64')['name'])
        self.assertIsNone(select_download(data, 'darwin', 'unknown'))
        malicious = release()
        malicious['assets'][0]['browser_download_url'] = 'https://example.com/installer.dmg'
        self.assertIsNone(select_download(parse_release(malicious), 'darwin', 'arm64'))
        with self.assertRaises(ValueError):
            parse_release({**release(), 'html_url': 'https://github.com/other/project/releases/tag/v99.0.0'})

    def test_daily_shared_cache_and_manual_bypass(self):
        with patch('annie.updates.requests.get', return_value=response(release())) as get:
            first = check_release(self.path, now=100000)
            self.assertEqual(check_release(self.path, now=100001), first)
            get.assert_called_once()
            check_release(self.path, manual=True, now=100002)
            self.assertEqual(get.call_count, 2)
            check_release(self.path, now=100002 + CHECK_INTERVAL)
            self.assertEqual(get.call_count, 3)

    def test_no_release_and_offline_are_different_and_keep_last_known_notes(self):
        with patch('annie.updates.requests.get', return_value=response(status=404)):
            self.assertIsNone(check_release(self.path)['release'])
        with patch('annie.updates.requests.get', return_value=response(release())):
            check_release(self.path, manual=True)
        with patch('annie.updates.requests.get', side_effect=requests.Timeout):
            failed = check_release(self.path, manual=True)
        self.assertTrue(failed['error'])
        self.assertEqual(failed['release']['body'], release()['body'])
        with patch('annie.updates.requests.get') as get:
            check_release(self.path)
            get.assert_not_called()

    def test_corrupt_or_foreign_cache_is_ignored_and_simultaneous_check_is_locked(self):
        self.path.write_text('{broken')
        self.assertEqual(read_cache(self.path), {})
        self.path.write_text(json.dumps({'checked_at': 100, 'release': {**release(), 'html_url': 'javascript:alert(1)'}}))
        self.assertEqual(read_cache(self.path), {})
        lock = QLockFile(str(self.path) + '.lock')
        self.assertTrue(lock.tryLock(0))
        try:
            with patch('annie.updates.requests.get') as get:
                self.assertIn('in progress', check_release(self.path)['error'])
                get.assert_not_called()
        finally:
            lock.unlock()

    def test_api_failures_and_oversized_payload_are_bounded(self):
        with patch('annie.updates.requests.get', return_value=response(status=429)):
            self.assertIn('limiting requests', check_release(self.path)['error'])
        too_large = response()
        too_large.iter_content.return_value = [b'x' * (1024 * 1024 + 1)]
        with patch('annie.updates.requests.get', return_value=too_large):
            self.assertIn('too large', check_release(self.path, manual=True)['error'])

    def test_background_check_keeps_event_loop_responsive_and_cache_reaches_studio(self):
        service = UpdateService(cache_path=self.path)
        studio = UpdateService(cache_path=self.path)
        beats = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(True))
        timer.start()

        def slow_request(*args, **kwargs):
            time.sleep(.15)
            return response(release())

        try:
            with patch('annie.updates.requests.get', side_effect=slow_request) as get:
                service.check()
                service.check(manual=True)
                until = time.monotonic() + 3
                while service.worker is not None and time.monotonic() < until:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertIsNone(service.worker)
                get.assert_called_once()
            self.assertGreater(len(beats), 3)
            studio.reload_cache()
            self.assertTrue(studio.available)
            self.assertEqual(studio.state['release'], service.state['release'])
        finally:
            timer.stop()
            service.stop()
            studio.stop()
            if service.worker:
                service.worker.wait(3000)
                self.app.processEvents()

    def test_ui_shows_notes_on_click_and_does_not_render_release_html(self):
        from annie.gui.studio_updates import UpdatePanel
        parent = QWidget()
        layout = QVBoxLayout(parent)
        service = UpdateService(cache_path=self.path)
        with patch('annie.gui.studio_updates.UpdateService', return_value=service):
            panel = UpdatePanel(parent)
        layout.addWidget(panel)
        try:
            self.assertTrue(panel.isHidden())
            data = parse_release(release())
            data['body'] = '<img src="https://example.com/tracker">\nFixed audio'
            service.state = {'release': data}
            service.changed.emit()
            self.assertFalse(panel.isHidden())
            with patch.object(service, 'check') as check:
                panel.check_button.click()
                check.assert_called_once_with(manual=True)
            self.assertEqual(panel.dialog.notes.toPlainText(), data['body'])
            self.assertIn(VERSION, panel.dialog.summary.text())
            service.state = {'release': parse_release(release('v' + VERSION))}
            service.changed.emit()
            self.assertTrue(panel.isHidden())
            self.assertEqual(panel.dialog.heading.text(), "You're up to date")
        finally:
            service.stop()
            if panel.dialog:
                panel.dialog.close()
            parent.close()
