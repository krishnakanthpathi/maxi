"""
Maxi Terminal UI & Aesthetic Styling Engine
Self-contained, dependency-free ANSI styling for cards, dashboards, banners,
markdown rendering, and interactive streaming chat.
"""

import os
import sys
import re
import json
import shutil
import time
from typing import List, Dict, Any, Optional

# =============================================================================
# ANSI Styling & Color Engine
# =============================================================================

def supports_color() -> bool:
    """Returns True if the current stdout environment supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "")
    return term != "dumb"


COLOR_ENABLED = supports_color()

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Strips ANSI escape codes from text to compute exact visible length."""
    return _ANSI_RE.sub("", text)


def visible_len(text: str) -> int:
    """Returns display width of text, ignoring ANSI escape sequences and accounting for emojis."""
    clean = strip_ansi(text)
    # Quick width approximation: most emojis occupy 2 visual columns
    width = len(clean)
    for ch in clean:
        code = ord(ch)
        # Miscellaneous symbols, emoticons, dingbats
        if 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
            width += 1
    return width


def color(text: str, code: str) -> str:
    if not COLOR_ENABLED or not code:
        return text
    return f"{code}{text}\033[0m"


class Palette:
    RESET = "\033[0m" if COLOR_ENABLED else ""
    BOLD = "\033[1m" if COLOR_ENABLED else ""
    DIM = "\033[2m" if COLOR_ENABLED else ""
    ITALIC = "\033[3m" if COLOR_ENABLED else ""
    UNDERLINE = "\033[4m" if COLOR_ENABLED else ""

    # Modern 24-bit Truecolor & high-contrast ANSI colors
    BRAND = "\033[38;2;167;139;250m" if COLOR_ENABLED else ""       # Soft Violet #A78BFA
    BRAND_DEEP = "\033[38;2;139;92;246m" if COLOR_ENABLED else ""   # Deep Purple #8B5CF6
    CYAN = "\033[38;2;34;211;238m" if COLOR_ENABLED else ""         # Bright Cyan #22D3EE
    TEAL = "\033[38;2;45;212;191m" if COLOR_ENABLED else ""         # Mint Teal #2DD4BF
    EMERALD = "\033[38;2;52;211;153m" if COLOR_ENABLED else ""      # Emerald Green #34D399
    AMBER = "\033[38;2;251;191;36m" if COLOR_ENABLED else ""        # Amber #FBBF24
    ROSE = "\033[38;2;251;113;133m" if COLOR_ENABLED else ""        # Rose Red #FB7185
    BLUE = "\033[38;2;96;165;250m" if COLOR_ENABLED else ""         # Sky Blue #60A5FA
    TEXT = "\033[38;2;248;250;252m" if COLOR_ENABLED else ""        # Pure White #F8FAFC
    SLATE = "\033[38;2;148;163;184m" if COLOR_ENABLED else ""       # Slate Gray #94A3B8
    DARK = "\033[38;2;71;85;105m" if COLOR_ENABLED else ""          # Dark Slate #475569
    BG_DARK = "\033[48;2;30;41;59m" if COLOR_ENABLED else ""        # Dark Background Pill


def colorize(text: str, style_name: str) -> str:
    style = getattr(Palette, style_name.upper(), "")
    return f"{style}{text}{Palette.RESET}" if style else text


# =============================================================================
# Badges & Visual Components
# =============================================================================

def badge(text: str, kind: str = "active") -> str:
    """Returns a styled inline pill badge."""
    if not COLOR_ENABLED:
        return f"[{text}]"
    if kind == "active" or kind == "online" or kind == "success":
        return f"{Palette.EMERALD}{Palette.BOLD}● {text}{Palette.RESET}"
    if kind == "stopped" or kind == "offline":
        return f"{Palette.DARK}○ {text}{Palette.RESET}"
    if kind == "warn" or kind == "warning":
        return f"{Palette.AMBER}{Palette.BOLD}▲ {text}{Palette.RESET}"
    if kind == "error" or kind == "failed":
        return f"{Palette.ROSE}{Palette.BOLD}✖ {text}{Palette.RESET}"
    if kind == "brand":
        return f"{Palette.BRAND}{Palette.BOLD}⚡ {text}{Palette.RESET}"
    return f"{Palette.CYAN}[{text}]{Palette.RESET}"


