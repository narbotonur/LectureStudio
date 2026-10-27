"""Muse Voice realtime transport, following the official Voice API.

https://dev.meta.ai/docs/api-reference/voice/realtime
https://dev.meta.ai/docs/speech-to-text

16 kHz mono PCM; handshake auth; cumulative partials; final turns only enter
the transcript. No recordings are uploaded unless this backend is selected.
"""
import json
import io
import os
import threading
import time
import uuid
import wave

from annie.transcription import emit_segment


class VoiceUnavailable(RuntimeError):
    """Safe provider failure; does not include credentials or server payloads."""


class VoiceTurns:
    """Keep overlapping finalizations separate; partials never become evidence."""
    def __init__(self, emit, source, offset=0.0, clock=time.monotonic):
        self.emit, self.source, self.offset, self.clock = emit, source, offset, clock
        self.turns = {}
        self.finalized = set()
        self.active = None
        self.committed_seconds = offset
        self.started = clock()
        self.first_text = None

    def handle(self, event):
        kind = event.get('type')
        processed = max(0.0, float(event.get('audioProcessedMs', 0)) / 1000)
        if kind == 'error':
            raise VoiceUnavailable('Meta Voice rejected the transcription stream. Check access and billing.')
        if kind == 'speechStart':
            self.active = event['turnId']
            self.turns[self.active] = {'start': processed, 'end': None, 'speaker': ''}
        elif kind == 'speechEnd':
            self.turns.setdefault(event['turnId'], {'start': processed, 'speaker': ''})['end'] = processed
        elif kind == 'speaker' and self.active in self.turns:
            self.turns[self.active]['speaker'] = str(event.get('label', ''))
        elif kind == 'transcript':
            text = str(event.get('transcript', ''))
            self.emit('partial_transcript', text=text)
            if text and self.first_text is None:
                self.first_text = self.clock() - self.started
                self.emit('metrics', first_text_seconds=self.first_text)
        elif kind == 'speechComplete':
            turn_id = event['turnId']
            if turn_id in self.finalized:
                return
            turn = self.turns.get(turn_id)
            if turn is None:
                # A timestamp cannot be reconstructed honestly without speechStart.
                raise VoiceUnavailable('Meta Voice completed a turn without its start boundary.')
            turn['text'] = str(event.get('transcript', '')).strip()
            turn['end'] = turn.get('end') if turn.get('end') is not None else processed
            # Emit in audio order even when later turns finalize first. The
            # acknowledged offset must never skip an unfinished earlier turn.
            while self.turns:
                first_id = min(self.turns, key=lambda key: self.turns[key]['start'])
                first = self.turns[first_id]
                if 'text' not in first:
                    break
                if first['text']:
                    emit_segment(self.emit, self.offset + first['start'], self.offset + first['end'],
                                 first['text'], self.source, 'meta_voice', first.get('speaker', ''))
                    self.emit('transcript', text=first['text'])
                self.committed_seconds = max(self.committed_seconds, self.offset + first['end'])
                self.finalized.add(first_id)
                del self.turns[first_id]
            self.emit('partial_transcript', text='')
        if processed:
            self.emit('metrics', processed_seconds=self.offset + processed)


