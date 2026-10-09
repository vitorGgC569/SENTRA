"""SENTRA OS capability contracts and executor registry."""
from .contracts import Capability, Machine, OperationRequest, OperationResult, PolicyDecision
from .access import AuthorizedOperationGateway, OperationAccess
from .authority_bridge import BoundWorkItemPolicy
from .executor import AuthorizationRequired, DuplicateOperation, ExecutorAdapter, ExecutorRegistry, InvalidOperation