def box_card(
    title: str,
    lines: List[str],
    width: Optional[int] = None,
    border_color: str = Palette.BRAND,
    title_color: str = Palette.TEXT,
) -> str:
    """Renders a modern rounded-corner box container."""
    term_width = shutil.get_terminal_size((80, 24)).columns
    card_width = width or min(max(term_width - 4, 50), 76)
    content_w = card_width - 4

    # Top border
    title_display = f" {title} " if title else ""
    t_len = visible_len(title_display)
    right_dash_count = max(0, card_width - 2 - t_len)
    top = f"{border_color}╭─{Palette.RESET}{title_color}{Palette.BOLD}{title_display}{Palette.RESET}{border_color}{'─' * max(0, right_dash_count - 1)}╮{Palette.RESET}"

    # Body lines
    body = []
    for raw_line in lines:
        v_len = visible_len(raw_line)
        if v_len > content_w:
            # truncate line gracefully while preserving ANSI reset
            clean = strip_ansi(raw_line)
            overflow = v_len - content_w
            truncated = clean[:len(clean) - overflow - 3] + "..."
            raw_line = truncated
            v_len = visible_len(raw_line)
        pad = max(0, content_w - v_len)
        body.append(f"{border_color}│{Palette.RESET} {raw_line}{' ' * pad} {border_color}│{Palette.RESET}")

    # Bottom border
    bottom = f"{border_color}╰{'─' * (card_width - 2)}╯{Palette.RESET}"

    return "\n".join([top] + body + [bottom])


def render_banner(version: str = "0.3.0b1") -> str:
    """Renders the flagship Maxi header banner."""
    lines = [
        f"{Palette.BRAND}{Palette.BOLD}∑  M A X I{Palette.RESET}  {Palette.SLATE}·{Palette.RESET}  {Palette.CYAN}Workstation AI Agent Companion{Palette.RESET}  {Palette.DARK}v{version}{Palette.RESET}",
        f"{Palette.SLATE}Voice-first desktop automation · MCP tools · Long-term memory{Palette.RESET}",
    ]
    return box_card(title="AI Agent Daemon", lines=lines, border_color=Palette.BRAND_DEEP)


# =============================================================================
# Dashboard Views
# =============================================================================

