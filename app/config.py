from pathlib import Path
from typing import Dict, Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path.home() / ".maxi" / ".env")),
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
        default="http://localhost:11434/v1",
        alias="OPENAI_BASE_URL",
        description="Base URL for OpenAI-compatible provider (Ollama local, Groq, OpenRouter, etc.)"
    )
    openai_api_key: str = Field(
        default="ollama",
        alias="OPENAI_API_KEY",
        description="API key for the endpoint"
    )
    openai_model: str = Field(
        default="gemma4:31b-cloud",
        alias="OPENAI_MODEL",
        description="Target model identifier (e.g. gemma4:31b-cloud in Ollama)"
    )

    # Voice Service Settings
    voice_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        alias="VOICE_BASE_URL",
        description="Base URL for voice transcription/speech provider"
    )
    voice_api_key: Optional[str] = Field(
        default=None,
        alias="VOICE_API_KEY",
        description="API key for voice provider (fallback to GROQ_API_KEY / GROK_API_KEY)"
    )
    voice_model: str = Field(
        default="whisper-large-v3-turbo",
        alias="VOICE_MODEL",
        description="Model identifier for speech transcription"
    )
    voice_system_prompt: str = Field(
        default="You are Maxi Voice. Provide direct, single-sentence spoken answers without markdown, bullets, asterisks, or bold text.",
        alias="VOICE_SYSTEM_PROMPT"
    )
    enable_voice_hotkey: bool = Field(
        default=True,
        alias="ENABLE_VOICE_HOTKEY",
        description="Enable global Control+Space push-to-talk listener inside the daemon"
    )
    voice_start_sound: str = Field(
        default="minimal_wake",
        alias="VOICE_START_SOUND",
        description="Sound played when recording starts (from app/sounds or macOS system)"
    )
    voice_release_sound: str = Field(
        default="minimal_notification",
        alias="VOICE_RELEASE_SOUND",
        description="Sound played when recording stops/sends (from app/sounds or macOS system)"
    )
    voice_finish_sound: str = Field(
        default="minimal_complete",
        alias="VOICE_FINISH_SOUND",
        description="Sound played when voice command completes and result is returned (from app/sounds or macOS system)"
    )
    voice_hotkey: str = Field(
        default="auto",
        alias="VOICE_HOTKEY",
        description="Global voice hotkey trigger ('auto', 'right_option', or 'ctrl_space')"
    )
    voice_auto_endpoint: bool = Field(
        default=False,
        alias="VOICE_AUTO_ENDPOINT",
        description="Automatically detect end of speech silence. Set False for pure Push-to-Talk (Hold to speak)"
    )
    voice_silence_threshold: float = Field(
        default=0.012,
        alias="VOICE_SILENCE_THRESHOLD",
        description="Audio RMS amplitude below which audio is treated as silence"
    )
    voice_silence_duration: float = Field(
        default=1.2,
        alias="VOICE_SILENCE_DURATION",
        description="Silence duration in seconds before auto-stopping recording (if auto_endpoint enabled)"
    )

    # Hands-free Wake Word Auto-Catch Settings ("Hey Maxi" / "Hey Siri")
    enable_wake_word: bool = Field(
        default=True,
        alias="ENABLE_WAKE_WORD",
        description="Enable continuous hands-free wake word listener ('Hey Maxi' / 'Hey Siri')"
    )
    wake_words: str = Field(
        default="hey maxi,hey siri,hi maxi,hi siri,hey max,maxi,siri",
        alias="VOICE_WAKE_WORDS",
        description="Comma-separated list of wake words to auto-catch and trigger agent execution"
    )
    wake_word_auto_prefix: bool = Field(
        default=True,
        alias="WAKE_WORD_AUTO_PREFIX",
        description="Ensure voice commands are automatically prefixed with 'Hey Maxi,' when activating the agent"
    )
    wake_word_energy_threshold: float = Field(
        default=0.008,
        alias="WAKE_WORD_ENERGY_THRESHOLD",
        description="Microphone RMS energy threshold to trigger voice utterance capture (lowered from 0.015 to catch quiet words like 'that')"
    )
    wake_word_silence_duration: float = Field(
        default=1.8,
        alias="WAKE_WORD_SILENCE_DURATION",
        description="Silence duration in seconds after speech to finish utterance capture (raised from 1.0 to 1.8s for natural clause pauses)"
    )
    wake_word_max_duration: float = Field(
        default=45.0,
        alias="WAKE_WORD_MAX_DURATION",
        description="Maximum allowable duration in seconds for a continuous voice utterance"
    )

    def get_wake_words_list(self) -> list[str]:
        """Returns parsed, lowercase list of active wake words."""
        return [w.strip().lower() for w in self.wake_words.split(",") if w.strip()]

    def get_voice_api_key(self) -> str:
        """Resolves Voice/Groq API key from config or environment variables."""
        if self.voice_api_key:
            return self.voice_api_key
        import os
        for k in ("GROQ_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY"):
            val = os.environ.get(k)
            if val:
                return val
        return ""

    # System Persona & Skills
    system_prompt: str = (
        "You are Maxi, an ultra-fast, capable computer assistant. "
        "Keep all responses concise, direct, and punchy with zero fluff. "
        "You have access to native workstation MCP tools and persistent LMEM memory. "
        "Whenever needed, you can recall using LMEM memory to retrieve verified context and facts before answering. "
        "Proactively execute requested tasks via native tools."
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
