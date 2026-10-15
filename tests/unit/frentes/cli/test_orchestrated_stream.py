"""Shipped CLI stream: the first delta leaves before the source ends."""
from __future__ import annotations

from types import SimpleNamespace

from sentra_cli.agent import SentraAgent
from sentra_cli.client import ModelClient
from sentra_cli.__main__ import main, process_exit, stream_turn

_PARTS = ("Ol", "Olá", "Olá", "Olá, Dot")
_SEQUENCE = ("Ol", "á", ", Dot")


class _CountedSource:
    """Pulls one chunk at a time and counts that pull."""

    def __init__(self, parts):
        self.parts = tuple(parts)
        self.pulled = 0
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= len(self.parts):
            raise StopIteration
        part = self.parts[self._index]
        self._index += 1
        self.pulled += 1
        return part


def _open(factory, source, receipts):
    return factory(source, receipts=receipts, required=("coordinator",))


def _client(source, **kwargs):
    return ModelClient.stream_orchestrated_turn(source, **kwargs)


def _agent(source, **kwargs):
    return SentraAgent.orchestrate_stream(source, **kwargs)


def test_first_delta_is_emitted_before_the_source_ends():
    for factory in (_client, _agent):
        source = _CountedSource(_PARTS)
        seen = []
        for event in _open(factory, source, ()):
            seen.append(event)
            if event["kind"] == "delta":
                break
        assert seen[0] == {"kind": "progress", "phase": "coordinating"}
        assert seen[-1]["kind"] == "delta"
        assert seen[-1]["text"] == "Ol"
        assert source.pulled == 1
        assert source.pulled < len(source.parts)


def test_same_chunks_repeat_the_same_sequence_when_the_receipt_is_present():
    parts = ["Ol", "Olá", "Olá", "Olá, Dot"]
    missing = list(_open(_client, parts, ()))
    present = list(_open(_client, parts, ("coordinator",)))
    again = list(_open(_client, parts, ("coordinator",)))
    other = list(_open(_client, parts, ("not-coordinator",)))
    doubled = list(_open(_client, parts + parts, ("coordinator",)))
    agent_present = list(_open(_agent, list(parts), ("coordinator",)))

    assert missing[0] == {"kind": "progress", "phase": "coordinating"}
    assert present[0] == {"kind": "progress", "phase": "coordinating"}
    first_delta = next(index for index, event in enumerate(present) if event["kind"] == "delta")
    assert first_delta > 0
    assert all(event["kind"] != "delta" for event in present[:first_delta])

    assert missing[-1]["kind"] == "result"
    assert missing[-1]["success"] is False
    assert other[-1]["success"] is False
    assert present[-1]["success"] is True
    assert again[-1]["success"] is True
    assert present[-1]["sequence"] == _SEQUENCE
    assert again[-1]["sequence"] == present[-1]["sequence"]
    assert missing[-1]["sequence"] == present[-1]["sequence"]
    assert doubled[-1]["sequence"] == present[-1]["sequence"]
    assert agent_present[-1]["sequence"] == present[-1]["sequence"]
    assert [event["text"] for event in agent_present if event["kind"] == "delta"] == list(_SEQUENCE)

    shown = ""
    for delta in present[-1]["sequence"]:
        assert delta
        assert delta not in shown
        assert not shown.endswith(delta)
        assert not (shown and delta.startswith(shown))
        shown += delta
    assert shown == "Olá, Dot"
    assert present[-1]["text"] == shown
    assert "".join(doubled[-1]["sequence"]) == shown


def _printed(parts, receipts, *, announce=True):
    seen: list[tuple[str, int | None]] = []
    source = parts if isinstance(parts, _CountedSource) else list(parts)

    def write(text: str) -> None:
        pulled = source.pulled if isinstance(source, _CountedSource) else None
        seen.append((text, pulled))

    visible = stream_turn(source, receipts=receipts, write=write, announce=announce)
    return visible, seen


