"""Lightweight frameless prayer card; networking stays off the Qt UI thread."""
from dataclasses import replace
from datetime import datetime, timezone
import time
import sys

from PyQt5.QtCore import Qt, QTimer, QThread, QSize, QRectF, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QColor, QPainter, QPen, QPainterPath, QRegion
from PyQt5.QtWidgets import (QWidget, QDialog, QLabel, QPushButton, QFrame, QVBoxLayout,
                            QHBoxLayout, QFormLayout, QLineEdit, QComboBox, QSpinBox,
                            QCheckBox, QDialogButtonBox, QMessageBox, QApplication, QMenu)

from annie.gui.design import apply_theme, UI_FONT, MONO_FONT
from annie.desktop_pin import DesktopPin
from annie.gui.prayer_card import build_card, paint_glass
from annie.prayer_times import (PrayerStore, PrayerSettings, DISPLAY_TIMES, NAMES, MADHHABS,
                               METHODS, fetch_schedule, today_schedule, next_prayer,
                               local_now, refresh_due)


class PrayerSettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from annie import prayer_startup
        self.original = settings
        self.setWindowTitle('Намаз · настройки виджета')
        self.setMinimumWidth(500)
        outer = QVBoxLayout(self)
        title = QLabel('Город и расчёт времени')
        title.setProperty('role', 'section')
        outer.addWidget(title)
        form = QFormLayout()
        self.city, self.country = QLineEdit(settings.city), QLineEdit(settings.country)
        self.city.setPlaceholderText('Например: Astana')
        self.country.setPlaceholderText('Например: Kazakhstan')
        form.addRow('Город', self.city)
        form.addRow('Страна', self.country)
        self.madhhab, self.method = QComboBox(), QComboBox()
        for key, title in MADHHABS.items():
            self.madhhab.addItem(title, key)
        self.madhhab.setCurrentIndex(self.madhhab.findData(settings.madhhab))
        for key, title in METHODS.items():
            self.method.addItem(title, key)
        self.method.setCurrentIndex(self.method.findData(settings.method))
        form.addRow('Мазхаб', self.madhhab)
        form.addRow('Метод Фаджра / Иши', self.method)
        outer.addLayout(form)
        note = QLabel('Ханафи: Аср при тени в две длины предмета; остальные три мазхаба — '
                      'в одну длину, сверх полуденной тени. Метод Фаджра / Иши выбирается отдельно.\n\n'
                      'AlAdhan — расчётный источник, не официальное расписание ДУМК. '
                      'Сверьте время с местной мечетью. Для высоких широт применяется угловая доля ночи.')
        note.setWordWrap(True)
        note.setProperty('role', 'muted')
        outer.addWidget(note)
        offsets = QHBoxLayout()
        self.adjustments = {}
        for name in DISPLAY_TIMES:
            column = QVBoxLayout()
            column.addWidget(QLabel(NAMES[name]))
            spin = QSpinBox()
            spin.setRange(-60, 60)
            spin.setValue(settings.adjustments.get(name, 0))
            spin.setSuffix(' мин')
            spin.setToolTip('Ручная поправка к расчёту. Не заменяет сезонное расписание мечети.')
            self.adjustments[name] = spin
            column.addWidget(spin)
            offsets.addLayout(column)
        outer.addWidget(QLabel('Поправки к расчётному времени'))
        outer.addLayout(offsets)
        self.on_top = QCheckBox('Поверх других окон')
        self.on_top.setChecked(settings.always_on_top)
        self.pin_desktop = QCheckBox('Закрепить на рабочем столе Windows (под окнами приложений)')
        self.pin_desktop.setChecked(settings.desktop_pinned)
        self.pin_desktop.setEnabled(sys.platform == 'win32')
        self.pin_desktop.toggled.connect(lambda pinned: self.on_top.setEnabled(not pinned))
        self.on_top.setEnabled(not settings.desktop_pinned)
        self.autostart = QCheckBox('Показывать при входе в систему — без запуска Studio')
        self.autostart.setChecked(prayer_startup.enabled())
        outer.addWidget(self.on_top)
        outer.addWidget(self.pin_desktop)
        outer.addWidget(self.autostart)
        privacy = QLabel('В AlAdhan передаются только указанные город, страна и параметры расчёта. '
                         'GPS, IP-геолокация, микрофон и Google-аккаунт не используются. '
                         'Город сохраняется локально. Дата хиджры расчётная и может отличаться от местной.')
        privacy.setWordWrap(True)
        privacy.setProperty('role', 'muted')
        outer.addWidget(privacy)
        self.feedback = QLabel('')
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        apply_theme(self)

    def _save(self):
        try:
            self.value = replace(self.original, city=self.city.text(), country=self.country.text(),
                                 madhhab=self.madhhab.currentData(), method=self.method.currentData(),
                                 adjustments={key: spin.value() for key, spin in self.adjustments.items()},
                                 always_on_top=self.on_top.isChecked(),
                                 desktop_pinned=self.pin_desktop.isChecked()).validate()
            self.accept()
        except ValueError as exc:
            self.feedback.setText(str(exc))