def render_status_card(health_data: Optional[Dict[str, Any]] = None, port: Optional[int] = None) -> str:
    """Renders a comprehensive, high-aesthetic terminal status dashboard."""
    import httpx
    from app import __version__
    from app.config import settings
    from app.cli import get_pid

    is_running = health_data is not None
    pid = get_pid()
    active_port = port or (health_data.get("active_port") if health_data else None) or settings.port
    mcp_count = 0
    tools_list = []
    sounds_info = {}
    config_info = {}

    if is_running:
        base_url = f"http://127.0.0.1:{active_port}"
        try:
            r = httpx.get(f"{base_url}/api/mcp/tools", timeout=1.5)
            if r.status_code == 200:
                tdata = r.json()
                mcp_count = tdata.get("count", 0)
                tools_list = [t.get("name", "") for t in tdata.get("tools", [])[:8]]
        except Exception:
            pass

        try:
            r = httpx.get(f"{base_url}/api/sounds", timeout=1.5)
            if r.status_code == 200:
                sounds_info = r.json().get("active", {})
        except Exception:
            pass

        try:
            r = httpx.get(f"{base_url}/api/config", timeout=1.5)
            if r.status_code == 200:
                config_info = r.json().get("config", {})
        except Exception:
            pass

    # Determine Accessibility Status on macOS
    access_status = "Granted"
    if sys.platform == "darwin":
        try:
            import ApplicationServices
            if not ApplicationServices.AXIsProcessTrusted():
                access_status = "Missing (Enable in System Settings)"
        except Exception:
            access_status = "Unknown"

    from app.core.config_manager import get_active_env_file
    env_file_path = str(get_active_env_file())

    # Status Pill
    if is_running:
        daemon_status = f"{badge('ONLINE', 'active')}  {Palette.SLATE}(PID: {pid or health_data.get('pid', 'External')}){Palette.RESET}"
    else:
        daemon_status = f"{badge('STOPPED', 'stopped')}  {Palette.DARK}(Run 'maxi start' to launch){Palette.RESET}"

    # LLM & Voice
    llm_model = config_info.get("llm_model") or settings.openai_model
    llm_url = config_info.get("llm_url") or settings.openai_base_url
    tts_voice = config_info.get("tts_voice") or settings.tts_voice
    tts_provider = config_info.get("tts_provider") or getattr(settings, "tts_provider", "ollama")
    hotkey = (config_info.get("voice_hotkey") or getattr(settings, "voice_hotkey", "Right Option (⌥)")).capitalize()

    lines = [
        f"{Palette.BOLD}Daemon State:{Palette.RESET}       {daemon_status}",
        f"{Palette.BOLD}HTTP API:{Palette.RESET}           {Palette.CYAN}http://{settings.host}:{active_port}{Palette.RESET} {Palette.DARK}· WebSocket /ws{Palette.RESET}",
        f"{Palette.BOLD}Config File:{Palette.RESET}        {Palette.DARK}{env_file_path}{Palette.RESET}",
        "",
        f"{Palette.BRAND}{Palette.BOLD}── Intelligence & Speech ─────────────────────────────{Palette.RESET}",
        f"{Palette.BOLD}LLM Model:{Palette.RESET}          {Palette.EMERALD}{llm_model}{Palette.RESET} {Palette.DARK}({llm_url}){Palette.RESET}",
        f"{Palette.BOLD}Voice STT:{Palette.RESET}          {Palette.TEXT}{settings.voice_model}{Palette.RESET} {Palette.DARK}(Groq Whisper LPUs){Palette.RESET}",
        f"{Palette.BOLD}TTS Speech:{Palette.RESET}         {Palette.AMBER}{tts_provider.capitalize()} Phonon ({tts_voice}){Palette.RESET} {Palette.DARK}@{settings.tts_rate}wpm{Palette.RESET}",
        f"{Palette.BOLD}Push-to-Talk:{Palette.RESET}       {Palette.TEXT}{hotkey}{Palette.RESET} {Palette.DARK}({access_status}){Palette.RESET}",
        "",
        f"{Palette.BRAND}{Palette.BOLD}── Workstation & MCP Tools ───────────────────────────{Palette.RESET}",
        f"{Palette.BOLD}Loaded Tools:{Palette.RESET}       {Palette.TEAL}{mcp_count} MCP tools active{Palette.RESET}",
    ]

    if tools_list:
        preview = ", ".join(tools_list[:5])
        if len(tools_list) > 5:
            preview += f" +{mcp_count - 5} more"
        lines.append(f"{Palette.BOLD}Sample Tools:{Palette.RESET}       {Palette.DARK}{preview}{Palette.RESET}")

    theme_start = sounds_info.get("start_sound", settings.voice_start_sound)
    theme_end = sounds_info.get("finish_sound", settings.voice_finish_sound)
    lines.extend([
        f"{Palette.BOLD}Audio Theme:{Palette.RESET}        {Palette.SLATE}{theme_start}{Palette.RESET} {Palette.DARK}→{Palette.RESET} {Palette.SLATE}{theme_end}{Palette.RESET}",
        "",
        f"{Palette.DARK}Quick commands: 'maxi chat' · 'maxi hud' · 'maxi restart' · 'maxi tts'{Palette.RESET}",
    ])

    title = f"∑ Maxi Daemon Status · v{__version__}"
    return box_card(title=title, lines=lines, border_color=Palette.BRAND)


def render_config_card(cfg: Dict[str, Any]) -> str:
    """Renders a styled configuration summary card."""
    lines = [
        f"{Palette.BRAND}{Palette.BOLD}🧠 LLM Model Provider{Palette.RESET}",
        f"  {Palette.BOLD}Preset:{Palette.RESET}       {Palette.CYAN}{cfg.get('llm_preset', 'custom').capitalize()}{Palette.RESET}",
        f"  {Palette.BOLD}Model:{Palette.RESET}        {Palette.EMERALD}{cfg.get('llm_model')}{Palette.RESET}",
        f"  {Palette.BOLD}Endpoint:{Palette.RESET}     {Palette.SLATE}{cfg.get('llm_url')}{Palette.RESET}",
        f"  {Palette.BOLD}API Key:{Palette.RESET}      {Palette.DARK}{cfg.get('llm_key_masked')}{Palette.RESET}",
        "",
        f"{Palette.BRAND}{Palette.BOLD}🎙️ Voice Transcription (STT){Palette.RESET}",
        f"  {Palette.BOLD}Model:{Palette.RESET}        {Palette.TEXT}{cfg.get('voice_model')}{Palette.RESET}",
        f"  {Palette.BOLD}Endpoint:{Palette.RESET}     {Palette.SLATE}{cfg.get('voice_url')}{Palette.RESET}",
        f"  {Palette.BOLD}Hotkey:{Palette.RESET}       {Palette.TEXT}{cfg.get('voice_hotkey', 'auto')}{Palette.RESET}",
        "",
        f"{Palette.BRAND}{Palette.BOLD}🔊 Text-to-Speech (TTS){Palette.RESET}",
        f"  {Palette.BOLD}Provider:{Palette.RESET}     {Palette.AMBER}{cfg.get('tts_provider', 'ollama').capitalize()}{Palette.RESET}",
        f"  {Palette.BOLD}Voice:{Palette.RESET}        {Palette.TEXT}{cfg.get('tts_voice')}{Palette.RESET} {Palette.DARK}@{cfg.get('tts_rate', 190)} WPM{Palette.RESET}",
        f"  {Palette.BOLD}Enabled:{Palette.RESET}      {badge('YES', 'active') if cfg.get('enable_tts') else badge('NO', 'stopped')}",
        "",
        f"{Palette.DARK}Edit ~/.maxi/.env or run 'maxi config wizard' to reconfigure.{Palette.RESET}",
    ]
    return box_card(title="Maxi Settings Configuration", lines=lines, border_color=Palette.BRAND_DEEP)


