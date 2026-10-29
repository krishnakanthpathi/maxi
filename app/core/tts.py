"""
Maxi Expressive Text-to-Speech (TTS) Engine (Kokoro Neural TTS + Siri Native Fallback)
Provides low-latency voice synthesis with:
- Real-time HTTP PCM streaming (24kHz 16-bit mono) from Kokoro-FastAPI at the configured endpoint
- Expressive annotation translation ([laugh], [chuckle], [sigh], [hmm], [gasp], [pause], [excited], [thoughtful])
  into Kokoro native IPA vocalizations ([Haha](/həhˈɑː/), [Hmm](/hˈmː/)), [pause:Xs], and [rate:X] tags
- Automatic micro-pause chunk flushing on opening appraisals ("Oh, I got it!", "Aha!") for ~1.1s time-to-first-audio
- Automatic Siri neural/premium voice fallback (Tara, Samantha, Daniel, Karen, Moira, Rishi) when offline
- Non-blocking background playback with instant barge-in interruption
"""

import re
import sys
import time
import shutil
import logging
import threading
import subprocess
from typing import Optional, List, Dict, Any, Callable
import httpx
from app.config import settings

logger = logging.getLogger("maxi.tts")

# Friendly Siri voice aliases mapped to macOS native voice names
SIRI_VOICE_ALIASES: Dict[str, str] = {
    "siri": "Tara",
    "siri-in": "Tara",
    "siri-india": "Tara",
    "tara": "Tara",
    "siri-us": "Samantha",
    "siri-america": "Samantha",
    "samantha": "Samantha",
    "siri-uk": "Daniel",
    "siri-british": "Daniel",
    "daniel": "Daniel",
    "siri-au": "Karen",
    "karen": "Karen",
    "siri-ie": "Moira",
    "moira": "Moira",
    "rishi": "Rishi",
    "aman": "Aman",
}

# Friendly Kokoro voice aliases mapped to Kokoro-82M voice IDs
KOKORO_VOICE_ALIASES: Dict[str, str] = {
    "kokoro": "af_heart",
    "cucuru": "af_heart",
    "heart": "af_heart",
    "bella": "af_bella",
    "nicole": "af_nicole",
    "sarah": "af_sarah",
    "sky": "af_sky",
    "nova": "af_nova",
    "kore": "af_kore",
    "aoede": "af_aoede",
    "alloy": "af_alloy",
    "fenrir": "am_fenrir",
    "michael": "am_michael",
    "puck": "am_puck",
    "adam": "am_adam",
    "echo": "am_echo",
    "eric": "am_eric",
    "liam": "am_liam",
    "onyx": "am_onyx",
    "emma": "bf_emma",
    "isabella": "bf_isabella",
    "alice": "bf_alice",
    "lily": "bf_lily",
    "fable": "bm_fable",
    "george": "bm_george",
    "lewis": "bm_lewis",
    "alpha": "hf_alpha",
    "beta": "hf_beta",
    "omega": "hm_omega",
    "psi": "hm_psi",
    "blend": "af_heart(2)+af_bella(1)",
}

KOKORO_VOICE_PRESETS: Dict[str, Dict[str, str]] = {
    "af_heart": {
        "name": "Kokoro Heart (US Female - Grade A)",
        "voice": "af_heart",
        "locale": "en_US",
        "description": "Flagship warm, expressive Kokoro US female voice (Default)"
    },
    "af_bella": {
        "name": "Kokoro Bella (US Female - Grade A-)",
        "voice": "af_bella",
        "locale": "en_US",
        "description": "Natural conversational US female voice"
    },
    "af_nicole": {
        "name": "Kokoro Nicole (US Female - Grade B-)",
        "voice": "af_nicole",
        "locale": "en_US",
        "description": "Calm, soft-spoken US female voice"
    },
    "am_fenrir": {
        "name": "Kokoro Fenrir (US Male - Grade C+)",
        "voice": "am_fenrir",
        "locale": "en_US",
        "description": "Dynamic, resonant US male voice"
    },
    "am_michael": {
        "name": "Kokoro Michael (US Male - Grade C+)",
        "voice": "am_michael",
        "locale": "en_US",
        "description": "Clear, grounded US male voice"
    },
    "am_puck": {
        "name": "Kokoro Puck (US Male - Grade C+)",
        "voice": "am_puck",
        "locale": "en_US",
        "description": "Upbeat, energetic US male voice"
    },
    "bf_emma": {
        "name": "Kokoro Emma (UK Female - Grade B-)",
        "voice": "bf_emma",
        "locale": "en_GB",
        "description": "Refined British English female voice"
    },
    "bm_fable": {
        "name": "Kokoro Fable (UK Male - Grade C)",
        "voice": "bm_fable",
        "locale": "en_GB",
        "description": "Storyteller British English male voice"
    },
    "hf_alpha": {
        "name": "Kokoro Alpha (IN Female)",
        "voice": "hf_alpha",
        "locale": "en_IN",
        "description": "Indian English female voice"
    },
    "hm_omega": {
        "name": "Kokoro Omega (IN Male)",
        "voice": "hm_omega",
        "locale": "en_IN",
        "description": "Indian English male voice"
    },
}

