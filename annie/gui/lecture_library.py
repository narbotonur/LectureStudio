"""Native lecture transcript editor, audio player, and local library."""
from bisect import bisect_left, bisect_right
from datetime import date
from pathlib import Path
import re

from PyQt5.QtCore import QPointF, QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (QActionGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QShortcut, QSizePolicy, QSlider, QTextEdit, QVBoxLayout, QWidget)

from annie.gui.design import MUTED, label, role
from annie.lecture_archive import library_entries, search_library


def timestamp(seconds):
    seconds = round(seconds * 1000)
    whole, ms = divmod(seconds, 1000)
    hours, rest = divmod(whole, 3600)
    minutes, sec = divmod(rest, 60)
    return f'{hours:02}:{minutes:02}:{sec:02}.{ms:03}'


def playback_time(seconds):
    clock = timestamp(seconds).split('.')[0]
    return clock[3:] if clock.startswith('00:') else clock


class LectureLibrary(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Lecture library')
        self.resize(640, 430)
        self.selected = None
        layout = QVBoxLayout(self)
        layout.addWidget(label('Lecture library', 'title'))
        self.query = QLineEdit(placeholderText='Search title, topic, tags, notes, or transcript')
        self.query.setAccessibleName('Search lectures')
        layout.addWidget(self.query)
        self.results = QListWidget()
        layout.addWidget(self.results)
        self.empty = label('')
        layout.addWidget(self.empty)
        self.entries = sorted(library_entries(root), key=lambda entry: (
            entry[1].get('lecture_date') or '', entry[0].stat().st_mtime), reverse=True)
        buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search_delay = QTimer(self, singleShot=True, interval=210)
        self.search_delay.timeout.connect(self._search)
        self.query.textChanged.connect(lambda: self.search_delay.start())
        self.results.itemActivated.connect(self._open)
        self._search()

    def _search(self):
        self.results.clear()
        for path, doc, start in search_library(self.entries, self.query.text()):
            detail = ' · '.join(part for part in (doc.get('course'), doc.get('lecture_date'),
                                timestamp(start) if start is not None else '') if part)
            title = doc.get('title') or doc['source_name']
            entry = QListWidgetItem(f'{title}\n{detail}' if detail else title)
            entry.setData(Qt.UserRole, (path, start))
            self.results.addItem(entry)
        self.empty.setText('No lectures match this search.' if not self.results.count() else '')
        if self.results.count():
            self.results.setCurrentRow(0)

    def _open(self, *_):
        item = self.results.currentItem()
        if item:
            self.selected = item.data(Qt.UserRole)
            self.accept()


class LectureDetails(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Lecture details')
        form = QFormLayout(self)
        self.fields = {}
        for key, title, value in (
            ('title','Title',document.get('title') or document['source_name']),
            ('course','Course',document.get('course', '')),
            ('lecture_date','Date (YYYY-MM-DD)',document.get('lecture_date') or ''),
            ('tags','Tags (comma separated)',', '.join(document.get('tags', []))),
        ):
            field = QLineEdit(value)
            self.fields[key] = field
            form.addRow(title, field)
        self.error = label('')
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self):
        values = {key: field.text().strip() for key, field in self.fields.items()}
        try:
            if values['lecture_date']:
                values['lecture_date'] = date.fromisoformat(values['lecture_date']).isoformat()
        except ValueError:
            self.error.setText('Enter a date in YYYY-MM-DD format.')
            return
        if not values['title']:
            self.error.setText('Enter a title.')
            return
        values['tags'] = [tag.strip() for tag in values['tags'].split(',') if tag.strip()]
        self.values = values
        self.accept()


class TranscriptTitle(QLabel):
    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._full_title = ''

    def set_title(self, title):
        self._full_title = title
        self.setToolTip(title)
        self.setAccessibleName(title)
        self._update_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self):
        self.setText(self.fontMetrics().elidedText(self._full_title, Qt.ElideRight, self.contentsRect().width()))


