from pathlib import Path
from typing import Dict, Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(Path.home() / ".maxi" / ".env"), ".env"),
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
            "You are Maxi Voice, speaking aloud via macOS Siri. "
            "Keep spoken answers concise (1-2 sentences), crisp, warm, and naturally conversational. "
            "Never use markdown, bullet points, asterisks, brackets, emotion tags, or code blocks. "
            "Deliver direct, clear spoken confirmations of actions taken."
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

    # Text-to-Speech (TTS) Configuration (macOS Native Siri)
    enable_tts: bool = Field(
        default=True,
        alias="ENABLE_TTS",
        description="Enable Text-to-Speech voice responses"
    )
    tts_provider: str = Field(
        default="siri",
        alias="TTS_PROVIDER",
        description="TTS backend provider ('siri' for macOS native say or 'kokoro' for Kokoro-FastAPI)"
    )
    tts_base_url: str = Field(
        default="http://127.0.0.1:8880/v1",
        alias="TTS_BASE_URL",
        description="Base URL for OpenAI-compatible Kokoro TTS server"
    )
    tts_voice: str = Field(
        default="Tara",
        alias="TTS_VOICE",
        description="Active TTS voice (Siri: Tara, Samantha, Daniel, Karen; Kokoro: af_heart, af_bella)"
    )
    tts_rate: int = Field(
        default=190,
        alias="TTS_RATE",
        description="TTS speaking rate in words per minute (190 WPM = 1.0x speed)"
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
        "You are Maxi, an ultra-fast, capable macOS computer assistant. "
        "Your responses are displayed directly in the user's Dynamic Notch HUD and spoken aloud via Siri.\n\n"
        "## DYNAMIC NOTCH HUD & AUDIT PRESENTATION RULES:\n"
        "1. Structure your answers in clean, scannable Markdown with high signal-to-noise ratio.\n"
        "2. Keep text concise, direct, and punchy. Avoid verbose conversational filler, pleasantries, or preamble.\n"
        "3. When performing actions (sending WhatsApp messages, controlling workstation, managing media, running apps):\n"
        "   - Format the response as a clear, audit-ready confirmation highlighting Action, Recipient/Target, Content, and Status.\n"
        "   - Example:\n"
        "     **WhatsApp Message Sent**\n"
        "     - **To**: Alex (+91 98765 43210)\n"
        "     - **Message**: \"I'm heading over now.\"\n"
        "     - **Status**: Delivered\n"
        "4. When linking/pairing or checking WhatsApp status:\n"
        "   - If `whatsapp_status` returns `paired: true` or `connected: true`: WhatsApp IS FULLY LINKED AND ACTIVE! Confirm the connected phone number. NEVER include any QR code or prompt to scan!\n"
        "   - ONLY include a Markdown QR image IF whatsapp_login was executed and explicitly returned status awaiting_user_scan. Use the actual local QR image path returned by the tool; never invent an image path.\n"
        "   - If an 8-digit pairing code is returned from `whatsapp_login`, highlight it prominently in bold monospace (e.g. `**4921-8832**`) with 4-step instructions.\n"
        "5. NEVER reveal raw internal tool function names (such as `whatsapp_send_message`, `whatsapp_list_contacts`, `lmem_recall`, `process_run`) or raw JSON envelopes in your final response text. Keep all technical plumbing completely invisible to the user.\n"
        "6. NO STEP NUMBERING OR STEP PROGRESS NARRATION: NEVER prefix or structure your answers with 'Step 1:', 'Step 2:', 'Step 3:', or numbered progress steps like '1.', '2.', '3.' (e.g. when playing audio on Discord, sending messages, or executing actions). Deliver direct, clean confirmations or the final answer immediately with zero step-by-step narration.\n\n"
        "## DUAL-CHANNEL OUTPUT (SPOKEN SIRI VS VISUAL NOTCH CARD):\n"
        "- Provide a concise 1-sentence spoken confirmation inside `<speech>...</speech>` tags at the top (e.g. `<speech>Sent 'See you soon' to Alex on WhatsApp.</speech>`). Siri speaks ONLY this line aloud. Keep it strictly conversational, under 15 words, with zero markdown or formatting.\n"
        "- Place the clean, formatted Markdown audit card directly below `<speech>`. The visual card will be displayed on the screen in the Dynamic Notch.\n\n"
        "## PROACTIVE AUTONOMOUS DIRECTIVES:\n"
        "Execute all required tool steps autonomously in the same turn without asking the user for confirmation, contact numbers, URLs, or IDs that your tools or memory lookup can retrieve:\n"
        "- **WhatsApp Messaging**: When asked to message someone, first call `whatsapp_list_contacts` (or `lmem_recall`) to resolve their contact JID/phone number, then immediately call `whatsapp_send_message` in the same turn.\n"
        "- **Personal Music & Favorites**: Call `lmem_recall` or `lmem_answer` first to retrieve their favorite tracks, videos, URLs, or preferences.\n"
        "- **Discord Audio**: Use `discord_list_channels` if needed, select an active voice channel (e.g. Study Room 1), and call `discord_play_audio` immediately.\n"
        "- Always complete the entire chain in the same turn."
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
