import json
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from app.config import settings
from app.core.agent import agent
from app.core.skills import skill_registry, Skill

router = APIRouter()


class PromptRequest(BaseModel):
    text: str = Field(..., description="Prompt or query text")
    source: Optional[str] = Field("text", description="Source: 'text', 'voice', or client identifier")


class VoiceWebhookRequest(BaseModel):
    transcript: str = Field(..., description="Transcribed voice text")
    client: Optional[str] = Field("external_voice_plugin", description="e.g. whisperflow, willow")


class SkillToggleRequest(BaseModel):
    name: str
    enabled: bool


@router.get("/health")
async def health_check():
    import os
    from app import __version__
    return {"status": "ok", "service": "Maxi Agent Daemon", "pid": os.getpid(), "version": __version__}


@router.post("/prompt")
async def handle_prompt(request: PromptRequest):
    """Stateless text and UI prompt endpoint."""
    try:
        from app.core.tts import tts_service
        src = request.source or "text"
        result = await agent.run(prompt=request.text, source=src)
        out = result.get("output", "")
        if out and getattr(settings, "enable_tts", True) and (src.startswith("voice") or getattr(settings, "tts_speak_all_sources", False)):
            tts_service.speak(out)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/webhook")
async def handle_voice_webhook(request: VoiceWebhookRequest):
    """Direct webhook ingest for voice apps (Whisperflow, Willow, etc.)."""
    try:
        from app.core.tts import tts_service
        result = await agent.run(
            prompt=request.transcript,
            source=f"voice:{request.client}"
        )
        out = result.get("output", "")
        if out and getattr(settings, "enable_tts", True):
            tts_service.speak(out)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/clear")
async def clear_context():
    """Start a new chat while retaining deliberately saved long-term memories."""
    from app.core.voice_service import voice_service
    voice_service.abort_current_command(reason="new_chat")
    agent.clear_history()
    return {"status": "cleared", "message": "Conversation history reset to empty."}


@router.post("/voice/cancel")
async def cancel_voice():
    """Immediately abort any active recording, STT transcription, or LLM agent processing."""
    from app.core.voice_service import voice_service
    voice_service.abort_current_command(reason="esc")
    return {"status": "cancelled", "message": "Active voice/agent execution aborted."}


@router.post("/voice/start")
async def start_voice(locked: bool = True):
    """Start hands-free voice recording via API or HUD UI."""
    from app.core.voice_service import voice_service
    voice_service.start_recording(locked=locked)
    return {"status": "recording", "locked": locked}


@router.post("/voice/stop")
async def stop_voice():
    """Stop active voice recording and process speech."""
    from app.core.voice_service import voice_service
    voice_service.stop_recording()
    return {"status": "processing"}


_last_voice_toggle = 0.0


@router.post("/voice/toggle")
async def toggle_voice():
    """Toggle voice recording on/off with debouncing to prevent key-repeat glitches."""
    global _last_voice_toggle
    now = time.monotonic()
    from app.core.voice_service import voice_service

    if now - _last_voice_toggle < 0.45:
        return {"status": "recording" if voice_service.is_ptt_recording else "processing", "debounced": True}

    if voice_service.is_ptt_recording:
        if time.time() - voice_service.ptt_press_time < 0.4:
            return {"status": "recording", "debounced": True}
        _last_voice_toggle = now
        voice_service.stop_recording()
        return {"status": "processing"}
    else:
        _last_voice_toggle = now
        voice_service.start_recording(locked=True)
        return {"status": "recording"}


@router.get("/skills", response_model=List[Skill])
async def list_skills():
    return skill_registry.list_skills()


@router.post("/skills/toggle")
async def toggle_skill(request: SkillToggleRequest):
    skill = skill_registry.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")
    skill.enabled = request.enabled
    return {"status": "updated", "skill": skill}


@router.get("/mcp/tools")
async def list_mcp_tools():
    """List all loaded MCP tools currently available to the agent."""
    from app.core.mcp_client import mcp_manager
    tools = mcp_manager.get_tools()
    return {
        "count": len(tools),
        "tools": [{"name": t.name, "description": t.description} for t in tools]
    }


@router.get("/history")
async def get_history(limit: int = Query(50, ge=1, le=500)):
    """Fetch recent conversation turns from the audit log."""
    history_file = Path(settings.history_file_path)
    if not history_file.exists():
        return {"count": 0, "history": []}

    records = []
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        # Return newest first
        recent = records[-limit:][::-1]
        return {"count": len(recent), "history": recent}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed reading history: {e}")