class TranscriptTools(QWidget):
    changed = pyqtSignal()
    analyze_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    export_requested = pyqtSignal()
    position_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self._audio = ''
        self.player = None
        self._pending_position = None
        self._play_after_seek = False
        self._preview_end = None
        self._playback_rate = 1.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        top = QHBoxLayout()
        self.title = role(TranscriptTitle(), 'lectureTitle')
        self.title.set_title('Transcript')
        top.addWidget(self.title, 1)
        relink = role(QPushButton('Link audio…'), 'quiet')
        relink.clicked.connect(self._relink)
        top.addWidget(relink)
        self.diarize = role(QPushButton('Label speakers…'), 'quiet')
        self.diarize.clicked.connect(self.analyze_requested.emit)
        top.addWidget(self.diarize)
        self.cancel = QPushButton('Cancel')
        self.cancel.clicked.connect(self.cancel_requested.emit)
        self.cancel.hide()
        top.addWidget(self.cancel)
        self.export = role(QPushButton('Export…'), 'quiet')
        self.export.clicked.connect(self.export_requested.emit)
        top.addWidget(self.export)
        layout.addLayout(top)
        transport = role(QFrame(), 'transport')
        playback = QHBoxLayout(transport)
        playback.setContentsMargins(8, 4, 10, 4)
        playback.setSpacing(10)
        self.play = QPushButton('Play')
        self.play.setObjectName('transcriptPlay')
        self.play.setMinimumWidth(64)
        self.play.clicked.connect(self._play)
        playback.addWidget(self.play)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setObjectName('transcriptSeek')
        self.seek.setAccessibleName('Playback position')
        playback.addWidget(self.seek, 1)
        self.position = label('00:00', 'studioStatus')
        playback.addWidget(self.position)
        self.speed = role(QPushButton('1×'), 'quiet')
        self.speed.setAccessibleName('Playback speed')
        self.speed.setToolTip('Change playback speed')
        rate_menu = QMenu(self.speed)
        self._speed_group = QActionGroup(self.speed)
        self._speed_group.setExclusive(True)
        for rate in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
            action = rate_menu.addAction(f'{rate:g}×')
            action.setCheckable(True)
            action.setChecked(rate == self._playback_rate)
            self._speed_group.addAction(action)
            action.triggered.connect(lambda checked=False, value=rate: self.set_playback_rate(value))
        self.speed.setMenu(rate_menu)
        playback.addWidget(self.speed)
        self.bookmarks = role(QPushButton('Bookmarks…'), 'quiet')
        playback.addWidget(self.bookmarks)
        self.find = role(QPushButton('Find…'), 'quiet')
        self.find.setToolTip('Find text in this transcript')
        playback.addWidget(self.find)
        layout.addWidget(transport)
        self.status = label('')
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.hide()
        layout.addWidget(self.status)
        self.relink = relink
        self.play.setEnabled(False)
        self.seek.setEnabled(False)
        self.speed.setEnabled(False)
        self.find.setEnabled(False)
        self.bookmarks.setEnabled(False)

    def _open_player(self):
        if self.player:
            return
        try:
            from PyQt5.QtMultimedia import QMediaPlayer
            self.player = QMediaPlayer(self)
            self.player.setNotifyInterval(100)
            self.player.durationChanged.connect(self._duration)
            self.player.seekableChanged.connect(lambda enabled: self._seek_pending() if enabled else None)
            self.player.positionChanged.connect(self._position)
            self.player.playbackRateChanged.connect(self._rate_changed)
            self.player.mediaStatusChanged.connect(self._restore_rate)
            self.player.stateChanged.connect(lambda state: self.play.setText(
                'Pause' if state == QMediaPlayer.PlayingState else 'Play'))
            self.player.error.connect(lambda _: self.set_status(self.player.errorString()))
            self.seek.sliderMoved.connect(self._manual_seek)
        except (ImportError, RuntimeError, OSError):
            self.set_status('Audio playback is unavailable in this Qt installation.')

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def display(self, document):
        self.document = document
        self.title.set_title(document.get('title') or document.get('source_name') or 'Transcript')
        path = document.get('audio_path', '')
        available = bool(path and Path(path).is_file())
        if available:
            self._open_player()
        self.play.setEnabled(available and self.player is not None)
        self.seek.setEnabled(self.play.isEnabled())
        self.speed.setEnabled(self.play.isEnabled())
        self.diarize.setEnabled(available and bool(document.get('segments')))
        if path != self._audio:
            self._pending_position = None
            self._play_after_seek = False
            self._preview_end = None
            self._audio = path
            if self.player:
                from PyQt5.QtMultimedia import QMediaContent
                self.player.stop()
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(Path(path).resolve()))) if available else QMediaContent())
        if self.player:
            self.set_status('' if available else 'Link the recording to play or label speakers.')
        if document.get('segments') and not document.get('complete') and available:
            self.set_status('Partial transcript · the linked audio is available.')

    def _relink(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Link lecture audio', '',
                                             'Audio or video (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.webm *.mp4);;All files (*)')
        if path and self.document is not None:
            self.document['audio_path'] = path
            self.display(self.document)
            self.changed.emit()

    def _play(self):
        if self.player and self.play.isEnabled():
            if self._pending_position is not None:
                self._play_after_seek = True
                self._seek_pending()
                return
            self._preview_end = None
            if self.player.state() == self.player.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def play_at(self, seconds, end=None):
        self._seek_to(seconds, play=True, end=end)

    def jump_to(self, seconds):
        self._seek_to(seconds, play=False)

    def _seek_to(self, seconds, *, play, end=None):
        if self.player and self.play.isEnabled():
            self._preview_end = round(end * 1000) if end is not None else None
            self._pending_position = round(seconds * 1000)
            self._play_after_seek = play
            self._seek_pending()

    def _duration(self, duration):
        self.seek.setRange(0, min(duration, 2**31-1))
        self._update_clock(self.player.position())
        self._seek_pending()

    def _seek_pending(self):
        if self._pending_position is not None and self.player.isSeekable():
            position = self._pending_position
            self._pending_position = None
            self.player.setPosition(position)
            if self._play_after_seek:
                self.player.play()

    def _manual_seek(self, milliseconds):
        self._pending_position = None
        self._preview_end = None
        self.player.setPosition(milliseconds)

    def _position(self, milliseconds):
        if self._preview_end is not None and self._pending_position is None and milliseconds >= self._preview_end:
            self._preview_end = None
            self.player.pause()
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self._update_clock(milliseconds)
        self.position_changed.emit(milliseconds / 1000)

    def current_time(self):
        return self.player.position() / 1000 if self.player and self.play.isEnabled() else None

    def set_playback_rate(self, rate):
        if self.player and self.play.isEnabled():
            self._playback_rate = rate
            self.player.setPlaybackRate(rate)
            self._rate_changed(self.player.playbackRate())

    def _rate_changed(self, rate):
        self.speed.setText(f'{rate:g}×')
        for action in self._speed_group.actions():
            action.setChecked(action.text() == self.speed.text())

    def _restore_rate(self, status):
        if status == self.player.LoadedMedia and self.player.playbackRate() != self._playback_rate:
            self.player.setPlaybackRate(self._playback_rate)

    def _update_clock(self, milliseconds):
        current = playback_time(milliseconds / 1000)
        duration = self.player.duration()
        self.position.setText(f'{current} / {playback_time(duration / 1000)}' if duration > 0 else current)

    def choose_label(self, current=''):
        name, ok = QInputDialog.getText(self, 'Speaker label', 'Name or label for this speaker', text=current)
        return name.strip() if ok else ''


