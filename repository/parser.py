"""Parser do protocolo compacto [[OP|ARG1|ARG2|...]]. Regex só identifica intenção."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_DIRECTIVE_RE = re.compile(r"\[\[([A-Z_]+)(?:\|([^\r\n]*))?\]\]")
_FIND_RE = re.compile(r"^\s*(\[\[[A-Z_]+(?:\|[^\r\n]*)?\]\])\s*$", re.MULTILINE)

# Allowlist: qualquer outra operação vira UNKNOWN_OPERATION (nunca executa shell)
ALLOWLIST = {
    "R", "S", "T", "SYM", "PATCH", "W", "TEST", "LINT", "TYPECHECK", "BUILD", "BENCH",
    "DIFF", "STATUS", "BRANCH", "CHECKPOINT", "ROLLBACK", "NEXT", "RART",
    "GIT_DIFF", "GIT_STATUS",
}


@dataclass
class Directive:
    operation: str
    args: List[str]
    raw: str
    known: bool = True


def parse(text: str) -> Optional[Directive]:
    if not isinstance(text, str) or len(text) > 8192 or "\x00" in text:
        return None
    text = text.strip()
    m = _DIRECTIVE_RE.fullmatch(text)
    if not m:
        return None
    op = m.group(1).strip()
    payload = m.group(2) or ""
    if "[[" in payload or "]]" in payload:
        return None
    args = payload.split("|") if payload else []
    args = [a.strip() for a in args]
    return Directive(operation=op, args=args, raw=text, known=(op in ALLOWLIST))


def find_all(text: str) -> List[Directive]:
    out: List[Directive] = []
    for m in _FIND_RE.finditer(text):
        directive = parse(m.group(1))
        if directive:
            out.append(directive)
    return out
