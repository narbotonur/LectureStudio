"""Create portfolio screenshots from a disposable, fictional Studio profile."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'assets'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _block(kind, title, start, minutes, detail=''):
    end = start + dt.timedelta(minutes=minutes)
    return {
        'id': uuid.uuid4().hex[:24],
        'kind': kind,
        'title': title,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'detail': detail,
    }


def _seed_profile(profile):
    from annie.gpa_tracker import GpaStore
    from annie.habits import HabitStore, TZ
    from annie.planner import PlannerStore

    gpa = GpaStore()
    algorithms = gpa.add_course('Algorithms', 6, 90)
    gpa.add_assessment(algorithms['id'], 'Problem sets', 25, 94)
    gpa.add_assessment(algorithms['id'], 'Midterm', 25, 88)
    gpa.add_assessment(algorithms['id'], 'Final exam', 50, None)
    discrete = gpa.add_course('Discrete Mathematics', 5, 85)
    gpa.add_assessment(discrete['id'], 'Quizzes', 20, 91)
    gpa.add_assessment(discrete['id'], 'Homework', 30, 86)
    gpa.add_assessment(discrete['id'], 'Final exam', 50, None)
    writing = gpa.add_course('Academic Writing', 4, 85)
    gpa.add_assessment(writing['id'], 'Research proposal', 30, 82)
    gpa.add_assessment(writing['id'], 'Final paper', 70, None)

    today = dt.datetime.now(TZ).date()
    monday = today - dt.timedelta(days=today.weekday())
    created = dt.datetime.combine(monday - dt.timedelta(days=14), dt.time(), TZ).timestamp()
    habits = HabitStore()
    review = habits.add('Review lecture notes', 'minutes', 30, '', 127, '18:00', created)
    problems = habits.add('Solve practice problems', 'count', 10, 'problems', 31, '19:00', created)
    reading = habits.add('Read before class', 'done', 1, '', 31, '08:00', created)
    for offset in range(today.weekday() + 1):
        day = monday + dt.timedelta(days=offset)
        habits.set_progress(reading['id'], day, 1)
        habits.set_progress(review['id'], day, 30 if offset % 2 == 0 else 20)
        habits.set_progress(problems['id'], day, 10 if offset < today.weekday() else 6)

    blocks = []
    for offset in range(7):
        day = monday + dt.timedelta(days=offset)
        blocks.append(_block('prayer', 'Prayer - Dhuhr',
                             dt.datetime.combine(day, dt.time(12, 15), TZ), 30))
        blocks.append(_block('prayer', 'Prayer - Asr',
                             dt.datetime.combine(day, dt.time(16, 15), TZ), 30))
    blocks.extend([
        _block('habit', 'Read before class',
               dt.datetime.combine(monday, dt.time(8, 0), TZ), 30),
        _block('study', 'Algorithms - graph practice',
               dt.datetime.combine(monday, dt.time(17, 0), TZ), 50,
               'Priority: upcoming midterm'),
        _block('study', 'Discrete Mathematics - proofs',
               dt.datetime.combine(monday + dt.timedelta(days=1), dt.time(17, 0), TZ), 50),
        _block('habit', 'Review lecture notes',
               dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(18, 0), TZ), 30),
        _block('study', 'Academic Writing - outline',
               dt.datetime.combine(monday + dt.timedelta(days=3), dt.time(17, 30), TZ), 50),
        _block('jumuah', 'Jumuah',
               dt.datetime.combine(monday + dt.timedelta(days=4), dt.time(12, 30), TZ), 90),
        _block('study', 'Algorithms - mock exam',
               dt.datetime.combine(monday + dt.timedelta(days=5), dt.time(10, 0), TZ), 100),
        _block('study', 'Weekly review',
               dt.datetime.combine(monday + dt.timedelta(days=6), dt.time(10, 30), TZ), 50),
    ])
    PlannerStore(profile).save_week(monday, blocks)
    return monday, blocks


def _calendar_events(monday, tz):
    result = []
    for offset, hour, title in (
            (0, 10, 'Algorithms'), (1, 9, 'Discrete Mathematics'),
            (2, 11, 'Academic Writing'), (3, 10, 'Algorithms')):
        start = dt.datetime.combine(monday + dt.timedelta(days=offset), dt.time(hour), tz)
        result.append({
            'summary': title,
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': (start + dt.timedelta(minutes=75)).isoformat()},
        })
    return result


def _wait(app, milliseconds=260):
    from PyQt5.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec_()
    app.processEvents()


def _capture(window, app, name):
    _wait(app)
    path = OUTPUT / name
    if not window.grab().save(str(path), 'PNG'):
        raise RuntimeError(f'Could not save {path}')
    print(f'Created {path.relative_to(ROOT)}')
    return path


def _make_gif(paths):
    from PIL import Image

    slides = []
    for path in paths:
        with Image.open(path) as image:
            slide = image.convert('RGB')
            slide.thumbnail((960, 600), Image.Resampling.LANCZOS)
            canvas = Image.new('RGB', (960, 600), '#111310')
            canvas.paste(slide, ((960 - slide.width) // 2, (600 - slide.height) // 2))
            slides.append(canvas)

    frames, durations = [], []
    for index, slide in enumerate(slides):
        frames.append(slide)
        durations.append(1500)
        target = slides[(index + 1) % len(slides)]
        for step in (0.25, 0.5, 0.75):
            frames.append(Image.blend(slide, target, step))
            durations.append(80)
    frames = [frame.quantize(colors=160, method=Image.Quantize.MEDIANCUT) for frame in frames]
    path = OUTPUT / 'lecture-studio-demo.gif'
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=2)
    print(f'Created {path.relative_to(ROOT)} ({path.stat().st_size / 1024 / 1024:.1f} MiB)')


def main():
    if sys.platform not in ('win32', 'darwin'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('PYTHONUTF8', '1')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lecture-studio-portfolio-') as temp:
        profile = Path(temp).resolve()
        os.environ['ANNIE_DATA_DIR'] = str(profile)
        monday, blocks = _seed_profile(profile)

        from PyQt5.QtWidgets import QApplication
        from annie.gui.meeting_window import MeetingWindow
        from annie.habits import TZ

        app = QApplication.instance() or QApplication([])
        app.setApplicationName('Lecture Studio Portfolio Capture')
        window = MeetingWindow()
        window._entrance_played = True
        window.resize(1280, 800)
        window.show()
        _wait(app, 80)

        window.class_picker.addItem('[10:00] Algorithms', 'Algorithms')
        window.class_picker.setCurrentIndex(window.class_picker.count() - 1)
        window.subject_input.setText('Algorithms - Graph Traversal')
        window.user_scratchpad.setPlainText(
            'Key idea: BFS explores a graph level by level.\n\n'
            '- Queue invariant determines shortest paths\n'
            '- Compare adjacency list and matrix costs\n'
            '- Revisit the proof for O(V + E)')
        window.notes_area.setPlainText(
            'BREADTH-FIRST SEARCH\n\n'
            'BFS maintains a frontier in a FIFO queue. Every vertex is discovered '
            'at most once, so an adjacency-list implementation runs in O(V + E).\n\n'
            'WHY IT MATTERS\n'
            'In an unweighted graph, the first discovered path has the minimum '
            'number of edges. The parent relation forms a BFS tree.\n\n'
            'REVIEW NEXT\n'
            '1. Prove the distance invariant.\n'
            '2. Trace BFS on a disconnected graph.\n'
            '3. Contrast the data structures used by BFS and DFS.')
        window.transcript_area.setPlainText(
            'Today we connect the queue invariant to shortest paths in unweighted '
            'graphs. When a vertex first enters the queue, all shorter paths have '
            'already been considered...')
        window.operation_status.setText('Recording - 24:18 - live transcription')
        window.record_btn.setText('Stop recording')
        window.record_btn.setProperty('state', 'recording')
        window.record_btn.style().unpolish(window.record_btn)
        window.record_btn.style().polish(window.record_btn)
        window.signal_widget.set_active(True)
        window.signal_widget._level = 0.68
        window.signal_widget._target_level = 0.68
        window.signal_widget._is_hearing = True
        notes = _capture(window, app, 'studio-notes.png')

        window._switch_tab(8)
        window.planner_page._display(blocks, _calendar_events(monday, TZ))
        window.planner_page.status.setText(
            'Plan saved locally - 5h 00m focused study around fixed commitments.')
        planner = _capture(window, app, 'weekly-planner.png')

        window._switch_tab(6)
        window.gpa_page.reload()
        gpa = _capture(window, app, 'gpa-tracker.png')

        window._switch_tab(7)
        window.habits_page.reload()
        habits = _capture(window, app, 'habit-tracker.png')

        _make_gif([notes, planner, gpa, habits])
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