# =============================================================================
# Markdown Rendering for Terminal
# =============================================================================

def render_markdown(text: str) -> str:
    """
    Renders common Markdown tags (headings, bold, italic, code blocks, lists)
    into high-contrast styled terminal output.
    """
    if not text:
        return ""
    if not COLOR_ENABLED:
        return text

    lines = []
    in_code_block = False
    code_lang = ""

    for line in text.splitlines():
        # Code block toggle
        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.lstrip("`").strip()
                header = f" {code_lang} " if code_lang else " Code "
                lines.append(f"{Palette.DARK}╭──{Palette.RESET}{Palette.AMBER}{Palette.BOLD}{header}{Palette.RESET}{Palette.DARK}{'─' * 40}╮{Palette.RESET}")
            else:
                in_code_block = False
                lines.append(f"{Palette.DARK}╰{'─' * 48}╯{Palette.RESET}")
            continue

        if in_code_block:
            lines.append(f"{Palette.DARK}│{Palette.RESET}  {Palette.TEAL}{line}{Palette.RESET}")
            continue

        # Headings
        if line.startswith("### "):
            lines.append(f"\n{Palette.CYAN}{Palette.BOLD}{line[4:]}{Palette.RESET}")
            continue
        elif line.startswith("## "):
            lines.append(f"\n{Palette.BRAND}{Palette.BOLD}{line[3:]}{Palette.RESET}")
            continue
        elif line.startswith("# "):
            lines.append(f"\n{Palette.BRAND_DEEP}{Palette.BOLD}# {line[2:]}{Palette.RESET}")
            continue

        # Bullet lists
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            prefix_spaces = len(line) - len(line.lstrip())
            content = line.strip()[2:]
            styled_content = _style_inline(content)
            lines.append(f"{' ' * prefix_spaces}{Palette.CYAN}•{Palette.RESET} {styled_content}")
            continue

        # Blockquote
        if line.startswith("> "):
            lines.append(f"{Palette.SLATE}│ {Palette.ITALIC}{_style_inline(line[2:])}{Palette.RESET}")
            continue

        # Normal paragraph with inline formatting
        lines.append(_style_inline(line))

    return "\n".join(lines)


def _style_inline(text: str) -> str:
    """Applies inline formatting for bold, italic, and inline code."""
    # Inline code `code`
    text = re.sub(r"`([^`]+)`", rf"{Palette.AMBER}`\1`{Palette.RESET}", text)
    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", rf"{Palette.BOLD}{Palette.TEXT}\1{Palette.RESET}", text)
    # Italic *text*
    text = re.sub(r"\*([^*]+)\*", rf"{Palette.ITALIC}\1{Palette.RESET}", text)
    return text


# =============================================================================
# Interactive Streaming Chat REPL
# =============================================================================

