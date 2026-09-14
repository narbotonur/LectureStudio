"""
Annie Meeting Notes & Transcriber Module
Inspired by Meetily AI & Notion AI:
1. Dual-Engine Speech-to-Text:
   - Local Whisper AI (small, large-v3-turbo, base, custom fine-tuned models)
   - Gemini Live Streaming (Ultra-Low Latency Cloud)
2. Meetily "Import & Enhance" File Transcriber:
   - Transcribes existing audio files (.wav, .mp3, .m4a, .aac, .flac, .ogg, .webm, .mp4) with precise timestamps [MM:SS]
3. Custom Summary Templates:
   - 🎓 University Lecture / Study Notes (Notion AI)
   - 💼 Business Meeting Minutes
   - ⚡ Executive Summary (TL;DR)
   - 💬 Q&A & Study Guide Breakdown
4. Dual AI Summarizer (Local Ollama offline + Cloud Gemini 3.6 Flash)
"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
import numpy as np
import sounddevice as sd
from PyQt5.QtCore import QThread, pyqtSignal
from google import genai
from google.genai import types

# Fix Windows DLL loading for CTranslate2 / faster_whisper
if sys.platform == "win32":
    for path in sys.path:
        for sub in ["ctranslate2", "faster_whisper"]:
            candidate = os.path.join(path, sub)
            if os.path.isdir(candidate):
                try:
                    os.add_dll_directory(candidate)
                except Exception:
                    pass

from annie.config import (GEMINI_API_KEY, GEMINI_MODEL, AUDIO_INPUT_DEVICE,
                          AUDIO_AGC_ENABLED, PHONE_IP, MODELS_DIR)
from annie.dsp import AudioEnhancer
from annie import config as cfg

FORMAT = 'int16'
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
SUMMARY_MODEL = "gemini-3.6-flash"
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-latest"

HALLUCINATION_PATTERNS = [
    r'^thank\s*you\.?$',
    r'^thanks\s*for\s*watching\.?$',
    r'^subtitles?\s*by.*$',
    r'^amara\.org.*$',
    r'^subscribe.*$',
    r'^please\s*subscribe.*$',
    r'^see\s*you\s*in\s*the\s*next\s*video\.?$',
    r'^you\.?$',
    r'^the\s*larger\s*model\??$',
    r'^bye\.?$',
    r'^okay\.?$'
]

def clean_stray_scripts(text: str) -> str:
    """
    Strips out stray non-Latin / non-Cyrillic scripts (Georgian, Devanagari, Kannada, Hebrew, etc.),
    removes noise tags (<noise>, [noise]), and scrubs acoustic repetition hallucination loops.
    """
    if not text:
        return ""
    # Filter out anything outside Latin, Cyrillic, Numbers, Basic Punctuation, Whitespace, and Math Symbols
    cleaned = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9\s.,!?:;\-\'\"()\[\]{}+=/*%<>]', '', text)
    cleaned = re.sub(r'<[^>]+>|\[[^\]]+\]', '', cleaned)
    
    # Scrub repetition loops from acoustic noise
    cleaned = re.sub(r'(\b\w+\b)(?:\s+\1){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(\b\w+\s+\w+\b)(?:\s+\1){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(?:\b\d+\b\s*){5,}', '', cleaned)
    cleaned = cleaned.strip()

    lower_t = cleaned.lower()
    for pat in HALLUCINATION_PATTERNS:
        if re.match(pat, lower_t, re.IGNORECASE):
            return ""

    return cleaned


def stream_phone_audio_loop(callback, running_check):
    """Streams live audio from Android/iPhone IP Webcam server (e.g. http://<PHONE_IP>:8080/audio.wav)."""
    if not PHONE_IP:
        print("  [PHONE AUDIO] PHONE_IP is not set in settings!")
        return
    url = f"http://{PHONE_IP}:8080/audio.wav"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Annie/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            _ = response.read(44)  # Skip WAV header
            while running_check():
                chunk = response.read(CHUNK_SIZE * 2)
                if not chunk:
                    break
                callback(chunk, CHUNK_SIZE, None, None)
    except Exception as e:
        print(f"  [PHONE AUDIO] Streaming error from {url}: {e}")


# ─────────────────────────────────────────────────────────────
#  Meetily & Notion AI Custom Summary Templates
# ─────────────────────────────────────────────────────────────

def build_meeting_notes_prompt(text_content: str, subject_context: str = "", template_name: str = "lecture", user_notes: str = "") -> str:
    ctx_note = f"\nSubject / Topic Context: {subject_context}" if subject_context else ""
    fusion_block = ""
    if user_notes and user_notes.strip():
        fusion_block = (
            "\n=======================================================\n"
            "✍️ STUDENT'S LIVE HIGHLIGHTS & KEY EMPHASIS [USER-WRITTEN]:\n"
            f"{user_notes.strip()}\n"
            "=======================================================\n"
            "CRITICAL NOTE FUSION INSTRUCTION (Granola / Humla Style):\n"
            "- The student personally wrote the highlights above during the lecture/meeting to mark what is most vital for them.\n"
            "- Prominently feature and elaborate on these highlighted points under the corresponding section headings.\n"
            "- Use the speech transcript below to provide full verbatim context, definitions, formulas, and explanations around the student's highlights.\n\n"
        )

    if template_name == "minutes":
        return (
            "You are an expert Corporate Meeting Secretary and Business Intelligence Synthesizer.\n"
            "Transform the provided transcript and notes into structured, actionable Business Meeting Minutes in clean Markdown.\n\n"
            f"{ctx_note}\n\n"
            f"{fusion_block}"
            "REQUIRED STRUCTURE:\n"
            "1. # <Meeting Title>\n"
            "2. ### Executive Summary (2-3 concise sentences on purpose and main outcome)\n"
            "3. ### Key Decisions Made (Bullet points with clear rationale)\n"
            "4. ### Action Items & Ownership (Use checkboxes `- [ ] **[Assignee / Team]** Task description (Deadline: ... )`)\n"
            "5. ### Discussion Topics & Highlights (H3 headings for each topic discussed, with indented sub-bullets)\n"
            "6. ### Next Steps & Follow-ups\n\n"
            "Return ONLY clean Markdown. Transcript:\n" + text_content
        )
    elif template_name == "brief":
        return (
            "You are an Executive Briefing Assistant.\n"
            "Transform the provided transcript and notes into a high-level, ultra-concise Executive Brief.\n\n"
            f"{ctx_note}\n\n"
            f"{fusion_block}"
            "REQUIRED STRUCTURE:\n"
            "1. # <Topic> — Executive Brief\n"
            "2. ### TL;DR Summary (High-level overview)\n"
            "3. ### 5 Critical Takeaways (High-impact bullet points)\n"
            "4. ### Key Metrics, Deadlines & Risks\n\n"
            "Return ONLY clean Markdown. Transcript:\n" + text_content
        )
    elif template_name == "qa":
        return (
            "You are an Academic Exam Prep & Study Guide Synthesizer.\n"
            "Transform the provided lecture transcript and notes into a comprehensive Q&A Study Guide.\n\n"
            f"{ctx_note}\n\n"
            f"{fusion_block}"
            "REQUIRED STRUCTURE:\n"
            "1. # <Lecture Topic> — Q&A Study Guide\n"
            "2. ### Core Questions & Concept Explanations\n"
            "   - **Q: [Clear conceptual question that could appear on an exam]**\n"
            "     - **A:** [Detailed explanation, key formulas, trade-offs, and examples]\n"
            "3. ### Key Terminology & Definitions (Glossary list)\n"
            "4. ### Open / Unresolved Questions\n\n"
            "Return ONLY clean Markdown. Transcript:\n" + text_content
        )
    else:
        # Default: "lecture" (Notion AI Study Notes)
        return (
            "You are the world's best Notion AI Study Note Synthesizer.\n"
            "Transform the provided lecture / meeting transcript and student notes into clean, professional, and beautifully structured Notion-style Markdown notes.\n\n"
            f"{ctx_note}\n\n"
            f"{fusion_block}"
            "STYLE & FORMATTING GUIDELINES (Strictly follow this structure):\n"
            "1. **Title (# <Lecture Topic / Course Name>)**: Start with a single clean H1 title.\n"
            "2. **Action Items (### Action Items)**: Use markdown task checkboxes `- [ ] ` for assignments, required readings, software to install, or practice exercises.\n"
            "3. **Core Topic Sections (### <Dynamic Topic Name>)**: Create specific, meaningful H3 headings for each major concept taught in the lecture (e.g. `### Classes of Computers`, `### Eight Great Ideas in Computer Architecture`, `### Five Classic Components`, `### Measuring Performance`, etc.). DO NOT use generic section names.\n"
            "4. **Hierarchical Bullet Points**:\n"
            "   - Use `- **Bold Concept / Term** — concise explanation or definition` format with an em-dash (`—`).\n"
            "   - Use nested sub-bullets (indented with 4 spaces `    - `) for breakdowns, categories, analogies, formulas, or examples.\n"
            "   - Bold key numbers, formulas (e.g. `**Instruction Count × CPI × Clock Cycle Time**`), and takeaways.\n"
            "   - Include real-world analogies, key takeaways, and trade-offs where applicable.\n"
            "5. **Logistics & Policies (### Logistics & Administration)**: If mentioned, include grading breakdown, exam rules, deadlines, and schedule details.\n\n"
            "ANTI-HALLUCINATION RULES:\n"
            "- Only include concepts, facts, policies, and details actually stated in the transcript or student highlights.\n"
            "- Do NOT invent corporate business roles (e.g. 'Lead Developer', 'QA Lead').\n"
            "- Return ONLY clean, valid Markdown text (no JSON, no code block wrapping).\n\n"
            "Transcript:\n" + text_content
        )


def generate_ai_summary_sync(text_content: str, subject_context: str = "", template_name: str = "lecture", user_notes: str = "") -> str:
    """
    Synthesizes structured notes using Local Ollama (if available) or Google Gemini 3.6 Flash.
    Fuses student's live notes with verbatim audio transcript (Granola / Humla style).
    """
    prompt = build_meeting_notes_prompt(text_content, subject_context, template_name, user_notes=user_notes)

    # 1. Try Local Ollama (100% Offline / Privacy-First like Meetily)
    try:
        req_data = json.dumps({
            "model": "llama3.2",
            "prompt": prompt,
            "stream": False
        }).encode('utf-8')
        req = urllib.request.Request("http://localhost:11434/api/generate", data=req_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            ollama_res = data.get("response", "").strip()
            if ollama_res:
                print("  [MEETING] Note synthesized via Local Ollama (100% Offline)")
                return ollama_res
    except Exception:
        pass

    # 2. Cloud Gemini fallback with automatic model rotation
    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    active_models = [
        cfg.GEMINI_MODEL,
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
    ]
    for model_name in active_models:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if res and res.text and res.text.strip():
                return res.text.strip()
        except Exception as e:
            print(f"  [MEETING] Model {model_name} error: {e}, trying next fallback...")
            continue

    return f"# Summary Error\n\nCould not generate summary across all fallback models."


def generate_anki_flashcards(text_content: str, subject_context: str = "", user_notes: str = "") -> str:
    """
    Generates high-yield Anki flashcards (Front/Back & Cloze deletions) from lecture content.
    Returns clean TSV/Markdown ready for import into Anki or Quizlet.
    Fuses user's live highlights into prioritized cards.
    """
    ctx_note = f"\nCourse / Topic Context: {subject_context}" if subject_context else ""
    user_note_block = ""
    if user_notes and user_notes.strip():
        user_note_block = f"\nStudent's Priority Notes (Ensure high-yield cards exist for each):\n{user_notes.strip()}\n"

    prompt = (
        "You are an expert Academic Learning Engineer specializing in spaced repetition and Anki flashcard design.\n"
        "Analyze the provided lecture transcript and student notes to generate a high-yield Anki Flashcard deck.\n\n"
        f"{ctx_note}\n"
        f"{user_note_block}\n"
        "FLASHCARD DESIGN PRINCIPLES:\n"
        "1. Minimum Information Principle: Each card must test exactly ONE discrete concept, formula, or definition.\n"
        "2. Clear and Unambiguous: Front must be a specific question or prompt; Back must be the concise, direct answer.\n"
        "3. Include LaTeX formulas where applicable (e.g. `$CPI = \\frac{\\text{Cycles}}{\\text{Instructions}}$`).\n"
        "4. Include both Question/Answer cards and Cloze deletion cards (`{{c1::key term}}`).\n\n"
        "FORMATTING:\n"
        "# 🎴 ANKI FLASHCARD DECK\n\n"
        "| # | Type | Front (Question / Prompt) | Back (Answer / Explanation) |\n"
        "|---|---|---|---|\n"
        "(Generate 10 to 20 rich cards in the table above)\n\n"
        "### 📋 RAW ANKI TSV (Tab-Separated for 1-Click Anki Import)\n"
        "```tsv\n"
        "<Front>\\t<Back>\\t<Tags>\n"
        "```\n\n"
        "Transcript / Notes:\n" + text_content
    )

    # 1. Try local Ollama
    try:
        req_data = json.dumps({"model": "llama3.2", "prompt": prompt, "stream": False}).encode('utf-8')
        req = urllib.request.Request("http://localhost:11434/api/generate", data=req_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            ollama_res = data.get("response", "").strip()
            if ollama_res:
                return ollama_res
    except Exception:
        pass

    # 2. Gemini fallback with automatic model rotation
    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    active_models = [
        cfg.GEMINI_MODEL,
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
    ]
    for model_name in active_models:
        try:
            res = client.models.generate_content(model=model_name, contents=prompt)
            if res and res.text and res.text.strip():
                return res.text.strip()
        except Exception:
            continue

    return "# Flashcard Generation Error\n\nCould not generate flashcards across fallback models."


def analyze_lecture_slide(image_bytes: bytes, mime_type: str = "", course_context: str = "") -> str:
    """
    Multimodal Vision Reader: Extracts text, diagrams, code, and LaTeX math formulas from lecture slide / blackboard photo.
    """
    ctx_note = f"Course Context: {course_context}\n" if course_context else ""
    prompt = (
        "You are Annie, an academic vision assistant for university students.\n"
        f"{ctx_note}"
        "Carefully analyze this lecture slide / chalkboard photo:\n"
        "1. Extract all text, headings, and bullet points verbatim.\n"
        "2. Transcribe any mathematical formulas or equations into standard LaTeX syntax (`$$...$$` or `$..$`).\n"
        "3. Extract and format any code blocks with proper syntax highlighting.\n"
        "4. Describe and explain any architectural diagrams, dataflow graphs, state machines, or circuits shown.\n"
        "5. Provide a 2-3 sentence 'Key Takeaway for Exam' at the end.\n\n"
        "Return clean, structured Markdown."
    )
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        mime_type = 'image/png'
    elif image_bytes.startswith(b'\xff\xd8\xff'):
        mime_type = 'image/jpeg'
    elif image_bytes.startswith((b'GIF87a', b'GIF89a')):
        mime_type = 'image/gif'
    elif image_bytes.startswith(b'RIFF') and image_bytes[8:12] == b'WEBP':
        mime_type = 'image/webp'
    mime_type = mime_type or 'image/jpeg'

    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    model_candidates = []
    for model_name in (
        cfg.GEMINI_MODEL,
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.5-flash',
        'gemini-flash-latest',
        'gemini-3.1-flash-lite',
    ):
        if model_name and model_name not in model_candidates:
            model_candidates.append(model_name)

    failures = []
    for model_name in model_candidates:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=[prompt, part]
            )
            text = (res.text or '').strip() if res else ''
            if text:
                return text
            failures.append(f'{model_name}: empty response')
        except Exception as exc:
            failures.append(f'{model_name}: {exc}')
            print(f'  [SLIDE] Model {model_name} failed; trying fallback: {exc}')

    detail = failures[-1] if failures else 'No compatible vision model was available.'
    raise RuntimeError(f'Slide analysis unavailable after all model fallbacks. {detail}')


# ─────────────────────────────────────────────────────────────
#  Engine 1: Gemini Live Streaming Transcriber (Cloud)
# ─────────────────────────────────────────────────────────────
class GeminiMeetingWorker(QThread):
    transcript_updated = pyqtSignal(str)
    summary_ready = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    audio_level = pyqtSignal(float, bool)

    def __init__(self, device=None, subject_context="", template_name="lecture"):
        super().__init__()
        self.setStackSize(8 * 1024 * 1024)
        self._running = True
        self.device = device if device is not None else AUDIO_INPUT_DEVICE
        self.subject_context = subject_context.strip()
        self.template_name = template_name
        self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={'api_version': 'v1alpha'})
        self.full_transcript = []
        self._last_input_transcription = ""
        self.enhancer = AudioEnhancer() if AUDIO_AGC_ENABLED else None

    def stop(self):
        self._running = False

    async def _run_async(self):
        ctx_prompt = ""
        if self.subject_context:
            ctx_prompt = f" The lecture topic / subject is: '{self.subject_context}'. Transcribe all specific academic terminology, code, formulas, and concepts accurately."

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription={},
            output_audio_transcription={},
            system_instruction=types.Content(parts=[types.Part.from_text(
                text=f"You are an English and Russian speech transcriber for academic university lectures and meetings.{ctx_prompt} Ignore background room noise. Never output foreign alphabets like Georgian, Devanagari, or Kannada."
            )])
        )
        self.status_changed.emit("Connecting...")

        try:
            async with self.client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                self.session = session
                self.out_queue = asyncio.Queue()

                t_mic = asyncio.create_task(self.listen_mic())
                t_send = asyncio.create_task(self.send_audio())
                t_recv = asyncio.create_task(self.receive_text())
                self._stream_tasks = [t_mic, t_send, t_recv]

                self.status_changed.emit("Listening...")

                while self._running:
                    await asyncio.sleep(0.1)

                for t in self._stream_tasks:
                    t.cancel()
                await asyncio.gather(*self._stream_tasks, return_exceptions=True)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [MEETING] Stream error: {e}")

        self.status_changed.emit("Generating AI Notes...")
        await self.generate_summary()

    def run(self):
        asyncio.run(self._run_async())

    async def listen_mic(self):
        def audio_callback(indata, frames, time_info, status):
            if not self._running:
                return
            data_bytes = bytes(indata)

            try:
                samples = np.frombuffer(data_bytes, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2) + 1e-6))
                level = min(1.0, rms / 400.0)
                is_hearing = rms > 12.0
                self.audio_level.emit(level, is_hearing)
            except Exception:
                pass

            if AUDIO_AGC_ENABLED and self.enhancer:
                data_bytes = self.enhancer.process(data_bytes)
            try:
                self.out_queue.put_nowait({"data": data_bytes, "mime_type": "audio/pcm;rate=16000"})
            except asyncio.QueueFull:
                pass

        if str(self.device) == "phone":
            print(f"  [MEETING] Using Phone Wireless Mic ({PHONE_IP})")
            await asyncio.to_thread(stream_phone_audio_loop, audio_callback, lambda: self._running)
            return

        try:
            stream = sd.RawInputStream(
                samplerate=SEND_SAMPLE_RATE,
                blocksize=CHUNK_SIZE,
                channels=CHANNELS,
                dtype=FORMAT,
                device=self.device,
                callback=audio_callback
            )
            with stream:
                while self._running:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [MEETING] Error starting mic (device={self.device}): {e}")

    async def send_audio(self):
        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(self.out_queue.get(), timeout=0.2)
                    await self.session.send(input=msg, end_of_turn=False)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def receive_text(self):
        try:
            while self._running:
                turn = self.session.receive()
                async for response in turn:
                    if not self._running:
                        break
                    if response.server_content:
                        if response.server_content.input_transcription:
                            transcript = response.server_content.input_transcription.text
                            if transcript and transcript != self._last_input_transcription:
                                delta = transcript
                                if transcript.startswith(self._last_input_transcription):
                                    delta = transcript[len(self._last_input_transcription):]
                                self._last_input_transcription = transcript

                                clean_delta = clean_stray_scripts(delta)
                                if clean_delta:
                                    self.transcript_updated.emit(clean_delta)

                        if response.server_content.turn_complete:
                            if self._last_input_transcription:
                                cleaned_turn = clean_stray_scripts(self._last_input_transcription).strip()
                                if cleaned_turn:
                                    self.full_transcript.append(cleaned_turn)
                                    self.transcript_updated.emit(" ")
                                self._last_input_transcription = ""
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self._running:
                print(f"  [MEETING] Receive error: {e}")

    async def generate_summary(self):
        if self._last_input_transcription:
            c = clean_stray_scripts(self._last_input_transcription).strip()
            if c:
                self.full_transcript.append(c)
            self._last_input_transcription = ""

        text_content = " ".join(self.full_transcript).strip()
        if not text_content:
            self.summary_ready.emit("# Empty Meeting\n\nNo audio was transcribed.")
            return

        summary = await asyncio.to_thread(generate_ai_summary_sync, text_content, self.subject_context, self.template_name)
        self.summary_ready.emit(summary)


