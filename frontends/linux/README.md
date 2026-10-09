# Maxi Linux Desktop Frontend 🐧

Linux desktop client implementation guide and protocol spec for GTK / Qt / Tauri.

## Architecture

The Linux client operates as a system tray indicator and desktop notification/overlay that communicates with the local Maxi daemon over WebSocket and REST.

### 1. Connection
- **Base REST URL**: `http://localhost:4848/api`
- **WebSocket Event Stream**: `ws://localhost:4848/ws`

### 2. Events & Protocols
- `voice_start`: Display recording indicator on desktop panel/dock.
- `voice_interim_transcript`: Live on-screen speech display.
- `voice_stop`: Switch indicator to thinking/executing state.
- `voice_result`: Send desktop notification via `notify-send` / FreeDesktop notification spec.
- `stream_token`: Live text streaming.

### 3. System Requirements
- Maxi core daemon requires Python 3.10+.
- Optional voice push-to-talk requires `libasound2` and `libportaudio2`.
- Background service managed via `systemd --user` (`~/.config/systemd/user/maxi.service`).
