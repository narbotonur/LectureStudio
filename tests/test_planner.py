import datetime as dt
import tempfile
import unittest

from annie.planner import (DEFAULT_SETTINGS, PlannerStore, TZ, blocks_as_events,
                           generate_week, validate_settings)

MONDAY = dt.date(2026, 9, 14)
NOW = dt.datetime(2026, 9, 14, 8, 0, tzinfo=TZ)


def course(name, credits, current, target=85):
    return {'name': name, 'credits': credits, 'current_percent': current,
            'target_percent': target}


def event(start, end, title='Class'):
    return {'summary': title, 'start': {'dateTime': start}, 'end': {'dateTime': end}}


class PlannerTests(unittest.TestCase):
    def test_settings_validation(self):
        result = validate_settings({})
        self.assertEqual(result['block_minutes'], 50)
        for change in ({'day_start': '23:00', 'day_end': '01:00'},
                       {'block_minutes': 10}, {'weekly_study_minutes': 3001},
                       {'jumuah_start': '14:00', 'jumuah_end': '12:00'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings(change)

    def test_study_avoids_calendar_prayer_habit_and_jumuah(self):
        settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 150,
                    'weekday_max_minutes': 50, 'weekend_max_minutes': 50,
                    'preferred_study': '17:00'}
        classes = [event('2026-09-14T17:00:00+05:00', '2026-09-14T18:00:00+05:00')]
        prayers = {day: {'Asr': f'{day.isoformat()}T18:00:00+05:00'}
                   for day in (MONDAY + dt.timedelta(days=i) for i in range(7))}
        created = NOW.timestamp()
        habits = [{'id': 'habit', 'name': 'Review notes', 'kind': 'minutes',
                   'target': 30, 'unit': 'min', 'days_mask': 127,
                   'preferred_time': '19:00', 'created': created}]
        result = generate_week(MONDAY, settings, classes, prayers, habits,
                               [course('MATH 251', 5, 80)], [], NOW)
        self.assertEqual(result['planned_study_minutes'], 150)
        study = [block for block in result['blocks'] if block['kind'] == 'study']
        self.assertEqual(len(study), 3)
        self.assertEqual(len({dt.datetime.fromisoformat(block['start']).date() for block in study}), 3)
        fixed = [(dt.datetime.fromisoformat(block['start']), dt.datetime.fromisoformat(block['end']))
                 for block in result['blocks'] if block['kind'] != 'study']
        fixed.append((dt.datetime.fromisoformat(classes[0]['start']['dateTime']),
                      dt.datetime.fromisoformat(classes[0]['end']['dateTime'])))
        for block in study:
            start, end = dt.datetime.fromisoformat(block['start']), dt.datetime.fromisoformat(block['end'])
            self.assertGreaterEqual(start, NOW)
            self.assertFalse(any(start < right and end > left for left, right in fixed))
        self.assertEqual(sum(block['kind'] == 'jumuah' for block in result['blocks']), 1)

    def test_urgent_deadline_wins_first_priority_tie(self):
        settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 50,
                    'weekday_max_minutes': 50}
        deadline = {'title': 'Problem set', 'course': 'MATH 251',
                    'due_at': '2026-09-15T23:59:00+05:00', 'status': 'open'}
        result = generate_week(MONDAY, settings, courses=[
            course('CSCI 151', 6, 70), course('MATH 251', 5, 84)],
            deadlines=[deadline], now=NOW)
        study = next(block for block in result['blocks'] if block['kind'] == 'study')
        self.assertEqual(study['title'], 'Study · MATH 251')
        self.assertIn('Problem set', study['detail'])

    def test_current_day_never_schedules_in_the_past(self):
        now = dt.datetime(2026, 9, 14, 20, 7, tzinfo=TZ)
        settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 50,
                    'weekday_max_minutes': 50, 'preferred_study': '17:00'}
        result = generate_week(MONDAY, settings, courses=[course('MATH', 5, None)], now=now)
        first = next(block for block in result['blocks'] if block['kind'] == 'study')
        self.assertGreater(dt.datetime.fromisoformat(first['start']), now)
        self.assertFalse(any(dt.datetime.fromisoformat(block['end']) <= now
                             for block in result['blocks']))

    def test_no_courses_is_clear_and_all_day_deadline_does_not_block(self):
        all_day = {'summary': 'Deadline', 'start': {'date': '2026-09-14'},
                   'end': {'date': '2026-09-15'}}
        settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 50}
        result = generate_week(MONDAY, settings, calendar_events=[all_day], now=NOW)
        self.assertEqual(result['planned_study_minutes'], 0)
        self.assertTrue(any('GPA' in warning for warning in result['warnings']))

    def test_small_remainder_still_reaches_exact_weekly_target(self):
        settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 60,
                    'block_minutes': 50, 'weekday_max_minutes': 60}
        result = generate_week(MONDAY, settings, courses=[course('MATH', 5, 80)], now=NOW)
        self.assertEqual(result['planned_study_minutes'], 60)
        minutes = [int((dt.datetime.fromisoformat(block['end']) -
                        dt.datetime.fromisoformat(block['start'])).total_seconds() / 60)
                   for block in result['blocks'] if block['kind'] == 'study']
        self.assertEqual(sum(minutes), 60)

    def test_plan_events_keep_stable_private_ids(self):
        result = generate_week(MONDAY, {**DEFAULT_SETTINGS, 'weekly_study_minutes': 50},
                               courses=[course('MATH', 5, 70)], now=NOW)
        events = blocks_as_events(result['blocks'])
        self.assertTrue(all(event['id'].startswith('annieplan') for event in events))
        self.assertEqual(events[0]['extendedProperties']['private']['anniePlanBlock'],
                         result['blocks'][0]['id'])

    def test_store_persists_settings_and_validates_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            store = PlannerStore(root)
            settings = {**DEFAULT_SETTINGS, 'weekly_study_minutes': 480}
            store.save_settings(settings)
            result = generate_week(MONDAY, settings, courses=[course('MATH', 5, 80)], now=NOW)
            store.save_week(MONDAY, result['blocks'], NOW)
            reopened = PlannerStore(root)
            self.assertEqual(reopened.settings()['weekly_study_minutes'], 480)
            self.assertEqual(reopened.week(MONDAY), result['blocks'])
            with self.assertRaises(ValueError):
                reopened.save_week(MONDAY, [{'kind': 'study'}])


if __name__ == '__main__':
    unittest.main()
