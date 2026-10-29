"""
Maxi Command Line Interface (CLI)
Entrypoint for `maxi start`, `maxi stop`, `maxi status`, `maxi hud`, `maxi run`.
"""

import sys
import os
import time
import tempfile
import argparse
import subprocess
import signal
from contextlib import contextmanager
from pathlib import Path
import httpx
from app import __version__

PID_FILE = Path.home() / ".maxi" / "daemon.pid"
PORT_FILE = Path.home() / ".maxi" / "daemon.port"


def get_configured_port() -> int:
    from app.config import settings
    return getattr(settings, "port", 4848) or 4848


def get_active_port() -> int:
    """Returns the port currently in use by the running daemon, else configured port."""
    if PORT_FILE.exists():
        try:
            p = int(PORT_FILE.read_text().strip())
            if 1 <= p <= 65535:
                return p
        except ValueError:
            pass
    return get_configured_port()


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks whether a TCP port is currently occupied by another process."""
    import socket
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "localhost") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind_host, port))
            return False
        except OSError:
            return True


def resolve_listen_port(desired_port: int, host: str = "127.0.0.1", max_fallback_attempts: int = 10) -> int:
    """
    Returns desired_port if free, or scans forward for the first free fallback port.
    """
    if not is_port_in_use(desired_port, host=host):
        return desired_port
    for offset in range(1, max_fallback_attempts + 1):
        candidate = desired_port + offset
        if not is_port_in_use(candidate, host=host):
            return candidate
    return desired_port


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


@contextmanager
def daemon_lock():
    """Hold a process lock for the backend lifetime, before writing its PID."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    with (PID_FILE.parent / "daemon.lock").open("a+b") as lock:
        try:
            if sys.platform == "win32":
                import msvcrt
                lock.write(b"\0")
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("A Maxi backend is already starting or running.")
        yield


def cmd_run(args):
    """Run daemon in foreground."""
    import uvicorn
    from app.config import settings

    with daemon_lock():
        PID_FILE.write_text(str(os.getpid()))
        desired_port = getattr(args, "port", None) or settings.port
        actual_port = resolve_listen_port(desired_port, host=settings.host)
        if actual_port != desired_port:
            print(f"⚠️  Port {desired_port} is in use by another process. Falling back to port {actual_port}.")
        PORT_FILE.write_text(str(actual_port))
        settings.port = actual_port
        os.environ["PORT"] = str(actual_port)
        os.environ["MAX_PORT"] = str(actual_port)
        try:
            uvicorn.run(
                "app.main:app",
                host=settings.host,
                port=actual_port,
                reload=(args.reload or settings.debug) and not os.environ.get("MAXI_DAEMON_REDIRECTED"),
                log_level="info",
                timeout_graceful_shutdown=2,
            )
        finally:
            if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
            if PORT_FILE.exists():
                PORT_FILE.unlink(missing_ok=True)


def get_python_exe() -> str:
    """Use the interpreter of this installed CLI, never another Maxi environment."""
    return sys.executable


def backend_health(port: int | None = None):
    from app.config import settings
    host = "127.0.0.1" if settings.host == "0.0.0.0" else settings.host

    ports_to_check = []
    if port is not None:
        ports_to_check.append(port)
    active_p = get_active_port()
    if active_p not in ports_to_check:
        ports_to_check.append(active_p)
    if settings.port not in ports_to_check:
        ports_to_check.append(settings.port)
    for offset in range(1, 10):
        p = settings.port + offset
        if p not in ports_to_check:
            ports_to_check.append(p)

    for check_p in ports_to_check:
        url = f"http://{host}:{check_p}"
        try:
            response = httpx.get(f"{url}/api/health", timeout=1, trust_env=False)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok" and data.get("service") == "Maxi Agent Daemon":
                data["active_port"] = check_p
                return data
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
    return None


def require_hud_endpoint():
    from app.config import settings
    if settings.port != 4848 or settings.host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        raise SystemExit("The native HUD requires the backend at 127.0.0.1:4848. Set HOST=127.0.0.1 and PORT=4848 in ~/.maxi/.env, then restart Maxi.")


