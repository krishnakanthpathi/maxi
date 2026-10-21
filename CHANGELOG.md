# Changelog

## 0.3.0-beta.1 — 2026-10-21

### Added
- Native macOS floating HUD with Liquid Glass on macOS 26+, a translucent fallback on macOS 14/15, and light/dark appearance support.
- Summation (∑) branding, larger bare icon controls, and an explicit New Chat action.
- Voice cancellation and HUD connection recovery regression checks.
- Release packaging for the Python backend and an unsigned Apple Silicon macOS HUD companion.

### Fixed
- Reconnect after dropped or unresponsive voice connections and after waking the Mac; ignore stale socket callbacks.
- Recover the HUD from live recording levels when its initial recording event was missed.
- Prevent late responses from restoring conversation context after New Chat, including streaming requests.
- Cancel stale voice commands so they cannot dispatch, inject text, or speak after cancellation.
- Display pairing QR images only from an explicit tool-returned path.
- Include the Swift frontend sources in Python wheels and keep API/CLI/package versions consistent.

### Release notes
- This is a beta. The macOS HUD binary is unsigned and not notarized.
- Python 3.10+ is required. The native HUD requires macOS 14+; Liquid Glass requires macOS 26+.
- The bundled prebuilt HUD targets Apple Silicon. Intel users can build the included Swift sources with Command Line Tools.
- The HUD is a companion to the Python daemon. Configure an LLM endpoint and a speech transcription provider before using voice commands.
- LightMem is an optional integration. Automatic memory injection is not part of this release. New Chat clears recent conversation, not explicitly saved long-term memories.
- Linux and Windows have the Python backend and platform hotkeys; this release does not include a native GUI for those platforms.
