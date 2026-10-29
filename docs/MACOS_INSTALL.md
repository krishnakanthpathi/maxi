# One-step macOS installation

Requires macOS 14+ on Apple Silicon or Intel and internet access for first setup.
No preinstalled Python, Homebrew, or Xcode is needed.

## DMG

Download `Maxi-0.3.0-beta.1-macos-universal.dmg` from
[the beta release](https://github.com/krishnakanthpathi/maxi/releases/tag/v0.3.0-beta.1).
Open it, drag Maxi to Applications, and open Maxi. Both the app and mounted
volume use the ∑ icon.

Opening Maxi shows its floating pill, even when it is already running. Use
**Show Maxi** from the ∑ menu to bring it back. The app stays out of the Dock;
it does not open a conventional main window.

On first launch, the app opens the bundled `Install Maxi.command`
in Terminal. It installs Python if needed, downloads and installs the separate backend wheel
and voice dependencies, and runs the provider wizard. The installer starts the
Python daemon directly, waits for its local health check to succeed, and then
opens the HUD. Later app launches also ensure the daemon is running.

The app uses an ad-hoc signature, not a Developer ID signature or notarization.
If macOS blocks it, review Maxi in System Settings → Privacy & Security.
Grant Microphone and appropriate Accessibility/Input Monitoring permissions
to the application or Python process running the voice listener.

## curl

```bash
curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install_macos.sh | bash
```

For an inspectable download before running:

```bash
curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install_macos.sh -o install-macos.sh
less install-macos.sh
bash install-macos.sh
```

The curl route downloads and checks the Python wheel, installs it into the private
runtime, and then downloads, checks, and installs the compiled universal app ZIP. No source clone
or Swift compilation happens on the user's computer.

## What is installed

| Location | Contents |
| --- | --- |
| `~/Applications/Maxi.app` | Compiled app (curl or a launch from the mounted DMG) |
| `/Applications/Maxi.app` | Used in place if you dragged the app here first |
| `~/.maxi/tools/uv` | Private, versioned Python installer |
| `~/.maxi/python/` | Python downloaded if required |
| `~/.maxi/venv/` | Isolated backend and dependencies |
| `~/.local/bin/maxi` | CLI link |
| `~/.maxi/.env` | Your model and speech provider configuration |

Existing `.env`, MCP configuration, chats, and memories are preserved. No
system Python is replaced. The installer does not edit shell startup files or
enable a login service. Opening Maxi starts the daemon; closing the HUD leaves
the daemon available. Run `~/.local/bin/maxi stop` to stop it.

Add `~/.local/bin` to PATH to use `maxi` from any terminal. To reconfigure:

```bash
~/.local/bin/maxi config wizard
~/.local/bin/maxi restart
```

Your LLM server/model and speech provider are configured separately. Optional
LightMem and third-party MCP servers are also separate installations.

The DMG is an **online bootstrap installer**, not an offline app or a conversion
of Python into Swift. The backend wheel ships separately; Python, the backend,
and dependency wheels are installed at setup time using [uv](https://docs.astral.sh/uv/guides/install-python/).

## Validation without launching

For CI or a manual install without configuration prompts or launch:

```bash
bash scripts/install_macos.sh --no-configure --no-launch
```

The installer also accepts `--app-source /path/to/Maxi.app`. Packaging checks can
set `MAXI_INSTALL_DIR`, `MAXI_APPS_DIR`, and `MAXI_BIN_DIR` to isolated absolute
directories; these overrides are for installation QA, not alternate locations
for a normal GUI installation.


The backend wheel contains no Swift source or native executable. `maxi hud`
opens the separately installed app after verifying backend health. Swift builds
require a source checkout. The app starts the backend on launch and after a
reopen while disconnected; API controls wait for a live WebSocket connection.
The native HUD requires `HOST=127.0.0.1` and `PORT=4848`; custom backend
ports remain available for API-only use. Startup reports a configuration error
if the backend is configured at a different address.
`maxi start` waits up to 30 seconds for HTTP readiness and exits nonzero on failure.
Startup failures are recorded in `~/.maxi/daemon.log` and `~/.maxi/launcher.log`.

For local release QA, pass `--wheel-source /path/to/maxi_ai-0.3.0b1-py3-none-any.whl`
with a `SHA256SUMS` manifest in the same directory. It can be combined with
`--app-source` to test both separate artifacts without downloading release files.


## HUD layout and auto-hide

The original compact glass pill floats below the hardware notch, with a separate
response card. Both have a static ∑ logo. There is no compact M mode, morphing,
or spinning. The response card includes New Chat, pin, speech and close controls.
The ∑ menu offers auto-hide and idle visibility settings. Escape dismisses the
HUD. Hovering pauses dismissal, and speech stays visible until it finishes.

Responses render Markdown tables, task lists, headings, quotes, lists and links.
Code blocks have syntax highlighting and individual Copy buttons. HTML blocks
also have a Preview button for self-contained interactive HTML/CSS/JavaScript;
preview frames cannot access local files, the backend or the network.
