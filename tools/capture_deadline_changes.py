"""Render actual native UI against an isolated fictional correction, no network."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    output = ROOT / 'review_artifacts' / 'deadline-native'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='deadline-native-preview-') as root:
        os.environ['ANNIE_DATA_DIR'] = root
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from annie.gui.meeting_window import MeetingWindow
        from annie.obligations import ObligationStore
        from annie.deadlines import DeadlineStore
        from tools.check_deadline_workflow import SEGMENTS, SOURCE, NEW, seed_old, fixture_response
        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        app.setQuitOnLastWindowClosed(False)
        store = ObligationStore(root)
        seed_old(store)
        with patch.object(MeetingWindow, '_load_classes'), \
             patch('annie.calendar_service.is_connected', return_value=False), \
             patch('annie.updates.UpdateService.start_automatic'), \
             patch('annie.gui.study_timer.StudyTimerPage.sync_pending'):
            window = MeetingWindow()
            from annie.planner import TZ
            window.today_page.clock = lambda: dt.datetime(2026, 10, 27, 9, 0, tzinfo=TZ)
            window._entrance_played = True
            window.show()
            window.operation_status.setText('OFFLINE FICTIONAL PREVIEW · supplied response · no model call')
            window._transcript_segments = SEGMENTS
            window._lecture_source_name = SOURCE
            window._lecture_date = dt.date(2026, 10, 27)
            window.subject_input.setText('CSCI 231')
            window.transcript_area.setPlainText('\n'.join(s['text'] for s in SEGMENTS))
            page = window.review_page
            page.analysis_generator = lambda *_: fixture_response(store.list_current('CSCI 231'))
            window._switch_tab(10)
            page.analyze()
            until = time.monotonic() + 10
            while page.has_running_job() and time.monotonic() < until:
                QTest.qWait(10)
            assert not page.has_running_job()
            assert page.findings.count() == 1
            assert all(s['text'] in page.evidence.toPlainText() for s in SEGMENTS)
            for width in (1180, 720):
                window.resize(width, 820)
                window._switch_tab(10)
                QTest.qWait(200)
                window.grab().save(str(output / f'review-{width}.png'))
                window._switch_tab(9)
                QTest.qWait(200)
                window.grab().save(str(output / f'today-pending-{width}.png'))
            window._switch_tab(10)
            page.confirm_date.setChecked(True)
            page._approve()
            current = store.list_current()[0]
            assert current['due_at'] == NEW
            assert len(store.history(current['assignment_id'])) == 2
            assert len(DeadlineStore(root).load()) == 1
            for width in (1180, 720):
                window.resize(width, 820)
                window._switch_tab(9)
                QTest.qWait(200)
                window.grab().save(str(output / f'today-approved-{width}.png'))
            window.close()
            app.processEvents()
    report = {'kind': 'actual PyQt UI, offline fictional model response', 'screenshots': 6,
              'one_active_deadline': True, 'retained_versions': 2,
              'explicit_confirmation': True, 'personal_data_used': False}
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