def test_printed_turn_shows_the_first_delta_before_the_source_ends():
    source = _CountedSource(_PARTS)
    visible, seen = _printed(source, ())
    assert seen[0] == ("coordinating\n", 0)
    assert seen[1] == ("Ol", 1)
    assert source.pulled > 1
    assert seen[1][1] < len(source.parts)
    deltas = [text for text, _pulled in seen if text not in {"coordinating\n", "\n"}]
    assert deltas == ["Ol", "á", ", Dot"]
    assert "".join(deltas) == "Olá, Dot"
    assert "".join(text for text, _pulled in seen).count("Olá, Dot") == 1
    assert visible["unit_gate"] is False
    assert "trio" not in visible


def test_printed_turn_repeats_the_same_text_and_obeys_the_receipt():
    parts = ["Ol", "Olá", "Olá", "Olá, Dot"]
    missing, _missing_seen = _printed(parts, ())
    present, present_seen = _printed(parts, ("coordinator",))
    again, again_seen = _printed(parts, ("coordinator",))
    doubled, doubled_seen = _printed(parts + parts, ("coordinator",))
    assert missing["unit_gate"] is False
    assert present["unit_gate"] is True
    assert again["unit_gate"] is True
    assert doubled["unit_gate"] is True
    assert present_seen == again_seen
    assert [text for text, _pulled in doubled_seen] == [text for text, _pulled in present_seen]
    assert "".join(text for text, _pulled in present_seen).count("Olá, Dot") == 1
    assert "Olá" not in [text for text, _pulled in present_seen]
    assert process_exit(missing) != 0
    withheld = dict(present)
    withheld["delivery"] = "uncertain"
    assert process_exit(withheld) == 3


def test_printed_turn_keeps_a_phrase_that_already_appeared():
    phrase = "em interfaces "
    visible, seen = _printed(
        ["acesso " + phrase, "seguros e ", phrase],
        ("coordinator",),
        announce=False,
    )
    texts = [text for text, _pulled in seen if text not in {"\n"}]
    assert "".join(texts) == "acesso em interfaces seguros e em interfaces "
    assert visible["shown"] == "acesso em interfaces seguros e em interfaces "
    assert visible["unit_gate"] is True


def test_finished_effect_is_shown_once_and_uncertain_is_not_exit_zero():
    calls = []

    def effect():
        calls.append("run")
        return "Olá, Dot"

    produced = effect()
    first_writes: list[str] = []
    second_writes: list[str] = []
    first = stream_turn((produced,), receipts=(), write=first_writes.append)
    second = stream_turn(
        (produced,),
        receipts=("coordinator",),
        announce=False,
        write=second_writes.append,
    )
    assert calls == ["run"]
    assert first_writes[0] == "coordinating\n"
    assert "".join(first_writes).count("Olá, Dot") == 1
    assert "coordinating\n" not in second_writes
    assert "".join(second_writes).count("Olá, Dot") == 1
    assert first["unit_gate"] is False
    assert second["unit_gate"] is True
    closed = dict(second)
    closed["delivery"] = "uncertain"
    assert process_exit(closed) == 3
    assert process_exit(first) != 0


def test_prompt_process_keeps_uncertain_and_the_unit_gate(tmp_path, monkeypatch):
    from sentra_cli import __main__ as cli_main

    class _Repl:
        def __init__(self, config):
            self.agent = SimpleNamespace(
                client=SimpleNamespace(last_error=None, last_delivery_state="uncertain"),
            )

        def run_one_shot(self, prompt):
            visible = stream_turn(
                ["Ol", "Olá", "Olá", "Olá, Dot"],
                receipts=("coordinator",),
            )
            visible["delivery"] = "uncertain"
            return visible

    monkeypatch.setattr(cli_main, "SentraREPL", _Repl)
    assert main(["--workspace", str(tmp_path), "--no-auto-start", "-p", "Ping"]) == 3

    class _Open:
        def __init__(self, config):
            self.agent = SimpleNamespace(
                client=SimpleNamespace(last_error=None, last_delivery_state="completed"),
            )

        def run_one_shot(self, prompt):
            return stream_turn(["Ol", "Olá"], receipts=())

    monkeypatch.setattr(cli_main, "SentraREPL", _Open)
    assert main(["--workspace", str(tmp_path), "--no-auto-start", "-p", "Ping"]) != 0
