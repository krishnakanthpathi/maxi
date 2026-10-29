import pytest
from app.ui.terminal import (
    strip_ansi,
    visible_len,
    badge,
    box_card,
    render_banner,
    render_status_card,
    render_config_card,
    render_markdown,
)


def test_strip_ansi_and_visible_len():
    colored = "\033[38;2;167;139;250mHello World\033[0m"
    assert strip_ansi(colored) == "Hello World"
    assert visible_len(colored) == 11


def test_badges():
    assert "ONLINE" in badge("ONLINE", "active")
    assert "STOPPED" in badge("STOPPED", "stopped")
    assert "WARN" in badge("WARN", "warning")
    assert "ERR" in badge("ERR", "error")


def test_box_card_rendering():
    card = box_card("Test Card", ["Line 1", "Line 2"], width=40)
    lines = card.splitlines()
    assert len(lines) == 4
    assert "Test Card" in lines[0]
    assert "Line 1" in lines[1]
    assert "Line 2" in lines[2]
    # Check that all borders have same visible width
    widths = [visible_len(l) for l in lines]
    assert widths[0] == widths[1] == widths[2] == widths[3] == 40


def test_render_banner():
    banner = render_banner("1.0.0")
    assert "M A X I" in banner
    assert "v1.0.0" in banner


def test_render_status_card_offline():
    card = render_status_card(None)
    assert "STOPPED" in card
    assert "Intelligence & Speech" in card


def test_render_status_card_online(monkeypatch):
    monkeypatch.setattr("app.cli.get_pid", lambda: 12345)
    health = {"pid": 12345, "status": "ok", "service": "Maxi Agent Daemon"}
    card = render_status_card(health)
    assert "ONLINE" in card
    assert "12345" in card


def test_render_config_card():
    cfg = {
        "llm_preset": "ollama",
        "llm_model": "beam:cloud",
        "llm_url": "http://localhost:11434/v1",
        "llm_key_masked": "ollama",
        "voice_model": "whisper-large-v3-turbo",
        "voice_url": "https://api.groq.com/openai/v1",
        "voice_hotkey": "option",
        "tts_provider": "ollama",
        "tts_voice": "Hugh",
        "tts_rate": 190,
        "enable_tts": True,
    }
    card = render_config_card(cfg)
    assert "LLM Model Provider" in card
    assert "beam:cloud" in card
    assert "Hugh" in card


def test_render_markdown():
    md = """# Header 1
## Header 2
- Item A
- Item B
> Important quote
```python
x = 10
```
This is **bold** and `code`."""
    rendered = render_markdown(md)
    assert "Header 1" in rendered
    assert "Item A" in rendered
    assert "Important quote" in rendered
    assert "x = 10" in rendered
