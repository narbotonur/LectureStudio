import datetime
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annie import calendar_service
from annie import config as cfg
from annie.meeting_prompt import (
    MeetingPrompt, MeetingPromptController, detect_conference_window,
    start_studio_transcription,
)


class ConferenceDetectionTests(unittest.TestCase):
    def test_detects_zoom_meeting(self):
        result = detect_conference_window([
            ('Zoom Meeting', 'Zoom.exe', 101),
        ])
        self.assertEqual(result.provider, 'Zoom')

    def test_detects_teams_call_but_not_ordinary_chat(self):
        self.assertIsNone(detect_conference_window([
            ('Chat | Microsoft Teams', 'ms-teams.exe', 202),
        ]))
        result = detect_conference_window([
            ('MATH 251 Meeting | Microsoft Teams', 'ms-teams.exe', 202),
        ])
        self.assertEqual(result.provider, 'Microsoft Teams')

    def test_detects_course_named_teams_window_only_with_active_audio(self):
        windows = [('CSCI 235 Lecture 1 | Microsoft Teams', 'ms-teams.exe', 202)]
        self.assertIsNone(detect_conference_window(windows))
        result = detect_conference_window(windows, {'ms-teams.exe'})
        self.assertEqual(result.provider, 'Microsoft Teams')

    def test_detects_google_meet_browser_tab_without_generic_meet_page(self):
        result = detect_conference_window([
            ('abc-defg-hij - Google Meet - Google Chrome', 'chrome.exe', 303),
        ])
        self.assertEqual(result.provider, 'Google Meet')
        self.assertIsNone(detect_conference_window([
            ('Meet our teaching team - Google Chrome', 'chrome.exe', 303),
        ]))


class CalendarLectureTests(unittest.TestCase):
    def test_only_course_like_events_start_notifications(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        events = [
            {
                'id': 'class', 'summary': 'CSCI 231 Lecture',
                'start': {'dateTime': (now + datetime.timedelta(seconds=30)).isoformat()},
            },
            {
                'id': 'other', 'summary': 'Dentist',
                'start': {'dateTime': (now + datetime.timedelta(seconds=30)).isoformat()},
            },
        ]
        with patch.object(calendar_service, 'list_events', return_value=events):
            result = calendar_service.get_starting_lecture_events()
        self.assertEqual([event['id'] for event in result], ['class'])

    def test_daily_schedule_is_downloaded_once_as_class_events(self):
        events = [
            {
                'id': 'class', 'summary': 'MATH 251 Lecture',
                'start': {'dateTime': '2026-09-08T12:00:00+05:00'},
            },
            {
                'id': 'other', 'summary': 'Dentist',
                'start': {'dateTime': '2026-09-08T13:00:00+05:00'},
            },
            {
                'id': 'all-day', 'summary': 'CSCI 235 Lecture',
                'start': {'date': '2026-09-08'},
            },
        ]
        with patch.object(calendar_service, 'list_events', return_value=events) as fetch:
            result = calendar_service.get_daily_lecture_schedule(
                datetime.date(2026, 9, 8)
            )
        self.assertEqual([event['id'] for event in result], ['class'])
        self.assertFalse(fetch.call_args.kwargs['interactive'])

    def test_cached_schedule_shows_a_simple_ten_minute_reminder(self):
        app = QApplication.instance() or QApplication([])
        controller = MeetingPromptController(None, lambda *_: None)
        controller.prompt = MagicMock()
        controller.prompt.isVisible.return_value = False
        start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
        event = {
            'id': 'math', 'summary': 'MATH 251',
            'start': {'dateTime': start.isoformat()},
        }
        with tempfile.TemporaryDirectory() as directory:
            controller._schedule_cache_path = Path(directory) / 'schedule.json'
            controller._schedule_day = controller._today_key()
            controller._schedule_events = [event]
            controller._check_cached_schedule()

        controller.prompt.present.assert_called_once_with(
            'Starts in 10 minutes', 'MATH 251',
            cfg.MEETING_PROMPT_AUDIO_SOURCE,
            show_action=False,
        )


class StartTranscriptionTests(unittest.TestCase):
    def test_prompt_selects_source_opens_studio_and_starts_recording(self):
        class Picker:
            index = -1

            def findData(self, value):
                return {'dual': 0, 'phone': 1}.get(value, -1)

            def setCurrentIndex(self, index):
                self.index = index

        class TextField:
            value = ''

            def text(self):
                return self.value

            def setText(self, value):
                self.value = value

        studio = types.SimpleNamespace(
            audio_source_picker=Picker(), subject_input=TextField(),
            show=lambda: setattr(studio, 'shown', True),
            raise_=lambda: None, activateWindow=lambda: None,
            is_active=lambda: False,
            _toggle_recording=lambda: setattr(studio, 'started', True),
            shown=False, started=False,
        )

        start_studio_transcription(studio, 'phone', 'CSCI 231 Lecture')

        self.assertEqual(studio.audio_source_picker.index, 1)
        self.assertEqual(studio.subject_input.value, 'CSCI 231 Lecture')
        self.assertTrue(studio.shown)
        self.assertTrue(studio.started)


class PromptAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prompt_expands_and_closes_before_callback(self):
        prompt = MeetingPrompt()
        prompt.setAttribute(Qt.WA_DontShowOnScreen)
        prompt.present('Start AI Meeting Note', 'Zoom meeting detected')
        self.app.processEvents()
        self.assertLess(prompt.width(), 620)
        self.assertEqual(prompt.windowOpacity(), 0.0)

        QTest.qWait(560)
        self.assertEqual((prompt.width(), prompt.height()), (620, 96))
        self.assertAlmostEqual(prompt.windowOpacity(), 1.0, places=2)

        completed = []
        prompt.dismiss_animated(lambda: completed.append(True))
        self.assertEqual(completed, [])
        QTest.qWait(330)
        self.assertFalse(prompt.isVisible())
        self.assertEqual(completed, [True])

    def test_calendar_reminder_uses_compact_layout_without_action(self):
        prompt = MeetingPrompt()
        prompt.setAttribute(Qt.WA_DontShowOnScreen)
        prompt.present(
            'Starts in 10 minutes', 'MATH 251', show_action=False,
        )
        QTest.qWait(700)
        self.assertEqual((prompt.width(), prompt.height()), (500, 96))
        self.assertFalse(prompt.start_button.isVisible())
        self.assertEqual(prompt.subtitle_label.text(), 'MATH 251')
        prompt.hide_immediately()


if __name__ == '__main__':
    unittest.main()
