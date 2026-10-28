"""Approved study actions retain their own lecture, independent of active input."""
import datetime as dt
import json
import tempfile
import unittest

from annie.lecture_actions import ActionStore, extract_actions


class ExecutableSourceTests(unittest.TestCase):
    def test_approved_study_source_is_immutable_and_rejects_pending_or_tampered(self):
        source = [{'start': 0, 'end': 10, 'source': 'Authored BFS lecture',
                   'text': 'Practice BFS on an unweighted graph before the next class.'}]
        item = {'type': 'review_task', 'summary': 'Practice BFS', 'quote': source[0]['text'],
                'source': source[0]['source'], 't_start': 0, 't_end': 10,
                'due_at': None, 'confidence': 0.8, 'suggested_action': 'Practice BFS.', 'minutes': 25}
        with tempfile.TemporaryDirectory() as root:
            store = ActionStore(root)
            result = extract_actions(source, generator=lambda *_: json.dumps({'findings': [item]}))
            store.add_scan(result, source, 'CSCI 231', 'BFS lecture', dt.date(2026, 10, 28))
            identity = store.list_actions()[0]['id']
            with self.assertRaises(ValueError):
                store.study_context(identity)
            store.approve(identity)
            context = store.study_context(identity)
            self.assertEqual(context['segments'][0]['text'], source[0]['text'])
            self.assertEqual(context['fingerprint'], result.fingerprint)
            context['segments'][0]['text'] = 'Local caller mutation'
            self.assertEqual(store.study_context(identity)['segments'][0]['text'], source[0]['text'])
            with store.connection() as db:
                db.execute("UPDATE lecture_actions SET segments='[]' WHERE id=?", (identity,))
            with self.assertRaises(ValueError):
                store.study_context(identity)
