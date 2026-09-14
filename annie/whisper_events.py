"""Forward isolated Whisper events while allowing a stopped recorder to drain."""
import queue


def consume_session(worker, **options):
    service = worker._service
    session_id, events = service.start(**options)
    worker._session_id = session_id
    if not worker._running:
        service.stop(session_id)
    result = {}
    try:
        while True:
            try:
                data = events.get(timeout=0.2)
            except queue.Empty:
                continue
            kind = data.get('type')
            if kind == 'status':
                worker.status_changed.emit(data.get('text', ''))
            elif kind == 'level' and hasattr(worker, 'audio_level'):
                rms = data.get('rms', 0)
                worker.audio_level.emit(min(1, rms / 400), data.get('is_hearing', False))
            elif kind == 'transcript':
                text = data.get('text', '')
                if text.strip():
                    if options.get('mode') != 'file':
                        text = text.strip() + ' '
                    worker.full_transcript.append(text)
                    worker.transcript_updated.emit(text)
            elif kind == 'progress' and hasattr(worker, 'progress_changed'):
                worker.progress_changed.emit(data.get('percent', 0))
            elif kind == 'recording_saved':
                worker.recording_path = data['path']
                worker.recording_saved.emit(data['path'])
            elif kind == 'capture_stopped' and hasattr(worker, 'capture_finished'):
                worker.capture_finished.emit()
            elif kind == 'metrics':
                worker.last_metrics.update({k: v for k, v in data.items()
                                            if k not in ('type', 'session_id')})
                if 'backlog_seconds' in data and hasattr(worker, 'backlog_updated'):
                    worker.backlog_updated.emit(float(data['backlog_seconds']))
            elif kind == 'error':
                worker.last_error = data.get('text', 'Whisper failed')
                worker.status_changed.emit(f'Error: {worker.last_error}')
            elif kind == 'warning':
                worker.last_warning = data.get('text', 'Audio capture was interrupted')
                worker.status_changed.emit(f'Warning: {worker.last_warning}')
            elif kind == 'session_done':
                result = data
                break
            elif kind == 'process_exit':
                worker.last_error = data.get('text', 'Whisper exited unexpectedly')
                worker.status_changed.emit(f'Error: {worker.last_error}')
                result = {'had_error': True}
                break
    finally:
        service.release(session_id)
        worker._session_id = None
    return result