SIRI_VOICE_PRESETS: Dict[str, Dict[str, str]] = {
    "tara": {
        "name": "Siri Female (Tara - Premium)",
        "voice": "Tara",
        "locale": "en_IN",
        "description": "Apple Siri natural English (India) premium voice"
    },
    "samantha": {
        "name": "Siri Female (Samantha - US)",
        "voice": "Samantha",
        "locale": "en_US",
        "description": "Classic Apple Siri US English voice"
    },
    "daniel": {
        "name": "Siri Male (Daniel - UK)",
        "voice": "Daniel",
        "locale": "en_GB",
        "description": "Apple Siri British English voice"
    },
    "karen": {
        "name": "Siri Female (Karen - AU)",
        "voice": "Karen",
        "locale": "en_AU",
        "description": "Apple Siri Australian English voice"
    },
    "moira": {
        "name": "Siri Female (Moira - IE)",
        "voice": "Moira",
        "locale": "en_IE",
        "description": "Apple Siri Irish English voice"
    },
    "rishi": {
        "name": "Siri Male (Rishi - IN)",
        "voice": "Rishi",
        "locale": "en_IN",
        "description": "Apple Siri Indian English male voice"
    },
    "aman": {
        "name": "Siri Male (Aman - IN)",
        "voice": "Aman",
        "locale": "en_IN",
        "description": "Apple Siri Indian English conversational male voice"
    },
}

KOKORO_VOICE_PREFIX_RE = re.compile(
    r"^(?:af|am|bf|bm|ef|em|ff|hf|hm|if|im|jf|jm|pf|pm|zf|zm)_[a-z0-9_]+(?:\(\d+(?:\.\d+)?\)\+[a-z0-9_()+.]+)*$",
    re.IGNORECASE,
)

# Expressive stage-direction mappings -> Kokoro IPA / Pause / Rate tags
_KOKORO_ANNOTATION_RULES = [
    # Laughs, chuckles, giggles
    (re.compile(r"\[(?:laugh|laughs|laughing)\]|\((?:laugh|laughs|laughing)\)|\*+(?:laughs|laughing)\*+", re.I), "[Haha](/həhˈɑː/)! [pause:0.15s]"),
    (re.compile(r"\[(?:chuckle|chuckles|chuckling)\]|\((?:chuckle|chuckles)\)|\*+(?:chuckles)\*+", re.I), "[Heh-heh](/hˈɛhɛ/), [pause:0.15s]"),
    (re.compile(r"\[(?:giggle|giggles)\]|\((?:giggles)\)", re.I), "[Hee-hee](/hˈiːhiː/)! [pause:0.15s]"),
    # Sighs, gasps, appraisals, thinking sounds
    (re.compile(r"\[(?:sigh|sighs|sighing)\]|\((?:sigh|sighs)\)|\*+(?:sighs)\*+", re.I), "[Haaah](/hˈɑːː/)... [pause:0.25s]"),
    (re.compile(r"\[(?:gasp|gasps|wow)\]|\((?:gasps)\)", re.I), "[Oh](/ˈoʊ/)! [pause:0.15s]"),
    (re.compile(r"\[(?:hmm|hm|thinking|pondering)\]", re.I), "[Hmm](/hˈmː/)... [pause:0.2s]"),
    (re.compile(r"\[(?:uh|um|uhm|hesitate|erm)\]", re.I), "[Uhm](/ˈʌm/), [pause:0.15s]"),
    (re.compile(r"\[(?:aha|appraisal|got it)\]", re.I), "Oh, I got it! [pause:0.15s]"),
    # Natural pauses / beats
    (re.compile(r"\[(?:short\s*pause|micro\s*pause|beat)\]", re.I), "[pause:0.15s]"),
    (re.compile(r"\[(?:long\s*pause)\]", re.I), "[pause:0.6s]"),
    (re.compile(r"\[(?:pause|wait)\]", re.I), "[pause:0.3s]"),
    # Prosody / pacing shifts
    (re.compile(r"\[(?:excited|cheerful|fast|upbeat)\]", re.I), "[rate:1.12]"),
    (re.compile(r"\[(?:thoughtful|slow|calm|soft|empathetic)\]", re.I), "[rate:0.88]"),
    (re.compile(r"\[(?:normal|reset)\]", re.I), "[rate:1.0]"),
]

