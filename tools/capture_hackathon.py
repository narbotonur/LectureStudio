"""Capture and exercise the hackathon workflow using fictional offline data only."""
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
    output = ROOT / 'review_artifacts' / 'hackathon'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='studio-hackathon-preview-') as profile:
        os.environ['ANNIE_DATA_DIR'] = profile
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from annie.gui.meeting_window import MeetingWindow
        from annie.gpa_tracker import GpaStore
        from annie.habits import HabitStore, TZ
        from annie.lecture_actions import ActionStore
        from annie.deadlines import DeadlineStore
        from tools.demo_lecture_actions import SEGMENTS, response

        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        app.setQuitOnLastWindowClosed(False)
        course = GpaStore().add_course('CSCI 231', 6, 85)
        grades = GpaStore()
        grades.add_assessment(course['id'], 'Quiz 1', 20, '14/20')
        grades.add_assessment(course['id'], 'Midterm', 30, '85%')
        grades.add_assessment(course['id'], 'Final exam', 50)
        habits = HabitStore()
        habits.add('Read Quran', 'minutes', 20, '', 127, routine='morning', anchor='after_fajr',
                   minimum_target=5, ideal_target=30, duration_minutes=20)
        habits.add('Read two pages', 'count', 2, 'pages', 127, routine='evening',
                   minimum_target=1, ideal_target=4, duration_minutes=15)
        with patch.object(MeetingWindow, '_load_classes'), \
             patch('annie.calendar_service.is_connected', return_value=False), \
             patch('annie.updates.UpdateService.start_automatic'), \
             patch('annie.gui.study_timer.StudyTimerPage.sync_pending'):
            window = MeetingWindow()
            window.today_page.clock = lambda: dt.datetime.now(TZ).replace(hour=9, minute=0)
            window._entrance_played = True
            window.setWindowTitle('Lecture Studio · OFFLINE FICTIONAL DEMO')
            window.resize(1180, 820)
            window.show()
            window.operation_status.setText('OFFLINE FICTIONAL DEMO · fixed responses · no model call')
            window._transcript_segments = SEGMENTS
            window._lecture_source_name = 'Fictional demo'
            window.subject_input.setText('CSCI 231')
            window.transcript_area.setPlainText('\n'.join(s['text'] for s in SEGMENTS))
            window.review_page.generator = response
            window._switch_tab(10)
            window.review_page.set_transcript(SEGMENTS, 'CSCI 231', 'Fictional demo', dt.date(2026, 10, 27))
            window.review_page.analyze()
            end = time.monotonic() + 10
            while window.review_page.has_running_job() and time.monotonic() < end:
                QTest.qWait(20)
            if window.review_page.has_running_job():
                raise RuntimeError('Offline review scan did not finish.')
            store = ActionStore()
            findings = store.list_actions('pending')
            if len(findings) != 3:
                raise RuntimeError('Expected three findings; check Review extraction.')

            def capture(name, index):
                window._switch_tab(index)
                QTest.qWait(350)
                if not window.grab().save(str(output / f'{name}.png')):
                    raise RuntimeError(f'Could not save {name}.')

            capture('review', 10)
            for item in findings:
                store.approve(item['id'])
            if len(store.approved_tasks()) != 2 or len(DeadlineStore().load()) != 1:
                raise RuntimeError('Approved actions did not reach local stores.')
            now = dt.datetime.now(TZ)
            start = now.replace(hour=10, minute=0, second=0, microsecond=0)
            window.today_page.set_events([{'summary': 'CSCI 231 · Lecture',
                'start': {'dateTime': start.isoformat()},
                'end': {'dateTime': (start + dt.timedelta(minutes=75)).isoformat()}}])
            capture('today', 9)
            capture('academics', 6)
            capture('routines', 7)
            window.resize(720, 820)
            capture('narrow-today', 9)
            capture('narrow-review', 10)
            capture('narrow-academics', 6)
            capture('narrow-routines', 7)
            window._start_daily_study('CSCI 231')
            active = window.study_page.store.active()
            if not active or active['subject'] != 'CSCI 231' or active['sync_state'] != 'local':
                raise RuntimeError('Today did not start a local study session.')
            window.study_page.store.transition(active['id'], 'end')
            window.close()
            app.processEvents()
        report = {'mode': 'offline fictional fixture, no model calls',
                  'verified_findings': 3, 'rejected_invented_quote': 1,
                  'approved_deadlines': 1, 'approved_study_tasks': 2,
                  'today_starts_local_timer': True, 'screenshots': 8}
        print(json.dumps(report, indent=2))
        from annie.secure_storage import atomic_write
        atomic_write(output / 'workflow-check.json', json.dumps(report, indent=2).encode())


if __name__ == '__main__':
    main()
