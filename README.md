# ∑ Maxi

**A little less clicking.** A voice-controlled desktop assistant with a native macOS floating HUD, an OpenAI-compatible LLM backend, and tools supplied by your MCP servers.

Hold **Right Option (⌥)**, say what you need, and release to send. Double-tap to lock hands-free recording; press **Esc** to cancel. The microphone opens for a recording session. Maxi does not listen for a wake word.

**Current release:** `v0.3.0-beta.1` · [Release notes](releases/v0.3.0-beta.1.md) · [Changelog](CHANGELOG.md)

## Requirements

- The macOS installer sets up Python automatically. Manual backend installs need Python 3.10+.
- A configured OpenAI-compatible LLM endpoint/model.
- A Whisper-compatible transcription provider and key for voice input.
- macOS 14+ for the native SwiftUI HUD. Liquid Glass uses macOS 26+; macOS 14/15 use a translucent material fallback.
- The combined macOS installer supports Apple Silicon and Intel; no Xcode or Homebrew is needed. The older HUD-only ZIP targets Apple Silicon.
- macOS Microphone access for recording and Accessibility/Input Monitoring access for the Python/terminal application running Maxi's shortcut listener. Text injection and context capture also need Accessibility access.
- MCP servers are configured separately. Available desktop actions depend on those servers and their permissions.

The macOS beta is not Developer ID signed or notarized. The combined app includes the compiled HUD, backend startup, and backend wheel; first setup downloads a private Python runtime when needed and installs dependencies. Internet access is required. Linux and Windows support the backend and platform shortcuts, without a native GUI in this release.

## Install the beta

On macOS 14+, download the **universal DMG** from [GitHub Releases](https://github.com/krishnakanthpathi/maxi/releases/tag/v0.3.0-beta.1), drag Maxi to Applications, and open it. First launch opens Terminal for setup and provider configuration. Later launches start the daemon and HUD together. The app and mounted disk use the ∑ icon.

Or install both pieces with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install_macos.sh | bash
```

The installer verifies release checksums, installs the app in `~/Applications`, keeps its runtime in `~/.maxi`, and links the CLI at `~/.local/bin/maxi`. It preserves existing settings and memories. See [macOS installation](docs/MACOS_INSTALL.md).

### Manual backend installation

Download the wheel and, on Apple Silicon, the optional HUD companion from [GitHub Releases](https://github.com/krishnakanthpathi/maxi/releases).

```bash
python3 -m venv ~/.maxi/venv
~/.maxi/venv/bin/python -m pip install "$HOME/Downloads/maxi_ai-0.3.0b1-py3-none-any.whl[voice]"
~/.maxi/venv/bin/maxi config wizard
~/.maxi/venv/bin/maxi start
```

Start your configured LLM server first. Configure speech transcription with:

```bash
~/.maxi/venv/bin/maxi config set voice-key YOUR_PROVIDER_KEY
```

Unzip the macOS companion and open `Maxi.app`. If macOS blocks the unsigned beta, review the application in System Settings → Privacy & Security. Alternatively, build the included HUD source:

```bash
xcode-select --install
~/.maxi/venv/bin/maxi hud --rebuild
```

Add `~/.maxi/venv/bin` to your PATH to use the shorter `maxi` commands. For a core installation without microphone/hotkey dependencies, omit `[voice]` when installing the wheel.

## Develop from source

```bash
git clone https://github.com/krishnakanthpathi/maxi.git
cd maxi
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[voice]'
mkdir -p ~/.maxi
cp .env.example ~/.maxi/.env  # only when creating a new configuration
.venv/bin/python -m app.cli config wizard
.venv/bin/python -m app.cli run
```

In another terminal, run `.venv/bin/python -m app.cli hud`. Existing users should keep their `~/.maxi/.env` and MCP configuration. The source installers in `scripts/` preserve existing user configuration.

## Everyday controls

| Action | Control |
| --- | --- |
| Record a voice command | Hold Right Option on macOS; Control + Space on Linux/Windows |
| Hands-free recording | Double-tap the configured shortcut; tap again to finish |
| Cancel recording, speech, or active voice work | Esc |
| Start a fresh conversation | New Chat (+) in the HUD, or New Chat in its menu |
| Keep a response visible | Pin |
| Pause spoken responses | Speaker toggle |
| Insert dictated text at the cursor | Start the command with “Dictate:” |

New Chat clears recent conversational context and stops active voice work. Late responses cannot refill the cleared context. Deliberately saved LightMem memories remain separate. Persistent memory is opt-in through the memory tools; automatic memory injection is not included in this release.

## Configure models, memory, and tools

```bash
maxi config wizard
maxi config preset ollama
maxi config preset groq
maxi config set llm-url http://localhost:11434/v1
maxi config set llm-model llama3.2
```

The optional [LightMem](https://pypi.org/project/lmem/) integration requires a separately installed `lmem` CLI. Maxi exposes recall, answer, and explicit remember tools. Do not assume facts have been saved unless the memory tool confirms success.

Put MCP configuration in `~/.maxi/mcp_config.json`. Start with `.maxi/mcp_config.example.json` and add servers you trust. A stdio server uses this structure:

```json
{
  "mcpServers": {
    "your-server": {
      "command": "/absolute/path/to/server-command",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

Place custom Markdown skills in `~/.maxi/skills/`. Use the HUD menu to reload skills and MCP connections after changes. No third-party MCP server, Discord bot, WhatsApp service, or model runtime is bundled.

## CLI and API

```bash
maxi --version
maxi start
maxi stop
maxi restart
maxi status
maxi run
maxi hud
maxi hud stop
maxi hud build
maxi config
maxi glossary
```

The daemon binds to `127.0.0.1:4848` by default. API documentation is at `http://127.0.0.1:4848/docs`; events are available at `ws://127.0.0.1:4848/ws`. Keep this local service on loopback; desktop tools may perform actions on the workstation.

## Verify and build a release

```bash
.venv/bin/python -m pytest -q
bash scripts/test_macos_hud.sh
uv build
bash scripts/package_macos.sh
bash scripts/package_macos_installer.sh
python3 scripts/verify_release.py
```

The wheel includes the Swift frontend source and bundled sound assets. Release distributions exclude private configuration, runtime history, databases, pairing QR codes, and build caches. See [release preparation](docs/RELEASING.md).

## Website

The landing page and user documentation live in `website/`. For Vercel, set the Root Directory to `./`; `vercel.json` supplies the static output settings. See [deployment instructions](docs/VERCEL.md).

## License

[MIT](LICENSE). The ∑ mark is available as [SVG](assets/maxi-mark.svg).
