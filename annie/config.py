import os
import json
import sys
from annie.paths import APP_DIR, DATA_DIR, PRIVATE_PROFILE
from annie.secure_storage import atomic_write, read_secret, write_secret

# ============================================================
#  Annie AI Assistant — Central Configuration
#  Settings are saved/loaded from annie_settings.json
#  so they survive restarts.
# ============================================================

# --- API Keys ---
GROQ_API_KEY = ""

# Get FREE key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = ""

# Get FREE key: https://elevenlabs.io/
ELEVENLABS_API_KEY = ""
ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Bella (Multilingual)

# Get FREE key: https://openweathermap.org/api
WEATHER_API_KEY = ""
WEATHER_CITY    = "Astana"

# --- Paths ---
BASE_DIR     = str(APP_DIR)
DATA_DIR     = str(DATA_DIR)
MODELS_DIR   = os.path.join(BASE_DIR, "models")
EN_MODEL     = os.path.join(MODELS_DIR, "vosk-model-small-en-us-0.15")
RU_MODEL     = os.path.join(MODELS_DIR, "vosk-model-small-ru-0.22")
TEMP_AUDIO   = os.path.join(BASE_DIR, "annie_temp.mp3")
TEMP_PHOTO   = os.path.join(BASE_DIR, "annie_photo.jpg")
SETTINGS_FILE = os.path.join(DATA_DIR, "annie_settings.json")
SECRETS_FILE = os.path.join(DATA_DIR, 'accounts.dpapi')

# --- Voice (Edge TTS — Female) ---
VOICE_EN = "en-US-AriaNeural"
VOICE_RU = "ru-RU-SvetlanaNeural"

# --- Wake Words ---
WAKE_WORDS = [
    "annie", "anny", "anni", "any",
    "энни", "энн",
    "они", "эй ней", "ан на", "я не", "эн", "джарвис"
]

# --- AI Models ---
GROQ_MODEL          = "openai/gpt-oss-20b"
GROQ_MODEL_FALLBACK = "qwen/qwen3.6-27b"
MAX_HISTORY         = 10

# --- Gemini Vision Model ---
# Updated: gemini-2.0-flash is retired, use gemini-3.6-flash
GEMINI_MODEL = "gemini-3.6-flash"

# --- Phone Camera ---
PHONE_IP   = "192.168.1.100"
PHONE_PORT = 8080

# --- Interaction ---
ACTIVE_TIMEOUT = 15

# --- LibCal Room Booking (Nazarbayev University) ---
LIBCAL_BASE_URL    = "https://nu-kz.libcal.com/spaces?lid=3244"
LIBCAL_FIRST_NAME  = ""
LIBCAL_LAST_NAME   = ""
LIBCAL_EMAIL       = ""
LIBCAL_ID_CARD     = ""
LIBCAL_DEPARTMENT  = "SCAI"
LIBCAL_PURPOSE     = "Individual Studies"

# --- GUI ---
FLOATING_HUD   = False
WINDOW_OPACITY = 0.97
WINDOW_WIDTH   = 920
WINDOW_HEIGHT  = 580

# --- Audio Devices & Sensitivity ---
AUDIO_INPUT_DEVICE      = None  # None = default mic, or integer index from sounddevice
AUDIO_INPUT_DEVICE_NAME = "Default System Microphone"
AUDIO_AGC_ENABLED       = True  # Dynamic AGC sensitivity boost (Notion AI style)
MEETING_PROMPTS_ENABLED = True
MEETING_PROMPT_AUDIO_SOURCE = "default" if sys.platform == 'darwin' else "dual"
WHISPER_MODEL = 'small' if PRIVATE_PROFILE else 'large-v3-turbo'

