"""Resolution-independent glass card and prayer symbols, drawn natively by Qt."""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient,
                         QRadialGradient, QPen)
from PyQt5.QtWidgets import (QWidget, QPushButton, QLabel, QFrame, QVBoxLayout,
                             QHBoxLayout, QSizePolicy)

from annie.gui.design import UI_FONT, MONO_FONT
from annie.prayer_times import DISPLAY_TIMES, NAMES


class PrayerIcon(QWidget):
    def __init__(self, prayer='Fajr', parent=None):
        super().__init__(parent)
        self.prayer = prayer
        self.setFixedSize(44, 44)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName(NAMES.get(prayer, prayer))

    def set_prayer(self, prayer):
        if self.prayer != prayer:
            self.prayer = prayer
            self.setAccessibleName(NAMES.get(prayer, prayer))
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width() / 48, self.height() / 48)
        colors = {'Fajr': ('#923FFF', '#590BD6'), 'Sunrise': ('#1C99FC', '#0052BA'),
                  'Dhuhr': ('#FFD942', '#F5A600'), 'Asr': ('#FFBA46', '#F87900'),
                  'Maghrib': ('#F46B75', '#BB3148'), 'Isha': ('#48336D', '#201237')}
        light, dark = colors.get(self.prayer, colors['Isha'])
        base = QLinearGradient(8, 3, 35, 45)
        base.setColorAt(0, QColor(light))
        base.setColorAt(1, QColor(dark))
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawEllipse(QRectF(3, 3, 42, 42))
        if self.prayer in ('Fajr', 'Isha'):
            moon = QPainterPath()
            moon.addEllipse(QRectF(13, 9, 25, 29))
            cut = QPainterPath()
            cut.addEllipse(QRectF(7, 3, 27, 31))
            gleam = QLinearGradient(15, 9, 36, 38)
            gleam.setColorAt(0, QColor(255, 255, 255, 230))
            gleam.setColorAt(.6, QColor(223, 218, 255, 230))
            gleam.setColorAt(1, QColor(192, 183, 238, 70))
            p.setBrush(gleam)
            p.drawPath(moon.subtracted(cut))
        elif self.prayer in ('Sunrise', 'Maghrib'):
            glow = QLinearGradient(24, 13, 24, 32)
            glow.setColorAt(0, QColor('#E6F6FF') if self.prayer == 'Sunrise' else QColor('#FFE1AF'))
            glow.setColorAt(1, QColor(255, 235, 200, 12))
            p.setBrush(glow)
            p.save()
            p.setClipRect(QRectF(8, 7, 32, 22))
            p.drawEllipse(QRectF(11, 15, 26, 27))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 100), 1.2))
            p.drawLine(QPointF(12, 29), QPointF(36, 29))
        else:
            glow = QRadialGradient(QPointF(21, 20), 19)
            glow.setColorAt(0, QColor('#FFF8BC') if self.prayer == 'Dhuhr' else QColor('#FFD988'))
            glow.setColorAt(.55, QColor('#FFE178') if self.prayer == 'Dhuhr' else QColor('#FFA937'))
            glow.setColorAt(1, QColor(255, 191, 35, 15))
            p.setBrush(glow)
            p.drawEllipse(QRectF(8, 8, 32, 32))


class CardButton(QPushButton):
    def __init__(self, glyph, tooltip, parent=None):
        super().__init__('', parent)
        self.glyph = glyph
        self.setFixedSize(27, 27)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#F0F6FF'), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.glyph == 'pin':
            path = QPainterPath(QPointF(10, 6))
            path.lineTo(17, 6)
            path.lineTo(16, 13)
            path.lineTo(19, 16)
            path.lineTo(8, 16)
            path.lineTo(11, 13)
            path.closeSubpath()
            if self.isChecked():
                p.setBrush(QColor(230, 244, 255, 180))
            p.drawPath(path)
            p.drawLine(QPointF(13.5, 16), QPointF(13.5, 22))
        elif self.glyph == 'size':
            p.drawLine(7, 17, 17, 7)
            p.drawLine(12, 7, 17, 7)
            p.drawLine(17, 7, 17, 12)
            p.drawLine(7, 12, 7, 17)
            p.drawLine(7, 17, 12, 17)
        else:
            p.drawEllipse(QRectF(8, 8, 11, 11))
            p.drawEllipse(QRectF(11, 11, 5, 5))
            p.translate(13.5, 13.5)
            for _ in range(8):
                p.drawLine(QPointF(0, -6), QPointF(0, -8))
                p.rotate(45)