@router.post("/reload")
async def reload_configuration():
    """Hot-reload .env, settings, skills from .maxi/skills/*.md and MCP servers from .maxi/mcp_config.json."""
    from pathlib import Path
    from dotenv import load_dotenv
    from app.config import settings, Settings
    from app.core.mcp_client import mcp_manager

    # 1. Reload environment variables from ~/.maxi/.env and .env
    env_file = Path.home() / ".maxi" / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=True)
    if Path(".env").exists():
        load_dotenv(dotenv_path=".env", override=True)

    # 2. Reload Settings object in-place so all modules referencing settings pick up new values
    new_settings = Settings()
    for k, v in new_settings.model_dump().items():
        setattr(settings, k, v)

    # 3. Reload skills and MCP servers
    skill_registry.reload()
    await mcp_manager.connect_all()
    tools = mcp_manager.get_tools()

    # 4. Refresh voice service connections/caches
    from app.core.voice_service import voice_service
    if voice_service:
        voice_service.refresh_config()

    return {
        "status": "reloaded",
        "model": settings.openai_model,
        "tts_provider": getattr(settings, "tts_provider", "kokoro"),
        "tts_voice": getattr(settings, "tts_voice", "Hugh"),
        "skills_count": len(skill_registry.list_skills()),
        "mcp_tools_count": len(tools)
    }


@router.post("/restart")
async def restart_daemon():
    """Restarts the Maxi background daemon."""
    import sys
    import subprocess
    import asyncio

    async def _do_restart():
        await asyncio.sleep(0.3)
        py = sys.executable
        subprocess.Popen([py, "-m", "app.cli", "restart"], start_new_session=True)

    asyncio.create_task(_do_restart())
    return {"status": "restarting"}


class SoundPlayRequest(BaseModel):
    sound: str = Field(..., description="Name or relative file path of the sound to play")


class SoundSetRequest(BaseModel):
    start_sound: Optional[str] = Field(None, description="Sound to play when recording starts")
    release_sound: Optional[str] = Field(None, description="Sound to play when recording stops/sends")
    finish_sound: Optional[str] = Field(None, description="Sound to play when result is ready")
    auto_endpoint: Optional[bool] = Field(None, description="Enable/disable VAD silence auto-endpointing")


@router.get("/sounds")
async def list_sounds():
    """List all available modern UI sounds and currently active sound settings."""
    from app.core.voice_service import resolve_sound_path
    sounds_dir = Path(__file__).resolve().parent.parent / "sounds"
    available = []
    if sounds_dir.exists():
        for p in sorted(sounds_dir.glob("*.*")):
            if p.suffix.lower() in (".mp3", ".wav", ".aiff", ".m4a", ".ogg"):
                available.append(p.stem)

    themes = {
        "minimal": {"start": "minimal_wake", "release": "minimal_notification", "finish": "minimal_complete", "description": "Linear / modern clean UI clicks"},
        "glass": {"start": "glass_wake", "release": "glass_notification", "finish": "glass_complete", "description": "Crystal ping and airy acoustic resonance"},
        "soft": {"start": "soft_wake", "release": "soft_notification", "finish": "soft_complete", "description": "Warm, mellow, tactile non-intrusive chimes"},
        "scifi": {"start": "scifi_wake", "release": "scifi_notification", "finish": "scifi_complete", "description": "High-tech Jarvis / digital assistant chirp"},
        "zen": {"start": "zen_wake", "release": "zen_notification", "finish": "zen_complete", "description": "Calm, meditative singing bowl tone"},
        "synth": {"start": "bloom", "release": "minimal_notification", "finish": "chime", "description": "Synthesized pure sine harmonic bloom & chord"}
    }

    return {
        "active": {
            "start_sound": settings.voice_start_sound,
            "release_sound": settings.voice_release_sound,
            "finish_sound": settings.voice_finish_sound,
            "auto_endpoint": settings.voice_auto_endpoint
        },
        "themes": themes,
        "available_files": available
    }


@router.post("/sounds/play")
async def preview_sound(request: SoundPlayRequest):
    """Audition / preview a sound on local workstation speakers."""
    from app.core.voice_service import play_sound, resolve_sound_path
    resolved = resolve_sound_path(request.sound)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Sound '{request.sound}' not found")
    play_sound(request.sound)
    return {"status": "playing", "sound": request.sound, "file": str(resolved.name)}