class TranscriptNavigator(QWidget):
    """Find speech in the current view and track audio without moving its caret."""
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self._passages = []
        self._times = []
        self._end_limits = []
        self._hits = []
        self._match = None
        self._active = None
        self._seconds = None
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Find in visible transcript…')
        self.query.setAccessibleName('Find in transcript')
        self.query.setMaxLength(180)
        box.addWidget(self.query, 1)
        self.count = label('', 'studioStatus')
        box.addWidget(self.count)
        self.previous = QPushButton('Previous')
        self.previous.clicked.connect(lambda: self.move_match(-1))
        self.next = QPushButton('Next')
        self.next.clicked.connect(lambda: self.move_match())
        box.addWidget(self.previous)
        box.addWidget(self.next)
        close = role(QPushButton('Close'), 'quiet')
        close.clicked.connect(lambda: self.close_search(focus_transcript=True))
        box.addWidget(close)
        self._timer = QTimer(self, singleShot=True, interval=100)
        self._timer.timeout.connect(self._find)
        self.query.textChanged.connect(self._queue_search)
        self.query.returnPressed.connect(self.move_match)
        self._esc = QShortcut('Escape', self, context=Qt.WidgetWithChildrenShortcut,
                              activated=lambda: self.close_search(focus_transcript=True))
        self._display_count()
        self.hide()

    def open_search(self):
        self.show()
        self.query.setFocus()
        self.query.selectAll()

    def close_search(self, *, focus_transcript=False):
        self.hide()
        self.query.clear()
        if focus_transcript:
            self.view.setFocus()

    def set_passages(self, passages):
        previous = self._hits[self._match][0] if self._match is not None else None
        self._passages = sorted(passages, key=lambda span: span[2])
        self._times = []
        self._end_limits = []
        for _, _, start, end, _, _ in self._passages:
            self._times.append(start)
            self._end_limits.append(max(end, self._end_limits[-1] if self._end_limits else 0))
        self._active = None
        self._find(reveal=previous is not None, from_position=previous)
        self.track_playback(self._seconds)

    def _queue_search(self):
        if not self.query.text().strip():
            self._find()
        else:
            self._timer.start()

    def _find(self, *, reveal=True, from_position=None):
        self._timer.stop()
        self._hits = []
        self._match = None
        words = self.query.text().split()
        if words:
            pattern = re.compile(r'\s+'.join(map(re.escape, words)), re.IGNORECASE)
            for _, _, _, _, text_start, text in self._passages:
                previous = 0
                position = text_start
                for hit in pattern.finditer(text):
                    left, right = hit.span()
                    position += len(text[previous:left].encode('utf-16-le', 'surrogatepass')) // 2
                    end = position + len(text[left:right].encode('utf-16-le', 'surrogatepass')) // 2
                    self._hits.append((position, end))
                    previous, position = right, end
        if self._hits:
            self._hits.sort()
            caret = self.view.textCursor().selectionStart() if from_position is None else from_position
            self._match = bisect_left(self._hits, (caret, 0)) % len(self._hits)
            if reveal:
                self._reveal_match()
        self._display_count()
        self._paint_selections()

    def move_match(self, step=1):
        if self._timer.isActive():
            self._find()
            return
        if self._hits:
            self._match = (self._match + step) % len(self._hits)
            self._reveal_match()
            self._display_count()
            self._paint_selections()

    def _reveal_match(self):
        cursor = self._select(self._hits[self._match])
        cursor.setPosition(cursor.selectionStart())
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def _display_count(self):
        found = bool(self._hits)
        self.count.setText(f'{self._match + 1} of {len(self._hits)}' if found else
                           ('No matches' if self.query.text().strip() else ''))
        self.previous.setEnabled(found)
        self.next.setEnabled(found)

    def track_playback(self, seconds):
        self._seconds = seconds
        current = None
        if seconds is not None:
            index = bisect_right(self._times, seconds) - 1
            while index >= 0 and self._end_limits[index] > seconds:
                begin, finish, _, end, _, _ = self._passages[index]
                if seconds < end:
                    current = (begin, finish)
                    break
                index -= 1
        if self._active != current:
            self._active = current
            self._paint_selections()

    def _select(self, span):
        cursor = QTextCursor(self.view.document())
        cursor.setPosition(span[0])
        cursor.setPosition(span[1], QTextCursor.KeepAnchor)
        return cursor

    def _paint_selections(self):
        selections = []
        if self._active:
            playing = QTextEdit.ExtraSelection()
            playing.cursor = self._select(self._active)
            playing.format.setProperty(QTextFormat.FullWidthSelection, True)
            playing.format.setBackground(QColor('#29463F'))
            selections.append(playing)
        if self._match is not None:
            found = QTextEdit.ExtraSelection()
            found.cursor = self._select(self._hits[self._match])
            found.format.setBackground(QColor('#E4C07B'))
            found.format.setForeground(QColor('#1A201E'))
            selections.append(found)
        self.view.setExtraSelections(selections)


