"""Capture native lab UI, replaying a saved fictional live spec or offline fixture.

Never performs a model call or reads personal lecture data.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    output = ROOT / 'review_artifacts/executable-native'
    output.mkdir(parents=True, exist_ok=True)
    live = ROOT / 'review_artifacts/executable-lecture/live-spec.json'
    with tempfile.TemporaryDirectory(prefix='executable-native-preview-') as profile:
        os.environ['ANNIE_DATA_DIR'] = profile
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from annie.gui.meeting_window import MeetingWindow
        from annie.executable_lectures import generate_lab, LabStore
        from annie.lecture_actions import ActionStore, extract_actions, transcript_fingerprint
        from tools.check_executable_lecture import SEGMENTS, SOURCE, fixture_response
        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        app.setQuitOnLastWindowClosed(False)
        spec = json.loads(live.read_text(encoding='utf-8')) if live.exists() else generate_lab(
            SEGMENTS, 'CSCI 231', SOURCE, generator=fixture_response)
        actions = ActionStore(profile)
        ref = spec['evidence'][0]
        study = {'type': 'key_concept', 'summary': 'Explore BFS', 'quote': ref['quote'],
                 't_start': ref['start'], 't_end': ref['end'], 'source': ref['source'],
                 'confidence': 0, 'due_at': None, 'minutes': 25,
                 'suggested_action': 'Explore the BFS graph in an executable lab.'}
        scan = extract_actions(spec['source_snapshot'], generator=lambda *_: json.dumps({'findings': [study]}))
        actions.add_scan(scan, spec['source_snapshot'], spec['course'], spec['source_name'])
        action_id = actions.list_actions()[0]['id']
        actions.approve(action_id)
        with patch.object(MeetingWindow, '_load_classes'), \
             patch('annie.calendar_service.is_connected', return_value=False), \
             patch('annie.updates.UpdateService.start_automatic'), \
             patch('annie.gui.study_timer.StudyTimerPage.sync_pending'):
            window = MeetingWindow()
            window._entrance_played = True
            from annie.planner import TZ
            import datetime as dt
            window.today_page.clock = lambda: dt.datetime(2026, 10, 28, 9, tzinfo=TZ)
            window._transcript_segments = spec['source_snapshot']
            window._lecture_source_name = spec['source_name']
            window.subject_input.setText(spec['course'])
            window.show()
            window._switch_tab(11)
            page = window.lab_page
            window._switch_tab(9)
            from PyQt5.QtWidgets import QPushButton
            launch = next(b for b in window.today_page.findChildren(QPushButton)
                          if b.text() == 'Open executable lab')
            launch.click()
            assert page.action_id == action_id
            assert page._fingerprint == spec['fingerprint']
            page.load_lab(spec)
            window.operation_status.setText('FICTIONAL UI REPLAY · no API call in this capture')

            def capture(name, width, focus=None):
                window.resize(width, 820)
                if focus is not None:
                    page.scroll.ensureWidgetVisible(focus)
                QTest.qWait(180)
                assert window.width() == width, (name, window.width())
                assert not page.scroll.horizontalScrollBar().isVisible(), name
                assert window.grab().save(str(output / (name + '.png')))

            capture('source-review-1180', 1180, page.evidence)
            page.review_source.setChecked(True)
            page.use_lab()
            assert page.lab_id
            page.slider.setValue(len(page.result['steps']) - 1)
            capture('equal-edges-1180', 1180, page.canvas)
            graph = spec['graph']
            start, target = graph['start'], graph['target']
            middle = next(n for n in graph['nodes'] if n not in (start, target))
            page.edges_input.setPlainText(f'{start} {target} 10\n{start} {middle} 1\n{middle} {target} 1')
            page.weighted.setChecked(True)
            page.apply_edits()
            assert page.result['bfs_cost'] == 10 and page.result['shortest_cost'] == 2
            page.slider.setValue(len(page.result['steps']) - 1)
            capture('weighted-1180', 1180, page.canvas)
            capture('weighted-720', 720, page.canvas)
            page.predicted_cost.setValue(10)
            page.check_prediction()
            assert 'passed' in page.attempt_feedback.text()
            capture('prediction-720', 720, page.check_button)
            assert len(LabStore(profile).attempts(page.lab_id)) == 1
            assert LabStore(profile).attempts(page.lab_id)[0]['action_id'] == action_id
            assert actions.approved_tasks()[0]['done'] == 0
            window.close()
            app.processEvents()
    report = {'mode': 'native UI replay of saved fictional live spec' if live.exists() else 'native supplied offline fixture',
              'new_api_calls': 0, 'personal_data_used': False, 'screenshots': 5,
              'weighted_bfs_cost': 10, 'weighted_shortest_cost': 2,
              'prediction_saved': True, 'horizontal_overflow_720': False}
    report.update(today_saved_source_link=True, study_action_not_automatically_completed=True)
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
