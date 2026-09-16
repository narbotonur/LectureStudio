"""
Elite Annie — Modern Academic Workspace
Crafted with the clean, elegant design system of elitenuet.xyz (Tailwind & Shadcn aesthetic).
Ultra-clean, distraction-free, spacious UI for university lectures and study.
"""
import os
import sys
import webbrowser
import datetime
import math
from typing import Optional, List, Dict

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QFrame, QWidget, QSizePolicy, QApplication, QLineEdit,
    QFileDialog, QMessageBox, QStackedWidget, QSplitter, QListWidget, QListWidgetItem,
    QTimeEdit, QDateEdit, QScrollArea, QMenu, QAction, QBoxLayout, QShortcut,
    QInputDialog, QGraphicsOpacityEffect
)
from annie.gui.design import apply_theme, role, label, STYLE, UI_FONT

from PyQt5.QtCore import (
    QAbstractAnimation, QEasingCurve, QPropertyAnimation, Qt, pyqtSignal,
    QTimer, QRectF, QDate, QTime, QThread, QEvent,
)
from PyQt5.QtGui import QFont, QPainter, QColor, QLinearGradient, QBrush, QPen, QPainterPath

# ─────────────────────────────────────────────────────────────
#  Elite NUET Design Tokens (Tailwind / Shadcn Modern Light-Dark)
# ─────────────────────────────────────────────────────────────
EMERALD = "#C5ED87"
EMERALD_HOVER = "#D9FFA5"
EMERALD_BG = "rgba(0, 196, 140, 0.08)"
EMERALD_BORDER = "rgba(0, 196, 140, 0.25)"

# Modern Slate Theme (Inspired by elitenuet.xyz)
BG_APP = "#111310"             # Crisp modern slate-50
BG_SURFACE = "#1B1E19"         # Pure white card surface
BORDER_COLOR = "#343B30"       # Slate-200 border
BORDER_HOVER = "#47543D"       # Slate-300 border

TEXT_MAIN = "#F1F3E9"          # Slate-900 high contrast
TEXT_SUB = "#ADB6A4"           # Slate-600 readable body
TEXT_DIM = "#929D88"           # Slate-400 subtle hint


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
            end_dt = start_dt + datetime.timedelta(hours=1)

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
class ResponsiveComboBox(QComboBox):
    """Combobox that allows compact layout shrinking without locking min width to longest text."""
    def minimumSizeHint(self):
        sz = super().minimumSizeHint()
        sz.setWidth(min(sz.width(), 140))
        return sz