class MetaVoiceBackend:
    name = 'meta_voice'
    # Rotate before the provider's documented 60-minute stream cap.
    session_seconds = 59 * 60

    def __init__(self, api_key=None, language='', keywords=(), connector=None):
        self.api_key = api_key or os.environ.get('META_API_KEY') or os.environ.get('MODEL_API_KEY', '')
        if not self.api_key:
            raise VoiceUnavailable('Set a Meta Model API key to use Muse Voice.')
        aliases = {'en': 'English', 'tr': 'Turkish', 'ar': 'Arabic', 'de': 'German',
                   'fr': 'French', 'es': 'Spanish', 'zh': 'Mandarin Chinese'}
        if str(language).lower() in ('ru', 'russian', 'kk', 'kazakh'):
            raise VoiceUnavailable('Russian and Kazakh are not documented Muse Voice languages. Use Local Whisper for these lectures.')
        self.language = aliases.get(language, language)
        self.keywords = list(keywords)
        self.connector = connector
        self.committed_seconds = 0.0

    def stream(self, spool, emit, source):
        if self.connector is None:
            try:
                from websockets.sync.client import connect
            except ImportError as exc:
                raise VoiceUnavailable('Muse Voice needs the websockets package with sync support.') from exc
        else:
            connect = self.connector
        self.committed_seconds = spool.read_seconds
        complete = False
        while not complete:
            offset = spool.read_seconds
            turns = VoiceTurns(emit, source, offset)
            sender_stop = threading.Event()
            sender_done = threading.Event()
            errors = []
            duration = [0.0]
            eof = [False]
            uri = f'wss://api.meta.ai/v1/asr/realtime?sessionId=studio-{uuid.uuid4().hex}'
            try:
                with connect(uri, open_timeout=20, close_timeout=5, max_size=2**20) as ws:
                    handshake = {
                        'authorization': {'accessToken': f'Bearer {self.api_key}'},
                        'audioEncoding': 'PCM_16KHZ', 'model': 'muse-voice-transcribe-1.0',
                        'mode': 'ENDPOINTING', 'partialMode': 'CUMULATIVE',
                        'emitAudioProgress': True,
                    }
                    if self.language:
                        handshake['languageBias'] = [self.language]
                    if self.keywords:
                        handshake['keywords'] = self.keywords
                    ws.send(json.dumps(handshake))
                    ack = json.loads(ws.recv(timeout=20))
                    if not isinstance(ack, dict) or not ack.get('sessionId'):
                        raise VoiceUnavailable('Meta Voice handshake failed. Check API access and billing.')
                    emit('status', text='Muse Voice connected · live transcription')

                    def send_audio():
                        started = time.monotonic()
                        try:
                            while not sender_stop.is_set() and duration[0] < self.session_seconds:
                                data = spool.read(2560, timeout=.2)
                                if data is None:
                                    eof[0] = True
                                    break
                                if not data:
                                    continue
                                # Absolute pacing prevents drift and provider backlog rejection.
                                wait = started + duration[0] - time.monotonic()
                                if wait > 0 and sender_stop.wait(wait):
                                    return
                                if time.monotonic() - started - duration[0] > 5:
                                    raise VoiceUnavailable('Muse Voice upload fell behind real time; switching to local transcription.')
                                ws.send(data)
                                duration[0] += len(data) / 32000
                            if not sender_stop.is_set():
                                ws.send(json.dumps({'type': 'endStream'}))
                        except Exception as exc:
                            errors.append(exc)
                        finally:
                            sender_done.set()

                    sender = threading.Thread(target=send_audio, name='meta-voice-send', daemon=True)
                    sender.start()
                    finishing = None
                    try:
                        while True:
                            if errors:
                                raise VoiceUnavailable('Muse Voice audio transport failed; saved audio remains available.')
                            if sender_done.is_set():
                                finishing = finishing or time.monotonic()
                                if time.monotonic() - finishing > 30:
                                    raise VoiceUnavailable('Muse Voice did not finish the stream within 30 seconds.')
                            try:
                                message = ws.recv(timeout=.2)
                            except TimeoutError:
                                continue
                            except Exception as exc:
                                # Newer websockets exposes received close code on rcvd.
                                received = getattr(exc, 'rcvd', None)
                                code = getattr(received, 'code', None)
                                if code == 1000 and sender_done.is_set() and not errors:
                                    break
                                raise VoiceUnavailable('Muse Voice connection ended before completion; continuing locally.') from exc
                            if isinstance(message, str):
                                turns.handle(json.loads(message))
                                self.committed_seconds = turns.committed_seconds
                    finally:
                        sender_stop.set()
                        ws.close()
                        sender.join(timeout=6)
                        if sender.is_alive():
                            raise VoiceUnavailable('Muse Voice sender did not close; recording is preserved.')
                    if turns.turns:
                        raise VoiceUnavailable('Muse Voice closed with unfinished turns; continuing locally.')
                    complete = eof[0]
                    if not complete:
                        emit('status', text='Renewing Muse Voice connection before the session limit')
            except VoiceUnavailable:
                raise
            except Exception as exc:
                raise VoiceUnavailable('Muse Voice is unavailable; saved audio can be transcribed locally.') from exc


def transcribe_file(path, backend, stop, emit, request=None):
    """Split mono PCM WAVs below Meta's 10-minute/32 MB request caps."""
    if request is None:
        import requests
        request = requests.post
    from pathlib import Path
    source = Path(path).name
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                or audio.getframerate() not in (16000, 24000) or audio.getcomptype() != 'NONE'):
            raise VoiceUnavailable('Muse Voice file input needs mono 16-bit PCM WAV at 16 or 24 kHz. Select Local Whisper for other formats.')
        rate, frames = audio.getframerate(), audio.getnframes()
        position = 0
        while position < frames and not stop.is_set():
            pcm = audio.readframes(rate * 590)
            if not pcm:
                break
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as clip:
                clip.setnchannels(1)
                clip.setsampwidth(2)
                clip.setframerate(rate)
                clip.writeframes(pcm)
            settings = {'model': 'muse-voice-transcribe-1.0', 'audioEncoding': 'WAV',
                        'mode': 'ENDPOINTING'}
            if backend.language:
                settings['languageBias'] = [backend.language]
            if backend.keywords:
                settings['keywords'] = backend.keywords
            try:
                response = request('https://api.meta.ai/v1/asr/transcribe',
                                   headers={'Authorization': f'Bearer {backend.api_key}',
                                            'Accept': 'application/json'},
                                   files={'request': (None, json.dumps(settings), 'application/json'),
                                          'audio': ('lecture.wav', buffer.getvalue(), 'audio/wav')},
                                   timeout=(20, 180))
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                raise VoiceUnavailable('Muse Voice file transcription failed. Saved audio is unchanged; retry with Local Whisper.') from exc
            for turn in payload.get('turns', []):
                text = str(turn.get('transcript', '')).strip()
                if text:
                    start = position / rate + float(turn['startMs']) / 1000
                    end = position / rate + float(turn['endMs']) / 1000
                    emit_segment(emit, start, end, text, source, 'meta_voice', str(turn.get('speaker', '')))
                    emit('transcript', text=f'[{int(start // 60):02d}:{int(start % 60):02d} → {int(end // 60):02d}:{int(end % 60):02d}] {text}\n')
            position += len(pcm) // 2
            emit('progress', percent=min(100, int(position / max(frames, 1) * 100)))
    return {'cancelled': stop.is_set()}
