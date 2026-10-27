"""Render fictional tracker fixtures without opening a personal profile."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    destination = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('review_artifacts/trackers').resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='studio-tracker-preview-') as temporary:
        os.environ['ANNIE_DATA_DIR'] = temporary
        os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        from annie.gui.design import apply_theme
        from annie.gui.gpa_tracker import GpaTrackerPage
        from annie.gui.habit_tracker import HabitTrackerPage
        from annie.gpa_tracker import GpaStore
        from annie.habits import HabitStore, TZ
        import datetime as dt

        app = QApplication.instance() or QApplication([])
        habits = HabitStore()
        day = dt.datetime.now(TZ).date()
        for name, kind, target, unit, group, anchor, low, high, duration, progress in (
            ('Quran reading', 'minutes', 25, '', 'morning', 'after_fajr', 5, 40, 25, 10),
            ('Understand two pages', 'count', 2, 'pages', 'morning', 'after_fajr', 1, 3, 15, 2),
            ('Listen to an audiobook', 'minutes', 20, '', 'flexible', 'commute', 5, 30, 20, 5),
            ('Read a book', 'minutes', 25, '', 'evening', 'before_sleep', 10, 40, 25, 0),
        ):
            habit = habits.add(name, kind, target, unit, now=1, routine=group, anchor=anchor,
                               minimum_target=low, ideal_target=high, duration_minutes=duration)
            habits.set_progress(habit['id'], day, progress)
        grades = GpaStore()
        for name, credits in (('CSCI 231', 6), ('MATH 251', 6), ('WCS 210', 6)):
            course = grades.add_course(name, credits)
            grades.add_assessment(course['id'], 'Quiz 1', 10, '7/10')
            grades.add_assessment(course['id'], 'Midterm', 30, '43/50')
            grades.add_assessment(course['id'], 'Assignments', 20)
            grades.add_assessment(course['id'], 'Final', 40)
        for name, page in (('routines', HabitTrackerPage(store=habits)),
                           ('academics', GpaTrackerPage(store=grades))):
            page.resize(1180, 780)
            apply_theme(page)
            page.setAttribute(Qt.WA_DontShowOnScreen)
            page.show()
            app.processEvents()
            page.grab().save(str(destination / f'{name}.png'))
            page.close()
        print(destination)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