def paint_glass(widget):
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(3, 2, -3, -5)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(10, 25, 48, 38))
    p.drawRoundedRect(rect.translated(0, 3), 26, 26)
    background = QLinearGradient(rect.topLeft(), rect.bottomRight())
    background.setColorAt(0, QColor(92, 137, 197, 235))
    background.setColorAt(.55, QColor(78, 111, 153, 235))
    background.setColorAt(1, QColor(105, 142, 151, 235))
    p.setBrush(background)
    border = QLinearGradient(rect.topLeft(), rect.bottomRight())
    border.setColorAt(0, QColor(236, 248, 255, 185))
    border.setColorAt(.55, QColor(236, 248, 255, 35))
    border.setColorAt(1, QColor(236, 248, 255, 115))
    p.setPen(QPen(border, 1.1))
    p.drawRoundedRect(rect, 26, 26)


def build_card(w):
    w.setObjectName('prayerCard')
    w.setStyleSheet(f'''
        QWidget#prayerCard {{ font-family: '{UI_FONT}'; color: #F2F7FF; }}
        QLabel {{ background: transparent; border: none; color: #F2F7FF; }}
        QPushButton {{ background: transparent; border: none; border-radius: 9px; padding: 0; }}
        QPushButton:hover {{ background: rgba(255,255,255,28); }}
        QPushButton:checked {{ background: rgba(230,246,255,42); }}
        QPushButton:focus {{ border: 1px solid rgba(230,246,255,150); }}
        QFrame#timeTile {{ background: transparent; border: none; border-radius: 14px; }}
        QFrame#timeTile[next="true"] {{ background: rgba(234,245,255,20); }}
    ''')
    outer = QVBoxLayout(w)
    outer.setContentsMargins(23, 18, 23, 18)
    outer.setSpacing(10)
    top = QHBoxLayout()
    top.setSpacing(5)
    w.next_label = QLabel('Выбрать город')
    w.next_label.setStyleSheet('font-size: 16px; font-weight: 600;')
    w.next_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    top.addWidget(w.next_label, 1)
    w.summary_countdown = QLabel('—:—:—')
    w.summary_countdown.setStyleSheet(f"font-family: '{MONO_FONT}'; font-size: 17px; font-weight: 600;")
    top.addWidget(w.summary_countdown)
    top.addSpacing(6)
    w.size_button = CardButton('size', 'Компактный / широкий виджет')
    w.size_button.clicked.connect(w.toggle_size)
    top.addWidget(w.size_button)
    w.pin_button = CardButton('pin', 'Закрепить на рабочем столе')
    w.pin_button.setCheckable(True)
    w.pin_button.clicked.connect(w.set_pinned)
    top.addWidget(w.pin_button)
    w.settings_button = CardButton('settings', 'Город, мазхаб и метод расчёта')
    w.settings_button.clicked.connect(w.open_settings)
    top.addWidget(w.settings_button)
    outer.addLayout(top)
    w.hero_panel = QWidget()
    hero = QHBoxLayout(w.hero_panel)
    hero.setContentsMargins(0, 4, 0, 0)
    hero.setSpacing(6)
    w.hero_icon = PrayerIcon('Asr')
    hero.addWidget(w.hero_icon)
    w.countdown = QLabel('—:—:—')
    w.countdown.setStyleSheet(f"font-family: '{MONO_FONT}'; font-size: 30px; font-weight: 600;")
    hero.addWidget(w.countdown)
    outer.addWidget(w.hero_panel)
    w.at_label = QLabel('')
    w.at_label.setStyleSheet('font-size: 11px; color: #D3E1EF;')
    outer.addWidget(w.at_label)
    w.times_panel = QWidget()
    grid = QHBoxLayout(w.times_panel)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(4)
    w.tiles = {}
    for name in DISPLAY_TIMES:
        tile = QFrame()
        tile.setObjectName('timeTile')
        column = QVBoxLayout(tile)
        column.setContentsMargins(3, 4, 3, 6)
        column.setSpacing(4)
        icon = PrayerIcon(name)
        column.addWidget(icon, 0, Qt.AlignHCenter)
        title = QLabel(NAMES[name])
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size: 12px; color: #DBE7F4;')
        value = QLabel('—:—')
        value.setAlignment(Qt.AlignCenter)
        value.setStyleSheet('font-size: 16px; font-weight: 600;')
        column.addWidget(title)
        column.addWidget(value)
        grid.addWidget(tile, 1)
        w.tiles[name] = tile, value
    outer.addWidget(w.times_panel)
    w.date_row = QHBoxLayout()
    w.hijri_label = QLabel('')
    w.hijri_label.setStyleSheet('font-size: 11px; color: #D5E2EF;')
    w.hijri_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    w.date_row.addWidget(w.hijri_label, 1)
    w.location = QLabel('')
    w.location.setStyleSheet('font-size: 11px; color: #E3ECF7;')
    w.date_row.addWidget(w.location)
    outer.addLayout(w.date_row)
    w.footer = QLabel('Выберите город в настройках')
    w.footer.setWordWrap(True)
    w.footer.setStyleSheet('font-size: 9px; color: #C5D7E8;')
    outer.addWidget(w.footer)
