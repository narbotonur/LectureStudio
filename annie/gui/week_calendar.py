"""Week calendar: a single painted time grid, cached data and background loading."""
import datetime as dt
import time
import zlib
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QRectF, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QAbstractScrollArea, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget
from annie.gui.design import UI_FONT

TZ = dt.timezone(dt.timedelta(hours=5))
COLORS = ('#344E66', '#51426B', '#355744', '#675033', '#633F4D', '#34595E')


@dataclass
class CalendarBlock:
    event: dict
    day: int
    start: float
    end: float
    all_day: bool = False
    lane: int = 0
    lanes: int = 1


def build_blocks(events, monday):
    """Clip events to each local day and allocate lanes for overlapping times."""
    blocks = []
    for event in events:
        if event.get('status') == 'cancelled':
            continue
        try:
            start_data, end_data = event.get('start', {}), event.get('end', {})
            all_day = 'dateTime' not in start_data
            if all_day:
                start = dt.datetime.combine(dt.date.fromisoformat(start_data['date']), dt.time(), TZ)
                end = dt.datetime.combine(dt.date.fromisoformat(end_data.get('date', '')), dt.time(), TZ)
            else:
                start = dt.datetime.fromisoformat(start_data['dateTime'].replace('Z', '+00:00'))
                end = dt.datetime.fromisoformat(end_data['dateTime'].replace('Z', '+00:00'))
                start = start.replace(tzinfo=TZ) if start.tzinfo is None else start.astimezone(TZ)
                end = end.replace(tzinfo=TZ) if end.tzinfo is None else end.astimezone(TZ)
            if end <= start:
                continue
            for day in range(7):
                midnight = dt.datetime.combine(monday + dt.timedelta(days=day), dt.time(), TZ)
                tomorrow = midnight + dt.timedelta(days=1)
                if start < tomorrow and end > midnight:
                    a = max(0, (start - midnight).total_seconds() / 60)
                    b = min(1440, (end - midnight).total_seconds() / 60)
                    blocks.append(CalendarBlock(event, day, a, b, all_day))
        except (ValueError, KeyError, TypeError):
            continue

    for day in range(7):
        timed = sorted((b for b in blocks if b.day == day and not b.all_day), key=lambda b: (b.start, b.end))
        group, ends = [], []

        def finalize():
            for item in group:
                item.lanes = len(ends)

        for block in timed:
            if group and block.start >= max(ends):
                finalize()
                group, ends = [], []
            lane = next((i for i, end in enumerate(ends) if end <= block.start), len(ends))
            if lane == len(ends):
                ends.append(block.end)
            else:
                ends[lane] = block.end
            block.lane = lane
            group.append(block)
        finalize()
    return blocks


