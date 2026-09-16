import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

from annie.moodle_calendar import (MAX_BYTES, MoodleConnection, MoodleError,
                                   fetch_preview, preview_calendar, validate_url)

URL = 'https://moodle.example/calendar/export_execute.php?authtoken=private-test-token'


def calendar(events=''):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + events + 'END:VCALENDAR\r\n').encode()


EVENT = ('BEGIN:VEVENT\r\nUID:test-1\r\nDTSTAMP:20260916T000000Z\r\n'
         'DTSTART:20260920T120000Z\r\nSUMMARY:Math quiz\r\nEND:VEVENT\r\n')


def response(body, status=200):
    result = Mock(status_code=status)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = [body[:20], body[20:]]
    return result


class MoodleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MoodleConnection(self.temp.name)

    def test_preview_unfolds_names_and_ignores_alarm_summary(self):
        event = EVENT.replace('SUMMARY:Math quiz\r\n',
            'SUMMARY:Math\\, quiz \'A\' and\r\n more\\nReview\r\n'
            'BEGIN:VALARM\r\nSUMMARY:Alarm text\r\nEND:VALARM\r\n')
        self.assertEqual(preview_calendar(calendar(event)),
                         {'count': 1, 'titles': ["Math, quiz 'A' andmore Review"]})

    def test_empty_calendar_is_valid_and_preview_is_bounded(self):
        self.assertEqual(preview_calendar(calendar()), {'count': 0, 'titles': []})
        result = preview_calendar(calendar(EVENT * 70))
        self.assertEqual(result['count'], 70)
        self.assertEqual(len(result['titles']), 50)

    def test_login_html_truncated_and_malformed_calendars_fail(self):
        for body in (b'<html>Sign in</html>', calendar(EVENT)[:-18],
                     calendar(EVENT).replace(b'END:VEVENT', b'END:VALARM'),
                     calendar(EVENT).replace(b'VERSION:2.0', b'VERSION:1.0'),
                     calendar(EVENT) + b'Unexpected trailing data', b'\xff'):
            with self.subTest(body=body), self.assertRaises(MoodleError):
                preview_calendar(body)

    def test_only_https_urls_without_embedded_passwords(self):
        self.assertEqual(validate_url(' ' + URL + ' '), URL)
        for url in ('password', 'file:///calendar.ics', 'http://moodle.example/export',
                    'https://user:password@moodle.example/export',
                    'https://moodle.example:wrong/export', 'https://moodle.example/#token',
                    'https://moodle.example/\nsecret'):
            with self.subTest(url=url), self.assertRaises(MoodleError):
                validate_url(url)

    def test_requests_do_not_redirect_or_inherit_login_and_errors_hide_url(self):
        with patch('annie.moodle_calendar.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value = response(calendar(EVENT))
            self.assertEqual(fetch_preview(URL)['count'], 1)
            self.assertFalse(session.trust_env)
            self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
            self.assertEqual(session.get.call_args.kwargs['timeout'], (5, 10))
            session.get.side_effect = requests.ConnectionError('Failure at ' + URL)
            with self.assertRaises(MoodleError) as error:
                fetch_preview(URL)
            self.assertNotIn('private-test-token', str(error.exception))

    def test_http_errors_redirects_and_size_limit(self):
        with patch('annie.moodle_calendar.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            for status in (302, 401, 403, 404, 500):
                session.get.return_value = response(b'', status)
                with self.subTest(status=status), self.assertRaises(MoodleError):
                    fetch_preview(URL)
            session.get.return_value = response(b'x' * (MAX_BYTES + 1))
            with self.assertRaises(MoodleError):
                fetch_preview(URL)

    def test_failed_verification_never_saves_and_failed_refresh_preserves_connection(self):
        preview = preview_calendar(calendar(EVENT))
        with patch('annie.moodle_calendar.fetch_preview', side_effect=MoodleError('Sign in')):
            with self.assertRaises(MoodleError):
                self.store.check(URL)
        self.assertFalse(self.store.path.exists())
        with patch('annie.moodle_calendar.fetch_preview', return_value=preview):
            self.store.check(URL)
        raw = self.store.path.read_bytes()
        self.assertNotIn(b'private-test-token', raw)
        with patch('annie.moodle_calendar.fetch_preview', side_effect=MoodleError('Offline')):
            with self.assertRaises(MoodleError):
                self.store.check('https://new.example/export')
        self.assertEqual(self.store.path.read_bytes(), raw)
        self.assertEqual(self.store.read()['url'], URL)
        with patch('annie.moodle_calendar.fetch_preview', return_value=preview) as fetch:
            self.store.check()
            fetch.assert_called_once_with(URL)
        self.store.disconnect()
        self.assertIsNone(self.store.read())

    def test_unreadable_saved_connection_has_safe_actionable_error(self):
        self.store.path.write_bytes(b'invalid')
        with self.assertRaisesRegex(MoodleError, 'reconnect'):
            self.store.read()


class MoodleDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_background_check_keeps_ui_alive_and_closes_only_after_completion(self):
        from annie.gui.moodle_setup import MoodleSetup
        from PyQt5.QtWidgets import QLineEdit
        with tempfile.TemporaryDirectory() as root:
            store = MoodleConnection(root)
            gate = threading.Event()
            with patch('annie.moodle_calendar.fetch_preview',
                       side_effect=lambda _: (gate.wait(3), preview_calendar(calendar(EVENT)))[1]):
                dialog = MoodleSetup(connection=store)
                self.assertEqual(dialog.url.echoMode(), QLineEdit.Password)
                dialog.show()
                dialog.url.setText(URL)
                dialog._check()
                self.assertIsNotNone(dialog._worker)
                dialog.reject()
                self.assertTrue(dialog.isVisible())
                self.app.processEvents()
                gate.set()
                deadline = time.monotonic() + 5
                while dialog._worker and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertIsNone(dialog._worker)
                self.assertEqual(dialog.preview.item(0).text(), 'Math quiz')
                self.assertEqual(dialog.url.text(), '')
                self.assertTrue(dialog.disconnect_button.isEnabled())
                dialog.reject()
                self.assertFalse(dialog.isVisible())
                dialog.deleteLater()
                self.app.processEvents()

    def test_opening_saved_preview_does_not_fetch_and_disconnect_clears_it(self):
        from annie.gui.moodle_setup import MoodleSetup
        with tempfile.TemporaryDirectory() as root:
            store = MoodleConnection(root)
            with patch('annie.moodle_calendar.fetch_preview', return_value=preview_calendar(calendar(EVENT))) as fetch:
                store.check(URL)
                fetch.reset_mock()
                dialog = MoodleSetup(connection=store)
                fetch.assert_not_called()
                self.assertIn('Saved preview', dialog.status.text())
                self.assertEqual(dialog.preview.count(), 1)
                dialog._disconnect()
                self.assertEqual(dialog.preview.count(), 0)
                self.assertFalse(store.path.exists())
                dialog.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
