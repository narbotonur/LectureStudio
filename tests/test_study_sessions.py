import datetime as dt
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from annie.study_sessions import StudyStore, TZ, duration_text
from annie.gui.study_timer import StudyTimerPage, StudySyncThread
from annie.gui.week_calendar import EliteTimetableView


class StudyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StudyStore(Path(self.temp.name) / 'study.sqlite3')
        self.subject = self.store.add_subject('MATH 251', now=1)

    def tearDown(self):
        self.temp.cleanup()

    def test_subject_validation_and_case_insensitive_reuse(self):
        self.assertEqual(self.store.add_subject(' math   251 ')['id'], self.subject['id'])
        self.assertEqual(len(self.store.subjects()), 1)
        for name in (' ', 'a' * 101):
            with self.assertRaises(ValueError):
                self.store.add_subject(name)

    def test_pause_resume_restart_and_idempotent_end(self):
        session = self.store.start(self.subject['id'], sync=True, now=100)
        sid = session['id']
        with self.assertRaises(ValueError):
            self.store.start(self.subject['id'], now=101)
        self.store.transition(sid, 'pause', now=160)
        reopened = StudyStore(self.store.path)
        self.assertEqual(reopened.active()['state'], 'paused')
        self.assertEqual(reopened.elapsed(sid, now=250), 60)
        reopened.transition(sid, 'resume', now=260)
        self.assertEqual(reopened.elapsed(sid, now=300), 100)
        ended = reopened.transition(sid, 'end', now=320)
        self.assertEqual(reopened.transition(sid, 'end', now=999)['ended'], 320)
        self.assertIsNone(reopened.active())
        self.assertEqual(reopened.totals(end=1000), 120)
        self.assertEqual(reopened.history()[0]['seconds'], 120)
        self.assertEqual((ended['started'], ended['ended']), (100, 320))
        self.assertEqual(len(reopened.pending_sync()), 1)

    def test_midnight_totals_clip_active_segments_not_whole_session(self):
        midnight = dt.datetime(2026, 9, 8, tzinfo=TZ).timestamp()
        sid = self.store.start(self.subject['id'], now=midnight - 600)['id']
        self.store.transition(sid, 'pause', now=midnight - 120)
        self.store.transition(sid, 'resume', now=midnight + 120)
        self.store.transition(sid, 'end', now=midnight + 600)
        self.assertEqual(self.store.totals(midnight - 86400, midnight), 480)
        self.assertEqual(self.store.totals(midnight, midnight + 86400), 480)
        events = self.store.calendar_events(dt.date(2026, 9, 7), dt.date(2026, 9, 14))
        self.assertEqual(len(events), 1)
        self.assertIn('0h 16m', events[0]['description'])
        self.assertRegex(events[0]['id'], r'^[0-9a-v]+$')
        self.assertEqual(events[0]['extendedProperties']['private']['annieStudySession'], sid)

    def test_backwards_clock_rejected_without_changing_state(self):
        sid = self.store.start(self.subject['id'], now=100)['id']
        with self.assertRaises(ValueError):
            self.store.transition(sid, 'end', now=90)
        self.assertEqual(self.store.active()['state'], 'running')

    def test_running_session_recovers_elapsed_from_saved_timestamps(self):
        sid = self.store.start(self.subject['id'], now=100)['id']
        self.assertEqual(StudyStore(self.store.path).elapsed(sid, now=3700), 3600)
        self.assertEqual(duration_text(3661, clock=True), '01:01:01')

    def test_manual_session_and_edits_change_totals_keep_event_id(self):
        start = dt.datetime(2026, 9, 7, 12, tzinfo=TZ).timestamp()
        session = self.store.record_completed(self.subject['id'], start, 20 * 60, now=start + 3600)
        updated_subject = self.store.add_subject('Physics')
        before = self.store.event_body(session)
        edited = self.store.update_completed(session['id'], updated_subject['id'], 10 * 60, now=start + 3600)
        self.assertEqual(edited['sync_state'], 'local')
        self.assertIsNone(self.store.active())
        self.assertEqual(self.store.totals(end=start + 3600), 600)
        calendar = self.store.calendar_events(dt.date(2026, 9, 7), dt.date(2026, 9, 8))[0]
        self.assertEqual(calendar['id'], before['id'])
        self.assertEqual(calendar['summary'], 'Study · Physics')
        self.assertEqual(calendar['end']['dateTime'], '2026-09-07T12:10:00+05:00')
        with self.assertRaisesRegex(ValueError, 'ending in the past'):
            self.store.update_completed(session['id'], updated_subject['id'], 3601, now=start + 3600)
        self.assertEqual(self.store.history()[0]['seconds'], 600)

    def test_subject_edit_preserves_breaks_and_stale_sync_cannot_win(self):
        sid = self.store.start(self.subject['id'], sync=True, now=100)['id']
        self.store.transition(sid, 'pause', now=120)
        self.store.transition(sid, 'resume', now=150)
        self.store.transition(sid, 'end', now=190)
        old = self.store.pending_sync()[0]
        new = self.store.add_subject('Physics')
        self.store.update_completed(sid, new['id'])
        self.store.mark_sync(sid, revision=old['sync_revision'])
        pending = self.store.pending_sync()[0]
        self.assertEqual((pending['started'], pending['ended'], pending['seconds']), (100, 190, 60))
        self.assertEqual(pending['subject'], 'Physics')
        self.store.mark_sync(sid, revision=pending['sync_revision'])
        self.assertFalse(self.store.pending_sync())