# Fallback rules when speaking through macOS `say` (Siri) so brackets are never read literally
_SIRI_ANNOTATION_RULES = [
    (re.compile(r"\[(?:laugh|laughs|laughing)\]|\((?:laugh|laughs|laughing)\)|\*+(?:laughs|laughing)\*+", re.I), "Haha! "),
    (re.compile(r"\[(?:chuckle|chuckles|chuckling)\]|\((?:chuckle|chuckles)\)|\*+(?:chuckles)\*+", re.I), "Heh, "),
    (re.compile(r"\[(?:giggle|giggles)\]|\((?:giggles)\)", re.I), "Hee-hee! "),
    (re.compile(r"\[(?:sigh|sighs|sighing)\]|\((?:sigh|sighs)\)|\*+(?:sighs)\*+", re.I), "Ahh... "),
    (re.compile(r"\[(?:gasp|gasps|wow)\]|\((?:gasps)\)", re.I), "Oh! "),
    (re.compile(r"\[(?:hmm|hm|thinking|pondering)\]", re.I), "Hmm... "),
    (re.compile(r"\[(?:uh|um|uhm|hesitate|erm)\]", re.I), "Uhm, "),
    (re.compile(r"\[(?:aha|appraisal|got it)\]", re.I), "Oh, I got it! "),
    (re.compile(r"\[(?:short\s*pause|micro\s*pause|long\s*pause|pause|beat|wait)(?::[^\]]+)?\]", re.I), "... "),
    (re.compile(r"\[(?:rate|baserate|voice|excited|cheerful|fast|upbeat|thoughtful|slow|calm|soft|empathetic|normal|reset)(?::[^\]]+)?\]", re.I), ""),
    (re.compile(r"\[([^\[\]]+)\]\(\/[^\/\(\)]+\/\)", re.I), r"\1"),
]

# Opening appraisal pattern to auto-inject a micro-flush [pause:0.15s] so Kokoro streams the first phrase in ~1.1s
_OPENING_APPRAISAL_RE = re.compile(
    r"^((?:Oh,?\s+I\s+got\s+it|Oh,?\s+got\s+it|Aha,?\s+right|Aha|Oh,?\s+nice|Oh,?\s+right|Hmm,?\s+let(?:'s|\s+me)\s+see|Got\s+it|Sure\s+thing|Right|Oh,?\s+okay)[!.,?]+)\s+(?!\[pause:)",
    re.I,
)


OLLAMA_VOICE_ALIASES: Dict[str, str] = {
    "phonon": "phonon",
    "hugh": "Hugh",
    "ollama": "phonon",
}


def is_ollama_voice(voice: Optional[str]) -> bool:
    """Returns True if the given voice name or active provider targets Ollama speech (e.g. phonon)."""
    if voice:
        v = voice.strip().lower()
        if v in SIRI_VOICE_ALIASES or v in SIRI_VOICE_PRESETS:
            return False
        if v in KOKORO_VOICE_ALIASES or v in KOKORO_VOICE_PRESETS or KOKORO_VOICE_PREFIX_RE.match(v):
            return False
        if v in ("phonon", "ollama", "hugh") or v in OLLAMA_VOICE_ALIASES:
            return True
    provider = getattr(settings, "tts_provider", "").lower().strip()
    return provider in ("ollama", "phonon")


def is_kokoro_voice(voice: Optional[str]) -> bool:
    """Returns True if the given voice name or alias targets Kokoro Neural TTS."""
    if voice:
        v = voice.strip().lower()
        if v in SIRI_VOICE_ALIASES or v in SIRI_VOICE_PRESETS:
            return False
        if v in ("phonon", "ollama", "hugh") or v in OLLAMA_VOICE_ALIASES:
            return False
        if v in KOKORO_VOICE_ALIASES or v in KOKORO_VOICE_PRESETS or KOKORO_VOICE_PREFIX_RE.match(v):
            return True
    provider = getattr(settings, "tts_provider", "kokoro").lower().strip()
    return provider == "kokoro"


