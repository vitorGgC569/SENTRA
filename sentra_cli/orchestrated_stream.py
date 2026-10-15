"""Ordered CLI deltas and the coordinator receipt gate.

One chunk is pulled at a time. The first new delta is yielded before the
source is exhausted. The same chunks always produce the same sequence.
Text already on screen is not emitted again. Success requires every
required receipt; the default gate is the coordinator receipt.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator


def reduce_deltas(shown: str, chunk: str) -> tuple[str, str]:
    """Return the text on screen and the part that was not shown yet."""
    if not isinstance(chunk, str) or chunk == "":
        return shown, ""
    if chunk.startswith(shown):
        delta = chunk[len(shown):]
        return shown + delta, delta
    if shown.startswith(chunk):
        return shown, ""
    return shown + chunk, chunk


def turn_succeeded(receipts: Iterable[str], required: Iterable[str]) -> bool:
    needed = tuple(required)
    if not needed or any(not isinstance(item, str) or item == "" for item in needed):
        return False
    have = {item for item in receipts if isinstance(item, str) and item}
    return all(item in have for item in needed)


def stream_orchestrated_turn(
    chunk_source: Iterable[str],
    *,
    receipts: Iterable[str] = (),
    required: Iterable[str] = ("coordinator",),
) -> Iterator[dict]:
    """Yield coordinating, then each new delta, then the receipt result.

    The generator pulls the next chunk only after the previous delta was
    yielded. A snapshot that repeats text already shown contributes nothing.
    """
    yield {"kind": "progress", "phase": "coordinating"}
    shown = ""
    sequence: list[str] = []
    for chunk in chunk_source:
        shown, delta = reduce_deltas(shown, chunk)
        if not delta:
            continue
        sequence.append(delta)
        yield {"kind": "delta", "text": delta}
    yield {
        "kind": "result",
        "text": shown,
        "success": turn_succeeded(receipts, required),
        "sequence": tuple(sequence),
    }


def orchestrate_stream(
    chunk_source: Iterable[str],
    *,
    receipts: Iterable[str] = (),
    required: Iterable[str] = ("coordinator",),
) -> Iterator[dict]:
    """Same visible stream as stream_orchestrated_turn. Nothing is buffered."""
    yield from stream_orchestrated_turn(
        chunk_source, receipts=receipts, required=required,
    )
