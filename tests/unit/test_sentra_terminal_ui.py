"""Pure checks for the centered Windows CLI (no live provider or workspace)."""
from __future__ import annotations

import io
import sys

from sentra_cli.terminal_ui import CenteredTerminalUI, _clean, _clip, geometry


def test_dashboard_responsive_and_fits() -> None:
    for width, height in ((120, 43), (100, 31), (75, 25), (55, 20), (35, 13)):
        layout = geometry(width, height)
        assert layout.left >= 1
        assert layout.left + layout.width - 1 <= width
        assert 1 <= layout.top < layout.input_row < layout.info_row < layout.footer_row <= height
        if width > 78:
            assert abs((layout.left - 1) - (width - layout.width) / 2) <= 1


def test_dashboard_looks_like_centered_composer_and_escapes_prompt() -> None:
    capture = io.StringIO()
    ui = CenteredTerminalUI(capture, enabled=True)
    layout = geometry(112, 40)
    ui._draw(layout, model="sentra/codex/current", effort="high",
             turns=[], value="", cursor=0)
    screen = capture.getvalue()
    assert "\x1b[2J" in screen
    assert "█" in screen and "Seu ambiente" in screen
    assert "sentra/codex/current" in screen
    assert "Pergunte qualquer coisa" in screen
    assert "/model" in screen and "/help" in screen
    assert f"\x1b[{layout.input_row};{layout.left + 3}H" in screen
    assert _clean("a\x1b[2Jb\n\t") == "ab  "
    assert _clip("abcdefgh", 4) == "abc…"


def test_dashboard_redraws_recent_history_in_same_centered_column() -> None:
    capture = io.StringIO()
    ui = CenteredTerminalUI(capture, enabled=True)
    layout = geometry(100, 30, has_history=True)
    ui._draw(layout, model="sentra/chatgpt-web/gpt-6", effort="medium",
             turns=[("user", "Crie um arquivo"), ("assistant", "Operação depende de autorização")],
             value="Novo pedido", cursor=len("Novo pedido"))
    screen = capture.getvalue()
    assert "VOCÊ" in screen and "SENTRA" in screen
    assert "Crie um arquivo" in screen and "depende de autorização" in screen
    assert screen.index("Crie um arquivo") < screen.index("Novo pedido")
    assert "ChatGPT Web" in screen


def test_editor_inserts_moves_and_reuses_previous_prompt(monkeypatch) -> None:
    import msvcrt
    sequence = iter(["o", "l", "a", "\xe0", "K", "á", "\r",
                     "\xe0", "H", "\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(sequence))
    stream = io.StringIO()
    ui = CenteredTerminalUI(stream, enabled=True)
    monkeypatch.setattr(ui, "_limits", lambda: (100, 30))
    first = ui.read(model="sentra/codex/current", effort="low", turns=[])
    second = ui.read(model="sentra/codex/current", effort="low", turns=[("user", first)])
    assert first == "oláa"  # Insert before last character.
    assert second == first
    assert ui.history == [first, second]


def test_editor_control_characters_do_not_inject_escape_sequences(monkeypatch) -> None:
    import msvcrt
    sequence = iter(["x", "\x1b", "c", "\x01", "A", "\x05", "!", "\r"])
    monkeypatch.setattr(msvcrt, "getwch", lambda: next(sequence))
    ui = CenteredTerminalUI(io.StringIO(), enabled=True)
    monkeypatch.setattr(ui, "_limits", lambda: (100, 30))
    assert ui.read(model="sentra/codex/current", effort="low", turns=[]) == "Axc!"