class StudyUITests(StudyStoreTests):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_controls_and_close_reopen_preserve_paused_timer(self):
        page = StudyTimerPage(store=self.store)
        page.setAttribute(Qt.WA_DontShowOnScreen)
        page.show()
        try:
            self.assertFalse(page.start_button.isEnabled())
            page.subject_picker.setCurrentIndex(1)
            with patch('annie.study_sessions.time.time', return_value=100):
                page.start_button.click()
            with patch('annie.study_sessions.time.time', return_value=160):
                page.pause_button.click()
            self.assertEqual(page.pause_button.text(), 'Resume')
            self.assertEqual(page.elapsed_label.text(), '00:01:00')
            self.assertFalse(page.subject_picker.isEnabled())
            page.stop_background()
            page.resume_background()
            self.assertEqual(page.elapsed_label.text(), '00:01:00')
            with patch.object(page, 'sync_pending'), patch('annie.study_sessions.time.time', return_value=220):
                page.end_button.click()
            self.assertEqual(page.history_table.rowCount(), 1)
            self.assertEqual(self.store.history()[0]['seconds'], 60)
        finally:
            page.stop_background()
            page.close()
            page.deleteLater()

    def test_local_calendar_offline_and_google_deduplication(self):
        start = dt.datetime(2026, 9, 7, 12, tzinfo=TZ).timestamp()
        sid = self.store.start(self.subject['id'], now=start)['id']
        self.store.transition(sid, 'end', now=start + 3600)
        view = EliteTimetableView()
        view.monday = dt.date(2026, 9, 7)
        try:
            view.set_study_store(self.store)
            with patch('annie.calendar_service.is_connected', return_value=False):
                view._refresh()
            self.assertEqual(len(view.grid.blocks), 1)
            event = self.store.event_body(self.store.history()[0])
            view._loaded(view.monday, [event], '')
            self.assertEqual(len(view.grid.blocks), 1)
            view.monday += dt.timedelta(days=7)
            view.reload_local_sessions()
            self.assertEqual(len(view.grid.blocks), 0)
        finally:
            view.deleteLater()

    def test_google_failure_is_retryable_and_success_uses_stable_id(self):
        sid = self.store.start(self.subject['id'], sync=True, now=100)['id']
        self.store.transition(sid, 'end', now=160)
        worker = StudySyncThread(self.store)
        with patch('annie.calendar_service.get_service', return_value=None):
            worker.run()
        self.assertEqual(len(self.store.pending_sync()), 1)
        service = Mock()
        with patch('annie.calendar_service.get_service', return_value=service):
            worker.run()
        body = service.events.return_value.insert.call_args.kwargs['body']
        self.assertEqual(body['id'], 'annie' + sid)
        self.assertFalse(body['reminders']['useDefault'])
        self.assertEqual(self.store.pending_sync(), [])

    def test_google_lost_response_conflict_is_not_duplicated(self):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        sid = self.store.start(self.subject['id'], sync=True, now=100)['id']
        self.store.transition(sid, 'end', now=160)
        service = Mock()
        service.events.return_value.insert.return_value.execute.side_effect = HttpError(Response({'status': '409'}), b'{}')
        service.events.return_value.get.return_value.execute.return_value = self.store.event_body(self.store.history()[0])
        with patch('annie.calendar_service.get_service', return_value=service):
            StudySyncThread(self.store).run()
        self.assertEqual(self.store.pending_sync(), [])
        self.assertEqual(service.events.return_value.insert.call_count, 1)
        service.events.return_value.patch.assert_not_called()

    def test_edit_sync_patches_the_linked_calendar_event(self):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        session = self.store.record_completed(self.subject['id'], 100, 60, sync=True, now=400)
        before = self.store.event_body(session)
        self.store.mark_sync(session['id'])
        self.store.update_completed(session['id'], self.subject['id'], 120, now=400)
        service = Mock()
        service.events.return_value.insert.return_value.execute.side_effect = HttpError(
            Response({'status': '409'}), b'{}')
        service.events.return_value.get.return_value.execute.return_value = before
        with patch('annie.calendar_service.get_service', return_value=service):
            StudySyncThread(self.store).run()
        arguments = service.events.return_value.patch.call_args.kwargs
        self.assertEqual(arguments['eventId'], before['id'])
        self.assertNotIn('id', arguments['body'])
        self.assertIn('end', arguments['body'])
        self.assertFalse(self.store.pending_sync())


if __name__ == '__main__':
    unittest.main()