class PrayerFetchThread(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, settings, cached, parent=None):
        super().__init__(parent)
        self.settings, self.cached = settings, cached

    def run(self):
        try:
            self.result.emit(fetch_schedule(self.settings, self.cached,
                                           cancelled=self.isInterruptionRequested))
        except Exception as exc:
            self.failed.emit(str(exc))


class PrayerWidget(QWidget):
    quit_requested = pyqtSignal()

    def __init__(self, store=None, start_network=True):
        super().__init__()
        self.store = store or PrayerStore()
        self.settings = self.store.settings()
        if sys.platform != 'win32':
            self.settings.desktop_pinned = False
        self.data = self.store.cache(self.settings)
        self._worker = None
        self._generation = 0
        self._closing = False
        self._on_shutdown = None
        self._drag = None
        self._animation = None
        self._error = ''
        self._next_attempt = 0
        self._network = start_network
        self._desktop = DesktopPin(self)
        self._pin_suspended = False
        self._pin_retry = 0
        self._pin_error = ''
        self._update_flags()
        # Stable native painting in both Windows pin states. Layered Qt child
        # windows can disappear inside Explorer despite passing HWND checks.
        self.setAttribute(Qt.WA_TranslucentBackground, sys.platform != 'win32')
        if sys.platform == 'win32':
            self.setAttribute(Qt.WA_NoSystemBackground, False)
            self.setAutoFillBackground(True)
        self.setWindowTitle('Annie · Намаз')
        build_card(self)
        self.pin_button.setVisible(sys.platform == 'win32')
        self.pin_button.setChecked(self.settings.desktop_pinned)
        self._set_size(False)
        self._place()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(1000)
        self.tick()
        if start_network and self.settings.city:
            QTimer.singleShot(0, lambda: self.refresh(True))

    def _update_flags(self):
        self._desktop.detach()
        flags = Qt.Tool | Qt.FramelessWindowHint
        if self.settings.always_on_top and not self.settings.desktop_pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def paintEvent(self, event):
        paint_glass(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if sys.platform == 'win32':
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(3, 2, self.width() - 6, self.height() - 7), 26, 26)
            self.setMask(QRegion(outline.toFillPolygon().toPolygon()))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_pin)

    def _apply_pin(self):
        if (self._closing or self._pin_suspended or not self.isVisible()
                or self.testAttribute(Qt.WA_DontShowOnScreen)):
            return
        if not self.settings.desktop_pinned:
            self._desktop.detach()
            return
        try:
            self._desktop.attach()
            self.update()
            self._pin_error = ''
        except Exception as exc:
            self._pin_error = str(exc)
        self._pin_retry = time.monotonic() + 10
        self.pin_button.setChecked(self._desktop.attached)
        self.pin_button.setToolTip('Открепить, чтобы переместить виджет' if self._desktop.attached
                                  else self._pin_error or 'Закрепить на рабочем столе')

    def set_pinned(self, pinned):
        self._drag = None
        self._desktop.detach()
        self.settings.desktop_pinned = bool(pinned) and sys.platform == 'win32'
        if self.settings.desktop_pinned:
            self.settings.always_on_top = False
        self._pin_error = ''
        self._update_flags()
        self.show()
        self._apply_pin()
        self.pin_button.setChecked(self.settings.desktop_pinned and not self._pin_error)
        self._save_appearance()

    def _layout_finished(self):
        self._clamp()
        self._pin_suspended = False
        self._apply_pin()

    def _set_size(self, animated=True):
        self.times_panel.setVisible(not self.settings.compact)
        self.hero_panel.setVisible(self.settings.compact)
        self.summary_countdown.setVisible(not self.settings.compact)
        self.at_label.setVisible(self.settings.compact)
        width, height = (250, 230) if self.settings.compact else (480, 226)
        # Geometry animation gives the same gentle expansion as a notification.
        target = self.geometry()
        target.setSize(QSize(width, height))
        if self._animation:
            self._animation.stop()
        if animated and self.isVisible():
            animation = QPropertyAnimation(self, b'geometry', self)
            animation.setDuration(230)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.setStartValue(self.geometry())
            animation.setEndValue(target)
            animation.finished.connect(self._layout_finished)
            self._animation = animation
            animation.start()
        else:
            self.resize(width, height)
            self._pin_suspended = False

    def _place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        if self.settings.position:
            self.move(*self.settings.position)
        else:
            self.move(screen.right() - self.width() - 24, screen.top() + 60)
        self._clamp()

    def _clamp(self):
        if self._desktop.attached:
            return  # Native child coordinates belong to Explorer; never move via Qt.
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def toggle_size(self):
        self._desktop.detach()
        self._pin_suspended = True
        self.settings.compact = not self.settings.compact
        self._set_size()
        self._save_appearance()

    def _save_appearance(self):
        if not self._desktop.attached:
            self.settings.position = [self.x(), self.y()]
        if self.settings.city and self.settings.country:
            try:
                self.store.save_settings(self.settings)
            except OSError:
                self._error = 'Не удалось сохранить настройки'

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.settings.desktop_pinned:
            self._drag = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None and not self.settings.desktop_pinned and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self._clamp()
            self._save_appearance()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Настройки…', self.open_settings)
        menu.addAction('Обновить расписание', lambda: self.refresh(True))
        menu.addAction('Изменить размер', self.toggle_size)
        if sys.platform == 'win32':
            pin = menu.addAction('Закрепить на рабочем столе')
            pin.setCheckable(True)
            pin.setChecked(self.settings.desktop_pinned)
            pin.triggered.connect(self.set_pinned)
        menu.addSeparator()
        menu.addAction('Скрыть виджет', self.hide)
        menu.addAction('Выйти', self.quit_requested.emit)
        menu.exec_(event.globalPos())

    def open_settings(self):
        from annie import prayer_startup
        dialog = PrayerSettingsDialog(self.settings, None if self._desktop.attached else self)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            self.store.save_settings(dialog.value)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, 'Намаз', str(exc))
            return
        try:
            prayer_startup.set_enabled(dialog.autostart.isChecked())
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, 'Намаз', f'Настройки сохранены, но автозапуск не изменён: {exc}')
        self.settings = dialog.value
        self._generation += 1
        self.data = self.store.cache(self.settings)
        self._error = ''
        self._next_attempt = 0
        self._update_flags()
        self.pin_button.setChecked(self.settings.desktop_pinned)
        self.show()
        self.tick()
        self.refresh(True)

    def refresh(self, force=False):
        if (self._closing or self._worker is not None or not self._network
                or not self.settings.city or not self.settings.country):
            return
        if not force and (not refresh_due(self.data) or time.monotonic() < self._next_attempt):
            return
        self._next_attempt = time.monotonic() + 600
        generation = self._generation
        worker = PrayerFetchThread(replace(self.settings, adjustments=dict(self.settings.adjustments)), self.data, self)
        self._worker = worker

        def result(data):
            if self._closing or generation != self._generation:
                return
            self.data = data
            self._error = ''
            try:
                self.store.save_cache(data)
            except OSError:
                self._error = 'Время получено, но кэш не сохранён'
            self.tick()

        def failed(message):
            if not self._closing and generation == self._generation:
                self._error = 'Обновление не удалось'
                self.footer.setToolTip(message)
                self.tick()

        def finished():
            self._worker = None
            worker.deleteLater()
            if self._closing:
                if self._on_shutdown:
                    self._on_shutdown()
            elif generation != self._generation:
                self.refresh(True)
            else:
                self.tick()

        worker.result.connect(result)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        current = today_schedule(self.data, now)
        upcoming = next_prayer(self.data, now)
        city = self.settings.city.split(',')[0] if self.settings.compact else self.settings.city
        self.location.setText('Астана' if city.casefold() == 'astana' else city[:24])
        self.location.setToolTip(f'{self.settings.city}, {self.settings.country}')
        self.hijri_label.setText(('☾  ' + current.get('hijri', '')) if current else '')
        if (self.settings.desktop_pinned and time.monotonic() >= self._pin_retry
                and not self._desktop.attached):
            self._apply_pin()
        if upcoming:
            when, name = upcoming
            seconds = max(0, int(when.timestamp() - now.timestamp()))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            genitive = {'Fajr': 'Фаджра', 'Dhuhr': 'Зухра', 'Asr': 'Асра', 'Maghrib': 'Магриба', 'Isha': 'Иша'}
            self.next_label.setText(f'До {genitive[name]}')
            tomorrow = when.astimezone(local_now(self.data, now).tzinfo).date() > local_now(self.data, now).date()
            self.at_label.setText(('Завтра в ' if tomorrow else 'Сегодня в ') + when.strftime('%H:%M'))
            self.countdown.setText(f'{hours:02}:{minutes:02}:{seconds:02}')
            self.hero_icon.set_prayer(name)
        else:
            self.next_label.setText('Нужно обновление' if self.settings.city else 'Выбрать город')
            self.at_label.setText('Нет актуального расписания')
            self.countdown.setText('—:—:—')
        self.summary_countdown.setText(self.countdown.text())
        for name, (tile, label) in self.tiles.items():
            label.setText(datetime.fromisoformat(current['times'][name]).strftime('%H:%M') if current else '—:—')
            active = bool(upcoming and upcoming[1] == name and current
                          and current['times'][name] == upcoming[0].isoformat())
            if tile.property('next') != active:
                tile.setProperty('next', active)
                tile.style().unpolish(tile)
                tile.style().polish(tile)
        if current:
            method = METHODS[self.settings.method].split(' · ')[0]
            footer = f'{MADHHABS[self.settings.madhhab]} · {method} · AlAdhan'
            self.footer.setToolTip(f"{current['date']} · {self.data['timezone']}\nХиджра (расчёт): {current.get('hijri', '')}\n"
                                   'Расчётные времена. Сверьте с местной мечетью.')
            if any(self.settings.adjustments.values()):
                footer += ' · с поправками'
        else:
            footer = 'Укажите город и страну в настройках' if not self.settings.city else 'Нет данных на сегодня'
        if self._error:
            footer += ' · ' + self._error + ('; сохранённые данные' if current else '')
        elif self._worker:
            footer += ' · обновление…'
        if self._pin_error:
            footer += ' · не закреплён'
            self.pin_button.setToolTip(self._pin_error)
        self.footer.setText(footer)
        if self._network:
            self.refresh()

    def shutdown(self, callback):
        self._closing = True
        self._timer.stop()
        self._on_shutdown = callback
        self._save_appearance()
        self._desktop.detach()
        self.hide()
        if self._worker:
            self._worker.requestInterruption()
        else:
            callback()

    def closeEvent(self, event):
        event.ignore()
        self.quit_requested.emit()