def cmd_start(args):
    """Start the installed backend and return success only after HTTP readiness."""
    from app.config import settings

    if getattr(args, "restart", False):
        cmd_stop(args)
        time.sleep(0.5)

    if getattr(args, "for_hud", False):
        require_hud_endpoint()
    existing_pid = get_pid()
    health = backend_health()
    if health:
        active_port = health.get("active_port", get_active_port())
        print(f"⚡ Maxi backend is already healthy on port {active_port}.")
        return
    if existing_pid:
        raise SystemExit(f"Maxi PID {existing_pid} is alive but its API is unavailable. Check {PID_FILE.parent / 'daemon.log'}; run maxi restart if needed.")

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = PID_FILE.parent / "daemon.log"

    print("🚀 Starting Maxi background daemon...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True

    env = dict(os.environ)
    env["MAXI_DAEMON_REDIRECTED"] = "1"
    if sys.platform.startswith("linux"):
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "XAUTHORITY" not in env:
            import glob
            uid = os.getuid()
            auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth*") or glob.glob(f"/run/user/{uid}/.Xauthority*")
            if auths:
                env["XAUTHORITY"] = auths[0]
            elif (Path.home() / ".Xauthority").exists():
                env["XAUTHORITY"] = str(Path.home() / ".Xauthority")
        if "WAYLAND_DISPLAY" not in env and Path(f"/run/user/{os.getuid()}/wayland-0").exists():
            env["WAYLAND_DISPLAY"] = "wayland-0"

    py_exe = get_python_exe()
    with open(log_file, "a") as log_out:
        proc = subprocess.Popen(
            [py_exe, "-m", "app.cli", "run"],
            stdin=subprocess.DEVNULL,
            stdout=log_out,
            stderr=log_out,
            env=env,
            cwd=str(PID_FILE.parent),
            **kwargs
        )

    deadline = time.monotonic() + getattr(args, "timeout", 30)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        health = backend_health()
        if health and health.get("pid") == proc.pid:
            active_port = health.get("active_port", get_active_port())
            print(f"✅ Maxi backend is healthy (PID: {proc.pid}) on port {active_port}")
            print(f"📜 Logs: {log_file}")
            return
        time.sleep(0.25)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if PID_FILE.exists() and PID_FILE.read_text().strip() == str(proc.pid):
        PID_FILE.unlink(missing_ok=True)
    if PORT_FILE.exists():
        PORT_FILE.unlink(missing_ok=True)
    raise SystemExit(f"Maxi backend did not become healthy. Inspect logs at {log_file}")


def cmd_stop(args):
    """Stop running background daemon."""
    pid = get_pid()
    if not pid:
        # Also check if something is on port 4848
        print("ℹ️  No active Maxi daemon PID file found.")
        PORT_FILE.unlink(missing_ok=True)
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
        PORT_FILE.unlink(missing_ok=True)


def cmd_restart(args):
    """Restart background daemon."""
    cmd_stop(args)
    time.sleep(1.0)
    cmd_start(args)


def cmd_status(args):
    """Check status of Maxi daemon and active tools."""
    from app.ui.terminal import render_status_card
    health = backend_health()
    active_port = health.get("active_port") if health else get_active_port()
    print("\n" + render_status_card(health, port=active_port) + "\n")


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
    """Display all Kokoro Neural TTS and Siri TTS presets."""
    from app.core.config_manager import get_current_config
    from app.core.tts import (
        KOKORO_VOICE_PRESETS, KOKORO_VOICE_ALIASES,
        SIRI_VOICE_PRESETS, SIRI_VOICE_ALIASES,
        is_kokoro_voice, resolve_siri_voice, tts_service
    )

    cfg = get_current_config()
    active_raw = cfg.get("tts_voice", "af_heart")
    active_resolved = resolve_siri_voice(active_raw)
    tts_enabled = cfg.get("enable_tts", True)
    tts_rate = cfg.get("tts_rate", 190)
    tts_url = cfg.get("tts_base_url", "http://100.75.149.115:8880/v1")
    engine_label = f"Kokoro Neural TTS ({tts_url})" if is_kokoro_voice(active_resolved) else "macOS Native Siri TTS"

    print("\n🔊 Maxi Expressive TTS Voices (Kokoro Neural + Siri Fallback)")
    print("━" * 70)
    print(f"Active Engine: {engine_label}")
    print(f"Active Voice:  {active_resolved} (Configured: '{active_raw}', Rate: {tts_rate} WPM, {'Enabled' if tts_enabled else 'Disabled'})")
    print("")
    print("🎭 Recommended Kokoro Neural Voices (Linux HP Server):")
    for key, info in KOKORO_VOICE_PRESETS.items():
        marker = "✅ (Active)" if info["voice"].lower() == active_resolved.lower() else ""
        print(f"  • {key:<10} -> {info['name']:<34} [{info['locale']}] {marker}")

    print("\n✨ Expressive Voice Annotations (Supported in Kokoro & Voice Replies):")
    print("  • Appraisals:  \"Oh, I got it! [pause:0.15s]\" | \"Aha, right!\"")
    print("  • Reactions:   [laugh]  [chuckle]  [giggle]  [sigh]  [gasp]  [hmm]  [uhm]")
    print("  • Pacing/Beat: [pause]  [pause:0.3s]  [excited]  [thoughtful]  [slow]")
    print("  • Blending:    af_heart(2)+af_bella(1)  (alias: 'blend')")

    print("\n🍎 Apple Siri Fallback Presets:")
    for key, info in SIRI_VOICE_PRESETS.items():
        marker = "✅ (Active)" if info["voice"].lower() == active_resolved.lower() else ""
        print(f"  • {key:<10} -> {info['voice']:<10} [{info['locale']}]  {info['description']} {marker}")

    print("━" * 70)
    print("How to change or test TTS voice:")
    print("  • Use Kokoro Heart:   maxi tts set kokoro   (or: maxi tts set af_heart)")
    print("  • Use Kokoro Bella:   maxi tts set bella    (or: maxi tts set af_bella)")
    print("  • Use Apple Siri:     maxi tts set tara     (or: maxi tts set samantha)")
    print("  • Test expressive:    maxi tts test af_heart \"Oh, I got it! [laugh] That works great!\"")
    print("")

    if preview_voice:
        resolved = resolve_siri_voice(preview_voice)
        sample_text = f"Oh, I got it! [chuckle] I am Maxi, speaking with the {resolved} voice."
        print(f"🔊 Previewing '{resolved}' ({tts_rate} WPM): \"{sample_text}\"")
        tts_service.speak(sample_text, voice=resolved, rate=tts_rate, block=True)


def cmd_tts(args):
    """Manage and preview Kokoro & Siri TTS voices directly from the terminal."""
    from app.core.config_manager import save_config
    from app.core.tts import is_kokoro_voice, resolve_siri_voice, tts_service

    action = getattr(args, "tts_action", None) or "voices"
    if action == "voices":
        _print_available_voices(preview_voice=getattr(args, "test", None))
    elif action == "set":
        voice_val = getattr(args, "voice_name", None)
        if not voice_val:
            print("Usage: maxi tts set <voice_name>")
            return
        resolved = resolve_siri_voice(voice_val)
        provider = "kokoro" if is_kokoro_voice(resolved) else "siri"
        updates = {"TTS_VOICE": resolved, "TTS_PROVIDER": provider, "ENABLE_TTS": "true"}
        if getattr(args, "rate", None):
            updates["TTS_RATE"] = str(args.rate)
        _, msg = save_config(updates)
        print(f"✅ Switched TTS voice to: {resolved} ({provider.upper()})")
        print(f"📜 {msg}")
        if not getattr(args, "no_preview", False):
            sample = f"Oh, I got it! [chuckle] Hi, I'm Maxi using the {resolved} voice."
            tts_service.speak(sample, voice=resolved, block=True)
    elif action == "test":
        voice_val = getattr(args, "voice_name", None)
        resolved = resolve_siri_voice(voice_val)
        text = (
            getattr(args, "text", None)
            or f"Oh, I got it! [laugh] Hello, I am Maxi speaking with the {resolved} voice."
        )
        print(f"🔊 Testing TTS voice '{resolved}': \"{text}\"")
        tts_service.speak(text, voice=resolved, block=True)
    elif action == "on":
        _, msg = save_config({"ENABLE_TTS": "true"})
        print("✅ TTS enabled.")
        print(f"📜 {msg}")
    elif action == "off":
        _, msg = save_config({"ENABLE_TTS": "false"})
        print("🔇 TTS disabled.")
        print(f"📜 {msg}")
    else:
        _print_available_voices()


def cmd_config(args):
    """View and update Maxi LLM, Voice, and System configurations."""
    from app.core.config_manager import (
        get_current_config, save_config, PRESETS, VOICE_PRESETS,
        KEY_ALIASES, mask_secret
    )
    from app.core.tts import (
        KOKORO_VOICE_PRESETS, KOKORO_VOICE_ALIASES,
        SIRI_VOICE_PRESETS, SIRI_VOICE_ALIASES,
        is_kokoro_voice, resolve_siri_voice
    )

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
        elif (
            preset_name in SIRI_VOICE_PRESETS
            or preset_name in SIRI_VOICE_ALIASES
            or preset_name in KOKORO_VOICE_PRESETS
            or preset_name in KOKORO_VOICE_ALIASES
        ):
            resolved = resolve_siri_voice(preset_name)
            p_info = KOKORO_VOICE_PRESETS.get(
                resolved.lower(),
                SIRI_VOICE_PRESETS.get(resolved.lower(), {"name": resolved, "locale": "en"}),
            )
            provider = "kokoro" if is_kokoro_voice(resolved) else "siri"
            updates = {
                "TTS_VOICE": resolved,
                "TTS_PROVIDER": provider,
                "ENABLE_TTS": "true",
            }
            _, msg = save_config(updates)
            print(f"✅ Switched TTS voice preset to {p_info.get('name', resolved)}:")
            print(f"   Voice:  {resolved} ({p_info.get('locale', 'en')})")
            print(f"📜 {msg}")
            return
        else:
            print(f"❌ Unknown preset '{preset_name}'.")
            print(f"   Available LLM presets:      {', '.join(PRESETS.keys())}")
            print(f"   Available Voice presets:    {', '.join(VOICE_PRESETS.keys())}")
            print(f"   Available Kokoro voices:    {', '.join(KOKORO_VOICE_PRESETS.keys())}")
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
            "ENABLE_TTS": cfg.get("enable_tts", True),
            "TTS_PROVIDER": cfg.get("tts_provider", "kokoro"),
            "TTS_BASE_URL": cfg.get("tts_base_url", "http://100.75.149.115:8880/v1"),
            "TTS_VOICE": cfg.get("tts_voice", "af_heart"),
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
            print("  maxi config set tts-voice af_heart")
            print("  maxi config set tts-voice samantha")
            print("  maxi config set tts-rate 190")
            print("  maxi config set tts true")
            print("  maxi config set llm-url http://localhost:11434/v1")
            print("  maxi config set llm-model llama3.2")
            print("  maxi config set voice-key gsk_...")
            return
        canonical = KEY_ALIASES.get(k.lower(), k)
        updates = {canonical: v}
        if canonical == "TTS_VOICE":
            v = resolve_siri_voice(v)
            updates[canonical] = v
            updates["TTS_PROVIDER"] = "kokoro" if is_kokoro_voice(v) else "siri"
        _, msg = save_config(updates)
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
        resolved_v = resolve_siri_voice(args.tts_voice)
        flag_updates["TTS_VOICE"] = resolved_v
        flag_updates["TTS_PROVIDER"] = "kokoro" if is_kokoro_voice(resolved_v) else "siri"
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

    tts_voice_raw = cfg.get("tts_voice", "af_heart")
    tts_voice_resolved = resolve_siri_voice(tts_voice_raw)
    use_kokoro = is_kokoro_voice(tts_voice_resolved)
    tts_preset_meta = (
        KOKORO_VOICE_PRESETS.get(tts_voice_resolved.lower(), {})
        if use_kokoro
        else SIRI_VOICE_PRESETS.get(tts_voice_resolved.lower(), {})
    )
    tts_voice_label = tts_preset_meta.get(
        "name",
        f"{tts_voice_resolved} ({'Kokoro Neural' if use_kokoro else 'macOS Siri'})",
    )

    from app.ui.terminal import render_config_card
    print("\n" + render_config_card(cfg) + "\n")


def cmd_glossary(args):
    """Manage Willow-style custom vocabulary terms and spoken replacements."""
    from app.core.glossary import glossary_manager

    action = getattr(args, "glossary_action", None) or "list"
    if action == "add":
        term = getattr(args, "term", None)
        replacement = getattr(args, "replacement", None)
        if not term:
            print("Usage: maxi glossary add <term> [replacement]")
            return
        if replacement:
            glossary_manager.add_replacement(term, replacement)
            print(f"✅ Added glossary replacement: '{term}' -> '{replacement}'")
        else:
            glossary_manager.add_term(term)
            print(f"✅ Added vocabulary term: '{term}'")
    elif action == "remove":
        term = getattr(args, "term", None)
        if not term:
            print("Usage: maxi glossary remove <term>")
            return
        r1 = glossary_manager.remove_term(term)
        r2 = glossary_manager.remove_replacement(term)
        if r1 or r2:
            print(f"🗑️  Removed '{term}' from glossary.")
        else:
            print(f"ℹ️  '{term}' was not found in glossary.")
    else:
        data = glossary_manager.list_all()
        terms = data.get("terms", [])
        replacements = data.get("replacements", {})
        print("\n📖 Maxi Custom Vocabulary & Glossary (~/.maxi/glossary.json)")
        print("━" * 60)
        print(f"Vocabulary Terms ({len(terms)}):")
        if terms:
            print("  " + ", ".join(terms))
        else:
            print("  (none)")
        print(f"\nSpoken -> Written Replacements ({len(replacements)}):")
        if replacements:
            for k, v in replacements.items():
                print(f"  • \"{k}\" -> \"{v}\"")
        else:
            print("  (none)")
        print("━" * 60)
        print("Usage:")
        print("  • Add domain term:       maxi glossary add \"LangGraph\"")
        print("  • Add auto-replacement:  maxi glossary add \"my github\" \"https://github.com/krishnakanth\"")
        print("  • Remove entry:          maxi glossary remove \"LangGraph\"")
        print("")


VOICE_CLI_LOCK = Path(tempfile.gettempdir()) / "maxi_voice_cli.lock"


def cmd_voice(args):
    """Trigger or toggle voice input recording on the active Maxi daemon with key-repeat suppression."""
    now = time.time()
    if VOICE_CLI_LOCK.exists():
        try:
            last_ts = float(VOICE_CLI_LOCK.read_text().strip())
            if now - last_ts < 0.75:
                return  # Silently suppress rapid key-repeat spawns from GNOME
        except Exception:
            pass
    try:
        VOICE_CLI_LOCK.write_text(str(now))
    except Exception:
        pass

    health = backend_health()
    if not health:
        raise SystemExit("Maxi daemon is not running. Start it with: maxi start")
    active_port = health.get("active_port", get_active_port())
    action = getattr(args, "voice_action", "toggle") or "toggle"
    url = f"http://127.0.0.1:{active_port}/api/voice/{action}"
    try:
        resp = httpx.post(url, timeout=5.0)
        data = resp.json()
        status = data.get("status", "ok")
        print(f"🎙️ Maxi Voice [{action}]: {status}")
    except Exception as e:
        raise SystemExit(f"Could not contact Maxi daemon on port {active_port}: {e}")


HUD_PID_FILE = Path.home() / ".maxi" / "hud.pid"


def cmd_hud(args):
    """Build and launch the native macOS Willow-style Floating Pill HUD."""
    if sys.platform != "darwin":
        print("⚠️  The native Cocoa Floating HUD is only supported on macOS.")
        return

    action = getattr(args, "hud_action", None) or "start"
    if action == "stop":
        if HUD_PID_FILE.exists():
            try:
                pid = int(HUD_PID_FILE.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                print(f"🛑 Stopped Maxi HUD (PID: {pid}).")
            except (ValueError, OSError):
                print("ℹ️  HUD process was not running.")
            finally:
                HUD_PID_FILE.unlink(missing_ok=True)
        else:
            subprocess.run(["pkill", "-f", "MaxiHUD"], check=False)
            print("🛑 Stopped Maxi HUD.")
        return

    if action != "build":
        require_hud_endpoint()

    # The wheel is backend-only. Prefer the separately installed native app.
    if action != "build" and not getattr(args, "rebuild", False):
        for app_dir in (Path.home() / "Applications/Maxi.app", Path("/Applications/Maxi.app")):
            if app_dir.is_dir():
                cmd_start(args)
                subprocess.run(["open", str(app_dir)], check=True)
                return

    macos_dir = Path(__file__).resolve().parent.parent / "frontends" / "macos"
    if not macos_dir.exists():
        raise SystemExit("Install the separate Maxi.app with scripts/install_macos.sh. Building the HUD requires a source checkout.")

    release_bin = macos_dir / ".build" / "release" / "MaxiHUD"
    debug_bin = macos_dir / ".build" / "debug" / "MaxiHUD"

    binary = release_bin if release_bin.exists() else (debug_bin if debug_bin.exists() else None)
    if action == "build" or binary is None or getattr(args, "rebuild", False):
        print("🔨 Building native macOS MaxiHUD (SwiftUI + AppKit NSPanel)...")
        res = subprocess.run(["swift", "build", "-c", "release"], cwd=str(macos_dir))
        if res.returncode != 0:
            print("❌ Failed to build MaxiHUD.")
            return
        binary = release_bin
        print(f"✅ Built MaxiHUD binary: {binary}")
        if action == "build":
            return

    cmd_start(args)
    hud_env = dict(os.environ, MAXI_BACKEND_PYTHON=get_python_exe())

    # Stop existing HUD if running
    if HUD_PID_FILE.exists():
        try:
            old_pid = int(HUD_PID_FILE.read_text().strip())
            os.kill(old_pid, signal.SIGTERM)
        except Exception:
            pass
        HUD_PID_FILE.unlink(missing_ok=True)

    if getattr(args, "foreground", False) or action == "run":
        print("✨ Running MaxiHUD in foreground (Ctrl+C to close)...")
        HUD_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        HUD_PID_FILE.write_text(str(os.getpid()))
        try:
            subprocess.run([str(binary)], env=hud_env)
        except KeyboardInterrupt:
            pass
        finally:
            HUD_PID_FILE.unlink(missing_ok=True)
    else:
        HUD_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        hud_log = HUD_PID_FILE.parent / "hud.log"
        with open(hud_log, "a") as out:
            proc = subprocess.Popen(
                [str(binary)],
                stdout=out,
                stderr=out,
                start_new_session=True,
                env=hud_env,
            )
        HUD_PID_FILE.write_text(str(proc.pid))
        print(f"✨ Maxi Floating HUD launched (PID: {proc.pid})")
        print("   • Hold Right Option (⌥) to speak, or double-tap Right Option for hands-free lock")
        print("   • Press Esc while recording to cancel")


def main():
    parser = argparse.ArgumentParser(
        prog="maxi",
        description="⚡ Maxi - Pluggable, ultra-fast background AI agent daemon"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # run
    p_run = subparsers.add_parser("run", help="Run daemon in foreground")
    p_run.add_argument("--reload", action="store_true", help="Enable live code reload")

    # start
    p_start = subparsers.add_parser("start", help="Start daemon and wait for a healthy API")
    p_start.add_argument("--timeout", type=float, default=30, help="Startup deadline in seconds (default: 30)")
    p_start.add_argument("--for-hud", action="store_true", help="Require the local endpoint used by the native HUD")
    p_start.add_argument("--restart", action="store_true", help="Restart background daemon if already running")

    # stop
    subparsers.add_parser("stop", help="Stop background daemon")

    # restart
    subparsers.add_parser("restart", help="Restart background daemon")

    # status
    subparsers.add_parser("status", help="Check daemon and MCP health")

    # hud
    p_hud = subparsers.add_parser("hud", help="Launch or manage the native macOS Willow-style Floating HUD")
    p_hud.add_argument("hud_action", nargs="?", choices=["start", "stop", "run", "build"], default="start", help="HUD action")
    p_hud.add_argument("--foreground", "-f", action="store_true", help="Run HUD in foreground")
    p_hud.add_argument("--rebuild", action="store_true", help="Force rebuild Swift binary before launching")

    # chat
    subparsers.add_parser("chat", help="Start interactive terminal chat session with Maxi")

    # ask
    p_ask = subparsers.add_parser("ask", help="Send a prompt to Maxi and stream the response in terminal")
    p_ask.add_argument("query", nargs="+", help="Query or prompt for Maxi")

    # glossary
    p_gloss = subparsers.add_parser("glossary", help="Manage custom STT vocabulary terms and spoken replacements")
    gloss_sub = p_gloss.add_subparsers(dest="glossary_action", help="Glossary action")
    gloss_sub.add_parser("list", help="List all glossary terms and replacements")
    p_gloss_add = gloss_sub.add_parser("add", help="Add a vocabulary term or spoken->written replacement")
    p_gloss_add.add_argument("term", help="Term or spoken phrase")
    p_gloss_add.add_argument("replacement", nargs="?", default=None, help="Optional replacement string")
    p_gloss_rem = gloss_sub.add_parser("remove", help="Remove a term or replacement")
    p_gloss_rem.add_argument("term", help="Term to remove")

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

    # voice
    p_voice = subparsers.add_parser("voice", help="Trigger or toggle voice input recording")
    p_voice.add_argument("voice_action", nargs="?", choices=["toggle", "start", "stop"], default="toggle", help="Voice action (default: toggle)")

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
    elif args.command == "chat":
        from app.ui.terminal import run_interactive_chat
        run_interactive_chat()
    elif args.command == "ask":
        import asyncio
        from app.ui.terminal import stream_agent_response
        asyncio.run(stream_agent_response(" ".join(args.query)))
    elif args.command == "glossary":
        cmd_glossary(args)
    elif args.command == "tts":
        cmd_tts(args)
    elif args.command == "voice":
        cmd_voice(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
