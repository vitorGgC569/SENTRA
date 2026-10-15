"""Presentation-only boundary for the existing uppercase CLI directive syntax.

This parser never executes or authorizes a directive. Lowercase/Unicode/mixed
case bracket prose is ordinary text. Ambiguous unfinished headers are held
until more text arrives; arguments of a structured header are never exposed.
"""
from __future__ import annotations
import re

_HEADER = re.compile(r"\[\[[A-Z_]+(?:\||\]\])")
_UNFINISHED = re.compile(r"\[\[(?:[A-Z_]+\]?|)\Z")


def prose_prefix(text: str, *, complete: bool = False) -> str:
    if not isinstance(text, str) or type(complete) is not bool:
        raise TypeError("text and an explicit completion boolean required")
    if "[" not in text:
        return text
    header = _HEADER.search(text)
    if header is not None:
        return text[:header.start()]
    if not complete:
        unfinished = _UNFINISHED.search(text)
        if unfinished is not None:
            return text[:unfinished.start()]
        if text.endswith("["):
            return text[:-1]
    return text
