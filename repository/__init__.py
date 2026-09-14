"""Local Repository Command Gateway — protocolo compacto [[OP|args]]."""
from .session import RepositorySession, SessionManager, PathEscapeError
from .parser import Directive, parse, find_all, ALLOWLIST
from .policy import PolicyEngine, PolicyDenied, PROTECTED_COMPONENTS
from .registry import CommandRegistry
from .transactions import TransactionManager
from .result_store import ResultStore
from .git_adapter import GitAdapter
from .gateway import CommandGateway, AgentConsoleBridge

__all__ = ["RepositorySession", "SessionManager", "PathEscapeError", "Directive",
           "parse", "find_all", "ALLOWLIST", "PolicyEngine", "PolicyDenied",
           "PROTECTED_COMPONENTS", "CommandRegistry", "TransactionManager",
           "ResultStore", "GitAdapter", "CommandGateway", "AgentConsoleBridge"]
