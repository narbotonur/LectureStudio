"""Native lab interactions; authored examples only, no network or user profile."""
import copy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest

from PyQt5.QtWidgets import QApplication

from annie.gui.lecture_lab import LectureLabPage


class NativeLectureLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self, root):
        page = LectureLabPage(root=root)
        page.load_example()
        self.assertIsNotNone(page.current_spec, page.status.text())
        return page

    def accept(self, page):
        page.review_source.setChecked(True)
        page.use_lab()
        self.assertIsNotNone(page.lab_id, page.status.text())

    def test_source_acknowledgement_precedes_save_and_execution(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.assertIn('No model call', page.status.text())
            self.assertIn('CONSTRUCTED EXAMPLE', page.evidence.toPlainText())
            page.use_lab()
            self.assertIsNone(page.lab_id)
            self.assertEqual(page.store.list_labs(), [])
            self.accept(page)
            self.assertEqual(len(page.store.list_labs()), 1)
            self.assertTrue(page.experiment.isEnabled())
            self.assertEqual(page.result['bfs_path'], ['A', 'C'])
            self.assertEqual(page.result['bfs_cost'], 1)
            page.close()

    def test_weight_switch_counterexample_and_prediction_are_engine_computed(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            page.set_study_action('approved-study-action')
            page.weighted.setChecked(True)
            self.assertEqual(page.result['bfs_cost'], 10)
            self.assertEqual(page.result['shortest_cost'], 2)
            self.assertIn('outside the equal-edge', page.assumption_label.text())
            page.predicted_cost.setValue(2)
            page.check_prediction()
            page.predicted_cost.setValue(10)
            page.check_prediction()
            attempts = page.store.attempts(page.lab_id)
            self.assertFalse(attempts[0]['correct'])
            self.assertTrue(attempts[1]['correct'])
            self.assertEqual(attempts[1]['action_id'], 'approved-study-action')
            self.assertIn('does not establish mastery', page.attempt_feedback.text())
            page.close()

    def test_pending_graph_edit_cannot_record_old_graph_as_new_prediction(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            original = copy.deepcopy(page.result)
            page.edges_input.setPlainText('A C -1')
            self.assertFalse(page.check_button.isEnabled())
            page.apply_edits()
            page.check_prediction()
            self.assertEqual(page.result, original)
            self.assertEqual(page.store.attempts(page.lab_id), [])
            page.restore_graph()
            self.assertTrue(page.check_button.isEnabled())
            page.close()

    def test_disconnected_experiment_accepts_no_path_prediction(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            page.edges_input.clear()
            page.apply_edits()
            self.assertFalse(page.result['reachable'])
            page.no_path.setChecked(True)
            page.check_prediction()
            attempts = page.store.attempts(page.lab_id)
            self.assertTrue(attempts[0]['correct'])
            self.assertIsNone(attempts[0]['answer']['predicted_cost'])
            page.close()

    def test_trace_navigation_and_saved_lab_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            identity = page.lab_id
            self.assertFalse(page.prev_button.isEnabled())
            page.slider.setValue(page.slider.maximum())
            self.assertFalse(page.next_button.isEnabled())
            self.assertIn('Queue:', page.step_label.text())
            page.close()
            reopened = LectureLabPage(root=root)
            index = reopened.saved_combo.findData(identity)
            self.assertGreater(index, 0)
            reopened.saved_combo.setCurrentIndex(index)
            reopened.open_saved()
            self.assertEqual(reopened.current_spec['title'], page.current_spec['title'])
            self.assertIsNone(reopened.lab_id)  # A new session still asks source review.
            reopened.close()

    def test_changed_source_result_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            proposed = copy.deepcopy(page.current_spec)
            page._spec = None
            page.set_transcript([{'start': 0, 'end': 3, 'source': 'Another lecture',
                                  'text': 'BFS uses a queue.'}], 'New course', 'Another lecture')
            page._worker = SimpleNamespace(course='Original course', source_name='Original lecture')
            page._generated(proposed)
            self.assertIsNone(page.current_spec)
            self.assertIn('source changed', page.status.text())
            page._worker = None
            page.close()

    def test_changed_source_invalidates_prior_lab_and_study_action(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            page.set_study_action('previous-action')
            page.set_transcript([{'start': 0, 'end': 3, 'source': 'New source',
                                  'text': 'This lecture discusses graph theory.'}], 'New course', 'New source')
            self.assertIsNone(page.current_spec)
            self.assertIsNone(page.lab_id)
            self.assertEqual(page.action_id, '')
            self.assertFalse(page.experiment.isEnabled())
            self.assertFalse(page.use_button.isEnabled())
            self.assertFalse(page.review_source.isChecked())
            self.assertEqual(len(page.store.list_labs()), 1)  # Saved prior source remains intact.
            page.close()

    def test_small_decimal_prediction_and_edge_precision_survive_controls(self):
        for weight in (0.001, 0.12345678912345):
            with self.subTest(weight=weight), tempfile.TemporaryDirectory() as root:
                page = self.page(root)
                spec = copy.deepcopy(page.current_spec)
                spec['graph']['edges'][0]['weight'] = weight
                page.load_lab(spec)
                self.accept(page)
                self.assertIn(repr(weight), page.edges_input.toPlainText())
                page.apply_edits()
                self.assertEqual(page._graph['edges'][0]['weight'], weight)
                page.weighted.setChecked(True)
                page.predicted_cost.setValue(weight)
                page.check_prediction()
                self.assertTrue(page.store.attempts(page.lab_id)[0]['correct'])
                self.assertIn(format(weight, '.12g'), page.comparison_label.text())
                page.close()

    def test_bad_saved_source_does_not_block_page_startup_or_get_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            page = self.page(root)
            self.accept(page)
            identity = page.lab_id
            path = page.store.path
            page.close()
            with sqlite3.connect(path) as db:
                payload = json.loads(db.execute('SELECT payload FROM executable_labs WHERE id=?', (identity,)).fetchone()[0])
                payload['fingerprint'] = 'tampered-source'
                stored = json.dumps(payload)
                db.execute('UPDATE executable_labs SET payload=? WHERE id=?', (stored, identity))
            db.close()
            reopened = LectureLabPage(root=root)
            self.assertIn('could not be loaded', reopened.status.text())
            self.assertFalse(reopened.open_saved_button.isEnabled())
            self.assertEqual(reopened.saved_combo.count(), 1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT payload FROM executable_labs WHERE id=?', (identity,)).fetchone()[0], stored)
            db.close()
            reopened.close()

    def test_corrupt_storage_file_does_not_prevent_workspace_startup(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'executable_labs.sqlite3'
            original = b'not a sqlite database'
            path.write_bytes(original)
            page = LectureLabPage(root=root)
            self.assertIsNone(page.store)
            self.assertIn('could not be loaded', page.status.text())
            self.assertEqual(path.read_bytes(), original)
            page.close()


if __name__ == '__main__':
    unittest.main()
