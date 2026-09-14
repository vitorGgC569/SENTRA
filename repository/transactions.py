"""Transactional file operations: BEGIN -> snapshot -> edit -> validate -> COMMIT/ROLLBACK."""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def sha256_file(p: Path) -> str:
    if not p.exists():
        return "missing"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


@dataclass
class Transaction:
    transaction_id: str
    agent_id: str
    task_id: str
    files: List[str]
    session_id: str = ""
    before: Dict[str, str] = field(default_factory=dict)
    after: Dict[str, str] = field(default_factory=dict)
    snapshots: Dict[str, Optional[bytes]] = field(default_factory=dict)
    status: str = "OPEN"
    created_at: float = field(default_factory=time.time)


class TransactionManager:
    def __init__(self):
        self._txns: Dict[str, Transaction] = {}

    def begin(self, agent_id: str, task_id: str, paths: List[Path], session_id: str = "") -> Transaction:
        txn = Transaction(transaction_id=f"txn_{uuid.uuid4().hex[:8]}", agent_id=agent_id,
                          task_id=task_id, files=[str(p) for p in paths], session_id=session_id)
        for p in paths:
            txn.before[str(p)] = sha256_file(p)
            txn.snapshots[str(p)] = p.read_bytes() if p.exists() else None
        self._txns[txn.transaction_id] = txn
        return txn

    def commit(self, txn: Transaction, paths: List[Path]) -> Transaction:
        if txn.status != "OPEN":
            raise ValueError(f"transaction is {txn.status}")
        for p in paths:
            txn.after[str(p)] = sha256_file(p)
        txn.status = "COMMITTED"
        return txn

    def rollback(self, txn: Transaction) -> Transaction:
        if txn.status == "ROLLED_BACK":
            return txn
        # Do not overwrite a newer edit with an obsolete snapshot.
        if txn.status == "COMMITTED":
            for fstr in txn.snapshots:
                if sha256_file(Path(fstr)) != txn.after.get(fstr):
                    raise ValueError(f"ROLLBACK_CONFLICT: {fstr} changed after transaction")
        for fstr, content in txn.snapshots.items():
            p = Path(fstr)
            if content is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
            txn.after[str(p)] = sha256_file(p)
        txn.status = "ROLLED_BACK"
        return txn
