"""RepositorySession — agente trabalha com paths relativos a um ROOT autorizado."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set
from workspace.paths import PathAccessError, resolve_workspace_path


PathEscapeError = PathAccessError


@dataclass
class RepositorySession:
    session_id: str
    repository_root: Path
    working_directory: str = "."
    active_branch: str = "main"
    read_permissions: bool = True
    write_permissions: bool = True
    run_permissions: bool = True
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    transaction_id: Optional[str] = None
    # Aliases compactos: F17=arquivo, A12=artifact, P07=patch, T31=transaction, R81=resultado
    file_aliases: Dict[str, str] = field(default_factory=dict)
    artifact_aliases: Dict[str, str] = field(default_factory=dict)
    patch_registry: Dict[str, str] = field(default_factory=dict)
    result_registry: Dict[str, str] = field(default_factory=dict)
    transaction_aliases: Dict[str, str] = field(default_factory=dict)
    read_cache: Dict[str, str] = field(default_factory=dict)  # path -> content_hash
    _alias_counter: Dict[str, int] = field(default_factory=lambda: {"F": 0, "A": 0, "P": 0, "T": 0, "R": 0})

    def touch(self) -> None:
        self.last_activity = time.time()

    def register_alias(self, kind: str, value: str) -> str:
        registries = {"F": self.file_aliases, "A": self.artifact_aliases,
                      "P": self.patch_registry, "R": self.result_registry,
                      "T": self.transaction_aliases}
        if kind not in registries:
            raise ValueError(f"unknown alias kind: {kind}")
        for existing, item in registries[kind].items():
            if item == value:
                return existing
        self._alias_counter[kind] = self._alias_counter.get(kind, 0) + 1
        alias = f"{kind}{self._alias_counter[kind]:02d}"
        registries[kind][alias] = value
        return alias

    def resolve_alias(self, ref: str) -> str:
        if ref in self.file_aliases:
            return self.file_aliases[ref]
        if ref in self.artifact_aliases:
            return self.artifact_aliases[ref]
        if ref in self.patch_registry:
            return self.patch_registry[ref]
        if ref in self.result_registry:
            return self.result_registry[ref]
        if ref in self.transaction_aliases:
            return self.transaction_aliases[ref]
        return ref

    def resolve_path(self, rel_or_alias: str) -> Path:
        """Resolve para dentro do repository_root; bloqueia escape (../, absoluto, UNC, symlink)."""
        # Only file aliases may become paths; artifact content is never a path.
        raw = self.file_aliases.get(rel_or_alias, rel_or_alias)
        return resolve_workspace_path(self.repository_root, raw,
                                      working_directory=self.working_directory)


class SessionManager:
    def __init__(self, default_root: Path):
        self.default_root = Path(default_root).resolve()
        self.sessions: Dict[str, RepositorySession] = {}

    def open(self, repository_root: Optional[str] = None, working_directory: str = ".",
             read: bool = True, write: bool = True, run: bool = True) -> RepositorySession:
        root = Path(repository_root).resolve() if repository_root else self.default_root
        # Sessão só abre dentro do default_root (ou o próprio default_root)
        try:
            root.relative_to(self.default_root)
        except ValueError:
            # permite o próprio default_root e subpaths; fora disso bloqueia
            if root != self.default_root:
                raise PathEscapeError(f"repository_root outside authorized area: {root}")
        sess = RepositorySession(
            session_id=f"repo_{uuid.uuid4().hex[:8]}",
            repository_root=root,
            working_directory=working_directory,
            read_permissions=read, write_permissions=write, run_permissions=run,
        )
        resolve_workspace_path(root, ".", working_directory=working_directory)
        self.sessions[sess.session_id] = sess
        return sess

    def get(self, session_id: str) -> RepositorySession:
        return self.sessions[session_id]
