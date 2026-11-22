"""Native controls for checking the selected input and preparing local models."""
from importlib.util import find_spec
from pathlib import Path
from queue import Empty
from threading import Event
from tempfile import TemporaryDirectory

from PyQt5.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QProgressBar,
                             QPushButton, QTabWidget, QVBoxLayout, QWidget)

from annie.audio_setup import MIC_TEST_SECONDS, SPEAKER_DOWNLOAD_BYTES, SetupCancelled, install_speaker_models
from annie.gui.design import ACCENT, BACKGROUND, BORDER, RAISED, SURFACE, apply_theme, label, role


class SetupTask(QThread):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.cancel = Event()

    def run(self):
        try:
            result = self.action(self.cancel, self.progress.emit)
            self.result.emit(result)
        except SetupCancelled:
            self.error.emit('Cancelled.')
        except Exception as exc:
            self.error.emit(str(exc) or 'Setup could not finish. Try again.')


def _run_audio_worker(mode, cancel, report, **options):
    from annie.whisper_service import get_whisper_service
    service = get_whisper_service()
    if cancel.is_set():
        raise SetupCancelled
    session, messages = service.start(mode=mode, **options)
    aborted = False
    error = 'Whisper setup failed.'
    try:
        while True:
            if cancel.is_set() and not aborted:
                if mode == 'prepare':
                    service.abort_preparation(session)
                else:
                    service.stop(session)
                aborted = True
            try:
                message = messages.get(timeout=0.2)
            except Empty:
                continue
            kind = message['type']
            if kind in ('process_exit', 'session_done'):
                if aborted or message.get('cancelled') or cancel.is_set():
                    raise SetupCancelled
                if kind == 'process_exit' or message.get('had_error'):
                    raise RuntimeError(message.get('text') or error)
                return message.get('result')
            if kind == 'status':
                report(message['text'])
            elif kind == 'input_test_progress':
                report((message['elapsed'], message['peak']))
            elif kind == 'error':
                error = message.get('text', 'Whisper setup failed.')
    finally:
        service.release(session)


