"""
Elite Annie — Modern Academic Workspace
Crafted with the clean, elegant design system of elitenuet.xyz (Tailwind & Shadcn aesthetic).
Ultra-clean, distraction-free, spacious UI for university lectures and study.
"""
from collections import Counter
from copy import deepcopy
import os
import sys
import webbrowser
import datetime
from html import escape
from pathlib import Path
import re
import math
import uuid
from threading import Event
from typing import Optional, List, Dict

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QCheckBox,
    QComboBox, QFrame, QWidget, QSizePolicy, QApplication, QLineEdit,
    QFileDialog, QMessageBox, QStackedWidget, QSplitter, QListWidget, QListWidgetItem,
    QTimeEdit, QDateEdit, QScrollArea, QMenu, QAction, QBoxLayout, QShortcut,
    QInputDialog
)
from annie.gui.design import (ACCENT as EMERALD, ACCENT_HOVER as EMERALD_HOVER, BACKGROUND as BG_APP,
                              BORDER as BORDER_COLOR, MUTED as TEXT_SUB, SURFACE as BG_SURFACE,
                              TEXT as TEXT_MAIN, apply_theme, role, label, UI_FONT)
from annie.gui.lecture_library import (LectureDetails, LectureLibrary, SpeakerPanel, TranscriptBookmarks,
                                       TranscriptNavigator, TranscriptTools, playback_time, timestamp)
from annie.lecture_archive import library_entries, load_transcript, save_lecture
from annie.paths import DATA_DIR

from PyQt5.QtCore import (
    QAbstractAnimation, QEasingCurve, QPropertyAnimation, Qt, pyqtSignal,
    QTimer, QRectF, QDate, QTime, QThread, QEvent, QSize,
)
from PyQt5.QtGui import (QTextCursor, QTextBlockFormat, QTextCharFormat, QFont, QPainter, QColor,
                         QLinearGradient, QBrush, QPen, QPainterPath, QKeySequence)

# ─────────────────────────────────────────────────────────────
#  Elite NUET Design Tokens (Tailwind / Shadcn Modern Light-Dark)
# ─────────────────────────────────────────────────────────────
EMERALD_BG = "rgba(0, 196, 140, 0.08)"
EMERALD_BORDER = "rgba(0, 196, 140, 0.25)"
BORDER_HOVER = "#51626B"
TEXT_DIM = "#95A9B2"

LECTURE_PAGES = (0, 1, 2)


# ─────────────────────────────────────────────────────────────
#  Elite Minimalist Waveform Pill
# ─────────────────────────────────────────────────────────────
class EliteAudioWaveform(QWidget):
    level_changed = pyqtSignal(float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._level = 0.0
        self._target_level = 0.0
        self._is_hearing = False
        self._bars = [0.06] * 14
        self._phase = 0.0
        self._active = False

        self._decay_timer = QTimer(self)
        self._decay_timer.timeout.connect(self._decay)
        self._decay_timer.start(40)

    def set_active(self, active: bool):
        self._active = active
        if not active:
            self._level = 0.0
            self._target_level = 0.0
            self._is_hearing = False
            self._bars = [0.06] * 14
        self.update()

    def update_audio_level(self, level: float, is_hearing: bool):
        if not self._active:
            return
        self._target_level = max(0.0, min(1.0, level))
        self._is_hearing = is_hearing
        self.level_changed.emit(self._target_level, is_hearing)

    def _decay(self):
        if not self._active:
            return
        self._level += (self._target_level - self._level) * 0.22
        self._target_level *= 0.9
        self._phase += 0.16
        for index, current in enumerate(self._bars):
            shape = 0.4 + 0.6 * abs(math.sin(self._phase + index * 0.72))
            target = max(0.05, self._level * shape) if self._is_hearing else 0.05
            self._bars[index] = current + (target - current) * 0.24
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        if not self._active:
            p.setPen(QColor(TEXT_DIM))
            p.setFont(QFont(UI_FONT, 9))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "···")
            return

        n = len(self._bars)
        spacing = w / n * 0.45
        bar_w = w / n - spacing
        start_x = 0.0
        cy = h / 2.0

        for i, bh_norm in enumerate(self._bars):
            bh = max(3.0, bh_norm * (h - 4.0))
            bx = start_x + i * (bar_w + spacing)
            by = cy - bh / 2.0

            if self._is_hearing:
                p.setBrush(QColor(EMERALD))
            else:
                p.setBrush(QColor("#929D88"))

            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 1.2, 1.2)

        p.setPen(QColor(EMERALD if self._is_hearing else TEXT_SUB))
        p.setFont(QFont(UI_FONT, 9, QFont.DemiBold))
        text_x = start_x + n * (bar_w + spacing) + 8.0
        p.drawText(QRectF(text_x, 0, w - text_x, h), Qt.AlignVCenter | Qt.AlignLeft,
                   f"● Recording ({int(self._level * 100)}%)" if self._is_hearing else "○ Listening...")


