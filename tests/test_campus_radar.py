"""Local snapshot/diff checks only: no authentication, fetches or messages."""
import copy
import datetime as dt
import json
import sqlite3
import tempfile
import unittest

from annie.campus_radar import RadarStore


T1 = '2026-10-28T10:00:00+05:00'
T2 = '2026-10-28T11:00:00+05:00'
T3 = '2026-10-28T12:00:00+05:00'
T4 = '2026-10-28T13:00:00+05:00'
DUE_A = '2026-11-03T17:00:00+05:00'
DUE_B = '2026-11-06T17:00:00+05:00'


def item(**updates):
    result = {'external_id': 'lab-2', 'title': 'Lab 2', 'course': 'CSCI 231',
              'due_at': DUE_A, 'raw_due_text': 'November 3 at 17:00 UTC+05',
              'source_url': 'https://campus.example/assignment?id=2', 'status': 'open'}
    result.update(updates)
    return result


def envelope(**updates):
    result = {'source': {'source_id': 'course-csci', 'kind': 'moodle',
        'name': 'CSCI 231', 'url': 'https://campus.example/course?id=231', 'scope': 'course'},
        'checked_at': T1, 'complete': True, 'items': [item()]}
    result.update(updates)
    return result


class CampusRadarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='campus-radar-test-')
        self.addCleanup(self.temp.cleanup)
        self.store = RadarStore(self.temp.name)

    def register(self, identity='one', scope='assignment'):
        return self.store.register_source(identity, 'webwork', 'Math homework',
            'https://Math.Example:443/webwork?set=HW_2&utm_source=ignored&id=4#ignored', scope)

    def test_initial_source_is_unverified_and_url_is_canonical(self):
        source = self.register()
        self.assertEqual(source['url'], 'https://math.example/webwork?id=4&set=HW_2')
        self.assertEqual(source['state'], 'unverified')
        self.assertIsNone(source['last_success_at'])
        self.assertIsNone(source['last_attempt_at'])
        self.assertEqual(self.store.coverage()['unverified_count'], 1)

    def test_first_seen_is_baseline_observation_not_created(self):
        self.register()
        events = self.store.record_check('one', [item()], checked_at=T1)
        self.assertEqual([e['type'] for e in events], ['first_seen'])
        self.assertIn('creation time is unknown', events[0]['evidence'])
        self.assertEqual(self.store.sources()[0]['state'], 'success')
        self.assertEqual(len(self.store.items()[0]['due_versions']), 1)
        self.assertEqual(self.store.record_check('one', [item()], checked_at=T2), [])
        self.assertEqual(len(self.store.events()), 1)
        self.assertEqual(self.store.items()[0]['revision'], 1)

    def test_discovery_requires_prior_complete_baseline(self):
        self.register()
        first = self.store.record_check('one', [item()], checked_at=T1, complete=False)
        second = self.store.record_check('one', [item(), item(external_id='lab-3')],
                                         checked_at=T2, complete=True)
        third = self.store.record_check('one', [item(), item(external_id='lab-3'), item(external_id='lab-4')],
                                        checked_at=T3)
        self.assertEqual(first[0]['type'], 'first_seen')
        self.assertEqual(second[0]['type'], 'first_seen')
        self.assertEqual(third[0]['type'], 'discovered')
        self.assertIn('creation time is unknown', third[0]['evidence'])

    def test_due_change_and_reversion_have_distinct_revision_events(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        changed = self.store.record_check('one', [item(due_at=DUE_B, raw_due_text='November 6 at 17:00')],
                                         checked_at=T2)
        reverted = self.store.record_check('one', [item()], checked_at=T3)
        self.assertEqual(changed[0]['type'], 'due_changed')
        self.assertEqual(reverted[0]['type'], 'due_changed')
        self.assertNotEqual(changed[0]['id'], reverted[0]['id'])
        self.assertEqual([e['revision'] for e in (changed[0], reverted[0])], [2, 3])
        current = self.store.items()[0]
        self.assertEqual(current['item_id'], changed[0]['item_id'])
        self.assertEqual([v['due_at'] for v in current['due_versions']],
            ['2026-11-03T12:00:00+00:00', '2026-11-06T12:00:00+00:00', '2026-11-03T12:00:00+00:00'])

    def test_status_change_is_observed_not_inferred(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        events = self.store.record_check('one', [item(status='closed')], checked_at=T2)
        self.assertEqual([e['type'] for e in events], ['status_changed'])
        self.assertEqual(events[0]['old_status'], 'open')
        self.assertEqual(events[0]['new_status'], 'closed')

    def test_unknown_date_preserves_raw_field_and_never_guesses(self):
        self.register()
        self.store.record_check('one', [item(due_at=None, raw_due_text='Maybe next Friday')], checked_at=T1)
        current = self.store.items()[0]
        self.assertIsNone(current['due_at'])
        self.assertEqual(current['raw_due_text'], 'Maybe next Friday')
        changed = self.store.record_check('one', [item(due_at=None, raw_due_text='Ask instructor next week')],
                                         checked_at=T2)
        self.assertEqual(changed[0]['type'], 'due_changed')
        self.assertIsNone(changed[0]['new_due_at'])

    def test_disappearance_retains_item_status_and_due_as_unknown_availability(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        last_success = self.store.sources()[0]['last_success_at']
        self.assertEqual(self.store.record_check('one', [], checked_at=T2), [])
        current = self.store.items()[0]
        self.assertEqual(current['availability'], 'unknown')
        self.assertEqual(current['status'], 'open')
        self.assertEqual(current['due_at'], '2026-11-03T12:00:00+00:00')
        self.assertEqual(self.store.sources()[0]['state'], 'partial')
        self.assertEqual(self.store.sources()[0]['last_success_at'], last_success)
        self.assertTrue(self.store.coverage()['has_unknown_items'])
        self.assertEqual(self.store.record_check('one', [item()], checked_at=T3), [])
        self.assertEqual(self.store.items()[0]['availability'], 'observed')
        self.assertEqual(self.store.sources()[0]['state'], 'success')

    def test_failure_and_empty_complete_success_are_different(self):
        self.register('failed')
        self.register('empty')
        self.store.record_failure('failed', 'Access unavailable', checked_at=T1)
        self.store.record_check('empty', [], checked_at=T1)
        sources = {s['source_id']: s for s in self.store.sources()}
        self.assertEqual(sources['failed']['state'], 'error')
        self.assertIsNone(sources['failed']['last_success_at'])
        self.assertEqual(sources['empty']['state'], 'success')
        self.assertIsNotNone(sources['empty']['last_success_at'])
        self.assertEqual(self.store.events(), [])

    def test_failure_preserves_last_success_and_sanitizes_credential_error(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        before = self.store.sources()[0]['last_success_at']
        self.store.record_failure('one', 'Request https://math.example/?token=not-a-real-secret failed; '
                                 'Authorization: Bearer fixture-only', checked_at=T2)
        source = self.store.sources()[0]
        self.assertEqual(source['last_success_at'], before)
        self.assertNotIn('not-a-real-secret', source['last_error'])
        self.assertNotIn('fixture-only', source['last_error'])
        self.assertEqual(source['state'], 'error')
        self.assertEqual(self.store.items()[0]['availability'], 'unknown')

    def test_failure_diagnostics_do_not_retain_quoted_or_spaced_api_keys(self):
        self.register()
        self.store.record_failure('one', 'API key: "fictional-key-value"; '
                                 '{"access_token": "fictional-token-value"}; LLM_fixture_only', checked_at=T1)
        error = self.store.sources()[0]['last_error']
        self.assertNotIn('fictional-key-value', error)
        self.assertNotIn('fictional-token-value', error)
        self.assertNotIn('LLM_fixture_only', error)

    def test_assignment_scope_never_claims_full_course_coverage(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        coverage = self.store.coverage()
        self.assertEqual(coverage['assignment_source_count'], 1)
        self.assertEqual(coverage['full_course_source_count'], 0)
        self.assertFalse(coverage['full_course_coverage_verified'])
        self.assertEqual(coverage['coverage_basis'], 'local_snapshots_only')
        self.assertIn('other course work is not covered', coverage['sources'][0]['note'])

    def test_partial_check_never_reports_success_or_advances_last_success(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1, complete=False)
        source = self.store.sources()[0]
        self.assertEqual(source['state'], 'partial')
        self.assertIsNone(source['last_success_at'])
        self.store.record_check('one', [item()], checked_at=T2)
        last_success = self.store.sources()[0]['last_success_at']
        self.store.record_check('one', [item()], checked_at=T3, complete=False)
        self.assertEqual(self.store.sources()[0]['last_success_at'], last_success)

    def test_same_titles_different_ids_courses_and_sources_remain_separate(self):
        self.register('a')
        self.register('b')
        self.store.record_check('a', [item(), item(external_id='another', course='MATH 162')], checked_at=T1)
        self.store.record_check('b', [item()], checked_at=T1)
        current = self.store.items()
        self.assertEqual(len(current), 3)
        self.assertEqual(len({i['item_id'] for i in current}), 3)

    def test_mark_read_is_explicit_persistent_and_idempotent(self):
        self.register()
        event = self.store.record_check('one', [item()], checked_at=T1)[0]
        self.assertEqual(len(self.store.events(unread_only=True)), 1)
        self.store.mark_read(event['id'])
        self.store.mark_read(event['id'])
        self.assertEqual(RadarStore(self.temp.name).events(unread_only=True), [])
        self.assertFalse(self.store.events()[0]['unread'])
        with self.assertRaises(ValueError):
            self.store.mark_read('unknown-event')

    def test_bad_items_rollback_entire_check(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        before = (self.store.sources(), self.store.items(), self.store.events())
        invalid = [item(external_id='good-new'), item(external_id='bad', due_at='2026-11-03T17:00')]
        with self.assertRaises(ValueError):
            self.store.record_check('one', invalid, checked_at=T2)
        self.assertEqual((self.store.sources(), self.store.items(), self.store.events()), before)

    def test_transaction_failure_rolls_back_snapshot_items_events_and_source(self):
        self.register()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_events BEFORE INSERT ON radar_events BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_check('one', [item()], checked_at=T1)
        self.assertEqual(self.store.items(), [])
        self.assertEqual(self.store.events(), [])
        self.assertEqual(self.store.sources()[0]['state'], 'unverified')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM radar_snapshots').fetchone()[0], 0)

    def test_import_registration_and_item_validation_are_atomic(self):
        invalid = envelope(items=[item(due_at=False)])
        with self.assertRaises(ValueError):
            self.store.import_snapshot(invalid)
        self.assertEqual(self.store.sources(), [])
        events = self.store.import_snapshot(envelope())
        self.assertEqual(events[0]['type'], 'first_seen')
        self.assertEqual(len(self.store.sources()), 1)
        old_name = self.store.sources()[0]['name']
        stale = envelope(checked_at='2026-10-27T12:00:00+05:00')
        stale['source']['name'] = 'Name must roll back too'
        with self.assertRaises(ValueError):
            self.store.import_snapshot(stale)
        self.assertEqual(self.store.sources()[0]['name'], old_name)

    def test_timestamps_require_timezone_and_normalize_equivalent_instants(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=dt.datetime(2026, 10, 28, 5, tzinfo=dt.timezone.utc))
        equivalent = item(due_at='2026-11-03T12:00:00Z')
        self.assertEqual(self.store.record_check('one', [equivalent], checked_at=T2), [])
        for value in (False, 123, '2026-10-28T14:00:00', dt.datetime(2026, 10, 28)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.record_check('one', [], checked_at=value)
        with self.assertRaisesRegex(ValueError, 'older'):
            self.store.record_failure('one', 'Old error', checked_at=T1)

    def test_source_credentials_and_auth_query_fields_are_never_saved(self):
        urls = ['http://math.example/', 'https://user:pass@math.example/',
            'https://math.example/?token=fixture', 'https://math.example/?sesskey=fixture',
            'https://math.example/?api_key=fixture', 'https://math.example/?effectiveUser=student',
            'https://math.example/?PASSWORD=fixture', 'https://math.example/?access%5Ftoken=fixture',
            'https://math.example/?session=fixture', 'https://math.example/?auth=fixture',
            'https://math.example/?id=1&id=2']
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.store.register_source('bad', 'webwork', 'Name', url)
        self.assertEqual(self.store.sources(), [])
        self.register()
        with self.assertRaises(ValueError):
            self.store.record_check('one', [item(source_url='https://math.example/?key=fixture')], checked_at=T1)
        self.assertEqual(self.store.items(), [])

    def test_source_identity_cannot_silently_change_scope_or_endpoint(self):
        source = self.register()
        renamed = self.store.register_source('one', 'webwork', 'Renamed', source['url'])
        self.assertEqual(renamed['name'], 'Renamed')
        for update in ({'scope': 'course'}, {'kind': 'gmail'}, {'url': 'https://other.example/'}):
            payload = {key: renamed[key] for key in ('source_id', 'kind', 'name', 'url', 'scope')}
            payload.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.store.register_source(**payload)

    def test_malformed_flags_duplicates_and_envelopes_do_not_write(self):
        self.register()
        cases = [([item(), item()], True), ([item(status=True)], True),
                 ([item(external_id=False)], True), ([item(due_at=True)], True),
                 ([item()], 1), ([{**item(), 'extra': True}], True)]
        for values, complete in cases:
            with self.subTest(items=values, complete=complete), self.assertRaises(ValueError):
                self.store.record_check('one', values, checked_at=T1, complete=complete)
        bad_envelope = envelope()
        bad_envelope['source'].pop('scope')
        for capture in ({}, {**envelope(), 'extra': True}, bad_envelope, envelope(checked_at=None)):
            with self.subTest(capture=capture), self.assertRaises(ValueError):
                self.store.import_snapshot(capture)
        self.assertEqual(self.store.items(), [])
        self.assertEqual(len(self.store.sources()), 1)

    def test_assignment_closing_time_is_not_a_due_date(self):
        self.register()
        original = 'Set closes on November 1, 2026, 11:59:00 PM +05.'
        self.store.record_check('one', [item(due_at=None, raw_due_text='',
            closes_at='2026-11-01T23:59:00+05:00', raw_close_text=original)], checked_at=T1)
        current = self.store.items()[0]
        self.assertIsNone(current['due_at'])
        self.assertEqual(current['raw_due_text'], '')
        self.assertEqual(current['closes_at'], '2026-11-01T18:59:00+00:00')
        self.assertEqual(current['raw_close_text'], original)

    def test_close_change_and_reversion_have_distinct_events_and_history(self):
        self.register()
        first = item(closes_at=DUE_A, raw_close_text='Closes November 3')
        second = item(closes_at=DUE_B, raw_close_text='Closes November 6')
        self.store.record_check('one', [first], checked_at=T1)
        changed = self.store.record_check('one', [second], checked_at=T2)
        reverted = self.store.record_check('one', [first], checked_at=T3)
        self.assertEqual([e['type'] for e in changed], ['closes_changed'])
        self.assertEqual([e['type'] for e in reverted], ['closes_changed'])
        self.assertNotEqual(changed[0]['id'], reverted[0]['id'])
        self.assertEqual(changed[0]['old_due_at'], changed[0]['new_due_at'])
        self.assertEqual(changed[0]['new_closes_at'], '2026-11-06T12:00:00+00:00')
        self.assertEqual(len(self.store.items()[0]['closes_versions']), 3)

    def test_older_capture_close_defaults_do_not_invent_a_change(self):
        self.register()
        self.store.record_check('one', [item()], checked_at=T1)
        with self.store.connection() as db:
            row = db.execute('SELECT item_id,payload FROM radar_items').fetchone()
            old_payload = json.loads(row['payload'])
            old_payload.pop('closes_at')
            old_payload.pop('raw_close_text')
            db.execute('UPDATE radar_items SET payload=? WHERE item_id=?',
                       (json.dumps(old_payload), row['item_id']))
        self.assertEqual(self.store.record_check('one', [item()], checked_at=T2), [])
        current = self.store.items()[0]
        self.assertEqual(current['revision'], 1)
        self.assertIsNone(current['closes_at'])
        self.assertEqual(current['raw_close_text'], '')

    def test_raw_due_and_close_text_are_preserved_without_normalizing_whitespace(self):
        self.register()
        self.store.record_check('one', [item(raw_due_text='  Next Friday\n', raw_close_text=' Closes soon\n')],
                                checked_at=T1)
        current = self.store.items()[0]
        self.assertEqual(current['raw_due_text'], '  Next Friday\n')
        self.assertEqual(current['raw_close_text'], ' Closes soon\n')

    def test_bad_close_field_rolls_back_entire_capture(self):
        invalid = envelope(items=[item(external_id='fine'), item(external_id='bad', closes_at=True)])
        with self.assertRaises(ValueError):
            self.store.import_snapshot(invalid)
        self.assertEqual(self.store.sources(), [])
        self.assertEqual(self.store.items(), [])


if __name__ == '__main__':
    unittest.main()
