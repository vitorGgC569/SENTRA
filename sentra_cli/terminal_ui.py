"""Centered SENTRA terminal composer.

Windows Console/Windows Terminal: native keyboard input and VT rendering, no
third-party TUI runtime. Unavailable/redirected terminals fall back to Rich
console input in the caller, retaining the existing noninteractive interface.
This is a presentation boundary only; it does not dispatch tools or grants.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import sys
import textwrap
import unicodedata
from typing import TextIO

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_FONT = {
    "S": ("01111", "10000", "01110", "00001", "11110"),
    "E": ("11111", "10000", "11110", "10000", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100"),
    "R": ("11110", "10001", "11110", "10100", "10010"),
    "A": ("01110", "10001", "11111", "10001", "10001"),
}

def _clean(value: object, limit: int = 4000) -> str:
    """Never allow provider-controlled terminal escape/control sequences."""
    raw = _ANSI.sub("", str(value or ""))
    return "".join(ch if ch.isprintable() else " " for ch in raw)[:limit]

def _cells(text: str) -> int:
    return sum(0 if unicodedata.combining(ch) else
               2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if _cells(text) <= width:
        return text
    if width == 1:
        return "…"
    result = ""
    for ch in text:
        if _cells(result + ch) > width - 1:
            break
        result += ch
    return result + "…"

def _fit(text: str, width: int) -> str:
    clipped = _clip(_clean(text), width)
    return clipped + " " * max(0, width - _cells(clipped))

def _paint(text: str, fg: str = "", bg: str = "", *, enabled: bool = True) -> str:
    if not enabled:
        return text
    prefix = ("\x1b[38;2;" + fg + "m" if fg else "")
    prefix += ("\x1b[48;2;" + bg + "m" if bg else "")
    return prefix + text + "\x1b[0m" if prefix else text

@dataclass(frozen=True)
class Geometry:
    columns: int
    rows: int
    left: int
    width: int
    top: int
    input_row: int
    info_row: int
    footer_row: int
    full_logo: bool

def geometry(columns: int, rows: int, *, has_history: bool = False) -> Geometry:
    """Pure sizing rules, safe for narrow terminals and resized windows."""
    columns = max(20, columns)
    rows = max(9, rows)
    width = min(78, max(16, columns - 6))
    left = max(1, (columns - width) // 2 + 1)
    full_logo = not has_history and columns >= 55 and rows >= 18
    if has_history:
        top = 2
        input_row = max(6, rows - 5)
    elif full_logo:
        top = max(2, (rows - 15) // 2)
        input_row = min(rows - 4, top + 9)
    else:
        top = max(2, (rows - 10) // 2)
        input_row = min(rows - 4, top + 3)
    return Geometry(columns, rows, left, width, top, input_row,
                    input_row + 1, input_row + 3, full_logo)


def _vt_console() -> bool:
    if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        import ctypes
        from ctypes import wintypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        current = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(current)):
            return False
        if not ctypes.windll.kernel32.SetConsoleMode(handle, current.value | 0x0004):
            return False
        return True
    except (AttributeError, OSError, ValueError):
        return False


class CenteredTerminalUI:
    """Read one keyboard-edited turn with a responsive centered compositor."""

    def __init__(self, stream: TextIO | None = None, *, enabled: bool | None = None):
        self.stream = stream or sys.stdout
        self.enabled = _vt_console() if enabled is None else enabled
        self.color = "NO_COLOR" not in os.environ
        self.history: list[str] = []
        self._last_geometry: Geometry | None = None

    def _go(self, row: int, column: int) -> None:
        self.stream.write(f"\x1b[{max(1, row)};{max(1, column)}H")

    def _write(self, row: int, col: int, value: str) -> None:
        self._go(row, col)
        self.stream.write(value)

    def _logo(self, layout: Geometry) -> None:
        if not layout.full_logo:
            title = "S E N T R A"
            self._write(layout.top, max(1, (layout.columns - len(title)) // 2 + 1),
                        _paint(title, "242;243;247", enabled=self.color))
            return
        name = "SENTRA"
        glyph_width = 5 * len(name) + len(name) - 1
        origin = max(1, (layout.columns - glyph_width) // 2 + 1)
        for y in range(5):
            line = "".join(("".join("█" if cell == "1" else " " for cell in _FONT[letter][y]))
                           + (" " if i < len(name) - 1 else "")
                           for i, letter in enumerate(name))
            # Silver wordmark, with restrained white emphasis at the end.
            split = 4 * 6
            styled = (_paint(line[:split], "135;138;145", enabled=self.color) +
                      _paint(line[split:], "244;245;249", enabled=self.color))
            self._write(layout.top + y, origin, styled)

    def _model_picker(self, layout: Geometry, models: list[str], current: str) -> None:
        """An always-visible inline picker, instead of a Rich table erased by redraw."""
        start = 3
        visible = max(1, layout.input_row - start - 4)
        left = layout.left + 2
        width = max(12, layout.width - 4)
        self._write(start, left, _paint(_fit("MODELOS  ·  número + Enter  ·  0 cancela", width),
                                         "156;173;198", enabled=self.color))
        count = min(len(models), visible)
        for index, value in enumerate(models[:count], 1):
            name = _clean(value, 160)
            suffix = "   ✓" if value == current else ""
            line = f"{index:>2}  {name}{suffix}"
            self._write(start + index + 1, left,
                        _paint(_fit(line, width), "220;222;232" if value == current else "154;158;168",
                               enabled=self.color))
        if len(models) > count:
            self._write(start + count + 2, left,
                        _paint(_fit(f"+ {len(models) - count} modelos · /model ID para os demais", width),
                               "125;129;139", enabled=self.color))

    def _history(self, layout: Geometry, turns: list[tuple[str, str]]) -> None:
        width = layout.width - 4
        available = max(0, layout.input_row - 7)
        lines: list[tuple[str, str]] = []
        for speaker, content in turns[-12:]:
            source = _ANSI.sub("", str(content))
            label = "VOCÊ" if speaker == "user" else "SENTRA" if speaker == "assistant" else "SISTEMA"
            lines.append(("label", label))
            for paragraph in source.replace("\r", "").split("\n"):
                clean = _clean(paragraph, 2000)
                wrapped = textwrap.wrap(clean, width=max(14, width - 2),
                                        break_long_words=True, replace_whitespace=True) or [""]
                lines.extend(("text", part) for part in wrapped)
            lines.append(("space", ""))
        if len(lines) > available and available:
            lines = [("label", "↑ Histórico anterior")] + lines[-max(0, available - 1):]
        for i, (kind, message) in enumerate(lines[:available]):
            color = "143;172;219" if kind == "label" else "207;209;214"
            self._write(5 + i, layout.left + 2,
                        _paint(_fit(message, width), color, enabled=self.color))

    def _input_display(self, value: str, cursor: int, cells: int) -> tuple[str, int]:
        """Horizontal viewport keeps the caret inside the centered textbox."""
        chars = list(value)
        pos = min(max(0, cursor), len(chars))
        left = 0
        while left < pos and _cells("".join(chars[left:pos])) > cells - 2:
            left += 1
        visible = ""
        for char in chars[left:]:
            if _cells(visible + char) > cells:
                break
            visible += char
        offset = _cells("".join(chars[left:pos]))
        return _fit(visible, cells), min(cells, offset)

    def _render_input(self, layout: Geometry, value: str, cursor: int) -> None:
        inner_width = layout.width - 4
        shown, caret = self._input_display(value, cursor, inner_width)
        if not value:
            shown = _fit("Pergunte qualquer coisa...", inner_width)
            color = "136;138;146"
        else:
            color = "238;239;242"
        self._write(layout.input_row, layout.left,
                    _paint("│", "91;163;247", "31;32;35", enabled=self.color) +
                    _paint("  " + shown + " ", color, "31;32;35", enabled=self.color))
        self._go(layout.input_row, layout.left + 3 + (caret if value else 0))
        self.stream.flush()

    def _draw(self, layout: Geometry, *, model: str, effort: str, turns: list[tuple[str, str]],
              value: str, cursor: int, choices: list[str] | None = None) -> None:
        self.stream.write("\x1b[?25l\x1b[H\x1b[2J")
        self._logo(layout)
        if not turns and choices is None:
            tagline = "Seu ambiente de criação e colaboração"
            row = layout.top + (6 if layout.full_logo else 1)
            self._write(row, max(1, (layout.columns - len(tagline)) // 2 + 1),
                        _paint(tagline, "118;121;131", enabled=self.color))
        elif choices is None:
            self._history(layout, turns)
        if choices is not None:
            self._model_picker(layout, choices, model)
        self._write(layout.input_row - 1, layout.left + 1, " " * (layout.width - 2))
        provider = ("Codex" if model.startswith("sentra/codex/") else
                    "ChatGPT Web" if model.startswith("sentra/chatgpt-web/") else
                    "SENTRA Gateway")
        width = layout.width - 4
        sep = "  ·  "
        model_label, effort_label = _clean(model, 100), _clean(effort, 32)
        flat = "Build" + sep + model_label + sep + provider + sep + effort_label
        if _cells(flat) <= width:
            segments = (("Build", "98;162;248"), (sep, "117;120;130"),
                        (model_label, "234;234;239"), (sep + provider + sep, "145;148;160"),
                        (effort_label, "251;188;94"))
            styled_label = "".join(_paint(word, color, "31;32;35", enabled=self.color)
                                   for word, color in segments)
            styled_label += _paint(" " * (width - _cells(flat)), bg="31;32;35", enabled=self.color)
        else:
            styled_label = _paint(_fit(flat, width), "210;214;224", "31;32;35",
                                  enabled=self.color)
        self._write(layout.info_row, layout.left,
                    _paint("│", "91;163;247", "31;32;35", enabled=self.color) +
                    _paint("  ", bg="31;32;35", enabled=self.color) +
                    styled_label + _paint(" ", bg="31;32;35", enabled=self.color))
        footer = ("Escolha o número  ·  0 cancela" if choices is not None else
                  "/model modelos   /help comandos   ↑↓ histórico")
        footer_width = max(0, layout.width - len(footer))
        self._write(layout.footer_row, layout.left,
                    _paint("~", "133;137;148", enabled=self.color))
        if footer_width > 0:
            self._write(layout.footer_row, layout.left + footer_width,
                        _paint(footer, "128;132;142", enabled=self.color))
        self.stream.write("\x1b[?25h")
        self._render_input(layout, value, cursor)

    @staticmethod
    def _limits() -> tuple[int, int]:
        size = shutil.get_terminal_size((108, 36))
        return size.columns, size.lines

    def read(self, *, model: str, effort: str, turns: list[tuple[str, str]],
             choices: list[str] | None = None) -> str:
        if not self.enabled:
            raise RuntimeError("native interactive terminal not available")
        import msvcrt
        value = ""
        position = 0
        history_index: int | None = None
        width, height = self._limits()
        layout = geometry(width, height, has_history=bool(turns) or choices is not None)
        self._last_geometry = layout
        self._draw(layout, model=model, effort=effort, turns=turns,
                   value=value, cursor=position, choices=choices)
        while True:
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                self._go(layout.footer_row + 1, 1)
                self.stream.write("\x1b[0m\n")
                self.stream.flush()
                if value.strip():
                    self.history.append(value)
                    self.history = self.history[-100:]
                return value
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x1a":
                raise EOFError
            if char in ("\x00", "\xe0"):
                special = msvcrt.getwch()
                if special == "K":
                    position = max(0, position - 1)
                elif special == "M":
                    position = min(len(value), position + 1)
                elif special == "G":
                    position = 0
                elif special == "O":
                    position = len(value)
                elif special in ("H", "P") and self.history:
                    if history_index is None:
                        history_index = len(self.history) if special == "P" else len(self.history) - 1
                    else:
                        history_index += -1 if special == "H" else 1
                    history_index = min(len(self.history), max(0, history_index))
                    value = self.history[history_index] if history_index < len(self.history) else ""
                    position = len(value)
                elif special == "S" and position < len(value):
                    value = value[:position] + value[position + 1:]
            elif char in ("\b", "\x7f"):
                if position:
                    value = value[:position - 1] + value[position:]
                    position -= 1
            elif char == "\x01":  # Ctrl+A
                position = 0
            elif char == "\x05":  # Ctrl+E
                position = len(value)
            elif char == "\x15":  # Ctrl+U
                value = value[position:]
                position = 0
            elif char == "\x1b":  # Escape alone must never silently erase a draft.
                pass
            elif char.isprintable() and len(value) < 32768:
                value = value[:position] + char + value[position:]
                position += 1
                history_index = None
            new_width, new_height = self._limits()
            if (new_width, new_height) != (width, height):
                width, height = new_width, new_height
                layout = geometry(width, height, has_history=bool(turns) or choices is not None)
                self._last_geometry = layout
                self._draw(layout, model=model, effort=effort, turns=turns,
                   value=value, cursor=position, choices=choices)
            else:
                self._render_input(layout, value, position)
