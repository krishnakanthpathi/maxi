from pathlib import Path
from typing import Dict, Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    # Server settings
    app_name: str = "Maxi Agent Daemon"
    host: str = "127.0.0.1"
    port: int = 4848
    debug: bool = False

    # OpenAI-Compatible Endpoint Settings
    openai_base_url: str = Field(
        default="http://localhost:1234/v1",
        alias="OPENAI_BASE_URL",
        description="Base URL for any OpenAI-compatible provider (Ollama, LM Studio, OpenRouter, vLLM, etc.)"
    )
    openai_api_key: str = Field(
        default="sk-local-no-key-required",
        alias="OPENAI_API_KEY",
        description="API key for the endpoint"
    )
    openai_model: str = Field(
        default="gemma-4-31b",
        alias="OPENAI_MODEL",
        description="Target model identifier"
    )

    # System Persona & Skills
    system_prompt: str = (
        "You are Maxi, an ultra-fast, capable cross-platform background agent. "
        "You have access to native MCP tools and system skills. "
        "Provide direct, punchy responses and proactively execute requested tasks via tools."
    )

    # Base configuration paths (defaults to .maxi directory)
    mcp_config_path: Optional[str] = Field(
        default=None,
        alias="MAXI_MCP_CONFIG",
        description="Path to MCP servers JSON configuration file (e.g. .maxi/mcp_config.json)"
    )
    skills_dir_path: Optional[str] = Field(
        default=None,
        alias="MAXI_SKILLS_DIR",
        description="Directory containing custom markdown skill files (*.md)"
    )
    history_file_path: str = Field(
        default=".maxi/history.jsonl",
        alias="MAXI_HISTORY_FILE",
        description="Path to append-only turn history audit log"
    )

    # Registered MCP Servers (overridden by config file if present)
    mcp_servers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def get_mcp_config_file(self) -> Path:
        """Resolves MCP config file looking in .maxi first, then root fallback, then ~/.maxi."""
        if self.mcp_config_path:
            p = Path(self.mcp_config_path)
            if p.exists():
                return p

        candidates = [
            Path(".maxi/mcp_config.json"),
            Path.home() / ".maxi" / "mcp_config.json",
            Path("max_mcp.json"),
        ]
        for p in candidates:
            if p.exists() and p.is_file():
                return p
        return Path(".maxi/mcp_config.json")

    def get_skills_dir(self) -> Path:
        """Resolves skills directory looking in .maxi/skills first, then root skills/, then ~/.maxi/skills."""
        if self.skills_dir_path:
            p = Path(self.skills_dir_path)
            if p.exists():
                return p

        candidates = [
            Path(".maxi/skills"),
            Path.home() / ".maxi" / "skills",
            Path("skills"),
        ]
        for p in candidates:
            if p.exists() and p.is_dir():
                return p
        return Path(".maxi/skills")


settings = Settings()
