"""Exercise the real loopback transport with isolated, synthetic coursework."""
import copy
import http.client
import json
import tempfile
import unittest
from pathlib import Path
import sys

from annie.campus_radar import RadarStore
from annie.campus_receiver import CampusReceiver, NotificationLedger


def snapshot():
    return {'source': {'source_id': 'ww.TEST_101', 'kind': 'webwork', 'name': 'TEST 101',
            'url': 'https://webwork-new.nu.edu.kz/webwork2/TEST_101', 'scope': 'course'},
            'checked_at': '2026-10-28T10:00:00+05:00', 'complete': True,
            'items': [{'external_id': 'HW_1', 'title': 'Test assignment', 'course': 'TEST 101',
                'due_at': '2026-11-03T23:59:00+05:00', 'raw_due_text': 'Due November 3, 2026, 11:59:00 PM +05.',
                'source_url': 'https://webwork-new.nu.edu.kz/webwork2/TEST_101/HW_1', 'status': 'open'}]}


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RadarStore(self.temp.name)
        self.signals = []
        self.receiver = CampusReceiver(self.store, 'test-token', lambda: self.signals.append(True), port=0)
        self.receiver.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.receiver.stop)

    def post(self, body=None, path='/capture', **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.receiver.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        options = {'Authorization': 'Bearer test-token', 'Content-Type': 'application/json', **headers}
        raw = body if isinstance(body, str) else json.dumps(body or snapshot())
        connection.request('POST', path, raw.encode('utf-8'), options)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_real_http_capture_and_authenticated_failure(self):
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(len(self.signals), 1)
        before = self.store.sources()[0]['last_success_at']
        self.assertEqual(self.post({'source_id': 'ww.TEST_101', 'reason': 'Signed out',
            'checked_at': '2026-10-28T11:00:00+05:00'}, '/failure')[0], 200)
        source = self.store.sources()[0]
        self.assertEqual(source['state'], 'error')
        self.assertEqual(source['last_success_at'], before)

    def test_auth_origin_host_and_size_block_writes(self):
        for options in ({'Authorization': ''}, {'Origin': 'https://hostile.example'},
                        {'Origin': 'null'}, {'Host': 'localhost:8768'},
                        {'Content-Type': 'text/plain'}, {'Content-Length': '1000001'}):
            status, _ = self.post(**options)
            self.assertIn(status, (400, 401, 403, 413))
        self.assertEqual(self.store.sources(), [])

    def test_extension_origin_accepted(self):
        self.assertEqual(self.post(Origin='chrome-extension://' + 'a' * 32)[0], 200)

    def test_duplicate_json_and_other_course_links_rejected_atomically(self):
        self.assertEqual(self.post('{"source":{},"source":{}}')[0], 400)
        for url in ('https://attacker.example/webwork2/TEST_101/HW_1',
                    'https://webwork-new.nu.edu.kz/webwork2/OTHER/HW_1',
                    'https://webwork-new.nu.edu.kz/webwork2/TEST_101/HW_1?effectiveUser=private'):
            data = snapshot()
            data['items'][0]['source_url'] = url
            self.assertEqual(self.post(data)[0], 400)
        self.assertFalse(self.store.sources())

    def test_failed_capture_never_claims_success(self):
        data = snapshot()
        data['items'][0]['due_at'] = 'ambiguous'
        self.assertEqual(self.post(data)[0], 400)
        self.assertFalse(self.store.sources())
        self.assertFalse(self.signals)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RadarStore(self.temp.name)

    def test_baseline_summary_diff_retry_and_restart_dedup(self):
        data = snapshot()
        second = copy.deepcopy(data['items'][0])
        second.update(external_id='HW_2', title='Test assignment 2',
                      source_url='https://webwork-new.nu.edu.kz/webwork2/TEST_101/HW_2')
        data['items'].append(second)
        self.store.import_snapshot(data)
        ledger = NotificationLedger(self.store)
        ledger.deliver(lambda *_: False)
        delivered = []
        def send(title, text):
            delivered.append((title, text))
            return True
        ledger.deliver(send)
        self.assertEqual(len(delivered), 1)
        self.assertIn('baseline', delivered[0][0])
        self.assertIn('2 assignment', delivered[0][1])
        self.assertEqual(len(self.store.events(unread_only=True)), 2)
        NotificationLedger(self.store).deliver(send)
        self.assertEqual(len(delivered), 1)
        data['checked_at'] = '2026-10-28T11:00:00+05:00'
        data['items'][0]['due_at'] = '2026-11-04T23:59:00+05:00'
        data['items'][0]['raw_due_text'] = 'Due November 4, 2026, 11:59:00 PM +05.'
        self.store.import_snapshot(data)
        NotificationLedger(self.store).deliver(send)
        self.assertEqual(len(delivered), 2)
        self.assertIn('Due date changed', delivered[-1][1])
        self.store.import_snapshot(data)
        ledger.deliver(send)
        self.assertEqual(len(delivered), 2)


class PairingTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'DPAPI check; noninteractive CI must not prompt for Keychain')
    def test_pairing_survives_restart_without_plaintext_disk_copy(self):
        from annie.campus_receiver import pairing_token
        from annie.secure_storage import delete_secret
        with tempfile.TemporaryDirectory() as root:
            token = pairing_token(Path(root))
            self.assertEqual(pairing_token(Path(root)), token)
            self.assertNotIn(token.encode(), (Path(root) / 'campus-pairing.dpapi').read_bytes())
            delete_secret(Path(root) / 'campus-pairing.dpapi')
