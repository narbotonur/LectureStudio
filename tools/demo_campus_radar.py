"""Reproducible native Radar demo using synthetic loopback captures only.

No university request, Meta call, personal profile or Windows notification.
--capture renders actual UI previews and verifies idempotent replay.
"""
import argparse
import copy
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def snapshot():
    return {'source': {'source_id': 'ww.DEMO_ONLY_101', 'kind': 'webwork',
        'name': 'DEMO ONLY 101 — synthetic source',
        'url': 'https://webwork-new.nu.edu.kz/webwork2/DEMO_ONLY_101', 'scope': 'course'},
        'checked_at': '2026-10-28T10:00:00+05:00', 'complete': True,
        'items': [{'external_id': 'HW_1', 'title': 'Problem set 1', 'course': 'DEMO ONLY 101',
            'due_at': '2026-11-03T17:00:00+05:00',
            'raw_due_text': 'Due November 3, 2026, 5:00:00 PM +05.',
            'source_url': 'https://webwork-new.nu.edu.kz/webwork2/DEMO_ONLY_101/HW_1',
            'status': 'open'}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='radar-synthetic-demo-') as temporary:
        os.environ['ANNIE_DATA_DIR'] = temporary
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QHBoxLayout, QVBoxLayout, QWidget
        from PyQt5.QtTest import QTest
        from annie.campus_receiver import CampusReceiver
        from annie.gui.campus_radar import RadarPage
        from annie.gui.design import apply_theme
        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        window = QMainWindow()
        window.setWindowTitle('Lecture Studio · Synthetic Campus Radar demo')
        body = QWidget()
        layout = QVBoxLayout(body)
        notice = QLabel('SYNTHETIC LOOPBACK DEMO · no university access · no Meta request · no Windows alert')
        notice.setTextFormat(Qt.PlainText)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        page = RadarPage(root=temporary)
        for widget in (page.receiver_button, page.pairing, page.copy_pairing, page.import_button, page.open_button):
            widget.hide()
        page.connection_status.setText('Synthetic captures pass through the real authenticated local receiver. Source URLs are fictional course placeholders; no browser session is connected.')
        layout.addWidget(page, 1)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        feedback = QLabel('')
        feedback.setWordWrap(True)
        feedback.setTextFormat(Qt.PlainText)
        layout.addWidget(feedback)
        window.setCentralWidget(body)
        window.resize(1180, 820)
        apply_theme(window)
        token = secrets.token_urlsafe(32)
        bridge = CampusReceiver(page.store, token, page.capture_received.emit, port=0)
        bridge.start()
        data = snapshot()

        def send():
            data['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            connection = http.client.HTTPConnection('127.0.0.1', bridge.server.server_port, timeout=5)
            try:
                connection.request('POST', '/capture', json.dumps(data).encode('utf-8'),
                    {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                result = connection.getresponse()
                reply = json.loads(result.read())
                if result.status != 200:
                    raise ValueError('Synthetic local capture was rejected.')
                app.processEvents()
                feedback.setText(f"Synthetic capture accepted: {reply['changes']} new change(s). No remote source or model was contacted.")
                return reply
            finally:
                connection.close()

        def new_homework():
            if len(data['items']) == 1:
                item = copy.deepcopy(data['items'][0])
                item.update(external_id='HW_2', title='Problem set 2',
                            source_url='https://webwork-new.nu.edu.kz/webwork2/DEMO_ONLY_101/HW_2')
                data['items'].append(item)
            send()

        def change_due():
            data['items'][0].update(due_at='2026-11-06T17:00:00+05:00',
                raw_due_text='Due November 6, 2026, 5:00:00 PM +05.')
            send()

        for title, callback in [('Simulate new homework', new_homework),
                                ('Simulate deadline change', change_due), ('Repeat same capture', send)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, fn=callback: fn())
            buttons.addWidget(button)
        try:
            window.show()
            send()
            if args.capture:
                output = ROOT / 'review_artifacts/release-0.8.0'
                output.mkdir(parents=True, exist_ok=True)
                new_homework()
                change_due()
                before = len(page.store.events())
                assert send()['changes'] == 0
                assert len(page.store.events()) == before == 3
                page.events_list.setCurrentRow(0)
                QTest.qWait(200)
                window.grab().save(str(output / 'campus-radar-demo.png'))
                print(json.dumps({'kind': 'synthetic loopback and actual native UI',
                    'items': len(page.store.items()), 'events': before, 'repeat_added_events': 0,
                    'remote_requests': 0, 'model_calls': 0, 'personal_data_used': False}))
            else:
                return app.exec_()
        finally:
            bridge.stop()
            window.close()
            app.processEvents()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
