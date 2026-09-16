import tempfile
import unittest
from pathlib import Path

from annie.gpa_tracker import GpaStore, letter_for_percent


class GpaTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GpaStore(Path(self.temp.name) / 'gpa.sqlite3')

    def test_nu_letter_boundaries(self):
        expected = ((100, ('A', 4.0)), (95, ('A', 4.0)),
                    (94.99, ('A-', 3.67)), (85, ('B+', 3.33)),
                    (80, ('B', 3.0)), (50, ('D', 1.0)), (49.99, ('F', 0.0)))
        for value, result in expected:
            with self.subTest(value=value):
                self.assertEqual(letter_for_percent(value), result)

    def test_course_summary_and_required_remaining_score(self):
        course = self.store.add_course('MATH 251', 5, 85, now=1)
        self.store.add_assessment(course['id'], 'Midterm', 40, 80)
        self.store.add_assessment(course['id'], 'Final', 60, None)
        result = self.store.summary(course['id'])
        self.assertEqual(result['total_weight'], 100)
        self.assertEqual(result['graded_weight'], 40)
        self.assertEqual(result['earned_points'], 32)
        self.assertEqual(result['current_percent'], 80)
        self.assertEqual(result['current_letter'], 'B')
        self.assertAlmostEqual(result['required_percent'], 88.333333, places=5)
        self.assertEqual(result['target_letter'], 'B+')

    def test_credit_weighted_estimated_and_target_gpa(self):
        math = self.store.add_course('MATH 251', 5, 85)
        cs = self.store.add_course('CSCI 151', 3, 90)
        ungraded = self.store.add_course('HST 100', 2, 80)
        self.store.add_assessment(math['id'], 'Work so far', 50, 80)
        self.store.add_assessment(cs['id'], 'Course total', 100, 90)
        self.store.add_assessment(ungraded['id'], 'Final', 100, None)
        result = self.store.semester_summary()
        self.assertEqual(result['courses'], 3)
        self.assertEqual(result['credits'], 10)
        self.assertEqual(result['estimated_credits'], 8)
        self.assertAlmostEqual(result['estimated_gpa'], (5 * 3 + 3 * 3.67) / 8)
        self.assertAlmostEqual(result['target_gpa'], (5 * 3.33 + 3 * 3.67 + 2 * 3) / 10)

    def test_component_weight_limit_and_update_replacement(self):
        course = self.store.add_course('PHYS 161')
        first = self.store.add_assessment(course['id'], 'Labs', 60, 90)
        self.store.add_assessment(course['id'], 'Final', 40)
        with self.assertRaisesRegex(ValueError, 'exceed 100'):
            self.store.add_assessment(course['id'], 'Bonus', 1)
        self.store.update_assessment(first['id'], 'Labs and quizzes', 50, 92)
        self.assertEqual(self.store.summary(course['id'])['total_weight'], 90)
        with self.assertRaisesRegex(ValueError, 'exceed 100'):
            self.store.update_assessment(first['id'], 'Labs', 70, 92)

    def test_validation_uniqueness_persistence_and_cascade(self):
        course = self.store.add_course('  Math   251  ', 5, 85)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.store.add_course('math 251')
        for credits in (0, float('nan'), 31):
            with self.subTest(credits=credits), self.assertRaises(ValueError):
                self.store.add_course('Invalid ' + str(credits), credits)
        item = self.store.add_assessment(course['id'], 'Quiz', 10, 0)
        reopened = GpaStore(self.store.path)
        self.assertEqual(reopened.courses()[0]['name'], 'Math 251')
        self.assertEqual(reopened.assessments(course['id'])[0]['score'], 0)
        reopened.delete_assessment(item['id'])
        self.assertEqual(reopened.assessments(course['id']), [])
        reopened.add_assessment(course['id'], 'Final', 100)
        reopened.delete_course(course['id'])
        self.assertEqual(reopened.courses(), [])
        with reopened.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assessments').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