class WeekGrid(QAbstractScrollArea):
    selected = pyqtSignal(str)
    HOUR = 48
    GUTTER = 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self.monday = dt.datetime.now(TZ).date()
        self.monday -= dt.timedelta(days=self.monday.weekday())
        self.blocks = []
        self._hits = []
        self._all_day_rows = 0
        self.setFrameShape(self.NoFrame)
        self.setAccessibleName('Weekly calendar, seven days with hourly time grid')
        self.viewport().setMouseTracking(True)
        # Give native wheel scrolling a useful step instead of the default 1 px.
        self.verticalScrollBar().setSingleStep(24)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self._clock = QTimer(self)
        self._clock.setInterval(60000)
        self._clock.timeout.connect(self.viewport().update)

    def set_events(self, events, monday):
        self.monday = monday
        self.blocks = build_blocks(events, monday)
        self._all_day_rows = max((sum(b.all_day and b.day == day for b in self.blocks) for day in range(7)), default=0)
        self._ranges()
        self.viewport().update()

    def _header_height(self):
        return 62 + self._all_day_rows * 24

    def _ranges(self):
        self.day_width = max(118, (self.viewport().width() - self.GUTTER) / 7)
        self.horizontalScrollBar().setRange(0, max(0, int(self.GUTTER + 7 * self.day_width - self.viewport().width())))
        self.verticalScrollBar().setRange(0, max(0, int(24 * self.HOUR - self.viewport().height() + self._header_height())))
        self.verticalScrollBar().setPageStep(max(1, self.viewport().height() - self._header_height()))
        self.horizontalScrollBar().setPageStep(self.viewport().width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ranges()

    def wheelEvent(self, event):
        # Trackpads provide pixel deltas including momentum. Preserve them;
        # treating these as mouse-wheel ticks makes Mac scrolling jumpy/slow.
        pixels = event.pixelDelta()
        if not pixels.isNull():
            vertical, horizontal = self.verticalScrollBar(), self.horizontalScrollBar()
            vertical.setValue(vertical.value() - pixels.y())
            horizontal.setValue(horizontal.value() - pixels.x())
            event.accept()
            return
        super().wheelEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._clock.start()

    def hideEvent(self, event):
        self._clock.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.viewport().width(), self.viewport().height()
        header = self._header_height()
        offset = self.verticalScrollBar().value()
        sx = self.horizontalScrollBar().value()
        now = dt.datetime.now(TZ)
        p.fillRect(self.viewport().rect(), QColor('#141813'))
        p.setFont(QFont(UI_FONT, 9))
        for day in range(7):
            x = self.GUTTER + day * self.day_width - sx
            if self.monday + dt.timedelta(days=day) == now.date():
                p.fillRect(QRectF(x, header, self.day_width, h - header), QColor('#1B2419'))
            p.setPen(QColor('#30382C'))
            p.drawLine(int(x), header, int(x), h)
        for hour in range(25):
            y = header + hour * self.HOUR - offset
            if y < header or y > h:
                continue
            p.setPen(QColor('#30382C'))
            p.drawLine(self.GUTTER, int(y), w, int(y))
            p.setPen(QColor('#20271D'))
            p.drawLine(self.GUTTER, int(y + self.HOUR / 2), w, int(y + self.HOUR / 2))

        self._hits = []
        p.save()
        p.setClipRect(QRectF(self.GUTTER, header, w - self.GUTTER, max(0, h - header)))
        for block in self.blocks:
            if block.all_day:
                continue
            x = self.GUTTER + block.day * self.day_width - sx + 3
            lane_width = (self.day_width - 6) / block.lanes
            y = header + block.start / 60 * self.HOUR - offset
            height = max(4, (block.end - block.start) / 60 * self.HOUR - 2)
            rect = QRectF(x + block.lane * lane_width, y, lane_width - 2, height)
            if rect.bottom() >= header and rect.top() <= h:
                self._draw_block(p, rect, block)
        day = (now.date() - self.monday).days
        if 0 <= day < 7:
            y = header + (now.hour + now.minute / 60) * self.HOUR - offset
            x = self.GUTTER + day * self.day_width - sx
            p.setPen(QPen(QColor('#F18B80'), 2))
            p.drawLine(int(x), int(y), int(x + self.day_width), int(y))
        p.restore()

        # Fixed day header and time gutter stay visible while scrolling.
        p.fillRect(QRectF(0, 0, w, header), QColor('#1B2118'))
        p.fillRect(QRectF(0, header, self.GUTTER, h - header), QColor('#141813'))
        p.setPen(QColor('#919F86'))
        p.setFont(QFont(UI_FONT, 8))
        for hour in range(24):
            y = header + hour * self.HOUR - offset
            if header <= y <= h:
                p.drawText(QRectF(0, y + 3, self.GUTTER - 6, 18), Qt.AlignRight, f'{hour:02}:00')
        p.save()
        p.setClipRect(QRectF(self.GUTTER, 0, w - self.GUTTER, header))
        counts = [0] * 7
        for day in range(7):
            date = self.monday + dt.timedelta(days=day)
            x = self.GUTTER + day * self.day_width - sx
            p.setPen(QColor('#C5ED87' if date == now.date() else '#D9E1D1'))
            p.setFont(QFont(UI_FONT, 9, QFont.DemiBold))
            p.drawText(QRectF(x, 8, self.day_width, 20), Qt.AlignCenter, date.strftime('%a'))
            p.setFont(QFont(UI_FONT, 14, QFont.DemiBold))
            p.drawText(QRectF(x, 28, self.day_width, 26), Qt.AlignCenter, str(date.day))
        for block in self.blocks:
            if block.all_day:
                rect = QRectF(self.GUTTER + block.day * self.day_width - sx + 3,
                              60 + counts[block.day] * 24, self.day_width - 6, 21)
                self._draw_block(p, rect, block)
                counts[block.day] += 1
        p.restore()

    def _draw_block(self, painter, rect, block):
        title = str(block.event.get('summary') or 'Untitled')
        key = ' '.join(title.split()[:2])
        color = COLORS[zlib.crc32(key.encode()) % len(COLORS)]
        painter.setPen(QPen(QColor(color).lighter(140), 1))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(rect, 5, 5)
        painter.save()
        painter.setClipRect(rect.adjusted(5, 2, -4, -2), Qt.IntersectClip)
        painter.setPen(QColor('#F2F5EF'))
        painter.setFont(QFont(UI_FONT, 9, QFont.DemiBold))
        text = title
        if not block.all_day and rect.height() > 42:
            start = f'{int(block.start)//60:02}:{int(block.start)%60:02}'
            end = f'{int(block.end)//60:02}:{int(block.end)%60:02}'
            text = f'{start}–{end}\n{title}'
            if rect.height() > 90 and block.event.get('location'):
                text += '\n' + block.event['location']
        painter.drawText(rect.adjusted(6, 3, -4, -2), Qt.AlignTop | Qt.TextWordWrap, text)
        painter.restore()
        self._hits.append((rect, block))

    def _hit(self, pos):
        for rect, block in reversed(self._hits):
            if rect.contains(pos) and pos.x() >= self.GUTTER:
                if block.all_day or pos.y() >= self._header_height():
                    return block
        return None

    def mouseMoveEvent(self, event):
        block = self._hit(event.pos())
        self.viewport().setCursor(Qt.PointingHandCursor if block else Qt.ArrowCursor)
        if block:
            ev = block.event
            text = ev.get('summary', 'Untitled') + '\n' + str(ev.get('start', {}).get('dateTime') or 'All day')
            if ev.get('location'):
                text += '\n' + ev['location']
            if ev.get('extendedProperties', {}).get('private', {}).get('annieStudySession'):
                text += '\n' + ev.get('description', '')
            QToolTip.showText(event.globalPos(), text, self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        block = self._hit(event.pos())
        if event.button() == Qt.LeftButton and block:
            self.selected.emit(block.event.get('summary', 'Class'))


class WeekFetch(QThread):
    loaded = pyqtSignal(object, object, str)

    def __init__(self, monday, parent=None):
        super().__init__(parent)
        self.monday = monday

    def run(self):
        try:
            from annie.calendar_service import list_events
            start = dt.datetime.combine(self.monday, dt.time(), TZ)
            events = list_events(start, start + dt.timedelta(days=7), interactive=False,
                                 raise_errors=True, paginate=True)
            self.loaded.emit(self.monday, events, '')
        except Exception:
            self.loaded.emit(self.monday, [], 'Could not refresh calendar. Check your connection and try again.')


class EliteTimetableView(QWidget):
    select_class = pyqtSignal(str)
    events_loaded = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.monday = dt.datetime.now(TZ).date()
        self.monday -= dt.timedelta(days=self.monday.weekday())
        self._cache = {}
        self._worker = None
        self._pending = None
        self._study_store = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        nav = QHBoxLayout()
        self.heading = QLabel()
        nav.addWidget(self.heading, 1)
        for text, callback in (('‹', lambda: self._change_week(-1)),
                               ('Today', self._today), ('›', lambda: self._change_week(1)),
                               ('↻', lambda: self._refresh(force=True))):
            button = QPushButton(text)
            button.clicked.connect(callback)
            button.setToolTip({'‹': 'Previous week', '›': 'Next week', '↻': 'Refresh calendar'}.get(text, text))
            nav.addWidget(button)
        layout.addLayout(nav)
        self.status = QLabel('Open Schedule to load your calendar.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.grid = WeekGrid()
        self.grid.selected.connect(self.select_class)
        layout.addWidget(self.grid, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel('UTC+05 · Click a class to use it in Studio'), 1)
        add = QPushButton('+ Add class')
        add.clicked.connect(self._open_add)
        footer.addWidget(add)
        calendar = QPushButton('Calendar ↗')
        calendar.clicked.connect(self._open_calendar)
        footer.addWidget(calendar)
        layout.addLayout(footer)
        self._update_heading()
        QTimer.singleShot(0, lambda: self.grid.verticalScrollBar().setValue(8 * self.grid.HOUR))

    def _update_heading(self):
        end = self.monday + dt.timedelta(days=6)
        self.heading.setText(f'{self.monday:%d %b} – {end:%d %b %Y}')

    def set_study_store(self, store):
        self._study_store = store
        self.reload_local_sessions()

    def reload_local_sessions(self):
        """Merge durable sessions with the cached week, without another network call."""
        events = list(self._cache.get(self.monday, (0, []))[1])
        if self._study_store is not None:
            local = self._study_store.calendar_events(self.monday, self.monday + dt.timedelta(days=7))
            local_ids = {event['id'] for event in local}
            session_ids = {event['extendedProperties']['private']['annieStudySession'] for event in local}
            events = [event for event in events if event.get('id') not in local_ids and
                      event.get('extendedProperties', {}).get('private', {}).get('annieStudySession') not in session_ids]
            events.extend(local)
        self.grid.set_events(events, self.monday)
        return events

    def _change_week(self, direction):
        self.monday += dt.timedelta(days=7 * direction)
        self._update_heading()
        self._refresh()

    def _today(self):
        today = dt.datetime.now(TZ).date()
        self.monday = today - dt.timedelta(days=today.weekday())
        self._update_heading()
        self._refresh()
        self.grid.verticalScrollBar().setValue(8 * self.grid.HOUR)

    def _refresh(self, force=False):
        from annie.calendar_service import is_connected
        events = self.reload_local_sessions()
        if not is_connected():
            self.status.setText('Connect your calendar to see classes here. Study sessions remain available locally.')
            return
        cached = self._cache.get(self.monday)
        if cached:
            self.status.setText('No events this week.' if not events else '')
            if not force and time.monotonic() - cached[0] < 300:
                return
        if self._worker is not None:
            if self._worker.monday != self.monday:
                self._pending = self.monday
            return
        self.status.setText('Refreshing calendar…')
        self._worker = WeekFetch(self.monday, self)
        self._worker.loaded.connect(self._loaded)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _loaded(self, monday, events, error):
        if not error:
            self._cache[monday] = (time.monotonic(), events)
            if len(self._cache) > 8:
                oldest = min(self._cache, key=lambda key: self._cache[key][0])
                del self._cache[oldest]
            if monday <= dt.datetime.now(TZ).date() < monday + dt.timedelta(days=7):
                self.events_loaded.emit(events)
        if monday != self.monday:
            return
        if error:
            self.status.setText(error)
        else:
            events = self.reload_local_sessions()
            self.status.setText('No events this week.' if not events else '')

    def _finished(self):
        worker = self._worker
        self._worker = None
        if worker:
            worker.deleteLater()
        if self._pending is not None:
            self._pending = None
            self._refresh()

    def has_running_job(self):
        return self._worker is not None

    def _open_add(self):
        from annie.gui.meeting_window import EliteAddClassModal
        dialog = EliteAddClassModal(self, default_date=self.monday)
        dialog.event_added.connect(lambda _: self._refresh(force=True))
        dialog.exec_()

    @staticmethod
    def _open_calendar():
        import webbrowser
        webbrowser.open('https://calendar.google.com')
