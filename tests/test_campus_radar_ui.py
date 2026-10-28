"""Recorded coursework changes in native UI; no browser or account access."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication

from annie.gui.campus_radar import RadarPage, read_captured_snapshot


def snapshot():
    return {'source': {'source_id': 'math-assignment', 'kind': 'webwork',
        'name': 'MATH assignment', 'url': 'https://course.example.test/webwork/course/set1/',
        'scope': 'assignment'}, 'checked_at': '2026-10-28T09:00:00+05:00', 'complete': True,
        'items': [{'external_id': 'set1', 'title': 'Problem set 1', 'course': 'MATH 251',
            'due_at': '2026-11-03T17:00:00+05:00', 'raw_due_text': 'Due November 3 at 17:00',
            'source_url': 'https://course.example.test/webwork/course/set1/', 'status': 'open'}]}


def captured(root, data):
    path = Path(root) / 'captured.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


class CampusRadarUiTests(unittest.TestCase):
    def test_open_baseline_assignment_is_visible_before_closed_history(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            closed = copy.deepcopy(data['items'][0])
            closed.update(external_id='old-set', title='Closed history', status='closed', due_at=None, raw_due_text='')
            data['items'].append(closed)
            page.store.import_snapshot(data)
            page.reload()
            self.assertEqual(page.events_list.item(0).data(Qt.UserRole)['new_status'], 'open')
            page.close()

    def test_disabled_windows_messages_are_reported_and_not_claimed_sent(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            page.tray = object()
            with patch('annie.gui.campus_radar.QSystemTrayIcon.isSystemTrayAvailable', return_value=True), \
                 patch('annie.gui.campus_radar.QSystemTrayIcon.supportsMessages', return_value=False):
                self.assertFalse(page._notify('Coursework change', 'Synthetic only'))
            self.assertIn('disabled or unavailable', page.connection_status.text())
            self.assertIn('delivery will retry', page.connection_status.text())
            page.tray = None
            page.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_import_first_observation_and_mark_reviewed(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            changed = QSignalSpy(page.changes_updated)
            self.assertTrue(page.import_snapshot(captured(root, snapshot())), page.status.text())
            self.assertIn('Manually captured snapshot', page.status.text())
            self.assertIn('did not check the website', page.status.text())
            self.assertEqual(page.events_list.count(), 1)
            self.assertIn('first local observation', page.details.toPlainText())
            self.assertIn('not proof', page.details.toPlainText())
            page.mark_reviewed()
            self.assertEqual(page.events_list.count(), 0)
            self.assertEqual(len(changed), 2)
            self.assertEqual(page.store.items()[0]['status'], 'open')
            page.unread_only.setChecked(False)
            self.assertEqual(page.events_list.count(), 1)
            self.assertFalse(page.mark_button.isEnabled())
            page.close()

    def test_due_change_displays_old_new_and_source_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            page.import_snapshot(captured(root, data))
            data['checked_at'] = '2026-10-28T10:00:00+05:00'
            data['items'][0]['due_at'] = '2026-11-06T17:00:00+05:00'
            data['items'][0]['raw_due_text'] = 'Updated due date: November 6 at 17:00'
            self.assertTrue(page.import_snapshot(captured(root, data)), page.status.text())
            changed = next(i for i in range(page.events_list.count())
                           if page.events_list.item(i).data(Qt.UserRole)['type'] == 'due_changed')
            page.events_list.setCurrentRow(changed)
            details = page.details.toPlainText()
            self.assertIn('03 Nov 2026 17:00', details)
            self.assertIn('06 Nov 2026 17:00', details)
            self.assertIn('CAPTURED SOURCE EVIDENCE', details)
            self.assertIn('November 6', details)
            page.close()

    def test_assignment_scope_never_claims_whole_course_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            page.import_snapshot(captured(root, snapshot()))
            self.assertEqual(page.sources_table.item(0, 1).text(), 'Assignment only')
            page.sources_table.selectRow(0)
            self.assertIn('does not cover the whole course', page.details.toPlainText())
            self.assertIn('Last successful capture:', page.details.toPlainText())
            page.close()

    def test_partial_capture_reports_unknown_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            data['complete'] = False
            page.import_snapshot(captured(root, data))
            self.assertIn('partial', page.status.text())
            self.assertIn('unknown', page.status.text())
            page.sources_table.selectRow(0)
            self.assertIn('incomplete or unverified', page.details.toPlainText())
            page.close()

    def test_source_error_is_not_reported_as_no_homework(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            source = {**snapshot()['source'], 'state': 'error',
                'last_success_at': '2026-10-27T09:00:00+05:00',
                'last_attempt_at': '2026-10-28T10:00:00+05:00',
                'last_error': 'Login session expired. <b>This is source text</b>'}
            with patch.object(page.store, 'sources', return_value=[source]):
                page.reload()
                self.assertIn('failed', page.status.text())
                self.assertIn('unknown', page.status.text())
                page.sources_table.selectRow(0)
                self.assertIn(source['last_error'], page.details.toPlainText())
                self.assertEqual(page.status.textFormat(), Qt.PlainText)
                self.assertEqual(page.coverage_label.textFormat(), Qt.PlainText)
                self.assertNotIn('no new homework', page.status.text().casefold())
            page.close()

    def test_malformed_item_preflight_does_not_register_source(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            data['items'].append({**data['items'][0], 'external_id': 'set2', 'due_at': '2026-11-03T17:00'})
            self.assertFalse(page.import_snapshot(captured(root, data)))
            self.assertEqual(page.store.sources(), [])
            self.assertEqual(page.store.items(), [])
            page.close()

    def test_credential_url_and_wrong_types_fail_before_storage(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            data['source']['url'] += '?sesskey=private-value'
            self.assertFalse(page.import_snapshot(captured(root, data)))
            self.assertNotIn('private-value', page.status.text())
            malformed = snapshot()
            malformed['source']['kind'] = {'unexpected': 'object'}
            self.assertFalse(page.import_snapshot(captured(root, malformed)))
            self.assertEqual(page.store.sources(), [])
            page.close()

    def test_open_source_is_explicit_https_action(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            page.import_snapshot(captured(root, snapshot()))
            with patch('annie.gui.campus_radar.QDesktopServices.openUrl', return_value=True) as opening:
                page.open_source()
                self.assertEqual(opening.call_count, 1)
                self.assertEqual(opening.call_args[0][0].scheme(), 'https')
            page.close()

    def test_snapshot_size_and_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'capture.json'
            path.write_text(' ' * 1_000_001, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '1 MB'):
                read_captured_snapshot(path)
            path.write_text('{"source":{},"source":{}}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                read_captured_snapshot(path)

    def test_closing_time_is_distinct_from_missing_due_date(self):
        with tempfile.TemporaryDirectory() as root:
            page = RadarPage(root=root)
            data = snapshot()
            data['items'][0].update(due_at=None, raw_due_text='',
                closes_at='2026-11-03T17:00:00+05:00', raw_close_text='Set closes on November 3 at 17:00')
            self.assertTrue(page.import_snapshot(captured(root, data)), page.status.text())
            self.assertIn('Closes:', page.events_list.item(0).text())
            self.assertIn('Due date: not supplied', page.details.toPlainText())
            self.assertIn('closing time is not treated as a due date', page.details.toPlainText())
            self.assertIn('Set closes on November 3', page.details.toPlainText())
            data['checked_at'] = '2026-10-28T10:00:00+05:00'
            data['items'][0].update(closes_at='2026-11-06T17:00:00+05:00',
                                    raw_close_text='Set closes on November 6 at 17:00')
            self.assertTrue(page.import_snapshot(captured(root, data)), page.status.text())
            changed = next(i for i in range(page.events_list.count())
                           if page.events_list.item(i).data(Qt.UserRole)['type'] == 'closes_changed')
            page.events_list.setCurrentRow(changed)
            self.assertIn('Closing time changed', page.details.toPlainText())
            self.assertIn('03 Nov', page.details.toPlainText())
            self.assertIn('06 Nov', page.details.toPlainText())
            self.assertIsNone(page.store.items()[0]['due_at'])
            page.close()
