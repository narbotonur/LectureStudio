"""Regression tests for local lecture identity, editing, and archival."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt5.QtCore import QCoreApplication, QEvent, QSize, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

from annie.gui import meeting_window
from annie.lecture_archive import load_transcript, save_transcript, search_library, library_entries


def passage(start, text, **extra):
    return {'start': start, 'end': start + 1, 'text': text, 'source': 'Fixture', **extra}


class LectureWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.profile = tempfile.TemporaryDirectory()
        self.addCleanup(self.profile.cleanup)
        self.root = Path(self.profile.name)
        dependencies = [
            patch.object(meeting_window, 'DATA_DIR', self.root),
            patch.object(meeting_window.MeetingWindow, '_load_classes'),
            patch('annie.updates.UpdateService.start_automatic'),
            patch('annie.gui.study_timer.StudyTimerPage.sync_pending'),
            patch('annie.platform_support.audio_sources', return_value=[('Default microphone', 'default')]),
        ]
        for item in dependencies:
            item.start()
            self.addCleanup(item.stop)
        self.window = meeting_window.MeetingWindow()
        self.addCleanup(self._close_window)

    def _close_window(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_open_switch_late_note_and_visible_export(self):
        a = save_transcript(self.root, [passage(1, 'first')], 'Lecture A', 'CSCI')
        b = save_transcript(self.root, [passage(2, 'second')], 'Lecture B', 'MATH', lecture_date=dt.date(2026, 1, 2))
        self.assertTrue(self.window._open_lecture_path(a))
        old = self.window._lecture
        self.window.user_scratchpad.setPlainText('Private A')
        self.window._on_fusion_finished('Old notes')
        self.assertTrue(self.window._open_lecture_path(b))
        self.assertEqual(self.window.user_scratchpad.toPlainText(), '')
        self.window._on_fusion_finished('Late for A', old)
        self.assertEqual(self.window.notes_area.toPlainText(), '')
        self.assertEqual(load_transcript(a)['notes'], 'Late for A')
        self.window._on_fusion_finished('Notes for B <topic>')
        self.window._on_slide_finished('slide.png', 'Visible slide')
        self.window._copy_notes()
        self.assertIn('Visible slide', self.app.clipboard().text())
        html = self.root / 'out.html'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(html), '')), patch('webbrowser.open'):
            self.window._export_pdf()
        rendered = html.read_text(encoding='utf-8')
        self.assertIn('2026-01-02', rendered)
        self.assertIn('&lt;topic&gt;', rendered)
        self.assertIn('Visible slide', rendered)

    def test_delayed_generation_keeps_unsaved_manual_changes(self):
        path = save_transcript(self.root, [passage(1, 'first')], 'Lecture A')
        self.assertTrue(self.window._open_lecture_path(path))
        self.window.notes_area.setPlainText('Keep this manual edit')
        self.window._on_fusion_finished('Generated alternative', self.window._lecture, '')
        saved = load_transcript(path)
        self.assertEqual(saved['notes'], 'Keep this manual edit')
        self.assertEqual(saved['revisions'][-1]['notes'], 'Generated alternative')

    def test_large_transcript_keeps_speakers_and_uses_exact_time(self):
        items = [passage(i, 'repeat' if i in (0, 30) else 'a' * 1100, speaker='A' if i % 2 == 0 else 'B')
                 for i in range(180)]
        path = save_transcript(self.root, items, 'Long lecture')
        self.assertTrue(self.window._open_lecture_path(path))
        self.assertEqual(load_transcript(path)['segments'][30]['speaker'], 'A')
        self.window._seek_transcript(30)
        self.assertEqual(self.window.transcript_area.textCursor().selectedText(), '00:30   A · repeat')
        self.assertIn('[00:00:30.000] A · repeat', self.window._last_transcript)
        self.window._entrance_played = True
        self.window.show()
        self.window._seek_transcript(30)
        view = self.window.transcript_area
        cursor = view.textCursor()
        cursor.setPosition(cursor.selectionStart() + 2)
        with patch.object(self.window.transcript_tools, 'play_at') as play:
            QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.cursorRect(cursor).center())
        play.assert_called_once_with(30)

    def test_speaker_review_filters_preserve_full_transcript_and_save_assignments(self):
        window = self.window
        doc = window._new_lecture('Speaker review')
        doc['segments'] = [passage(1, 'first', speaker='A', id='first'),
                           passage(4, 'unassigned', id='unassigned'),
                           passage(8, 'second', speaker='B', id='second'),
                           passage(33, 'A returns', speaker='A', id='return')]
        doc['speaker_turns'] = [{'start': 4, 'end': 6, 'speaker': 'A'},
                                {'start': 3, 'end': 5, 'speaker': 'B'}]
        self.assertTrue(window._activate_lecture(doc))
        filters = window.speaker_panel.filters

        filters.setCurrentIndex(filters.findData('speaker:A'))
        self.assertEqual([row['id'] for _, _, row in window._transcript_ranges], ['first', 'return'])
        self.assertIn('second', window._last_transcript)
        window._seek_transcript(8)
        self.assertEqual(window.speaker_panel.selection(), ('all', ''))
        self.assertIn('second', window.transcript_area.textCursor().selectedText())

        filters.setCurrentIndex(filters.findData('uncertain'))
        self.assertEqual([row['id'] for _, _, row in window._transcript_ranges], ['unassigned'])
        with patch.object(QInputDialog, 'getItem', return_value=('B [B]', True)):
            window.speaker_panel.assign.click()
        self.assertEqual(window.speaker_panel.selection(), ('uncertain', ''))
        self.assertEqual(window.transcript_area.toPlainText(), '')
        filters.setCurrentIndex(filters.findData('overlap'))
        self.assertIn('B · unassigned', window.transcript_area.toPlainText())
        self.assertEqual(load_transcript(self.root / 'transcripts' / f'lecture-{doc["id"]}.json')['segments'][1]['speaker'], 'B')

    def test_find_wraps_around_and_respects_speaker_filter_and_utf16_offsets(self):
        path = save_transcript(self.root, [
            passage(1, '🎙 Сначала: деректер\r\nқұрылымы.', speaker='A'),
            passage(8, 'Мы обсуждаем деректер құрылымы.', speaker='B'),
            passage(15, 'Ещё один пример: деректер құрылымы.', speaker='A'),
        ], 'Search fixture')
        window = self.window
        self.assertTrue(window._open_lecture_path(path))
        window._entrance_played = True
        window.show()
        QApplication.setActiveWindow(window)
        window.lecture_buttons[1].setFocus()
        QTest.qWait(30)
        QTest.keyClick(window.lecture_buttons[1], Qt.Key_F, Qt.ControlModifier)
        navigator = window.transcript_navigation
        self.assertTrue(navigator.isVisibleTo(window))
        navigator.query.setText('ДЕРЕКТЕР құрылымы')
        QTest.qWait(180)
        self.assertEqual(navigator.count.text(), '1 of 3')
        self.assertEqual(window.transcript_area.extraSelections()[-1].cursor.selectedText(), 'деректер\u2029құрылымы')
        QTest.keyClick(navigator.query, Qt.Key_Return)
        self.assertEqual(navigator.count.text(), '2 of 3')
        navigator.next.click()
        self.assertEqual(navigator.count.text(), '3 of 3')
        navigator.next.click()
        self.assertEqual(navigator.count.text(), '1 of 3')
        QTest.keyClick(navigator.query, Qt.Key_F3)
        self.assertEqual(navigator.count.text(), '2 of 3')
        QTest.keyClick(navigator.query, Qt.Key_F3, Qt.ShiftModifier)
        self.assertEqual(navigator.count.text(), '1 of 3')
        filters = window.speaker_panel.filters
        filters.setCurrentIndex(filters.findData('speaker:A'))
        self.assertEqual(navigator.count.text(), '1 of 2')
        navigator.previous.click()
        self.assertEqual(navigator.count.text(), '2 of 2')
        QTest.keyClick(navigator.query, Qt.Key_Escape)
        self.assertTrue(navigator.isHidden())
        self.assertEqual(window.transcript_area.extraSelections(), [])

    def test_playback_highlight_tracks_overlaps_without_moving_the_text_cursor(self):
        path = save_transcript(self.root, [
            passage(1, 'Long turn', end=9, speaker='A'),
            passage(4, 'Short interruption', end=6, speaker='B'),
        ], 'Playback fixture')
        window = self.window
        self.assertTrue(window._open_lecture_path(path, 1))
        view = window.transcript_area
        selected = view.textCursor().selectedText()
        window.transcript_tools.position_changed.emit(4.5)
        self.assertIn('Short interruption', view.extraSelections()[0].cursor.selectedText())
        window.transcript_tools.position_changed.emit(6.25)
        self.assertIn('Long turn', view.extraSelections()[0].cursor.selectedText())
        self.assertEqual(view.textCursor().selectedText(), selected)
        window.transcript_tools.position_changed.emit(9)
        self.assertEqual(view.extraSelections(), [])

    def test_bookmarks_save_rename_jump_and_remove_in_the_open_lecture(self):
        path = save_transcript(self.root, [passage(30.125, 'Keep this passage')], 'Bookmarks fixture')
        window = self.window
        self.assertTrue(window._open_lecture_path(path, 30.125))

        def add_and_jump(dialog):
            dialog._add(30.125)
            dialog.rename.click()
            dialog.jump.click()
            return dialog.result()

        with patch.object(QInputDialog, 'getText', side_effect=[('Start', True), ('Important', True)]), \
                patch.object(meeting_window.TranscriptBookmarks, 'exec_', new=add_and_jump), \
                patch.object(window.transcript_tools, 'jump_to') as jump:
            window.transcript_tools.bookmarks.click()
        self.assertEqual(load_transcript(path)['bookmarks'], [{'start': 30.125, 'title': 'Important'}])
        jump.assert_called_once_with(30.125)

        def remove_bookmark(dialog):
            self.assertEqual(dialog.items.count(), 1)
            dialog.remove.click()
            return QDialog.Accepted

        with patch.object(meeting_window.TranscriptBookmarks, 'exec_', new=remove_bookmark):
            window.transcript_tools.bookmarks.click()
        self.assertEqual(load_transcript(path)['bookmarks'], [])

    def test_compact_workspace_keeps_its_native_size_and_playback_controls(self):
        window = self.window
        window._entrance_played = True
        window.show()
        window.resize(640, 500)
        for tab in (1, 4, 6, 9, 10, 1):
            window._switch_tab(tab)
            QTest.qWait(20)
            self.assertEqual(window.size(), QSize(640, 500))
            self.assertEqual(window.windowHandle().size(), QSize(640, 500))
        self.assertTrue(window.transcript_tools.play.isVisibleTo(window))
        self.assertTrue(window.transcript_tools.export.isVisibleTo(window))
        self.assertFalse(window.bottom_panel.isVisibleTo(window))
        self.assertFalse(window.recording_panel.isVisibleTo(window))
        self.assertTrue(window.import_audio_button.isVisibleTo(window))
        canvas = window.layout().itemAt(0).widget()
        self.assertEqual(canvas.horizontalScrollBar().maximum(), 0)
        self.assertEqual(canvas.verticalScrollBar().maximum(), 0)

    def test_lecture_navigation_retains_subpage_and_library_shortcut(self):
        window = self.window
        window._entrance_played = True
        window.show()
        window.activateWindow()
        window.workspace_buttons[0].click()
        self.assertTrue(window.audio_check.isVisibleTo(window))
        window.lecture_buttons[1].click()
        self.assertTrue(window.workspace_buttons[0].isChecked())
        self.assertTrue(window.lecture_buttons[1].isChecked())
        window.workspace_buttons[4].click()
        self.assertFalse(window.lecture_navigation.isVisibleTo(window))
        window.workspace_buttons[0].click()
        self.assertEqual(window.stack.currentIndex(), 1)
        self.assertTrue(window.library_button.isVisibleTo(window))

        dialog = QDialog(window)
        QTest.qWait(50)
        with patch.object(meeting_window, 'LectureLibrary', return_value=dialog) as library, \
                patch.object(dialog, 'exec_', return_value=QDialog.Rejected):
            QTest.keyClick(window, Qt.Key_O, Qt.ControlModifier)
            library.assert_called_once_with(self.root, window)

    def test_stop_recording_stays_available_outside_lecture(self):
        window = self.window
        worker = Mock()
        worker.isRunning.return_value = True
        worker.isFinished.return_value = False
        window._switch_tab(0)
        with patch('annie.meeting.WhisperMeetingWorker', return_value=worker):
            window.record_btn.click()
        window._switch_tab(4)
        self.assertTrue(window.stop_recording_btn.isVisibleTo(window))
        self.assertTrue(window.stop_recording_btn.isEnabled())
        self.assertFalse(window.recording_panel.isVisibleTo(window))
        window.stop_recording_btn.click()
        worker.stop.assert_called_once_with()
        window._on_summary('# Empty Meeting')
        self.assertEqual(window.stop_recording_btn.text(), 'Finishing…')
        self.assertFalse(window.stop_recording_btn.isEnabled())
        worker.isRunning.return_value = False
        worker.isFinished.return_value = True
        window._reap_jobs()
        self.assertFalse(window.stop_recording_btn.isVisibleTo(window))

    def test_visible_edit_action_corrects_one_passage_and_keeps_original(self):
        path = save_transcript(self.root, [passage(1, 'First line'), passage(3, 'Original wording')], 'Editing fixture')
        window = self.window
        self.assertTrue(window._open_lecture_path(path, 3))
        with patch.object(QInputDialog, 'getMultiLineText', return_value=('Corrected wording', True)):
            window.speaker_panel.edit.click()
        row = load_transcript(path)['segments'][1]
        self.assertEqual(row['text'], 'Original wording')
        self.assertEqual(row['edited_text'], 'Corrected wording')
        self.assertEqual(window.lecture_save_status.text(), 'Saved locally')
        self.assertEqual(window.transcript_save_status.text(), 'Saved locally')

    def test_broken_presentation_fields_cannot_replace_active_lecture(self):
        good = save_transcript(self.root, [passage(1, 'first')], 'Lecture A')
        self.assertTrue(self.window._open_lecture_path(good))
        bad = self.root / 'invalid.json'
        bad.write_text(json.dumps({'version': 2, 'source_name': 'Bad lecture', 'audio_path': 42,
                                   'segments': [passage(1, 'bad')]}), encoding='utf-8')
        self.assertFalse(self.window._open_lecture_path(bad))
        self.assertEqual(self.window._lecture_source_name, 'Lecture A')

    def test_search_returns_exact_non_latin_passage(self):
        path = save_transcript(self.root, [passage(1, 'chapter'), passage(21, 'деректер құрылымы')], 'Search fixture')
        results = search_library(library_entries(self.root), 'құрылымы')
        self.assertEqual([(entry[0], entry[2]) for entry in results], [(path, 21)])
