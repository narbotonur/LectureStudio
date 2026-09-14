"""Compact, non-taskbar companion shown while Lecture Studio is minimized."""
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QRect, QRectF, QSize, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QIcon, QPainter
from PyQt5.QtWidgets import QApplication, QBoxLayout, QDialog, QFrame, QHBoxLayout, QLabel, QLayout, QToolButton, QVBoxLayout, QWidget

from annie.utils import nu_links


class AudioLevelMeter(QWidget):
    """A smoothed volume meter; silence stays flat, even during recording."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(94, 24)
        self.setAccessibleName('Recording audio volume')
        self._active = False
        self._vertical = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._target = self._level = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active):
        self._active = active
        if not active:
            self._target = self._level = 0.0
        self.setVisible(active)
        self._sync_timer()
        self.update()

    def update_level(self, level, _is_hearing=False):
        if self._active:
            self._target = max(0.0, min(1.0, float(level)))

    def set_vertical(self, vertical):
        self._vertical = vertical
        self.setFixedSize(24, 94) if vertical else self.setFixedSize(94, 24)
        self.update()

    def _sync_timer(self):
        if self._active and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._level += (self._target - self._level) * 0.3
        self._target *= 0.93
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._vertical:
            painter.translate(self.width(), 0)
            painter.rotate(90)
        painter.setPen(Qt.NoPen)
        for index in range(18):
            height = 5 + 17 * (1 - abs(index - 8.5) / 10)
            lit = self._level > (index + 0.5) / 18
            painter.setBrush(QColor('#C5ED87' if lit else '#394132'))
            painter.drawRoundedRect(QRectF(index * 5.2, (24 - height) / 2, 3, height), 1.5, 1.5)


class StudioDock(QDialog):
    restore_requested = pyqtSignal()
    EDGE_DISTANCE = 80
    EDGE_GAP = 6

    def __init__(self):
        # Intentionally unowned: Windows must not hide this when Studio hides.
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Annie · Mini studio')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._animation = None
        self._closing = False
        self._drag_offset = None
        self._saved_position = None
        self._saved_geometry = None
        self._compact = False
        self._vertical = False
        self._recording = False
        self._press_position = None
        self._dragged = False
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(3000)
        self._collapse_timer.timeout.connect(self._collapse_if_away)
        self.resize(550, 148)
        self.setStyleSheet('''
            QWidget { font-family: 'Segoe UI'; color: #F1F3E9; }
            QFrame#dockShell { background: #181B17; border: 1px solid #3C4436; border-radius: 26px; }
            QLabel { background: transparent; border: none; }
            QLabel#dockTitle { font-size: 13px; font-weight: 700; }
            QLabel#dockStatus { font-size: 10px; color: #ADB6A4; }
            QLabel#dockMark { background: #252B21; border: 1px solid #59664D; border-radius: 17px;
                color: #C5ED87; font-size: 16px; font-weight: 700; }
            QToolButton { background: #252B21; border: 1px solid #394232; border-radius: 12px;
                padding: 7px; font-size: 11px; font-weight: 600; }
            QToolButton:hover { background: #34402B; border-color: #657B50; }
            QToolButton:pressed { background: #425136; }
            QToolButton:focus { border-color: #C5ED87; }
            QToolButton#restoreStudio { background: #C5ED87; color: #17200F; border: none; }
            QToolButton#restoreStudio:hover { background: #D9FFA5; }
            QToolButton#portalShortcut { padding: 0px; border-radius: 14px; }
        ''')
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        outer.setContentsMargins(6, 6, 6, 6)
        shell = QFrame()
        shell.setObjectName('dockShell')
        outer.addWidget(shell)
        body = self.body = QVBoxLayout(shell)
        body.setContentsMargins(18, 13, 18, 13)
        body.setSpacing(12)
        header = self.header = QBoxLayout(QBoxLayout.LeftToRight)
        header.setSpacing(10)
        mark = self.mark = QLabel('A')
        mark.setObjectName('dockMark')
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        header.addWidget(mark, 0, Qt.AlignCenter)
        self.copy_panel = QWidget()
        copy = QVBoxLayout(self.copy_panel)
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(1)
        title = QLabel('Lecture studio')
        title.setObjectName('dockTitle')
        self.status = QLabel('Ready when you are')
        self.status.setObjectName('dockStatus')
        copy.addWidget(title)
        copy.addWidget(self.status)
        header.addWidget(self.copy_panel, 1)
        self.meter = AudioLevelMeter()
        header.addWidget(self.meter, 0, Qt.AlignCenter)
        self.restore_button = QToolButton()
        self.restore_button.setObjectName('restoreStudio')
        self.restore_button.setText('Open studio ↗')
        self.restore_button.setAccessibleName('Restore Lecture Studio')
        self.restore_button.setToolTip('Open Lecture Studio')
        self.restore_button.setFixedHeight(34)
        self.restore_button.clicked.connect(self.restore_requested.emit)
        header.addWidget(self.restore_button)
        body.addLayout(header)
        self.links_panel = QWidget()
        links = self.links = QBoxLayout(QBoxLayout.LeftToRight, self.links_panel)
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(8)
        links.setAlignment(Qt.AlignCenter)
        self.portal_buttons = {}
        assets = Path(__file__).parent / 'assets' / 'portals'
        for name, asset, slot in (
            ('Moodle', 'moodle-symbol.svg', nu_links.open_moodle),
            ('Registrar', 'registrar-symbol.svg', nu_links.open_registrar),
            ('MyNU', 'mynu.png', nu_links.open_my_nu),
            ('LibCal', 'libcal-symbol.svg', nu_links.open_libcal),
        ):
            button = QToolButton()
            button.setObjectName('portalShortcut')
            button.setText(name)
            button.setAccessibleName('Open ' + name)
            button.setIcon(QIcon(str(assets / asset)))
            icon_size = 20 if name == 'MyNU' else 34
            button.setIconSize(QSize(icon_size, icon_size))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setFixedSize(46, 46)
            button.setToolTip('Open ' + name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            links.addWidget(button, 0, Qt.AlignCenter)
            self.portal_buttons[name] = button
        body.addWidget(self.links_panel)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_recording(False)

    def set_recording(self, active):
        changed = self._recording != active
        self._recording = active
        self.status.setText('● Recording · live audio' if active else 'Ready when you are')
        self.meter.set_active(active)
        if changed and (self._compact or self._vertical):
            self._transition_layout()

    def _desired_size(self):
        if self._compact:
            if not self._recording:
                return QSize(68, 68)
            return QSize(68, 178) if self._vertical else QSize(178, 68)
        return QSize(92, 464 if self._recording else 364) if self._vertical else QSize(390, 154)

    def _apply_layout(self):
        column = self._vertical
        self.header.setDirection(QBoxLayout.TopToBottom if column else QBoxLayout.LeftToRight)
        self.links.setDirection(QBoxLayout.TopToBottom if column else QBoxLayout.LeftToRight)
        self.copy_panel.setVisible(not self._compact and not column)
        self.links_panel.setVisible(not self._compact)
        self.restore_button.setVisible(not self._compact)
        self.restore_button.setText('↗')
        self.restore_button.setFixedSize(34, 34)
        self.header.setAlignment(self.restore_button, Qt.AlignCenter)
        self.header.setStretch(1, 0 if column or self._compact else 1)
        self.body.setContentsMargins(*( (10, 10, 10, 10) if self._compact or column else (18, 13, 18, 13)))
        self.body.setSpacing(0 if self._compact else 12)
        self.meter.set_vertical(column)
        self.setToolTip('Click to expand · Drag to move' if self._compact else 'Drag the header to move')

    def _screen_area(self):
        screen = QApplication.screenAt(self.geometry().center()) or self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    @classmethod
    def edge_for(cls, rect, area):
        """Side edges win over top/bottom when both are within reach."""
        left, right = abs(rect.left() - area.left()), abs(area.right() - rect.right())
        top, bottom = abs(rect.top() - area.top()), abs(area.bottom() - rect.bottom())
        if min(left, right) <= cls.EDGE_DISTANCE:
            return 'left' if left <= right else 'right'
        if min(top, bottom) <= cls.EDGE_DISTANCE:
            return 'top' if top <= bottom else 'bottom'
        return None

    def _target_rect(self, old, size, area):
        # Keep the same edge gaps through expansion, including at corners.
        x = old.center().x() - size.width() // 2
        y = old.center().y() - size.height() // 2
        if abs(old.left() - area.left()) <= self.EDGE_DISTANCE:
            x = old.left()
        elif abs(area.right() - old.right()) <= self.EDGE_DISTANCE:
            x = old.right() - size.width() + 1
        if abs(old.top() - area.top()) <= self.EDGE_DISTANCE:
            y = old.top()
        elif abs(area.bottom() - old.bottom()) <= self.EDGE_DISTANCE:
            y = old.bottom() - size.height() + 1
        x = max(area.left(), min(x, area.right() - size.width() + 1))
        y = max(area.top(), min(y, area.bottom() - size.height() + 1))
        return QRect(x, y, size.width(), size.height())

    def _transition_layout(self, adapt_edge=False):
        old = self.geometry()
        area = self._screen_area()
        if adapt_edge:
            edge = self.edge_for(old, area)
            self._vertical = edge in ('left', 'right')
            # Snap both axes in corners, while the side determines orientation.
            if edge == 'left':
                old.moveLeft(area.left() + self.EDGE_GAP)
            elif edge == 'right':
                old.moveRight(area.right() - self.EDGE_GAP)
            if abs(old.top() - area.top()) <= self.EDGE_DISTANCE:
                old.moveTop(area.top() + self.EDGE_GAP)
            elif abs(area.bottom() - old.bottom()) <= self.EDGE_DISTANCE:
                old.moveBottom(area.bottom() - self.EDGE_GAP)
        self._apply_layout()
        target = self._target_rect(old, self._desired_size(), area)

        def remember():
            self._saved_geometry = QRect(target)
            self._saved_position = target.topLeft()

        if self.isVisible():
            self._animate(target, 1.0, 280, QEasingCurve.OutCubic, remember)
        else:
            self.setGeometry(target)
            remember()

    def _arm_collapse(self):
        if (self.isVisible() and not self._compact and not self._closing
                and self._drag_offset is None):
            self._collapse_timer.start()

    def _collapse_if_away(self):
        if (self._closing or self._compact or not self.isVisible()
                or self._drag_offset is not None
                or self.geometry().contains(QCursor.pos())):
            return
        self._compact = True
        self._transition_layout()

    def expand(self):
        if not self._compact or self._closing:
            return
        self._compact = False
        self._transition_layout()
        self._arm_collapse()

    def enterEvent(self, event):
        self._collapse_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._arm_collapse()
        super().leaveEvent(event)

    def _stop_animation(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None

    def _animate(self, target, opacity, duration, easing, after=None):
        self._stop_animation()
        group = QParallelAnimationGroup(self)
        for prop, start, end in ((b'geometry', self.geometry(), target),
                                 (b'windowOpacity', self.windowOpacity(), opacity)):
            animation = QPropertyAnimation(self, prop, group)
            animation.setDuration(duration)
            animation.setStartValue(start)
            animation.setEndValue(end)
            animation.setEasingCurve(easing)
            group.addAnimation(animation)

        def complete():
            self._animation = None
            if after:
                after()
            group.deleteLater()

        group.finished.connect(complete)
        self._animation = group
        group.start()

    def present(self, screen=None):
        self._stop_animation()
        self._collapse_timer.stop()
        self._closing = False
        self._compact = False
        self.setEnabled(True)
        screen = screen or QApplication.primaryScreen()
        area = screen.availableGeometry()
        point = self._saved_position
        size = self._desired_size()
        x = point.x() if point else area.center().x() - size.width() // 2
        y = point.y() if point else area.top() + 28
        old = QRect(self._saved_geometry) if self._saved_geometry else QRect(x, y, size.width(), size.height())
        self._vertical = self.edge_for(old, area) in ('left', 'right')
        self._apply_layout()
        target = self._target_rect(old, self._desired_size(), area)
        self.setGeometry(target.adjusted(12, -12, -12, -24))
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._animate(target, 1.0, 420, QEasingCurve.OutBack, self._arm_collapse)

    def dismiss_animated(self, after):
        if self._closing:
            return
        if not self.isVisible():
            after()
            return
        self._closing = True
        self._collapse_timer.stop()
        self._saved_position = self.pos()
        self._saved_geometry = self.geometry()
        self.setEnabled(False)
        target = self.geometry().adjusted(8, -16, -8, -24)

        def done():
            self.hide_immediately()
            after()

        self._animate(target, 0.0, 230, QEasingCurve.InCubic, done)

    def hide_immediately(self):
        self._collapse_timer.stop()
        self._stop_animation()
        self.hide()
        self._closing = False
        self.setWindowOpacity(1.0)

    def reject(self):
        self.restore_requested.emit()

    def closeEvent(self, event):
        event.ignore()
        self.restore_requested.emit()

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton and not self._closing
                and (self._compact or event.pos().y() < (175 if self._vertical else 78))):
            self._stop_animation()
            self._collapse_timer.stop()
            self.resize(self._desired_size())
            self.setWindowOpacity(1.0)
            self._drag_offset = event.globalPos() - self.pos()
            self._press_position = event.globalPos()
            self._dragged = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self._press_position).manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
            if self._dragged:
                self.move(event.globalPos() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            if self._dragged:
                self._transition_layout(adapt_edge=True)
            elif self._compact:
                self.expand()
            self._saved_position = self.pos()
            self._arm_collapse()
        super().mouseReleaseEvent(event)
