# Maxi macOS Native Frontend 🍏

Native Apple macOS frontend implementation guide and client architecture.

## Architecture

The macOS frontend is designed as a lightweight Swift/SwiftUI application that docks in the menu bar and displays a floating translucent HUD panel over all spaces when triggered.

### 1. Connection
- **Base REST URL**: `http://localhost:4848/api`
- **WebSocket Event Stream**: `ws://localhost:4848/ws`

### 2. Global Hotkey & Activation
- By default, the Maxi daemon captures **Right Option** globally.
- The Swift app can optionally monitor the WebSocket events:
  - `voice_start`: Expand the floating Siri-style dynamic orb.
  - `voice_interim_transcript`: Update live subtitle text with streaming words while the user speaks.
  - `voice_locked`: Show lock icon indicator (hands-free mode).
  - `voice_stop`: Transition orb to thinking/processing state.
  - `voice_result`: Display final response card and tool execution badges.
  - `stream_token`: Live character-by-character typing animation.

### 3. REST Control Endpoints
- `POST /api/prompt` -> `{"text": "...", "source": "macos:menubar"}`
- `GET /api/sounds` -> Lists available sound themes (`minimal`, `glass`, `soft`, `scifi`, `zen`, `synth`)
- `POST /api/sounds/set` -> `{"start_sound": "minimal_wake", "finish_sound": "minimal_complete"}`
- `GET /api/mcp/tools` -> Live list of loaded MCP workstation tools
