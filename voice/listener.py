#!/usr/bin/env python3
"""
🎙️ Maxi Push-to-Talk Voice Service
Decoupled background voice daemon using Groq whisper-large-v3-turbo for STT.
Trigger: Hold [Control + Space], speak your command, release to dispatch to Maxi daemon.

Architecture:
[Microphone Audio] ──> [Groq Whisper STT (~120ms)] ──> [POST /api/voice/webhook] ──> [Maxi Agent]
"""

import io
import os
import re
import sys
import time
import wave
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from pynput import keyboard
import httpx

SAMPLE_RATE = 16000
CHANNELS = 1
DEFAULT_DAEMON_URL = "http://127.0.0.1:4848"


def get_groq_api_key() -> str:
    """Resolves Groq API key from environment, .env file, or ~/.zshrc."""
    key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROK_API_KEY")
    if key:
        return key

    # Check local .env
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY=") or line.startswith("GROK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    # Check ~/.zshrc
    zshrc_file = Path.home() / ".zshrc"
    if zshrc_file.exists():
        for line in zshrc_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^export\s+(?:GROQ|GROK)_API_KEY=[\"']?([^\"'\s]+)", line)
            if m:
                return m.group(1).strip()

    return ""


def play_sound(sound_name: str):
    """Play macOS system audio chime asynchronously."""
    sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
    if os.path.exists(sound_path):
        subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_notification(title: str, message: str, subtitle: str = ""):
    """Display native macOS notification banner."""
    clean_msg = message.replace('"', '\\"').replace("\n", " ")[:120]
    clean_title = title.replace('"', '\\"')
    clean_sub = subtitle.replace('"', '\\"') if subtitle else ""
    sub_clause = f'subtitle "{clean_sub}"' if clean_sub else ""
    script = f'display notification "{clean_msg}" with title "{clean_title}" {sub_clause}'
    subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class VoiceService:
    def __init__(self, daemon_url: str = DEFAULT_DAEMON_URL, groq_key: str = ""):
        self.daemon_url = daemon_url.rstrip("/")
        self.groq_key = groq_key or get_groq_api_key()
        if not self.groq_key:
            print("⚠️ Warning: No GROQ_API_KEY found in environment or ~/.zshrc.")

        # Key state
        self.ctrl_pressed = False
        self.space_pressed = False
        self.is_recording = False
        self.audio_buffer = []
        self.stream = None
        self.lock = threading.Lock()

    def _is_ctrl(self, key) -> bool:
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return True
        if hasattr(key, "vk") and key.vk in (59, 62):
            return True
        return False

    def _is_space(self, key) -> bool:
        if key == keyboard.Key.space:
            return True
        if hasattr(key, "vk") and key.vk == 49:
            return True
        if hasattr(key, "char") and key.char == " ":
            return True
        return False

    def _audio_callback(self, indata, frames, time_info, status):
        if self.is_recording:
            self.audio_buffer.append(indata.copy())

    def start_recording(self):
        with self.lock:
            if self.is_recording:
                return
            self.is_recording = True
            self.audio_buffer = []
            play_sound("Tink")
            print("\n🎙️ [Recording...] Speak your command (Hold Control + Space)")
            try:
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback
                )
                self.stream.start()
            except Exception as e:
                print(f"❌ Error starting microphone stream: {e}")
                self.is_recording = False

    def stop_recording(self):
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

        if not self.audio_buffer:
            print("⚠️ No audio captured.")
            return

        chunks = list(self.audio_buffer)
        threading.Thread(target=self._process_audio, args=(chunks,), daemon=True).start()

    def _process_audio(self, chunks):
        audio_data = np.concatenate(chunks, axis=0)
        # Filter out quick accidental taps (< 300 ms)
        if len(audio_data) < SAMPLE_RATE * 0.3:
            print("⚠️ Audio too short (<300ms). Ignored.")
            return

        print("⚡ [Transcribing via Groq Whisper...]")
        t0 = time.perf_counter()

        # Convert to WAV bytes in memory
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            int16_data = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)
            wf.writeframes(int16_data.tobytes())
        wav_bytes = buf.getvalue()

        # 1. Transcribe via Groq Whisper API
        transcript = ""
        try:
            headers = {"Authorization": f"Bearer {self.groq_key}"}
            files = {"file": ("command.wav", wav_bytes, "audio/wav")}
            data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data
                )
                if resp.status_code == 200:
                    transcript = resp.json().get("text", "").strip()
                else:
                    print(f"❌ Groq STT error {resp.status_code}: {resp.text}")
                    return
        except Exception as e:
            print(f"❌ Failed to transcribe via Groq: {e}")
            return

        if not transcript or transcript in (".", "...", "!", "?"):
            print("⚠️ No clear speech recognized.")
            return

        stt_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        print(f"🗣️ Transcript ({stt_latency_ms}ms): \"{transcript}\"")
        play_sound("Pop")

        # 2. Forward to Maxi Daemon
        print(f"🚀 Dispatching to Maxi Daemon @ {self.daemon_url}/api/voice/webhook...")
        t_agent = time.perf_counter()
        agent_output = ""
        tools_used = []
        try:
            with httpx.Client(timeout=30.0) as client:
                webhook_resp = client.post(
                    f"{self.daemon_url}/api/voice/webhook",
                    json={"transcript": transcript, "client": "groq_voice_service"}
                )
                if webhook_resp.status_code == 200:
                    res = webhook_resp.json()
                    agent_output = res.get("output", "")
                    tools_used = res.get("tools_used", [])
                else:
                    agent_output = f"Daemon returned error {webhook_resp.status_code}"
        except Exception as e:
            agent_output = f"Cannot reach Maxi daemon at {self.daemon_url}: {e}"

        total_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        print(f"⚡ Maxi Result ({total_latency_ms}ms total): {agent_output}")
        if tools_used:
            print(f"🛠️  Tools executed: {', '.join(tools_used)}")

        show_notification(
            title="Maxi Voice 🎙️",
            message=agent_output or "Command executed.",
            subtitle=transcript
        )

    def on_press(self, key):
        if self._is_ctrl(key):
            self.ctrl_pressed = True
        elif self._is_space(key):
            self.space_pressed = True

        if self.ctrl_pressed and self.space_pressed and not self.is_recording:
            self.start_recording()

    def on_release(self, key):
        was_recording = self.is_recording
        if self._is_ctrl(key):
            self.ctrl_pressed = False
        elif self._is_space(key):
            self.space_pressed = False

        if was_recording and not (self.ctrl_pressed and self.space_pressed):
            self.stop_recording()

    def run(self):
        print("=" * 65)
        print("🎙️  MAXI DECOUPLED VOICE SERVICE (Groq Whisper-Turbo)")
        print("=" * 65)
        print(f"• Hotkey:     Hold [Control + Space], speak, release")
        print(f"• STT Engine: Groq whisper-large-v3-turbo")
        print(f"• Daemon:     {self.daemon_url}")
        print("• Audio FX:   Tink (start recording) | Pop (processed)")
        print("• Exit:       Press [Ctrl + C] in this terminal")
        print("=" * 65)

        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            try:
                listener.join()
            except KeyboardInterrupt:
                print("\nShutting down voice service...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maxi Push-to-Talk Voice Service")
    parser.add_argument("--daemon-url", default=DEFAULT_DAEMON_URL, help="Maxi daemon endpoint")
    parser.add_argument("--groq-key", default="", help="Custom Groq API key")
    args = parser.parse_args()

    service = VoiceService(daemon_url=args.daemon_url, groq_key=args.groq_key)
    service.run()
