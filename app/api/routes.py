import json
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
    return {"status": "ok", "service": "Maxi Agent Daemon"}


@router.post("/prompt")
async def handle_prompt(request: PromptRequest):
    """Stateless text and UI prompt endpoint."""
    try:
        result = await agent.run(prompt=request.text, source=request.source)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/voice/webhook")
async def handle_voice_webhook(request: VoiceWebhookRequest):
    """Direct webhook ingest for voice apps (Whisperflow, Willow, etc.)."""
    try:
        result = await agent.run(
            prompt=request.transcript,
            source=f"voice:{request.client}"
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/clear")
async def clear_context():
    """Clears short-term sliding conversational history buffer."""
    agent.clear_history()
    return {"status": "cleared", "message": "Conversation history reset to empty."}


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
    """Hot-reload skills from .maxi/skills/*.md and MCP servers from .maxi/mcp_config.json."""
    from app.core.mcp_client import mcp_manager
    skill_registry.reload()
    await mcp_manager.connect_all()
    tools = mcp_manager.get_tools()
    return {
        "status": "reloaded",
        "skills_count": len(skill_registry.list_skills()),
        "mcp_tools_count": len(tools)
    }


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


