"""Application-facing host for centrally admitted machines and evidence.

One owned asyncio loop keeps registry/transport locks in their actual loop when
the Canvas HTTP server uses several request threads. Configuration comes from
the authenticated host; agent operations cannot register machines or origins.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import threading
import time

from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.central_authority import CentralDurableIntentAuthority
from sentra_runtime.contracts import OperationRequest
from sentra_runtime.executor import AuthorizationRequired


class MachineHost:
    def __init__(self, control: ControlPlaneService, *, owner: str):
        if not isinstance(control, ControlPlaneService) or not owner:
            raise ValueError("authenticated central machine host required")
        self.control, self.owner = control, owner
        from .machine_configuration import MachineConfigurationStore
        self.configurations = MachineConfigurationStore(control.store, owner)
        self.restore_errors = []
        self.memory_errors = []
        self._experiences = None
        self._telemetry=None
        self._diagnostic_errors=0
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._factories = {}
        self._inventory = {}
        self._configuration_handlers = {}
        self._runtime_host_resolver = None
        self._canvas_adapter = None
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="sentra-machine-host")
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("machine host loop failed to start")
        try:
            from .telemetry_pipeline import TelemetryPipeline
            setting=TelemetryPipeline.load_settings(control.store,owner)
            if setting and setting.get("enabled") is True:
                self._telemetry=TelemetryPipeline(control.store,owner=owner,**setting["configuration"])
        except Exception:self._diagnostic_errors+=1

    def configure_telemetry(self,config):
        from .telemetry_pipeline import TelemetryPipeline
        if not isinstance(config,dict) or set(config)-{"enabled","endpoint","max_pending","batch_size","batch_bytes","flush_seconds","retention_seconds","max_attempts"}:
            raise ValueError("bounded diagnostic configuration required")
        values=dict(config);enabled=values.pop("enabled",None)
        if type(enabled) is not bool:raise ValueError("explicit diagnostic enable/disable required")
        candidate=TelemetryPipeline(self.control.store,owner=self.owner,start=False,**values) if enabled else None
        TelemetryPipeline.save_settings(self.control.store,self.owner,{"enabled":enabled,"configuration":values})
        previous=self._telemetry;self._telemetry=candidate
        if previous:previous.close()
        if candidate:candidate.start()
        return self.telemetry_status()

    def telemetry_status(self):
        value=self._telemetry.status() if self._telemetry else {"enabled":False,"diagnostics_only":True,"audit_complete":False}
        return {**value,"enabled":self._telemetry is not None,"host_diagnostic_errors":self._diagnostic_errors}

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _call(self, coroutine, *, timeout=150):
        if self._closed:
            coroutine.close()
            raise RuntimeError("machine host is closed")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            # This does not kill blocking I/O. The central boundary retains
            # exclusion/lease and records UNCERTAIN rather than resending it.
            future.cancel()
            raise

    @staticmethod
    def _machine_id(workspace_id, agent_id, kind):
        digest = hashlib.sha256((workspace_id + "\0" + agent_id).encode()).hexdigest()[:24]
        return "canvas-" + kind + "-" + digest

    def configure_documents(self, *, workspace_id: str, workspace_root: str,
                            agent_id: str, recalculation_backends=None, ocr_backends=None) -> dict:
        return self._call(self._configure_documents(workspace_id, workspace_root, agent_id,
                                                    recalculation_backends or [],ocr_backends or []))

    async def _configure_documents(self, workspace_id, workspace_root, agent_id, recalculation_backends, ocr_backends):
        from sentra_executors.central_integration import CentralExecutorFactory
        from sentra_executors.documents import (DocumentBinding, FormulaRecalculationBinding,
                                                OCRBinding, declare_document_machine)
        from sentra_executors.rpa import dependency_versions
        from .workspace_paths import workspace_paths
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir() or not workspace_id or not agent_id:
            raise ValueError("trusted Canvas workspace/agent required")
        machine_id = self._machine_id(workspace_id, agent_id, "documents")
        if machine_id in self._inventory:
            if recalculation_backends or ocr_backends:
                raise ValueError("document machine already configured; provider configuration is immutable")
            return dict(self._inventory[machine_id])
        def providers(values, cls):
            if not isinstance(values,list) or len(values)>4 or any(not isinstance(v,dict) for v in values):
                raise ValueError("bounded explicit document providers required")
            records=[]
            for value in values:
                config=dict(value)
                if "owner_principal_id" in config and config["owner_principal_id"]!=agent_id:
                    raise ValueError("document provider owner mismatch")
                config["owner_principal_id"]=agent_id
                records.append(cls(**config))
            return tuple(records)
        recalculation=providers(recalculation_backends,FormulaRecalculationBinding)
        ocr=providers(ocr_backends,OCRBinding)
        transform_actions=["excel.transform","table.transform","pdf.extract_pages"]
        if recalculation:transform_actions.append("excel.recalculate")
        if ocr:transform_actions.append("pdf.ocr")
        paths = workspace_paths(root,self.control.durable.root)
        bindings = (
            DocumentBinding("document:inspect", paths,
                actions=("excel.inspect", "table.inspect", "pdf.inspect", "pdf.text","artifact.verify","acceptance.evaluate")),
            DocumentBinding("document:transform", paths,
                actions=tuple(transform_actions), timeout_seconds=120 if recalculation or ocr else 30,
                recalculation_backends=recalculation,ocr_backends=ocr),
        )
        factory = CentralExecutorFactory(control=self.control, owner=self.owner, agent_id=agent_id)
        declaration = declare_document_machine(machine_id=machine_id,
            owner_principal_id=agent_id, bindings=bindings, policy=factory.policy)
        factory.register_execution(declaration)
        self._factories[machine_id] = factory
        self._inventory[machine_id] = {
            "machine_id": machine_id, "kind": "documents", "workspace_id": workspace_id,
            "agent_id": agent_id, "capabilities": [b.capability_id for b in bindings],
            "actions": {b.capability_id: list(b.actions) for b in bindings},
            "dependencies": dependency_versions(), "registered": True,
            "grant_created": False,
        }
        self.configurations.put(machine_id, {"kind":"documents","workspace_id":workspace_id,
            "workspace_root":str(root),"agent_id":agent_id,
            "recalculation_backends":[asdict(p) for p in recalculation],"ocr_backends":[asdict(p) for p in ocr]})
        return dict(self._inventory[machine_id])

    def configure_workspace_files(self, *, workspace_id: str, workspace_root: str, agent_id: str) -> dict:
        """Owner-configured UTF-8 files machine. No WorkItems or Grants created."""
        return self._call(self._configure_workspace_files(workspace_id, workspace_root, agent_id))

    def configure_worktrees(self, *, workspace_id, workspace_root, agent_id, dot_id):
        return self._call(self._configure_worktrees(workspace_id,workspace_root,agent_id,dot_id))

    async def _configure_worktrees(self,workspace_id,workspace_root,agent_id,dot_id):
        from contextlib import closing
        from sentra_executors.git_worktrees import GitWorktreeBinding,declare_git_worktree_machine
        from sentra_executors.central_integration import CentralExecutorFactory
        from workspace.worktrees import WorktreeManager
        root=Path(workspace_root).resolve(strict=True)
        with closing(self.control.store.connect('shell')) as db:
            dot=self.control.shell._entity(db,self.owner,workspace_id,'dot',dot_id)
        if dot.get('agent_id')!=agent_id:raise PermissionError('worktree configuration must match its Dot agent')
        machine_id=self._machine_id(workspace_id,agent_id,'git-worktrees')
        if machine_id in self._inventory:return dict(self._inventory[machine_id])
        manager=WorktreeManager(root,self.control.durable.root/'git-worktrees'/machine_id)
        bindings=tuple(GitWorktreeBinding(cap,manager,dot_id,control=self.control,owner=self.owner) for cap in ('git:worktree','git:worktree.inspect'))
        factory=CentralExecutorFactory(control=self.control,owner=self.owner,agent_id=agent_id)
        factory.register_execution(declare_git_worktree_machine(machine_id=machine_id,
            owner_principal_id=agent_id,bindings=bindings,policy=factory.policy))
        self._factories[machine_id]=factory
        self._inventory[machine_id]={'machine_id':machine_id,'kind':'git-worktrees','workspace_id':workspace_id,
            'agent_id':agent_id,'dot_id':dot_id,'capabilities':[b.capability_id for b in bindings],
            'actions':{},  # Each Git capability is already a specific operation, with no action selector.
            'registered':True,'grant_created':False,'publication_supported':False}
        self.configurations.put(machine_id,{'kind':'git-worktrees','workspace_id':workspace_id,
            'workspace_root':str(root),'agent_id':agent_id,'dot_id':dot_id})
        return dict(self._inventory[machine_id])

    async def _configure_workspace_files(self, workspace_id, workspace_root, agent_id):
        from sentra_executors.central_integration import CentralExecutorFactory
        from sentra_executors.workspace_files import (FILE_CAPABILITIES, WorkspaceFilesBinding,
                                                       declare_workspace_files_machine)
        from .workspace_paths import workspace_paths
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir() or not workspace_id or not agent_id:
            raise ValueError("trusted Canvas workspace and Dot required")
        machine_id = self._machine_id(workspace_id, agent_id, "workspace-files")
        if machine_id in self._inventory:
            return dict(self._inventory[machine_id])
        paths = workspace_paths(root, self.control.durable.root)
        from sentra_canvas.task_workspace import directory
        resolve_paths=lambda request:workspace_paths(directory(self.control,self.owner,request,root),self.control.durable.root)
        bindings = tuple(WorkspaceFilesBinding(capability_id=cap, paths=paths, actions=tuple(actions),resolve_paths=resolve_paths)
                         for cap, actions in FILE_CAPABILITIES.items())
        factory = CentralExecutorFactory(control=self.control, owner=self.owner, agent_id=agent_id)
        declaration = declare_workspace_files_machine(machine_id=machine_id,
            owner_principal_id=agent_id, bindings=bindings, policy=factory.policy)
        factory.register_execution(declaration)
        self._factories[machine_id] = factory
        self._inventory[machine_id] = {
            "machine_id": machine_id, "kind": "workspace-files",
            "workspace_id": workspace_id, "agent_id": agent_id,
            "capabilities": list(FILE_CAPABILITIES),
            "actions": {cap: list(actions) for cap, actions in FILE_CAPABILITIES.items()},
            "registered": True, "grant_created": False,
        }
        self.configurations.put(machine_id, {
            "kind": "workspace-files", "workspace_id": workspace_id,
            "workspace_root": str(root), "agent_id": agent_id})
        return dict(self._inventory[machine_id])

    def configure_browser(self, *, workspace_id: str, workspace_root: str,
                          agent_id: str, profiles: list[dict], headless: bool = True) -> dict:
        return self._call(self._configure_browser(workspace_id, workspace_root, agent_id,
                                                  profiles, headless))

    async def _configure_browser(self, workspace_id, workspace_root, agent_id, profiles, headless):
        from sentra_executors.central_integration import CentralExecutorFactory
        from sentra_executors.playwright_browser import (
            NetworkProfile, PlaywrightBrowserBinding, PlaywrightBrowserBackend,
            declare_playwright_browser_machine,
        )
        from sentra_executors.rpa import dependency_versions
        from .workspace_paths import workspace_paths
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 8 or type(headless) is not bool:
            raise ValueError("explicit bounded browser profiles required")
        network_profiles = []
        for profile in profiles:
            if not isinstance(profile, dict) or set(profile) - {
                "name", "mode", "allowed_origins", "methods", "resource_types", "max_requests", "max_redirects", "max_response_bytes"
            }:
                raise ValueError("unsupported browser profile field")
            values = dict(profile)
            for key in ("allowed_origins", "methods", "resource_types"):
                if key in values:
                    if not isinstance(values[key], list) or any(not isinstance(x, str) for x in values[key]):
                        raise ValueError("invalid browser profile list")
                    values[key] = tuple(values[key])
            network_profiles.append(NetworkProfile(**values))
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir() or not workspace_id or not agent_id:
            raise ValueError("trusted Canvas workspace/agent required")
        machine_id = self._machine_id(workspace_id, agent_id, "browser")
        # Network policy is immutable for the lifetime of registered contexts.
        # Reconfiguration requires explicit closure before registering anew.
        if machine_id in self._inventory:
            raise ValueError("browser already registered; close owned sessions before reconfiguration")
        factory = CentralExecutorFactory(control=self.control, owner=self.owner, agent_id=agent_id)
        binding = PlaywrightBrowserBinding("browser:operate", tuple(network_profiles),
            artifact_paths=workspace_paths(root,self.control.durable.root), headless=headless)
        declaration = declare_playwright_browser_machine(machine_id=machine_id,
            owner_principal_id=agent_id, bindings=(binding,), policy=factory.policy,
            backend=PlaywrightBrowserBackend())
        factory.register_execution(declaration)
        self._factories[machine_id] = factory
        self._inventory[machine_id] = {
            "machine_id": machine_id, "kind": "browser", "workspace_id": workspace_id,
            "agent_id": agent_id, "capabilities": [binding.capability_id],
            "actions": {binding.capability_id: list(binding.actions)},
            "profiles": [asdict(p) for p in network_profiles],
            "dependencies": dependency_versions(), "registered": True,
            "grant_created": False,
        }
        self.configurations.put(machine_id, {"kind":"browser","workspace_id":workspace_id,
            "workspace_root":str(root),"agent_id":agent_id,"profiles":[asdict(p) for p in network_profiles],
            "headless":headless})
        return dict(self._inventory[machine_id])

    def configure_openhands(self,*,workspace_id,workspace_root,agent_id,provider_config):
        async def configure():
            from .interop_machine import OpenHandsMachine,OPENHANDS_CAPABILITIES
            root=Path(workspace_root).resolve(strict=True)
            if not root.is_dir() or not isinstance(provider_config,dict):raise ValueError("explicit OpenHands workspace/server configuration required")
            machine_id=self._machine_id(workspace_id,agent_id,"openhands")
            if machine_id in self._inventory:raise ValueError("OpenHands machine configuration is immutable")
            config=dict(provider_config)
            if config.get("enabled") is not True:raise ValueError("OpenHands provider must be explicitly enabled")
            factory=OpenHandsMachine(self.control,owner=self.owner,agent_id=agent_id,machine_id=machine_id,configuration=config)
            self._factories[machine_id]=factory
            self._inventory[machine_id]={"machine_id":machine_id,"kind":"openhands","workspace_id":workspace_id,
                "agent_id":agent_id,"capabilities":list(OPENHANDS_CAPABILITIES),
                "actions":{cap:[cap.split(":",1)[1]] for cap in OPENHANDS_CAPABILITIES},
                "registered":True,"grant_created":False,"server":factory.config.api_url,
                "provider_id":factory.config.provider_id,"remote_workspace":factory.config.remote_workspace}
            self.configurations.put(machine_id,{"kind":"openhands","workspace_id":workspace_id,
                "workspace_root":str(root),"agent_id":agent_id,"provider_config":config})
            return dict(self._inventory[machine_id])
        return self._call(configure())

    def configure_interop(self, *, workspace_id, workspace_root, agent_id, kind, provider_config):
        async def configure():
            from sentra_interop.provider_machine import InteropProviderMachine
            if kind not in {"acp", "a2a", "mcp", "channels", "acp_registry"} or not isinstance(provider_config, dict) or provider_config.get("enabled") is not True:
                raise ValueError("explicit enabled interop provider configuration required")
            root = Path(workspace_root).resolve(strict=True)
            if not root.is_dir() or not workspace_id or not agent_id:
                raise ValueError("trusted workspace and agent required")
            machine_id = self._machine_id(workspace_id, agent_id, kind)
            if machine_id in self._inventory:
                raise ValueError("interop machine configuration is immutable")
            configured = json.loads(json.dumps(provider_config, allow_nan=False))
            common = dict(owner=self.owner, agent_id=agent_id, machine_id=machine_id, workspace_root=str(root))
            if kind == "channels":
                from sentra_interop.channel_machine import ChannelProviderMachine
                factory = ChannelProviderMachine(self.control, configuration={k:v for k,v in configured.items() if k != "enabled"}, **common)
            elif kind == "acp_registry":
                from sentra_interop.registry_machine import RegistryProviderMachine
                factory = RegistryProviderMachine(self.control, configuration=configured, **common)
            else:
                factory = InteropProviderMachine(self.control, kind=kind, configuration=configured, **common)
            inventory = {**factory.catalog(), "machine_id": machine_id, "workspace_id": workspace_id, "agent_id": agent_id}
            self.configurations.put(machine_id, {"kind": kind, "workspace_id": workspace_id,
                "workspace_root": str(root), "agent_id": agent_id, "provider_config": configured})
            self._factories[machine_id] = factory
            self._inventory[machine_id] = inventory
            return dict(inventory)
        return self._call(configure())

    def configure_executor(self, *, workspace_id, workspace_root, agent_id, kind, provider_config):
        from sentra_executors.integral import configure_executor
        return configure_executor(self, workspace_id=workspace_id, workspace_root=workspace_root,
                                  agent_id=agent_id, kind=kind, provider_config=provider_config)

    def application_action(self, *, workspace_id, work_item_id, machine_id, capability_id,
                           operation_id, request_key, command, selector_key, text=None):
        from sentra_executors.ufo_actions import UFOApplicationActions
        return self._call(UFOApplicationActions(self._dispatch).execute(workspace_id=workspace_id,
            work_item_id=work_item_id, machine_id=machine_id, capability_id=capability_id,
            operation_id=operation_id, request_key=request_key, command=command,
            selector_key=selector_key, text=text))

    def input_status(self, *, workspace_id, machine_id, work_item_id=None, capability_id=None):
        async def status():
            from sentra_executors.input_control import InputControl
            config = self._inventory.get(machine_id)
            factory = self._factories.get(machine_id)
            if config is None or config["workspace_id"] != workspace_id:
                raise AuthorizationRequired("machine outside workspace")
            resource = getattr(factory, "_input_resources", {}).get(machine_id)
            if not resource:
                raise ValueError("machine does not expose human/agent input control")
            value = InputControl(self.control, owner=self.owner).status(resource_id=resource, workspace_id=workspace_id)
            value.pop("resource_id", None)
            value.pop("principal_id", None)
            value["ttl_remaining_seconds"] = max(0, int(value.get("expires_at", 0) - time.time()))
            value["grant_status"] = "unknown"
            if work_item_id and capability_id:
                item = self.control.work_item_info(work_item_id, self.owner)
                if (item.get("metadata", {}).get("workspace_id") != workspace_id or item.get("metadata", {}).get("machine_id") != machine_id
                        or item.get("assignee_agent_id") != config["agent_id"] or capability_id not in config["capabilities"]):
                    value["grant_status"] = "denied"
                else:
                    policy = BoundWorkItemPolicy(owner=self.owner, principal_type="agent",
                        authorization=self.control.authorization, governance=self.control.governance)
                    probe = OperationRequest("op-input-status", config["agent_id"], machine_id, capability_id, work_item_id, "input-status", {})
                    value["grant_status"] = "granted" if policy(probe).allowed is True else "denied"
            return value
        return self._call(status(), timeout=15)

    def input_handoff(self, *, workspace_id, machine_id, holder, expected_epoch,
                      ttl_seconds=60, work_item_id=None, capability_id=None, operation_id=None, arguments=None, request_key=None,
                      only_if_available=False, client_id=''):
        async def handoff():
            from sentra_executors.input_control import InputControl
            config = self._inventory.get(machine_id)
            factory = self._factories.get(machine_id)
            if config is None or config["workspace_id"] != workspace_id:
                raise AuthorizationRequired("machine outside workspace")
            resource = getattr(factory, "_input_resources", {}).get(machine_id)
            if not resource:
                raise ValueError("machine does not expose human/agent input control")
            request = None
            if holder == "agent":
                item = self.control.work_item_info(work_item_id, self.owner)
                if (item.get("metadata", {}).get("workspace_id") != workspace_id
                        or item.get("metadata", {}).get("machine_id") != machine_id
                        or item.get("assignee_agent_id") != config["agent_id"]):
                    raise AuthorizationRequired("input WorkItem outside machine/workspace")
                request = factory.dispatch_request(run_id=item["run_id"], work_item_id=work_item_id,
                    machine_id=machine_id, capability_id=capability_id, operation_id=operation_id,
                    arguments=arguments or {}, idempotency_key=request_key)
            return InputControl(self.control, owner=self.owner).handoff(resource_id=resource, workspace_id=workspace_id,
                machine_id=machine_id, holder=holder, expected_epoch=expected_epoch, request_key=request_key,
                ttl_seconds=ttl_seconds, request=request, only_if_available=only_if_available,client_id=client_id)
        return self._call(handoff(), timeout=15)

    def dispatch_human(self, *, workspace_id, work_item_id, machine_id, capability_id,
                       operation_id, arguments, expected_epoch, idempotency_key=None, client_id=''):
        async def dispatch():
            from sentra_executors.input_control import human_input_scope
            config = self._inventory.get(machine_id)
            factory = self._factories.get(machine_id)
            if config is None or config["workspace_id"] != workspace_id:
                raise AuthorizationRequired("human input machine outside workspace")
            resource = getattr(factory, "_input_resources", {}).get(machine_id)
            if not resource:
                raise ValueError("machine has no human input resource")
            if not isinstance(arguments, dict) or set(arguments) & {"human", "owner", "principal", "principal_id", "resource_id"}:
                raise ValueError("human input authority is server-derived")
            with human_input_scope(self.control, owner=self.owner, workspace_id=workspace_id,
                                   machine_id=machine_id, resource_id=resource, expected_epoch=expected_epoch,client_id=client_id):
                return await self._dispatch(workspace_id, work_item_id, machine_id, capability_id,
                                            operation_id, arguments, idempotency_key)
        return self._call(dispatch())

    def receive_interop_callback(self, machine_id, raw_body, headers):
        async def receive():
            config = self._inventory.get(machine_id)
            factory = self._factories.get(machine_id)
            if config is None or config.get("kind") != "a2a" or not callable(getattr(factory, "receive_callback", None)):
                raise ValueError("A2A callback provider is not configured")
            if not isinstance(raw_body, bytes) or len(raw_body) > 2_000_000 or not isinstance(headers, dict):
                raise ValueError("bounded raw callback request required")
            return factory.receive_callback(raw_body=raw_body, headers=headers)
        return self._call(receive(), timeout=30)

    def attach_runtime_adapters(self, *, runtime_host_resolver=None, canvas=None):
        """Attach trusted host dependencies before restore; no TaskRuntime fork."""
        if runtime_host_resolver is not None and not callable(runtime_host_resolver):
            raise ValueError("trusted runtime host resolver required")
        if canvas is not None and self.owner != "canvas:" + canvas.store.principal:
            raise PermissionError("Canvas adapter belongs to another principal")
        self._runtime_host_resolver = runtime_host_resolver
        self._canvas_adapter = canvas

    def configure_runtime(self, *, workspace_id, workspace_root, agent_id, provider, binding_id, runtime_host=None):
        if runtime_host is None:
            if not callable(self._runtime_host_resolver):
                raise RuntimeError("subordinate runtime provider host is not configured")
            runtime_host = self._runtime_host_resolver(workspace_id)
        if getattr(runtime_host,"control",None) is not self.control or getattr(runtime_host,"owner",None) != self.owner:
            raise PermissionError("runtime provider must share the exact Control Plane and owner")
        async def configure():
            from sentra_interop.workflow_runtime_machine import configure_runtime_machine
            # An async SDK loader primes the sync machine constructor's cache
            # on this owned loop. A sync provider must already be preconnected.
            loader = getattr(runtime_host,"restore_async",None)
            if callable(loader):
                await loader(binding_id)
            return configure_runtime_machine(self, workspace_id=workspace_id,workspace_root=workspace_root,
                agent_id=agent_id,provider=provider,binding_id=binding_id,runtime_host=runtime_host)
        return self._call(configure())

    def configure_computer(self, *, workspace_id, workspace_root, agent_id):
        async def configure():
            from sentra_executors.local_computer import configure_computer
            return configure_computer(self, workspace_id=workspace_id, workspace_root=workspace_root, agent_id=agent_id)
        return self._call(configure())

    def configure_terminal(self, *, workspace_id, workspace_root, agent_id, canvas=None):
        canvas = canvas or self._canvas_adapter
        if canvas is None or self.owner != "canvas:" + canvas.store.principal:
            raise RuntimeError("fenced terminal Canvas adapter is not configured for this owner")
        async def configure():
            from sentra_interop.workflow_runtime_machine import configure_terminal_machine
            return configure_terminal_machine(self,workspace_id=workspace_id,workspace_root=workspace_root,
                agent_id=agent_id,canvas_principal=canvas.store.principal,canvas=canvas)
        return self._call(configure())

    def configure_workflow(self,*,workspace_id,workspace_root,agent_id,definitions):
        async def configure():
            from .workflow_machine import DocumentWorkflowMachine,WORKFLOW_CAPABILITIES
            root=Path(workspace_root).resolve(strict=True)
            machine_id=self._machine_id(workspace_id,agent_id,"workflow")
            if not root.is_dir() or machine_id in self._inventory:
                raise ValueError("workflow machine already configured or workspace missing")
            configured=json.loads(json.dumps(definitions,allow_nan=False))
            factory=DocumentWorkflowMachine(self.control,owner=self.owner,agent_id=agent_id,
                machine_id=machine_id,workspace_root=root,definitions=configured)
            inventory={"machine_id":machine_id,"kind":"workflow","workspace_id":workspace_id,
                "agent_id":agent_id,"capabilities":list(WORKFLOW_CAPABILITIES),
                "actions":{cap:[cap.split(":",1)[1]] for cap in WORKFLOW_CAPABILITIES},
                "definitions":factory.catalog(),"registered":True,"grant_created":False,
                "scheduler":"central-host","validation_status":"pending"}
            self.configurations.put(machine_id,{"kind":"workflow","workspace_id":workspace_id,
                "workspace_root":str(root),"agent_id":agent_id,"definitions":configured})
            self._factories[machine_id]=factory
            self._inventory[machine_id]=inventory
            return dict(inventory)
        return self._call(configure())

    def configure_session(self,*,workspace_id,workspace_root,agent_id,kind,provider_config):
        async def configure():
            from sentra_executors.central_integration import CentralExecutorFactory
            from sentra_executors.identity_sessions import SessionJournal
            from sentra_executors.rpa import AuthorizedPaths
            if kind not in {"daytona","guacamole","rustdesk"} or not isinstance(provider_config,dict):
                raise ValueError("explicit supported remote session configuration required")
            root=Path(workspace_root).resolve(strict=True)
            machine_id=self._machine_id(workspace_id,agent_id,kind)
            if not root.is_dir() or machine_id in self._inventory:raise ValueError("remote machine already configured or workspace missing")
            config=json.loads(json.dumps(provider_config,allow_nan=False))
            if config.pop("enabled",None) is not True:raise ValueError("remote session must be explicitly enabled")
            private=self.control.durable.root/"provider-state"/machine_id
            private.mkdir(parents=True,exist_ok=True)
            journal=SessionJournal(str(private/"sessions.sqlite3"),AuthorizedPaths((str(private),),(str(private),)))
            from .workspace_paths import workspace_paths
            paths=workspace_paths(root,self.control.durable.root)
            persisted=json.loads(json.dumps(provider_config,allow_nan=False))
            factory=CentralExecutorFactory(control=self.control,owner=self.owner,agent_id=agent_id)
            def secret(ref,purpose):
                self.control.secret_info(ref,self.owner)
                self.control.bind_secret(ref,self.owner,target_type="agent",target_id=agent_id,purpose=purpose)
                return lambda:self.control.governance.resolve_secret_for_runtime(ref,self.owner,
                    actor_type="agent",actor_id=agent_id,purpose=purpose)
            if kind=="daytona":
                from sentra_executors.daytona_sessions import (DaytonaConnectionConfig,DaytonaSessionBinding,
                                                               declare_daytona_session_machine)
                connection=dict(config.pop("connection"))
                credential_ref=connection.pop("credential_ref")
                connection["credential"]=secret(credential_ref,"daytona:"+machine_id)
                connection["allowed_sdk_versions"]=tuple(connection["allowed_sdk_versions"])
                for field in ("existing_sandbox_ids","allowed_commands","actions"):
                    if field in config:config[field]=tuple(config[field])
                if set(config)&{"capability_id","paths","connection"}:raise ValueError("host owns remote capability and paths")
                binding=DaytonaSessionBinding(capability_id="daytona:session",paths=paths,
                    connection=DaytonaConnectionConfig(**connection),**config)
                declaration=declare_daytona_session_machine(machine_id=machine_id,owner_principal_id=agent_id,
                    bindings=(binding,),journal=journal,policy=factory.policy)
            elif kind=="guacamole":
                from sentra_executors.remote_guacamole import GuacamoleBinding,declare_guacamole_machine
                refs=config.pop("secret_refs",{})
                if not isinstance(refs,dict) or set(refs)-{"password","private-key","passphrase","username"}:
                    raise ValueError("invalid Guacamole credential references")
                resolvers={name:secret(ref,"guacamole:"+machine_id+":"+name) for name,ref in refs.items()}
                if set(config)&{"capability_id","paths","secrets"}:raise ValueError("host owns Guacamole capability/paths/credentials")
                parameters=config.get("parameters")
                if not isinstance(parameters,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in parameters.items()):
                    raise ValueError("configured Guacamole plugin parameters required")
                config["parameters"]=tuple(sorted(parameters.items()))
                for field in ("allowed_input","supported_versions","actions","record_input"):
                    if field in config:config[field]=tuple(config[field])
                capability="remote:control" if config.get("allowed_input") or config.get("clipboard_enabled") and "clipboard.write" in config.get("actions", ()) else "remote:view"
                binding=GuacamoleBinding(capability_id=capability,paths=paths,
                    secrets=(lambda:{name:resolve() for name,resolve in resolvers.items()}) if resolvers else None,**config)
                declaration=declare_guacamole_machine(machine_id=machine_id,owner_principal_id=agent_id,
                    bindings=(binding,),journal=journal,policy=factory.policy)
            else:
                from sentra_executors.remote_rustdesk import RustDeskPeerBinding,declare_rustdesk_machine
                from .native_bundle import pinned_rustdesk_bundle
                if set(config)&{"capability_id","paths","runtime_root","host_runtime_paths","manifest_paths"}:
                    raise ValueError("host owns native runtime/build/output path authority")
                runtime = config.pop('runtime', None)
                native_fields = {'executable', 'executable_sha256', 'build_manifest', 'source_revision'}
                if runtime is not None and runtime != 'installed':
                    raise ValueError('unknown RustDesk runtime selection')
                if runtime == 'installed' and native_fields & set(config):
                    raise ValueError('installed RustDesk selection cannot override native build pins')
                if runtime == 'installed' or not native_fields & set(config):
                    from sentra_remote.runtime_payload import installed_rustdesk_configuration
                    selected = await asyncio.to_thread(installed_rustdesk_configuration)
                    config.update(selected); persisted.pop('runtime', None); persisted.update(selected)
                source_revision=config.pop("source_revision")
                builds=private/"builds";builds.mkdir(mode=0o700,exist_ok=True)
                native=await asyncio.to_thread(pinned_rustdesk_bundle,executable=config["executable"],
                    executable_sha256=config["executable_sha256"],build_manifest=config["build_manifest"],
                    source_revision=source_revision,private_root=builds)
                config["executable"]=native["executable"];config["build_manifest"]=native["build_manifest"]
                persisted.update(executable=native["executable"],build_manifest=native["build_manifest"])
                runtime=private/"native-runtime";runtime.mkdir(mode=0o700,exist_ok=True)
                for field in ("actions", "allowed_input", "allowed_keycodes"):
                    if field in config:config[field]=tuple(config[field])
                login_ref = config.pop("login_credential_ref", None)
                if "login_credential" in config:
                    raise ValueError("RustDesk login credential must reference the central vault")
                if login_ref:
                    config["login_credential"] = secret(login_ref, "rustdesk:" + machine_id + ":login")
                binding=RustDeskPeerBinding(capability_id="rustdesk:session",paths=paths,runtime_root=str(runtime),
                    host_runtime_paths=AuthorizedPaths((str(runtime),),(str(runtime),)),
                    manifest_paths=AuthorizedPaths((native["bundle_root"],),()),**config)
                declaration=declare_rustdesk_machine(machine_id=machine_id,owner_principal_id=agent_id,
                    bindings=(binding,),journal=journal,policy=factory.policy)
            factory.register_execution(declaration)
            inventory={"machine_id":machine_id,"kind":kind,"workspace_id":workspace_id,
                "agent_id":agent_id,"capabilities":[binding.capability_id],"actions":{binding.capability_id:list(binding.actions)},
                "registered":True,"grant_created":False,"transport_ready":"unverified"}
            if kind=="rustdesk":inventory.update(peer_alias=binding.peer_alias,source_revision=native["source_revision"],
                native_bundle_sha256=native["bundle_sha256"],native_execution_verified=False,
                desktop_login_verified=False,control_api_available=False)
            self.configurations.put(machine_id,{"kind":kind,"workspace_id":workspace_id,"workspace_root":str(root),
                "agent_id":agent_id,"provider_config":persisted})
            self._factories[machine_id]=factory
            self._inventory[machine_id]=inventory
            return dict(inventory)
        return self._call(configure())

    def attach_configuration_handler(self, kind, handler):
        """Trusted root composition slot; configuration never grants execution."""
        if kind != "code-mode" or not callable(handler):
            raise ValueError("trusted code-mode configuration handler required")
        self._configuration_handlers[kind] = handler

    def configure_code(self, *, workspace_id, workspace_root, agent_id, provider_config):
        handler = self._configuration_handlers.get("code-mode")
        if handler is None:
            raise RuntimeError("code-mode Canvas adapter is not configured")
        return handler(self, workspace_id=workspace_id, workspace_root=workspace_root,
                       agent_id=agent_id, provider_config=provider_config)

    def restore(self, validate_scope):
        """Rebuild dispatch bindings only after the host checks current scope.

        No grant, WorkItem, browser context or remote session is created here.
        Configured roots cannot follow a workspace that has moved elsewhere.
        """
        if not callable(validate_scope):
            raise ValueError("trusted scope validator required")
        from sentra_executors.integral import EXECUTOR_KINDS
        for entry in self.configurations.entries():
            config = entry["configuration"]
            try:
                validate_scope(config)
                identity_kind = config["kind"]
                if identity_kind in {"runtime-temporal","runtime-langgraph"}:
                    identity_kind += "-" + config["binding_id"][-8:]
                if entry["machine_id"] != self._machine_id(config["workspace_id"],config["agent_id"],identity_kind):
                    raise ValueError("machine identity changed")
                if config["kind"] in {"runtime-temporal","runtime-langgraph"}:
                    self.configure_runtime(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],provider=config["provider"],binding_id=config["binding_id"])
                elif config["kind"] == "computer-local":
                    self.configure_computer(workspace_id=config["workspace_id"], workspace_root=config["workspace_root"], agent_id=config["agent_id"])
                elif config["kind"] == "virtualbox_vm":
                    from sentra_canvas.shell_dot_vm import configure_virtualbox_machine
                    configure_virtualbox_machine(self, workspace_id=config['workspace_id'], workspace_root=config['workspace_root'],
                        agent_id=config['agent_id'], root_dot_id=config['root_dot_id'])
                elif config["kind"] == "workspace-files":
                    self.configure_workspace_files(workspace_id=config["workspace_id"],
                        workspace_root=config["workspace_root"], agent_id=config["agent_id"])
                elif config['kind']=='git-worktrees':
                    self.configure_worktrees(workspace_id=config['workspace_id'],workspace_root=config['workspace_root'],
                        agent_id=config['agent_id'],dot_id=config['dot_id'])
                elif config["kind"] == "terminal":
                    if self.owner != "canvas:" + config["canvas_principal"]:
                        raise PermissionError("terminal restore principal changed")
                    self.configure_terminal(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],agent_id=config["agent_id"])
                elif config["kind"] == "code-mode":
                    self.configure_code(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],provider_config=config["provider_config"])
                elif config["kind"] == "documents":
                    self.configure_documents(**{key:config[key] for key in ("workspace_id","workspace_root","agent_id")},
                        recalculation_backends=config.get("recalculation_backends",[]),ocr_backends=config.get("ocr_backends",[]))
                elif config["kind"] == "browser":
                    profiles=[dict(p) for p in config["profiles"]]
                    for profile in profiles:
                        for key in ("allowed_origins","methods","resource_types"):
                            profile[key]=list(profile[key])
                    self.configure_browser(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],profiles=profiles,headless=config["headless"])
                elif config["kind"] == "openhands":
                    self.configure_openhands(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],provider_config=config["provider_config"])
                elif config["kind"] in {"acp", "a2a", "mcp", "channels", "acp_registry"}:
                    self.configure_interop(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],kind=config["kind"],provider_config=config["provider_config"])
                elif config["kind"] in EXECUTOR_KINDS:
                    self.configure_executor(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],kind=config["kind"],provider_config=config["provider_config"])
                elif config["kind"] == "workflow":
                    self.configure_workflow(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],definitions=config["definitions"])
                elif config["kind"] in {"daytona","guacamole","rustdesk"}:
                    self.configure_session(workspace_id=config["workspace_id"],workspace_root=config["workspace_root"],
                        agent_id=config["agent_id"],kind=config["kind"],provider_config=config["provider_config"])
                else:
                    raise ValueError("unsupported persisted machine")
            except (ValueError, KeyError, FileNotFoundError, PermissionError, RuntimeError) as exc:
                self.restore_errors.append({"machine_id":entry["machine_id"],"error":type(exc).__name__})

    def inventory(self, workspace_id: str) -> list[dict]:
        async def get():
            return [dict(item) for item in self._inventory.values()
                    if item["workspace_id"] == workspace_id]
        return self._call(get(), timeout=10)

    def task_catalog(self, *, workspace_id, agent_ids=None, conversation_id=None):
        async def get():
            rows=self.control.list_work_items(self.owner,states=["RUNNING"],limit=1000)["items"]
            result=[]
            for item in rows:
                if item.get("metadata",{}).get("workspace_id")!=workspace_id:continue
                for ident,config in self._inventory.items():
                    agent=config["agent_id"]
                    if (config["workspace_id"]!=workspace_id or item.get("assignee_agent_id")!=agent
                            or item.get("metadata",{}).get("machine_id")!=ident
                            or agent_ids is not None and agent not in agent_ids):continue
                    scoped = config['kind'] in {'workspace-files', 'terminal', 'computer-local', 'virtualbox_vm','git-worktrees'}
                    if conversation_id is not None and scoped and item.get('metadata', {}).get('conversation_id') != conversation_id:
                        continue
                    factory=self._factories[ident];caps=[]
                    for cap in sorted(set(item["required_capabilities"])&set(config["capabilities"])):
                        request=OperationRequest("op-discovery",agent,ident,cap,item["work_item_id"],"discovery",{})
                        if factory.policy(request).allowed is True:caps.append(cap)
                    if caps and self.control.durable.run_status(item["run_id"],self.owner,include_details=False)["state"]=="RUNNING":
                        result.append({"work_item_id":item["work_item_id"],"machine_id":ident,
                            "agent_id":agent,"capabilities":caps,"objective":item["objective"],
                            **({"conversation_id": item.get("metadata", {}).get("conversation_id")}
                               if scoped else {})})
            return result
        return self._call(get(),timeout=15)

    def dispatch(self, *, workspace_id: str, work_item_id: str, machine_id: str,
                 capability_id: str, operation_id: str, arguments: dict,
                 idempotency_key: str | None = None, effect_authorize=None) -> dict:
        return self._call(self._dispatch(workspace_id, work_item_id, machine_id,
                                         capability_id, operation_id, arguments, idempotency_key, effect_authorize))

    async def _dispatch(self, workspace_id, work_item_id, machine_id, cap, oid, arguments, key,
                        effect_authorize=None):
        started=time.monotonic()
        item = self.control.work_item_info(work_item_id, self.owner)
        config = self._inventory.get(machine_id)
        if (config is None or config["workspace_id"] != workspace_id
                or item.get("metadata", {}).get("workspace_id") != workspace_id
                or item.get("metadata", {}).get("machine_id") != machine_id
                or item.get("assignee_agent_id") != config["agent_id"]):
            raise AuthorizationRequired("machine/WorkItem not bound to this Canvas workspace")
        factory = self._factories[machine_id]
        request = factory.dispatch_request(run_id=item["run_id"], work_item_id=work_item_id,
            machine_id=machine_id, capability_id=cap, operation_id=oid,
            arguments=arguments, idempotency_key=key)
        if effect_authorize is None:
            result = await factory.submit(run_id=item["run_id"], request=request)
        else:
            from sentra_executors.central_integration import CentralExecutorFactory
            if not isinstance(factory, CentralExecutorFactory):
                raise AuthorizationRequired("machine does not support additional host effect authority")
            result = await factory.submit(run_id=item["run_id"], request=request, effect_authorize=effect_authorize)
        if self._telemetry is not None:
            try:
                from .otlp_sink import SafeTelemetryEvent
                self._telemetry.enqueue(SafeTelemetryEvent("sentra.machine",result.state,oid,
                    elapsed_ms=min(86400000,max(0,int((time.monotonic()-started)*1000)))))
            except Exception:self._diagnostic_errors+=1
        if result.state in {"SUCCEEDED","FAILED"}:
            try:
                from .experience import ExperienceMemory
                if self._experiences is None:
                    self._experiences=ExperienceMemory(self.control,owner=self.owner)
                config=next(entry["configuration"] for entry in self.configurations.entries()
                            if entry["machine_id"]==machine_id)
                self._experiences.record(request,workspace_id=workspace_id,configuration=config)
            except Exception as exc:
                # Experience indexing cannot turn a committed effect into a retry.
                self.memory_errors=(self.memory_errors+[{"operation_id":oid,
                                                       "error":type(exc).__name__}])[-20:]
        return asdict(result)

    def experiences(self, *, workspace_id, work_item_id, machine_id, query, limit=5):
        async def find():
            from .experience import ExperienceMemory
            item=self.control.work_item_info(work_item_id,self.owner)
            config=self._inventory.get(machine_id)
            if (config is None or config["workspace_id"]!=workspace_id
                    or item.get("metadata",{}).get("workspace_id")!=workspace_id
                    or item.get("metadata",{}).get("machine_id")!=machine_id
                    or item.get("assignee_agent_id")!=config["agent_id"] or item["state"]!="RUNNING"):
                raise AuthorizationRequired("experience query outside assigned machine task")
            factory=self._factories[machine_id]
            caps=set(item["required_capabilities"])&set(config["capabilities"])
            # Discovery of knowledge does not create execution permissions.
            knowledge_policy=BoundWorkItemPolicy(owner=self.owner,principal_type="agent",
                authorization=self.control.authorization,governance=self.control.governance,
                trusted_context=lambda _: {"actual_cost":0.0})
            if not any(knowledge_policy(OperationRequest("op-memory-query",config["agent_id"],machine_id,cap,
                work_item_id,"memory-query",{})).allowed is True for cap in caps):
                raise AuthorizationRequired("experience query requires a live task grant")
            stored=next(entry["configuration"] for entry in self.configurations.entries()
                        if entry["machine_id"]==machine_id)
            if self._experiences is None:self._experiences=ExperienceMemory(self.control,owner=self.owner)
            return {"experiences":self._experiences.retrieve(workspace_id=workspace_id,
                principal_id=config["agent_id"],configuration=stored,query=query,limit=limit),"knowledge_only":True}
        return self._call(find(),timeout=15)

    def observe(self, *, workspace_id: str, operation_id: str, as_owner: bool = False) -> dict:
        """Read persisted evidence after restart without creating any new session."""
        async def recover():
            row = self.control.durable.operation_status(operation_id, self.owner)
            progress = row.get("progress") or {}
            item = self.control.work_item_info(progress["work_item_id"], self.owner)
            if (item["run_id"] != row["run_id"]
                    or item.get("metadata", {}).get("workspace_id") != workspace_id):
                raise AuthorizationRequired("operation belongs to another Canvas workspace")
            request = OperationRequest(operation_id, progress["principal_id"],
                progress["machine_id"], progress["capability_id"], progress["work_item_id"],
                row["idempotency_key"], {})
            policy = BoundWorkItemPolicy(owner=self.owner, principal_type="agent",
                authorization=self.control.authorization, governance=self.control.governance)
            if not as_owner and policy(request).allowed is not True:
                raise AuthorizationRequired("persisted operation status is not authorized")
            authority = CentralDurableIntentAuthority(self.control.durable)
            receipt = authority.receipt_for_operation(operation_id, self.owner)
            result = authority.result_for_receipt(receipt)
            value=asdict(result) if result is not None else {
                "operation_id": operation_id, "state": "UNCERTAIN",
                "evidence": {}, "error": "provider reconciliation required",
            }
            late=authority.late_return_for_receipt(receipt) if value["state"]=="UNCERTAIN" else None
            if late is not None:value["late_return"]=late
            return value
        return self._call(recover(), timeout=10)

    def close(self):
        if self._closed:
            return
        async def cleanup():
            from .effect_boundary import _ResourceLock, ResourceEffectBusy
            for machine_id in self._factories:
                probe = _ResourceLock(self.control.durable.root / "effect-locks", machine_id)
                try:
                    probe.acquire(0)
                except ResourceEffectBusy as exc:
                    raise RuntimeError("physical workers have not stopped; machine host retained") from exc
                else:
                    probe.release()
            seen = set()
            for factory in self._factories.values():
                direct_shutdown=getattr(factory,"shutdown",None)
                if callable(direct_shutdown):await direct_shutdown()
                for declaration in getattr(factory,'_declarations',{}).values():
                    backend = getattr(declaration.adapter, "backend", None)
                    if backend is not None and id(backend) not in seen:
                        seen.add(id(backend))
                        shutdown = getattr(backend, "shutdown", None)
                        if callable(shutdown):
                            await asyncio.to_thread(shutdown)
        self._call(cleanup(), timeout=10)
        if self._telemetry:self._telemetry.close()
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
