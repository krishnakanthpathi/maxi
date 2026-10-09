"""
Maxi Configuration Manager
Provides unified management for LLM and Voice provider endpoints, API keys, models,
presets (Ollama local, Groq cloud, OpenRouter), and hot-reloading into the running daemon.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import httpx

GLOBAL_ENV_FILE = Path.home() / ".maxi" / ".env"
LOCAL_ENV_FILE = Path(".env")

PRESETS = {
    "ollama": {
        "name": "Ollama (Local Default)",
        "description": "Local offline LLM running on port 11434 with zero API costs",
        "llm_url": "http://localhost:11434/v1",
        "llm_key": "ollama",
        "llm_model": "gemma4:31b-cloud",
        "requires_key": False
    },
    "groq": {
        "name": "Groq (Cloud Ultra-Fast)",
        "description": "Ultra-low latency LPU inference for Llama 3.3",
        "llm_url": "https://api.groq.com/openai/v1",
        "llm_key": "",
        "llm_model": "llama-3.3-70b-versatile",
        "requires_key": True
    },
    "openrouter": {
        "name": "OpenRouter (Cloud Universal)",
        "description": "Multi-provider gateway for Claude, GPT, Llama, and Mistral",
        "llm_url": "https://openrouter.ai/api/v1",
        "llm_key": "",
        "llm_model": "meta-llama/llama-3.3-70b-instruct",
        "requires_key": True
    }
}

VOICE_PRESETS = {
    "groq-whisper": {
        "name": "Groq Whisper (Cloud Default)",
        "description": "Whisper Large v3 Turbo on Groq LPUs (~200ms transcription)",
        "voice_url": "https://api.groq.com/openai/v1",
        "voice_key": "",
        "voice_model": "whisper-large-v3-turbo",
        "requires_key": True
    },
    "local-whisper": {
        "name": "Local Whisper (Local Offline)",
        "description": "Local faster-whisper or whisper.cpp server",
        "voice_url": "http://localhost:8000/v1",
        "voice_key": "local-key",
        "voice_model": "whisper-1",
        "requires_key": False
    }
}

KEY_ALIASES = {
    # LLM aliases
    "llm-url": "OPENAI_BASE_URL",
    "llm_url": "OPENAI_BASE_URL",
    "base-url": "OPENAI_BASE_URL",
    "base_url": "OPENAI_BASE_URL",
    "openai-base-url": "OPENAI_BASE_URL",
    "openai_base_url": "OPENAI_BASE_URL",
    "OPENAI_BASE_URL": "OPENAI_BASE_URL",

    "llm-key": "OPENAI_API_KEY",
    "llm_key": "OPENAI_API_KEY",
    "api-key": "OPENAI_API_KEY",
    "api_key": "OPENAI_API_KEY",
    "openai-api-key": "OPENAI_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "OPENAI_API_KEY": "OPENAI_API_KEY",

    "llm-model": "OPENAI_MODEL",
    "llm_model": "OPENAI_MODEL",
    "model": "OPENAI_MODEL",
    "openai-model": "OPENAI_MODEL",
    "openai_model": "OPENAI_MODEL",
    "OPENAI_MODEL": "OPENAI_MODEL",

    # Voice aliases
    "voice-url": "VOICE_BASE_URL",
    "voice_url": "VOICE_BASE_URL",
    "voice-base-url": "VOICE_BASE_URL",
    "voice_base_url": "VOICE_BASE_URL",
    "VOICE_BASE_URL": "VOICE_BASE_URL",

    "voice-key": "VOICE_API_KEY",
    "voice_key": "VOICE_API_KEY",
    "voice-api-key": "VOICE_API_KEY",
    "voice_api_key": "VOICE_API_KEY",
    "VOICE_API_KEY": "VOICE_API_KEY",

    "voice-model": "VOICE_MODEL",
    "voice_model": "VOICE_MODEL",
    "VOICE_MODEL": "VOICE_MODEL",

    # Audio & hotkey toggles
    "auto-endpoint": "VOICE_AUTO_ENDPOINT",
    "auto_endpoint": "VOICE_AUTO_ENDPOINT",
    "voice_auto_endpoint": "VOICE_AUTO_ENDPOINT",
    "VOICE_AUTO_ENDPOINT": "VOICE_AUTO_ENDPOINT",

    "hotkey": "ENABLE_VOICE_HOTKEY",
    "enable-voice-hotkey": "ENABLE_VOICE_HOTKEY",
    "enable_voice_hotkey": "ENABLE_VOICE_HOTKEY",
    "ENABLE_VOICE_HOTKEY": "ENABLE_VOICE_HOTKEY",
}


def mask_secret(val: Optional[str]) -> str:
    """Masks secret key string for safe terminal display."""
    if not val:
        return "(not set)"
    s = str(val).strip()
    if s.lower() in ("ollama", "sk-local-no-key-required", "local-key", "none"):
        return s
    if len(s) <= 8:
        return "********"
    return f"{s[:6]}...{s[-4:]}"


def get_active_env_file() -> Path:
    """Returns target env file path, creating ~/.maxi/.env if needed."""
    if LOCAL_ENV_FILE.exists() and LOCAL_ENV_FILE.is_file():
        return LOCAL_ENV_FILE
    GLOBAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_ENV_FILE.exists():
        GLOBAL_ENV_FILE.touch()
    return GLOBAL_ENV_FILE


def read_env_values(file_path: Path) -> Dict[str, str]:
    """Parses a .env file into key-value pairs."""
    result: Dict[str, str] = {}
    if not file_path.exists():
        return result
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            result[k] = v
    return result


def write_env_values(file_path: Path, updates: Dict[str, str]) -> None:
    """Updates or appends values in .env file, preserving other lines and comments."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if file_path.exists():
        lines = file_path.read_text(encoding="utf-8").splitlines()

    written_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                written_keys.add(k)
                continue
        new_lines.append(line)

    # Append any remaining keys not found in existing lines
    for k, v in updates.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}")

    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def detect_llm_preset(url: str, model: str) -> str:
    """Detects active LLM preset based on URL and model."""
    url_lower = (url or "").lower()
    model_lower = (model or "").lower()

    if "11434" in url_lower or "localhost" in url_lower and "llama" in model_lower:
        return "ollama"
    if "groq.com" in url_lower:
        return "groq"
    if "openrouter.ai" in url_lower:
        return "openrouter"
    return "custom"


