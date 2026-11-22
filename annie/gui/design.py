"""Annie's native desktop visual system and home composition."""
from datetime import datetime
import sys

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QFont, QPalette
from PyQt5.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QTextEdit, QSizePolicy, QShortcut,
)

BACKGROUND = '#171C21'
SURFACE = '#20272D'
RAISED = '#29343B'
BORDER = '#354249'
TEXT = '#F0F4F5'
MUTED = '#B0C0C7'
ACCENT = '#A7E5CB'
ACCENT_HOVER = '#C0F2DC'
SELECTION = '#34564D'
UI_FONT = 'Helvetica Neue' if sys.platform == 'darwin' else 'Segoe UI'
MONO_FONT = 'Menlo' if sys.platform == 'darwin' else 'Consolas'

STYLE = f'''
QWidget {{ color: {TEXT}; font-family: '{UI_FONT}'; font-size: 13px; }}
QWidget#homeContent {{ background: {BACKGROUND}; }}
QDialog, QMainWindow, QWidget#home, QWidget#annieSurface {{ background: {BACKGROUND}; }}
QLabel {{ background: transparent; border: none; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="eyebrow"] {{ color: {ACCENT}; font-size: 10px; font-weight: 600; letter-spacing: 2px; }}
QLabel[role="title"] {{ font-size: 27px; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: 34px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="lectureTitle"] {{ font-size: 23px; font-weight: 650; }}
QLabel[role="studyClock"] {{ color: {ACCENT}; font-family: '{MONO_FONT}'; font-size: 46px; font-weight: 600; padding: 12px 0; }}
QTableWidget {{ background: {SURFACE}; alternate-background-color: {RAISED}; border: 1px solid {BORDER};
    color: {TEXT}; selection-color: {TEXT};
    border-radius: 10px; gridline-color: {BORDER}; selection-background-color: {SELECTION}; }}
QTableWidget::item {{ padding: 6px; }}
QListWidget {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 10px; selection-background-color: {SELECTION}; selection-color: {TEXT}; }}
QListWidget::item {{ padding: 8px; }}
QHeaderView::section {{ background: {RAISED}; color: {MUTED}; border: none; padding: 8px; }}
QFrame[role="panel"], QFrame[role="notesOutput"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[role="notesInput"] {{ background: transparent; }}
QFrame[role="studioHeader"] {{ background: transparent; border: none; }}
QLabel[role="brandMark"] {{ background: #27443B; color: {ACCENT};
    border-radius: 11px; font-size: 18px; font-weight: 650; }}
QLabel[role="studioTitle"] {{ color: {TEXT}; font-size: 20px; font-weight: 650; }}
QLabel[role="studioStatus"], QLabel[role="fieldLabel"] {{ color: {MUTED}; font-size: 12px; }}
QFrame[role="recordingBar"], QFrame[role="transport"] {{ background: {SURFACE}; border-radius: 12px; }}
QFrame[role="studioFooter"] {{ background: transparent; border-top: 1px solid {BORDER}; }}
QFrame[role="lectureNavigation"] {{ background: transparent; border-bottom: 1px solid {BORDER}; }}
QFrame[role="navigation"] {{ background: transparent; }}
QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 8px;
    color: {TEXT}; padding: 7px 12px; font-size: 12px; font-weight: 600; }}
QPushButton:hover {{ background: #34424A; border-color: #51626B; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:pressed {{ background: #3E5159; }}
QPushButton[role="primary"] {{ background: {ACCENT}; color: {BACKGROUND}; border-color: {ACCENT}; }}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="nav"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; text-align: left; }}
QPushButton[role="nav"]:hover {{ background: {SURFACE}; color: {TEXT}; border-color: transparent; }}
QPushButton[role="nav"]:checked {{ background: #284239; color: {ACCENT}; border-color: transparent; }}
QPushButton[role="lectureNav"] {{ background: transparent; border: 1px solid transparent; border-bottom-width: 2px;
    border-radius: 0; font-size: 13px; color: {MUTED}; }}
QPushButton[role="lectureNav"]:hover {{ color: {TEXT}; }}
QPushButton[role="lectureNav"]:checked {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QPushButton[role="nav"]:focus, QPushButton[role="lectureNav"]:focus {{ border-color: {ACCENT}; }}
QPushButton[role="quiet"], QPushButton#studioUtilityButton {{ background: transparent; border-color: transparent; color: {MUTED}; }}
QPushButton[role="quiet"]:hover, QPushButton#studioUtilityButton:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[role="quiet"]:focus, QPushButton#studioUtilityButton:focus {{ border-color: {ACCENT}; }}
QPushButton[role="quiet"]:disabled {{ color: #81939D; background: transparent; border-color: transparent; }}
QPushButton#transcriptPlay {{ background: #34584D; border-color: transparent; color: {TEXT}; padding: 5px 12px; }}
QPushButton#transcriptPlay:hover {{ background: #426B5E; }}
QPushButton#transcriptPlay:focus {{ border-color: {ACCENT}; }}
QPushButton#transcriptPlay:disabled {{ background: {RAISED}; color: #81939D; }}
QSlider#transcriptSeek::groove:horizontal {{ height: 4px; background: #485861; border-radius: 2px; }}
QSlider#transcriptSeek::sub-page:horizontal {{ background: #73BCAB; border-radius: 2px; }}
QSlider#transcriptSeek::handle:horizontal {{ background: {ACCENT}; width: 12px; margin: -4px 0; border-radius: 6px; }}
QSlider#transcriptSeek::handle:horizontal:focus {{ border: 1px solid {TEXT}; }}
QSlider#transcriptSeek::handle:horizontal:disabled {{ background: #66777F; }}
QPushButton#recordButton {{ min-width: 118px; border: none; border-radius: 12px;
    padding: 9px 18px; font-size: 12px; font-weight: 700; }}
QPushButton#recordButton[state="idle"] {{ background: {ACCENT}; color: {BACKGROUND}; }}
QPushButton#recordButton[state="idle"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#recordButton[state="busy"] {{ background: {RAISED}; color: {MUTED}; }}
QPushButton#stopRecordingButton {{ background: #FFB5A1; color: #241713; border-color: #FFB5A1; }}
QPushButton#stopRecordingButton:hover {{ background: #FF9C85; }}
QPushButton#stopRecordingButton:focus {{ border-color: {TEXT}; }}
QPushButton#stopRecordingButton:disabled {{ background: {RAISED}; color: {MUTED}; border-color: {BORDER}; }}
QPushButton[role="warmAction"] {{ color: #E7C28F; border-color: #5E5038; background: #262219; }}
QPushButton[role="warmAction"]:hover {{ background: #332B1E; border-color: #806D4C; color: #F3D3A6; }}
QPushButton:disabled {{ color: #81939D; background: {SURFACE}; border-color: {BORDER}; }}
QLineEdit, QComboBox, QTimeEdit, QDateEdit, QDateTimeEdit, QSpinBox, QDoubleSpinBox {{ background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px; padding: 9px; selection-background-color: {SELECTION}; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QAbstractSpinBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QCalendarWidget QWidget {{ background: {RAISED}; color: {TEXT}; }}
QCalendarWidget QAbstractItemView {{ background: {SURFACE}; color: {TEXT};
    selection-background-color: {ACCENT}; selection-color: {BACKGROUND}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox[role="speakerFilter"]::down-arrow {{ width: 0; height: 0; }}
QComboBox QAbstractItemView, QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; selection-background-color: {SELECTION}; }}
QMenu {{ padding: 6px; }}
QMenu::item {{ padding: 9px 20px; }}
QMenu::item:selected {{ background: {SELECTION}; }}
QTextEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 10px; padding: 12px; font-size: 14px; selection-background-color: {SELECTION}; }}
QTextEdit[role="paper"] {{ background: transparent; border: 1px solid transparent; padding: 5px; font-size: 15px; }}
QTextEdit[role="paper"]:focus {{ border-color: #648B80; }}
QTextEdit#transcriptBody {{ font-size: 15px; selection-color: {TEXT}; selection-background-color: {SELECTION}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ width: 6px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #4D6069; border-radius: 3px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #4D6069; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: {BACKGROUND}; }}
QSplitter::handle:hover {{ background: #476460; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #738891; border-radius: 4px; background: {SURFACE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
'''