# ─────────────────────────────────────────────────────────────
#  Engine 2: Local Whisper AI Transcriber (CTranslate2)
# ─────────────────────────────────────────────────────────────
class WhisperMeetingWorker(QThread):
    transcript_updated = pyqtSignal(str)
    summary_ready = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    audio_level = pyqtSignal(float, bool)
    recording_saved = pyqtSignal(str)
    capture_finished = pyqtSignal()
    backlog_updated = pyqtSignal(float)

    def __init__(self, device=None, model_name="small", subject_context="", template_name="lecture", user_notes=""):
        super().__init__()
        from annie.whisper_service import get_whisper_service
        self._service = get_whisper_service()
        self._session_id = None
        self._running = True
        self.device = str(device) if device is not None else "default"
        self.model_name = model_name
        self.subject_context = subject_context.strip()
        self.template_name = template_name
        self.user_notes = user_notes.strip()
        self.full_transcript = []
        self.last_metrics = {}
        self.last_error = ""
        self.last_warning = ""
        self.recording_path = ""

    def stop(self):
        self._running = False
        if self._session_id:
            self.status_changed.emit("Finishing remaining transcript...")
            self._service.stop(self._session_id)

    def run(self):
        from pathlib import Path
        import uuid
        from annie import config as cfg
        from annie.whisper_events import consume_session
        if not self._running:
            return
        recording_path = Path(cfg.DATA_DIR) / "recordings" / f"lecture-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.wav"
        try:
            result = consume_session(
                self, mode="record", model_name=self.model_name, device=self.device,
                subject_context=self.subject_context, agc=cfg.AUDIO_AGC_ENABLED,
                recording_path=str(recording_path),
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.status_changed.emit(f"Error: {exc}")
            result = {"had_error": True}
        finally:
            self._running = False
            self.capture_finished.emit()

        text_content = "".join(self.full_transcript).strip()
        if not text_content:
            if self.last_error:
                self.summary_ready.emit(f"# Recording Error\n\n{self.last_error}\n\nSaved audio: {self.recording_path or 'No audio captured'}")
            else:
                self.summary_ready.emit("# Empty Meeting\n\nNo speech was transcribed.")
            return
        if result.get('had_error'):
            detail = self.last_error or 'Audio capture or transcription failed unexpectedly.'
            self.summary_ready.emit(
                "# Incomplete Recording\n\n"
                f"{detail}\n\n"
                f"Saved audio: {self.recording_path or 'No audio captured'}\n\n"
                "AI study notes were not generated because the transcript may be incomplete. "
                "The partial transcript remains available in the Transcript tab."
            )
            self.status_changed.emit("Recording incomplete. Partial transcript and saved audio preserved.")
            return
        self.status_changed.emit("Generating AI Notes...")
        try:
            summary = generate_ai_summary_sync(text_content, self.subject_context, self.template_name, user_notes=self.user_notes)
            warning = result.get('warning') or self.last_warning
            if warning:
                summary = f"> Audio warning: {warning} Saved audio: {self.recording_path}\n\n" + summary
            self.summary_ready.emit(summary)
            if warning:
                self.status_changed.emit("Notes ready with an audio-gap warning. Recording saved locally.")
            else:
                self.status_changed.emit("Notes ready. Recording saved locally.")
        except Exception as exc:
            self.status_changed.emit(f"Error generating notes: {exc}")
            self.summary_ready.emit(f"# Notes Error\n\n{exc}\n\nThe transcript and recorded audio are preserved.")


class AudioFileMeetingWorker(QThread):
    transcript_updated = pyqtSignal(str)
    summary_ready = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    progress_changed = pyqtSignal(int)

    def __init__(self, file_path: str, model_name: str = "small", subject_context: str = "", template_name: str = "lecture", user_notes: str = ""):
        super().__init__()
        from annie.whisper_service import get_whisper_service
        self._service = get_whisper_service()
        self._session_id = None
        self.file_path = file_path
        self.model_name = model_name
        self.subject_context = subject_context.strip()
        self.template_name = template_name
        self.user_notes = user_notes.strip()
        self._running = True
        self.full_transcript = []
        self.last_metrics = {}
        self.last_error = ""

    def stop(self):
        self._running = False
        if self._session_id:
            self._service.stop(self._session_id)

    def run(self):
        from annie.whisper_events import consume_session
        if not self._running:
            return
        if not os.path.isfile(self.file_path):
            self._running = False
            self.status_changed.emit("File not found.")
            return
        try:
            result = consume_session(self, mode="file", model_name=self.model_name,
                                     file_path=self.file_path, subject_context=self.subject_context)
            if result.get('cancelled') or not self._running:
                self.status_changed.emit("Transcription canceled.")
                return
            if result.get('had_error'):
                self.summary_ready.emit(f"# Transcription Error\n\n{self.last_error}")
                return
            full_text = "".join(self.full_transcript).strip()
            if not full_text:
                self.summary_ready.emit("# Empty Recording\n\nNo speech was detected in this file.")
                return
            self.status_changed.emit("Synthesizing AI Notes...")
            summary = generate_ai_summary_sync(full_text, self.subject_context, self.template_name, user_notes=self.user_notes)
            self.summary_ready.emit(summary)
            self.status_changed.emit("Ready")
        except Exception as exc:
            self.status_changed.emit(f"Error: {exc}")
            self.summary_ready.emit(f"# Transcription Error\n\n{exc}")
        finally:
            self._running = False


# Default export
MeetingTranscriberWorker = GeminiMeetingWorker
