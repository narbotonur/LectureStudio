"""Annie's native desktop visual system and home composition."""
from datetime import datetime
import sys

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QFont, QPalette
from PyQt5.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QTextEdit, QSizePolicy, QShortcut,
)

BACKGROUND = '#111310'
SURFACE = '#1B1E19'
RAISED = '#242921'
BORDER = '#343B30'
TEXT = '#F1F3E9'
MUTED = '#ADB6A4'
ACCENT = '#C5ED87'
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
QLabel[role="studyClock"] {{ color: {ACCENT}; font-family: '{MONO_FONT}'; font-size: 46px; font-weight: 600; padding: 12px 0; }}
QTableWidget {{ background: {SURFACE}; alternate-background-color: {RAISED}; border: 1px solid {BORDER};
    border-radius: 10px; gridline-color: {BORDER}; selection-background-color: #35452B; }}
QTableWidget::item {{ padding: 6px; }}
QHeaderView::section {{ background: {RAISED}; color: {MUTED}; border: none; padding: 8px; }}
QFrame[role="panel"], QFrame#notesPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[role="navigation"] {{ background: {SURFACE}; border-radius: 12px; }}
QFrame[role="studioHeader"] {{ background: transparent; border: none; }}
QLabel[role="brandMark"] {{ background: #252B21; color: {ACCENT}; border: 1px solid #526642;
    border-radius: 21px; font-size: 18px; font-weight: 700; }}
QLabel[role="studioTitle"] {{ color: {TEXT}; font-size: 24px; font-weight: 650; }}
QLabel[role="studioStatus"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="fieldLabel"], QLabel[role="navCaption"] {{ color: #849079; font-size: 9px;
    font-weight: 700; letter-spacing: 1px; }}
QLabel[role="navCaption"] {{ padding: 3px 9px 7px 9px; }}
QFrame[role="recordingBar"] {{ background: #171A16; border: 1px solid {BORDER}; border-radius: 17px; }}
QFrame[role="studioFooter"] {{ background: #171A16; border: 1px solid {BORDER}; border-radius: 13px; }}
QFrame[role="navigation"] {{ background: #171A16; border: 1px solid #2B3228; border-radius: 15px; }}
QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 8px;
    color: {TEXT}; padding: 7px 12px; font-size: 12px; font-weight: 600; }}
QPushButton:hover {{ background: #30392A; border-color: #6C805B; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:pressed {{ background: #455438; }}
QPushButton[role="primary"] {{ background: {ACCENT}; color: {BACKGROUND}; border-color: {ACCENT}; }}
QPushButton[role="primary"]:hover {{ background: #D9FFA5; }}
QPushButton[role="nav"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; text-align: left; }}
QPushButton[role="nav"]:hover {{ background: #20251D; color: {TEXT}; border-color: transparent; }}
QPushButton[role="nav"]:checked {{ background: #2D3826; color: {ACCENT}; border-color: #46583A; }}
QPushButton#studioUtilityButton {{ background: transparent; border-color: #30372D; color: {MUTED}; }}
QPushButton#studioUtilityButton:hover {{ background: #20251D; color: {TEXT}; border-color: #526642; }}
QPushButton#recordButton {{ min-width: 118px; border: none; border-radius: 12px;
    padding: 9px 18px; font-size: 12px; font-weight: 700; }}
QPushButton#recordButton[state="idle"] {{ background: {ACCENT}; color: {BACKGROUND}; }}
QPushButton#recordButton[state="idle"]:hover {{ background: #D9FFA5; }}
QPushButton#recordButton[state="recording"] {{ background: #FFB5A1; color: #241713; }}
QPushButton#recordButton[state="recording"]:hover {{ background: #FF9C85; }}
QPushButton#recordButton[state="busy"] {{ background: #30372D; color: {MUTED}; }}
QPushButton[role="warmAction"] {{ color: #E7C28F; border-color: #5E5038; background: #262219; }}
QPushButton[role="warmAction"]:hover {{ background: #332B1E; border-color: #806D4C; color: #F3D3A6; }}
QPushButton:disabled {{ color: #818B79; background: #252B21; border-color: {BORDER}; }}
QLineEdit, QComboBox, QTimeEdit, QDateEdit, QSpinBox, QDoubleSpinBox {{ background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px; padding: 9px; selection-background-color: #455C33; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#courseContextInput {{ background: #1A1E18; border-color: #30372D; }}
QAbstractSpinBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView, QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; selection-background-color: #455C33; }}
QMenu {{ padding: 6px; }}
QMenu::item {{ padding: 9px 20px; }}
QMenu::item:selected {{ background: #455C33; }}
QTextEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 10px; padding: 12px; font-size: 14px; selection-background-color: #455C33; }}
QTextEdit[role="paper"] {{ border: 1px solid transparent; padding: 4px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ width: 6px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #47543D; border-radius: 3px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #47543D; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: {BACKGROUND}; }}
QSplitter::handle:hover {{ background: #526642; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #738564; border-radius: 4px; background: {SURFACE}; }}
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
                       (QPalette.Highlight, '#455C33'), (QPalette.HighlightedText, TEXT),
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
