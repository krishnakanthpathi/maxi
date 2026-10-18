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
        default=(
            "You are Maxi Voice, speaking aloud via an expressive neural TTS engine (Kokoro). "
            "Keep spoken answers concise (1-2 sentences), warm, and naturally conversational—never use markdown, bullet points, or code blocks. "
            "Start with a short natural appraisal or reaction when appropriate (e.g., 'Oh, I got it!', 'Aha, right!', 'Hmm, let me see...', 'Oh, nice!') followed by [pause:0.15s] so the first phrase streams immediately. "
            "Use inline expressive annotations naturally when they fit the moment: [laugh], [chuckle], [sigh], [hmm], [gasp], [pause:0.3s], [excited], or [thoughtful]."
        ),
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
    auto_duck_audio: bool = Field(
        default=False,
        alias="AUTO_DUCK_AUDIO",
        description="Automatically duck/lower system volume while recording voice input (Willow PrivateDucker)"
    )
    enable_context_capture: bool = Field(
        default=True,
        alias="ENABLE_CONTEXT_CAPTURE",
        description="Capture active app, window title, URL, and highlighted text on hotkey press (Willow FocusedInputCapture)"
    )
    double_tap_window: float = Field(
        default=0.38,
        alias="DOUBLE_TAP_WINDOW",
        description="Max interval in seconds between two quick hotkey taps to lock hands-free recording"
    )

    agent_timeout_seconds: float = Field(
        default=90.0,
        alias="AGENT_TIMEOUT_SECONDS",
        description="Maximum execution timeout in seconds for agent turn execution"
    )

    # Text-to-Speech (TTS) Configuration (Kokoro Neural TTS + Siri Fallback)
    enable_tts: bool = Field(
        default=True,
        alias="ENABLE_TTS",
        description="Enable Text-to-Speech voice responses"
    )
    tts_provider: str = Field(
        default="kokoro",
        alias="TTS_PROVIDER",
        description="TTS backend provider ('kokoro' for OpenAI-compatible Kokoro-FastAPI or 'siri' for macOS native say)"
    )
    tts_base_url: str = Field(
        default="http://100.75.149.115:8880/v1",
        alias="TTS_BASE_URL",
        description="Base URL for OpenAI-compatible Kokoro TTS server"
    )
    tts_voice: str = Field(
        default="af_heart",
        alias="TTS_VOICE",
        description="Active TTS voice (e.g. Kokoro: af_heart, af_bella, am_fenrir, bf_emma; Siri: Tara, Samantha, Daniel)"
    )
    tts_rate: int = Field(
        default=190,
        alias="TTS_RATE",
        description="TTS speaking rate in words per minute (190 WPM = 1.0x Kokoro speed)"
    )
    tts_speak_all_sources: bool = Field(
        default=False,
        alias="TTS_SPEAK_ALL_SOURCES",
        description="If True, speak responses for text/API prompts in addition to voice commands"
    )

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
        "You have access to native workstation MCP tools and persistent LMEM memory. Relevant user memories and preferences are automatically injected into your context. "
        "PROACTIVE AUTONOMOUS DIRECTIVE: When the user asks you to play audio, join voice channels, send messages, or perform actions, execute them immediately using your tools. NEVER stall by asking the user for channel IDs, guild IDs, or file paths that you can resolve via your tools (such as `discord_list_channels`, `discord_list_guilds`, `whatsapp_list_contacts`) or local files (e.g. `/tmp/stefan_theme.mp3`). Resolve parameters and trigger the action (such as `discord_play_audio`, `discord_join_voice`) autonomously in the same turn."
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
        default=str(Path.home() / ".maxi" / "history.jsonl"),
        alias="MAXI_HISTORY_FILE",
        description="Path to append-only turn history audit log"
    )

    # Registered MCP Servers (overridden by config file if present)
    mcp_servers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def get_history_file(self) -> Path:
        """Safely resolves history log path, ensuring it always points to a writable user directory."""
        import os
        p = Path(self.history_file_path)
        if not p.is_absolute():
            if Path(".maxi").exists() and os.access(".maxi", os.W_OK) and str(Path(".").resolve()) != "/":
                return p
            return Path.home() / ".maxi" / "history.jsonl"
        return p

    def get_mcp_config_file(self) -> Path:
        """Resolves MCP config file looking in .maxi first, then root fallback, then ~/.maxi."""
        if self.mcp_config_path:
            p = Path(self.mcp_config_path)
            if p.exists():
                return p

        candidates = [
            Path.home() / ".maxi" / "mcp_config.json",
            Path(".maxi/mcp_config.json"),
            Path("max_mcp.json"),
        ]
        for p in candidates:
            if p.exists() and p.is_file():
                return p
        return Path.home() / ".maxi" / "mcp_config.json"

    def get_skills_dir(self) -> Path:
        """Resolves skills directory looking in .maxi/skills first, then root skills/, then ~/.maxi/skills."""
        if self.skills_dir_path:
            p = Path(self.skills_dir_path)
            if p.exists():
                return p

        candidates = [
            Path.home() / ".maxi" / "skills",
            Path(".maxi/skills"),
            Path("skills"),
        ]
        for p in candidates:
            if p.exists() and p.is_dir():
                return p
        return Path.home() / ".maxi" / "skills"


settings = Settings()
