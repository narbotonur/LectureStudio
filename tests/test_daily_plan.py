import datetime as dt
import tempfile
import unittest

from annie.daily_plan import DailyPlanStore, suggest_today
from annie.planner import TZ


NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=TZ)
COURSES = [{'name': 'MATH 251', 'credits': 6, 'current_percent': 70, 'target_percent': 90}]


class DailyPlanTests(unittest.TestCase):
    def test_cutoff_requires_the_whole_block_to_finish_before_deadline(self):
        due = NOW.replace(hour=11)
        deadline = {'id': 'lab', 'title': 'Lab 2', 'due_at': due.isoformat()}
        items, _ = suggest_today(deadlines=[deadline], now=NOW)
        self.assertLessEqual(dt.datetime.fromisoformat(items[0]['end']), due)
        events = [{'summary': 'Class', 'start': {'dateTime': NOW.isoformat()},
                   'end': {'dateTime': due.isoformat()}}]
        items, warnings = suggest_today(deadlines=[deadline], events=events, now=NOW)
        self.assertEqual(items, [])
        self.assertIn('before 11:00', warnings[0])

    def test_large_task_does_not_hide_a_shorter_one(self):
        tasks = [{'id': 'long', 'summary': 'Read textbook', 'minutes': 60},
                 {'id': 'short', 'summary': 'Review definitions', 'minutes': 10}]
        items, _ = suggest_today(tasks=tasks, settings={'weekday_max_minutes': 25}, now=NOW)
        self.assertEqual([item['action_id'] for item in items], ['short'])

    def test_new_calendar_conflict_preserves_manual_block_and_move(self):
        event = {'summary': 'Class', 'start': {'dateTime': NOW.isoformat()},
                 'end': {'dateTime': (NOW + dt.timedelta(hours=1)).isoformat()}}
        with tempfile.TemporaryDirectory() as root:
            store = DailyPlanStore(root)
            original = store.schedule(title='Practice', start=NOW.isoformat(), minutes=45, pinned=True)
            items, _ = suggest_today(events=[event], decisions=store.decisions(), now=NOW)
            self.assertIn('Overlaps', items[0]['conflict'])
            self.assertEqual(items[0]['start'], NOW.isoformat())
            tomorrow = NOW + dt.timedelta(days=1)
            moved = store.schedule(original, title='Practice', start=tomorrow.isoformat(), minutes=15, pinned=True)
            reopened = DailyPlanStore(root)
            self.assertFalse(reopened.missed(tomorrow.date()))
            self.assertFalse(suggest_today(decisions=reopened.decisions(), now=NOW)[0])
            active, _ = suggest_today(decisions=reopened.decisions(), now=tomorrow)
            self.assertEqual((active[0]['id'], active[0]['minutes'], active[0]['pinned']), (moved['id'], 15, True))

    def test_reviewed_deadline_creates_concrete_step_without_gpa_course(self):
        deadline = {'id': 'deadline-1', 'origin_assignment_id': 'lab-2',
                    'title': 'Lab 2', 'course': 'CSCI 231', 'due_at': '2026-11-06T17:00+05:00'}
        items, _ = suggest_today(deadlines=[deadline], now=NOW)
        self.assertEqual(items[0]['title'], 'Work on Lab 2')
        self.assertEqual(items[0]['minutes'], 25)
        self.assertEqual(items[0]['deadline_id'], 'lab-2')
        self.assertEqual(items[0]['status'], 'suggested')

    def test_accepted_deadline_step_keeps_time_but_refreshes_changed_due_date(self):
        deadline = {'id': 'deadline-1', 'origin_assignment_id': 'lab-2',
                    'title': 'Lab 2', 'course': 'CSCI 231', 'due_at': '2026-11-03T17:00+05:00'}
        with tempfile.TemporaryDirectory() as root:
            store = DailyPlanStore(root)
            item = suggest_today(deadlines=[deadline], now=NOW)[0][0]
            store.decide(item, 'accepted')
            changed = {**deadline, 'due_at': '2026-11-06T17:00+05:00'}
            items, _ = suggest_today(deadlines=[changed], decisions=store.decisions(), now=NOW)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['start'], item['start'])
            self.assertIn('06 Nov', items[0]['reason'])

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

    def test_skip_carried_task_and_repeat_postpone_do_not_reappear(self):
        for decision in ('skipped', 'tomorrow', 'done'):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as root:
                store = DailyPlanStore(root)
                store.decide(suggest_today(COURSES, now=NOW)[0][0], 'tomorrow')
                next_day = NOW + dt.timedelta(days=1)
                carried = suggest_today(COURSES, decisions=store.decisions(), now=next_day)[0][0]
                store.decide(carried, decision)
                self.assertEqual(suggest_today(COURSES, decisions=store.decisions(), now=next_day)[0], [])

    def test_completed_time_counts_toward_daily_limit(self):
        with tempfile.TemporaryDirectory() as root:
            store = DailyPlanStore(root)
            item = suggest_today(COURSES, now=NOW)[0][0]
            store.decide(item, 'done')
            other = [{'name': 'CSCI', 'credits': 6, 'current_percent': 70, 'target_percent': 90}]
            items, _ = suggest_today(other, settings={'weekday_max_minutes': 30},
                                      decisions=store.decisions(), now=NOW)
            self.assertEqual(items, [])

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