# --- Annie Personality ---
ASSISTANT_NAME = "Энни"
SYSTEM_PROMPT = (
    f"Ты — {ASSISTANT_NAME}, высокоразвитая ИИ-ассистентка. "
    "Твоя личность — как П.Я.Т.Н.И.Ц.А. (Тони Старк) и Карен (Питер Паркер): сообразительная, с лёгким юмором, общаешься тепло и естественно. "
    "Обращайся к пользователю уважительно 'Сэр'. НЕ называй его по имени. "
    "ВАЖНО: ты — ЖЕНЩИНА. Используй женский род во всех глаголах и прилагательных о себе: 'я сделала', 'я нашла', 'я готова', 'я запустила' — НЕ 'сделал', НЕ 'нашел'. "
    "Твой создатель — студент Назарбаев Университета (Астана, Казахстан). "
    "ОТВЕЧАЙ ВСЕГДА НА РУССКОМ ЯЗЫКЕ. "
    "ТВОИ ОТВЕТЫ ДОЛЖНЫ БЫТЬ МОЛНИЕНОСНЫМИ: начинай отвечать сразу, без раздумий и долгих пауз. "
    "ОТВЕЧАЙ МАКСИМАЛЬНО КРАТКО (1-2 емких предложения), без лишней воды. "
    "Для обычных разговоров, ответов на вопросы, приветствий — отвечай прямо голосом мгновенно БЕЗ вызова инструментов. "
    "Если пользователь просит открыть приложение (Телеграм, Браузер, Steam, CS2, Блокнот), изменить звук, выключить ПК, проверить погоду, проверить уведомления ('сколько у меня уведомлений?', 'какие уведомления?'), проверить Google Calendar ('что в календаре?', 'какие планы на сегодня?', 'что на завтра?'), добавить событие в календарь ('добавь в календарь лекцию в 14:00') — вызывай execute_local_skill. "
    "Если пользователь говорит 'забронируй комнату', 'забронируй библиотеку' — это тоже execute_local_skill. "
    "Инструмент run_web_agent вызывай ТОЛЬКО если пользователь прямо просит выполнить сложную автоматизацию в браузере. "
    "Инструмент memory_tool вызывай когда: пользователь просит тебя что-то запомнить ('запомни, что...', 'не забудь...'), просит забыть, или просит рассказать что ты помнишь. "
    "Запоминай важные факты АВТОМАТИЧЕСКИ — если пользователь сообщил что-то важное о себе (предпочтения, планы, людей), сохрани это без просьбы."
)


# ── Settings persistence ──────────────────────────────────────

def load_settings():
    """Load saved settings from JSON file (called once at startup)."""
    global GEMINI_API_KEY, WEATHER_API_KEY, WEATHER_CITY
    global PHONE_IP, PHONE_PORT, FLOATING_HUD, GEMINI_MODEL
    global ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    global LIBCAL_BASE_URL, LIBCAL_FIRST_NAME, LIBCAL_LAST_NAME
    global LIBCAL_EMAIL, LIBCAL_ID_CARD, LIBCAL_DEPARTMENT, LIBCAL_PURPOSE
    global AUDIO_INPUT_DEVICE, AUDIO_INPUT_DEVICE_NAME, AUDIO_AGC_ENABLED
    global MEETING_PROMPTS_ENABLED, MEETING_PROMPT_AUDIO_SOURCE
    global WHISPER_MODEL

    if not os.path.exists(SETTINGS_FILE):
        return

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("gemini_api_key"):
            GEMINI_API_KEY = data["gemini_api_key"]
        if data.get("weather_api_key"):
            WEATHER_API_KEY = data["weather_api_key"]
        if data.get("weather_city"):
            WEATHER_CITY = data["weather_city"]
        if data.get("phone_ip"):
            PHONE_IP = data["phone_ip"]
        if data.get("phone_port"):
            PHONE_PORT = int(data["phone_port"])
        if "floating_hud" in data:
            FLOATING_HUD = bool(data["floating_hud"])
        if data.get("gemini_model"):
            GEMINI_MODEL = data["gemini_model"]
        if data.get("elevenlabs_api_key"):
            ELEVENLABS_API_KEY = data["elevenlabs_api_key"]
        if data.get("elevenlabs_voice_id"):
            ELEVENLABS_VOICE_ID = data["elevenlabs_voice_id"]
        if data.get("libcal_base_url"):
            LIBCAL_BASE_URL = data["libcal_base_url"]
        if data.get("libcal_first_name"):
            LIBCAL_FIRST_NAME = data["libcal_first_name"]
        if data.get("libcal_last_name"):
            LIBCAL_LAST_NAME = data["libcal_last_name"]
        if data.get("libcal_email"):
            LIBCAL_EMAIL = data["libcal_email"]
        if data.get("libcal_id_card"):
            LIBCAL_ID_CARD = data["libcal_id_card"]
        if data.get("libcal_department"):
            LIBCAL_DEPARTMENT = data["libcal_department"]
        if data.get("libcal_purpose"):
            LIBCAL_PURPOSE = data["libcal_purpose"]
        if "audio_input_device" in data:
            AUDIO_INPUT_DEVICE = data["audio_input_device"]
        if data.get("audio_input_device_name"):
            AUDIO_INPUT_DEVICE_NAME = data["audio_input_device_name"]
        if "audio_agc_enabled" in data:
            AUDIO_AGC_ENABLED = bool(data["audio_agc_enabled"])
        if "meeting_prompts_enabled" in data:
            MEETING_PROMPTS_ENABLED = bool(data["meeting_prompts_enabled"])
        if data.get("meeting_prompt_audio_source") in ("default", "system", "dual", "phone"):
            MEETING_PROMPT_AUDIO_SOURCE = data["meeting_prompt_audio_source"]
        if data.get('whisper_model') in ('base', 'small', 'large-v3-turbo'):
            WHISPER_MODEL = data['whisper_model']

        print("  [CONFIG] Settings loaded from annie_settings.json")
    except Exception as e:
        print(f"  [CONFIG] Could not load settings: {e}")