@router.post("/sounds/set")
async def set_active_sounds(request: SoundSetRequest):
    """Set active start, release, finish sounds and auto-endpointing dynamically."""
    from app.core.voice_service import resolve_sound_path
    updated = {}
    if request.start_sound is not None:
        if not resolve_sound_path(request.start_sound) and request.start_sound.lower() not in ("none", "off"):
            raise HTTPException(status_code=404, detail=f"Start sound '{request.start_sound}' not found")
        settings.voice_start_sound = request.start_sound
        updated["start_sound"] = request.start_sound

    if request.release_sound is not None:
        if not resolve_sound_path(request.release_sound) and request.release_sound.lower() not in ("none", "off"):
            raise HTTPException(status_code=404, detail=f"Release sound '{request.release_sound}' not found")
        settings.voice_release_sound = request.release_sound
        updated["release_sound"] = request.release_sound

    if request.finish_sound is not None:
        if not resolve_sound_path(request.finish_sound) and request.finish_sound.lower() not in ("none", "off"):
            raise HTTPException(status_code=404, detail=f"Finish sound '{request.finish_sound}' not found")
        settings.voice_finish_sound = request.finish_sound
        updated["finish_sound"] = request.finish_sound

    if request.auto_endpoint is not None:
        settings.voice_auto_endpoint = request.auto_endpoint
        updated["auto_endpoint"] = request.auto_endpoint

    return {"status": "updated", "active": updated}


@router.get("/config")
async def get_configuration():
    """Retrieve active LLM and Voice provider configuration and available presets."""
    from app.core.config_manager import get_current_config, PRESETS, VOICE_PRESETS
    return {
        "config": get_current_config(),
        "presets": PRESETS,
        "voice_presets": VOICE_PRESETS
    }


@router.post("/config")
async def update_configuration(updates: dict):
    """Hot-reload configuration for LLM, Voice, and Audio settings."""
    from app.core.config_manager import save_config, get_current_config
    success, msg = save_config(updates, notify_daemon=False)
    return {
        "status": "updated" if success else "error",
        "message": msg,
        "config": get_current_config()
    }


