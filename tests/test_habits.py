import datetime as dt
import tempfile
import unittest
from pathlib import Path

from annie.habits import HabitStore, schedule_text, scheduled


class HabitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = HabitStore(Path(self.temp.name) / 'habits.sqlite3')

    def test_add_types_schedule_and_order(self):
        reading = self.store.add('Read textbook', 'minutes', 30, '', 31, '19:30', now=1)
        prayer = self.store.add('Morning adhkar', 'done', 99, 'ignored', 127, '07:00', now=2)
        problems = self.store.add('Solve problems', 'count', 5, 'problems', 21, '', now=3)
        self.assertEqual(prayer['target'], 1)
        self.assertEqual(prayer['unit'], '')
        self.assertEqual(reading['unit'], 'min')
        self.assertEqual([item['name'] for item in self.store.habits()],
                         ['Morning adhkar', 'Read textbook', 'Solve problems'])
        monday = dt.date(2026, 9, 14)
        self.assertTrue(scheduled(reading, monday))
        self.assertFalse(scheduled(reading, monday + dt.timedelta(days=5)))
        self.assertEqual(schedule_text(31), 'Weekdays')
        self.assertEqual(schedule_text(21), 'Mon · Wed · Fri')
        self.assertEqual(problems['unit'], 'problems')

    def test_week_rates_ignore_future_and_unplanned_days(self):
        monday = dt.date(2026, 9, 14)
        wednesday = monday + dt.timedelta(days=2)
        created = dt.datetime(2026, 9, 14, 8).timestamp()
        daily = self.store.add('Read', 'minutes', 10, '', 127, now=created)
        mwf = self.store.add('Exercise', 'done', 1, '', 21, now=created)
        self.store.set_progress(daily['id'], monday, 10)
        self.store.set_progress(daily['id'], monday + dt.timedelta(days=1), 5)
        self.store.set_progress(mwf['id'], monday, 1)
        self.store.set_progress(mwf['id'], wednesday, 1)
        # An off-schedule Tuesday log is kept but does not inflate adherence.
        self.store.set_progress(mwf['id'], monday + dt.timedelta(days=1), 1)
        result = self.store.week(wednesday)
        self.assertEqual(result['week_opportunities'], 5)
        self.assertAlmostEqual(result['week_rate'], .7)
        self.assertEqual(result['today_opportunities'], 2)
        self.assertAlmostEqual(result['today_rate'], .5)
        self.assertEqual(result['days'][0], monday)

    def test_days_before_creation_do_not_reduce_week(self):
        wednesday = dt.date(2026, 9, 16)
        created = dt.datetime(2026, 9, 16, 8, tzinfo=dt.timezone(dt.timedelta(hours=5))).timestamp()
        habit = self.store.add('New habit', 'done', days_mask=127, now=created)
        self.store.set_progress(habit['id'], wednesday, 1)
        result = self.store.week(wednesday)
        self.assertEqual(result['week_opportunities'], 1)
        self.assertEqual(result['week_rate'], 1)

    def test_partial_progress_is_capped_and_zero_removes_log(self):
        day = dt.date(2026, 9, 14)
        created = dt.datetime(2026, 9, 14, 8, tzinfo=dt.timezone(dt.timedelta(hours=5))).timestamp()
        habit = self.store.add('Practice', 'count', 10, 'problems', 127, now=created)
        self.store.set_progress(habit['id'], day, 25)
        self.assertEqual(self.store.week(day)['week_rate'], 1)
        self.store.set_progress(habit['id'], day, 0)
        self.assertEqual(self.store.progress(habit['id'], day, day + dt.timedelta(days=1)), {})
        self.assertEqual(self.store.week(day)['week_rate'], 0)

    def test_validation_update_uniqueness_and_delete_cascade(self):
        habit = self.store.add('Review', 'done', days_mask=127)
        self.store.add('Read', 'minutes', 20, days_mask=31)
        for args in (('No days', 'done', 1, '', 0, ''),
                     ('No unit', 'count', 3, '', 127, ''),
                     ('Bad time', 'done', 1, '', 127, '25:00')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.store.add(*args)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.store.update(habit['id'], 'read', 'done', 1, '', 127)
        self.store.update(habit['id'], 'Daily review', 'minutes', 15, '', 31, '18:00')
        changed = next(item for item in self.store.habits() if item['id'] == habit['id'])
        self.assertEqual((changed['name'], changed['unit'], changed['target']),
                         ('Daily review', 'min', 15))
        self.store.set_progress(habit['id'], dt.date(2026, 9, 14), 15)
        self.store.delete(habit['id'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM habit_logs').fetchone()[0], 0)

    def test_persists_across_reopen_and_done_values_are_boolean(self):
        habit = self.store.add('Plan tomorrow')
        day = dt.date(2026, 9, 16)
        self.assertEqual(self.store.set_progress(habit['id'], day, 50), 1)
        reopened = HabitStore(self.store.path)
        self.assertEqual(reopened.progress(habit['id'], day, day + dt.timedelta(days=1))[day], 1)


if __name__ == '__main__':
    unittest.main()