class SpeakerFilter(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(MUTED), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        center_x = self.width() - 15
        center_y = self.height() / 2
        painter.drawPolyline(QPolygonF([QPointF(center_x - 4, center_y - 2),
                                       QPointF(center_x, center_y + 2),
                                       QPointF(center_x + 4, center_y - 2)]))


class TranscriptBookmarks(QDialog):
    def __init__(self, bookmarks, playhead, passage, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Lecture bookmarks')
        self.resize(470, 335)
        self.bookmarks = sorted((dict(mark) for mark in bookmarks), key=lambda mark: mark['start'])
        self.jump_time = None
        layout = QVBoxLayout(self)
        layout.addWidget(label('Lecture bookmarks', 'section'))
        self.items = QListWidget()
        self.items.setAccessibleName('Saved lecture bookmarks')
        self.items.itemDoubleClicked.connect(lambda _: self._jump())
        layout.addWidget(self.items, 1)
        self.empty = label('Add a bookmark at the audio position or at a selected passage.')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        add = QHBoxLayout()
        for text, seconds in (('Playhead', playhead), ('Passage', passage)):
            if seconds is not None:
                action = QPushButton(f'Add {text.lower()} · {playback_time(seconds)}…')
                action.clicked.connect(lambda checked=False, at=seconds: self._add(at))
                add.addWidget(action)
        add.addStretch(1)
        layout.addLayout(add)
        controls = QHBoxLayout()
        self.rename = QPushButton('Rename…')
        self.rename.clicked.connect(self._rename)
        controls.addWidget(self.rename)
        self.remove = QPushButton('Remove')
        self.remove.clicked.connect(self._remove)
        controls.addWidget(self.remove)
        controls.addStretch(1)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        controls.addWidget(cancel)
        done = QPushButton('Done')
        done.clicked.connect(self.accept)
        controls.addWidget(done)
        self.jump = role(QPushButton('Jump'), 'primary')
        self.jump.setDefault(True)
        self.jump.clicked.connect(self._jump)
        controls.addWidget(self.jump)
        layout.addLayout(controls)
        self.items.currentRowChanged.connect(self._update_actions)
        self._refresh()

    def _refresh(self, index=0):
        self.items.clear()
        for mark in self.bookmarks:
            self.items.addItem(f"{playback_time(mark['start'])}   {mark['title']}")
        self.empty.setVisible(not self.bookmarks)
        self.items.setCurrentRow(min(index, len(self.bookmarks) - 1))
        self._update_actions()

    def _update_actions(self):
        selected = self.items.currentRow() >= 0
        for button in (self.rename, self.remove, self.jump):
            button.setEnabled(selected)

    def _add(self, seconds):
        title, approved = QInputDialog.getText(self, 'New bookmark', 'Name',
                                               text=f'Bookmark at {playback_time(seconds)}')
        if approved and title.strip():
            index = bisect_right([mark['start'] for mark in self.bookmarks], seconds)
            self.bookmarks.insert(index, {'start': seconds, 'title': title.strip()[:120]})
            self._refresh(index)

    def _rename(self):
        index = self.items.currentRow()
        mark = self.bookmarks[index]
        title, approved = QInputDialog.getText(self, 'Rename bookmark', 'Name', text=mark['title'])
        if approved and title.strip():
            mark['title'] = title.strip()[:120]
            self._refresh(index)

    def _remove(self):
        index = self.items.currentRow()
        self.bookmarks.pop(index)
        self._refresh(index)

    def _jump(self):
        index = self.items.currentRow()
        if index >= 0:
            self.jump_time = self.bookmarks[index]['start']
            self.accept()


class SpeakerPanel(QWidget):
    filter_changed = pyqtSignal()
    sample_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    assign_requested = pyqtSignal()
    edit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.filters = role(SpeakerFilter(), 'speakerFilter')
        self.filters.setAccessibleName('Speaker and review filter')
        self.filters.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.filters.setMinimumContentsLength(12)
        self.filters.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.filters.currentIndexChanged.connect(self._change_filter)
        layout.addWidget(self.filters, 1)
        self.sample = role(QPushButton('Voice sample'), 'quiet')
        self.sample.clicked.connect(lambda: self.sample_requested.emit(self.speaker()))
        self.manage = role(QPushButton('Speaker'), 'quiet')
        self.manage.setToolTip('Rename or merge the selected speaker')
        speaker_menu = QMenu(self.manage)
        self.rename = speaker_menu.addAction('Rename speaker…', lambda: self.rename_requested.emit(self.speaker()))
        self.merge = speaker_menu.addAction('Merge speaker…', lambda: self.merge_requested.emit(self.speaker()))
        self.manage.setMenu(speaker_menu)
        self.assign = role(QPushButton('Assign…'), 'quiet')
        self.assign.setToolTip('Assign the current or selected transcript passages')
        self.assign.clicked.connect(self.assign_requested.emit)
        self.edit = QPushButton('Edit text…')
        self.edit.setToolTip('Correct the selected passage (F2)')
        self.edit.clicked.connect(self.edit_requested.emit)
        for button in (self.sample, self.manage, self.assign, self.edit):
            layout.addWidget(button)
        self.has_audio = False
        self.editable = True
        self.speaker_count = 0
        self.hide()

    def selection(self):
        value = self.filters.currentData() or 'all'
        kind, _, identity = value.partition(':')
        return kind, identity

    def speaker(self):
        kind, identity = self.selection()
        return identity if kind == 'speaker' else ''

    def display(self, counts, names, total, uncertain, overlap, *, has_audio, editable):
        old = self.filters.currentData() or 'all'
        blocked = self.filters.blockSignals(True)
        self.filters.clear()
        self.filters.addItem(f'All passages ({total})', 'all')
        for speaker, count in counts.items():
            name = names.get(speaker, speaker)
            self.filters.addItem(f'{name} ({count})', f'speaker:{speaker}')
        self.filters.addItem(f'Unassigned ({uncertain})', 'uncertain')
        self.filters.addItem(f'Overlapping speech ({overlap})', 'overlap')
        self.filters.setCurrentIndex(max(0, self.filters.findData(old)))
        self.filters.blockSignals(blocked)
        self.has_audio = has_audio
        self.editable = editable
        self.speaker_count = len(counts)
        self.setVisible(bool(total))
        self._sync_buttons()

    def _change_filter(self):
        self._sync_buttons()
        self.filter_changed.emit()

    def _sync_buttons(self):
        selected = bool(self.speaker())
        self.filters.setToolTip(self.filters.currentText())
        self.sample.setEnabled(selected and self.has_audio)
        self.manage.setEnabled(selected and self.editable)
        self.rename.setEnabled(selected and self.editable)
        self.merge.setEnabled(selected and self.editable and self.speaker_count > 1)
        self.assign.setEnabled(self.editable)
        self.edit.setEnabled(self.editable)
