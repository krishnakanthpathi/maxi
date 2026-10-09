# Maxi macOS Native Frontend 🍏

Native Apple macOS Siri-style floating HUD and Menu Bar assistant built in Swift and SwiftUI.

---

## ⚡ Features

- **Floating Glass HUD (`NSPanel`)**:
  - Pinned on level `.floating` across **all Mission Control Spaces** (`.canJoinAllSpaces`).
  - Native Apple frosted glass (`.ultraThinMaterial`) with specular hairline borders.
  - Non-activating HUD (`.nonactivatingPanel`): Never steals keyboard focus from your active code editor or browser.
  - Smooth spring transitions and auto-dismiss after 6 seconds of inactivity.
  - Global `ESC` key dismiss.
- **Bioluminescent Siri Acoustic Orb**:
  - Reactive multi-layer angular and radial plasma gradients.
  - **Idle**: Soft cyan ambient breathing glow.
  - **Listening (Right Option ⌥)**: Expands into vibrant acoustic ripples (hot pink -> electric cyan -> amber) synchronized with speech.
  - **Thinking / Processing**: Swirling revolving luminous rings while Ollama generates.
  - **Responding**: Synchronized pulsing glow with real-time token streaming.
- **Menu Bar Companion (`NSStatusItem`)**:
  - Minimalist Lightning Crest (`⚡`) in macOS status bar.
  - Live status indicator (Daemon connection state, active MCP tools count, Ollama model).
  - Quick actions: Toggle HUD, audition sound chimes, open Web Workstation, restart daemon.
- **WebSocket Event Bridge (`ws://127.0.0.1:4848/ws`)**:
  - Real-time bi-directional synchronization with the background Python daemon.
  - Supports both push-to-talk voice commands and instant typed commands.

---

## 🚀 Quick Start

### 1. Launch the App
To start the native macOS app immediately:
```bash
open "frontends/macos/dist/Maxi.app"
```
Or directly run the compiled binary:
```bash
./frontends/macos/dist/Maxi.app/Contents/MacOS/MaxiHUD
```

### 2. Global Hotkey Activation
- Hold **Right Option (`⌥`)** anywhere on macOS to speak.
- The Siri HUD will instantly glide in, listen to your command, and execute workstation tools.
- Release **Right Option (`⌥`)** to finish and stream the response.
- Press **`ESC`** or click outside to dismiss.

---

## 🛠️ Build & Package from Source

Requires macOS 13+ (Ventura, Sonoma, Sequoia, Tahoe) and Swift 5.9+:

```bash
# Compile and build the native app bundle
./frontends/macos/scripts/build_app.sh
```

The output bundle is generated at:
`frontends/macos/dist/Maxi.app`
