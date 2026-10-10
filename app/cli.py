"""
Maxi Command Line Interface (CLI)
Entrypoint for `maxi start`, `maxi stop`, `maxi status`, `maxi hud`, `maxi run`.
"""

import sys
import os
import time
import argparse
import subprocess
import signal
from pathlib import Path
import httpx

PID_FILE = Path.home() / ".maxi" / "daemon.pid"


def get_pid() -> int | None:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process is still alive
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)
    return None


def cmd_run(args):
    """Run daemon in foreground."""
    import uvicorn
    from app.config import settings

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    try:
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            reload=args.reload or settings.debug,
            log_level="info"
        )
    finally:
        PID_FILE.unlink(missing_ok=True)


def get_python_exe() -> str:
    """Finds the isolated virtual environment python interpreter."""
    v1 = Path.home() / ".maxi" / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if v1.exists():
        return str(v1)
    v2 = Path(__file__).resolve().parent.parent / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if v2.exists():
        return str(v2)
    return sys.executable


def cmd_start(args):
    """Start daemon in background process."""
    existing_pid = get_pid()
    if existing_pid:
        print(f"⚡ Maxi daemon is already running (PID: {existing_pid}).")
        return

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = PID_FILE.parent / "daemon.log"

    print("🚀 Starting Maxi background daemon...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True

    py_exe = get_python_exe()
    with open(log_file, "a") as log_out:
        proc = subprocess.Popen(
            [py_exe, "-m", "app.cli", "run"],
            stdout=log_out,
            stderr=log_out,
            **kwargs
        )

    # Give process 1-2 seconds to bind port
    time.sleep(1.5)
    if proc.poll() is None:
        PID_FILE.write_text(str(proc.pid))
        print(f"✅ Maxi daemon started (PID: {proc.pid}) on http://127.0.0.1:4848")
        print(f"📜 Logs: {log_file}")
    else:
        print(f"❌ Failed to start daemon. Inspect logs at {log_file}")


def cmd_stop(args):
    """Stop running background daemon."""
    pid = get_pid()
    if not pid:
        # Also check if something is on port 4848
        print("ℹ️  No active Maxi daemon PID file found.")
        return

    print(f"🛑 Stopping Maxi daemon (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        if get_pid():
            kill_sig = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, kill_sig)
        print("✅ Daemon stopped.")
    except (ProcessLookupError, OSError):
        print("ℹ️  Process already terminated.")
    finally:
        PID_FILE.unlink(missing_ok=True)


def cmd_restart(args):
    """Restart background daemon."""
    cmd_stop(args)
    time.sleep(1.0)
    cmd_start(args)


def cmd_status(args):
    """Check status of Maxi daemon and active tools."""
    pid = get_pid()
    try:
        resp = httpx.get("http://127.0.0.1:4848/api/health", timeout=2.0)
        if resp.status_code == 200:
            print(f"⚡ Maxi Daemon: RUNNING (PID: {pid or 'External'})")
            print("   Endpoint: http://127.0.0.1:4848")

            # Check MCP tools
            tools_resp = httpx.get("http://127.0.0.1:4848/api/mcp/tools", timeout=2.0)
            if tools_resp.status_code == 200:
                tools_data = tools_resp.json()
                print(f"   MCP Tools: {tools_data.get('count', 0)} loaded")

            # Check sounds
            sounds_resp = httpx.get("http://127.0.0.1:4848/api/sounds", timeout=2.0)
            if sounds_resp.status_code == 200:
                sdata = sounds_resp.json()
                active = sdata.get("active", {})
                print(f"   Audio Theme: {active.get('start_sound')} -> {active.get('finish_sound')}")
            return
    except Exception:
        pass

    print("💤 Maxi Daemon: STOPPED")


def cmd_hud(args):
    """Open the web HUD in the default browser."""
    import webbrowser
    url = "http://127.0.0.1:4848/hud"
    print(f"🌐 Opening Maxi HUD at {url}...")
    webbrowser.open(url)


def _run_config_wizard():
    from app.core.config_manager import save_config, get_current_config
    cfg = get_current_config()
    print("\n🧙 Maxi Interactive Setup Wizard\n")
    print("Select LLM Provider:")
    print("  1) Ollama (Local Default - http://localhost:11434/v1)")
    print("  2) Groq (Cloud - https://api.groq.com/openai/v1)")
    print("  3) OpenRouter (Cloud - https://openrouter.ai/api/v1)")
    print("  4) Custom OpenAI-compatible URL")

    try:
        choice = input("Enter choice [1-4, default 1]: ").strip() or "1"
        updates = {}
        if choice == "1":
            updates["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
            m = input(f"Ollama model [default {cfg['llm_model']}]: ").strip() or cfg["llm_model"]
            updates["OPENAI_MODEL"] = m
            updates["OPENAI_API_KEY"] = "ollama"
        elif choice == "2":
            updates["OPENAI_BASE_URL"] = "https://api.groq.com/openai/v1"
            updates["OPENAI_MODEL"] = "llama-3.3-70b-versatile"
            k = input("Groq API Key: ").strip() or cfg["llm_key"]
            updates["OPENAI_API_KEY"] = k
        elif choice == "3":
            updates["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
            updates["OPENAI_MODEL"] = "meta-llama/llama-3.3-70b-instruct"
            k = input("OpenRouter API Key: ").strip() or cfg["llm_key"]
            updates["OPENAI_API_KEY"] = k
        else:
            url = input(f"Base URL [{cfg['llm_url']}]: ").strip() or cfg["llm_url"]
            model = input(f"Model [{cfg['llm_model']}]: ").strip() or cfg["llm_model"]
            key = input(f"API Key [{cfg['llm_key_masked']}]: ").strip() or cfg["llm_key"]
            updates["OPENAI_BASE_URL"] = url
            updates["OPENAI_MODEL"] = model
            updates["OPENAI_API_KEY"] = key

        print("\nSelect Voice STT Provider:")
        print("  1) Groq Whisper (Cloud Default - whisper-large-v3-turbo)")
        print("  2) Local Whisper (Local Default - http://localhost:8000/v1)")
        print("  3) Keep current voice settings")

        v_choice = input("Enter choice [1-3, default 1]: ").strip() or "1"
        if v_choice == "1":
            updates["VOICE_BASE_URL"] = "https://api.groq.com/openai/v1"
            updates["VOICE_MODEL"] = "whisper-large-v3-turbo"
            vk = input(f"Groq Voice API Key [{cfg['voice_key_masked']}]: ").strip()
            if vk:
                updates["VOICE_API_KEY"] = vk
        elif v_choice == "2":
            updates["VOICE_BASE_URL"] = "http://localhost:8000/v1"
            updates["VOICE_MODEL"] = "whisper-1"
            updates["VOICE_API_KEY"] = "local-key"

        print("\nSelect Siri TTS Output Voice:")
        print("  1) Tara     (Siri Female - India Premium, en_IN)")
        print("  2) Samantha (Siri Female - US Classic, en_US)")
        print("  3) Daniel   (Siri Male   - UK British, en_GB)")
        print("  4) Karen    (Siri Female - Australia, en_AU)")
        print("  5) Moira    (Siri Female - Ireland, en_IE)")
        print("  6) Rishi    (Siri Male   - India, en_IN)")
        print("  7) Aman     (Siri Male   - India Conversational, en_IN)")
        print("  8) Custom macOS voice name (e.g. Eddy, Flo, Tessa)")
        print("  9) Disable TTS Voice Output")

        cur_tts_voice = cfg.get("tts_voice", "Tara")
        t_choice = input(f"Enter choice [1-9, default keep '{cur_tts_voice}']: ").strip()
        tts_map = {
            "1": "Tara",
            "2": "Samantha",
            "3": "Daniel",
            "4": "Karen",
            "5": "Moira",
            "6": "Rishi",
            "7": "Aman",
        }
        if t_choice in tts_map:
            updates["ENABLE_TTS"] = "true"
            updates["TTS_VOICE"] = tts_map[t_choice]
        elif t_choice == "8":
            custom_v = input(f"Enter macOS voice name [{cur_tts_voice}]: ").strip() or cur_tts_voice
            updates["ENABLE_TTS"] = "true"
            updates["TTS_VOICE"] = custom_v
        elif t_choice == "9":
            updates["ENABLE_TTS"] = "false"

        _, msg = save_config(updates)
        print("\n🎉 Configuration updated successfully!")
        print(f"📜 {msg}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nWizard cancelled.")


def _print_available_voices(preview_voice: str = None):
    """Display all Siri TTS presets and installed macOS voices."""
    from app.core.config_manager import get_current_config
    from app.core.tts import (
        SIRI_VOICE_PRESETS, SIRI_VOICE_ALIASES,
        resolve_siri_voice, tts_service
    )

    cfg = get_current_config()
    active_raw = cfg.get("tts_voice", "Tara")
    active_resolved = resolve_siri_voice(active_raw)
    tts_enabled = cfg.get("enable_tts", True)
    tts_rate = cfg.get("tts_rate", 190)

    print("\n🔊 Maxi Siri TTS Voices")
    print("━" * 64)
    print(f"Active Voice:  {active_resolved} (Configured: '{active_raw}', Rate: {tts_rate} WPM, {'Enabled' if tts_enabled else 'Disabled'})")
    print("")
    print("🌟 Recommended Siri Voice Presets:")
    for key, info in SIRI_VOICE_PRESETS.items():
        marker = "✅ (Active)" if info["voice"].lower() == active_resolved.lower() else ""
        print(f"  • {key:<10} -> {info['voice']:<10} [{info['locale']}]  {info['description']} {marker}")

    print("\n🏷️  Quick Aliases:")
    print("  siri / siri-in -> Tara   | siri-us -> Samantha | siri-uk -> Daniel")
    print("  siri-au        -> Karen  | siri-ie -> Moira    | rishi / aman")

    installed = tts_service.list_available_voices()
    if installed:
        print(f"\n🍎 All Installed macOS English Voices ({len(installed)} available):")
        for v in installed:
            v_base = v["name"].split("(")[0].strip().lower()
            is_act = "✅" if v_base == active_resolved.lower() or v["name"].lower() == active_resolved.lower() else "  "
            print(f"  {is_act} {v['name']:<26} [{v['locale']}]  \"{v['sample']}\"")

    print("━" * 64)
    print("How to change or test TTS voice:")
    print("  • Change voice:       maxi config set tts-voice samantha")
    print("                        maxi config --tts-voice daniel")
    print("                        maxi tts set tara")
    print("  • Change speed (WPM): maxi config set tts-rate 195")
    print("  • Toggle TTS on/off:  maxi config set tts true/false")
    print("  • Preview a voice:    maxi tts test samantha")
    print("")

    if preview_voice:
        resolved = resolve_siri_voice(preview_voice)
        sample_text = f"Hello! I am Maxi, speaking with the {resolved} voice."
        print(f"🔊 Previewing '{resolved}' ({tts_rate} WPM): \"{sample_text}\"")
        tts_service.speak(sample_text, voice=resolved, rate=tts_rate, block=True)


def cmd_tts(args):
    """Manage and preview Siri TTS voices directly from the terminal."""
    from app.core.config_manager import save_config
    from app.core.tts import resolve_siri_voice, tts_service

    action = getattr(args, "tts_action", None) or "voices"
    if action == "voices":
        _print_available_voices(preview_voice=getattr(args, "test", None))
    elif action == "set":
        voice_val = getattr(args, "voice_name", None)
        if not voice_val:
            print("Usage: maxi tts set <voice_name>")
            return
        resolved = resolve_siri_voice(voice_val)
        updates = {"TTS_VOICE": resolved, "ENABLE_TTS": "true"}
        if getattr(args, "rate", None):
            updates["TTS_RATE"] = str(args.rate)
        _, msg = save_config(updates)
        print(f"✅ Switched Siri TTS voice to: {resolved}")
        print(f"📜 {msg}")
        if not getattr(args, "no_preview", False):
            tts_service.speak(f"Hi, I'm Maxi using the {resolved} voice.", voice=resolved, block=True)
    elif action == "test":
        voice_val = getattr(args, "voice_name", None)
        resolved = resolve_siri_voice(voice_val)
        text = getattr(args, "text", None) or f"Hello! I am Maxi speaking with the {resolved} voice."
        print(f"🔊 Testing TTS voice '{resolved}': \"{text}\"")
        tts_service.speak(text, voice=resolved, block=True)
    elif action == "on":
        _, msg = save_config({"ENABLE_TTS": "true"})
        print("✅ Siri TTS enabled.")
        print(f"📜 {msg}")
    elif action == "off":
        _, msg = save_config({"ENABLE_TTS": "false"})
        print("🔇 Siri TTS disabled.")
        print(f"📜 {msg}")
    else:
        _print_available_voices()


def cmd_config(args):
    """View and update Maxi LLM, Voice, and System configurations."""
    from app.core.config_manager import (
        get_current_config, save_config, PRESETS, VOICE_PRESETS,
        KEY_ALIASES, mask_secret
    )
    from app.core.tts import SIRI_VOICE_PRESETS, SIRI_VOICE_ALIASES, resolve_siri_voice

    # 0. Voices subcommand
    if getattr(args, "config_action", None) == "voices" or getattr(args, "list_voices", False):
        _print_available_voices(preview_voice=getattr(args, "test_voice", None))
        return

    # 1. Preset subcommand or flag
    preset_arg = getattr(args, "preset_name", None) or getattr(args, "preset", None)
    if getattr(args, "config_action", None) == "preset" or preset_arg:
        preset_name = (preset_arg or "").lower()
        if preset_name in PRESETS:
            p = PRESETS[preset_name]
            key = getattr(args, "key", None)
            if not key and p["requires_key"]:
                cur_key = get_current_config()["llm_key"]
                if cur_key and cur_key not in ("ollama", "sk-local-no-key-required", "sk-dummy-key"):
                    key = cur_key
                else:
                    try:
                        key = input(f"🔑 Enter API Key for {p['name']}: ").strip()
                    except (KeyboardInterrupt, EOFError):
                        print("\nAborted.")
                        return
            updates = {
                "OPENAI_BASE_URL": p["llm_url"],
                "OPENAI_MODEL": p["llm_model"],
                "OPENAI_API_KEY": key or p["llm_key"]
            }
            _, msg = save_config(updates)
            print(f"✅ Switched LLM preset to {p['name']}:")
            print(f"   URL:   {p['llm_url']}")
            print(f"   Model: {p['llm_model']}")
            print(f"   Key:   {mask_secret(updates['OPENAI_API_KEY'])}")
            print(f"📜 {msg}")
            return
        elif preset_name in VOICE_PRESETS:
            vp = VOICE_PRESETS[preset_name]
            key = getattr(args, "key", None)
            if not key and vp["requires_key"]:
                cur_key = get_current_config()["voice_key"]
                if cur_key:
                    key = cur_key
                else:
                    try:
                        key = input(f"🔑 Enter Voice API Key for {vp['name']}: ").strip()
                    except (KeyboardInterrupt, EOFError):
                        print("\nAborted.")
                        return
            updates = {
                "VOICE_BASE_URL": vp["voice_url"],
                "VOICE_MODEL": vp["voice_model"],
                "VOICE_API_KEY": key or vp["voice_key"]
            }
            _, msg = save_config(updates)
            print(f"✅ Switched Voice preset to {vp['name']}:")
            print(f"   URL:   {vp['voice_url']}")
            print(f"   Model: {vp['voice_model']}")
            print(f"   Key:   {mask_secret(updates['VOICE_API_KEY'])}")
            print(f"📜 {msg}")
            return
        elif preset_name in SIRI_VOICE_PRESETS or preset_name in SIRI_VOICE_ALIASES:
            resolved = resolve_siri_voice(preset_name)
            p_info = SIRI_VOICE_PRESETS.get(resolved.lower(), {"name": resolved, "locale": "en"})
            updates = {
                "TTS_VOICE": resolved,
                "ENABLE_TTS": "true",
            }
            _, msg = save_config(updates)
            print(f"✅ Switched Siri TTS voice preset to {p_info.get('name', resolved)}:")
            print(f"   Voice:  {resolved} ({p_info.get('locale', 'en')})")
            print(f"📜 {msg}")
            return
        else:
            print(f"❌ Unknown preset '{preset_name}'.")
            print(f"   Available LLM presets:      {', '.join(PRESETS.keys())}")
            print(f"   Available Voice presets:    {', '.join(VOICE_PRESETS.keys())}")
            print(f"   Available Siri TTS presets: {', '.join(SIRI_VOICE_PRESETS.keys())}")
            return

    # 2. Get subcommand
    if getattr(args, "config_action", None) == "get":
        k = getattr(args, "key_name", None)
        if not k:
            print("Usage: maxi config get <key>")
            return
        canonical = KEY_ALIASES.get(k.lower(), k)
        cfg = get_current_config()
        mapping = {
            "OPENAI_BASE_URL": cfg["llm_url"],
            "OPENAI_API_KEY": cfg["llm_key"],
            "OPENAI_MODEL": cfg["llm_model"],
            "VOICE_BASE_URL": cfg["voice_url"],
            "VOICE_API_KEY": cfg["voice_key"],
            "VOICE_MODEL": cfg["voice_model"],
            "VOICE_HOTKEY": cfg.get("voice_hotkey", "auto"),
            "VOICE_AUTO_ENDPOINT": cfg["auto_endpoint"],
            "ENABLE_VOICE_HOTKEY": cfg["hotkey_enabled"],
            "ENABLE_WAKE_WORD": cfg.get("enable_wake_word", False),
            "VOICE_WAKE_WORDS": cfg.get("wake_words", "hey maxi,hey siri"),
            "WAKE_WORD_AUTO_PREFIX": cfg.get("wake_word_auto_prefix", False),
            "ENABLE_TTS": cfg.get("enable_tts", True),
            "TTS_VOICE": cfg.get("tts_voice", "Tara"),
            "TTS_RATE": cfg.get("tts_rate", 190),
            "TTS_SPEAK_ALL_SOURCES": cfg.get("tts_speak_all_sources", False),
            "AGENT_TIMEOUT_SECONDS": cfg.get("agent_timeout_seconds", 90.0),
        }
        val = mapping.get(canonical, "Unknown key")
        print(f"{k} = {val}")
        return

    # 3. Set subcommand
    if getattr(args, "config_action", None) == "set":
        k = getattr(args, "key_name", None)
        v = getattr(args, "value", None)
        if not k or v is None:
            print("Usage: maxi config set <key> <value>")
            print("Examples:")
            print("  maxi config set tts-voice samantha")
            print("  maxi config set tts-rate 190")
            print("  maxi config set tts true")
            print("  maxi config set llm-url http://localhost:11434/v1")
            print("  maxi config set llm-model llama3.2")
            print("  maxi config set voice-key gsk_...")
            return
        canonical = KEY_ALIASES.get(k.lower(), k)
        if canonical == "TTS_VOICE":
            v = resolve_siri_voice(v)
        _, msg = save_config({canonical: v})
        disp_val = mask_secret(v) if "KEY" in canonical.upper() else v
        print(f"✅ Set {canonical} = {disp_val}")
        print(f"📜 {msg}")
        return

    # 4. Direct flags
    flag_updates = {}
    if getattr(args, "llm_url", None):
        flag_updates["OPENAI_BASE_URL"] = args.llm_url
    if getattr(args, "llm_key", None):
        flag_updates["OPENAI_API_KEY"] = args.llm_key
    if getattr(args, "llm_model", None):
        flag_updates["OPENAI_MODEL"] = args.llm_model
    if getattr(args, "voice_url", None):
        flag_updates["VOICE_BASE_URL"] = args.voice_url
    if getattr(args, "voice_key", None):
        flag_updates["VOICE_API_KEY"] = args.voice_key
    if getattr(args, "voice_model", None):
        flag_updates["VOICE_MODEL"] = args.voice_model
    if getattr(args, "tts_voice", None):
        flag_updates["TTS_VOICE"] = resolve_siri_voice(args.tts_voice)
    if getattr(args, "tts_rate", None) is not None:
        flag_updates["TTS_RATE"] = str(args.tts_rate)
    if getattr(args, "tts", None) is not None:
        flag_updates["ENABLE_TTS"] = str(args.tts).lower()

    if flag_updates:
        _, msg = save_config(flag_updates)
        print("✅ Updated configuration:")
        for k, v in flag_updates.items():
            disp_v = mask_secret(v) if "KEY" in k else v
            print(f"   {k} = {disp_v}")
        print(f"📜 {msg}")
        return

    # 5. Wizard / interactive mode
    if getattr(args, "config_action", None) == "wizard" or getattr(args, "interactive", False):
        _run_config_wizard()
        return

    # 6. Default: Display active dashboard
    cfg = get_current_config()
    llm_preset_info = PRESETS.get(cfg["llm_preset"], {}).get("name", "Custom Endpoint")
    voice_preset_info = VOICE_PRESETS.get(cfg["voice_preset"], {}).get("name", "Custom STT")

    tts_voice_raw = cfg.get("tts_voice", "Tara")
    tts_voice_resolved = resolve_siri_voice(tts_voice_raw)
    tts_preset_meta = SIRI_VOICE_PRESETS.get(tts_voice_resolved.lower(), {})
    tts_voice_label = tts_preset_meta.get("name", f"{tts_voice_resolved} (macOS Voice)")

    print("\n⚡ Maxi Configuration")
    print("━" * 58)
    print(f"🧠 LLM Provider:        {llm_preset_info}")
    print(f"   Endpoint URL:        {cfg['llm_url']}")
    print(f"   Model:               {cfg['llm_model']}")
    print(f"   API Key:             {cfg['llm_key_masked']}")
    print("")
    print(f"🎙️ Voice STT Provider:  {voice_preset_info}")
    print(f"   Endpoint URL:        {cfg['voice_url']}")
    print(f"   Model:               {cfg['voice_model']}")
    print(f"   API Key:             {cfg['voice_key_masked']}")
    print("")
    print(f"🔊 Siri TTS Output:     {'Active' if cfg.get('enable_tts', True) else 'Disabled'}")
    print(f"   Active Voice:        {tts_voice_resolved} — {tts_voice_label}")
    print(f"   Speech Rate:         {cfg.get('tts_rate', 190)} WPM")
    print(f"   Siri Presets:        {', '.join(SIRI_VOICE_PRESETS.keys())}")
    print("")
    hotkey_pref = (cfg.get("voice_hotkey") or "auto").lower()
    if hotkey_pref == "auto":
        hotkey_name = "Right Option (⌥)" if sys.platform == "darwin" else "Control + Space"
    elif hotkey_pref in ("right_option", "option_r", "alt_r", "option"):
        hotkey_name = "Right Option (⌥)"
    else:
        hotkey_name = "Control + Space"

    print("⚙️ Audio & Interface:")
    print(f"   Push-to-Talk Hotkey: {hotkey_name} ({'Active' if cfg['hotkey_enabled'] else 'Disabled'})")
    wake_status = "Active" if cfg.get("enable_wake_word", False) else "Disabled"
    print(f"   Wake Word Auto-Catch: {wake_status} (Triggers: {cfg.get('wake_words', 'hey maxi,hey siri')})")
    print(f"   Prompt Auto-Prefix:  {'Enabled (Hey Maxi, ...)' if cfg.get('wake_word_auto_prefix', False) else 'Disabled'}")
    print(f"   Auto-Endpoint:       {'Enabled' if cfg['auto_endpoint'] else 'Disabled (Hold to speak)'}")
    print(f"   Config File:         {cfg['env_file']}")
    print("━" * 58)
    print("Commands:")
    print("  • List all TTS voices:        maxi config voices  (or: maxi tts)")
    print("  • Change Siri TTS voice:      maxi config set tts-voice <tara|samantha|daniel|karen|moira|rishi|aman>")
    print("  • Preview a TTS voice:        maxi tts test <voice>")
    print("  • Change TTS speed (WPM):     maxi config set tts-rate 190")
    print("  • Toggle TTS on/off:          maxi config set tts true/false")
    print("  • Switch LLM preset:          maxi config preset <ollama|groq|openrouter>")
    print("  • Toggle hands-free wake:     maxi config set wake-word true/false")
    print("  • Interactive wizard:         maxi config wizard")
    print("")


def main():
    parser = argparse.ArgumentParser(
        prog="maxi",
        description="⚡ Maxi - Pluggable, ultra-fast background AI agent daemon"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # run
    p_run = subparsers.add_parser("run", help="Run daemon in foreground")
    p_run.add_argument("--reload", action="store_true", help="Enable live code reload")

    # start
    subparsers.add_parser("start", help="Start daemon in background")

    # stop
    subparsers.add_parser("stop", help="Stop background daemon")

    # restart
    subparsers.add_parser("restart", help="Restart background daemon")

    # status
    subparsers.add_parser("status", help="Check daemon and MCP health")

    # hud
    subparsers.add_parser("hud", help="Open Maxi HUD in browser")

    # tts
    p_tts = subparsers.add_parser("tts", help="List, preview, and configure Siri TTS voices")
    p_tts.add_argument("--test", help="Preview a specific voice aloud")
    tts_sub = p_tts.add_subparsers(dest="tts_action", help="TTS subaction")

    p_tts_voices = tts_sub.add_parser("voices", help="List all available Siri and macOS TTS voices")
    p_tts_voices.add_argument("--test", help="Preview a specific voice aloud")

    p_tts_set = tts_sub.add_parser("set", help="Set the active Siri TTS voice")
    p_tts_set.add_argument("voice_name", help="Voice name or alias (e.g. tara, samantha, daniel, karen, moira, rishi, aman)")
    p_tts_set.add_argument("--rate", type=int, help="Optional speech rate in WPM (default 190)")
    p_tts_set.add_argument("--no-preview", action="store_true", help="Do not play audio preview after switching")

    p_tts_test = tts_sub.add_parser("test", help="Speak a sample phrase with a voice")
    p_tts_test.add_argument("voice_name", nargs="?", default=None, help="Voice to preview (defaults to active voice)")
    p_tts_test.add_argument("text", nargs="?", default=None, help="Optional custom text to speak")

    tts_sub.add_parser("on", help="Enable Siri TTS voice output")
    tts_sub.add_parser("off", help="Disable Siri TTS voice output")

    # config
    p_cfg = subparsers.add_parser("config", help="View or update LLM, Voice STT, and Siri TTS configuration")
    p_cfg.add_argument("--llm-url", help="Set OpenAI-compatible LLM endpoint URL")
    p_cfg.add_argument("--llm-key", help="Set LLM API key")
    p_cfg.add_argument("--llm-model", help="Set target model (e.g. llama3.2, llama-3.3-70b-versatile)")
    p_cfg.add_argument("--voice-url", help="Set Voice STT endpoint URL")
    p_cfg.add_argument("--voice-key", help="Set Voice API key")
    p_cfg.add_argument("--voice-model", help="Set Voice model (e.g. whisper-large-v3-turbo)")
    p_cfg.add_argument("--tts-voice", help="Set Siri TTS voice (e.g. tara, samantha, daniel, karen, moira, rishi, aman)")
    p_cfg.add_argument("--tts-rate", type=int, help="Set Siri TTS speech rate in WPM (e.g. 190)")
    p_cfg.add_argument("--tts", choices=["true", "false", "on", "off"], help="Enable or disable Siri TTS output")
    p_cfg.add_argument("--voices", dest="list_voices", action="store_true", help="List available Siri & macOS TTS voices")
    p_cfg.add_argument("--preset", help="Quick switch preset (ollama, groq, openrouter, or siri voice name)")
    p_cfg.add_argument("-i", "--interactive", action="store_true", help="Launch interactive config wizard")

    cfg_sub = p_cfg.add_subparsers(dest="config_action", help="Config subaction")

    # config set <key> <value>
    p_set = cfg_sub.add_parser("set", help="Set a configuration key")
    p_set.add_argument("key_name", help="Key name (e.g. tts-voice, tts-rate, tts, llm-url, llm-model, voice-key)")
    p_set.add_argument("value", help="Value to set")

    # config get <key>
    p_get = cfg_sub.add_parser("get", help="Get a configuration key value")
    p_get.add_argument("key_name", help="Key name to inspect (e.g. tts-voice, tts-rate, tts)")

    # config preset <name>
    p_pre = cfg_sub.add_parser("preset", help="Apply preconfigured profile (ollama, groq, openrouter, or Siri voice)")
    p_pre.add_argument("preset_name", help="Preset name: ollama, groq, openrouter, tara, samantha, daniel, karen, moira, rishi")
    p_pre.add_argument("--key", help="Optional API key for this preset")

    # config voices
    p_voices = cfg_sub.add_parser("voices", help="List available Siri TTS presets and installed macOS voices")
    p_voices.add_argument("--test", dest="test_voice", help="Preview a specific voice aloud")

    # config wizard
    cfg_sub.add_parser("wizard", help="Interactive step-by-step configuration wizard")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "restart":
        cmd_restart(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "hud":
        cmd_hud(args)
    elif args.command == "tts":
        cmd_tts(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


