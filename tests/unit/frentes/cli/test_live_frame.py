"""The centered UI paints Coordenando immediately and the closing frame once."""
from __future__ import annotations

import io
from types import SimpleNamespace

from sentra_cli.repl import SentraREPL
from sentra_cli.terminal_ui import CenteredTerminalUI


class _UI(CenteredTerminalUI):
    def __init__(self):
        super().__init__(stream=io.StringIO(), enabled=True)
        self.frames: list[list[tuple[str, str]]] = []

    def _limits(self):
        return 80, 24

    def _draw(self, layout, *, model, effort, turns, value, cursor, choices=None):
        self.frames.append(list(turns))
        super()._draw(
            layout, model=model, effort=effort, turns=turns,
            value=value, cursor=cursor, choices=choices,
        )


def _repl():
    repl = object.__new__(SentraREPL)
    repl.config = SimpleNamespace(model="sentra/codex/current")
    return repl


def test_coordinating_is_painted_before_deltas_and_the_final_frame_closes():
    repl = _repl()
    ui = _UI()
    turns: list[tuple[str, str]] = []
    reply: list[str] = []
    state = {"last_draw": 0.0}
    kwargs = dict(ui=ui, turns=turns, line="Ping", reply=reply, effort="high", state=state)

    repl._consume_live_text("coordinating\n", now=10.0, **kwargs)
    assert ui.frames[0][-2:] == [("system", "Coordenando"), ("user", "Ping")]
    assert all("coordinating" not in text for _, text in ui.frames[0])
    assert "Coordenando" in ui.stream.getvalue()
    assert "coordinating" not in ui.stream.getvalue()
    painted = len(ui.frames)

    repl._consume_live_text("Ol", now=10.02, **kwargs)
    repl._consume_live_text("á", now=10.04, **kwargs)
    repl._consume_live_text(", Dot", now=10.06, **kwargs)
    assert len(ui.frames) == painted
    assert "".join(reply) == "Olá, Dot"

    repl._finish_live_frame(ui=ui, turns=turns, line="Ping", reply=reply, effort="high")
    assert len(ui.frames) == painted + 1
    assert ui.frames[-1][-1] == ("assistant", "Olá, Dot")
    assert ("system", "Coordenando") in ui.frames[-1]
    assert "Olá, Dot" in ui.stream.getvalue()


def test_intermediate_deltas_wait_seventy_milliseconds():
    repl = _repl()
    ui = _UI()
    turns: list[tuple[str, str]] = []
    reply: list[str] = []
    state = {"last_draw": 0.0}
    kwargs = dict(ui=ui, turns=turns, line="Ping", reply=reply, effort="high", state=state)

    repl._consume_live_text("coordinating\n", now=10.0, **kwargs)
    repl._consume_live_text("Ol", now=10.08, **kwargs)
    assert ui.frames[-1][-1] == ("assistant", "Ol")
    held = len(ui.frames)
    repl._consume_live_text("á", now=10.10, **kwargs)
    assert len(ui.frames) == held
    repl._finish_live_frame(ui=ui, turns=turns, line="Ping", reply=reply, effort="high")
    assert ui.frames[-1][-1] == ("assistant", "Olá")
    assert len(ui.frames) == held + 1