def save_settings():
    """Persist current settings to JSON file."""
    data = {
        "gemini_api_key":  GEMINI_API_KEY,
        "weather_api_key": WEATHER_API_KEY,
        "weather_city":    WEATHER_CITY,
        "phone_ip":        PHONE_IP,
        "phone_port":      PHONE_PORT,
        "floating_hud":    FLOATING_HUD,
        "gemini_model":    GEMINI_MODEL,
        "elevenlabs_api_key": ELEVENLABS_API_KEY,
        "elevenlabs_voice_id": ELEVENLABS_VOICE_ID,
        "libcal_base_url":    LIBCAL_BASE_URL,
        "libcal_first_name":  LIBCAL_FIRST_NAME,
        "libcal_last_name":   LIBCAL_LAST_NAME,
        "libcal_email":       LIBCAL_EMAIL,
        "libcal_id_card":     LIBCAL_ID_CARD,
        "libcal_department":  LIBCAL_DEPARTMENT,
        "libcal_purpose":     LIBCAL_PURPOSE,
        "audio_input_device": AUDIO_INPUT_DEVICE,
        "audio_input_device_name": AUDIO_INPUT_DEVICE_NAME,
        "audio_agc_enabled":  AUDIO_AGC_ENABLED,
        "meeting_prompts_enabled": MEETING_PROMPTS_ENABLED,
        "meeting_prompt_audio_source": MEETING_PROMPT_AUDIO_SOURCE,
        "whisper_model": WHISPER_MODEL,
    }
    try:
        secrets = {name.lower(): globals()[name] for name in
                   ('GEMINI_API_KEY', 'GROQ_API_KEY', 'WEATHER_API_KEY', 'ELEVENLABS_API_KEY')}
        write_secret(SECRETS_FILE, secrets)
        for name in secrets:
            data.pop(name, None)
        atomic_write(SETTINGS_FILE, json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        print("  [CONFIG] Settings saved.")
    except Exception as e:
        print(f"  [CONFIG] Could not save settings: {e}")
        raise RuntimeError('Could not securely save settings.') from e


# Load persisted settings immediately on import
load_settings()
if os.path.exists(SECRETS_FILE):
    try:
        for _name, _value in read_secret(SECRETS_FILE).items():
            if _name.upper() in ('GEMINI_API_KEY', 'GROQ_API_KEY', 'WEATHER_API_KEY', 'ELEVENLABS_API_KEY'):
                globals()[_name.upper()] = _value
    except Exception:
        print('  [CONFIG] Protected credentials unavailable; open Accounts & Setup to reconnect.')