# ─────────────────────────────────────────────────────────────
#  Elite Quick-Add Modal Dialog
# ─────────────────────────────────────────────────────────────
class EliteAddClassModal(QDialog):
    event_added = pyqtSignal(str)

    def __init__(self, parent=None, default_date: Optional[datetime.date] = None):
        super().__init__(parent)
        self.setWindowTitle("Schedule Class")
        self.setFixedSize(460, 420)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                font-family: 'Segoe UI';
            }}
            QLabel {{
                color: {TEXT_SUB};
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit, QDateEdit, QTimeEdit {{
                background-color: #111310;
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 10px;
                padding: 9px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus, QDateEdit:focus, QTimeEdit:focus {{
                border: 1px solid {EMERALD};
                background-color: #1B1E19;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QLabel("Add Class to Schedule")
        header.setFont(QFont(UI_FONT, 16, QFont.Bold))
        header.setStyleSheet(f"color: {TEXT_MAIN};")
        layout.addWidget(header)

        layout.addWidget(QLabel("Course Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g. CSCI 235 — Programming Languages")
        layout.addWidget(self.title_edit)

        dt_row = QHBoxLayout()
        dt_row.setSpacing(10)

        date_box = QVBoxLayout()
        date_box.addWidget(QLabel("Date:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        init_d = default_date or datetime.date.today()
        self.date_edit.setDate(QDate(init_d.year, init_d.month, init_d.day))
        date_box.addWidget(self.date_edit)
        dt_row.addLayout(date_box)

        time_box1 = QVBoxLayout()
        time_box1.addWidget(QLabel("Start:"))
        self.start_time = QTimeEdit()
        self.start_time.setTime(QTime.currentTime())
        time_box1.addWidget(self.start_time)
        dt_row.addLayout(time_box1)

        time_box2 = QVBoxLayout()
        time_box2.addWidget(QLabel("End:"))
        self.end_time = QTimeEdit()
        self.end_time.setTime(QTime.currentTime().addSecs(3600))
        time_box2.addWidget(self.end_time)
        dt_row.addLayout(time_box2)

        layout.addLayout(dt_row)

        layout.addWidget(QLabel("Room / Location:"))
        self.loc_edit = QLineEdit()
        self.loc_edit.setPlaceholderText("e.g. 7E.429 / 3E.221 / Online")
        layout.addWidget(self.loc_edit)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(38)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #F1F5F9;
                color: {TEXT_SUB};
                border: 1px solid {BORDER_COLOR};
                border-radius: 10px;
                padding: 6px 18px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #343B30;
                color: {TEXT_MAIN};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save Class")
        save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {EMERALD};
                color: #1B1E19;
                border: none;
                border-radius: 10px;
                padding: 6px 22px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {EMERALD_HOVER};
            }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

        role(save_btn, "primary")
        apply_theme(self)

    def _save(self):
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing Title", "Please enter a course title.")
            return

        qdate = self.date_edit.date()
        qstart = self.start_time.time()
        qend = self.end_time.time()

        start_dt = datetime.datetime(qdate.year(), qdate.month(), qdate.day(), qstart.hour(), qstart.minute())
        end_dt = datetime.datetime(qdate.year(), qdate.month(), qdate.day(), qend.hour(), qend.minute())
        if end_dt <= start_dt:
            QMessageBox.warning(self, 'Invalid class time', 'End time must be later than start time.')
            self.end_time.setFocus()
            return

        loc = self.loc_edit.text().strip()

        try:
            from annie.calendar_service import create_event, is_connected
            if not is_connected():
                QMessageBox.warning(self, "Calendar Not Connected", "Google Calendar is not connected.")
                return

            ok, msg = create_event(summary=title, start_dt=start_dt, end_dt=end_dt, location=loc)
            if ok:
                self.event_added.emit(title)
                self.accept()
            else:
                QMessageBox.critical(self, "Error", msg)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


# ─────────────────────────────────────────────────────────────
#  Elite Weekly Timetable View
# ─────────────────────────────────────────────────────────────
from annie.gui.week_calendar import EliteTimetableView


# ─────────────────────────────────────────────────────────────
#  Thread-Safe Background Workers with Qt Signals
# ─────────────────────────────────────────────────────────────
class NoteFusionThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, transcript: str, context: str, user_notes: str = "", template: str = "lecture"):
        super().__init__()
        self.transcript = transcript
        self.context = context
        self.user_notes = user_notes
        self.template = template

    def run(self):
        try:
            from annie.meeting import generate_ai_summary_sync
            res = generate_ai_summary_sync(self.transcript, self.context, self.template, user_notes=self.user_notes)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class AnkiGenThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, content: str, context: str, user_notes: str = ""):
        super().__init__()
        self.content = content
        self.context = context
        self.user_notes = user_notes

    def run(self):
        try:
            from annie.meeting import generate_anki_flashcards
            res = generate_anki_flashcards(self.content, self.context, user_notes=self.user_notes)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class SlideVisionThread(QThread):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, img_path: str, context: str):
        super().__init__()
        self.img_path = img_path
        self.context = context

    def run(self):
        try:
            with open(self.img_path, "rb") as f:
                data = f.read()
            from annie.meeting import analyze_lecture_slide
            res = analyze_lecture_slide(data, course_context=self.context)
            self.finished.emit(self.img_path, res)
        except Exception as e:
            self.error.emit(str(e))


class PrepGuideThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, file_paths, assessment_type, context):
        super().__init__()
        self.file_paths = list(file_paths)
        self.assessment_type = assessment_type
        self.context = context

    def run(self):
        try:
            from annie.study_guide import generate_exam_prep_guide
            guide = generate_exam_prep_guide(
                self.file_paths,
                self.assessment_type,
                self.context,
                progress=self.status.emit,
            )
            self.finished.emit(guide)
        except Exception as exc:
            self.error.emit(str(exc))


class StudyChatThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt

    def run(self):
        try:
            from google import genai
            from annie.config import GEMINI_API_KEY, GEMINI_MODEL
            if not GEMINI_API_KEY:
                self.error.emit('Set up Gemini to send a question.')
                return
            client = genai.Client(api_key=GEMINI_API_KEY)
            active_models = [
                GEMINI_MODEL,
                "gemini-3.7-flash",
                "gemini-3.8-flash",
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-flash-latest",
                "gemini-3.1-flash-lite",
            ]
            for model_name in active_models:
                try:
                    res = client.models.generate_content(
                        model=model_name,
                        contents=f"You are Annie, an elite academic AI study tutor for a computer science and mathematics university student. Answer cleanly and accurately:\n\n{self.prompt}"
                    )
                    if res and res.text and res.text.strip():
                        self.finished.emit(res.text.strip())
                        return
                except Exception:
                    continue
            self.error.emit("Failed to generate response across all models.")
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
#  Elite Main Workstation Window
# ─────────────────────────────────────────────────────────────
class SpeakerDetection(QThread):
    result = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, audio, model, count, parent=None):
        super().__init__(parent)
        self.audio, self.model, self.count = audio, model, count
        self.cancel_event = Event()

    def run(self):
        from annie.diarization import DiarizationError, diarize
        try:
            intervals = diarize(self.audio, model_path=self.model, speaker_count=self.count, stop=self.cancel_event)
            if not self.cancel_event.is_set():
                self.result.emit(intervals)
        except (DiarizationError, OSError, ValueError) as exc:
            self.error.emit(str(exc))


class ResponsiveComboBox(QComboBox):
    """Combobox that allows compact layout shrinking without locking min width to longest text."""
    def minimumSizeHint(self):
        sz = super().minimumSizeHint()
        sz.setWidth(min(sz.width(), 140))
        return sz


class StudioStack(QStackedWidget):
    """Keeps page switching independent of the minimum size of hidden pages."""

    def minimumSizeHint(self):
        return QSize(0, 0)

    def addScrollableWidget(self, page):
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        page.setObjectName('homeContent')
        scroll.viewport().setObjectName('homeContent')
        scroll.setWidget(page)
        return self.addWidget(scroll)


class StudioShellLayout(QVBoxLayout):
    def hasHeightForWidth(self):
        # Let the shell shrink to its minimum. Page content scrolls inside the
        # stack, independently of the preferred heights of the other pages.
        return False


class MeetingWindow(QDialog):
    settings_changed = pyqtSignal()
    meeting_state_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Annie · Lecture studio")
        # Enable full desktop resizing, Aero Snap (Win + Left Arrow), and minimize/maximize controls
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(640, 500)
        self.resize(1180, 820)
        self._is_pinned = False
        self._last_transcript = ""
        self._transcript_segments = []
        self._lecture_source_name = 'Current lecture'
        self._lecture_date = None
        self._lecture = self._new_lecture('Untitled lecture')
        self._transcript_ranges = []
        self._open_lectures = {}
        self._speaker_job = None
        self._diarization_model = self._load_speaker_model()
        self._audio_setup = None
        self._lecture_timer = QTimer(self, singleShot=True, interval=650)
        self._lecture_timer.timeout.connect(self._save_active_lecture)
        self._recording = False
        self._recording_session = False
        self._last_lecture_page = 0
        self._jobs = set()
        self._mini_dock = None
        self._restore_maximized = False
        self._entrance_played = False
        self._window_animation = None
        self._geometry_animation = None
        self._job_timer = QTimer(self)
        self._job_timer.timeout.connect(self._reap_jobs)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG_APP};
                color: {TEXT_MAIN};
                font-family: 'Segoe UI';
            }}
            QPushButton {{
                background: white; color: {TEXT_SUB}; border: 1px solid {BORDER_COLOR};
                border-radius: 8px; padding: 8px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {EMERALD}; color: {TEXT_MAIN}; }}
            QPushButton:focus {{ border: 2px solid {EMERALD}; }}
            QPushButton:disabled {{ color: #929D88; background: #F1F5F9; }}
            QMenu {{ background: white; color: {TEXT_MAIN}; padding: 6px; border: 1px solid {BORDER_COLOR}; }}
            QMenu::item {{ padding: 8px 18px; }}
            QMenu::item:selected {{ background: #E8F7F1; }}
            QSplitter::handle {{ background: {BORDER_COLOR}; border-radius: 2px; }}
            QTextEdit {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 12px;
                padding: 16px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                line-height: 1.6;
            }}
            QTextEdit:focus {{
                border: 1px solid {EMERALD};
            }}
            QLineEdit {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {EMERALD};
            }}
            QComboBox {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
            }}
            QComboBox:focus {{
                border: 1px solid {EMERALD};
            }}
            QComboBox QAbstractItemView {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                selection-background-color: {EMERALD};
                selection-color: #1B1E19;
                border: 1px solid {BORDER_COLOR};
            }}
        """)

        # Keep page height-for-width measurements inside the scroll viewport.
        # The native window can then retain its size when a page is switched.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        canvas = QScrollArea()
        canvas.setFrameShape(QFrame.NoFrame)
        canvas.setWidgetResizable(True)
        canvas.viewport().setObjectName('homeContent')
        shell = QWidget(objectName='homeContent')
        canvas.setWidget(shell)
        outer.addWidget(canvas)
        self.studio_layout = layout = StudioShellLayout(shell)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        # A stable header: identity and live status stay together while actions
        # remain in the same place at every window size.
        self.header_panel = role(QFrame(), "studioHeader")
        header = QHBoxLayout(self.header_panel)
        header.setContentsMargins(0, 4, 0, 4)
        header.setSpacing(12)
        brand_mark = role(QLabel("A"), "brandMark")
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(38, 38)
        header.addWidget(brand_mark)

        heading = role(QLabel("Lecture Studio"), "studioTitle")
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title_column.addWidget(heading)
        self.operation_status = QLabel()
        self.operation_status.setWordWrap(True)
        self.operation_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        role(self.operation_status, "studioStatus")
        title_column.addWidget(self.operation_status)
        self.capture_status = label('', 'studioStatus')
        self.capture_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.capture_status.hide()
        title_column.addWidget(self.capture_status)
        header.addLayout(title_column, 1)
        header.addStretch()
        self.study_status_btn = QPushButton()
        self.study_status_btn.setObjectName("studioUtilityButton")
        self.study_status_btn.setToolTip("Open your study timer")
        self.study_status_btn.clicked.connect(lambda: self._switch_tab(5))
        self.study_status_btn.hide()
        header.addWidget(self.study_status_btn)
        self.signal_widget = EliteAudioWaveform()
        self.signal_widget.setFixedWidth(72)
        header.addWidget(self.signal_widget)
        self.stop_recording_btn = QPushButton('Stop recording')
        self.stop_recording_btn.setObjectName('stopRecordingButton')
        self.stop_recording_btn.clicked.connect(self._toggle_recording)
        header.addWidget(self.stop_recording_btn)
        self.snap_btn = QPushButton("Split screen")
        self.snap_btn.setObjectName("studioUtilityButton")
        self.snap_btn.clicked.connect(self._snap_to_left)
        header.addWidget(self.snap_btn)
        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setObjectName("studioUtilityButton")
        self.pin_btn.setFixedSize(44, 36)
        self.pin_btn.setToolTip("Keep this window on top")
        self.pin_btn.clicked.connect(self._toggle_pin)
        self._update_pin_style()
        header.addWidget(self.pin_btn)
        layout.addWidget(self.header_panel)

        from annie.gui.studio_updates import UpdatePanel
        self.updates_panel = UpdatePanel(self)
        layout.addWidget(self.updates_panel)

        self.recording_panel = role(QFrame(), "recordingBar")
        self.recording_panel.setMinimumHeight(76)
        recording_bar = QHBoxLayout(self.recording_panel)
        recording_bar.setContentsMargins(16, 7, 12, 7)
        recording_bar.setSpacing(10)

        class_field = QWidget()
        class_field.setMinimumWidth(145)
        class_field.setMaximumWidth(520)
        class_column = QVBoxLayout(class_field)
        class_column.setContentsMargins(0, 0, 0, 0)
        class_column.setSpacing(4)
        class_column.addWidget(label("Class", "fieldLabel"))
        self.class_picker = ResponsiveComboBox()
        self.class_picker.setMinimumWidth(135)
        self.class_picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.class_picker.addItem("Select a class", "")
        self.class_picker.setAccessibleName("Class")
        self.class_picker.currentIndexChanged.connect(self._on_class_picked)
        class_column.addWidget(self.class_picker)
        recording_bar.addWidget(class_field, 5)

        source_field = QWidget()
        source_field.setMinimumWidth(130)
        source_field.setMaximumWidth(250)
        source_column = QVBoxLayout(source_field)
        source_column.setContentsMargins(0, 0, 0, 0)
        source_column.setSpacing(4)
        source_column.addWidget(label("Audio source", "fieldLabel"))
        self.audio_source_picker = ResponsiveComboBox()
        self.audio_source_picker.setMinimumWidth(120)
        self.audio_source_picker.setAccessibleName("Audio source")
        self.audio_source_picker.currentTextChanged.connect(self.audio_source_picker.setToolTip)
        from annie.platform_support import audio_sources
        for title, value in audio_sources():
            self.audio_source_picker.addItem(title, value)
        source_column.addWidget(self.audio_source_picker)
        recording_bar.addWidget(source_field, 3)
        recording_bar.addStretch(1)

        self.audio_check = role(QPushButton('Test audio…'), 'quiet')
        self.audio_check.setToolTip('Check input and set up local models')
        self.audio_check.clicked.connect(self._open_audio_setup)
        recording_bar.addWidget(self.audio_check)
        self.record_btn = QPushButton("Start recording")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.setProperty("state", "idle")
        self.record_btn.setFixedHeight(42)
        self.record_btn.setMinimumWidth(125)
        self.record_btn.clicked.connect(self._toggle_recording)
        recording_bar.addWidget(self.record_btn)
        layout.addWidget(self.recording_panel)

        self.navigation = role(QFrame(), "navigation")
        nav_bar = QBoxLayout(QBoxLayout.TopToBottom, self.navigation)
        nav_bar.setContentsMargins(8, 10, 8, 8)
        self.nav_layout = nav_bar
        nav_bar.setSpacing(5)
        self.workspace_buttons = {}
        for index, title in ((9, 'Today'), (0, 'Lecture'), (10, 'Review'), (4, 'Schedule'), (6, 'Academics')):
            button = self._create_tab_btn(title)
            button.clicked.connect(lambda checked=False, i=index: self._switch_tab(self._last_lecture_page if i == 0 else i))
            self.workspace_buttons[index] = button
            nav_bar.addWidget(button)
        nav_bar.addStretch()
        nav_bar.addWidget(self.updates_panel.check_button)
        self.tools_btn = role(QPushButton("More"), 'quiet')
        menu = QMenu(self.tools_btn)
        for title, index in [('Study timer', 5), ('Campus Radar', 12),
                             ('Executable lecture lab', 11), ('Daily routines', 7),
                             ('Weekly plan · advanced', 8), ('Legacy assistant', 3)]:
            menu.addAction(title, lambda checked=False, i=index: self._switch_tab(i))
        menu.addSeparator()
        from annie.prayer_startup import launch as launch_prayer_widget
        menu.addAction("Prayer times widget · Намаз", launch_prayer_widget)
        menu.addSeparator()
        menu.addAction("Open saved recordings", lambda: self._open_profile_folder('recordings'))
        menu.addAction("Open study materials", lambda: self._open_profile_folder('library'))
        library_action = menu.addAction('Lecture library…', self._open_library, QKeySequence(QKeySequence.Open))
        self.addAction(library_action)
        menu.addAction('Review flashcards…', self._review_flashcards)
        menu.addAction('Open saved transcript…', self._open_saved_transcript)
        menu.addAction('Edit lecture details…', self._edit_lecture_details)
        menu.addAction('Restore lecture revision…', self._restore_lecture_revision)
        menu.addAction('Audio & local models…', self._open_audio_setup)
        menu.addAction("Accounts & Setup…", self._open_studio_setup)
        menu.addAction("Moodle calendar…", self._open_moodle_setup)
        menu.addAction("Deadline Inbox…", self._open_deadline_inbox)
        menu.addAction('Check for updates…', self.updates_panel.check_manually)
        menu.addSeparator()
        menu.addAction("Import audio…", self._import_audio)
        menu.addAction("Import slide…", self._import_slide)
        menu.addAction("Create exam prep guide…", self._create_exam_prep_guide)
        menu.addSeparator()
        from annie.utils.nu_links import open_moodle, open_registrar, open_my_nu
        menu.addAction("Open Moodle", open_moodle)
        menu.addAction("Open Registrar", open_registrar)
        menu.addAction("Open My.NU", open_my_nu)
        self.tools_btn.setMenu(menu)
        nav_bar.addWidget(self.tools_btn)


        # ── 3. Main Workspace Stack ──────────────────────────
        self.stack = StudioStack()

        # Tab 0: Note Fusion Workspace (Granola / Humla Style)
        self.stack.addWidget(self._build_notes_fusion_tab())

        # Tab 1: Live Speech Transcript
        self.transcript_area = QTextEdit()
        self.transcript_area.setObjectName('transcriptBody')
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setPlaceholderText('Open Notes to start a recording, or choose Import audio.')
        self.transcript_area.setContextMenuPolicy(Qt.CustomContextMenu)
        self.transcript_area.customContextMenuRequested.connect(self._transcript_menu)
        self._transcript_viewport = self.transcript_area.viewport()
        self._transcript_viewport.installEventFilter(self)
        transcript_page = QWidget()
        transcript_layout = QVBoxLayout(transcript_page)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        self.transcript_tools = TranscriptTools()
        self.transcript_tools.changed.connect(self._save_active_lecture)
        self.transcript_tools.changed.connect(self._refresh_speaker_controls)
        self.transcript_tools.analyze_requested.connect(self._request_diarization)
        self.transcript_tools.cancel_requested.connect(self._cancel_diarization)
        self.transcript_tools.export_requested.connect(self._show_export_menu)
        self.transcript_tools.bookmarks.clicked.connect(self._show_transcript_bookmarks)
        transcript_layout.addWidget(self.transcript_tools)
        self.transcript_navigation = TranscriptNavigator(self.transcript_area, transcript_page)
        self.transcript_tools.find.clicked.connect(self._open_transcript_search)
        self.transcript_tools.position_changed.connect(self.transcript_navigation.track_playback)
        transcript_layout.addWidget(self.transcript_navigation)
        self.speaker_panel = SpeakerPanel()
        self.speaker_panel.filter_changed.connect(self._filter_transcript)
        self.speaker_panel.sample_requested.connect(self._play_speaker_sample)
        self.speaker_panel.rename_requested.connect(self._rename_speaker)
        self.speaker_panel.merge_requested.connect(self._merge_speaker)
        self.speaker_panel.assign_requested.connect(self._assign_transcript_selection)
        self.speaker_panel.edit_requested.connect(self._edit_current_passage)
        transcript_layout.addWidget(self.speaker_panel)
        self._overlap_windows = []
        self._overlap_rows = set()
        transcript_layout.addWidget(self.transcript_area, 1)
        self.transcript_save_status = label('', 'studioStatus')
        self.transcript_save_status.hide()
        transcript_layout.addWidget(self.transcript_save_status, alignment=Qt.AlignRight)
        self.stack.addWidget(transcript_page)

        # Tab 2: Anki Flashcards
        self.flashcards_area = QTextEdit()
        self.flashcards_area.setAcceptRichText(False)
        self.flashcards_area.setPlaceholderText(
            'Generate flashcards, or enter one question and answer per line separated by a tab.')
        cards_page = QWidget()
        cards_layout = QVBoxLayout(cards_page)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        card_actions = QHBoxLayout()
        card_actions.addWidget(label('Flashcards', 'title'), 1)
        for title, callback in (('Add card…', self._add_flashcard), ('Export TSV…', self._export_flashcards),
                                ('Review due…', self._review_flashcards)):
            card_button = QPushButton(title)
            card_button.clicked.connect(callback)
            card_actions.addWidget(card_button)
        cards_layout.addLayout(card_actions)
        cards_layout.addWidget(self.flashcards_area, 1)
        self.stack.addWidget(cards_page)

        # Tab 3: Study Chat
        self.stack.addWidget(self._build_chat_tab())

        # Tab 4: Weekly Timetable
        self.timetable_view = EliteTimetableView()
        self.timetable_view.select_class.connect(self._on_timetable_class_selected)
        self.stack.addScrollableWidget(self.timetable_view)

        from annie.gui.study_timer import StudyTimerPage
        self.study_page = StudyTimerPage(self)
        self.stack.addScrollableWidget(self.study_page)
        self.timetable_view.set_study_store(self.study_page.store)
        self.study_page.sessions_changed.connect(self.timetable_view.reload_local_sessions)
        self.study_page.timer_changed.connect(self._update_study_status)
        self.study_page._tick()

        from annie.gui.gpa_tracker import GpaTrackerPage
        self.gpa_page = GpaTrackerPage(self)
        self.stack.addScrollableWidget(self.gpa_page)

        from annie.gui.habit_tracker import HabitTrackerPage
        self.habits_page = HabitTrackerPage(self)
        self.stack.addScrollableWidget(self.habits_page)

        from annie.gui.weekly_planner import WeeklyPlannerPage
        self.planner_page = WeeklyPlannerPage(self)
        self.stack.addScrollableWidget(self.planner_page)

        from annie.gui.today import TodayPage
        self.today_page = TodayPage(self)
        self.today_page.navigate.connect(self._switch_tab)
        self.today_page.library_requested.connect(self._open_library)
        self.due_cards = QPushButton('Review flashcards')
        self.due_cards.clicked.connect(self._review_flashcards)
        self.today_page.layout().insertWidget(2, self.due_cards)
        if hasattr(self.today_page, 'inbox_requested'):
            self.today_page.inbox_requested.connect(self._open_deadline_inbox)
        self.today_page.study_requested.connect(self._start_daily_study)
        self.stack.addWidget(self.today_page)
        self.timetable_view.events_loaded.connect(self.today_page.set_events)
        from annie.gui.lecture_review import LectureReviewPage
        self.review_page = LectureReviewPage(self)
        self.review_page.actions_changed.connect(self.today_page.reload)
        self.review_page.evidence_requested.connect(self._show_transcript_evidence)
        self.stack.addScrollableWidget(self.review_page)
        from annie.gui.lecture_lab import LectureLabPage
        self.lab_page = LectureLabPage(self)
        self.lab_page.evidence_requested.connect(self._show_lab_evidence)
        self.stack.addWidget(self.lab_page)
        self.today_page.lab_requested.connect(self._open_study_lab)
        from annie.gui.campus_radar import RadarPage
        self.radar_page = RadarPage(self)
        self.radar_page.changes_updated.connect(self.today_page.reload)
        self.stack.addScrollableWidget(self.radar_page)

        self.workspace_body = QBoxLayout(QBoxLayout.LeftToRight)
        self.workspace_body.setSpacing(12)
        self.workspace_body.addWidget(self.navigation)
        content = QVBoxLayout()
        content.setSpacing(8)
        self.lecture_navigation = role(QFrame(), 'lectureNavigation')
        lecture_bar = QHBoxLayout(self.lecture_navigation)
        lecture_bar.setContentsMargins(5, 4, 5, 4)
        lecture_bar.setSpacing(5)
        self.lecture_buttons = {}
        for index, title in zip(LECTURE_PAGES, ('Notes', 'Transcript', 'Flashcards')):
            button = self._create_tab_btn(title, style='lectureNav')
            button.clicked.connect(lambda checked=False, i=index: self._switch_tab(i))
            self.lecture_buttons[index] = button
            lecture_bar.addWidget(button)
        lecture_bar.addStretch(1)
        self.library_button = role(QPushButton('Library…'), 'quiet')
        self.library_button.setToolTip('Open saved lectures')
        self.library_button.clicked.connect(self._open_library)
        lecture_bar.addWidget(self.library_button)
        self.import_audio_button = role(QPushButton('Import audio…'), 'quiet')
        self.import_audio_button.clicked.connect(self._import_audio)
        lecture_bar.addWidget(self.import_audio_button)
        content.addWidget(self.lecture_navigation)
        content.addWidget(self.stack, 1)
        self.workspace_body.addLayout(content, 1)
        layout.addLayout(self.workspace_body, 1)

        # ── 4. Bottom Clean Action Bar ───────────────────────
        self.bottom_panel = role(QFrame(), "studioFooter")
        bottom_bar = QHBoxLayout(self.bottom_panel)
        bottom_bar.setContentsMargins(10, 8, 8, 8)
        bottom_bar.setSpacing(8)

        # Quick context input
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Course or topic…")
        self.subject_input.setAccessibleName('Lecture course or topic')
        self.subject_input.setObjectName("courseContextInput")
        bottom_bar.addWidget(self.subject_input, 1)
        self.lecture_save_status = label('', 'studioStatus')
        bottom_bar.addWidget(self.lecture_save_status)

        # Gen Anki Cards Button
        self.gen_anki_btn = QPushButton("Make flashcards")
        role(self.gen_anki_btn, "warmAction")
        self.gen_anki_btn.setFixedHeight(38)
        self.gen_anki_btn.setMinimumWidth(135)
        self.gen_anki_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_SURFACE};
                color: #E5BB83;
                border: 1px solid #6C5A3E;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #373024;
            }}
        """)
        self.gen_anki_btn.clicked.connect(self._generate_anki)
        bottom_bar.addWidget(self.gen_anki_btn)

        # Export Menu Button (Copy, Obsidian .md, HTML/PDF, .txt)
        self.export_btn = QPushButton("Export…")
        self.export_btn.setObjectName("exportButton")
        self.export_btn.setFixedHeight(38)
        self.export_btn.setMinimumWidth(110)
        self.export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {EMERALD};
                color: {EMERALD};
            }}
        """)
        self.export_btn.clicked.connect(self._show_export_menu)
        self.export_feedback_timer = QTimer(self, singleShot=True, interval=2000)
        self.export_feedback_timer.timeout.connect(self._restore_export_label)
        bottom_bar.addWidget(self.export_btn)

        layout.addWidget(self.bottom_panel)

        self.worker = None
        for editor in (self.user_scratchpad, self.notes_area, self.flashcards_area):
            editor.textChanged.connect(self._lecture_edited)
        self.subject_input.textEdited.connect(self._lecture_edited)
        self.transcript_tools.display(self._lecture)
        self._load_classes()
        role(self.operation_status, "studioStatus")
        role(self.fuse_btn, "primary")
        apply_theme(self)
        self._shortcuts = []
        for index in range(9):
            self._shortcuts.append(QShortcut(f"Ctrl+{index + 1}", self,
                activated=lambda i=index: self._switch_tab(i)))
        self._shortcuts.append(QShortcut("Ctrl+Return", self, activated=self._fuse_notes))
        self._shortcuts.append(QShortcut("F2", self.transcript_area,
            context=Qt.WidgetWithChildrenShortcut, activated=self._edit_current_passage))
        for key, callback in ((QKeySequence(QKeySequence.Find), self._open_transcript_search),
                              ('F3', self.transcript_navigation.move_match),
                              ('Shift+F3', lambda: self.transcript_navigation.move_match(-1))):
            self._shortcuts.append(QShortcut(key, transcript_page,
                context=Qt.WindowShortcut, activated=callback))
        self._switch_tab(9)

    def _create_tab_btn(self, text: str, style='nav') -> QPushButton:
        btn = role(QPushButton(text), style)
        btn.setFixedHeight(36)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        return btn

    def _snap_to_left(self):
        """Ease the workspace into a predictable split-screen geometry."""
        screen = QApplication.primaryScreen().availableGeometry()
        target_w = max(self.minimumWidth(), screen.width() // 2)
        target = screen.adjusted(0, 0, -(screen.width() - target_w), 0)
        if self.isMaximized():
            self.showNormal()
        if self._geometry_animation:
            self._geometry_animation.stop()
        animation = QPropertyAnimation(self, b"geometry", self)
        animation.setDuration(260)
        animation.setStartValue(self.geometry())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._geometry_animation = animation

        animation.finished.connect(
            lambda: setattr(self, '_geometry_animation', None)
            if self._geometry_animation is animation else None
        )
        animation.start(QAbstractAnimation.DeleteWhenStopped)

    def _toggle_pin(self):
        """Toggles Always-on-Top so Workstation stays visible while browsing on right."""
        self._is_pinned = not self._is_pinned
        self._update_pin_style()
        if self._is_pinned:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _update_pin_style(self):
        self.pin_btn.setText("On" if self._is_pinned else "Pin")
        self.pin_btn.setStyleSheet(f"color: {EMERALD};" if self._is_pinned else "")

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        in_lecture = index in LECTURE_PAGES
        if in_lecture:
            self._last_lecture_page = index
        for page, button in self.workspace_buttons.items():
            button.setChecked(page == (0 if in_lecture else index))
        for page, button in self.lecture_buttons.items():
            button.setChecked(page == index)
        self.lecture_navigation.setVisible(in_lecture)
        self.bottom_panel.setVisible(index in (0, 2, 3))
        self._refresh_audio_controls()
        if index == 12:
            self.radar_page.reload()
        if index == 7:
            self.habits_page.reload()
        if index == 8:
            self.planner_page.reload()
        if index == 9:
            self.today_page.reload()
            self._refresh_due_cards()
        if index == 10:
            try:
                self.review_page.set_transcript(self._lecture.get('source_segments', self._transcript_segments),
                    course=self.subject_input.text().strip(), source_name=self._lecture_source_name,
                    lecture_date=self._lecture_date)
            except ValueError as exc:
                self.review_page.set_transcript([])
                self.review_page.status.setText(str(exc))
        if index == 6:
            self.gpa_page.reload()
        if index == 11:
            self.lab_page.set_study_action('')
            try:
                self.lab_page.set_transcript(self._lecture.get('source_segments', self._transcript_segments),
                    course=self.subject_input.text().strip(), source_name=self._lecture_source_name)
            except ValueError as exc:
                self.lab_page.set_transcript([])
                self.lab_page.status.setText(str(exc))
        self.gen_anki_btn.setVisible(index in (0, 2))
        self.export_btn.setVisible(index == 0)
        if index == 4:
            self.timetable_view._refresh()

    def _update_study_status(self, text):
        self.study_status_btn.setText(text)
        self.study_status_btn.setVisible(bool(text))

    def _open_study_lab(self, action_id):
        from annie.lecture_actions import ActionStore
        try:
            context = ActionStore().study_context(action_id)
            self._switch_tab(11)
            self.lab_page.set_transcript(context['segments'], context['course'], context['source_name'])
            self.lab_page.set_study_action(action_id)
            self.lab_page.status.setText('Source loaded from your approved study action. Generate a lab to review its assumptions.')
        except (ValueError, OSError) as exc:
            self.operation_status.setText(str(exc))

    def _show_lab_evidence(self, timestamp):
        spec = self.lab_page.current_spec
        if spec:
            self._open_evidence_source(spec.get('source_name'), timestamp)

    def _start_daily_study(self, subject):
        try:
            active = self.study_page.store.active()
            if active:
                if active['subject'] != subject:
                    answer = QMessageBox.question(self, 'Study session in progress',
                        f"You are currently studying {active['subject']}. Open that session before starting {subject}?",
                        QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                    if answer != QMessageBox.Yes:
                        return
                self._switch_tab(5)
                return
            saved = self.study_page.store.add_subject(subject)
            self.study_page.store.start(saved['id'], sync=False)
            self.study_page._load_subjects(saved['id'])
            self.study_page._refresh()
            self._switch_tab(5)
        except (ValueError, OSError) as exc:
            self.operation_status.setText(str(exc))

    def _open_moodle_setup(self):
        from annie.gui.moodle_setup import MoodleSetup
        MoodleSetup(self).exec_()

    def _open_deadline_inbox(self):
        from annie.gui.deadline_inbox import DeadlineInbox
        dialog = DeadlineInbox(self)
        if hasattr(dialog, 'saved_changed'):
            dialog.saved_changed.connect(self.today_page.reload)
            dialog.saved_changed.connect(self.review_page.reload)
        dialog.exec_()
        self.today_page.reload()

    def _open_studio_setup(self):
        if self._recording or self.has_running_jobs():
            QMessageBox.information(self, 'Work in progress', 'Finish the current recording or background task before changing accounts.')
            return
        from annie.gui.studio_setup import StudioSetup
        if StudioSetup(self).exec_() == QDialog.Accepted:
            self.timetable_view._cache.clear()
            self.timetable_view._refresh(force=True)
            self.study_page.sync_pending()
            self.settings_changed.emit()

    def _transcribing(self):
        return bool(self.worker and (self.worker.isRunning() or self.worker in self._jobs))

    def _open_audio_setup(self, _checked=False, *, models=False):
        if self._transcribing():
            self.operation_status.setText('Finish the recording or import before opening audio setup.')
            return
        if self._audio_setup is None:
            from annie.gui.audio_setup import AudioSetup
            self._audio_setup = AudioSetup(DATA_DIR, self)
            self._audio_setup.speaker_model_changed.connect(self._select_speaker_model)
            self._audio_setup.busy_changed.connect(self._refresh_audio_controls)
        if not self._audio_setup.task:
            from annie.config import WHISPER_MODEL
            self._audio_setup.configure(self.audio_source_picker.currentData() or 'default',
                self.audio_source_picker.currentText(), WHISPER_MODEL, self._diarization_model, show_models=models)
        self._audio_setup.open()

    def _select_speaker_model(self, model):
        from annie.secure_storage import atomic_write
        self._diarization_model = model
        try:
            atomic_write(DATA_DIR / 'speaker-model-folder.txt', model.encode('utf-8'))
        except OSError:
            self._audio_setup.speaker_status.setText('Ready for this session. The folder preference could not be saved.')
        self._refresh_speaker_controls()

    def _open_profile_folder(self, name):
        from pathlib import Path
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from annie.paths import DATA_DIR
        folder = Path(DATA_DIR) / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError('Windows or macOS could not open the folder.')
        except OSError as exc:
            QMessageBox.warning(self, 'Open folder', str(exc))

    @staticmethod
    def _new_lecture(source, course='', day=None, audio=''):
        return {'id': uuid.uuid4().hex, 'source_name': source, 'title': source,
                'course': course, 'lecture_date': day.isoformat() if day else None,
                'audio_path': audio, 'segments': [], 'complete': False}

    def _lecture_edited(self, *_):
        self._set_lecture_save_status('Unsaved changes')
        self._lecture_timer.start()

    def _set_lecture_save_status(self, text):
        self.lecture_save_status.setText(text)
        self.transcript_save_status.setText(text)
        self.transcript_save_status.setVisible(bool(text))

    def _snapshot_lecture(self):
        values = {name: editor.toPlainText() for name, editor in (
            ('scratchpad', self.user_scratchpad), ('notes', self.notes_area), ('cards', self.flashcards_area))}
        previous = {name: self._lecture.get(name, '') for name in values}
        if previous != values and any(previous.values()):
            self._add_lecture_revision(previous)
        self._lecture.update(values, course=self.subject_input.text().strip(), segments=self._transcript_segments)

    def _add_lecture_revision(self, previous):
        history = self._lecture.setdefault('revisions', [])
        history.append({'saved_at': datetime.datetime.now().isoformat(timespec='seconds'), **previous})
        del history[:-25]

    def _persist_lecture(self, document):
        try:
            save_lecture(DATA_DIR, document)
            return True
        except (OSError, ValueError, TypeError) as exc:
            self.operation_status.setText(f'Lecture could not be saved: {exc}')
            return False

    def _save_active_lecture(self):
        self._lecture_timer.stop()
        self._snapshot_lecture()
        if not any(self._lecture.get(key) for key in ('segments', 'audio_path', 'notes', 'scratchpad', 'cards', 'chat', 'past_chats', 'bookmarks')) and self._lecture['title'] == 'Untitled lecture':
            self._set_lecture_save_status('')
            return True
        saved = self._persist_lecture(self._lecture)
        self._set_lecture_save_status('Saved locally' if saved else 'Changes not saved')
        return saved

    def _activate_lecture(self, document):
        if not self._save_active_lecture():
            return False
        self._open_lectures[self._lecture['id']] = self._lecture
        self._set_lecture_save_status('Saved locally' if 'version' in document else '')
        self._lecture = document = self._open_lectures.setdefault(document['id'], document)
        self._lecture.setdefault('title', document['source_name'])
        self._lecture_source_name = document['source_name']
        self._lecture_date = datetime.date.fromisoformat(document['lecture_date']) if document.get('lecture_date') else None
        self._transcript_segments = document['segments']
        self.transcript_navigation.close_search()
        self.transcript_navigation.track_playback(None)
        self.speaker_panel.filters.blockSignals(True)
        self.speaker_panel.filters.setCurrentIndex(0)
        self.speaker_panel.filters.blockSignals(False)
        self.subject_input.setText(document.get('course', ''))
        for name, editor in (('scratchpad', self.user_scratchpad), ('notes', self.notes_area), ('cards', self.flashcards_area)):
            blocked = editor.blockSignals(True)
            editor.setPlainText(document.get(name, ''))
            editor.blockSignals(blocked)
        self._render_transcript()
        self._render_chat()
        self.transcript_tools.display(document)
        self.transcript_navigation.track_playback(self.transcript_tools.current_time())
        self._refresh_speaker_controls()
        return True

    def _open_library(self):
        if self.worker and (self.worker.isRunning() or self.worker in self._jobs):
            self.operation_status.setText('Finish transcription before opening another lecture.')
            return
        if not self._save_active_lecture():
            return
        dialog = LectureLibrary(DATA_DIR, self)
        apply_theme(dialog)
        if dialog.exec_() == QDialog.Accepted:
            path, start = dialog.selected
            self._open_lecture_path(path, start)

    def _open_saved_transcript(self):
        if self.worker and (self.worker.isRunning() or self.worker in self._jobs):
            self.operation_status.setText('Finish transcription before opening another lecture.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Open saved transcript', str(DATA_DIR / 'transcripts'), 'Lecture transcript (*.json)')
        if path:
            self._open_lecture_path(path)

    def _open_lecture_path(self, path, start=None):
        try:
            if self._activate_lecture(load_transcript(path)):
                self._switch_tab(1)
                if start is not None:
                    self._seek_transcript(start)
                return True
        except (ValueError, OSError) as exc:
            self.operation_status.setText(str(exc))
        return False

    def _edit_lecture_details(self):
        self._snapshot_lecture()
        dialog = LectureDetails(self._lecture, self)
        apply_theme(dialog)
        if dialog.exec_() == QDialog.Accepted:
            self._lecture.update(dialog.values)
            self.subject_input.setText(dialog.values['course'])
            raw_date = dialog.values['lecture_date']
            self._lecture_date = datetime.date.fromisoformat(raw_date) if raw_date else None
            self.transcript_tools.display(self._lecture)
            self._save_active_lecture()

    def _restore_lecture_revision(self):
        self._save_active_lecture()
        history = self._lecture.get('revisions', [])
        labels = [f"{i+1}. {row['saved_at']}" for i, row in enumerate(history)]
        if not labels:
            self.operation_status.setText('This lecture has no previous saved edits.')
            return
        choice, confirmed = QInputDialog.getItem(self, 'Lecture history', 'Restore a version', labels, len(labels)-1, False)
        if not confirmed:
            return
        revision = history[labels.index(choice)]
        for name, editor in (('scratchpad', self.user_scratchpad), ('notes', self.notes_area), ('cards', self.flashcards_area)):
            if name in revision:
                editor.setPlainText(revision[name])
        if 'segments' in revision:
            self._add_lecture_revision({'segments': [dict(item) for item in self._transcript_segments],
                                        'speaker_names': dict(self._lecture.get('speaker_names', {}))})
            self._transcript_segments[:] = deepcopy(revision['segments'])
            self._lecture['speaker_names'] = dict(revision.get('speaker_names', {}))
            self._lecture['speaker_reviewed'] = True
            self._render_transcript()
        self._save_active_lecture()

    def _build_chat_tab(self) -> QWidget:
        box = QWidget()
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        settings = QHBoxLayout()
        self.use_chat_source = QCheckBox('Include this lecture in the next request')
        settings.addWidget(self.use_chat_source, 1)
        restore_chat = QPushButton('Conversations…')
        restore_chat.clicked.connect(self._restore_chat)
        settings.addWidget(restore_chat)
        clear_chat = QPushButton('New conversation')
        clear_chat.clicked.connect(self._new_chat)
        settings.addWidget(clear_chat)
        vbox.addLayout(settings)
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText("Think it through with Annie.\n\nAsk for an explanation, work through a problem, or explore a new idea.")
        vbox.addWidget(self.chat_history, 1)

        in_row = QHBoxLayout()
        in_row.setSpacing(8)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Ask a question…")
        self.chat_input.returnPressed.connect(self._send_chat)
        in_row.addWidget(self.chat_input, 1)

        send_btn = self.send_chat_btn = QPushButton("Send")
        send_btn.setFixedHeight(36)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {EMERALD};
                color: #1B1E19;
                border: none;
                border-radius: 10px;
                padding: 6px 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {EMERALD_HOVER};
            }}
        """)
        send_btn.clicked.connect(self._send_chat)
        in_row.addWidget(send_btn)

        vbox.addLayout(in_row)
        return box

    def _load_classes(self):
        self.timetable_view.events_loaded.connect(self._populate_classes)
        QTimer.singleShot(0, self.timetable_view._refresh)

    def _populate_classes(self, events):
        from annie.gui.week_calendar import TZ
        today = datetime.datetime.now(TZ).date()
        selected = self.class_picker.currentData()
        self.class_picker.blockSignals(True)
        self.class_picker.clear()
        self.class_picker.addItem("Select a class", "")
        for event in events:
            try:
                if event.get('extendedProperties', {}).get('private', {}).get('annieStudySession'):
                    continue
                raw = event.get('start', {}).get('dateTime')
                if not raw:
                    continue
                start = datetime.datetime.fromisoformat(raw.replace('Z', '+00:00'))
                start = start.replace(tzinfo=TZ) if start.tzinfo is None else start.astimezone(TZ)
                if start.date() != today:
                    continue
                title = event.get('summary') or 'Class'
                self.class_picker.addItem(f'[{start:%H:%M}] {title}', title)
            except (TypeError, ValueError):
                continue
        index = self.class_picker.findData(selected)
        self.class_picker.setCurrentIndex(max(0, index))
        self.class_picker.blockSignals(False)

    def _on_class_picked(self, index: int):
        val = self.class_picker.itemData(index)
        if val:
            self.subject_input.setText(val)

    def _on_timetable_class_selected(self, title: str):
        self.subject_input.setText(title)
        self._switch_tab(0)

    def _build_notes_fusion_tab(self) -> QWidget:
        self.notes_splitter = QSplitter(Qt.Horizontal)
        self.notes_splitter.setChildrenCollapsible(False)
        self.notes_splitter.setHandleWidth(9)
        for index, title in enumerate(('Your highlights', 'Study notes')):
            panel = role(QFrame(), 'notesInput' if index == 0 else 'notesOutput')
            column = QVBoxLayout(panel)
            column.setContentsMargins(14, 12, 14, 12)
            heading = QHBoxLayout()
            heading.addWidget(label(title, 'section'), 1)
            column.addLayout(heading)
            editor = role(QTextEdit(), "paper")
            editor.setMinimumSize(100, 60)
            column.addWidget(editor, 1)
            if index == 0:
                self.user_scratchpad = editor
                editor.setAccessibleName("Your lecture highlights")
                editor.setPlaceholderText('Add key ideas, questions, or reminders…')
            else:
                self.notes_area = editor
                editor.setAcceptRichText(False)
                editor.setAccessibleName("Generated study notes")
                editor.setPlaceholderText('Create study notes from your transcript or highlights, or write your own.')
                self.fuse_btn = QPushButton("Create study notes")
                self.fuse_btn.clicked.connect(self._fuse_notes)
                self.fuse_btn.setToolTip("Combine your highlights with the lecture transcript")
                heading.addWidget(self.fuse_btn)
            self.notes_splitter.addWidget(panel)
        self.notes_splitter.setSizes([380, 620])
        return self.notes_splitter

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "notes_splitter"):
            compact = self.width() < 900
            self.studio_layout.setContentsMargins(*((16, 10, 16, 10) if compact else (22, 18, 22, 18)))
            self.studio_layout.setSpacing(8 if compact else 12)
            self.recording_panel.setMinimumHeight(68 if compact else 76)
            self.nav_layout.setContentsMargins(8, 6 if compact else 10, 8, 6 if compact else 8)
            self.signal_widget.setFixedWidth(44 if compact else 72)
            self.updates_panel.check_button.setVisible(not compact)
            self.gpa_page.set_compact(self.width() < 760)
            self.audio_source_picker.setToolTip(self.audio_source_picker.currentText())
            self.workspace_body.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
            self.nav_layout.setDirection(QBoxLayout.LeftToRight if compact else QBoxLayout.TopToBottom)
            self.navigation.setMinimumWidth(0 if compact else 172)
            self.navigation.setMaximumWidth(16777215 if compact else 172)
            self.navigation.setMaximumHeight(58 if compact else 16777215)
            orientation = Qt.Vertical if self.width() < 800 and self.height() >= 700 else Qt.Horizontal
            if self.notes_splitter.orientation() != orientation:
                self.notes_splitter.setOrientation(orientation)
                self.notes_splitter.setSizes([400, 600])

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == 'darwin' and not self.testAttribute(Qt.WA_DontShowOnScreen):
            from annie.macos_support import set_studio_visible
            set_studio_visible(True)
        if hasattr(self, 'study_page') and self.study_page._stopping:
            self.study_page.resume_background()
        if not self.isMinimized() and self._mini_dock is not None:
            self._mini_dock.hide_immediately()
        if self._entrance_played or self.testAttribute(Qt.WA_DontShowOnScreen):
            return
        self._entrance_played = True
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(220)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._window_animation = animation

        animation.finished.connect(
            lambda: setattr(self, '_window_animation', None)
            if self._window_animation is animation else None
        )
        animation.start(QAbstractAnimation.DeleteWhenStopped)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.WindowStateChange and self.isMinimized()
                and hasattr(self, '_mini_dock')):
            self._restore_maximized = bool(event.oldState() & Qt.WindowMaximized)
            QTimer.singleShot(0, self._show_mini_dock)

    def _show_mini_dock(self):
        # A queued minimize may have been cancelled by an immediate restore.
        if not self.isMinimized():
            return
        if self._mini_dock is None:
            from annie.gui.studio_dock import StudioDock
            self._mini_dock = StudioDock()
            self._mini_dock.restore_requested.connect(self._restore_from_dock)
            self.meeting_state_changed.connect(self._mini_dock.set_recording)
            self.signal_widget.level_changed.connect(self._mini_dock.meter.update_level)
        screen = self.screen()
        self.hide()
        if sys.platform == 'darwin':
            from annie.macos_support import set_accessory_mode
            set_accessory_mode()
        self._mini_dock.set_recording(self._recording)
        self._mini_dock.present(screen)

    def _restore_from_dock(self):
        def restore():
            if self._restore_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()

        if self._mini_dock is not None:
            self._mini_dock.dismiss_animated(restore)

    def _set_record_button_state(self, state):
        self.record_btn.setProperty("state", state)
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)
        self.record_btn.update()

    def _fuse_notes(self):
        transcript = self._last_transcript or self.transcript_area.toPlainText().strip()
        user_notes = self.user_scratchpad.toPlainText().strip()

        if not transcript and not user_notes:
            QMessageBox.information(self, "No Content", "Please record lecture audio or type your notes first.")
            return

        self.fuse_btn.setEnabled(False)
        self.fuse_btn.setText("Creating notes…")

        subj = self.subject_input.text().strip()
        self._fusion_thread = NoteFusionThread(transcript=transcript, context=subj, user_notes=user_notes, template="lecture")
        document = self._lecture
        expected = self.notes_area.toPlainText()
        self._fusion_thread.finished.connect(lambda text: self._on_fusion_finished(text, document, expected))
        self._fusion_thread.error.connect(self._on_fusion_error)
        self._start_job(self._fusion_thread)

    def _on_fusion_finished(self, notes_text: str, document=None, expected=None):
        self.fuse_btn.setEnabled(True)
        self.fuse_btn.setText("Create study notes")
        self._store_generated('notes', notes_text, document, expected=expected)

    def _store_generated(self, key, text, document=None, *, expected=None):
        document = self._lecture if document is None else document
        visible = document is self._lecture
        value = text.strip()
        if visible:
            self._snapshot_lecture()
        previous = document.get(key, '')
        if expected is not None and previous != expected:
            history = document.setdefault('revisions', [])
            history.append({'saved_at': datetime.datetime.now().isoformat(timespec='seconds'), key: value})
            del history[:-25]
            self._persist_lecture(document)
            if visible:
                self.operation_status.setText('Your edits were kept. The generated version is in lecture history.')
            return
        if visible:
            editor = self.notes_area if key == 'notes' else self.flashcards_area
            editor.setPlainText(value)
            self._save_active_lecture()
        else:
            previous = document.get(key)
            if previous and previous != text.strip():
                history = document.setdefault('revisions', [])
                history.append({'saved_at': datetime.datetime.now().isoformat(timespec='seconds'), key: previous})
                del history[:-25]
            document[key] = text.strip()
            self._persist_lecture(document)

    def _on_fusion_error(self, err: str):
        self.fuse_btn.setEnabled(True)
        self.fuse_btn.setText("Create study notes")
        self.operation_status.setText(f"Study notes could not be generated: {err}")

    def _toggle_recording(self):
        if self._recording:
            # Stop
            self.worker.user_notes = self.user_scratchpad.toPlainText().strip()
            self.worker.stop()
            self._recording = False
            self.signal_widget.set_active(False)
            self._set_capture_status('Stopping input…')
            self.meeting_state_changed.emit(False)
            self._refresh_audio_controls()
        else:
            if self._transcribing() or (self._audio_setup and self._audio_setup.task):
                return
            from annie.planner import TZ
            now = datetime.datetime.now(TZ)
            source_name = f"Lecture {now:%Y-%m-%d %H:%M} · {uuid.uuid4().hex[:8]}"
            if not self._activate_lecture(self._new_lecture(source_name, self.subject_input.text().strip(), now.date())):
                return

            self._set_capture_status('Opening audio source…')
            self.operation_status.setText('Processing · Preparing transcription')

            subject = self.subject_input.text().strip()
            user_notes = self.user_scratchpad.toPlainText().strip()
            selected_audio_dev = self.audio_source_picker.currentData()
            if selected_audio_dev is None:
                selected_audio_dev = "default"
            from annie.meeting import WhisperMeetingWorker
            from annie.config import WHISPER_MODEL
            self.worker = WhisperMeetingWorker(device=selected_audio_dev, model_name=WHISPER_MODEL, subject_context=subject, user_notes=user_notes)
            self.worker.transcript_updated.connect(self._on_transcript)
            self.worker.summary_ready.connect(self._on_summary)
            self.worker.status_changed.connect(self._on_worker_status)
            self._connect_transcription_events(self.worker)
            if hasattr(self.worker, 'audio_level'):
                self.worker.audio_level.connect(self.signal_widget.update_audio_level)
            if hasattr(self.worker, 'capture_finished'):
                self.worker.capture_started.connect(self._on_capture_started)
                self.worker.capture_finished.connect(self._on_capture_finished)
                self.worker.backlog_updated.connect(self._on_backlog)
                self.worker.recording_saved.connect(self._on_recording_saved)
            self._recording = True
            self._recording_session = True
            self.meeting_state_changed.emit(True)
            self._start_job(self.worker)
            self._refresh_audio_controls()
            self.stop_recording_btn.setFocus()

    def _import_audio(self):
        if self._transcribing() or (self._audio_setup and self._audio_setup.task):
            self.operation_status.setText("Finish the current audio task first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "", "Audio & Video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.webm *.mp4);;All Files (*)"
        )
        if not file_path:
            return

        source_name = f"{os.path.basename(file_path)} · {uuid.uuid4().hex[:8]}"
        if not self._activate_lecture(self._new_lecture(source_name, self.subject_input.text().strip(), audio=file_path)):
            return

        subj = self.subject_input.text().strip()
        user_notes = self.user_scratchpad.toPlainText().strip()
        from annie.meeting import AudioFileMeetingWorker
        from annie.config import WHISPER_MODEL
        self.worker = AudioFileMeetingWorker(file_path=file_path, model_name=WHISPER_MODEL, subject_context=subj, user_notes=user_notes)
        self.worker.transcript_updated.connect(self._on_transcript)
        self.worker.summary_ready.connect(self._on_summary)
        self.worker.status_changed.connect(self._on_worker_status)
        self._connect_transcription_events(self.worker)
        self._set_capture_status('')
        self.operation_status.setText('Processing · Preparing imported audio')
        self._start_job(self.worker)
        self._switch_tab(1)

    def _import_slide(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Slide / Blackboard Photo", "", "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)"
        )
        if not file_path:
            return

        subj = self.subject_input.text().strip()
        self._slide_thread = SlideVisionThread(file_path, subj)
        document = self._lecture
        self._slide_thread.finished.connect(lambda path, text: self._on_slide_finished(path, text, document))
        self._slide_thread.error.connect(self._on_slide_error)
        self._start_job(self._slide_thread)

    def _on_slide_finished(self, p, text, document=None):
        document = self._lecture if document is None else document
        block = f"\n\nSLIDE / WHITEBOARD ANALYSIS ({os.path.basename(p)})\n{text}\n"
        current = self.notes_area.toPlainText() if document is self._lecture else document.get('notes', '')
        self._store_generated('notes', current + block, document)
        if document is self._lecture:
            self.operation_status.setText("Slide analysis added to study notes.")
            self._switch_tab(0)

    def _on_slide_error(self, err):
        self.operation_status.setText(f"Slide analysis failed: {err}")

    def _create_exam_prep_guide(self):
        if self._recording:
            QMessageBox.information(
                self,
                "Work in progress",
                "Stop the current recording before creating a prep guide.",
            )
            return
        current_prep = getattr(self, '_prep_thread', None)
        if current_prep and current_prep.isRunning():
            QMessageBox.information(
                self,
                "Prep guide in progress",
                "A preparation guide is already being created. Progress is shown above the workspace.",
            )
            return

        assessment_type, accepted = QInputDialog.getItem(
            self,
            "Create exam prep guide",
            "Assessment type:",
            ("Quiz", "Midterm", "Final"),
            0,
            False,
        )
        if not accepted:
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Select materials for {assessment_type}",
            "",
            "Study materials (*.pdf *.pptx *.docx *.png *.jpg *.jpeg *.jpe *.jpef *.webp *.bmp *.gif *.txt *.md);;All files (*)",
        )
        if not file_paths:
            return

        self.operation_status.setText(
            f"Preparing {assessment_type.lower()} guide from {len(file_paths)} file(s)…"
        )
        self._prep_thread = PrepGuideThread(
            file_paths,
            assessment_type,
            self.subject_input.text().strip(),
        )
        self._prep_thread.status.connect(self.operation_status.setText)
        document = self._lecture
        expected = self.notes_area.toPlainText()
        self._prep_thread.finished.connect(lambda guide: self._on_prep_guide_finished(guide, document, expected))
        self._prep_thread.error.connect(self._on_prep_guide_error)
        self._start_job(self._prep_thread)

    def _on_prep_guide_finished(self, guide, document=None, expected=None):
        self._store_generated('notes', guide, document, expected=expected)
        if document is None or document is self._lecture:
            self.operation_status.setText("Exam preparation guide ready.")
            self._switch_tab(0)

    def _on_prep_guide_error(self, err):
        self.operation_status.setText(f"Prep guide failed: {err}")
        QMessageBox.warning(self, "Prep guide failed", err)

    def _on_transcript(self, text: str):
        cursor = self.transcript_area.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text, QTextCharFormat())
        self.transcript_area.setTextCursor(cursor)
        self._last_transcript = self.transcript_area.toPlainText()

    def _connect_transcription_events(self, worker):
        worker.transcript_segment.connect(self._on_transcript_segment)
        worker.metrics_updated.connect(self._on_transcription_metrics)
        worker.partial_transcript_updated.connect(
            lambda text: self.operation_status.setText(f'Processing · {text[-140:]}') if text else None)
        worker.transcript_ready.connect(self._on_transcription_ready)

    def _on_transcript_segment(self, segment):
        self._transcript_segments.append(segment)

    def _on_transcription_metrics(self, metrics):
        parts = []
        if metrics.get('backend'):
            parts.append(str(metrics['backend']))
        if metrics.get('inference_seconds') and metrics.get('audio_seconds'):
            parts.append(f"processing {metrics['inference_seconds'] / metrics['audio_seconds']:.2f}× real time")
        if metrics.get('backlog_seconds', 0) >= 2:
            parts.append(f"{metrics['backlog_seconds']:.0f}s pending")
        if metrics.get('audio_interruptions'):
            parts.append(f"{metrics['audio_interruptions']} audio interruptions")
        if parts:
            self.operation_status.setText('Processing · ' + ' · '.join(parts))

    def _on_transcription_ready(self):
        self._lecture['complete'] = True
        self._render_transcript()
        self._save_active_lecture()
        self.transcript_tools.display(self._lecture)
        self._switch_tab(1)

    def _save_transcript_archive(self, complete=False):
        if complete:
            self._lecture['complete'] = True
        self._render_transcript()
        self.transcript_tools.display(self._lecture)
        self._save_active_lecture()
        self._refresh_speaker_controls()

    def _render_transcript(self, *, refresh_speakers=True):
        if refresh_speakers:
            self._refresh_speaker_controls()
        self._transcript_ranges = []
        self.transcript_area.clear()
        cursor = self.transcript_area.textCursor()
        passage_format = QTextBlockFormat()
        passage_format.setBottomMargin(10)
        passage_format.setLineHeight(128, QTextBlockFormat.ProportionalHeight)
        clock_format = QTextCharFormat()
        clock_format.setForeground(QColor(TEXT_DIM))
        clock_format.setFontPointSize(10)
        clock_format.setFontWeight(QFont.DemiBold)
        speaker_format = QTextCharFormat()
        speaker_format.setForeground(QColor(EMERALD))
        speaker_format.setFontWeight(QFont.DemiBold)
        speech_format = QTextCharFormat()
        speech_format.setForeground(QColor(TEXT_MAIN))
        displays = self._lecture.get('speaker_names', {})
        kind, selected = self.speaker_panel.selection()
        lines = []
        visible_passages = []
        for segment in self._transcript_segments:
            identity = segment.get('speaker', '')
            speaker = displays.get(identity, identity)
            start = segment['start']
            text = segment.get('edited_text', segment['text'])
            speaker_prefix = f'{speaker} · ' if speaker else ''
            lines.append(f'[{timestamp(start)}] {speaker_prefix}{text}')
            if (kind == 'speaker' and identity != selected or kind == 'uncertain' and identity
                    or kind == 'overlap' and segment['id'] not in self._overlap_rows):
                continue
            if cursor.position():
                cursor.insertBlock(passage_format, speech_format)
            else:
                cursor.setBlockFormat(passage_format)
            begin = cursor.position()
            clock_format.setToolTip(f'Play from {timestamp(start)}')
            cursor.insertText(playback_time(start) + '   ', clock_format)
            cursor.insertText(speaker_prefix, speaker_format)
            text_start = cursor.position()
            visible_text = text.replace('\r\n', '\n').replace('\r', '\n')
            cursor.insertText(visible_text, speech_format)
            self._transcript_ranges.append((begin, cursor.position(), segment))
            visible_passages.append((begin, cursor.position(), start, segment['end'], text_start, visible_text))
        if kind == 'all':
            placeholder = 'Open Notes to start a recording, or choose Import audio.'
        else:
            placeholder = 'No passages match this filter.'
        self.transcript_area.setPlaceholderText(placeholder)
        cursor.setPosition(0)
        self.transcript_area.setTextCursor(cursor)
        self._last_transcript = '\n'.join(lines)
        self.transcript_navigation.set_passages(visible_passages)

    def _filter_transcript(self):
        self._render_transcript(refresh_speakers=False)

    def _open_transcript_search(self):
        if self.transcript_tools.find.isEnabled():
            self.transcript_navigation.open_search()

    def _show_transcript_bookmarks(self):
        document = self._lecture
        saved = document.get('bookmarks', [])
        selection = self._selected_passages()
        passage = selection[0]['start'] if len(selection) == 1 else None
        dialog = TranscriptBookmarks(saved, self.transcript_tools.current_time(), passage, self)
        apply_theme(dialog)
        if dialog.exec_() != QDialog.Accepted or document is not self._lecture:
            return
        if dialog.bookmarks != saved:
            document['bookmarks'] = dialog.bookmarks
            if not self._save_active_lecture():
                document['bookmarks'] = saved
                return
        if dialog.jump_time is not None:
            self._seek_transcript(dialog.jump_time)
            self.transcript_tools.jump_to(dialog.jump_time)

    def _play_speaker_sample(self, identity):
        from annie.diarization import speaker_voice_sample
        sample = speaker_voice_sample(self._transcript_segments, identity, self._overlap_windows)
        if sample:
            self._seek_transcript(sample[0])
            self.transcript_tools.play_at(*sample)
        else:
            self.transcript_tools.set_status('No clean voice sample is available for this speaker.')

    def _selected_passages(self):
        cursor = self.transcript_area.textCursor()
        if cursor.hasSelection():
            return [row for start, end, row in self._transcript_ranges
                    if start < cursor.selectionEnd() and end > cursor.selectionStart()]
        return [row for start, end, row in self._transcript_ranges if start <= cursor.position() <= end]

    def _edit_current_passage(self):
        if self._transcribing():
            return
        rows = self._selected_passages()
        if len(rows) == 1:
            self._edit_passage(rows[0])
        elif rows:
            self.transcript_tools.set_status('Select one passage to edit its text.')

    def _assign_transcript_selection(self):
        if self._transcribing():
            return
        rows = self._selected_passages()
        if rows:
            self._assign_passages(rows)

    def eventFilter(self, watched, event):
        if (watched is getattr(self, '_transcript_viewport', None)
                and event.type() in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick) and event.button() == Qt.LeftButton):
            point = self.transcript_area.cursorForPosition(event.pos()).position()
            double = event.type() == QEvent.MouseButtonDblClick
            segment = next((row for left, right, row in self._transcript_ranges
                            if left <= point <= (right if double else left + len(playback_time(row['start'])))), None)
            if segment:
                self._seek_transcript(segment['start'], play=True)
                return True
        return super().eventFilter(watched, event)

    def _transcript_menu(self, point):
        cursor = self.transcript_area.cursorForPosition(point)
        current = next((row for start, end, row in self._transcript_ranges if start <= cursor.position() <= end), None)
        menu = self.transcript_area.createStandardContextMenu()
        busy = self.worker and (self.worker.isRunning() or self.worker in self._jobs)
        if current and not busy:
            selected = self.transcript_area.textCursor()
            rows = [row for start, end, row in self._transcript_ranges
                    if selected.hasSelection() and start < selected.selectionEnd() and end > selected.selectionStart()]
            menu.addSeparator()
            menu.addAction('Play this passage', lambda: self._seek_transcript(current['start'], play=True))
            menu.addAction('Edit passage text…', lambda: self._edit_passage(current))
            menu.addAction('Assign selected passage(s)…', lambda: self._assign_passages(rows or [current]))
            if current.get('speaker'):
                menu.addAction('Rename all passages by this speaker…', lambda: self._rename_speaker(current['speaker']))
                menu.addAction('Merge this speaker into another…', lambda: self._merge_speaker(current['speaker']))
        menu.exec_(self.transcript_area.viewport().mapToGlobal(point))

    def _track_transcript_revision(self):
        self._add_lecture_revision({'segments': deepcopy(self._transcript_segments),
                                    'speaker_names': dict(self._lecture.get('speaker_names', {}))})

    def _finish_transcript_edit(self):
        self._lecture['speaker_reviewed'] = True
        self._render_transcript()
        self._save_active_lecture()

    def _edit_passage(self, current):
        text, ok = QInputDialog.getMultiLineText(self, 'Edit passage', 'Transcript text',
                                               current.get('edited_text', current['text']))
        if ok and text.strip():
            self._track_transcript_revision()
            current['edited_text'] = text.strip()
            self._render_transcript()
            self._save_active_lecture()
            self.review_page.status.setText('A local transcript edit was saved. Source quotes still refer to the original recording. Recheck any finding affected by the edit.')

    def _speaker_options(self):
        names = self._lecture.get('speaker_names', {})
        return {f'{names.get(identity, identity)} [{identity}]': identity for identity in
                sorted({row.get('speaker') for row in self._transcript_segments if row.get('speaker')})}

    def _assign_passages(self, rows):
        options = self._speaker_options()
        new = 'Create a speaker…'
        clear = 'Leave unassigned'
        available = [*options, new, clear] if options else [new, clear]
        choice, ok = QInputDialog.getItem(self, 'Assign speaker', 'Speaker', available, 0, False)
        if not ok:
            return
        name = ''
        if choice == new:
            name = self.transcript_tools.choose_label(f'Speaker {len(options)+1}')
            if not name:
                return
            identity = f'manual-{uuid.uuid4().hex[:8]}'
        else:
            identity = options.get(choice, '')
        if all(row.get('speaker', '') == identity for row in rows):
            return
        self._track_transcript_revision()
        if name:
            self._lecture.setdefault('speaker_names', {})[identity] = name
        for row in rows:
            row['speaker'] = identity
        self._finish_transcript_edit()

    def _rename_speaker(self, identity):
        names = self._lecture.setdefault('speaker_names', {})
        name = self.transcript_tools.choose_label(names.get(identity, identity))
        if name:
            self._track_transcript_revision()
            names[identity] = name
            self._finish_transcript_edit()

    def _merge_speaker(self, source):
        options = {key: value for key, value in self._speaker_options().items() if value != source}
        if not options:
            self.transcript_tools.set_status('There is no other speaker to merge into.')
            return
        choice, ok = QInputDialog.getItem(self, 'Merge speaker', 'Merge all passages into', list(options), 0, False)
        if ok:
            self._track_transcript_revision()
            for row in self._transcript_segments:
                if row.get('speaker') == source:
                    row['speaker'] = options[choice]
            self._lecture.get('speaker_names', {}).pop(source, None)
            self._finish_transcript_edit()

    def _refresh_speaker_controls(self):
        from annie.diarization import diarization_ready, overlap_windows, overlapping_passages
        tools = self.transcript_tools
        running = self._speaker_job is not None
        audio = self._lecture.get('audio_path')
        has_audio = bool(audio and Path(audio).is_file())
        editable = not self._transcribing()
        tools.find.setEnabled(editable and bool(self._transcript_segments))
        tools.bookmarks.setEnabled(editable and bool(self._transcript_segments or self._lecture.get('bookmarks')
                                                     or tools.play.isEnabled()))
        tools.diarize.setEnabled(not running and editable and bool(self._transcript_segments) and has_audio)
        tools.diarize.setText('Label speakers…' if diarization_ready(self._diarization_model) else 'Set up speakers…')
        tools.cancel.setVisible(running)
        self._overlap_windows = overlap_windows(self._lecture.get('speaker_turns'))
        self._overlap_rows = overlapping_passages(self._transcript_segments, self._overlap_windows)
        counts = Counter(row.get('speaker') or '' for row in self._transcript_segments)
        uncertain = counts.pop('', 0)
        self.speaker_panel.display(counts, self._lecture.get('speaker_names', {}),
            len(self._transcript_segments), uncertain, len(self._overlap_rows), has_audio=tools.play.isEnabled(),
            editable=editable)

    @staticmethod
    def _load_speaker_model():
        try:
            return (DATA_DIR / 'speaker-model-folder.txt').read_text(encoding='utf-8').strip() or None
        except (OSError, UnicodeError):
            return None

    def _request_diarization(self):
        from annie.diarization import diarization_ready
        if self._speaker_job:
            return
        if not diarization_ready(self._diarization_model):
            self._open_audio_setup(models=True)
            return
        if self._lecture.get('speaker_reviewed'):
            accepted = QMessageBox.question(self, 'Run speaker detection again?',
                'Save the current labels to lecture history and replace them with a new automatic pass?',
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if accepted != QMessageBox.Yes:
                return
        count, ok = QInputDialog.getInt(self, 'Speakers', 'Expected speakers (0 to detect automatically)', 0, 0, 40)
        if ok:
            self._start_diarization(count or None)

    def _start_diarization_if_ready(self):
        if self._speaker_job or not self._transcript_segments or self._lecture.get('speaker_reviewed'):
            return
        from annie.diarization import diarization_ready
        if self._lecture.get('audio_path') and diarization_ready(self._diarization_model):
            self._start_diarization()

    def _start_diarization(self, count=None):
        audio = self._lecture.get('audio_path')
        if self._speaker_job or not audio or not Path(audio).is_file() or not self._transcript_segments:
            return
        document = self._lecture
        job = SpeakerDetection(audio, self._diarization_model, count, self)
        self._speaker_job = job
        signature = self._speaker_signature(document)
        job.result.connect(lambda turns: self._finish_diarization_result(document, signature, job, turns))
        job.error.connect(lambda error: self.transcript_tools.set_status(error)
                          if document is self._lecture else None)
        job.finished.connect(self._diarization_finished)
        self.transcript_tools.set_status('Identifying speakers on this computer…')
        self._refresh_speaker_controls()
        self._start_job(job)

    @staticmethod
    def _speaker_signature(document):
        return (document.get('audio_path'), dict(document.get('speaker_names', {})),
                tuple((row.get('id'), row['start'], row['end'], row.get('speaker'), row.get('edited_text'))
                      for row in document['segments']))

    def _finish_diarization_result(self, document, signature, job, turns):
        if job.cancel_event.is_set():
            return
        if self._speaker_signature(document) != signature:
            if document is self._lecture:
                self.transcript_tools.set_status('The audio or speaker labels changed. Run speaker analysis again to apply a new result.')
            return
        self._apply_diarization(document, turns)

    def _apply_diarization(self, document, turns):
        if not turns:
            self.transcript_tools.set_status('No speaker intervals were detected. The existing transcript is available.')
            return
        from annie.diarization import assign_speaker_words, assign_speakers
        from annie.lecture_archive import archive_segments
        originals = archive_segments(document.get('source_segments', document['segments']))
        document['source_segments'] = originals
        rows = archive_segments(document['segments'])
        assignments = assign_speakers(originals, turns)
        timed_words = assign_speaker_words(originals, turns)
        history = document.setdefault('revisions', [])
        history.append({'saved_at': datetime.datetime.now().isoformat(timespec='seconds'),
                        'segments': rows, 'speaker_names': dict(document.get('speaker_names', {}))})
        del history[:-25]
        by_original = {}
        for row in rows:
            by_original.setdefault(row.get('source_segment_id', row['id']), []).append(row)
        passages = []
        for original in originals:
            identity = original['id']
            previous = by_original.get(identity, [original])
            if any('edited_text' in row for row in previous):
                current = assign_speakers(previous, turns)
                passages.extend({**row, 'speaker': current.get(row['id'], '')} for row in previous)
                continue
            words = timed_words.get(identity, [])
            speakers = {word['speaker'] for word in words if word['speaker']}
            if len(speakers) <= 1 or ' '.join(''.join(word['text'] for word in words).split()) != ' '.join(original['text'].split()):
                passages.append({**original, 'speaker': assignments.get(identity, '')})
                continue
            from itertools import groupby
            for index, (speaker, group) in enumerate(groupby(words, key=lambda word: word['speaker'])):
                items = list(group)
                passages.append({**original, 'id': f'{identity}-{index}', 'source_segment_id': identity,
                    'speaker': speaker, 'start': items[0]['start'], 'end': items[-1]['end'],
                    'text': ''.join(word['text'] for word in items).strip(), 'words': items})
        document['segments'][:] = passages
        document['speaker_names'] = {}
        document['speaker_turns'] = turns
        document['speaker_reviewed'] = False
        if document is self._lecture:
            self._render_transcript()
            self._save_active_lecture()
            self.transcript_tools.set_status('Speaker labels are ready. Choose a speaker or a review filter.')
        else:
            self._persist_lecture(document)

    def _cancel_diarization(self):
        if self._speaker_job:
            self._speaker_job.cancel_event.set()

    def _diarization_finished(self):
        self._speaker_job = None
        self._refresh_speaker_controls()

    def _seek_transcript(self, seconds, *, play=False):
        if self.stack.currentIndex() != 1:
            self._switch_tab(1)
        exact = next((r for r in self._transcript_ranges if r[2]['start'] == seconds), None)
        match = exact or next((r for r in self._transcript_ranges
                               if r[2]['start'] <= seconds < r[2]['end']), None)
        if match is None:
            original = next((row for row in self._lecture.get('source_segments', ())
                             if row['start'] <= seconds < row['end']), None)
            if original:
                pieces = (row for row in self._transcript_ranges if row[2].get('source_segment_id') == original['id'])
                match = min(pieces, key=lambda row: abs(row[2]['start'] - seconds), default=None)
        if match is None and self.speaker_panel.selection()[0] != 'all':
            self.speaker_panel.filters.setCurrentIndex(0)
            self._seek_transcript(seconds, play=play)
            return
        if match is not None:
            cursor = self.transcript_area.textCursor()
            cursor.setPosition(match[0])
            cursor.setPosition(match[1], QTextCursor.KeepAnchor)
            self.transcript_area.setTextCursor(cursor)
            self.transcript_area.ensureCursorVisible()
        if play:
            self.transcript_tools.play_at(seconds)

    def _show_transcript_evidence(self, seconds):
        action = self.review_page._current()
        self._open_evidence_source(action.get('source_name') if action else None, seconds)

    def _open_evidence_source(self, source, seconds):
        if source and source != self._lecture_source_name:
            if self.worker and (self.worker.isRunning() or self.worker in self._jobs):
                self.operation_status.setText('Finish transcription before opening the evidence lecture.')
                return
            match = next((path for path, document in library_entries(DATA_DIR)
                          if document['source_name'] == source), None)
            if not match or not self._open_lecture_path(match):
                self.operation_status.setText('This finding has a saved quote. Its lecture archive is unavailable.')
                return
        self._seek_transcript(seconds, play=True)

    def _on_summary(self, summary_text: str):
        if summary_text.startswith(('# Recording Error', '# Incomplete Recording', '# Transcription Error',
                                    '# Empty Recording', '# Empty Meeting', '# Notes Error')):
            self.operation_status.setText(summary_text.splitlines()[0].lstrip('# '))
            return
        self._store_generated('notes', summary_text, expected='')
        self._switch_tab(0)

    def _refresh_due_cards(self):
        import sqlite3
        from annie.flashcard_review import CardReviews
        try:
            count = sum(1 for _ in CardReviews(DATA_DIR).due())
        except (OSError, ValueError, sqlite3.Error):
            self.due_cards.hide()
            return
        self.due_cards.setText(f'Review flashcards · {count} due')
        self.due_cards.setVisible(bool(count))

    def _review_flashcards(self):
        import sqlite3
        from annie.gui.flashcard_review import FlashcardSession
        if self._save_active_lecture():
            try:
                FlashcardSession(DATA_DIR, self).exec_()
            except (OSError, ValueError, sqlite3.Error):
                self.operation_status.setText('Flashcard review could not open the local library.')
            self._refresh_due_cards()

    def _add_flashcard(self):
        from annie.flashcard_review import export_tsv, parse_cards
        front, ok = QInputDialog.getText(self, 'Add flashcard', 'Question')
        if not ok or not front.strip():
            return
        back, ok = QInputDialog.getMultiLineText(self, 'Add flashcard', 'Answer')
        if ok and back.strip():
            rows = parse_cards(self.flashcards_area.toPlainText())
            self.flashcards_area.setPlainText(export_tsv([*rows, (front.strip(), back.strip(), '')]))

    def _export_flashcards(self):
        from annie.flashcard_review import export_tsv, parse_cards
        rows = parse_cards(self.flashcards_area.toPlainText())
        if not rows:
            self.operation_status.setText('Add a flashcard with a question and answer before exporting.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Anki TSV', 'flashcards.tsv', 'TSV (*.tsv)')
        if path:
            from annie.secure_storage import atomic_write
            try:
                atomic_write(path, export_tsv(rows).encode('utf-8'))
            except OSError as exc:
                self.operation_status.setText(f'Could not export flashcards: {exc}')

    def _generate_anki(self):
        text = self.notes_area.toPlainText() or self._last_transcript
        if not text:
            QMessageBox.information(self, "No Content", "Record or import a lecture first.")
            return

        self.gen_anki_btn.setEnabled(False)
        self.gen_anki_btn.setText("Generating...")

        user_notes = self.user_scratchpad.toPlainText().strip()
        self._anki_thread = AnkiGenThread(text, self.subject_input.text().strip(), user_notes=user_notes)
        document = self._lecture
        expected = self.flashcards_area.toPlainText()
        self._anki_thread.finished.connect(lambda deck: self._on_anki_finished(deck, document, expected))
        self._anki_thread.error.connect(self._on_anki_error)
        self._start_job(self._anki_thread)

    def _on_anki_finished(self, deck, document=None, expected=None):
        self.gen_anki_btn.setEnabled(True)
        self.gen_anki_btn.setText("Make flashcards")
        from annie.flashcard_review import export_tsv, parse_cards
        rows = parse_cards(deck)
        if not rows:
            self.operation_status.setText('Generated cards did not contain a valid TSV deck.')
            return
        self._store_generated('cards', export_tsv(rows), document, expected=expected)
        if document is None or document is self._lecture:
            self._switch_tab(2)

    def _on_anki_error(self, err):
        self.gen_anki_btn.setEnabled(True)
        self.gen_anki_btn.setText("Make flashcards")
        self.operation_status.setText(f"Flashcards could not be generated: {err}")

    def _render_chat(self):
        session = self._lecture.get('chat', [])
        self.chat_history.setPlainText('\n\n'.join(
            ('You' if row['role'] == 'user' else 'Annie') + ': ' + row['text']
            for row in session))
        self.chat_history.moveCursor(QTextCursor.End)
        self.use_chat_source.setText('Attach this lecture to the conversation' if not self._lecture.get('chat_context')
                                     else 'Update attached lecture material')

    def _new_chat(self):
        if self._lecture.get('chat'):
            self._lecture.setdefault('past_chats', []).append(
                {'chat': self._lecture.pop('chat'), 'context': self._lecture.get('chat_context', '')})
            self._lecture.pop('chat_context', None)
            self._render_chat()
            self._save_active_lecture()

    def _restore_chat(self):
        sessions = self._lecture.get('past_chats', [])
        if not sessions:
            self.operation_status.setText('There are no previous conversations for this lecture.')
            return
        choices = [f"{i+1}. {item['chat'][0]['text'][:60]}" for i, item in enumerate(sessions)]
        choice, accepted = QInputDialog.getItem(self, 'Conversations', 'Conversation', choices, 0, False)
        if accepted:
            saved = sessions.pop(choices.index(choice))
            self._new_chat()
            self._lecture.update(chat=saved['chat'], chat_context=saved['context'])
            self._render_chat()
            self._save_active_lecture()

    def _send_chat(self):
        question = self.chat_input.text().strip()
        if not question or any(isinstance(job, StudyChatThread) and job.isRunning() for job in self._jobs):
            return
        document = self._lecture
        session = document.setdefault('chat', [])
        session.append({'role': 'user', 'text': question})
        self.chat_input.clear()
        self._render_chat()
        context = ''
        if self.use_chat_source.isChecked():
            self.use_chat_source.setChecked(False)
            context = (self.notes_area.toPlainText() or self._last_transcript)[:30000]
            if context:
                document['chat_context'] = context
                self._render_chat()
                self.operation_status.setText('Sending the selected lecture material and dialog to Gemini…')
        if document.get('chat_context'):
            context = 'Selected lecture material, use as reference only:\n' + document['chat_context'] + '\n\n'
        history = '\n'.join(f"{row['role']}: {row['text']}" for row in session[-20:])
        self._save_active_lecture()
        thread = StudyChatThread(context + history[-24000:])
        thread.finished.connect(lambda reply: self._on_chat_finished(reply, document, session))
        thread.error.connect(lambda err: self.operation_status.setText(f'Assistant: {err}'))
        self._start_job(thread)

    def _on_chat_finished(self, reply, document=None, session=None):
        document = self._lecture if document is None else document
        session = document.setdefault('chat', []) if session is None else session
        session.append({'role': 'assistant', 'text': reply})
        if document is self._lecture:
            self._render_chat()
            self._save_active_lecture()
        else:
            self._persist_lecture(document)

    def _show_export_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {BG_SURFACE};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {EMERALD_BG};
                color: {EMERALD};
            }}
        """)
        notes_commands = (('Copy notes', self._copy_notes), ('Obsidian Markdown (.md)', self._save_obsidian),
                          ('Notes as HTML (.html)', self._export_pdf))
        transcript_commands = (('Transcript text (.txt)', self._save_txt), ('Timed captions (.vtt)', self._export_captions))
        sections = [
            ('Notes', notes_commands, bool(self.notes_area.toPlainText().strip())),
            ('Transcript', transcript_commands, bool(self._last_transcript)),
        ]
        in_transcript = self.stack.currentIndex() == 1
        if in_transcript:
            sections.reverse()
        for section, commands, enabled in sections:
            menu.addSection(section)
            for title, callback in commands:
                action = menu.addAction(title, callback)
                action.setEnabled(enabled and (callback != self._export_captions or bool(self._transcript_segments)))

        anchor = self.transcript_tools.export if in_transcript else self.export_btn
        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _copy_notes(self):
        text = self.notes_area.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            if self.stack.currentIndex() == 1:
                self.operation_status.setText('Notes copied to clipboard.')
            else:
                self.export_btn.setText("Copied!")
                self.export_feedback_timer.start()

    def _restore_export_label(self):
        self.export_btn.setText('Export…')

    def _save_obsidian(self):
        text = self.notes_area.toPlainText()
        if not text:
            return
        date_str = self._lecture.get("lecture_date") or datetime.date.today().isoformat()
        subj = self.subject_input.text().strip() or "Lecture"
        frontmatter = f"---\ntags:\n  - university\n  - lecture\n  - {subj.replace(' ', '_').lower()}\ndate: {date_str}\n---\n\n"
        path, _ = QFileDialog.getSaveFileName(self, "Save Obsidian Note", f"{subj.replace(' ', '_')}_{date_str}.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(frontmatter + text)

    def _export_pdf(self):
        text = self.notes_area.toPlainText()
        if not text:
            return
        date_str = self._lecture.get("lecture_date") or datetime.date.today().isoformat()
        subj = self.subject_input.text().strip() or "Lecture Notes"
        subj, text = escape(subj), escape(text)
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subj}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1B1E19; color: #F1F3E9; padding: 40px 60px; line-height: 1.6; max-width: 860px; margin: auto; }}
  h1 {{ font-size: 26px; color: #F1F3E9; border-bottom: 2px solid #C5ED87; padding-bottom: 8px; }}
  h3 {{ font-size: 16px; color: #D9FFA5; margin-top: 20px; }}
</style></head>
<body><h1>{subj} ({date_str})</h1><pre style="font-family:inherit; white-space:pre-wrap;">{text}</pre></body></html>"""
        path, _ = QFileDialog.getSaveFileName(self, "Export notes as HTML", f"{subj.replace(' ', '_')}_{date_str}.html", "HTML (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            webbrowser.open(path)

    def _save_txt(self):
        text = self._last_transcript
        if text:
            path, _ = QFileDialog.getSaveFileName(self, "Save Transcript", "transcript.txt", "Text (*.txt)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)

    def _export_captions(self):
        if not self._transcript_segments:
            return
        from annie.secure_storage import atomic_write
        path, _ = QFileDialog.getSaveFileName(self, 'Export timed captions', 'transcript.vtt', 'WebVTT (*.vtt)')
        if not path:
            return
        labels = self._lecture.get('speaker_names', {})
        rows = ['WEBVTT', '']
        for segment in self._transcript_segments:
            rows.append(f"{timestamp(segment['start'])} --> {timestamp(segment['end'])}")
            text = escape(segment.get('edited_text', segment['text']))
            speaker = segment.get('speaker')
            rows.extend([(f"<v {escape(labels.get(speaker, speaker))}>{text}</v>" if speaker else text), ''])
        try:
            atomic_write(path, '\n'.join(rows).encode('utf-8'))
        except OSError as exc:
            self.operation_status.setText(f'Could not export captions: {exc}')

    def is_active(self) -> bool:
        return self._recording

    def _on_worker_status(self, status):
        self.operation_status.setText(status)

    def _set_capture_status(self, state):
        self.capture_status.setText(f'Audio input · {state}' if state else '')
        self.capture_status.setVisible(bool(state))

    def _refresh_audio_controls(self):
        transcribing = self._transcribing()
        preparing = bool(self._audio_setup and self._audio_setup.task)
        ready = not (transcribing or preparing)
        self.recording_panel.setVisible(self.stack.currentIndex() == 0 and not self._recording_session)
        self.signal_widget.setVisible(self._recording)
        self.stop_recording_btn.setVisible(self._recording_session)
        self.stop_recording_btn.setEnabled(self._recording)
        self.stop_recording_btn.setText('Stop recording' if self._recording else 'Finishing…')
        self.audio_check.setEnabled(ready)
        self.import_audio_button.setEnabled(ready)
        self.library_button.setEnabled(not transcribing)
        self.record_btn.setEnabled(ready)
        self.record_btn.setText('Processing audio…' if transcribing else 'Start recording')
        state = 'busy' if transcribing else 'idle'
        if self.record_btn.property('state') != state:
            self._set_record_button_state(state)

    def _on_capture_started(self):
        if self._recording:
            self._set_capture_status('Recording')
            self.signal_widget.set_active(True)

    def _on_capture_finished(self):
        if self._recording:
            self._recording = False
            self.meeting_state_changed.emit(False)
        self.signal_widget.set_active(False)
        self._set_capture_status('Stopped')
        self._refresh_audio_controls()

    def _on_backlog(self, seconds):
        if seconds >= 2:
            self.operation_status.setText(f"Processing · {seconds:.0f}s of audio pending")

    def _on_recording_saved(self, path):
        self._last_recording_path = path
        self._lecture['audio_path'] = path
        self.operation_status.setToolTip(f"Audio recording: {path}")
        self._save_active_lecture()

    def _start_job(self, job):
        # Retain all QThreads, including jobs whose custom 'finished' signal
        # fires before QThread.run() has actually returned.
        self._jobs.add(job)
        job.start()
        self._job_timer.start(100)

    def _reap_jobs(self):
        for job in list(self._jobs):
            if job.isFinished():
                self._jobs.discard(job)
                if job is self.worker:
                    self._save_transcript_archive()
                    self._start_diarization_if_ready()
                    self._recording_session = False
                    self.signal_widget.set_active(False)
                    self._set_capture_status('')
                    if self._recording:
                        self._recording = False
                        self.meeting_state_changed.emit(False)
                    self._refresh_audio_controls()
        if not self._jobs:
            self._job_timer.stop()

    def has_running_jobs(self):
        return (any(job.isRunning() for job in self._jobs) or
                (self._audio_setup is not None and self._audio_setup.task is not None) or
                self.updates_panel.service.is_running() or
                self.updates_panel.downloads.is_running() or
                self.timetable_view.has_running_job() or self.study_page.has_running_job() or
                self.planner_page.has_running_job() or self.review_page.has_running_job()
                or self.lab_page.has_running_job())

    def stop_jobs(self):
        if self._audio_setup is not None:
            self._audio_setup.reject()
        self.updates_panel.service.stop()
        self.updates_panel.downloads.cancel()
        if self.updates_panel.dialog is not None:
            self.updates_panel.dialog.close()
        self.study_page.stop_background()
        self.planner_page.stop_background()
        self.review_page.stop_background()
        self.lab_page.stop_background()
        self._cancel_diarization()
        if self._mini_dock is not None:
            self._mini_dock.hide_immediately()
        for job in list(self._jobs):
            if job.isRunning():
                if hasattr(job, 'stop'):
                    job.stop()
                else:
                    job.requestInterruption()
        self._recording = False
        self.signal_widget.set_active(False)
        self.meeting_state_changed.emit(False)

    def closeEvent(self, event):
        if not self._save_active_lecture():
            event.ignore()
            return
        self.radar_page.stop_receiver()
        self.stop_jobs()
        if sys.platform == 'darwin' and not self.testAttribute(Qt.WA_DontShowOnScreen):
            from annie.macos_support import set_accessory_mode
            set_accessory_mode()
        # Keep worker references alive while an in-flight model request ends.
        # The cached window can be reopened after closing its visible surface.
        super().closeEvent(event)