def detect_voice_preset(url: str) -> str:
    """Detects active Voice preset based on URL."""
    url_lower = (url or "").lower()
    if "groq.com" in url_lower:
        return "groq-whisper"
    if "localhost" in url_lower or "127.0.0.1" in url_lower:
        return "local-whisper"
    return "custom"


def get_current_config() -> Dict[str, Any]:
    """Returns combined active settings from environment and config files."""
    from app.config import settings

    llm_preset = detect_llm_preset(settings.openai_base_url, settings.openai_model)
    voice_preset = detect_voice_preset(settings.voice_base_url)

    return {
        "llm_url": settings.openai_base_url,
        "llm_key": settings.openai_api_key,
        "llm_key_masked": mask_secret(settings.openai_api_key),
        "llm_model": settings.openai_model,
        "llm_preset": llm_preset,
        "voice_url": settings.voice_base_url,
        "voice_key": settings.get_voice_api_key(),
        "voice_key_masked": mask_secret(settings.get_voice_api_key()),
        "voice_model": settings.voice_model,
        "voice_preset": voice_preset,
        "auto_endpoint": settings.voice_auto_endpoint,
        "hotkey_enabled": settings.enable_voice_hotkey,
        "env_file": str(get_active_env_file()),
    }


def save_config(updates: Dict[str, str], notify_daemon: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Saves updates to config files and optionally notifies live daemon.
    Returns (success, message).
    """
    from app.config import settings

    # Normalize canonical keys
    canonical_updates: Dict[str, str] = {}
    for k, v in updates.items():
        canonical_k = KEY_ALIASES.get(k, k)
        canonical_updates[canonical_k] = str(v)

    # 1. Update in-memory settings
    for k, v in canonical_updates.items():
        if k == "OPENAI_BASE_URL":
            settings.openai_base_url = v
        elif k == "OPENAI_API_KEY":
            settings.openai_api_key = v
        elif k == "OPENAI_MODEL":
            settings.openai_model = v
        elif k == "VOICE_BASE_URL":
            settings.voice_base_url = v
        elif k == "VOICE_API_KEY":
            settings.voice_api_key = v
        elif k == "VOICE_MODEL":
            settings.voice_model = v
        elif k == "VOICE_AUTO_ENDPOINT":
            settings.voice_auto_endpoint = v.lower() in ("true", "1", "yes")
        elif k == "ENABLE_VOICE_HOTKEY":
            settings.enable_voice_hotkey = v.lower() in ("true", "1", "yes")

    # 2. Write to ~/.maxi/.env
    GLOBAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_env_values(GLOBAL_ENV_FILE, canonical_updates)

    # 3. If local .env exists, keep it in sync
    if LOCAL_ENV_FILE.exists() and LOCAL_ENV_FILE.is_file():
        write_env_values(LOCAL_ENV_FILE, canonical_updates)

    # 4. Notify live daemon if running
    hot_reloaded = False
    if notify_daemon:
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.post("http://127.0.0.1:4848/api/config", json=canonical_updates)
                if resp.status_code == 200:
                    hot_reloaded = True
        except Exception:
            pass

    msg = f"Configuration saved to {GLOBAL_ENV_FILE}"
    if hot_reloaded:
        msg += " (Hot-reloaded into active daemon!)"
    return True, msg
