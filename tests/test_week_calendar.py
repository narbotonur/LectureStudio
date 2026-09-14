import datetime as dt
import time
import unittest
from unittest.mock import patch

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie.gui.week_calendar import build_blocks, EliteTimetableView, TZ


MONDAY = dt.date(2026, 9, 7)


def event(start, end, title='MATH 251'):
    return dict(summary=title, start={'dateTime': start}, end={'dateTime': end})


class CalendarLayoutTests(unittest.TestCase):
    def test_overlaps_get_separate_lanes_but_adjacent_events_share_a_lane(self):
        blocks = build_blocks([
            event('2026-09-07T09:00:00+05:00', '2026-09-07T10:15:00+05:00'),
            event('2026-09-07T09:30:00+05:00', '2026-09-07T10:00:00+05:00'),
            event('2026-09-07T10:15:00+05:00', '2026-09-07T11:00:00+05:00'),
        ], MONDAY)
        self.assertEqual((blocks[0].start, blocks[0].end), (540, 615))
        self.assertEqual((blocks[0].lanes, blocks[1].lanes, blocks[2].lanes), (2, 2, 1))
        self.assertNotEqual(blocks[0].lane, blocks[1].lane)

    def test_timezone_midnight_weekends_and_exclusive_all_day_end(self):
        blocks = build_blocks([
            event('2026-09-11T18:30:00Z', '2026-09-11T20:30:00Z'),
            dict(summary='Weekend', start={'date': '2026-09-12'}, end={'date': '2026-09-14'}),
            dict(summary='Cancelled', status='cancelled', start={'date': '2026-09-12'}),
            dict(summary='Invalid'),
        ], MONDAY)
        self.assertEqual([(b.day, b.start, b.end) for b in blocks if not b.all_day],
                         [(4, 1410, 1440), (5, 0, 90)])
        self.assertEqual([b.day for b in blocks if b.all_day], [5, 6])


class CalendarLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_network_is_backgrounded_and_repeat_tab_visits_use_cache(self):
        view = EliteTimetableView()
        view.monday = MONDAY
        events = [event('2026-09-07T09:00:00+05:00', '2026-09-07T10:00:00+05:00')]

        def slow_fetch(*args, **kwargs):
            time.sleep(0.15)
            return events
        try:
            with patch('annie.calendar_service.is_connected', return_value=True), \
                    patch('annie.calendar_service.list_events', side_effect=slow_fetch) as fetch:
                start = time.monotonic()
                view._refresh()
                self.assertLess(time.monotonic() - start, 0.12)
                self.assertTrue(view.has_running_job())
                view._refresh()  # No duplicate concurrent request.
                deadline = time.monotonic() + 3
                while view.has_running_job() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertFalse(view.has_running_job())
                view._refresh()
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(len(view.grid.blocks), 1)
        finally:
            if view._worker:
                view._worker.wait(3000)
                self.app.processEvents()
            view.deleteLater()
