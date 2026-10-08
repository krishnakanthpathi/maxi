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
