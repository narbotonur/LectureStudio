"""Bootstrap the isolated Whisper service after configuring Windows CUDA DLLs."""
import os
import sys
import re

if sys.platform == "win32":
    for path in sys.path:
        for sub in [
            "ctranslate2", "faster_whisper",
            os.path.join("nvidia", "cublas", "bin"),
            os.path.join("nvidia", "cudnn", "bin"),
            os.path.join("nvidia", "cuda_nvrtc", "bin"),
        ]:
            cand = os.path.join(path, sub)
            if os.path.isdir(cand):
                try:
                    os.add_dll_directory(cand)
                    os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
                except Exception:
                    pass


# Known Whisper silence hallucination phrases
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
    if not text:
        return ""
    cleaned = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9\s.,!?:;\-\'\"()\[\]{}+=/*%<>]', '', text)
    cleaned = re.sub(r'<[^>]+>|\[[^\]]+\]', '', cleaned)
    cleaned = re.sub(r'(\b\w+\b)(?:\s+\1){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(\b\w+\s+\w+\b)(?:\s+\1){2,}', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # Filter out silence hallucinations
    lower_t = cleaned.lower()
    for pat in HALLUCINATION_PATTERNS:
        if re.match(pat, lower_t, re.IGNORECASE):
            return ""

    return cleaned

if __name__ == "__main__":
    from annie.whisper_runtime import main
    sys.exit(main(clean_stray_scripts))
