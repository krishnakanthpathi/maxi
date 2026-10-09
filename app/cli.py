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


def cmd_start(args):
    """Start daemon in background process."""
    existing_pid = get_pid()
    if existing_pid:
        print(f"⚡ Maxi daemon is already running (PID: {existing_pid}).")
        return

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = PID_FILE.parent / "daemon.log"

    print("🚀 Starting Maxi background daemon...")
    with open(log_file, "a") as log_out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.cli", "run"],
            stdout=log_out,
            stderr=log_out,
            start_new_session=True
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
            os.kill(pid, signal.SIGKILL)
        print("✅ Daemon stopped.")
    except ProcessLookupError:
        print("ℹ️  Process already terminated.")
    finally:
        PID_FILE.unlink(missing_ok=True)


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

    # status
    subparsers.add_parser("status", help="Check daemon and MCP health")

    # hud
    subparsers.add_parser("hud", help="Open Maxi HUD in browser")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "hud":
        cmd_hud(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
