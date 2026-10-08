# Maxi Agent ⚡

**Maxi** is a cross-platform background AI agent daemon designed for macOS, Linux, and Windows. It provides native OS control via the Model Context Protocol (MCP), dynamic markdown skill orchestration, and local HTTP / WebSocket endpoints for desktop HUDs (Tauri) and external voice plugins (Whisperflow, Willow Voice, etc.).

---

## Architecture Overview

```
[Voice Plugins / Apps]           [Tauri Desktop App]
 (Whisperflow, Willow, Mic)         (Tray, Floating HUD, Hotkeys)
         │                                   │
         │ POST /api/voice/webhook           │ WebSocket /ws
         └───────────────┬───────────────────┘
                         ▼
             ┌─────────────────────────┐
             │   Maxi Daemon (FastAPI) │
             │   - Skill Registry      │
             │   - LangChain Core      │
             │   - MCP Tool Manager    │
             └───────────┬─────────────┘
                         │ stdio / SSE
                         ▼
             ┌─────────────────────────┐
             │       MCP Servers       │
             │   (Native OS, JXA,      │
             │    Win32, DBus, etc.)   │
             └─────────────────────────┘
```

---

## Features

- **Background Daemon**: Runs quietly on `127.0.0.1:4848`.
- **OpenAI-Compatible Engine**: Connects to any local (Ollama, LM Studio, vLLM) or remote (OpenRouter, OpenAI) endpoint.
- **MCP Client Integration**: Aggregates tools from any local or remote MCP servers and binds them to LangChain.
- **Markdown Skill Engine**: Dynamically matches and injects `.md` skills from `.maxi/skills/` based on prompt intent and source.
- **Voice Ingest Endpoint**: Pre-configured `POST /api/voice/webhook` ready for external speech transcription engines.
- **Bidirectional Streaming**: WebSocket (`/ws`) for instant token streaming to desktop HUDs.

---

## Getting Started

### 1. Install Dependencies
Using `uv` (recommended) or `pip`:

```bash
cd /Users/krishnakanth/Projects/maxi

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 3. Run the Daemon
```bash
uvicorn app.main:app --host 127.0.0.1 --port 4848 --reload
```

---

## Configuration: The `.maxi` Directory

All runtime, audit logs, and configurations live inside the [`.maxi/`](file:///Users/krishnakanth/Projects/maxi/.maxi) folder:

```text
maxi/
├── .maxi/
│   ├── mcp_config.json        # MCP server definitions
│   ├── history.jsonl          # Append-only conversation audit log
│   └── skills/                # Markdown skills (*.md)
│       ├── os_automation.md
│       ├── voice_interaction.md
│       └── system_monitor.md
```

### 1. Stateless Architecture & History Logging
- **100% Stateless**: Every request is evaluated fresh with zero context pollution from past requests (`Persona + Matched Skill + Fresh MCP Tools + Prompt`).
- **Audit Logging**: Each completed turn is automatically recorded to `.maxi/history.jsonl` with timestamps, source, prompt, response, and tools used.

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/health` | `GET` | Service liveness probe |
| `/api/prompt` | `POST` | Primary text prompt runner (stateless) |
| `/api/voice/webhook` | `POST` | Ingestion endpoint for Whisperflow / Willow transcripts |
| `/api/mcp/tools` | `GET` | List all connected MCP tools |
| `/api/history` | `GET` | Fetch recent conversation turns from audit log |
| `/api/skills` | `GET` | List active skills |
| `/api/skills/toggle` | `POST` | Enable/disable specific skills |
| `/api/reload` | `POST` | Hot-reload MCP servers and skills without restarting |
| `/ws` | `WebSocket` | Real-time bidirectional streaming |