class AudioSetup(QDialog):
    speaker_model_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle('Audio & local models')
        self.setWindowModality(Qt.WindowModal)
        self.resize(530, 375)
        self.task = None
        self.player = None
        self.sample_dir = None
        self.has_sample = False
        self.whisper_ready = False
        self.whisper_checked = False
        self.model = None
        self.device = None
        self.speaker_model = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.input_page = QWidget()
        self.models_page = QWidget()
        self.tabs.addTab(self.input_page, 'Input test')
        self.tabs.addTab(self.models_page, 'Local models')
        self.tabs.currentChanged.connect(self._model_tab_selected)

        audio = QVBoxLayout(self.input_page)
        audio.addWidget(label('Test the selected audio source', 'section'))
        self.source = label('')
        self.source.setWordWrap(True)
        audio.addWidget(self.source)
        self.test_status = label('Capture a five-second sample and play it back before your lecture.')
        self.test_status.setWordWrap(True)
        audio.addWidget(self.test_status)
        self.input_level = QProgressBar()
        self.input_level.setRange(0, 100)
        self.input_level.setValue(0)
        self.input_level.setTextVisible(False)
        self.input_level.setAccessibleName('Input peak level')
        audio.addWidget(self.input_level)
        input_actions = QHBoxLayout()
        self.record = role(QPushButton('Record test'), 'primary')
        self.record.clicked.connect(self._test_input)
        self.play = QPushButton('Play sample')
        self.play.clicked.connect(self._play_sample)
        input_actions.addWidget(self.record)
        input_actions.addWidget(self.play)
        input_actions.addStretch(1)
        audio.addLayout(input_actions)
        audio.addStretch(1)

        models = QVBoxLayout(self.models_page)
        models.addWidget(label('Whisper · transcription', 'section'))
        self.whisper_status = label('')
        self.whisper_status.setWordWrap(True)
        models.addWidget(self.whisper_status)
        self.whisper_button = QPushButton('Prepare Whisper')
        self.whisper_button.clicked.connect(lambda: self._check_whisper(True))
        models.addWidget(self.whisper_button, 0, Qt.AlignLeft)
        models.addSpacing(8)
        models.addWidget(label('Speaker identification', 'section'))
        self.speaker_status = label('')
        self.speaker_status.setWordWrap(True)
        models.addWidget(self.speaker_status)
        model_actions = QHBoxLayout()
        self.install = QPushButton(f'Download {SPEAKER_DOWNLOAD_BYTES / 1_000_000:.1f} MB')
        self.install.clicked.connect(self._install_speakers)
        self.browse = QPushButton('Use a model folder…')
        self.browse.clicked.connect(self._browse_models)
        model_actions.addWidget(self.install)
        model_actions.addWidget(self.browse)
        model_actions.addStretch(1)
        models.addLayout(model_actions)
        self.model_progress = QProgressBar()
        self.model_progress.setTextVisible(False)
        self.model_progress.hide()
        self.model_progress.setAccessibleName('Model preparation progress')
        models.addWidget(self.model_progress)
        models.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = QPushButton('Cancel task')
        self.cancel.clicked.connect(self.cancel_task)
        buttons.addWidget(self.cancel)
        close = QPushButton('Close')
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        apply_theme(self)
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BACKGROUND}; border-radius: 8px; }}
        """)
        self.tabs.tabBar().setStyleSheet(f"""
            QTabBar::tab {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 7px 13px;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }}
            QTabBar::tab:selected {{ background: {RAISED}; color: {ACCENT}; }}
        """)
        progress_style = f"""
            QProgressBar {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;
                min-height: 9px; max-height: 9px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
        """
        self.input_level.setStyleSheet(progress_style)
        self.model_progress.setStyleSheet(progress_style)
        self._refresh_buttons()

    def configure(self, device, source, model, speaker_model, *, show_models=False):
        from annie.diarization import diarization_ready
        self.device = device
        self.source.setText(source)
        self.model = model
        self.speaker_model = speaker_model
        self.whisper_ready = False
        self.whisper_checked = False
        self.test_status.setText('Capture a five-second sample and play it back before your lecture.')
        self.whisper_status.setText(self._whisper_details())
        self.speaker_status.setText('Ready on this computer.' if diarization_ready(speaker_model) else
                                    'Optional. Download the local models to label recurring voices.')
        self._runtime_available = find_spec('sherpa_onnx') is not None
        if not self._runtime_available and not diarization_ready(speaker_model):
            self.speaker_status.setText('The Sherpa runtime is missing. See the local speaker setup guide.')
        self.tabs.setCurrentWidget(self.models_page if show_models else self.input_page)
        self._refresh_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._model_tab_selected()

    def _model_tab_selected(self, _index=None):
        if (self.isVisible() and self.tabs.currentWidget() is self.models_page
                and not self.whisper_checked and not self.task):
            self._check_whisper(False)

    def _whisper_details(self):
        sizes = {'base': '145 MB', 'small': '465 MB', 'large-v3-turbo': '1.6 GB'}
        size = sizes.get(self.model)
        return f'{self.model} · Existing files are reused.' + (f' About {size} on first download.' if size else '')

    def _refresh_buttons(self):
        busy = self.task is not None
        self.record.setEnabled(not busy)
        self.play.setEnabled(not busy and self.has_sample)
        self.whisper_button.setEnabled(not busy and not self.whisper_ready)
        self.install.setEnabled(not busy and getattr(self, '_runtime_available', False))
        self.browse.setEnabled(not busy)
        self.cancel.setVisible(busy)
        self.cancel.setEnabled(busy)

    def _start(self, work, progress, success, status):
        self.task = task = SetupTask(work, self)
        task.progress.connect(progress)
        task.result.connect(success)
        task.error.connect(status.setText)
        task.finished.connect(self._finished)
        task.finished.connect(task.deleteLater)
        self._refresh_buttons()
        self.busy_changed.emit(True)
        task.start()

    def _finished(self):
        self.task = None
        self.model_progress.hide()
        self._refresh_buttons()
        self.busy_changed.emit(False)
        if not self.isVisible():
            self._discard_sample()
        else:
            self._model_tab_selected()

    def cancel_task(self):
        if self.task:
            self.task.cancel.set()
            self.cancel.setEnabled(False)

    def _discard_sample(self):
        if self.player:
            from PyQt5.QtMultimedia import QMediaContent
            self.player.stop()
            self.player.setMedia(QMediaContent())
        if self.sample_dir:
            self.sample_dir.cleanup()
            self.sample_dir = None
        self.has_sample = False
        self.input_level.setValue(0)
        self.play.setText('Play sample')
        self._refresh_buttons()

    def done(self, result):
        self.cancel_task()
        if not self.task:
            self._discard_sample()
        super().done(result)

    def _test_input(self):
        self._discard_sample()
        self.test_status.setText('Opening the selected audio source…')
        self.sample_dir = TemporaryDirectory(prefix='lecture-studio-input-test-')
        self.sample_path = Path(self.sample_dir.name) / 'test.wav'
        self._start(lambda cancel, tick: _run_audio_worker('input_test', cancel, tick,
                    device=self.device, sample_path=str(self.sample_path)), self._test_progress,
                    self._test_finished, self.test_status)

    def _test_progress(self, progress):
        elapsed, peak = progress
        self.input_level.setValue(round(peak * 100))
        self.test_status.setText(f'Capturing sample · {elapsed / 1000:.1f} / {MIC_TEST_SECONDS}s · {peak:.0%} peak')

    def _test_finished(self, result):
        seconds, peak = result
        self.has_sample = True
        self.input_level.setValue(round(peak * 100))
        detail = 'Little signal detected. Check the input or volume.' if peak < 0.005 else 'Play the sample to check clarity.'
        self.test_status.setText(f'{seconds:.1f}s captured · {peak:.0%} peak. {detail}')

    def _play_sample(self):
        try:
            from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.player.stateChanged.connect(lambda state: self.play.setText(
                    'Stop sample' if state == QMediaPlayer.PlayingState else 'Play sample'))
                self.player.error.connect(lambda _: self.test_status.setText(self.player.errorString()))
            if self.player.state() == QMediaPlayer.PlayingState:
                self.player.stop()
            else:
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(self.sample_path))))
                self.player.play()
        except (ImportError, OSError, RuntimeError):
            self.test_status.setText('Audio playback is unavailable in this Qt installation.')

    def _check_whisper(self, download):
        self.whisper_checked = True
        self.model_progress.setRange(0, 0)
        self.model_progress.show()
        self._start(lambda cancel, tick: _run_audio_worker('prepare', cancel, tick,
                    model_name=self.model, download=download),
                    self.whisper_status.setText, self._whisper_finished, self.whisper_status)

    def _whisper_finished(self, path):
        self.whisper_ready = bool(path)
        if self.whisper_ready:
            self.whisper_status.setText(f'{self.model} · Model files are ready on this computer.')
        else:
            self.whisper_status.setText(self._whisper_details() + ' Model files are not cached.')

    def _install_speakers(self):
        self.model_progress.setRange(0, 100)
        self.model_progress.setValue(0)
        self.model_progress.show()
        self.speaker_status.setText('Connecting to the model repository…')
        self._start(lambda cancel, tick: install_speaker_models(self.profile, cancel,
                    lambda received, total: tick((received, total))), self._speaker_progress,
                    self._set_speaker_model, self.speaker_status)

    def _speaker_progress(self, progress):
        received, total = progress
        self.model_progress.setValue(received * 100 // total)
        self.speaker_status.setText(f'{received / 1_000_000:.1f} / {total / 1_000_000:.1f} MB · downloading and verifying')

    def _browse_models(self):
        initial = str(self.speaker_model or self.profile)
        path = QFileDialog.getExistingDirectory(self, 'Speaker model folder', initial)
        if path:
            self._set_speaker_model(path)

    def _set_speaker_model(self, path):
        from annie.diarization import diarization_ready
        if diarization_ready(path):
            self.speaker_model = path
            self.speaker_status.setText('Ready on this computer.')
            self.speaker_model_changed.emit(str(path))
        else:
            self.speaker_status.setText('The folder needs a complete speaker model and its compatible runtime.')