def resolve_siri_voice(requested_voice: Optional[str] = None) -> str:
    """Resolves a voice alias or name (e.g. 'siri', 'tara', 'kokoro', 'heart') to its canonical voice ID."""
    if is_ollama_voice(requested_voice):
        default_voice = "Hugh"
    else:
        default_voice = "af_heart"
    raw = (requested_voice or getattr(settings, "tts_voice", default_voice) or default_voice).strip()
    lookup = raw.lower()
    if lookup in SIRI_VOICE_ALIASES:
        return SIRI_VOICE_ALIASES[lookup]
    if lookup in KOKORO_VOICE_ALIASES:
        return KOKORO_VOICE_ALIASES[lookup]
    if lookup in OLLAMA_VOICE_ALIASES:
        return OLLAMA_VOICE_ALIASES[lookup]
    return raw


def translate_expressive_annotations(text: str, for_kokoro: bool = True) -> str:
    """
    Translates inline expressive annotations ([laugh], [chuckle], [sigh], [hmm], [pause], [excited], etc.)
    into Kokoro-native IPA phoneme tags + [pause:Xs] + [rate:X] tags (or clean Siri prose when for_kokoro=False).
    """
    if not text or not text.strip():
        return ""

    s = text.strip()
    rules = _KOKORO_ANNOTATION_RULES if for_kokoro else _SIRI_ANNOTATION_RULES
    for pattern, replacement in rules:
        s = pattern.sub(replacement, s)

    if for_kokoro:
        # Auto-insert a 0.15s micro-pause after short opening appraisals ("Oh, I got it!", "Aha!")
        # so Kokoro flushes the opening chunk in ~1.1s while synthesizing the remainder in parallel.
        s = _OPENING_APPRAISAL_RE.sub(r"\1 [pause:0.15s] ", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_speech_and_display_text(text: str) -> tuple[str, str]:
    """
    Separates the spoken summary (for Siri TTS) from the written content (for the Notch HUD).
    Supports:
    1. Explicit <speech>...</speech> tags.
    2. Explicit 'Speech: ...' / 'Spoken: ...' lines.
    3. Without an explicit spoken summary, preserve the original content.
    """
    if not text or not text.strip():
        return "", ""

    raw = text.strip()

    # 1. Explicit <speech>...</speech> tag
    speech_match = re.search(r"<speech>([\s\S]*?)</speech>", raw, re.IGNORECASE)
    if speech_match:
        speech = speech_match.group(1).strip()
        display = re.sub(r"<speech>[\s\S]*?</speech>", "", raw, flags=re.IGNORECASE).strip()
        return speech, display

    # 2. Explicit 'Speech: ...' or 'Spoken: ...' line
    speech_line_match = re.search(r"^(?:Speech|Spoken):\s*(.+)$", raw, re.IGNORECASE | re.MULTILINE)
    if speech_line_match:
        speech = speech_line_match.group(1).strip()
        display = re.sub(r"^(?:Speech|Spoken):\s*.+$\n?", "", raw, flags=re.IGNORECASE | re.MULTILINE).strip()
        return speech, display

    # Sentence guessing can mistake list numbers, abbreviations, and expressive
    # annotations for an entire answer. The sanitizer applies the length limit.
    return raw, raw


def clean_text_for_tts(text: str, max_chars: int = 240, preserve_annotations: bool = False) -> str:
    """
    Sanitizes raw LLM output into clean, natural conversational prose suitable for Siri TTS.
    - Uses an explicit spoken summary when supplied with a visual audit card.
    - Removes code blocks, inline backticks, markdown links, raw URLs, and bullet points.
    - Caps speech length to snappy, single-breath answers (~1-2 sentences).
    """
    if not text or not text.strip():
        return ""

    # Isolate spoken summary from visual notch card
    speech_only, _ = extract_speech_and_display_text(text)
    s = speech_only.strip() if speech_only else text.strip()

    # 1. Remove fenced code blocks ```...```
    s = re.sub(r"```[\s\S]*?```", " ", s)

    # 2. Convert markdown links [label](https://...) -> label
    s = re.sub(r"\[([^\]]+)\]\((?!\/[^\/)]+\/\))[^\)]+\)", r"\1", s)

    # 3. Remove raw HTTP/HTTPS/file URLs and clean trailing colons before URLs
    s = re.sub(r":\s*https?://\S+", ".", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"file://\S+", "", s)

    # 4. Strip inline code backticks, bold, italics, headings, bullet markers
    s = s.replace("`", "")
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    if not preserve_annotations:
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
    else:
        s = re.sub(r"\*(?!(?:laugh|chuckle|sigh|giggle|gasp)[a-z]*\*)([^*]+)\*", r"\1", s, flags=re.I)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", s, flags=re.MULTILINE)

    # 5. Strip emojis and non-speech dingbats
    s = re.sub(
        r"[\U00010000-\U0010ffff"
        r"\u2600-\u27bf"
        r"\u2300-\u23ff"
        r"\u2b50\u2705\u274c\u26a1\ufe0f]+",
        " ",
        s,
    )

    # 6. Collapse whitespace and newlines into natural sentence pauses
    s = re.sub(r"[\r\n]+", ". ", s)
    s = re.sub(r"(?:\.\s*){2,}", "... " if preserve_annotations else ". ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 7. Cap length at 1-2 sentences so voice replies remain snappy
    if len(s) > max_chars:
        truncated = s[:max_chars]
        last_period = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
        if last_period > max_chars // 2:
            s = truncated[: last_period + 1].strip()
        else:
            s = truncated.strip() + "."

    return s


# Inline child worker script for Kokoro-FastAPI neural audio playback via native afplay with live levels
_KOKORO_STREAM_PLAYER_SCRIPT = r"""
import sys, json, urllib.request, os, subprocess, time, wave
try:
    import numpy as np
except Exception:
    np = None

url, voice, speed, text = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
endpoint = url.rstrip("/") + "/audio/speech"
payload = json.dumps({
    "model": "kokoro",
    "input": text,
    "voice": voice,
    "response_format": "wav",
    "speed": speed,
    "allow_voice_tags": True,
}).encode("utf-8")

req = urllib.request.Request(
    endpoint,
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    tmp_path = f"/tmp/maxi_kokoro_{os.getpid()}.wav"
    with open(tmp_path, "wb") as f:
        f.write(data)

    pcm = None
    sr = 24000
    try:
        with wave.open(tmp_path, "rb") as wf:
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw_frames = wf.readframes(wf.getnframes())
        if np is not None:
            if sw == 2:
                pcm = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                pcm = np.frombuffer(raw_frames, dtype=np.float32)
            if n_ch > 1:
                pcm = pcm[::n_ch]
    except Exception:
        pcm = None

    sys.stdout.write("PLAYING\n")
    sys.stdout.flush()

    player = None
    try:
        if sys.platform == "darwin":
            player = subprocess.Popen(["afplay", tmp_path])
        elif sys.platform.startswith("win"):
            ps = f"(New-Object Media.SoundPlayer '{tmp_path}').PlaySync()"
            player = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
        else:
            player = subprocess.Popen(["aplay", tmp_path])

        start_time = time.time()
        chunk_dur = 0.03
        chunk_samples = int(sr * chunk_dur)
        band_freqs = [(70.0, 250.0), (250.0, 650.0), (650.0, 1600.0), (1600.0, 3500.0), (3500.0, 7000.0)]

        while player.poll() is None:
            if pcm is not None and np is not None:
                t_now = time.time() - start_time
                idx = int(t_now * sr)
                if idx < len(pcm):
                    chunk = pcm[idx : idx + chunk_samples]
                    if len(chunk) > 0:
                        rms = float(np.sqrt(np.mean(np.square(chunk))))
                        if rms < 0.003:
                            levels = [0.1, 0.1, 0.1, 0.1, 0.1]
                        else:
                            n_s = len(chunk)
                            w = np.hanning(n_s).astype(np.float32)
                            fft = np.abs(np.fft.rfft(chunk * w))
                            n_b = len(fft)
                            freq_bin = (sr / 2.0) / max(1, n_b - 1)
                            levels = []
                            overall = min(1.0, max(0.12, (rms * 7.0) ** 0.65))
                            for lo, hi in band_freqs:
                                blo = max(0, int(lo / freq_bin))
                                bhi = min(n_b, max(blo + 1, int(hi / freq_bin)))
                                sub = fft[blo:bhi]
                                mag = float(np.mean(sub)) if len(sub) > 0 else 0.0
                                norm = min(1.0, max(0.10, (mag * 12.0) ** 0.65))
                                blended = 0.55 * norm + 0.45 * overall
                                levels.append(round(float(min(1.0, max(0.10, blended))), 3))
                        sys.stdout.write("L " + " ".join(str(x) for x in levels) + "\n")
                        sys.stdout.flush()
            time.sleep(chunk_dur)
    finally:
        if player is not None and player.poll() is None:
            try:
                player.kill()
            except Exception:
                pass
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
except Exception as e:
    sys.stderr.write(f"Kokoro player error: {e}\n")
    sys.exit(2)
"""

# Inline child worker script for Ollama speech (e.g. phonon) neural audio playback via native afplay with live levels
_OLLAMA_STREAM_PLAYER_SCRIPT = r"""
import sys, json, urllib.request, os, subprocess, time, wave
try:
    import numpy as np
except Exception:
    np = None

url, model, voice, text = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
endpoint = url.rstrip("/") + "/audio/speech"
body = {"model": model, "input": text}
if voice and voice.lower() not in ("none", "default", "phonon", "ollama", ""):
    body["voice"] = voice
payload = json.dumps(body).encode("utf-8")

req = urllib.request.Request(
    endpoint,
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    tmp_path = f"/tmp/maxi_ollama_{os.getpid()}.wav"
    with open(tmp_path, "wb") as f:
        f.write(data)

    pcm = None
    sr = 24000
    try:
        with wave.open(tmp_path, "rb") as wf:
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw_frames = wf.readframes(wf.getnframes())
        if np is not None:
            if sw == 2:
                pcm = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                pcm = np.frombuffer(raw_frames, dtype=np.float32)
            if n_ch > 1:
                pcm = pcm[::n_ch]
    except Exception:
        pcm = None

    sys.stdout.write("PLAYING\n")
    sys.stdout.flush()

    player = None
    try:
        if sys.platform == "darwin":
            player = subprocess.Popen(["afplay", tmp_path])
        elif sys.platform.startswith("win"):
            ps = f"(New-Object Media.SoundPlayer '{tmp_path}').PlaySync()"
            player = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
        else:
            player = subprocess.Popen(["aplay", tmp_path])

        start_time = time.time()
        chunk_dur = 0.03
        chunk_samples = int(sr * chunk_dur)
        band_freqs = [(70.0, 250.0), (250.0, 650.0), (650.0, 1600.0), (1600.0, 3500.0), (3500.0, 7000.0)]

        while player.poll() is None:
            if pcm is not None and np is not None:
                t_now = time.time() - start_time
                idx = int(t_now * sr)
                if idx < len(pcm):
                    chunk = pcm[idx : idx + chunk_samples]
                    if len(chunk) > 0:
                        rms = float(np.sqrt(np.mean(np.square(chunk))))
                        if rms < 0.003:
                            levels = [0.1, 0.1, 0.1, 0.1, 0.1]
                        else:
                            n_s = len(chunk)
                            w = np.hanning(n_s).astype(np.float32)
                            fft = np.abs(np.fft.rfft(chunk * w))
                            n_b = len(fft)
                            freq_bin = (sr / 2.0) / max(1, n_b - 1)
                            levels = []
                            overall = min(1.0, max(0.12, (rms * 7.0) ** 0.65))
                            for lo, hi in band_freqs:
                                blo = max(0, int(lo / freq_bin))
                                bhi = min(n_b, max(blo + 1, int(hi / freq_bin)))
                                sub = fft[blo:bhi]
                                mag = float(np.mean(sub)) if len(sub) > 0 else 0.0
                                norm = min(1.0, max(0.10, (mag * 12.0) ** 0.65))
                                blended = 0.55 * norm + 0.45 * overall
                                levels.append(round(float(min(1.0, max(0.10, blended))), 3))
                        sys.stdout.write("L " + " ".join(str(x) for x in levels) + "\n")
                        sys.stdout.flush()
            time.sleep(chunk_dur)
    finally:
        if player is not None and player.poll() is None:
            try:
                player.kill()
            except Exception:
                pass
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
except Exception as e:
    sys.stderr.write(f"Ollama speech error: {e}\n")
    sys.exit(2)
"""


class TTSService:
    """Manages non-blocking Kokoro Neural TTS & Siri TTS playback, barge-in cancellation, and echo suppression."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._is_speaking: bool = False
        self._last_speech_end_time: float = 0.0
        self._cooldown_seconds: float = 0.45
        self._broadcast_cb: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_broadcast_callback(self, cb: Callable[[Dict[str, Any]], None]):
        """Registers callback to broadcast TTS state events to WebSocket HUD clients."""
        self._broadcast_cb = cb

    @property
    def is_speaking(self) -> bool:
        """True if TTS audio is currently playing."""
        return self._is_speaking

    def is_active_or_cooldown(self) -> bool:
        """
        True if TTS is currently speaking OR within the post-speech acoustic cooldown window.
        """
        if self._is_speaking:
            return True
        if (time.time() - self._last_speech_end_time) < self._cooldown_seconds:
            return True
        return False

    def stop(self):
        """Immediately stops any active TTS speech (barge-in support)."""
        with self._lock:
            proc = self._proc
            self._proc = None
            was_speaking = self._is_speaking
            self._is_speaking = False
            if was_speaking:
                self._last_speech_end_time = time.time()

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if was_speaking and self._broadcast_cb:
            try:
                self._broadcast_cb({"event": "tts_stop"})
            except Exception:
                pass

    def speak(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[int] = None,
        block: bool = False,
    ) -> str:
        """
        Sanitizes, translates expressive annotations, and speaks text aloud using Kokoro Neural TTS or Siri.
        Returns the sanitized spoken text.
        """
        if not getattr(settings, "enable_tts", True):
            return ""

        resolved_voice = resolve_siri_voice(voice)
        use_kokoro = is_kokoro_voice(resolved_voice)

        clean_text = clean_text_for_tts(text, preserve_annotations=use_kokoro)
        if not clean_text:
            return ""

        # Cancel any ongoing speech first
        self.stop()

        resolved_rate = rate or getattr(settings, "tts_rate", 190) or 190

        if block:
            self._run_speech_sync(clean_text, resolved_voice, resolved_rate)
        else:
            t = threading.Thread(
                target=self._run_speech_sync,
                args=(clean_text, resolved_voice, resolved_rate),
                daemon=True,
            )
            t.start()

        return clean_text

    def _run_speech_sync(self, clean_text: str, voice: str, rate: int):
        use_ollama = is_ollama_voice(voice)
        use_kokoro = is_kokoro_voice(voice) and not use_ollama
        synthesized_text = (
            translate_expressive_annotations(clean_text, for_kokoro=True)
            if use_kokoro
            else clean_text
        )

        cmd = self._build_tts_command(synthesized_text, voice, rate)
        if not cmd:
            logger.warning("No TTS backend available on this system.")
            return

        if use_ollama:
            logger.info(f"🔊 Ollama Phonon TTS ({voice}): \"{synthesized_text}\"")
        elif use_kokoro:
            speed = round(max(0.5, min(2.5, rate / 190.0)), 2)
            logger.info(f"🔊 Kokoro Neural TTS ({voice} @ {speed}x): \"{synthesized_text}\"")
        else:
            logger.info(f"🔊 Siri TTS ({voice} @ {rate}wpm): \"{synthesized_text}\"")

        if sys.platform == "darwin":
            # Give CoreAudio a brief 60ms breath to release device buffers if a feedback chime just completed
            time.sleep(0.06)

        is_stream_worker = bool(use_kokoro or use_ollama)
        with self._lock:
            self._is_speaking = True
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE if is_stream_worker else subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc = self._proc
            except Exception as e:
                logger.error(f"Failed to launch TTS process: {e}")
                self._is_speaking = False
                self._proc = None
                return

        start_broadcasted = False
        if is_stream_worker and proc.stdout:
            try:
                while self._is_speaking and proc.poll() is None:
                    raw_line = proc.stdout.readline()
                    if not raw_line:
                        break
                    line_str = (raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore")).strip()
                    if line_str == "PLAYING":
                        if not start_broadcasted and self._broadcast_cb:
                            self._broadcast_cb({
                                "event": "tts_start",
                                "text": clean_text,
                                "voice": voice,
                            })
                            start_broadcasted = True
                    elif line_str.startswith("L "):
                        parts = line_str[2:].strip().split()
                        if len(parts) == 5 and self._broadcast_cb and self._is_speaking:
                            try:
                                levels = [float(p) for p in parts]
                                self._broadcast_cb({
                                    "event": "audio_level",
                                    "levels": levels,
                                    "speaking": True,
                                })
                            except Exception:
                                pass
            except Exception:
                pass

        if not start_broadcasted and self._broadcast_cb:
            try:
                self._broadcast_cb({
                    "event": "tts_start",
                    "text": clean_text,
                    "voice": voice,
                })
                start_broadcasted = True
            except Exception:
                pass

        try:
            proc.wait()
            # Automatic fallback if Kokoro server is unreachable or macOS voice is missing
            with self._lock:
                should_fallback = self._is_speaking and proc.returncode not in (0, -15, -9)

            if should_fallback and sys.platform == "darwin" and shutil.which("say"):
                siri_fallback_text = translate_expressive_annotations(clean_text, for_kokoro=False)
                logger.warning(
                    f"TTS voice '{voice}' exited with code {proc.returncode}; falling back to macOS Siri voice."
                )
                fallback_cmd = (
                    ["say", "-v", "Tara", "-r", str(rate), siri_fallback_text]
                    if (use_kokoro or use_ollama)
                    else ["say", "-r", str(rate), siri_fallback_text]
                )
                with self._lock:
                    if self._is_speaking:
                        self._proc = subprocess.Popen(
                            fallback_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        proc = self._proc
                if not start_broadcasted and self._broadcast_cb:
                    try:
                        self._broadcast_cb({
                            "event": "tts_start",
                            "text": clean_text,
                            "voice": "Tara",
                        })
                    except Exception:
                        pass
                proc.wait()
        except Exception as e:
            logger.debug(f"TTS process interrupted: {e}")
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                    self._is_speaking = False
                    self._last_speech_end_time = time.time()

            if self._broadcast_cb:
                try:
                    self._broadcast_cb({"event": "tts_stop"})
                except Exception:
                    pass

    def _build_tts_command(self, text: str, voice: str, rate: int) -> Optional[List[str]]:
        if is_ollama_voice(voice):
            base_url = getattr(settings, "tts_base_url", None)
            if not base_url or "8880" in base_url:
                base_url = (getattr(settings, "openai_base_url", None) or "http://localhost:11434/v1").rstrip("/")
            model = getattr(settings, "tts_model", "phonon") or "phonon"
            return [
                sys.executable,
                "-c",
                _OLLAMA_STREAM_PLAYER_SCRIPT,
                base_url,
                model,
                voice,
                text,
            ]

        if is_kokoro_voice(voice):
            base_url = getattr(settings, "tts_base_url", "http://127.0.0.1:8880/v1")
            speed = round(max(0.5, min(2.5, rate / 190.0)), 2)
            return [
                sys.executable,
                "-c",
                _KOKORO_STREAM_PLAYER_SCRIPT,
                base_url,
                voice,
                str(speed),
                text,
            ]

        siri_text = translate_expressive_annotations(text, for_kokoro=False) if "[" in text else text
        if sys.platform == "darwin" and shutil.which("say"):
            return ["say", "-v", voice, "-r", str(rate), siri_text]
        elif sys.platform.startswith("win"):
            safe_text = siri_text.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{safe_text}');"
            )
            return ["powershell", "-NoProfile", "-Command", ps]
        else:
            for bin_name in ("spd-say", "espeak-ng", "espeak"):
                if shutil.which(bin_name):
                    return [bin_name, siri_text]
        return None

    def list_kokoro_remote_voices(self) -> List[str]:
        """Fetches live voice IDs from the remote Kokoro-FastAPI server if reachable."""
        base_url = getattr(settings, "tts_base_url", "http://127.0.0.1:8880/v1").rstrip("/")
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{base_url}/audio/voices")
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data.get("voices", [])
                    return [v["id"] if isinstance(v, dict) else str(v) for v in raw]
        except Exception:
            pass
        return list(KOKORO_VOICE_PRESETS.keys())

    def list_available_voices(self) -> List[Dict[str, str]]:
        """Lists available English voices on macOS or returns presets."""
        voices: List[Dict[str, str]] = []
        if sys.platform == "darwin" and shutil.which("say"):
            try:
                out = subprocess.check_output(["say", "-v", "?"], text=True, timeout=3.0)
                seen = set()
                for line in out.splitlines():
                    if "#" not in line:
                        continue
                    left, sample = line.split("#", 1)
                    parts = left.strip().rsplit(None, 1)
                    if len(parts) != 2:
                        continue
                    v_name, locale = parts[0].strip(), parts[1].strip()
                    if locale.startswith("en_") and v_name not in seen:
                        seen.add(v_name)
                        voices.append({
                            "name": v_name,
                            "locale": locale,
                            "sample": sample.strip(),
                        })
            except Exception as e:
                logger.debug(f"Failed listing macOS voices: {e}")
        return voices


tts_service = TTSService()