class SmoothStackedWidget(QStackedWidget):
    """A restrained fade between workspace pages without moving the layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade_animation = None

    def setCurrentIndexAnimated(self, index):
        if index == self.currentIndex():
            return
        if self._fade_animation:
            self._fade_animation.stop()
        page = self.widget(index)
        super().setCurrentIndex(index)
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        effect.setOpacity(0.28)
        animation = QPropertyAnimation(effect, b'opacity', self)
        animation.setDuration(180)
        animation.setStartValue(0.28)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def finished():
            if page.graphicsEffect() is effect:
                page.setGraphicsEffect(None)
            if self._fade_animation is animation:
                self._fade_animation = None

        animation.finished.connect(finished)
        self._fade_animation = animation
        animation.start(QAbstractAnimation.DeleteWhenStopped)


class AnimatedStatusLabel(QLabel):
    """Keep frequent recording status updates readable instead of jumpy."""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._status_effect = QGraphicsOpacityEffect(self)
        self._status_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._status_effect)
        self._status_animation = None

    def setText(self, text):
        if text == self.text():
            return
        super().setText(text)
        if self._status_animation:
            self._status_animation.stop()
        self._status_effect.setOpacity(0.58)
        animation = QPropertyAnimation(self._status_effect, b'opacity', self)
        animation.setDuration(160)
        animation.setStartValue(0.58)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._status_animation = animation

        def finished():
            if self._status_animation is animation:
                self._status_animation = None

        animation.finished.connect(finished)
        animation.start(QAbstractAnimation.DeleteWhenStopped)


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
        self._recording = False
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        # A stable header: identity and live status stay together while actions
        # remain in the same place at every window size.
        self.header_panel = role(QFrame(), "studioHeader")
        header = QHBoxLayout(self.header_panel)
        header.setContentsMargins(10, 4, 0, 4)
        header.setSpacing(12)
        brand_mark = role(QLabel("A"), "brandMark")
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(42, 42)
        header.addWidget(brand_mark)

        heading = role(QLabel("Lecture studio"), "studioTitle")
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title_column.addWidget(heading)
        self.operation_status = AnimatedStatusLabel(
            "Ready · Choose a source and start recording"
        )
        self.operation_status.setWordWrap(True)
        role(self.operation_status, "studioStatus")
        title_column.addWidget(self.operation_status)
        header.addLayout(title_column, 1)
        header.addStretch()
        self.study_status_btn = QPushButton()
        self.study_status_btn.setObjectName("studioUtilityButton")
        self.study_status_btn.setToolTip("Open your study timer")
        self.study_status_btn.clicked.connect(lambda: self._switch_tab(5))
        self.study_status_btn.hide()
        header.addWidget(self.study_status_btn)
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
        recording_bar.setContentsMargins(16, 10, 12, 10)
        recording_bar.setSpacing(10)

        class_field = QWidget()
        class_field.setMinimumWidth(170)
        class_field.setMaximumWidth(520)
        class_column = QVBoxLayout(class_field)
        class_column.setContentsMargins(0, 0, 0, 0)
        class_column.setSpacing(4)
        class_column.addWidget(label("CLASS", "fieldLabel"))
        self.class_picker = ResponsiveComboBox()
        self.class_picker.setMinimumWidth(150)
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
        source_column.addWidget(label("AUDIO SOURCE", "fieldLabel"))
        self.audio_source_picker = ResponsiveComboBox()
        self.audio_source_picker.setMinimumWidth(120)
        self.audio_source_picker.setAccessibleName("Audio source")
        from annie.platform_support import audio_sources
        for title, value in audio_sources():
            self.audio_source_picker.addItem(title, value)
        source_column.addWidget(self.audio_source_picker)
        recording_bar.addWidget(source_field, 3)
        recording_bar.addStretch(1)

        self.signal_widget = EliteAudioWaveform()
        self.signal_widget.setFixedWidth(72)
        recording_bar.addWidget(self.signal_widget)
        self.record_btn = QPushButton("Start recording")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.setProperty("state", "idle")
        self.record_btn.setFixedHeight(42)
        self.record_btn.setMinimumWidth(142)
        self.record_btn.clicked.connect(self._toggle_recording)
        recording_bar.addWidget(self.record_btn)
        layout.addWidget(self.recording_panel)

        self.navigation = role(QFrame(), "navigation")
        nav_bar = QBoxLayout(QBoxLayout.TopToBottom, self.navigation)
        nav_bar.setContentsMargins(8, 10, 8, 8)
        self.nav_layout = nav_bar
        nav_bar.setSpacing(5)
        self.nav_caption = label("WORKSPACE", "navCaption")
        nav_bar.addWidget(self.nav_caption)
        for index, (attr, title) in enumerate((("tab_notes_btn", "Notes"),
                ("tab_transcript_btn", "Transcript"), ("tab_flashcards_btn", "Flashcards"),
                ("tab_chat_btn", "Assistant"), ("tab_schedule_btn", "Schedule"),
                ("tab_study_btn", "Study"), ("tab_gpa_btn", "GPA"),
                ("tab_habits_btn", "Habits"))):
            button = self._create_tab_btn(title, index == 0)
            button.clicked.connect(lambda checked=False, i=index: self._switch_tab(i))
            setattr(self, attr, button)
            nav_bar.addWidget(button)
        nav_bar.addStretch()
        nav_bar.addWidget(self.updates_panel.check_button)
        self.tools_btn = QPushButton("More")
        menu = QMenu(self.tools_btn)
        from annie.prayer_startup import launch as launch_prayer_widget
        menu.addAction("Prayer times widget · Намаз", launch_prayer_widget)
        menu.addSeparator()
        menu.addAction("Open saved recordings", lambda: self._open_profile_folder('recordings'))
        menu.addAction("Open study materials", lambda: self._open_profile_folder('library'))
        menu.addAction("Accounts & Setup…", self._open_studio_setup)
        menu.addAction("Moodle calendar…", self._open_moodle_setup)
        menu.addAction("Deadline Inbox…", self._open_deadline_inbox)
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
        self.stack = SmoothStackedWidget()

        # Tab 0: Note Fusion Workspace (Granola / Humla Style)
        self.stack.addWidget(self._build_notes_fusion_tab())

        # Tab 1: Live Speech Transcript
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setPlaceholderText("Listen now. Revisit every detail later.\n\nStart recording or import audio from the More menu. Your transcript will appear here.")
        self.stack.addWidget(self.transcript_area)

        # Tab 2: Anki Flashcards
        self.flashcards_area = QTextEdit()
        self.flashcards_area.setReadOnly(True)
        self.flashcards_area.setPlaceholderText("Turn understanding into recall.\n\nCapture a lecture first, then choose Make flashcards to create your review material.")
        self.stack.addWidget(self.flashcards_area)

        # Tab 3: Study Chat
        self.stack.addWidget(self._build_chat_tab())

        # Tab 4: Weekly Timetable
        self.timetable_view = EliteTimetableView()
        self.timetable_view.select_class.connect(self._on_timetable_class_selected)
        self.stack.addWidget(self.timetable_view)

        from annie.gui.study_timer import StudyTimerPage
        self.study_page = StudyTimerPage(self)
        self.stack.addWidget(self.study_page)
        self.timetable_view.set_study_store(self.study_page.store)
        self.study_page.sessions_changed.connect(self.timetable_view.reload_local_sessions)
        self.study_page.timer_changed.connect(self._update_study_status)
        self.study_page._tick()

        from annie.gui.gpa_tracker import GpaTrackerPage
        self.gpa_page = GpaTrackerPage(self)
        self.stack.addWidget(self.gpa_page)

        from annie.gui.habit_tracker import HabitTrackerPage
        self.habits_page = HabitTrackerPage(self)
        self.stack.addWidget(self.habits_page)

        self.workspace_body = QBoxLayout(QBoxLayout.LeftToRight)
        self.workspace_body.setSpacing(12)
        self.workspace_body.addWidget(self.navigation)
        self.workspace_body.addWidget(self.stack, 1)
        layout.addLayout(self.workspace_body, 1)

        # ── 4. Bottom Clean Action Bar ───────────────────────
        self.bottom_panel = role(QFrame(), "studioFooter")
        bottom_bar = QHBoxLayout(self.bottom_panel)
        bottom_bar.setContentsMargins(10, 8, 8, 8)
        bottom_bar.setSpacing(8)

        # Quick context input
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Course or topic…")
        self.subject_input.setObjectName("courseContextInput")
        bottom_bar.addWidget(self.subject_input, 1)

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
        self.export_btn = QPushButton("Export notes ▾")
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
        bottom_bar.addWidget(self.export_btn)

        layout.addWidget(self.bottom_panel)

        self.worker = None
        self._last_notes = ""
        self._load_classes()
        role(self.operation_status, "studioStatus")
        role(self.fuse_btn, "primary")
        apply_theme(self)
        self._shortcuts = []
        for index in range(8):
            self._shortcuts.append(QShortcut(f"Ctrl+{index + 1}", self,
                activated=lambda i=index: self._switch_tab(i)))
        self._shortcuts.append(QShortcut("Ctrl+Return", self, activated=self._fuse_notes))
        self._switch_tab(0)

    def _create_tab_btn(self, text: str, active: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        self._style_tab_btn(btn, active)
        return btn

    def _style_tab_btn(self, btn: QPushButton, active: bool):
        role(btn, "nav")
        btn.setCheckable(True)
        btn.setChecked(active)
        btn.setStyleSheet(STYLE)

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
        self.pin_btn.setStyleSheet("color: #C5ED87;" if self._is_pinned else "")

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndexAnimated(index)
        self._style_tab_btn(self.tab_notes_btn, index == 0)
        self._style_tab_btn(self.tab_transcript_btn, index == 1)
        self._style_tab_btn(self.tab_flashcards_btn, index == 2)
        self._style_tab_btn(self.tab_chat_btn, index == 3)
        self._style_tab_btn(self.tab_schedule_btn, index == 4)
        self._style_tab_btn(self.tab_study_btn, index == 5)
        self._style_tab_btn(self.tab_gpa_btn, index == 6)
        self._style_tab_btn(self.tab_habits_btn, index == 7)
        self.recording_panel.setVisible(index not in (5, 6, 7))
        self.bottom_panel.setVisible(index not in (5, 6, 7))
        if index == 7:
            self.habits_page.reload()
        self.gen_anki_btn.setVisible(index in (0, 1, 2))
        self.export_btn.setVisible(index in (0, 1, 2))
        if index == 4:
            self.timetable_view._refresh()

    def _update_study_status(self, text):
        self.study_status_btn.setText(text)
        self.study_status_btn.setVisible(bool(text))

    def _open_moodle_setup(self):
        from annie.gui.moodle_setup import MoodleSetup
        MoodleSetup(self).exec_()

    def _open_deadline_inbox(self):
        from annie.gui.deadline_inbox import DeadlineInbox
        DeadlineInbox(self).exec_()

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

    def _build_chat_tab(self) -> QWidget:
        box = QWidget()
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

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

        send_btn = QPushButton("Send")
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
        self._note_hints = []
        self.notes_splitter = QSplitter(Qt.Horizontal)
        self.notes_splitter.setChildrenCollapsible(False)
        self.notes_splitter.setHandleWidth(5)
        for index, (title, hint) in enumerate((
            ("Your highlights", "Capture what matters while you listen."),
            ("Study notes", "Your lecture, organized for revision."))):
            panel = QFrame()
            panel.setObjectName("notesPanel")
            panel.setStyleSheet(f"QFrame#notesPanel {{background: white; border: 1px solid {BORDER_COLOR}; border-radius: 12px;}} QLabel {{border: none; background: transparent;}}")
            column = QVBoxLayout(panel)
            column.setContentsMargins(16, 16, 16, 16)
            label = role(QLabel(title), "section")
            label.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {TEXT_MAIN};")
            column.addWidget(label)
            description = role(QLabel(hint), "muted")
            self._note_hints.append(description)
            description.setWordWrap(True)
            description.setStyleSheet(f"font-size: 12px; color: {TEXT_SUB};")
            column.addWidget(description)
            editor = role(QTextEdit(), "paper")
            editor.setMinimumSize(100, 60)
            editor.setStyleSheet(f"QTextEdit {{background: white; color: {TEXT_MAIN}; border: none; padding: 4px; font-size: 14px; selection-background-color: #A7F3D0;}}")
            column.addWidget(editor, 1)
            if index == 0:
                self.user_scratchpad = editor
                editor.setAccessibleName("Your lecture highlights")
                editor.setPlaceholderText("Add a key idea, a question, or a reminder…\n\n• Concepts to revisit\n• Examples from class\n• Upcoming deadlines")
                self.fuse_btn = QPushButton("Create study notes")
                self.fuse_btn.clicked.connect(self._fuse_notes)
                self.fuse_btn.setToolTip("Combine your highlights with the lecture transcript")
                column.addWidget(self.fuse_btn)
            else:
                self.notes_area = editor
                editor.setReadOnly(True)
                editor.setAccessibleName("Generated study notes")
                editor.setPlaceholderText("A clearer view of your lecture starts here.\n\nRecord a lecture or add your highlights, then create study notes.")
            self.notes_splitter.addWidget(panel)
        self.notes_splitter.setSizes([380, 620])
        return self.notes_splitter

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "notes_splitter"):
            for hint in self._note_hints:
                hint.setVisible(self.height() >= 620)
            compact = self.width() < 900
            self.workspace_body.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
            self.nav_layout.setDirection(QBoxLayout.LeftToRight if compact else QBoxLayout.TopToBottom)
            self.nav_caption.setVisible(not compact)
            self.navigation.setFixedWidth(self.width() - 44 if compact else 172)
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
        self._fusion_thread.finished.connect(self._on_fusion_finished)
        self._fusion_thread.error.connect(self._on_fusion_error)
        self._start_job(self._fusion_thread)

    def _on_fusion_finished(self, notes_text: str):
        self.fuse_btn.setEnabled(True)
        self.fuse_btn.setText("Create study notes")
        self._last_notes = notes_text.strip()
        self.notes_area.setPlainText(self._last_notes)

    def _on_fusion_error(self, err: str):
        self.fuse_btn.setEnabled(True)
        self.fuse_btn.setText("Create study notes")
        self.notes_area.setPlainText(f"⚠️ Note Fusion Error: {err}")

    def _toggle_recording(self):
        if self._recording:
            # Stop
            self.record_btn.setText("Creating notes…")
            self.record_btn.setEnabled(False)
            self._set_record_button_state("busy")
            self.worker.user_notes = self.user_scratchpad.toPlainText().strip()
            self.worker.stop()
            self._recording = False
            self.signal_widget.set_active(False)
            self.meeting_state_changed.emit(False)
        else:
            if self.worker and self.worker.isRunning():
                return
            # Start
            self._last_transcript = ""
            self.transcript_area.clear()
            self.notes_area.clear()
            self.flashcards_area.clear()

            self.record_btn.setText("Stop recording")
            self._set_record_button_state("recording")
            self.signal_widget.set_active(True)

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
            if hasattr(self.worker, 'audio_level'):
                self.worker.audio_level.connect(self.signal_widget.update_audio_level)
            if hasattr(self.worker, 'capture_finished'):
                self.worker.capture_finished.connect(self._on_capture_finished)
                self.worker.backlog_updated.connect(self._on_backlog)
                self.worker.recording_saved.connect(self._on_recording_saved)
            self._recording = True
            self.meeting_state_changed.emit(True)
            self._start_job(self.worker)

    def _import_audio(self):
        if self.worker and self.worker.isRunning():
            self.operation_status.setText("Finish the current recording or import first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "", "Audio & Video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.webm *.mp4);;All Files (*)"
        )
        if not file_path:
            return

        self.transcript_area.clear()
        self._last_transcript = ""
        self.notes_area.clear()
        self.flashcards_area.clear()

        subj = self.subject_input.text().strip()
        user_notes = self.user_scratchpad.toPlainText().strip()
        from annie.meeting import AudioFileMeetingWorker
        from annie.config import WHISPER_MODEL
        self.worker = AudioFileMeetingWorker(file_path=file_path, model_name=WHISPER_MODEL, subject_context=subj, user_notes=user_notes)
        self.worker.transcript_updated.connect(self._on_transcript)
        self.worker.summary_ready.connect(self._on_summary)
        self.worker.status_changed.connect(self._on_worker_status)
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
        self._slide_thread.finished.connect(self._on_slide_finished)
        self._slide_thread.error.connect(self._on_slide_error)
        self._start_job(self._slide_thread)

    def _on_slide_finished(self, p, text):
        block = f"\n\n📸 **SLIDE / WHITEBOARD ANALYSIS ({os.path.basename(p)}):**\n{text}\n"
        self.transcript_area.append(block)
        self.notes_area.append(block)
        self.operation_status.setText("Slide analysis added to the transcript and notes.")
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
        self._prep_thread.finished.connect(self._on_prep_guide_finished)
        self._prep_thread.error.connect(self._on_prep_guide_error)
        self._start_job(self._prep_thread)

    def _on_prep_guide_finished(self, guide):
        self._last_notes = guide.strip()
        self.notes_area.setPlainText(self._last_notes)
        self.operation_status.setText("Exam preparation guide ready.")
        self._switch_tab(0)

    def _on_prep_guide_error(self, err):
        self.operation_status.setText(f"Prep guide failed: {err}")
        QMessageBox.warning(self, "Prep guide failed", err)

    def _on_transcript(self, text: str):
        cursor = self.transcript_area.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.transcript_area.setTextCursor(cursor)
        self._last_transcript = self.transcript_area.toPlainText()

    def _on_summary(self, summary_text: str):
        self.record_btn.setText("Start recording")
        self.record_btn.setEnabled(True)
        self._set_record_button_state("idle")
        self._last_notes = summary_text.strip()
        self.notes_area.setPlainText(self._last_notes)
        self._switch_tab(0)

    def _generate_anki(self):
        text = self._last_notes or self.notes_area.toPlainText() or self.transcript_area.toPlainText()
        if not text:
            QMessageBox.information(self, "No Content", "Record or import a lecture first.")
            return

        self.gen_anki_btn.setEnabled(False)
        self.gen_anki_btn.setText("Generating...")

        user_notes = self.user_scratchpad.toPlainText().strip()
        self._anki_thread = AnkiGenThread(text, self.subject_input.text().strip(), user_notes=user_notes)
        self._anki_thread.finished.connect(self._on_anki_finished)
        self._anki_thread.error.connect(self._on_anki_error)
        self._start_job(self._anki_thread)

    def _on_anki_finished(self, deck):
        self.gen_anki_btn.setEnabled(True)
        self.gen_anki_btn.setText("Make flashcards")
        self.flashcards_area.setPlainText(deck)
        self._switch_tab(2)

    def _on_anki_error(self, err):
        self.gen_anki_btn.setEnabled(True)
        self.gen_anki_btn.setText("Make flashcards")
        self.flashcards_area.setPlainText(f"⚠️ Error generating flashcards: {err}")
        self._switch_tab(2)

    def _send_chat(self):
        q = self.chat_input.text().strip()
        if not q:
            return
        self.chat_input.clear()
        self.chat_history.append(f"\n👤 **You:** {q}\n")

        self._chat_thread = StudyChatThread(q)
        self._chat_thread.finished.connect(self._on_chat_finished)
        self._chat_thread.error.connect(lambda err: self.chat_history.append(f"⚠️ Error: {err}\n"))
        self._start_job(self._chat_thread)

    def _on_chat_finished(self, reply):
        self.chat_history.append(f"🤖 **Annie:**\n{reply}\n" + "─"*40)

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
        a_copy = menu.addAction("📋 Copy Notes to Clipboard")
        a_obsidian = menu.addAction("💾 Save as Obsidian Markdown (.md)")
        a_pdf = menu.addAction("🌐 Export HTML / Print to PDF")
        a_txt = menu.addAction("📄 Save Raw Transcript (.txt)")

        action = menu.exec_(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))
        if action == a_copy:
            self._copy_notes()
        elif action == a_obsidian:
            self._save_obsidian()
        elif action == a_pdf:
            self._export_pdf()
        elif action == a_txt:
            self._save_txt()

    def _copy_notes(self):
        text = self._last_notes or self.notes_area.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.export_btn.setText("✓ Copied!")
            QTimer.singleShot(2000, lambda: self.export_btn.setText("Export notes ▾"))

    def _save_obsidian(self):
        text = self._last_notes or self.notes_area.toPlainText()
        if not text:
            return
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        subj = self.subject_input.text().strip() or "Lecture"
        frontmatter = f"---\ntags:\n  - university\n  - lecture\n  - {subj.replace(' ', '_').lower()}\ndate: {date_str}\n---\n\n"
        path, _ = QFileDialog.getSaveFileName(self, "Save Obsidian Note", f"{subj.replace(' ', '_')}_{date_str}.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(frontmatter + text)

    def _export_pdf(self):
        text = self._last_notes or self.notes_area.toPlainText()
        if not text:
            return
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        subj = self.subject_input.text().strip() or "Lecture Notes"
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subj}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1B1E19; color: #F1F3E9; padding: 40px 60px; line-height: 1.6; max-width: 860px; margin: auto; }}
  h1 {{ font-size: 26px; color: #F1F3E9; border-bottom: 2px solid #C5ED87; padding-bottom: 8px; }}
  h3 {{ font-size: 16px; color: #D9FFA5; margin-top: 20px; }}
</style></head>
<body><h1>{subj} ({date_str})</h1><pre style="font-family:inherit; white-space:pre-wrap;">{text}</pre></body></html>"""
        path, _ = QFileDialog.getSaveFileName(self, "Export HTML / PDF", f"{subj.replace(' ', '_')}_{date_str}.html", "HTML (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            webbrowser.open(path)

    def _save_txt(self):
        text = self.transcript_area.toPlainText()
        if text:
            path, _ = QFileDialog.getSaveFileName(self, "Save Transcript", "transcript.txt", "Text (*.txt)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)

    def is_active(self) -> bool:
        return self._recording

    def _on_worker_status(self, status):
        self.operation_status.setText(status)

    def _on_capture_finished(self):
        if self._recording:
            self._recording = False
            self.meeting_state_changed.emit(False)
        self.signal_widget.set_active(False)
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Finishing notes...")
        self._set_record_button_state("busy")

    def _on_backlog(self, seconds):
        if seconds >= 2:
            action = "Recording" if self._recording else "Finishing transcript"
            self.operation_status.setText(f"{action} · {seconds:.0f}s of audio pending")

    def _on_recording_saved(self, path):
        self._last_recording_path = path
        self.operation_status.setToolTip(f"Audio recording: {path}")

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
                    self.record_btn.setEnabled(True)
                    self.record_btn.setText("Start recording")
                    self._set_record_button_state("idle")
                    self.signal_widget.set_active(False)
                    if self._recording:
                        self._recording = False
                        self.meeting_state_changed.emit(False)
        if not self._jobs:
            self._job_timer.stop()

    def has_running_jobs(self):
        return (any(job.isRunning() for job in self._jobs) or
                self.updates_panel.service.is_running() or
                self.updates_panel.downloads.is_running() or
                self.timetable_view.has_running_job() or self.study_page.has_running_job())

    def stop_jobs(self):
        self.updates_panel.service.stop()
        self.updates_panel.downloads.cancel()
        if self.updates_panel.dialog is not None:
            self.updates_panel.dialog.close()
        self.study_page.stop_background()
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
        self.stop_jobs()
        if sys.platform == 'darwin' and not self.testAttribute(Qt.WA_DontShowOnScreen):
            from annie.macos_support import set_accessory_mode
            set_accessory_mode()
        # Keep worker references alive while an in-flight model request ends.
        # The cached window can be reopened after closing its visible surface.
        super().closeEvent(event)
