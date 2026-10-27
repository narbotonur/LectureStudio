import concurrent.futures
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from annie.deadlines import DeadlineCandidate, DeadlineStore
from annie.obligations import ObligationStore


OLD_DUE = '2026-11-03T17:00+05:00'
NEW_DUE = '2026-11-06T17:00+05:00'


def proposal(**updates):
    result = {'course': 'CSCI 231', 'title': 'Lab 2', 'assignment_id': None,
              'expected_revision': 0, 'relation': 'new', 'proposed_due_at': OLD_DUE,
              'previous_due_at': None, 'reason': 'The lecturer states the due date.',
              'fingerprint': 'fictional-snapshot-1',
              'evidence': [{'quote': 'Lab 2 is due November 3, 2026 at 17:00.',
                            'start': 0, 'end': 10, 'source': 'Fictional lecture'}]}
    result.update(updates)
    return result


class ObligationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ObligationStore(self.root)

    def first(self):
        pending = self.store.propose(proposal())
        return self.store.approve(pending['id'], expected_fingerprint='fictional-snapshot-1')

    def correction(self, first, **updates):
        current = self.store.list_current()[0]
        data = proposal(assignment_id=first['assignment_id'], expected_revision=current['revision'],
                        relation='explicit_correction', proposed_due_at=NEW_DUE,
                        previous_due_at=current['due_at'], fingerprint='fictional-snapshot-2',
                        previous_evidence=current['evidence'],
                        evidence=[{'quote': 'Correction: Lab 2 is due November 6, 2026 at 17:00.',
                                   'start': 60, 'end': 75, 'source': 'Fictional lecture'}])
        data.update(updates)
        return self.store.propose(data)

    def test_correction_has_one_projection_and_preserves_version_evidence(self):
        first = self.first()
        original = DeadlineStore(self.root).load()[0]
        pending = self.correction(first)
        self.assertEqual(DeadlineStore(self.root).load()[0]['due_at'], OLD_DUE)
        self.assertEqual(pending['previous_evidence'][0]['start'], 0)
        approved = self.store.approve(pending['id'])
        self.assertEqual(approved['applied_revision'], 2)
        self.assertEqual(approved['confirmed_due_at'], NEW_DUE)
        self.assertFalse(approved['delivery_pending'])
        current = self.store.list_current('csci 231')[0]
        self.assertEqual(current['due_at'], NEW_DUE)
        self.assertEqual(current['evidence'][0]['start'], 60)
        self.assertEqual(current['fingerprint'], 'fictional-snapshot-2')
        inbox = DeadlineStore(self.root).load()
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]['id'], original['id'])
        self.assertEqual(inbox[0]['origin_revision'], 2)
        history = self.store.history(first['assignment_id'])
        self.assertEqual([v['due_at'] for v in history], [OLD_DUE, NEW_DUE])
        self.assertEqual(history[0]['evidence'][0]['start'], 0)
        self.assertEqual(history[1]['evidence'][0]['start'], 60)

    def test_double_approve_and_repeated_scan_are_idempotent(self):
        payload = proposal()
        pending = self.store.propose(payload)
        repeated = self.store.propose(proposal(reason='Another model wording.', title='LAB 2'))
        self.assertEqual(pending['id'], repeated['id'])
        self.assertEqual(repeated['reason'], payload['reason'])
        first = self.store.approve(pending['id'])
        second = self.store.approve(pending['id'])
        self.assertEqual(first['assignment_id'], second['assignment_id'])
        self.assertEqual(len(self.store.history(first['assignment_id'])), 1)
        self.assertEqual(len(DeadlineStore(self.root).load()), 1)
        payload['evidence'][0]['quote'] = 'changed external object'
        self.assertEqual(self.store.get_proposal(pending['id'])['evidence'][0]['quote'],
                         proposal()['evidence'][0]['quote'])

    def test_stale_revision_is_committed_as_stale_not_overwritten(self):
        first = self.first()
        a = self.correction(first)
        b = self.correction(first, proposed_due_at='2026-11-09T17:00+05:00',
                            fingerprint='another-snapshot')
        self.store.approve(a['id'])
        with self.assertRaisesRegex(ValueError, 'assignment changed'):
            self.store.approve(b['id'])
        self.assertEqual(self.store.get_proposal(b['id'])['status'], 'stale')
        self.assertEqual(self.store.list_current()[0]['due_at'], NEW_DUE)
        self.assertEqual(len(self.store.history(first['assignment_id'])), 2)

    def test_unresolved_needs_explicit_manual_date(self):
        pending = self.store.propose(proposal(relation='unresolved_conflict', proposed_due_at=NEW_DUE))
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.store.approve(pending['id'])
        self.assertEqual(self.store.list_current(), [])
        approved = self.store.approve(pending['id'], due_at=OLD_DUE)
        self.assertEqual(approved['proposed_due_at'], NEW_DUE)
        self.assertEqual(approved['confirmed_due_at'], OLD_DUE)
        self.assertEqual(self.store.list_current()[0]['due_at'], OLD_DUE)

    def test_null_unknown_date_is_not_cancellation(self):
        pending = self.store.propose(proposal(proposed_due_at=None))
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.store.approve(pending['id'])
        self.assertEqual(self.store.get_proposal(pending['id'])['status'], 'pending')
        self.assertEqual(DeadlineStore(self.root).load(), [])

    def test_different_courses_are_not_merged_and_existing_id_cannot_cross_course(self):
        first = self.first()
        other = self.store.propose(proposal(course='MATH 162'))
        self.store.approve(other['id'])
        self.assertEqual(len(self.store.list_current()), 2)
        self.assertEqual(len(DeadlineStore(self.root).load()), 2)
        with self.assertRaisesRegex(ValueError, 'this course'):
            self.store.propose(proposal(assignment_id=first['assignment_id'],
                                       expected_revision=1, course='MATH 162'))

    def test_two_new_proposals_cannot_race_to_create_same_course_title(self):
        a = self.store.propose(proposal())
        b = self.store.propose(proposal(fingerprint='different-snapshot', title='LAB 2', course='csci 231'))
        self.store.approve(a['id'])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.store.approve(b['id'])
        self.assertEqual(self.store.get_proposal(b['id'])['status'], 'stale')
        self.assertEqual(len(self.store.list_current()), 1)
        self.assertEqual(len(DeadlineStore(self.root).load()), 1)

    def test_assignment_title_boundaries_match_lab2_but_not_lab20(self):
        a = self.store.propose(proposal(title='Lab2'))
        same = self.store.propose(proposal(title='Lab 2'))
        self.assertEqual(a['id'], same['id'])
        b = self.store.propose(proposal(title='Lab-2', fingerprint='second-lecture'))
        self.store.approve(a['id'])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.store.approve(b['id'])
        other_number = self.store.propose(proposal(title='Lab 20'))
        self.store.approve(other_number['id'])
        self.assertEqual(len(self.store.list_current()), 2)

    def test_existing_assignment_id_does_not_allow_a_different_assignment_title(self):
        first = self.first()
        with self.assertRaisesRegex(ValueError, 'title does not match'):
            self.correction(first, title='Lab 20')
        accepted = self.correction(first, title='Lab2')
        self.store.approve(accepted['id'])
        self.assertEqual(self.store.list_current()[0]['due_at'], NEW_DUE)

    def test_previous_evidence_is_loaded_from_confirmed_history(self):
        first = self.first()
        invented = [{'quote': 'This is a fabricated old transcript quote.',
                     'start': 100, 'end': 110, 'source': 'Invented source'}]
        candidate = self.correction(first, previous_evidence=invented, source_name='Current lecture')
        self.assertEqual(candidate['previous_evidence'], first['evidence'])
        self.assertEqual(candidate['source_name'], 'Current lecture')

    def test_unchanged_approval_does_not_add_version(self):
        first = self.first()
        unchanged = self.correction(first, relation='unchanged', proposed_due_at=OLD_DUE)
        result = self.store.approve(unchanged['id'])
        self.assertEqual(result['applied_revision'], 1)
        self.assertEqual(len(self.store.history(first['assignment_id'])), 1)

    def test_mismatched_previous_date_cannot_replace_active_version(self):
        first = self.first()
        pending = self.correction(first, previous_due_at='2026-11-01T17:00+05:00')
        with self.assertRaisesRegex(ValueError, 'assignment changed'):
            self.store.approve(pending['id'])
        self.assertEqual(self.store.list_current()[0]['due_at'], OLD_DUE)

    def test_fingerprint_mismatch_and_rejection_never_save(self):
        pending = self.store.propose(proposal())
        with self.assertRaisesRegex(ValueError, 'transcript changed'):
            self.store.approve(pending['id'], expected_fingerprint='another')
        self.store.reject(pending['id'])
        with self.assertRaisesRegex(ValueError, 'no longer pending'):
            self.store.approve(pending['id'])
        self.assertEqual(len(self.store.list_proposals('rejected')), 1)
        self.assertEqual(self.store.list_current(), [])

    def test_outbox_recovers_before_first_json_write(self):
        pending = self.store.propose(proposal())
        with patch.object(DeadlineStore, 'upsert_origin', side_effect=OSError('disk unavailable')):
            approved = self.store.approve(pending['id'])
            self.assertTrue(approved['delivery_pending'])
            self.assertEqual(len(self.store.list_current()), 1)
            self.assertEqual(DeadlineStore(self.root).load(), [])
        recovered = ObligationStore(self.root)
        self.assertFalse(recovered.get_proposal(pending['id'])['delivery_pending'])
        self.assertEqual(len(DeadlineStore(self.root).load()), 1)

    def test_outbox_repeats_safely_after_json_write_before_mark(self):
        pending = self.store.propose(proposal())
        with patch.object(self.store, '_mark_delivered', side_effect=OSError('simulated crash')):
            approved = self.store.approve(pending['id'])
        before = DeadlineStore(self.root).load()
        self.assertTrue(approved['delivery_pending'])
        self.assertEqual(len(before), 1)
        recovered = ObligationStore(self.root)
        after = DeadlineStore(self.root).load()
        self.assertEqual(after, before)
        self.assertFalse(recovered.get_proposal(pending['id'])['delivery_pending'])

    def test_old_outbox_event_cannot_roll_back_newer_revision(self):
        first = self.first()
        newer = self.correction(first)
        self.store.approve(newer['id'])
        with self.store.connection() as db:
            db.execute('UPDATE obligation_outbox SET delivered=0')
        self.assertEqual(self.store.drain_outbox(), 2)
        self.assertEqual(DeadlineStore(self.root).load()[0]['due_at'], NEW_DUE)
        self.assertEqual(DeadlineStore(self.root).load()[0]['origin_revision'], 2)

    def test_legacy_rows_and_existing_projection_status_are_preserved(self):
        inbox = DeadlineStore(self.root)
        inbox.add('CSCI 231', 'Legacy syllabus', [DeadlineCandidate('Unrelated task', OLD_DUE, 'old source')])
        legacy = copy.deepcopy(inbox.load()[0])
        first = self.first()
        rows = inbox.load()
        rows[1]['status'] = 'done'
        inbox.path.write_text(json.dumps({'version': 1, 'deadlines': rows}), encoding='utf-8')
        self.store.approve(self.correction(first)['id'])
        rows = inbox.load()
        self.assertEqual(rows[0], legacy)
        self.assertEqual(rows[1]['status'], 'done')
        self.assertEqual(rows[1]['due_at'], NEW_DUE)

    def test_matching_legacy_deadline_blocks_new_assignment_without_adoption(self):
        inbox = DeadlineStore(self.root)
        inbox.add('csci 231', 'Legacy syllabus', [DeadlineCandidate('Lab2', OLD_DUE, 'old source')])
        original = copy.deepcopy(inbox.load())
        pending = self.store.propose(proposal(proposed_due_at=NEW_DUE))
        with self.assertRaisesRegex(ValueError, 'legacy Inbox item.*preserved'):
            self.store.approve(pending['id'])
        self.assertEqual(self.store.get_proposal(pending['id'])['status'], 'stale')
        self.assertEqual(self.store.list_current(), [])
        self.assertEqual(inbox.load(), original)
        self.assertEqual(len(inbox.load()), 1)

    def test_malformed_inbox_survives_recovery_without_overwrite(self):
        first = self.first()
        inbox = DeadlineStore(self.root)
        inbox.path.write_text('{broken inbox', encoding='utf-8')
        pending = self.correction(first)
        approved = self.store.approve(pending['id'])
        self.assertTrue(approved['delivery_pending'])
        recovered = ObligationStore(self.root)
        self.assertTrue(recovered.get_proposal(pending['id'])['delivery_pending'])
        self.assertEqual(inbox.path.read_text(encoding='utf-8'), '{broken inbox')

    def test_invalid_inbox_rows_block_new_assignment_without_overwrite(self):
        inbox = DeadlineStore(self.root)
        original = json.dumps({'version': 1, 'deadlines': ['not a deadline object']})
        inbox.path.write_text(original, encoding='utf-8')
        pending = self.store.propose(proposal())
        with self.assertRaisesRegex(ValueError, 'unreadable'):
            self.store.approve(pending['id'])
        self.assertEqual(self.store.list_current(), [])
        self.assertEqual(ObligationStore(self.root).get_proposal(pending['id'])['status'], 'pending')
        self.assertEqual(inbox.path.read_text(encoding='utf-8'), original)

    def test_invalid_payloads_leave_no_proposals(self):
        changes = [{'expected_revision': True}, {'expected_revision': -1},
                   {'proposed_due_at': '2026-11-03T17:00'}, {'relation': 'cancelled'},
                   {'assignment_id': 'unregistered', 'expected_revision': 1}, {'evidence': []},
                   {'previous_evidence': [{'quote': 'invalid'}]}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.propose(proposal(**change))
        invalid = proposal()
        invalid['evidence'][0]['start'] = float('nan')
        with self.assertRaises(ValueError):
            self.store.propose(invalid)
        self.assertEqual(self.store.list_proposals(), [])

    def test_shared_inbox_lock_preserves_concurrent_legacy_and_origin_writers(self):
        def write(index):
            inbox = DeadlineStore(self.root)
            if index % 2:
                return inbox.add('Course', 'Legacy source',
                                 [DeadlineCandidate(f'Task {index}', OLD_DUE, 'legacy quote')])
            return inbox.upsert_origin(f'assignment-{index}', revision=1,
                                       course='Course', title=f'Task {index}', due_at=OLD_DUE)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(write, range(20)))
        self.assertEqual(len(DeadlineStore(self.root).load()), 20)


if __name__ == '__main__':
    unittest.main()
