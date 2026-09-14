"""Session-owned bounded results. Offsets refer to stored result lines."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

PAGE_SIZE = MAX_RETURN_LINES = 200
MAX_PAGE_CHARS = 16_000
MAX_STORE_CHARS = 1_000_000


@dataclass
class StoredResult:
    result_id: str
    lines: List[str]
    owner: str = ""
    created_at: float = field(default_factory=time.time)
    summary: str = ""
    cursor: int = 0


class ResultStore:
    def __init__(self, max_results: int = 256):
        self._results: Dict[str, StoredResult] = {}
        self.max_results = max_results

    def store(self, content: str, session=None, summary: str = "") -> Tuple[str, str, bool]:
        if len(content) > MAX_STORE_CHARS:
            raise ValueError("result exceeds storage budget; request a narrower range")
        # Split oversized lines into explicit continuations instead of returning
        # an unbounded one-line payload or silently discarding its suffix.
        lines = []
        for line in content.splitlines():
            if len(line) <= 2000:
                lines.append(line)
            else:
                lines.extend(("[CONTINUATION] " if offset else "") + line[offset:offset + 2000]
                             for offset in range(0, len(line), 2000))
        rid = f"RES-{uuid.uuid4().hex[:16].upper()}"
        owner = session.session_id if session is not None else ""
        self._results[rid] = StoredResult(rid, lines, owner=owner, summary=summary)
        while len(self._results) > self.max_results:
            self._results.pop(next(iter(self._results)))
        alias = session.register_alias("R", rid) if session is not None else rid
        page, more = self.next_page(rid, 0, session=session)
        return rid, f"ALIAS={alias}\n{page}", more

    def next_page(self, result_id: str, offset: int | None = None, session=None) -> Tuple[str, bool]:
        r = self.get(result_id, session=session)
        if not r:
            return f"RESULT_ID={result_id} NOT_FOUND", False
        start = r.cursor if offset is None else offset
        if start < 0 or start > len(r.lines):
            return "ERROR: result offset outside range", False
        chunk = []
        size = 0
        for line in r.lines[start:start + MAX_RETURN_LINES]:
            if chunk and size + len(line) + 1 > MAX_PAGE_CHARS - 512:
                break
            chunk.append(line)
            size += len(line) + 1
        r.cursor = start + len(chunk)
        more = r.cursor < len(r.lines)
        header = f"RESULT_ID={result_id} LINES={len(r.lines)} OFFSET={start} MORE={str(more).lower()}"
        if r.summary:
            header += f"\nSUMMARY: {r.summary[:120]}"
        next_hint = f"\n[[NEXT|{result_id}|{r.cursor}]]" if more else ""
        return header + "\n" + "\n".join(chunk) + next_hint, more

    def get(self, result_id: str, session=None) -> StoredResult | None:
        result = self._results.get(result_id)
        owner = session.session_id if session is not None else ""
        return result if result and result.owner == owner else None

    def close_session(self, session) -> None:
        for rid in list(self._results):
            if self._results[rid].owner == session.session_id:
                del self._results[rid]