@router.get("/models")
async def list_available_models():
    """Query the active OpenAI-compatible endpoint for available models."""
    import httpx
    import logging
    logger = logging.getLogger("maxi.models")
    from app.core.config_manager import get_current_config

    cfg = get_current_config()
    base_url = (cfg.get("llm_url") or settings.openai_base_url or "").rstrip("/")
    api_key = cfg.get("llm_key") or settings.openai_api_key or ""
    current_model = cfg.get("llm_model") or settings.openai_model or "gemma4:31b-cloud"

    headers = {}
    if api_key and api_key.lower() not in ("ollama", "none", ""):
        headers["Authorization"] = f"Bearer {api_key}"

    models = []
    endpoints_to_try = [f"{base_url}/models"]
    if not base_url.endswith("/v1"):
        endpoints_to_try.append(f"{base_url}/v1/models")
    if "11434" in base_url or "localhost" in base_url:
        endpoints_to_try.append(f"{base_url.split('/v1')[0]}/api/tags")

    async with httpx.AsyncClient(timeout=4.0) as client:
        for ep in endpoints_to_try:
            try:
                resp = await client.get(ep, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        for m in data["data"]:
                            if isinstance(m, dict) and "id" in m:
                                mid = str(m["id"])
                                if "embed" not in mid.lower() and mid not in models:
                                    models.append(mid)
                            elif isinstance(m, str) and m not in models:
                                models.append(m)
                    elif isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
                        for m in data["models"]:
                            if isinstance(m, dict):
                                mname = str(m.get("name") or m.get("model") or "")
                                if mname and "embed" not in mname.lower() and mname not in models:
                                    models.append(mname)
                    if models:
                        break
            except Exception as ex:
                logger.debug(f"Failed to fetch models from {ep}: {ex}")

    if current_model:
        if current_model in models:
            models.remove(current_model)
        models.insert(0, current_model)
    elif not models:
        models = ["gemma4:31b-cloud", "gpt-oss:120b-cloud", "llama-3.3-70b-versatile"]

    return {
        "status": "ok",
        "current_model": current_model,
        "base_url": base_url,
        "models": models
    }


class TTSSpeakRequest(BaseModel):
    text: str = Field(..., description="Text to speak aloud using Siri TTS")
    voice: Optional[str] = Field(None, description="Optional Siri voice preset or macOS voice name (e.g. Tara, Samantha, Daniel)")
    rate: Optional[int] = Field(None, description="Optional speaking rate in words per minute")


@router.get("/tts")
async def get_tts_info():
    """Retrieve active Siri TTS configuration, voice presets, and available system voices."""
    from app.core.tts import tts_service, SIRI_VOICE_PRESETS, resolve_siri_voice
    return {
        "active": {
            "enable_tts": settings.enable_tts,
            "tts_voice": settings.tts_voice,
            "resolved_voice": resolve_siri_voice(settings.tts_voice),
            "tts_rate": settings.tts_rate,
            "tts_speak_all_sources": settings.tts_speak_all_sources,
            "is_speaking": tts_service.is_speaking,
        },
        "siri_presets": SIRI_VOICE_PRESETS,
        "available_voices": tts_service.list_available_voices(),
    }


@router.post("/tts/speak")
async def speak_tts(request: TTSSpeakRequest):
    """Speak text aloud using Siri TTS."""
    from app.core.tts import tts_service, resolve_siri_voice
    spoken = tts_service.speak(text=request.text, voice=request.voice, rate=request.rate)
    return {
        "status": "speaking" if spoken else "skipped",
        "text": spoken,
        "voice": resolve_siri_voice(request.voice),
        "rate": request.rate or settings.tts_rate,
    }


@router.post("/tts/stop")
async def stop_tts():
    """Immediately stop any active Siri TTS speech."""
    from app.core.tts import tts_service
    tts_service.stop()
    return {"status": "stopped"}


class TTSToggleRequest(BaseModel):
    enabled: Optional[bool] = None


@router.post("/tts/toggle")
async def toggle_tts(request: Optional[TTSToggleRequest] = None):
    """Toggle or explicitly set Text-to-Speech active state and persist to .env."""
    from app.core.config_manager import save_config
    if request and request.enabled is not None:
        target = request.enabled
    else:
        target = not getattr(settings, "enable_tts", True)

    settings.enable_tts = target
    save_config({"ENABLE_TTS": str(target).lower()}, notify_daemon=False)
    return {"status": "ok", "enable_tts": settings.enable_tts}


class GlossaryTermRequest(BaseModel):
    term: str = Field(..., description="Domain term or spoken phrase")
    replacement: Optional[str] = Field(None, description="Optional replacement text (if omitted, adds to vocabulary terms)")


class TextInjectRequest(BaseModel):
    text: str = Field(..., description="Text to inject at the active OS cursor position")
    preserve_clipboard: bool = Field(True, description="Whether to restore prior clipboard contents after pasting")


@router.get("/glossary")
async def get_glossary():
    """Retrieve custom vocabulary terms and automatic spoken-to-written replacements."""
    from app.core.glossary import glossary_manager
    data = glossary_manager.list_all()
    return {
        "terms": data["terms"],
        "replacements": data["replacements"],
        "whisper_prompt": glossary_manager.build_whisper_prompt(),
    }


@router.post("/glossary")
async def add_glossary_item(request: GlossaryTermRequest):
    """Add a vocabulary term or spoken-to-written replacement to ~/.maxi/glossary.json."""
    from app.core.glossary import glossary_manager
    if request.replacement is not None:
        data = glossary_manager.add_replacement(request.term, request.replacement)
    else:
        data = glossary_manager.add_term(request.term)
    return {"status": "updated", "glossary": data}


@router.delete("/glossary")
async def delete_glossary_item(term: str = Query(..., description="Term or replacement key to remove")):
    """Remove a vocabulary term or replacement from ~/.maxi/glossary.json."""
    from app.core.glossary import glossary_manager
    removed_term = glossary_manager.remove_term(term)
    removed_rep = glossary_manager.remove_replacement(term)
    if not removed_term and not removed_rep:
        raise HTTPException(status_code=404, detail=f"Term '{term}' not found in glossary")
    return {"status": "removed", "term": term, "glossary": glossary_manager.list_all()}


@router.get("/context")
async def get_focused_context(live: bool = Query(False, description="Capture fresh context immediately")):
    """Retrieve the last captured key-down context or capture live focused app/window/selection context."""
    from app.core.context_capture import context_capturer
    ctx = context_capturer.capture() if live else (context_capturer.last_context or context_capturer.capture())
    return {
        "context": ctx.to_dict(),
        "prompt_block": ctx.to_prompt_block(),
        "proper_nouns": ctx.extract_proper_nouns(),
    }


@router.post("/inject")
async def inject_text_endpoint(request: TextInjectRequest):
    """Inject text directly into the currently focused macOS text field while preserving clipboard."""
    from app.core.text_injector import text_injector
    ok = text_injector.inject_text(request.text, preserve_clipboard=request.preserve_clipboard)
    if not ok:
        raise HTTPException(status_code=400, detail="Text injection failed or empty text provided")
    return {"status": "injected", "length": len(request.text)}