def role(widget, value):
    widget.setProperty('role', value)
    return widget


def label(text, kind='muted'):
    return role(QLabel(text), kind)


def button(text, slot, kind=None):
    result = QPushButton(text)
    result.setCursor(Qt.PointingHandCursor)
    result.setMinimumHeight(36)
    result.clicked.connect(slot)
    if kind:
        role(result, kind)
    return result


def apply_theme(window):
    """Replace legacy per-widget styles so all screens share one visual system."""
    window.setStyleSheet('')
    window.setObjectName('annieSurface')
    palette = window.palette()
    for key, color in ((QPalette.Window, BACKGROUND), (QPalette.Base, SURFACE),
                       (QPalette.Button, RAISED), (QPalette.Text, TEXT),
                       (QPalette.WindowText, TEXT), (QPalette.ButtonText, TEXT),
                       (QPalette.Highlight, SELECTION), (QPalette.HighlightedText, TEXT),
                       (QPalette.PlaceholderText, MUTED)):
        palette.setColor(key, QColor(color))
    window.setPalette(palette)
    for widget in window.findChildren(QWidget):
        widget.setStyleSheet('')
        if isinstance(widget, QPushButton):
            widget.setCursor(Qt.PointingHandCursor)
        widget.setPalette(palette)
        widget.setStyleSheet(STYLE)
    window.setStyleSheet(STYLE)
    for widget in window.findChildren(QWidget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class Signature(QWidget):
    """A quiet orbital mark; state changes are explicit, with no idle animation."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(106, 106)
        self._state = 'idle'
        self.setAccessibleName('Annie voice status')

    def set_state(self, state):
        self._state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(53, 53)
        color = '#E5BB83' if self._state == 'thinking' else ACCENT
        for angle in (-35, 25, 85):
            painter.save()
            painter.rotate(angle)
            painter.setPen(QPen(QColor(color), 1.2))
            painter.drawEllipse(QRectF(-44, -19, 88, 38))
            painter.restore()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(-6, -6, 12, 12))


class LaunchCard(QPushButton):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)

    def __init__(self, number, title, subtitle, parent=None):
        super().__init__(parent)
        self.setAccessibleName(title)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        index = label(number, 'eyebrow')
        index.setFixedWidth(24)
        layout.addWidget(index)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        copy.addWidget(label(title, 'section'))
        description = label(subtitle)
        description.setWordWrap(True)
        copy.addWidget(description)
        layout.addLayout(copy, 1)
        layout.addWidget(label('↗', 'section'))
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)


def build_home(window):
    window.setWindowTitle('Annie · Your study space')
    window.resize(500, 820)
    central = QWidget()
    central.setObjectName('home')
    window.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(20, 20, 20, 18)
    layout.setSpacing(16)
    header = QHBoxLayout()
    header.addWidget(label('annie /', 'title'))
    header.addStretch()
    window.clock_lbl = label(datetime.now().strftime('%H:%M'))
    header.addWidget(window.clock_lbl)
    window.pin_btn = button('Pin', window._toggle_pin)
    window.pin_btn.setToolTip('Keep Annie on top of other windows')
    header.addWidget(window.pin_btn)
    layout.addLayout(header)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName('homeContent')
    body = QVBoxLayout(content)
    body.setContentsMargins(0, 0, 6, 0)
    body.setSpacing(10)
    hero = role(QFrame(), 'panel')
    hero_layout = QVBoxLayout(hero)
    hero_layout.setContentsMargins(20, 14, 20, 14)
    hero_layout.addWidget(label('YOUR STUDY COMPANION', 'eyebrow'))
    hero_row = QHBoxLayout()
    headline = label('Your day.\nIn focus.', 'hero')
    hero_row.addWidget(headline, 1)
    window.orb = Signature()
    hero_row.addWidget(window.orb)
    hero_layout.addLayout(hero_row)
    window.subtitle_lbl = label('Ask a question. Capture an idea.')
    window.subtitle_lbl.setWordWrap(True)
    hero_layout.addWidget(window.subtitle_lbl)
    window.status_badge = label('● Ready', 'eyebrow')
    window.status_lbl = window.status_badge
    hero_layout.addWidget(window.status_badge)
    body.addWidget(hero)

    body.addWidget(label('MAKE IT A PRODUCTIVE SESSION', 'eyebrow'))
    for attr, number, title, subtitle, slot in (
        ('card_meeting', '01', 'Lecture studio', 'Audio → notes → understanding', window._open_meeting),
        ('card_schedule', '02', 'Your week', 'Classes, plans, and what comes next', window._open_schedule),
        ('card_vision', '03', 'Visual thinking', 'Bring a slide or a formula into focus', window._open_camera),
    ):
        card = LaunchCard(number, title, subtitle)
        card.clicked.connect(slot)
        setattr(window, attr, card)
        body.addWidget(card)

    window.activity = QTextEdit()
    window.activity.setReadOnly(True)
    window.activity.setAccessibleName('Conversation')
    window.activity.document().setMaximumBlockCount(100)
    window.activity.setFixedHeight(120)
    window.activity.hide()
    body.addWidget(window.activity)

    body.addWidget(label('CAMPUS SHORTCUTS', 'eyebrow'))
    links = QGridLayout()
    from annie.utils.nu_links import open_moodle, open_registrar, open_my_nu, open_libcal
    for i, (title, slot) in enumerate((('Moodle ↗', open_moodle), ('Registrar ↗', open_registrar),
                                      ('My.NU ↗', open_my_nu), ('Library ↗', open_libcal))):
        links.addWidget(button(title, slot), i // 2, i % 2)
    body.addLayout(links)
    body.addStretch()
    scroll.setWidget(content)
    layout.addWidget(scroll, 1)

    dock = QGridLayout()
    window.workstation_btn = button('Open lecture studio  ↗', window._open_meeting, 'primary')
    dock.addWidget(window.workstation_btn, 0, 0, 1, 3)
    window.mute_btn = button('Mic on', window._toggle_mute)
    window.mute_btn.setToolTip('Mute or enable Annie’s microphone and voice')
    window.set_btn = button('Settings', window._open_settings)
    window.exit_btn = button('Quit', window.close)
    for col, widget in enumerate((window.mute_btn, window.set_btn, window.exit_btn)):
        dock.addWidget(widget, 1, col)
    layout.addLayout(dock)
    apply_theme(window)
    window._shortcuts = [QShortcut('Ctrl+M', window, activated=window._toggle_mute),
                         QShortcut('Ctrl+L', window, activated=window._open_meeting)]
