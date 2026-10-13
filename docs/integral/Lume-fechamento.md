# Lume — fechamento Pulso, interop e canais

Implementação em andamento em 11/10/2026. Sem teste, build, install, lint,
benchmark ou QA. Ownership e fontes anteriores preservados; PID47408 intocado.

## Contratos enviados cedo

Nexo mantém MachineHost/CP/runtime central. Os helpers de Lume preservam:
`configure_runtime_machine(machine_host, *, workspace_id, workspace_root,
agent_id, provider, binding_id, runtime_host)` e
`configure_terminal_machine(machine_host, *, workspace_id, workspace_root,
agent_id, canvas_principal, canvas)`.
`runtime_host.control is machine_host.control` é obrigatório.

O host expõe `await aconfigure(**configure_kwargs)` e
`await arestore(binding_id, *, secret_resolver=None)`. Clientes, workers e
checkpointers nascem e fecham no loop owned do MachineHost. Antes de construir
RuntimeProviderMachine, Nexo chama `await runtime_host.arestore(binding_id)`.
`restore(binding_id)` é somente lookup de binding já conectado no loop; não
usa asyncio.run nem abre cliente em outro loop. A criação assíncrona do helper
será publicada como `aconfigure_runtime_machine` sem remover a versão sync.

Root compõe resolvers síncronos `(action, ctx, params) -> dict` na fachada;
o resolver usa MachineHost.dispatch para construir **e executar** a Operation.
`action="execute"` recebe parâmetros públicos, nunca Grant/owner/Run fornecidos
pelo renderer. Resultados incluem `operation_id`, estado executado e receipt.
Observações usam `target_operation_id`; não aceitam operation_id novo do cliente.
Workflow: `intent_kind, workflow_id, namespace?, definition_id?,
definition_version?, inputs?, signal_name?, signal_id?, payload?, value?,
step_id?, checkpoint_id?`. Runtime: `provider, operation, binding_id?,
workflow_id, occurrence, inputs?` (start), `name,payload` (signal), `values`
(resume), `resume?` (advance), `reason` (interrupt),
`new_occurrence,checkpoint_id` (fork). Terminal write: `terminal_id,data`.
Seleção confiável de machine/agente/WorkItem pertence ao root/MachineHost.

Projeções Pulso usam control.store quando control é fornecido, incluindo PG;
SQLite standalone permanece apenas para uso explícito sem authority hospedada.
Nenhuma falha PG abre banco local como fallback.

## Pendências de composição

- Nexo: await arestore no loop antes de ctor/factory síncrona; identidade runtime
  com sufixo binding_id[-8:] conforme wrapper já informado; shutdown do host.
- Root: resolvers executores de workflow/runtime/terminal/channel e webhook raw
  autenticado ingress-only; confirmar Operation e mesmo WorkItem antes de ack.
- Meridiano: rastrear cobertura por cláusula, sem considerar este relato QA.

Resultados por arquivo serão acrescentados após as implementações.

## Delta de contratos de composição (em andamento)

- Implementado `workflow_runtime_host.RuntimeProviderHost.aconfigure/arestore`.
  `restore` é lookup-only; submit usa await arestore quando preciso. Helper
  `workflow_runtime_machine.aconfigure_runtime_machine(machine_host, **configuration)`
  aguarda arestore e chama o helper sync existente. **Nexo deve usar este helper
  async no configure/restore ou await arestore antes do helper sync.**
- `workflow_shell_host.PulsoMachineResolver(machine_host, *, domain,
  machine_lookup, channel_bridge=None)`: domains workflow/runtime/terminal/channel.
  `machine_lookup(ctx, domain, params)` retorna `{machine_id,work_item_id}` por
  roteamento/configuração confiável do servidor. Resolver chama dispatch real
  e acrescenta HumanReceiptViews. IDs vêm de `server_operation_id(ctx, capability)`.
- `PulsoShellDispatch` aceita agora terminal_resolver/channel_resolver além dos
  anteriores. Workflow/runtime/terminal mutations exigem resultado central com
  operation_id e state; builder não é considerado execução. `channel_claim`
  executa workflow signal e confirm_dispatch; signal_payload é resolvido do inbox.
  `channel_ack` e `receipt_get` usam target_operation_id e resolvem WorkItem no CP.
- `workflow_nats_transport.NATSWorkflowTransport(provider, control, owner,
  signal_bridge, signal_name, reference_mapper=None)` usa NATSJetStreamProvider
  TLS/CA/name/SPKI/binary pins já existente, valida envelope/subject de referências,
  registra provenance e adia broker ACK até sinal exato SUCCEEDED. IO exige
  contexto central; handles perdidos aguardam redelivery sem repetir sinal.
- `activepieces_webhooks.ActivepiecesWebhookIngress(control, *, owner,
  schedule_bridge, secret_resolver)` tem configure/receive/process_admitted/disable.
  receive raw <=1MiB é ingress-only. Contrato externo: timestamp segundos,
  event ID e HMAC-SHA256 de `timestamp + '.' + raw_body`; headers configuráveis
  (defaults x-sentra-timestamp/x-sentra-event-id/x-sentra-signature, sha256=).
  Corpo `{events:[...]}`; process_admitted requer activepieces:trigger_ingest
  com events_sha256 exato, assinatura enable SUCCEEDED e projeto/Run central.

Factory options reais (host-only, JSON persistível, vault refs separados):
Temporal: address,namespace,task_queue,tls=true,worker_version,package_pins
com temporalio exato, provision_worker e definition_source {path,sha256},
worker_factory=build_worker. Factory fonte pinada retorna workflows/activities
e recebe MachineHost/control existentes. LangGraph: worker_version,package_pins
langgraph e langgraph-checkpoint,definition_source {path,sha256},
graph_factory=build_graph. Builder recebe checkpointer configurado,MachineHost,
control; compiled graph deve usar o saver recebido. Sem install/import de
catálogo externo ou opções com objetos graph não persistíveis.
