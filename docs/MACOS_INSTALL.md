# One-step macOS installation

Requires macOS 14+ on Apple Silicon or Intel and internet access for first setup.
No preinstalled Python, Homebrew, or Xcode is needed.

## DMG

Download `Maxi-0.3.0-beta.1-macos-universal.dmg` from
[the beta release](https://github.com/krishnakanthpathi/maxi/releases/tag/v0.3.0-beta.1).
Open it, drag Maxi to Applications, and open Maxi. Both the app and mounted
volume use the ∑ icon.

On first launch, the native launcher opens the bundled `Install Maxi.command`
in Terminal. It installs Python if needed, installs the bundled backend wheel
and voice dependencies, and runs the provider wizard. Open Maxi again after
setup to start both the daemon and HUD. The installer normally opens it for you.

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

The curl route downloads and checks the compiled universal app ZIP. The backend
wheel is bundled inside the app and checked before installation. No source clone
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
of Python into Swift. It contains the backend wheel; Python and dependency
wheels are installed at setup time using [uv](https://docs.astral.sh/uv/guides/install-python/).

## Validation without launching

For CI or a manual install without configuration prompts or launch:

```bash
bash scripts/install_macos.sh --no-configure --no-launch
```

The installer also accepts `--app-source /path/to/Maxi.app`. Packaging checks can
set `MAXI_INSTALL_DIR`, `MAXI_APPS_DIR`, and `MAXI_BIN_DIR` to isolated absolute
directories; these overrides are for installation QA, not alternate locations
for a normal GUI installation.
