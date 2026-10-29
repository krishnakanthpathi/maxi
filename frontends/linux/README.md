# Maxi Linux Environment

This directory is reserved for the native Linux frontend/HUD companion (e.g., GTK4/Adwaita, Qt/QML, or WebKit/Tauri floating HUD).

Currently, Linux runs in backend daemon mode:
- Background service: `systemd --user` (`maxi.service`)
- Global voice push-to-talk hotkey: `Control + Space`
- Local REST and WebSocket API: `http://127.0.0.1:4848`
- Audio speech synthesis: `spd-say`, `espeak-ng`, or remote Kokoro
