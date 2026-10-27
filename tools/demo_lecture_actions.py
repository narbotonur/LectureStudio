"""Fictional offline Review demo. Never reads the signed-in user profile.

python tools/demo_lecture_actions.py --check
python tools/demo_lecture_actions.py

The mock response deliberately contains an invented quote, demonstrating that
evidence rejection executes locally. This is NOT an evaluation of a live model.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


SEGMENTS = [
    {'start': 0, 'end': 12, 'text': 'The lab report is due November 3, 2026 at 17:00.', 'source': 'Fictional demo transcript'},
    {'start': 12, 'end': 24, 'text': 'The exam will include stack frames and register preservation.', 'source': 'Fictional demo transcript'},
    {'start': 24, 'end': 36, 'text': 'Practice tracing one nested procedure call before next class.', 'source': 'Fictional demo transcript'},
]


def response(*_):
    kinds = ['deadline', 'exam_hint', 'review_task']
    titles = ['Lab report', 'Review stack frames', 'Trace a nested procedure call']
    findings = []
    for index, segment in enumerate(SEGMENTS):
        findings.append({'type': kinds[index], 'summary': titles[index], 'quote': segment['text'],
                         'source': segment['source'], 't_start': segment['start'], 't_end': segment['end'],
                         'confidence': .9, 'due_at': '2026-11-03T17:00+05:00' if index == 0 else None,
                         'minutes': 25, 'suggested_action': titles[index]})
    findings.append({**findings[1], 'quote': 'The final exam is cancelled. Do not study.'})
    return json.dumps({'findings': findings})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Run the offline evidence/approval smoke check.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='lecture-review-demo-') as root:
        os.environ['ANNIE_DATA_DIR'] = root
        from annie.lecture_actions import ActionStore, extract_actions
        store = ActionStore(root)
        lecture_date = dt.date(2026, 10, 27)
        if args.check:
            from annie.deadlines import DeadlineStore
            result = extract_actions(SEGMENTS, generator=response, lecture_date=lecture_date)
            store.add_scan(result, SEGMENTS, 'CSCI demo', 'Fictional demo', lecture_date)
            for item in store.list_actions('pending'):
                store.approve(item['id'])
                store.approve(item['id'])
            report = {'mode': 'offline fictional fixture; no model call',
                      'verified_quotes': len(result.actions), 'rejected_unsupported': result.rejected_count,
                      'local_deadlines': len(DeadlineStore(root).load()),
                      'local_study_actions': len(store.approved_tasks())}
            print(json.dumps(report, indent=2))
            return 0 if tuple(report.values())[1:] == (3, 1, 1, 2) else 1
        from PyQt5.QtWidgets import QApplication
        from annie.gui.design import apply_theme
        from annie.gui.lecture_review import LectureReviewPage
        app = QApplication.instance() or QApplication(sys.argv[:1])
        page = LectureReviewPage(store=store, generator=response)
        page.setWindowTitle('Lecture Studio · OFFLINE FICTIONAL DEMO · No Meta call')
        page.resize(1100, 720)
        page.set_transcript(SEGMENTS, 'CSCI demo', 'Fictional demo', lecture_date)
        page.status.setText('OFFLINE FICTIONAL DEMO. Analyze uses a fixed fixture, not a Meta model.')
        apply_theme(page)
        page.show()
        return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
