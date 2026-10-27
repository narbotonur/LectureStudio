"""Native review behavior using isolated fictional data, no network."""
import datetime as dt
import json
import tempfile
import time
import unittest

from PyQt5.QtCore import QDateTime
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie.deadlines import DeadlineStore
from annie.gui.lecture_review import LectureReviewPage
from annie.lecture_actions import ActionStore
from annie.lecture_reconciliation import analyze_lecture
from annie.obligations import ObligationStore


SOURCE = 'Fictional UI lecture'
SEGMENTS = [
    {'start': 0, 'end': 10, 'source': SOURCE,
     'text': 'Lab 2 is due November 3, 2026 at 17:00.'},
    {'start': 60, 'end': 75, 'source': SOURCE,
     'text': 'Correction: Lab 2 is now due November 6, 2026 at 17:00, not November 3.'}]


def answer(*_):
    return json.dumps({'findings': [], 'deadlines': [{'title': 'Lab 2', 'assignment_id': None,
        'relation': 'explicit_correction', 'due_at': '2026-11-06T17:00+05:00',
        'reason': 'The lecturer corrected the deadline.', 'evidence': [
            {'quote': s['text'], 'source': SOURCE, 't_start': s['start'], 't_end': s['end'],
             'due_at': ('2026-11-06' if i else '2026-11-03') + 'T17:00+05:00'}
            for i, s in enumerate(SEGMENTS)]}]})


class DeadlineReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_to_both_quotes_confirmation_and_reopened_inbox(self):
        with tempfile.TemporaryDirectory() as root:
            page = LectureReviewPage(store=ActionStore(root))
            page.analysis_generator = answer
            page.set_transcript(SEGMENTS, 'CSCI 231', SOURCE, dt.date(2026, 10, 27))
            page.analyze()
            deadline = time.monotonic() + 5
            while page.has_running_job() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(page.has_running_job())
            self.assertEqual(page.findings.count(), 1)
            for segment in SEGMENTS:
                self.assertIn(segment['text'], page.evidence.toPlainText())
            self.assertEqual(DeadlineStore(root).load(), [])
            page._approve()
            self.assertEqual(page.obligations.list_proposals()[0]['status'], 'pending')
            page.confirm_date.setChecked(True)
            page._approve()
            self.assertEqual(len(DeadlineStore(root).load()), 1)
            self.assertEqual(DeadlineStore(root).load()[0]['due_at'], '2026-11-06T17:00+05:00')
            self.assertEqual(len(ObligationStore(root).list_current()), 1)
            page.close()

    def test_unresolved_date_requires_edit_and_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            store = ObligationStore(root)
            result = analyze_lecture(SEGMENTS, 'CSCI 231', SOURCE, dt.date(2026, 10, 27), generator=answer)
            proposal = {**result.proposals[0], 'proposed_due_at': None, 'relation': 'unresolved_conflict'}
            store.propose(proposal)
            page = LectureReviewPage(store=ActionStore(root))
            self.assertFalse(page.confirm_date.isEnabled())
            page._approve()
            self.assertEqual(DeadlineStore(root).load(), [])
            page.due_editor.setDateTime(QDateTime.fromString('2026-11-07T12:00', 'yyyy-MM-ddTHH:mm'))
            self.assertTrue(page.confirm_date.isEnabled())
            page.confirm_date.setChecked(True)
            page._approve()
            self.assertEqual(DeadlineStore(root).load()[0]['due_at'], '2026-11-07T12:00+05:00')
            page.close()

    def test_active_source_edit_blocks_stale_approval(self):
        with tempfile.TemporaryDirectory() as root:
            result = analyze_lecture(SEGMENTS, 'CSCI 231', SOURCE, dt.date(2026, 10, 27), generator=answer)
            ObligationStore(root).propose(result.proposals[0])
            page = LectureReviewPage(store=ActionStore(root))
            changed = [{**SEGMENTS[0], 'text': 'Lab 2 is due November 4, 2026 at 17:00.'}]
            page.set_transcript(changed, 'CSCI 231', SOURCE, dt.date(2026, 10, 27))
            page.confirm_date.setChecked(True)
            page._approve()
            self.assertEqual(DeadlineStore(root).load(), [])
            self.assertIn('changed', page.status.text())
            page.close()

    def test_model_id_must_match_quoted_assignment_title(self):
        altered = [{**s, 'text': s['text'].replace('Lab 2', 'Lab 20')} for s in SEGMENTS]
        payload = json.loads(answer())['deadlines'][0]
        payload.update(title='Lab 20', assignment_id='confirmed-lab-2')
        for ref in payload['evidence']:
            ref['quote'] = ref['quote'].replace('Lab 2', 'Lab 20')
        result = analyze_lecture(altered, 'CSCI 231', SOURCE, dt.date(2026, 10, 27),
            current=[{'assignment_id': 'confirmed-lab-2', 'course': 'CSCI 231', 'title': 'Lab 2',
                      'due_at': '2026-11-03T17:00+05:00', 'revision': 1, 'evidence': []}],
            generator=lambda *_: json.dumps({'findings': [], 'deadlines': [payload]}))
        self.assertEqual(result.proposals, [])
        self.assertEqual(result.rejected_count, 1)