async def stream_agent_response(prompt: str, base_url: Optional[str] = None):
    """
    Connects to the daemon's WebSocket endpoint to stream the agent response
    token by token with live tool cards in the terminal.
    """
    import websockets
    if not base_url:
        from app.cli import get_active_port
        base_url = f"http://127.0.0.1:{get_active_port()}"

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

    print(f"\n{Palette.BRAND}{Palette.BOLD}╭─ Maxi Agent ────────────────────────────────────────{Palette.RESET}")
    print(f"{Palette.BRAND}│{Palette.RESET} {Palette.SLATE}Prompt:{Palette.RESET} {Palette.TEXT}{prompt}{Palette.RESET}")
    print(f"{Palette.BRAND}├{'─' * 52}{Palette.RESET}")

    try:
        async with websockets.connect(ws_url, close_timeout=2.0) as ws:
            # Send prompt
            payload = json.dumps({"text": prompt, "source": "cli:chat"})
            await ws.send(payload)

            first_chunk = True
            output_buffer = []

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    event = msg.get("event")

                    if event == "tool_start":
                        tool_name = msg.get("tool", "tool")
                        args = msg.get("args", {})
                        args_str = json.dumps(args, ensure_ascii=False)
                        if len(args_str) > 60:
                            args_str = args_str[:57] + "..."
                        print(f"{Palette.BRAND}│{Palette.RESET}  {Palette.AMBER}⚙ [Tool]{Palette.RESET} {Palette.BOLD}{tool_name}{Palette.RESET} {Palette.DARK}{args_str}{Palette.RESET}")

                    elif event == "tool_end":
                        tool_name = msg.get("tool", "tool")
                        print(f"{Palette.BRAND}│{Palette.RESET}  {Palette.EMERALD}✓ [Done]{Palette.RESET} {Palette.SLATE}{tool_name}{Palette.RESET}")

                    elif event == "chunk":
                        chunk = msg.get("data", "")
                        if first_chunk:
                            print(f"{Palette.BRAND}│{Palette.RESET}")
                            sys.stdout.write(f"{Palette.BRAND}│{Palette.RESET}  ")
                            first_chunk = False
                        # Print chunk live
                        chunk_clean = chunk.replace("\n", f"\n{Palette.BRAND}│{Palette.RESET}  ")
                        sys.stdout.write(f"{Palette.TEXT}{chunk_clean}{Palette.RESET}")
                        sys.stdout.flush()
                        output_buffer.append(chunk)

                    elif event == "done":
                        break

                    elif "error" in msg:
                        print(f"\n{Palette.ROSE}✖ Error: {msg['error']}{Palette.RESET}")
                        break

                except json.JSONDecodeError:
                    pass

            print(f"\n{Palette.BRAND}╰{'─' * 52}╯{Palette.RESET}\n")

    except Exception as e:
        # Fallback to HTTP POST if WebSocket connection fails
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{base_url}/api/prompt", json={"text": prompt, "source": "cli:chat"})
                if r.status_code == 200:
                    data = r.json()
                    out = data.get("output", "")
                    tools = data.get("tools_used", [])
                    if tools:
                        print(f"{Palette.BRAND}│{Palette.RESET}  {Palette.EMERALD}🛠️ Tools used:{Palette.RESET} {', '.join(tools)}")
                        print(f"{Palette.BRAND}│{Palette.RESET}")
                    rendered = render_markdown(out)
                    for l in rendered.splitlines():
                        print(f"{Palette.BRAND}│{Palette.RESET}  {l}")
                    print(f"{Palette.BRAND}╰{'─' * 52}╯{Palette.RESET}\n")
                else:
                    print(f"{Palette.ROSE}✖ Daemon returned error {r.status_code}: {r.text}{Palette.RESET}")
        except Exception as ex:
            print(f"{Palette.ROSE}✖ Could not reach Maxi Daemon on {base_url}: {ex}{Palette.RESET}")


def run_interactive_chat(base_url: Optional[str] = None):
    """Launches an interactive terminal chat session with Maxi."""
    import asyncio
    from app import __version__

    if not base_url:
        from app.cli import get_active_port
        base_url = f"http://127.0.0.1:{get_active_port()}"

    print(render_banner(__version__))
    print(f"\n{Palette.BOLD}Interactive Terminal Chat{Palette.RESET} {Palette.DARK}(Type 'exit' or press Ctrl+C to quit){Palette.RESET}\n")

    while True:
        try:
            prompt = input(f"{Palette.BRAND}{Palette.BOLD}You ➔ {Palette.RESET}").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "q", ":q"):
                print(f"{Palette.SLATE}Goodbye!{Palette.RESET}")
                break
            asyncio.run(stream_agent_response(prompt, base_url=base_url))
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Palette.SLATE}Session ended.{Palette.RESET}")
            break
