"""Native, source-reviewed BFS experiments. No webview or generated-code execution."""
import copy
import json
import math
import sqlite3

from PyQt5.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
    QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSplitter, QTextEdit, QVBoxLayout, QWidget)

from annie.gui.design import ACCENT, BACKGROUND, BORDER, MUTED, SURFACE, TEXT, label, role
from annie.lecture_actions import normalize_segments, transcript_fingerprint


def _clock(value):
    seconds = int(value)
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class GraphCanvas(QWidget):
    """Bounded QPainter rendering of a validated graph and engine snapshot."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph, self.step, self.weighted = None, {}, False
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName('Graph and current breadth-first search state')

    def display(self, graph, step, weighted):
        self.graph, self.step, self.weighted = graph, step, weighted
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(SURFACE))
        if not self.graph:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignCenter, 'Review a source and choose Use this lab to begin.')
            return
        nodes = self.graph['nodes']
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = max(35, min(self.width(), self.height()) / 2 - 42)
        positions = {node: center + QPointF(math.cos(-math.pi/2 + i*2*math.pi/len(nodes))*radius,
                                           math.sin(-math.pi/2 + i*2*math.pi/len(nodes))*radius)
                     for i, node in enumerate(nodes)}
        path = self.step.get('path', [])
        path_edges = set(zip(path, path[1:]))
        active_edge = self.step.get('edge')
        node_radius = 20
        for edge in self.graph['edges']:
            a, b = edge['source'], edge['target']
            start, end = positions[a], positions[b]
            on_path = (a, b) in path_edges or (not self.graph['directed'] and (b, a) in path_edges)
            active = active_edge == [a, b] or (not self.graph['directed'] and active_edge == [b, a])
            painter.setPen(QPen(QColor(ACCENT if on_path or active else MUTED), 3 if on_path or active else 1.4))
            if a == b:
                loop = QRectF(start.x()+8, start.y()-36, 34, 28)
                painter.drawArc(loop, 0, 300*16)
                point = QPointF(start.x()+32, start.y()-35)
            else:
                delta = end-start
                length = math.hypot(delta.x(), delta.y())
                unit = QPointF(delta.x()/length, delta.y()/length)
                origin, tip = start + unit*node_radius, end-unit*node_radius
                painter.drawLine(origin, tip)
                if self.graph['directed']:
                    perpendicular = QPointF(-unit.y(), unit.x())
                    arrow = QPolygonF([tip, tip-unit*10+perpendicular*5, tip-unit*10-perpendicular*5])
                    painter.setBrush(QColor(ACCENT if on_path or active else MUTED))
                    painter.drawPolygon(arrow)
                point = (start+end)/2 + QPointF(8, -8)
            text = f"{edge['weight']:g}" if self.weighted else '1'
            box = QRectF(point.x()-18, point.y()-10, 36, 20)
            painter.fillRect(box, QColor(SURFACE))
            painter.setPen(QColor(TEXT))
            painter.drawText(box, Qt.AlignCenter, text)
        visited, queued = set(self.step.get('visited', [])), set(self.step.get('queue', []))
        for node in nodes:
            point = positions[node]
            current = node == self.step.get('current')
            painter.setBrush(QColor(ACCENT if current else BACKGROUND))
            painter.setPen(QPen(QColor(ACCENT if current or node in visited else BORDER), 3 if node in queued else 1.6))
            painter.drawEllipse(point, node_radius, node_radius)
            painter.setPen(QColor(BACKGROUND if current else TEXT))
            painter.drawText(QRectF(point.x()-18, point.y()-15, 36, 30), Qt.AlignCenter, node)


class LabGeneration(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, segments, course, source_name, generator, parent=None):
        super().__init__(parent)
        self.segments, self.course, self.source_name = segments, course, source_name
        self.generator = generator

    def run(self):
        try:
            from annie.executable_lectures import generate_lab
            if self.isInterruptionRequested():
                return
            result = generate_lab(self.segments, self.course, self.source_name, generator=self.generator)
            if not self.isInterruptionRequested():
                self.result.emit(result)
        except Exception as exc:
            self.error.emit(str(exc) if isinstance(exc, ValueError) else
                            'Lab generation failed. Your source is preserved; try again.')


class LectureLabPage(QWidget):
    evidence_requested = pyqtSignal(float)

    @property
    def current_spec(self):
        return self._spec

    def __init__(self, parent=None, root=None, generator=None):
        super().__init__(parent)
        self.setObjectName('annieSurface')
        from annie.executable_lectures import LabStore
        try:
            self.store = LabStore(root)
        except (ValueError, OSError, sqlite3.Error):
            self.store = None
        self.generator = generator
        self.action_id = ''
        self._worker = None
        self._segments, self._fingerprint = [], ''
        self._course, self._source_name = '', 'Lecture'
        self._spec, self.lab_id, self._graph, self.result = None, None, None, None
        self._dirty = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 6, 0)
        header = QHBoxLayout()
        header.addWidget(label('Executable lecture', 'title'), 1)
        self.generate_button = role(QPushButton('Build lab from lecture'), 'primary')
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self.generate)
        header.addWidget(self.generate_button)
        outer.addLayout(header)
        self.source_label = label('Choose a timestamped lecture. Only BFS graph experiments are supported.', 'muted')
        self.source_label.setWordWrap(True)
        outer.addWidget(self.source_label)
        archive = QHBoxLayout()
        self.example_button = QPushButton('Load built-in example')
        self.example_button.clicked.connect(self.load_example)
        archive.addWidget(self.example_button)
        self.saved_combo = QComboBox()
        self.saved_combo.setMinimumWidth(0)
        self.saved_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.saved_combo.setMinimumContentsLength(12)
        archive.addWidget(self.saved_combo, 1)
        self.open_saved_button = QPushButton('Open saved lab')
        self.open_saved_button.clicked.connect(self.open_saved)
        archive.addWidget(self.open_saved_button)
        outer.addLayout(archive)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName('homeContent')
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        self.evidence = QTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMinimumHeight(150)
        self.evidence.setMaximumHeight(210)
        self.evidence.setPlaceholderText('Source quotes, interpreted claim and assumptions will appear here.')
        self.lab_source_label = label('No lab selected.', 'muted')
        self.lab_source_label.setWordWrap(True)
        content.addWidget(self.lab_source_label)
        content.addWidget(self.evidence)
        self.review_source = QCheckBox('I checked the source, interpretation and experiment assumptions.')
        self.review_source.toggled.connect(self._review_toggled)
        content.addWidget(self.review_source)
        source_actions = QHBoxLayout()
        self.use_button = role(QPushButton('Use this lab'), 'primary')
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self.use_lab)
        source_actions.addWidget(self.use_button)
        self.evidence_button = QPushButton('Go to transcript time')
        self.evidence_button.setEnabled(False)
        self.evidence_button.clicked.connect(self.open_evidence)
        source_actions.addWidget(self.evidence_button)
        content.addLayout(source_actions)
        self.experiment = QWidget()
        experiment_box = QVBoxLayout(self.experiment)
        experiment_box.setContentsMargins(0, 8, 0, 0)
        experiment_box.addWidget(label('Experiment controls', 'section'))
        endpoints = QHBoxLayout()
        endpoints.addWidget(label('Start'))
        self.start_combo, self.target_combo = QComboBox(), QComboBox()
        endpoints.addWidget(self.start_combo, 1)
        endpoints.addWidget(label('Target'))
        endpoints.addWidget(self.target_combo, 1)
        self.weighted = QCheckBox('Use edge weights')
        self.weighted.toggled.connect(self.apply_edits)
        endpoints.addWidget(self.weighted)
        experiment_box.addLayout(endpoints)
        self.edges_input = QTextEdit()
        self.edges_input.setMaximumHeight(85)
        self.edges_input.setAccessibleName('Edges: one source target weight per line')
        self.edges_input.setPlaceholderText('One edge per line: A C 10\nA B 1\nB C 1')
        experiment_box.addWidget(self.edges_input)
        apply_row = QHBoxLayout()
        self.apply_button = QPushButton('Apply graph edits')
        self.apply_button.clicked.connect(self.apply_edits)
        apply_row.addWidget(self.apply_button)
        self.reset_graph_button = QPushButton('Restore original graph')
        self.reset_graph_button.clicked.connect(self.restore_graph)
        apply_row.addWidget(self.reset_graph_button)
        experiment_box.addLayout(apply_row)
        self.assumption_label = label('', 'muted')
        self.assumption_label.setWordWrap(True)
        experiment_box.addWidget(self.assumption_label)
        self.canvas = GraphCanvas()
        experiment_box.addWidget(self.canvas)
        controls = QHBoxLayout()
        self.prev_button, self.next_button = QPushButton('Previous'), QPushButton('Next step')
        self.prev_button.clicked.connect(lambda: self.slider.setValue(self.slider.value()-1))
        self.next_button.clicked.connect(lambda: self.slider.setValue(self.slider.value()+1))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName('Breadth-first search execution step')
        self.slider.valueChanged.connect(self.show_step)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.next_button)
        experiment_box.addLayout(controls)
        self.step_label = label('')
        self.step_label.setWordWrap(True)
        experiment_box.addWidget(self.step_label)
        self.comparison_label = label('')
        self.comparison_label.setWordWrap(True)
        experiment_box.addWidget(self.comparison_label)
        experiment_box.addWidget(label('Predict, then check', 'section'))
        experiment_box.addWidget(label('What will the returned BFS route cost? You can inspect the trace first.', 'muted'))
        prediction = QHBoxLayout()
        self.predicted_cost = QDoubleSpinBox()
        self.predicted_cost.setRange(0, 3200)
        self.predicted_cost.setDecimals(9)
        self.predicted_cost.setAccessibleName('Predicted cost of returned BFS route')
        prediction.addWidget(self.predicted_cost)
        self.no_path = QCheckBox('No path exists')
        self.no_path.toggled.connect(lambda checked: self.predicted_cost.setEnabled(not checked))
        prediction.addWidget(self.no_path)
        self.check_button = QPushButton('Check prediction')
        self.check_button.clicked.connect(self.check_prediction)
        prediction.addWidget(self.check_button)
        experiment_box.addLayout(prediction)
        self.attempt_feedback = label('', 'muted')
        self.attempt_feedback.setWordWrap(True)
        experiment_box.addWidget(self.attempt_feedback)
        self.experiment.setEnabled(False)
        content.addWidget(self.experiment)
        content.addStretch()
        scroll.setWidget(body)
        self.scroll = scroll
        outer.addWidget(scroll, 1)
        self.status = label('No model call has been made. Building a lab sends the selected lecture text to Meta.', 'muted')
        self.status.setWordWrap(True)
        for text_label in (self.source_label, self.lab_source_label, self.status,
                           self.step_label, self.comparison_label, self.assumption_label,
                           self.attempt_feedback):
            text_label.setTextFormat(Qt.PlainText)
        outer.addWidget(self.status)
        self._reload_saved()
        self.edges_input.textChanged.connect(self._mark_dirty)
        self.start_combo.currentIndexChanged.connect(self._mark_dirty)
        self.target_combo.currentIndexChanged.connect(self._mark_dirty)

    def _reload_saved(self):
        self.saved_combo.clear()
        self.saved_combo.addItem('Saved labs', None)
        try:
            if self.store is None:
                raise ValueError('Lab storage is unavailable.')
            labs = self.store.list_labs()
        except (ValueError, OSError, sqlite3.Error):
            self.saved_combo.setItemText(0, 'Saved labs unavailable')
            self.open_saved_button.setEnabled(False)
            self.status.setText('Saved labs could not be loaded. Existing data was left unchanged; '
                                'restore a valid backup or inspect the local lab storage before reopening saved labs.')
            return False
        for spec in labs:
            self.saved_combo.addItem(spec['title'], spec['id'])
        self.open_saved_button.setEnabled(bool(labs))
        return True

    def set_study_action(self, action_id):
        self.action_id = str(action_id or '')

    def set_transcript(self, segments, course='', source_name='Lecture'):
        previous = (self._fingerprint, self._course, self._source_name)
        if segments:
            self._segments = normalize_segments(segments)
            self._fingerprint = transcript_fingerprint(self._segments)
        else:
            self._segments, self._fingerprint = [], ''
        if (self._fingerprint, course, source_name) != previous:
            self.action_id = ''
            self._spec, self.lab_id, self.result, self._graph = None, None, None, None
            self._dirty = False
            self.review_source.setChecked(False)
            self.use_button.setEnabled(False)
            self.experiment.setEnabled(False)
            self.canvas.display(None, {}, False)
            self.evidence.clear()
            self.lab_source_label.setText('No lab selected. Build from the current source or open a saved lab.')
            self.evidence_button.setEnabled(False)
            self.attempt_feedback.clear()
        self._course, self._source_name = course, source_name
        self.source_label.setText(f'Current lecture: {course or "Unspecified course"} · {source_name} · '
            f'{len(self._segments)} source segments. Build sends this text to Meta.')
        self.generate_button.setEnabled(bool(self._segments) and not self.has_running_job() and self.store is not None)

    def generate(self):
        if not self._segments or self.has_running_job() or self.store is None:
            return
        self.generate_button.setEnabled(False)
        self.status.setText('Building a bounded BFS experiment and checking its source references…')
        self._worker = LabGeneration(list(self._segments), self._course, self._source_name, self.generator, self)
        self._worker.result.connect(self._generated)
        self._worker.error.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _generated(self, spec):
        worker = self._worker
        if (worker is None or self._fingerprint != spec.get('fingerprint') or
                worker.course != self._course or worker.source_name != self._source_name):
            self.status.setText('The source changed during generation. Build again from the current lecture.')
            return
        self.load_lab(spec)
        self.status.setText('Source references checked. Review the interpretation and assumptions before using this lab.')

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker:
            worker.deleteLater()
        self.generate_button.setEnabled(bool(self._segments) and self.store is not None)

    def load_lab(self, spec):
        from annie.graph_lab import validate_graph
        validate_graph(spec['graph'])
        self._spec = copy.deepcopy(spec)
        self.lab_id, self.result, self._graph = None, None, None
        self.review_source.setChecked(False)
        self.use_button.setEnabled(False)
        self.experiment.setEnabled(False)
        self.canvas.display(None, {}, False)
        self.attempt_feedback.clear()
        self.lab_source_label.setText(f'Lab source: {spec.get("course") or "Unspecified course"} · {spec["source_name"]}')
        lines = [spec['title'], '', 'INTERPRETATION — check against the source', spec['claim'],
                 'This is an interpretation to review, not a verified statement of the teacher’s intent.', '',
                 'ASSUMPTIONS — interpreted or added for the example; compare with the source']
        lines += ['• ' + text for text in spec['assumptions']]
        lines += ['', 'CONSTRUCTED EXAMPLE — graph values are added for exploration, not quoted teacher facts.'
                  if spec['graph_origin'] == 'constructed_example' else
                  'LECTURE EXAMPLE — verify that these graph values match the source.', '', 'SOURCE QUOTES']
        for ref in spec['evidence']:
            lines += [f'{ref["source"]} · {_clock(ref["start"])}–{_clock(ref["end"])}', ref['quote'], '']
        self.evidence.setPlainText('\n'.join(lines))
        self.evidence_button.setEnabled(bool(spec['evidence']))

    def _review_toggled(self, checked):
        self.use_button.setEnabled(bool(self._spec) and checked and self.lab_id is None and self.store is not None)

    def use_lab(self):
        if self.store is None:
            self.status.setText('Local lab storage is unavailable. Existing data was preserved; restore a valid backup before saving.')
            return
        if self._spec is None or not self.review_source.isChecked():
            self.status.setText('Review the source and assumptions, then tick the confirmation box.')
            return
        try:
            self.lab_id = self.store.save(self._spec)
            self.experiment.setEnabled(True)
            self.use_button.setEnabled(False)
            self.restore_graph()
            archive_ok = self._reload_saved()
            self.status.setText('Lab saved locally. Execution is computed by the bounded graph engine, not the model.'
                if archive_ok else 'This lab was saved, but the saved-lab list could not be read. Existing records were left unchanged.')
            QTimer.singleShot(0, self._reveal_canvas)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else 'Could not save this lab locally.')

    def restore_graph(self):
        if not self._spec or not self.lab_id:
            return
        graph = copy.deepcopy(self._spec['graph'])
        self.start_combo.clear()
        self.target_combo.clear()
        self.start_combo.addItems(graph['nodes'])
        self.target_combo.addItems(graph['nodes'])
        self.start_combo.setCurrentText(graph['start'])
        self.target_combo.setCurrentText(graph['target'])
        self.edges_input.setPlainText('\n'.join(f"{e['source']} {e['target']} {e['weight']!r}" for e in graph['edges']))
        self._graph = graph
        self.weighted.blockSignals(True)
        self.weighted.setChecked(False)
        self.weighted.blockSignals(False)
        self._dirty = False
        self.recompute()
        self.status.setText('Original graph restored with equal effective edge weights.')

    def apply_edits(self, *_):
        if not self.lab_id or not self._spec:
            return
        try:
            from annie.graph_lab import validate_graph
            edges = []
            if len(self.edges_input.toPlainText()) > 5000:
                raise ValueError('Use at most 32 short edge lines.')
            for line in self.edges_input.toPlainText().splitlines():
                if not line.strip():
                    continue
                fields = line.split()
                if len(fields) != 3:
                    raise ValueError('Use one edge per line: source target weight (for example A C 10).')
                edges.append({'source': fields[0], 'target': fields[1], 'weight': float(fields[2])})
            graph = {**self._spec['graph'], 'edges': edges, 'start': self.start_combo.currentText(),
                     'target': self.target_combo.currentText()}
            self._graph = validate_graph(graph)
            self._dirty = False
            self.recompute()
            self.status.setText('Graph edits applied. The edited graph is an experiment, not a new claim about the lecture.')
        except (ValueError, TypeError) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else 'Invalid graph edits.')

    def recompute(self, *_):
        if not self._graph or not self.lab_id:
            return
        from annie.graph_lab import run_lab
        self.result = run_lab(self._graph, weighted=self.weighted.isChecked())
        self.check_button.setEnabled(True)
        self.slider.setEnabled(True)
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(self.result['steps'])-1)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.show_step(0)
        if self.weighted.isChecked() and not self.result['weights_equal']:
            self.assumption_label.setText('Changed experiment: unequal weighted edges are outside the equal-edge BFS assumption. '
                                         'This does not refute a lecture claim about an unweighted graph.')
        else:
            self.assumption_label.setText('Equal effective edge weights: BFS minimizes the number of edges. '
                                         'Source assumptions still require your review.')
        bfs = ' → '.join(self.result['bfs_path']) or 'No path'
        shortest = ' → '.join(self.result['shortest_path']) or 'No path'
        cost = lambda value: 'unreachable' if value is None else f'{value:.12g}'
        self.comparison_label.setText(f'BFS route: {bfs} · cost {cost(self.result["bfs_cost"])}\n'
            f'Cheapest route: {shortest} · cost {cost(self.result["shortest_cost"])}\n'
            'Both results are computed locally. BFS optimizes hops, not unequal edge weights.')
        self.attempt_feedback.clear()

    def show_step(self, index):
        if not self.result or not self._graph:
            return
        step = self.result['steps'][index]
        self.canvas.display(self._graph, step, self.weighted.isChecked())
        queue = ', '.join(step['queue']) or 'empty'
        visited = ', '.join(step['visited']) or 'none'
        self.step_label.setText(f'Step {index+1}/{len(self.result["steps"])} · {step["event"]} · '
            f'Current: {step["current"] or "—"}\nQueue: {queue}\nDiscovered: {visited}')
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self.result['steps'])-1)

    def check_prediction(self):
        if not self.lab_id or not self._graph or self._dirty:
            return
        try:
            result = self.store.record_attempt(self.lab_id, graph=self._graph,
                weighted=self.weighted.isChecked(),
                predicted_cost=None if self.no_path.isChecked() else self.predicted_cost.value(),
                predict_no_path=self.no_path.isChecked(), action_id=self.action_id)
            correct = result.get('correct', result.get('passed', False))
            self.attempt_feedback.setText('No prediction was supplied. This attempt is unassessed.' if correct is None else
                'This check passed. The result records this experiment only; it does not establish mastery.'
                if correct else 'This prediction did not match the computed BFS result. Inspect the trace and try again.')
            self.status.setText('Prediction and computed result saved locally for this exact graph and weight mode.')
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else 'Could not save this check.')

    def open_evidence(self):
        if self._spec and self._spec['evidence']:
            self.evidence_requested.emit(float(self._spec['evidence'][0]['start']))

    def open_saved(self):
        identity = self.saved_combo.currentData()
        if not identity:
            return
        try:
            spec = self.store.get(identity)
            self.load_lab(spec)
            self.action_id = ''
            self.status.setText('Saved lab opened. Review the source and assumptions before starting this session.')
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else 'Could not open this saved lab.')

    def load_example(self):
        from annie.executable_lectures import generate_lab
        source = 'Authored BFS example — not a live Meta result'
        segments = [{'start': 0, 'end': 12, 'source': source,
            'text': 'Breadth-first search (BFS) finds a path with the fewest edges in an unweighted graph.'}]
        payload = {'supported': True, 'reason': 'A bounded BFS example.', 'title': 'BFS: fewest edges versus lowest cost',
            'claim': 'BFS finds a path with the fewest edges.', 'assumptions': ['The original graph is unweighted.'],
            'graph_origin': 'constructed_example', 'evidence': [{'quote': segments[0]['text'],
                't_start': 0, 't_end': 12, 'source': source}],
            'graph': {'nodes': ['A', 'B', 'C'], 'edges': [
                {'source': 'A', 'target': 'C', 'weight': 10},
                {'source': 'A', 'target': 'B', 'weight': 1},
                {'source': 'B', 'target': 'C', 'weight': 1}],
                'start': 'A', 'target': 'C', 'directed': True}}
        try:
            spec = generate_lab(segments, 'Authored example', source, generator=lambda *_: json.dumps(payload))
            self.load_lab(spec)
            self.action_id = ''
            self.status.setText('Built-in authored example loaded. No model call was made. Tick source review to explore it.')
        except ValueError as exc:
            self.status.setText(str(exc))

    def has_running_job(self):
        return self._worker is not None

    def _reveal_canvas(self):
        if self.isVisible() and self.lab_id:
            self.scroll.ensureWidgetVisible(self.canvas, 0, 10)

    def _mark_dirty(self, *_):
        if self.lab_id:
            self._dirty = True
            self.check_button.setEnabled(False)
            self.slider.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.status.setText('Graph edits are not applied yet. Apply graph edits before stepping or checking a prediction.')

    def stop_background(self):
        if self._worker:
            self._worker.requestInterruption()
