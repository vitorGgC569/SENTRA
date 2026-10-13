"""SENTRA interop: opt-in protocol adapters, no implicit external execution."""
from .gate import DispatchOutcome, InteropGate, OperationJournal
from .acp import ACPSessionAdapter, ACPStdioTransport, ACPProtocolError, ACPLaunchError
from .a2a import A2AEnvelope, A2ATaskBoundary, AgentIdentity, A2AValidationError
from .mcp import ToolHiveMCPBoundary, MCPToolGrant, ToolHiveEndpoint
from .registry import ACPRegistryEntry, ACPVersionedCatalog
from .openhands import OpenHandsEvent, OpenHandsEventBridge
from .requests import InteropRequestMapper, InteropMappingDenied
from .acp_local import ACPLocalLifecycle, ACPLocalLedger, ACPReplayBlocked
from .a2a_loopback import A2ALoopbackClient, A2ALoopbackServer
from .mcp_stdio import MCPStdioClient, MCPStdioError
from .activepieces_loopback import ActivepiecesLoopbackServer, ActivepiecesActionClient
from .openhands_local import OpenHandsLocalStream, OpenHandsLocalError
from .workflow_bridge import SubagentWorkflowBridge, WorkflowReplayDenied
from .mcp_sdk_compat import MCPTypescriptCompatClient
from .acp_verified import ACPVerifiedResolver, VerifiedACPEntrypoint, ACPVerificationDenied
from .a2a_sse import A2ASSELedger, A2ASSEServer, A2ASSEClient, A2ASSEDenied
from .central import CentralInteropAdapter, CentralAuditReceipt, CentralInteropBlocked
from .provider_machine import InteropProviderMachine, INTEROP_CAPABILITIES
from .channel_machine import ChannelProviderMachine
from .registry_machine import RegistryProviderMachine

__all__ = [
    "DispatchOutcome", "InteropGate", "OperationJournal",
    "ACPSessionAdapter", "ACPStdioTransport", "ACPProtocolError", "ACPLaunchError",
    "A2AEnvelope", "A2ATaskBoundary", "AgentIdentity", "A2AValidationError",
    "ToolHiveMCPBoundary", "MCPToolGrant", "ToolHiveEndpoint",
    "ACPRegistryEntry", "ACPVersionedCatalog", "InteropRequestMapper", "InteropMappingDenied",
    "OpenHandsEventBridge",
    "OpenHandsEvent",
    "ACPLocalLifecycle", "ACPLocalLedger", "ACPReplayBlocked",
    "A2ALoopbackClient", "A2ALoopbackServer",
    "MCPStdioClient", "MCPStdioError",
    "ActivepiecesLoopbackServer", "ActivepiecesActionClient",
    "OpenHandsLocalStream", "OpenHandsLocalError",
    "SubagentWorkflowBridge", "WorkflowReplayDenied",
    "MCPTypescriptCompatClient", "ACPVerifiedResolver", "VerifiedACPEntrypoint",
    "ACPVerificationDenied", "A2ASSELedger", "A2ASSEServer",
    "A2ASSEClient", "A2ASSEDenied",
    "CentralInteropAdapter", "CentralAuditReceipt", "CentralInteropBlocked",
    "InteropProviderMachine", "INTEROP_CAPABILITIES",
    "ChannelProviderMachine", "RegistryProviderMachine",
]

from .workflow_runtime_host import RuntimeProviderHost
from .workflow_runtime_machine import RuntimeProviderMachine, TerminalWriteMachine, configure_runtime_machine, aconfigure_runtime_machine, configure_terminal_machine
from .workflow_shell import PulsoShellDispatch
from .workflow_shell_host import PulsoMachineResolver
__all__ += ["RuntimeProviderHost", "RuntimeProviderMachine", "TerminalWriteMachine", "configure_runtime_machine", "aconfigure_runtime_machine", "configure_terminal_machine", "PulsoShellDispatch", "PulsoMachineResolver"]

# Keep the generic workflow subclass lazy: the existing runtime workflow module
# imports this package while defining DocumentWorkflowMachine.
__all__ += ["WorkflowProviderMachine", "configure_workflow_machine", "RepositoryJobMachine"]
def __getattr__(name):
    if name in {"WorkflowProviderMachine", "configure_workflow_machine"}:
        from . import workflow_provider_machine
        return getattr(workflow_provider_machine,name)
    if name == "RepositoryJobMachine":
        from .workflow_jobs import RepositoryJobMachine
        return RepositoryJobMachine
    raise AttributeError(name)
