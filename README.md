# Maxi ⚡

**Maxi** is an ultra-fast, pluggable cross-platform background AI agent daemon designed for macOS, Linux, and Windows workstations. It combines native OS control via the Model Context Protocol (MCP), a 3-chime audio feedback engine, real-time streaming speech recognition with Voice Activity Detection (VAD), and a decoupled frontend architecture.

```
  __  __              _ 
 |  \/  | __ ___  __ (_)
 | |\/| |/ _` \ \/ / | |
 | |  | | (_| |>  <  | |
 |_|  |_|\__,_/_/\_\ |_|
```

---

## ⚡ Quick Start: One-Line Installer

Install and configure Maxi with a single command:

#### macOS & Linux (Terminal)
```bash
curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.sh | bash
```

#### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.ps1 | iex
```

The installer automatically:
1. Detects your platform (macOS, Linux, or Windows) and architecture.
2. Resolves audio dependencies (`libportaudio2`, `libasound2` on Linux).
3. Creates an isolated environment at `~/.maxi/venv`.
4. Symlinks the `maxi` CLI into `~/.local/bin/maxi`.
5. Configures native background service auto-start:
   - **macOS**: `launchd` LaunchAgent (`~/Library/LaunchAgents/com.maxi.daemon.plist`)
   - **Linux**: `systemd` user service (`~/.config/systemd/user/maxi.service`)

---

## 🚀 The `maxi` CLI

Control the background daemon from any terminal:

```bash
maxi start                       # Start background daemon on http://127.0.0.1:4848
maxi stop                        # Gracefully stop the background daemon
maxi restart                     # Restart background daemon
maxi status                      # Inspect daemon PID, health, loaded MCP tools, audio theme
maxi hud                         # Open the modern web HUD in your default browser
maxi config                      # View active LLM & Voice configuration
maxi config preset ollama        # Switch to Ollama (Local Default on :11434 with gemma4:31b-cloud)
maxi config preset groq          # Switch to Groq (Cloud ultra-fast LPU)
maxi config set llm-url <url>    # Set custom OpenAI-compatible endpoint URL
maxi config set llm-model <name> # Set model name
maxi config set voice-key <key>  # Set Groq Whisper voice STT API key
maxi config wizard               # Interactive terminal configuration wizard
maxi run                         # Run in foreground (ideal for systemd or development)
```

---

## 🎙️ Voice & Hotkey Features

### 1. Hardware Hotkeys
- **macOS**: Hold **Right Option (⌥)** (Dedicated modifier; ignores Ctrl+Space to eliminate IDE autocomplete collisions).
- **Windows / Linux**: Hold **Control + Space**.

### 2. Pure Push-to-Talk (Hold to Speak)
- **Hold to Speak**: Hold the hotkey down, speak your command naturally, and pause freely without being cut off.
- **Instant Dispatch**: Releasing the key stops recording and sends your command to the agent immediately.
- **Typing Protection**: Brief accidental key brushes (<250ms) are silently discarded without playing chimes or dispatching.
- **No Mid-Sentence Cutoffs**: Auto-endpointing is disabled by default so background silence will never interrupt your sentence.

### 3. Tactile Audio Pipeline
Every spoken interaction provides tactile auditory feedback:
1. **Wake Chime** (`minimal_wake`): Fires the millisecond listening begins upon pressing the key.
2. **Release / Send Chime** (`minimal_notification`): Fires when the key is released.
3. **Completion Chime** (`minimal_complete`): Fires after tools execute and final response text is generated.

Sound themes can be auditioned and switched via the Web HUD or API:
- `minimal` (Linear/Notion-style micro clicks)
- `glass` (Airy crystal resonance)
- `soft` (Warm, non-intrusive mellow chimes)
- `scifi` (Jarvis-style digital chirp)
- `zen` (Meditative singing bowl tone)
- `synth` (Synthesized pure sine harmonic bloom & chord)

---

## 🏗️ Architecture: Pluggable Frontends

The backend operates as a headless, event-driven daemon (`localhost:4848`). Any frontend plugs directly into its REST and WebSocket (`ws://localhost:4848/ws`) APIs:

```text
maxi/
├── app/                  # Headless Core Daemon Engine
│   ├── api/              # REST + WebSocket endpoints
│   ├── core/             # Agent, Voice Pipeline, MCP Client, Skills
│   └── sounds/           # Bundled UI audio assets
├── frontends/            # Pluggable Client Interfaces
│   ├── web/              # Siri-style Browser HUD
│   ├── macos/            # Native macOS Swift menu bar app & floating overlay
│   └── linux/            # Linux desktop indicator & tray (Tauri / GTK)
└── scripts/
    └── install.sh        # Universal cross-platform curl installer
```

### WebSocket Protocol (`/ws`)
Connected frontends receive real-time streaming events:
- `voice_start`: Trigger pulsing orb animation.
- `voice_interim_transcript`: Real-time streaming subtitles while speaking.
- `voice_stop`: Transition orb to processing state.
- `voice_result`: Final prompt, response text, execution latency, and tools used.
- `chunk`: Incremental token streaming.

---

## 📦 Python Packaging & PyPI Wheels

Maxi uses modern PEP 517/621 packaging via `pyproject.toml`:

```bash
# Core headless daemon (lightweight, zero audio drivers)
pip install maxi-ai

# With push-to-talk voice & audio extras
pip install "maxi-ai[voice]"
```

To build wheels locally:
```bash
uv build
# Generated artifacts in dist/:
# - dist/maxi_ai-0.2.0-py3-none-any.whl
# - dist/maxi_ai-0.2.0.tar.gz
```

---

## 🔧 Native MCP Tool Integration

Maxi automatically connects to configured Model Context Protocol (MCP) servers (e.g., `native-assistant-mcp`) configured in `~/.maxi/mcp_config.json` or `.maxi/mcp_config.json`, exposing 70+ native capabilities:
- Application focus & launching (`open_application`, `close_application`)
- Workstation automation & window management (`focus_window`, `resize_window`)
- Audio volume & media playback controls (`volume_set`, `media_control`)
- Screen capture & clipboard operations (`take_screenshot`, `clipboard_read`)
- Native notifications & alerts (`notify`, `say_speech`)

---

## ⚙️ Configuration

Environment variables can be set in `.env` or `~/.maxi/.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OPENAI_BASE_URL` | `http://localhost:1234/v1` | LLM API endpoint (Ollama, LM Studio, Groq, OpenAI) |
| `OPENAI_API_KEY` | `sk-local-no-key-required` | API key for LLM endpoint |
| `OPENAI_MODEL` | `gemma-4-31b` | Target LLM model identifier |
| `VOICE_BASE_URL` | `https://api.groq.com/openai/v1`| Speech-to-text API endpoint |
| `VOICE_API_KEY` | *(read from GROQ_API_KEY)* | API key for Whisper transcription |
| `VOICE_MODEL` | `whisper-large-v3-turbo` | Whisper model for fast STT |
| `VOICE_START_SOUND` | `minimal_wake` | Audio played when listening starts |
| `VOICE_RELEASE_SOUND`| `minimal_notification` | Audio played when listening stops/sends |
| `VOICE_FINISH_SOUND` | `minimal_complete` | Audio played when result is ready |
| `VOICE_AUTO_ENDPOINT`| `true` | Auto-detect 800ms silence and execute |

---

## 📄 License

MIT License. Designed and crafted for modern local workstations.
