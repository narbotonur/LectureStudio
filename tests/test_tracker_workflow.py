"""Preservation and user workflows for routine goals and editable grade inputs."""
import datetime as dt
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QPushButton

from annie.gpa_tracker import GpaStore, parse_score
from annie.gui.gpa_tracker import GpaTrackerPage
from annie.gui.habit_tracker import CompactRoutineWidget, HabitDialog, HabitTrackerPage
from annie.habits import HabitStore, TZ, progress_level


class RoutineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'habits.sqlite3'
        self.day = dt.datetime.now(TZ).date()

    def test_legacy_database_migration_preserves_goals_and_logs(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''
                CREATE TABLE habits (id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT UNIQUE,
                kind TEXT,target REAL,unit TEXT,days_mask INTEGER,preferred_time TEXT,
                active INTEGER,created REAL);
                CREATE TABLE habit_logs(habit_id TEXT,day TEXT,value REAL,updated REAL,
                PRIMARY KEY(habit_id,day));
                INSERT INTO habits VALUES ('legacy','Read','read','minutes',20,'min',127,'19:00',1,1);
                INSERT INTO habit_logs VALUES ('legacy','2026-09-14',12,1);
            ''')
        store = HabitStore(self.path)
        habit = store.habits()[0]
        self.assertEqual((habit['target'], habit['minimum_target'], habit['ideal_target']), (20, 20, 20))
        self.assertEqual(habit['duration_minutes'], 20)
        self.assertEqual(habit['routine'], 'flexible')
        self.assertEqual(habit['preferred_time'], '19:00')
        start = dt.date(2026, 9, 14)
        self.assertEqual(store.progress('legacy', start, start + dt.timedelta(days=1))[start], 12)
        self.assertEqual(HabitStore(self.path).habits()[0], habit)

    def test_minimum_normal_ideal_and_duration_are_distinct(self):
        store = HabitStore(self.path)
        habit = store.add('Read', 'count', 4, 'pages', now=1, routine='morning',
                          anchor='after_fajr', minimum_target=2, ideal_target=6,
                          duration_minutes=13)
        self.assertEqual(habit['duration_minutes'], 13)
        self.assertEqual(progress_level(habit, 2), 'minimum')
        self.assertEqual(progress_level(habit, 4), 'normal')
        self.assertEqual(progress_level(habit, 6), 'ideal')
        store.increment_progress(habit['id'], self.day, 1)
        store.increment_progress(habit['id'], self.day, 1)
        row = store.today_routines(self.day)['morning'][0]
        self.assertEqual((row['value'], row['level']), (2, 'minimum'))
        store.update(habit['id'], 'Read slowly', 'count', 4, 'pages', 127)
        updated = store.habits()[0]
        self.assertEqual((updated['routine'], updated['minimum_target'], updated['duration_minutes']),
                         ('morning', 2, 13))

    def test_invalid_goal_tiers_do_not_change_existing_habit(self):
        store = HabitStore(self.path)
        habit = store.add('Read', 'minutes', 20)
        for kwargs in ({'minimum_target': 25}, {'ideal_target': 10},
                       {'duration_minutes': 0}, {'routine': 'night'}, {'anchor': 'invented'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                store.update(habit['id'], 'Changed', 'minutes', 20, '', 127, **kwargs)
        self.assertEqual(store.habits()[0]['name'], 'Read')


class GradeInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GpaStore(Path(self.temp.name) / 'gpa.sqlite3')
        self.course = self.store.add_course('CSCI', 6, 85)

    def test_raw_points_round_trip_and_clear(self):
        item = self.store.add_assessment(self.course['id'], 'Quiz', 20, '7/10')
        self.assertEqual(item['score'], 70)
        self.assertEqual(item['score_input'], '7/10')
        self.assertEqual(self.store.set_score(item['id'], '17/20'), 85)
        reopened = GpaStore(self.store.path)
        self.assertEqual(reopened.assessments(self.course['id'])[0]['score_input'], '17/20')
        self.assertEqual(reopened.summary(self.course['id'])['earned_points'], 17)
        self.assertIsNone(self.store.set_score(item['id'], ''))
        self.assertIsNone(self.store.summary(self.course['id'])['current_percent'])

    def test_malformed_or_impossible_scores_are_rejected_without_write(self):
        item = self.store.add_assessment(self.course['id'], 'Quiz', 20, 70)
        for score in ('7/0', '11/10', 'a/10', '1/2/3', 'NaN', '101%', '-1', 'inf'):
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.store.set_score(item['id'], score)
        self.assertEqual(self.store.assessments(self.course['id'])[0]['score'], 70)
        self.assertEqual(parse_score('0/10'), 0)
        self.assertEqual(parse_score('87.5%'), 87.5)

    def test_what_if_includes_unconfigured_weight_without_mutating_grades(self):
        self.store.add_assessment(self.course['id'], 'Midterm', 40, 80)
        before = self.store.assessments(self.course['id'])
        result = self.store.what_if(self.course['id'], 90)
        self.assertEqual(result['projected_percent'], 86)
        self.assertEqual(result['unconfigured_weight'], 60)
        self.assertTrue(result['target_reached'])
        self.assertEqual(self.store.assessments(self.course['id']), before)
        with self.assertRaises(ValueError):
            self.store.what_if(self.course['id'], 101)


class TrackerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_edit_inline_score_and_keep_previous_value_on_invalid_input(self):
        store = GpaStore(Path(self.temp.name) / 'gpa.sqlite3')
        course = store.add_course('MATH')
        item = store.add_assessment(course['id'], 'Quiz', 20, 70)
        page = GpaTrackerPage(store=store)
        self.addCleanup(page.deleteLater)
        page.table.item(0, 2).setText('18/20')
        self.assertEqual(store.assessments(course['id'])[0]['score'], 90)
        page.table.item(0, 2).setText('30/20')
        self.assertEqual(store.assessments(course['id'])[0]['score'], 90)
        self.assertIn('previous score was kept', page.course_status.text())
        self.assertEqual(page.table.item(0, 2).data(Qt.UserRole), item['id'])
        self.assertFalse(page.table.item(0, 0).flags() & Qt.ItemIsEditable)
        page.what_if_score.setValue(95)
        self.assertIn('94.0%', page.what_if_result.text())

    def test_empty_course_disables_component_actions(self):
        store = GpaStore(Path(self.temp.name) / 'gpa.sqlite3')
        store.add_course('Empty')
        page = GpaTrackerPage(store=store)
        self.addCleanup(page.deleteLater)
        self.assertFalse(page.edit_component_button.isEnabled())
        self.assertFalse(page.delete_component_button.isEnabled())

    def test_compact_routine_checkin_and_dialog_tiers(self):
        store = HabitStore(Path(self.temp.name) / 'habits.sqlite3')
        habit = store.add('Quran', 'minutes', 20, now=1, routine='morning', minimum_target=5)
        compact = CompactRoutineWidget(store=store)
        self.addCleanup(compact.deleteLater)
        compact.findChild(QPushButton).click()
        row = store.today_routines()['morning'][0]
        self.assertEqual((row['value'], row['level']), (5, 'minimum'))
        page = HabitTrackerPage(store=store)
        self.addCleanup(page.deleteLater)
        self.assertEqual(page.today_value.text(), '1 / 1')
        self.assertEqual(page.week_value.text(), '0 / 1')
        dialog = HabitDialog(habit=habit)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.routine_values()['routine'], 'morning')
        dialog.target.setValue(30)
        self.assertGreaterEqual(dialog.ideal.value(), 30)


if __name__ == '__main__':
    unittest.main()
