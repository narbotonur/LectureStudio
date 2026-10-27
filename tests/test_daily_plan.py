import datetime as dt
import tempfile
import unittest

from annie.daily_plan import DailyPlanStore, suggest_today
from annie.planner import TZ


NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=TZ)
COURSES = [{'name': 'MATH 251', 'credits': 6, 'current_percent': 70, 'target_percent': 90}]


class DailyPlanTests(unittest.TestCase):
    def test_suggestions_avoid_classes_prayers_and_routine_duration(self):
        events = [{'summary': 'Class', 'start': {'dateTime': '2026-10-27T17:00:00+05:00'},
                   'end': {'dateTime': '2026-10-27T18:00:00+05:00'}}]
        prayers = {'Maghrib': '2026-10-27T18:00:00+05:00'}
        habits = [{'name': 'Read two pages', 'kind': 'count', 'target': 2,
                   'duration_minutes': 15, 'anchor': 'after_maghrib', 'days_mask': 127}]
        items, warnings = suggest_today(COURSES, events=events, prayers=prayers, habits=habits, now=NOW)
        self.assertFalse(warnings)
        self.assertGreaterEqual(dt.datetime.fromisoformat(items[0]['start']),
                                NOW.replace(hour=18, minute=45))
        self.assertEqual(items[0]['status'], 'suggested')

    def test_explicit_approval_persists_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            item = suggest_today(COURSES, now=NOW)[0][0]
            store = DailyPlanStore(root)
            self.assertFalse(store.decisions())
            store.decide(item, 'accepted')
            store.decide(item, 'accepted')
            reopened = DailyPlanStore(root)
            items, _ = suggest_today(COURSES, decisions=reopened.decisions(), now=NOW)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['status'], 'accepted')

    def test_tomorrow_removes_today_without_duplicate_course_next_day(self):
        with tempfile.TemporaryDirectory() as root:
            store = DailyPlanStore(root)
            item = suggest_today(COURSES, now=NOW)[0][0]
            store.decide(item, 'tomorrow')
            self.assertEqual(suggest_today(COURSES, decisions=store.decisions(), now=NOW)[0], [])
            items, _ = suggest_today(COURSES, decisions=store.decisions(), now=NOW + dt.timedelta(days=1))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['status'], 'tomorrow')

    def test_day_end_and_limit_never_force_extra_study(self):
        self.assertEqual(suggest_today(COURSES, settings={'weekday_max_minutes': 0}, now=NOW)[0], [])
        self.assertEqual(suggest_today(COURSES, now=NOW.replace(hour=23))[0], [])

    def test_rejected_decision_is_not_reoffered_and_tasks_keep_evidence_link(self):
        task = {'id': 'action-1', 'summary': 'Review stack frames', 'course': 'CSCI 231', 'minutes': 20}
        item = suggest_today(tasks=[task], now=NOW)[0][0]
        self.assertEqual(item['action_id'], 'action-1')
        with tempfile.TemporaryDirectory() as root:
            store = DailyPlanStore(root)
            store.decide(item, 'skipped')
            self.assertEqual(suggest_today(tasks=[task], decisions=store.decisions(), now=NOW)[0], [])


if __name__ == '__main__':
    unittest.main()
