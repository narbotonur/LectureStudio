"""Conference/lecture detection and a one-click transcription prompt."""
from dataclasses import dataclass
import datetime
import json
from pathlib import Path
import re
import sys
import time

from PyQt5.QtCore import (
    QAbstractAnimation, QEasingCurve, QObject, QParallelAnimationGroup,
    QPropertyAnimation, QRect, Qt, QThread, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QLayout, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from annie import config as cfg


_monitor_mutex = None


def _acquire_monitor_mutex():
    """Allow only one watcher: Windows session mutex or per-profile Qt lock."""
    global _monitor_mutex
    if _monitor_mutex is not None:
        return False
    if sys.platform != 'win32':
        from PyQt5.QtCore import QLockFile
        lock = QLockFile(str(Path(cfg.DATA_DIR) / 'lecture-watcher.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            return False
        _monitor_mutex = lock
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, 'Local\\AnnieLectureWatcher')
        if not handle:
            return False
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _monitor_mutex = handle
        return True
    except Exception:
        return False  # Never start a second watcher if locking fails.


def _release_monitor_mutex():
    global _monitor_mutex
    handle = _monitor_mutex
    _monitor_mutex = None
    if not handle or handle is True:
        return
    if hasattr(handle, 'unlock'):
        handle.unlock()
        return
    try:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass


@dataclass(frozen=True)
class ConferenceWindow:
    provider: str
    title: str
    process_name: str
    pid: int = 0

    @property
    def signature(self):
        stable_title = re.sub(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', '', self.title.lower())
        return f'{self.provider}:{self.pid}:{stable_title.strip()}'


def _canonical_process_name(name):
    name = (name or '').strip().lower()
    return {'zoom.us': 'zoom.exe', 'zoom': 'zoom.exe',
            'microsoft teams': 'ms-teams.exe', 'microsoft teams (work or school)': 'ms-teams.exe',
            'msteams': 'ms-teams.exe', 'google chrome': 'chrome.exe', 'microsoft edge': 'msedge.exe',
            'brave browser': 'brave.exe', 'firefox': 'firefox.exe',
            'safari': 'safari.exe'}.get(name, name)


def detect_conference_window(windows=None, active_audio_processes=None):
    """Detect a likely active Zoom, Teams, or Google Meet conference window."""
    live_scan = windows is None
    windows = list(windows) if windows is not None else _visible_windows()
    if not windows:
        return None
    if active_audio_processes is None:
        active_audio_processes = _active_audio_processes() if live_scan else set()
    active_audio_processes = {_canonical_process_name(name) for name in active_audio_processes}
    for title, process_name, pid in windows:
        low_title = (title or '').strip().lower()
        process = _canonical_process_name(process_name)
        if not low_title:
            continue

        if ('zoom meeting' in low_title or 'zoom webinar' in low_title or
                (process == 'zoom.exe' and any(word in low_title for word in ('meeting', 'webinar')))):
            return ConferenceWindow('Zoom', title, process_name, pid)

        if process in ('ms-teams.exe', 'teams.exe'):
            generic = (
                'microsoft teams', 'chat | microsoft teams', 'activity | microsoft teams',
                'calendar | microsoft teams', 'teams | microsoft teams',
            )
            meeting_words = ('meeting', 'call', 'webinar', 'собрани', 'звон')
            course_words = ('lecture', 'class', 'seminar', 'tutorial', 'lab', 'лекц', 'занят')
            course_title = (bool(re.search(r'\b[a-z]{2,}\s*[- ]?\d{2,4}\b', low_title)) or
                            any(word in low_title for word in course_words))
            definite_meeting = any(word in low_title for word in meeting_words)
            has_active_audio = process in active_audio_processes
            if (low_title not in generic and
                    (definite_meeting or (course_title and has_active_audio))):
                return ConferenceWindow('Microsoft Teams', title, process_name, pid)

        browser = process in ('chrome.exe', 'msedge.exe', 'brave.exe', 'firefox.exe', 'safari.exe')
        if browser and ('google meet' in low_title or 'meet.google.com' in low_title or
                        re.search(r'\bmeet\s*[-–]\s*[a-z]{3}-[a-z]{4}-[a-z]{3}\b', low_title)):
            return ConferenceWindow('Google Meet', title, process_name, pid)
    return None


def _visible_windows():
    if sys.platform == 'darwin':
        from annie.macos_support import visible_windows
        return visible_windows()
    if not hasattr(__import__('sys'), 'getwindowsversion'):
        return []
    try:
        import psutil
        import win32gui
        import win32process
    except Exception:
        return []

    result = []

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process_name = psutil.Process(pid).name()
        except Exception:
            return
        result.append((title, process_name, pid))

    win32gui.EnumWindows(collect, None)
    return result


class AudioSourceButton(QWidget):
    """A compact split button: start on the left, audio source on the arrow."""
    clicked = pyqtSignal()
    source_changed = pyqtSignal(str, str)

    OPTIONS = (
        ('Mic + system', 'dual'),
        ('System audio', 'system'),
        ('Microphone', 'default'),
        ('Wireless mic', 'phone'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        if sys.platform == 'darwin':
            from annie.platform_support import audio_sources
            self.OPTIONS = audio_sources()
        self._current_index = 0
        self.setFixedSize(184, 38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.primary_button = QPushButton('Start transcribing')
        self.primary_button.setObjectName('startPrimary')
        self.primary_button.setFixedSize(150, 38)
        self.primary_button.clicked.connect(self.clicked.emit)
        layout.addWidget(self.primary_button)

        self.menu_button = QToolButton()
        self.menu_button.setObjectName('startMenu')
        self.menu_button.setText('⌄')
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        self.menu_button.setFixedSize(34, 38)
        layout.addWidget(self.menu_button)

        self.setStyleSheet('''
            QPushButton#startPrimary {
                background: #BDEC78; color: #17200F; border: none;
                border-top-left-radius: 19px; border-bottom-left-radius: 19px;
                padding: 8px 8px 8px 14px; font-size: 12px; font-weight: 700;
                text-align: center;
            }
            QPushButton#startPrimary:hover, QToolButton#startMenu:hover {
                background: #CEF991;
            }
            QPushButton#startPrimary:pressed, QToolButton#startMenu:pressed {
                background: #AEDB68;
            }
            QToolButton#startMenu {
                background: #BDEC78; color: #27351B; border: none;
                border-left: 1px solid rgba(23, 32, 15, 55);
                border-top-right-radius: 19px; border-bottom-right-radius: 19px;
                padding: 0px 3px 5px 0px; font-size: 15px; font-weight: 700;
            }
            QToolButton#startMenu::menu-indicator { image: none; }
        ''')
        menu = QMenu(self)
        menu.setObjectName('sourceMenu')
        menu.setStyleSheet('''
            QMenu#sourceMenu {
                background: #1D211B;
                color: #E9EEE4;
                border: 1px solid #424A3B;
                padding: 7px;
                font-size: 12px;
            }
            QMenu#sourceMenu::item {
                min-width: 166px;
                padding: 9px 28px 9px 12px;
                border-radius: 7px;
            }
            QMenu#sourceMenu::item:selected {
                background: #31382C;
                color: #FFFFFF;
            }
            QMenu#sourceMenu::item:checked {
                color: #C5ED87;
                font-weight: 600;
            }
            QMenu#sourceMenu::indicator { width: 0px; height: 0px; }
        ''')
        self._actions = []
        for index, (title, value) in enumerate(self.OPTIONS):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, i=index: self.setCurrentIndex(i))
            self._actions.append(action)
        self.menu_button.setMenu(menu)
        self._sync_selection()

    def findData(self, value):
        for index, (_, option_value) in enumerate(self.OPTIONS):
            if option_value == value:
                return index
        return -1

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self.OPTIONS):
            return
        self._current_index = index
        self._sync_selection()
        title, value = self.OPTIONS[index]
        self.source_changed.emit(title, value)

    def currentData(self):
        return self.OPTIONS[self._current_index][1]

    def currentText(self):
        return self.OPTIONS[self._current_index][0]

    def _sync_selection(self):
        for index, action in enumerate(self._actions):
            action.setChecked(index == self._current_index)
        self.setToolTip(f'Audio source: {self.currentText()}')
        self.primary_button.setToolTip(f'Audio source: {self.currentText()}')


def _active_audio_processes():
    """Return processes with active Windows audio sessions."""
    if sys.platform == 'darwin':
        from annie.macos_support import active_audio_processes
        return active_audio_processes()
    if sys.platform != 'win32':
        return set()
    try:
        import psutil
        from pycaw.pycaw import AudioUtilities
    except Exception:
        return set()
    result = set()
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return result
    for session in sessions:
        process = getattr(session, 'Process', None)
        if not process or getattr(session, 'State', 0) != 1:
            continue
        try:
            result.add(process.name().lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


class MeetingPrompt(QDialog):
    start_requested = pyqtSignal(str)
    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(620, 96)
        self._final_size = (620, 96)
        self._animation = None
        self._target_geometry = QRect()
        self._closing = False
        self._base_subtitle = ''
        self._show_action = True

        shell = QFrame(self)
        shell.setObjectName('promptShell')
        shell.setStyleSheet('''
            QFrame#promptShell {
                background: #181B17;
                border: 1px solid #3C4436;
                border-radius: 27px;
            }
            QLabel { color: #F1F3E9; background: transparent; }
            QPushButton#closeButton {
                background: transparent; color: #ADB6A4; border: none;
                border-radius: 12px; font-size: 15px; padding: 3px;
            }
            QPushButton#closeButton:hover { background: #2B3028; color: white; }
        ''')
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(0, 0, 0, 155))
        shell.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 10)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        outer.addWidget(shell)
        row = QHBoxLayout(shell)
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(11)

        icon = QLabel('A')
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(40, 40)
        icon.setStyleSheet(
            'background:#252B21; border:1px solid #59664D; border-radius:20px; '
            'font-size:18px; font-weight:800; color:#C5ED87;'
        )
        row.addWidget(icon)

        self.label_panel = QWidget()
        self.label_panel.setFixedWidth(252)
        labels = QVBoxLayout(self.label_panel)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(2)
        self.title_label = QLabel('Start AI Meeting Note')
        self.title_label.setStyleSheet('font-size:13px; font-weight:700; color:#FFFFFF;')
        self.subtitle_label = QLabel('Annie detected a meeting')
        self.subtitle_label.setStyleSheet('font-size:10px; color:#AEB8A5;')
        labels.addWidget(self.title_label)
        labels.addWidget(self.subtitle_label)
        row.addWidget(self.label_panel)

        self.start_button = AudioSourceButton()
        self.source_picker = self.start_button
        self.source_picker.source_changed.connect(self._on_source_changed)
        self.start_button.clicked.connect(
            lambda: self.start_requested.emit(self.source_picker.currentData())
        )
        row.addWidget(self.start_button)
        close_button = QPushButton('×')
        close_button.setObjectName('closeButton')
        close_button.setFixedSize(26, 26)
        close_button.clicked.connect(self.dismissed.emit)
        row.addWidget(close_button)
        self.close_button = close_button

    def _on_source_changed(self, title, _value):
        if self._base_subtitle:
            subtitle = self._base_subtitle
            if self._show_action:
                subtitle = f'{subtitle}  ·  {title}'
            self.subtitle_label.setText(subtitle)

    def _stop_animation(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None

    def _animate(self, start_rect, end_rect, start_opacity, end_opacity,
                 duration, easing, finished):
        self._stop_animation()
        self.setGeometry(start_rect)
        self.setWindowOpacity(start_opacity)

        motion = QPropertyAnimation(self, b'geometry')
        motion.setDuration(duration)
        motion.setStartValue(start_rect)
        motion.setEndValue(end_rect)
        motion.setEasingCurve(easing)

        fade = QPropertyAnimation(self, b'windowOpacity')
        fade.setDuration(max(140, int(duration * 0.72)))
        fade.setStartValue(start_opacity)
        fade.setEndValue(end_opacity)
        fade.setEasingCurve(QEasingCurve.OutCubic if end_opacity > start_opacity
                            else QEasingCurve.InCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(motion)
        group.addAnimation(fade)
        group.finished.connect(finished)
        group.finished.connect(group.deleteLater)
        self._animation = group
        group.start(QAbstractAnimation.KeepWhenStopped)

    def present(self, title, subtitle, default_source='dual', show_action=True):
        self._closing = False
        self._show_action = show_action
        self._final_size = (620, 96) if show_action else (500, 96)
        self.start_button.setVisible(show_action)
        self.start_button.setEnabled(show_action)
        self.source_picker.setEnabled(show_action)
        self.label_panel.setFixedWidth(252 if show_action else 340)
        self.close_button.setEnabled(True)
        self.title_label.setText(title)
        self._base_subtitle = subtitle
        index = self.source_picker.findData(default_source)
        self.source_picker.setCurrentIndex(max(0, index))
        self._on_source_changed(self.source_picker.currentText(), self.source_picker.currentData())
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            final_width, final_height = self._final_size
            center_x = area.center().x()
            self._target_geometry = QRect(
                center_x - final_width // 2, area.top() + 28,
                final_width, final_height,
            )
            compact_width, compact_height = 400, 56
            start_rect = QRect(
                center_x - compact_width // 2,
                area.top() - compact_height + 12,
                compact_width,
                compact_height,
            )
        else:
            self._target_geometry = QRect(0, 28, *self._final_size)
            start_rect = QRect(110, -44, 400, 56)
        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._animate(
            start_rect,
            self._target_geometry,
            0.0,
            1.0,
            480,
            QEasingCurve.OutBack,
            self._finish_present,
        )

    def _finish_present(self):
        self.setGeometry(self._target_geometry)
        self.setWindowOpacity(1.0)
        self._animation = None

    def dismiss_animated(self, after=None):
        if not self.isVisible():
            if after:
                after()
            return
        if self._closing:
            return
        self._closing = True
        self.start_button.setEnabled(False)
        self.source_picker.setEnabled(False)
        self.close_button.setEnabled(False)
        start_rect = self.geometry()
        compact_width, compact_height = 350, 48
        end_rect = QRect(
            start_rect.center().x() - compact_width // 2,
            start_rect.y() - 58,
            compact_width,
            compact_height,
        )

        def complete():
            self.hide()
            self.setWindowOpacity(1.0)
            self._closing = False
            self._animation = None
            if after:
                after()

        self._animate(
            start_rect,
            end_rect,
            max(0.0, self.windowOpacity()),
            0.0,
            260,
            QEasingCurve.InCubic,
            complete,
        )

    def hide_immediately(self):
        self._stop_animation()
        self._closing = False
        self.setWindowOpacity(1.0)
        self.hide()


class CalendarScheduleThread(QThread):
    events_ready = pyqtSignal(object)

    def __init__(self, target_date, parent=None):
        super().__init__(parent)
        self.target_date = target_date

    def run(self):
        try:
            from annie.calendar_service import get_daily_lecture_schedule
            self.events_ready.emit(get_daily_lecture_schedule(self.target_date))
        except Exception:
            self.events_ready.emit([])


class ConferenceScanThread(QThread):
    result = pyqtSignal(object)

    def run(self):
        try:
            self.result.emit(detect_conference_window())
        except Exception:
            self.result.emit(None)


class MeetingPromptController(QObject):
    """Own detection timers and route a prompt action to Lecture Studio."""

    def __init__(self, parent, start_transcription, is_recording=None):
        super().__init__(parent)
        self.start_transcription = start_transcription
        self.is_recording = is_recording or (lambda: False)
        # Keep the prompt unowned so it can appear above Teams/Zoom even when
        # Annie's main window is minimized.
        self.prompt = MeetingPrompt()
        self.prompt.start_requested.connect(self._start)
        self.prompt.dismissed.connect(self._dismiss)
        self._conference_timer = QTimer(self)
        self._conference_timer.timeout.connect(self._check_conference)
        self._calendar_timer = QTimer(self)
        self._calendar_timer.timeout.connect(self._check_cached_schedule)
        self._calendar_refresh_timer = QTimer(self)
        self._calendar_refresh_timer.setSingleShot(True)
        self._calendar_refresh_timer.timeout.connect(self._refresh_calendar)
        self._calendar_worker = None
        self._conference_worker = None
        self._scan_epoch = 0
        self._schedule_events = []
        self._schedule_day = ''
        self._schedule_notified = set()
        self._schedule_cache_path = Path(cfg.DATA_DIR) / 'lecture_schedule_cache.json'
        self._notified = {}
        self._active_signature = ''
        self._active_context = ''
        self._started = False

    def start(self):
        if self._started or not cfg.MEETING_PROMPTS_ENABLED:
            return False
        if not _acquire_monitor_mutex():
            return False
        self._started = True
        self._conference_timer.start(3000)
        self._calendar_timer.start(30000)
        QTimer.singleShot(1500, self._check_conference)
        if self._load_schedule_cache():
            QTimer.singleShot(2500, self._check_cached_schedule)
        else:
            QTimer.singleShot(2500, self._refresh_calendar)
        self._schedule_next_calendar_refresh()
        return True

    def stop(self):
        self._scan_epoch += 1
        self._conference_timer.stop()
        self._calendar_timer.stop()
        self._calendar_refresh_timer.stop()
        self.prompt.hide_immediately()
        if self._started:
            self._started = False
            _release_monitor_mutex()

    def has_running_job(self):
        return any(worker is not None and worker.isRunning()
                   for worker in (self._calendar_worker, self._conference_worker))

    def _eligible(self, signature, cooldown=1800):
        return time.monotonic() - self._notified.get(signature, -cooldown) >= cooldown

    def _check_conference(self):
        if not self._started or self.is_recording() or self.prompt.isVisible() or self._conference_worker is not None:
            return
        epoch = self._scan_epoch
        worker = ConferenceScanThread(self)
        self._conference_worker = worker
        worker.result.connect(lambda result: self._conference_result(result, epoch))
        worker.finished.connect(self._conference_finished)
        worker.start()

    def _conference_finished(self):
        worker, self._conference_worker = self._conference_worker, None
        if worker:
            worker.deleteLater()

    def _conference_result(self, conference, epoch):
        if not self._started or epoch != self._scan_epoch or self.is_recording() or self.prompt.isVisible():
            return
        if not conference or not self._eligible(conference.signature):
            return
        self._active_signature = conference.signature
        self._active_context = conference.title
        self._notified[conference.signature] = time.monotonic()
        self.prompt.present(
            'Start AI Meeting Note',
            f'{conference.provider} meeting detected',
            cfg.MEETING_PROMPT_AUDIO_SOURCE,
        )

    @staticmethod
    def _today_key():
        return datetime.datetime.now().astimezone().date().isoformat()

    @staticmethod
    def _event_signature(event):
        start = event.get('start', {}).get('dateTime', '')
        return f"calendar:{event.get('id') or event.get('summary')}:{start}"

    @staticmethod
    def _compact_event(event):
        """Keep only reminder fields in the on-disk daily cache."""
        return {
            'id': event.get('id', ''),
            'summary': event.get('summary', 'Lecture'),
            'start': event.get('start', {}),
            'end': event.get('end', {}),
            'location': event.get('location', ''),
        }

    def _load_schedule_cache(self):
        try:
            data = json.loads(self._schedule_cache_path.read_text(encoding='utf-8'))
            if data.get('date') != self._today_key():
                return False
            events = data.get('events')
            if not isinstance(events, list):
                return False
            self._schedule_day = data['date']
            self._schedule_events = [
                self._compact_event(event)
                for event in events if isinstance(event, dict)
            ]
            self._schedule_notified = set(data.get('notified', []))
            self._save_schedule_cache()
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _save_schedule_cache(self):
        payload = {
            'date': self._schedule_day,
            'events': self._schedule_events,
            'notified': sorted(self._schedule_notified),
        }
        try:
            self._schedule_cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except OSError:
            pass

    def _schedule_next_calendar_refresh(self):
        now = datetime.datetime.now().astimezone()
        tomorrow = now.date() + datetime.timedelta(days=1)
        refresh_at = datetime.datetime.combine(
            tomorrow, datetime.time(0, 0, 5), tzinfo=now.tzinfo,
        )
        delay_ms = max(1000, int((refresh_at - now).total_seconds() * 1000))
        self._calendar_refresh_timer.start(delay_ms)

    def _refresh_calendar(self):
        if self._calendar_worker and self._calendar_worker.isRunning():
            return
        target_date = datetime.datetime.now().astimezone().date()
        self._calendar_worker = CalendarScheduleThread(target_date, self)
        self._calendar_worker.events_ready.connect(self._calendar_schedule_ready)
        self._calendar_worker.finished.connect(self._calendar_finished)
        self._calendar_worker.start()
        self._schedule_next_calendar_refresh()

    def _calendar_finished(self):
        worker = self.sender()
        if worker is self._calendar_worker:
            self._calendar_worker = None
        worker.deleteLater()

    def _calendar_schedule_ready(self, events):
        self._schedule_day = self._today_key()
        self._schedule_events = [
            self._compact_event(event)
            for event in (events or []) if isinstance(event, dict)
        ]
        self._schedule_notified = set()
        self._save_schedule_cache()
        self._check_cached_schedule()

    def _check_cached_schedule(self):
        if self._schedule_day != self._today_key():
            self._refresh_calendar()
            return
        if self.is_recording() or self.prompt.isVisible() or not self._schedule_events:
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        event = None
        signature = ''
        for candidate in self._schedule_events:
            candidate_signature = self._event_signature(candidate)
            if candidate_signature in self._schedule_notified:
                continue
            start_text = candidate.get('start', {}).get('dateTime')
            try:
                start = datetime.datetime.fromisoformat(start_text.replace('Z', '+00:00'))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=datetime.timezone.utc)
                minutes_until = (
                    start.astimezone(datetime.timezone.utc) - now
                ).total_seconds() / 60.0
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 < minutes_until <= 10:
                event = candidate
                signature = candidate_signature
                break
        if event is None:
            return

        title = event.get('summary') or 'Lecture'
        self._active_signature = signature
        self._active_context = title
        self._schedule_notified.add(signature)
        self._save_schedule_cache()
        self.prompt.present(
            'Starts in 10 minutes',
            title,
            cfg.MEETING_PROMPT_AUDIO_SOURCE,
            show_action=False,
        )

    def _start(self, source):
        cfg.MEETING_PROMPT_AUDIO_SOURCE = source
        cfg.save_settings()
        context = self._active_context
        self.prompt.dismiss_animated(
            lambda: self.start_transcription(source, context)
        )

    def _dismiss(self):
        self.prompt.dismiss_animated()


def start_studio_transcription(studio, source, context=''):
    """Show a Lecture Studio window and start recording with one click."""
    if studio.is_active():
        return
    from annie.platform_support import validate_audio_source
    validate_audio_source(source)
    index = studio.audio_source_picker.findData(source)
    if index >= 0:
        studio.audio_source_picker.setCurrentIndex(index)
    context = (context or '').strip()
    if context and not studio.subject_input.text().strip():
        studio.subject_input.setText(context)
    if hasattr(studio, 'isMinimized') and studio.isMinimized():
        studio.showNormal()
    else:
        studio.show()
    studio.raise_()
    studio.activateWindow()
    if not studio.is_active():
        studio._toggle_recording()
