# Pulso — execução persistente e automações (entrega integral + expansão)

Papel: scheduling durável, Goal/Loop, NATS/Temporal/LangGraph subordinados,
Activepieces, workflows empresariais, terminal persistente e recibos humanos.
Modelo: OpenCode Muse Spark 1.3 Free, esforço high.
Data: 2026-10-11. Fase: implementação integral; validação liberada somente
pelo Codex principal ao final de todas as frentes (nenhum teste, build,
lint, benchmark ou QA executado aqui).

Expansão (tarefa `docs/integral/tasks/Pulso.md`, Meridiano 11/10/2026):
adapters de runtime Temporal/LangGraph reais subordinados, agenda
cron/timezone/DST/misfire/ocorrência única/nonoverlap/pausa/custos/outbox,
triggers/notificações Slack/Telegram/WhatsApp com Lume, GC de terminal por
handle, contrato de workflow/canal e dependências. Seções da expansão estão
marcadas [EXPANSÃO] abaixo.

## Requisitos cobertos (fontes lidas integralmente no pertinente)

- `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` (ownership Pulso),
  `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md` (contrato da rota),
  `docs/SENTRA_TERMINAIS_OPENCODE_2026-10-11.md` (papéis dos terminais),
  nota Maestri `todos-os-projetos-ja-estao-clo` (465 linhas).
- `docs/SENTRA_INCORPORACAO_WORKFLOW_ACTIVEPIECES_2026-10-11.md` (rodada 3:
  worker com checkpoints, pieces reais SDK/HTTP, triggers com admissão
  central), `docs/SENTRA_INCORPORACAO_WORKFLOWS_CANVAS_2026-10-09.md`,
  `docs/DURABLE_EXECUTION.md` (Runs/Operations idempotentes, UNCERTAIN sem
  replay), seções de Goal/Loop, terminal persistente, recibos e aprovações
  de `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`.

## Arquivos criados (domínio exclusivo Pulso)

Todos sob o padrão `sentra_interop/workflow*` / `activepieces*` (ownership
Pulso) mais testes exclusivos:

- `sentra_interop/workflow_nats.py` — `NATSWorkflowSignalBridge`: ingestão
  de eventos JetStream como claims de `workflow:signal` idempotentes por
  `event_key`, com construção do intent exato e marcação de admissão. O
  transporte (`pull_events`) é injetado pelo host a partir do consumer real
  de `sentra_runtime/nats_jetstream.py`; sem transporte configurado, `drain`
  falha explicitamente (`NATSTransportMissing`). Nenhum callback de
  execução: notificação é referência, não efeito.
- `sentra_interop/workflow_temporal.py` — `TemporalRetryPolicy`
  (classificação retryable/terminal, backoff limitado, max_attempts
  incluindo a primeira tentativa, expiração) e `TemporalUpdateLedger`
  (admitido vs concluído como projeção local de operation IDs). Sem
  servidor Temporal; UNCERTAIN nunca gera nova tentativa de efeito.
- `sentra_interop/workflow_langgraph.py` — `LangGraphCheckpointBridge`
  (linhagem de parent checkpoints, staging de pending writes, heartbeat
  real com idle timeout — sem heartbeat artificial) e
  `LangGraphNamespaceStore` (memória TTL com scan lexical de namespaces
  descendentes, sem embeddings) sobre o `WorkflowCheckpointStore` real.
  Sem runtime LangGraph.
- `sentra_interop/workflow_scheduling.py` — `RoutineWorkflowBinding`:
  vínculo rotina→workflow com aprovação do dono, intents exatos por
  ocorrência (`create`/`advance`/`resume`/`signal`) idempotentes por
  `occurrence_key`, sem executar efeitos.
- `sentra_interop/activepieces_scheduling.py` —
  `ActivepiecesScheduleBridge`: callback `schedule_handler` para o host
  injetar em `OwnedPieceSDKBackend` (associa schedule AP à rotina; o
  disparo real continua via `RoutineSchedulerService.tick`), ingestão de
  webhooks com `_dedupe_key` + admissão central injetada, e reconciliação
  lookup-only para replies perdidos. Falha explícita sem callbacks do host.
- `sentra_interop/workflow_shell.py` — `PulsoShellDispatch`: fachada de
  31 ações em mapa exato (sem prefix dispatch) para composição na rota
  `POST /api/shell/bridge` (composição permanece com o Codex):
  `schedule_list/get/create/enable/disable/pause/resume/fire`,
  `goal_status/set/open/advance/stop`, `workflow_intent/observe/output`,
  `runtime_intent/observe`, `terminal_list/read/write`, `receipt_get`,
  `channel_list/enable/renew/disable/revoke/send_intent/inbox/claim/ack`.
  Identidade canônica CP (`canvas._runtime().owner`) + principal separado
  (`store.principal`); params com seletores de identidade/autoridade são
  negados. Mutações reservam `(request_key, intent SHA, scope)` em PENDING
  antes de qualquer efeito: replay só com intent idêntico, PENDING/UNCERTAIN
  retornam `status: uncertain`. Runs/agentes/workspace derivados server-side
  (rotina→authority Run real; terminal→ledger; goal→Run do runtime).
  `workflow_intent`/`runtime_intent` constroem (nunca admitem); terminal
  write exige o fence/consentimento central e falha fechado fora dele.
- `tests/unit/test_pulso_workflow_adapters.py`,
  `tests/unit/test_pulso_scheduling.py`, `tests/unit/test_pulso_shell.py`
  — testes criados para execução futura (não executados nesta fase).

## Arquivos criados na expansão [EXPANSÃO]

- `sentra_interop/workflow_runtime.py` — adapters reais subordinados com a
  assinatura de contrato `configure/start/advance/signal/cancel/observe/
  reconcile` (+`interrupt/resume`, `fork` no LangGraph):
  `TemporalRuntimeAdapter` (superfície duck-typed do client `temporalio`:
  `start_workflow` com `id_reuse_policy=reject_duplicate`, `signal`,
  `cancel`, `describe` + `fetch_history_events` opcional; IDs
  `sentra-<run>-<workflow>-<occurrence>`; histórico classificado por
  `workflow_temporal`; `retry_kwargs()` para `temporalio.common.RetryPolicy`)
  e `LangGraphRuntimeAdapter` (`ainvoke/astream/getattr aget_state/
  aupdate_state`; thread IDs com escopo+ocorrência; interrupt/resume com
  approval; `fork` cria thread nova do checkpoint sem reescrever história;
  cancel cooperativo sem rollback). Todo efeito exige admissão central
  corrente do Run/dono; `observe/reconcile` são somente-leitura;
  UNCERTAIN nunca replays. Sem SDK/servidor configurado, tudo falha com
  `RuntimeUnavailable`. Nenhum scheduler soberano: o tick continua sendo
  o `RoutineSchedulerService` central.
- `sentra_interop/workflow_channels.py` — `ChannelTriggerBridge`
  (Slack/Telegram/WhatsApp): verificação real de assinatura em stdlib
  (Slack `v0` HMAC-SHA256 + tolerância 300s; Telegram `secret_token`
  constant-time; WhatsApp `X-Hub-Signature-256` HMAC-SHA256), janela de
  replay, allowlist workspace/usuário, dedupe por event ID, claims com
  admissão central injetada (identidade externa nunca concede grant),
  `reconcile_inbound` lookup-only, ciclo `enable/renew/disable/revoke`
  (disable remove a assinatura externa via callback e registra receipt;
  revoke purga secret ref + allowlists), outbound em dois estágios
  (`stage_notification` idempotente → `send_staged` registra SENT no ACK →
  `mark_delivered` só com receipt durável; ACK ≠ conclusão). Só guarda
  `secret_id`; segredo resolvido por chamada via `secret_resolver` do
  host. Sem callbacks do host, falha explícita — nada simulado.
- `tests/unit/test_pulso_runtime.py`,
  `tests/unit/test_pulso_channels_schedule.py` — cobertura futura de
  runtimes (fakes duck-typed), canais (HMAC round-trip, dedupe, ciclo de
  vida, SENT→DELIVERED), cron timezone/DST/exclusões, after-completion,
  guard de políticas e GC do ledger (não executados nesta fase).

## Arquivos alterados (adições, sem mudar comportamento existente)

- `sentra_mcp/services/routine_scheduler.py` [EXPANSÃO] —
  `RoutineScheduleTZ` (cron com `timezone` IANA via zoneinfo: match em
  wall time local, gaps DST pulados, minutos ambíguos disparam só no
  fold 0, `calendar_exclusions` YYYY-MM-DD, zonas desconhecidas/tzdata
  ausente falham explicitamente; `every_after_completion_seconds` como
  modalidade distinta com ocorrência única e sem catch-up de backlog) e
  `RoutinePolicyStore` (tabela `pulso_routine_state`: pausas manuais e
  automáticas, `awaiting_completion` para non-overlap estrito,
  `consecutive_failures` com auto-pause por `_pulso_max_consecutive_failures`,
  `spent_micro_usd` contra `_pulso_cost_cap_usd`, `note_completion` para o
  host registrar outcomes terminais). `tick()` preserva semântica para
  specs legados (delegação exata quando sem chaves novas) e adiciona:
  gate de pausa/custo (PAUSED), ramo after-completion (PENDING/PROCESSED
  com espera de conclusão). Novos métodos de serviço `set_paused` e
  `note_outcome` (approval do dono exigida na pausa).
- `sentra_interop/workflow_shell.py` [EXPANSÃO] — 31 ações em mapa exato
  (novas: `schedule_pause/resume`, `runtime_intent/observe`,
  `channel_list/enable/renew/disable/revoke/send_intent/inbox/claim/ack`);
  `schedule_create` valida specs TZ/after-completion e aceita
  `max_consecutive_failures`/`cost_cap_usd` em metadata;
  `channel_send_intent` monta (nunca entrega); leituras de workflow,
  runtime e canais exigem `workflow_resolver`/`runtime_resolver`/
  `channel_bridge`/`channel_service`/`trigger_bridge` injetados.
  Correções da expansão: `schedule_list` respeita a assinatura real
  `list_routines(owner, *, enabled_only)` com paginação local;
  `schedule_enable/disable` usam `enabled=` keyword-only.
- `sentra_interop/workflow_channel_triggers.py` [CANAL LUME] —
  `ChannelWorkflowTrigger`: consome `pending_inbound`/`claim`/`ack` do
  `ChannelService` (Lume) e liga o trigger ao workflow real central pela
  `dispatch_idempotency_key` (`channel:<connector>:<event>`): rotas
  host-bound (`bind_route` com approval), claim CAS sem reatribuição
  automática, intent `workflow:signal` exato com payload de proveniência
  (texto resolvido server-side do inbox cifrado; `chat_trust_inherited:
  false`), `mark_admitted` + `ack_claim` (SUCCEEDED-only, senão
  uncertain). Nenhum efeito na facade; nenhum ChatTrust herdado.
  `confirm_dispatch` (com `attach_control`): verifica SUCCEEDED no mesmo
  WorkItem via durable read e só então acka — sem grants novos.
  `PulsoChannelSendExecutor`: `resolve` (texto server-side) + `execute`
  (request `channel:send` admitido → `ChannelService.send` do Lume).
- `sentra_interop/workflow_runtime_host.py` [HOST] —
  `RuntimeProviderHost(machine_host, ...)`: mesma MachineHost
  control+owner (policy/registry centrais); `register_factory` (construtor
  `(options, secrets) -> client`, factories builtin `temporalio-connect`
  e `langgraph-local` com indisponível explícito sem pacote);
  `configure` (pins versionados, `secret_refs` via resolver, opções sem
  material secreto, binding do adapter subordinado);
  `restore` (reconstrói client+adapter do binding); `catalog` (só
  projeções); `dispatch_request` (intent exato na família proposta
  `runtime:<provider>:<operation>` para o allowlist central);
  `submit` (executa DENTRO da admissão corrente, sem grants novos).
  `PulsoWorkflowExecutor`: `execute(request, intent)` admitido →
  `bridge_lookup` → `host_handler` (admite+executa `workflow_intent`).
- `sentra_interop/workflow_channels.py` [CANAL SEND]: `bind_sender`
  (subscription→connector, host approval) + `resolve_send` (texto
  server-side do payload protegido) para o root admitir `channel:send`
  e dirigir `ChannelService.send` (Lume) dentro da admissão.
- `sentra_executors/conpty_sessions.py` — `PersistentConPTYLedger`:
  projeção durável de vínculos de sessão, cursores de transcript e estado
  open/closed para listagem e retomada via transcript persistido do Canvas.
  Nunca alega handle vivo após restart (`live=False`, sem PID/lease como
  prova). Classe `ExistingConPTYSession` intacta.
  [GATE] `TerminalWriteGate`: `request` monta o intent fenced
  `terminal:write` (scope do ledger server-side); `execute` exige
  `CentralEffectContext` corrente e delega a `write_stdin`. A facade não
  chama write direto. `_scope`/`read`/`write_stdin` aceitam
  `canvas_principal` separado (default compatível).
  [EXPANSÃO] `gc_plan()` (plano review-only por handle idle, sem kills).
- `sentra_executors/operation_receipts.py` — `HumanReceiptViews`:
  recibo humano com linhagem (rotina/goal-loop/workflow/terminal),
  estado de aprovação e próximo passo sanitizado, ainda somente-leitura e
  projetado por campos. Classe `OperationReceiptViews` intacta.
- `sentra_mcp/services/routine_scheduler.py`, `sentra_mcp/services/jobs.py`,
  `sentra_executors/goal_loop.py`, `sentra_interop/workflow_bridge.py`,
  `workflow_checkpoint.py`, `workflow_contracts.py`, `workflow_http.py`,
  `workflow_worker.py`, `activepieces.py`, `activepieces_worker.py` —
  avaliados e considerados completos para o núcleo; nenhuma alteração
  necessária. `jobs.py` permanece restrito a operações de repositório
  (workflows empresariais correm no worker subordinado, não no JobService).

## Arquivos de outros donos (não tocados)

Nenhuma edição em `sentra_canvas/service.py`, `graph.py`,
`sentra_mcp/server.py`, `sentra_core/*`, `sentra_runtime/*` (inclui
`nats_jetstream.py` da Nexo), `sentra_interop` não-`workflow*`/
não-`activepieces*` (Lume), `governance.py`/`control_store.py` (Nexo),
`action_consent_gate.py` (Pacto), UI (Prisma/Tessela). Sem
commit/push/reset/stash. Mudanças anteriores preservadas (árvore sobre a
`main` `3639a2e`; apenas untracked da coordenação visíveis no status).

## Contrato de integração (enviado cedo ao Codex via `maestri ask`)

1. Codex registra `PulsoShellDispatch(control, governance, canvas=...,
   conversations=..., workflow_resolver=..., runtime_resolver=...,
   channel_bridge=..., channel_service=..., trigger_bridge=...,
   idempotency_database=..., workspace_root=...)` na rota
   `POST /api/shell/bridge` após autenticação bearer e normalização
   `ws`→`project_id`; deriva `owner` canônico (`canvas._runtime().owner`)
   e `principal_id` da sessão — nunca do browser. Ledger de idempotência
   obrigatório para mutações (sem ele, a facade recusa mutar).
2. Ações de leitura de workflow/runtime (`workflow_observe/output`,
   `runtime_observe`) exigem `workflow_resolver`/`runtime_resolver`
   injetados (já correm dentro da admissão central); sem eles, falham
   explicitamente. Canais: `ChannelTriggerBridge` local (ciclo de
   subscrição) + `ChannelService` (Lume: inbox/claim/ack/send) +
   `ChannelWorkflowTrigger` (Pulso: claim→intent pela dispatch key).
   Webhook receive só faz inbox (Lume, Codex compõe a rota).
3. Terminal `register()` do ledger deve ser chamado pelo host após
   `execute_consented_start` com sucesso; `note_cursor()` após leituras;
   `mark_closed()` após `execute_consented_close`. GC: `gc_plan()` +
   prova de handle vivo pelo host antes de qualquer close. Daytona:
   Forja detém `daytona_sessions.py`; Pulso solicita o mesmo padrão
   (close só por handle owned, GC review-only) sem editar o arquivo.
4. `ActivepiecesScheduleBridge.schedule_handler` é o callback a injetar
   como `schedule_handler=` em `OwnedPieceSDKBackend`; `webhook_handler`
   exige os callbacks de admissão/lookup do Control Plane do host.
5. Runtimes: o host provisiona client SDK autenticado + servidor e chama
   `configure(...)` com approval (`configure` negado via shell); cada
   efeito corre dentro de admissão central; `runtime_intent` monta
   (fork só LangGraph). `RoutineSchedulerService.set_paused/note_outcome`
   para o host/CLI registrar pausas e outcomes terminais (custos).
   Canais: `send` é do Lume sob `CentralEffectContext` (`channel:send` +
   hash, outbox antes do HTTP, `provider_accepted` separado de receipt do
   destinatário); SDKs oficiais Slack HTTP/TG Bot API/WA Cloud;
   libsignal/QR não importado e indisponível.
6. Ajustes do principal aplicados: identidade canônica + principal
   separado (`ExistingConPTYSession` aceita `canvas_principal`);
   replay com intent SHA + scope, reserva PENDING antes do efeito,
   UNCERTAIN em crash; schedules confirmam pin de projeto + Run real
   (renderer nunca envia `run_id`); mapa exato de 31 ações (sem prefix
   dispatch); `dispatch()` robusto com `principal_id/type`.
   Pergunta residual: prefixos de IDs (default: existentes, sem prefixo).
7. Assinaturas finais dos resolvers host (Nexo/Codex compõem; Pulso não
   admite nem cria grants — só dirige dentro de admissão):
   `workflow_resolver(action, ctx, params)`: `observe|output` → projeção
   de leitura; `execute` com `{request, intent}` admitido → dict via
   `PulsoWorkflowExecutor` + `bridge_lookup` injetado.
   `runtime_resolver("observe", ctx, params)` → `RuntimeProviderHost`
   (`dispatch_request` → admitido → `submit` no contexto).
   `channel_resolver`: `resolve {dedupe_key}` → `{connector_id,
   recipient, text}`; `execute {request, connector_id, recipient, text}`
   → `ChannelService.send` (Lume). `ChannelWorkflowTrigger` fecha
   claim→signal→SUCCEEDED ack sem grants novos (`confirm_dispatch`).
   `TerminalWriteGate.request/execute` para `terminal:write` fenced.

## Dependências [EXPANSÃO]

Nenhuma dependência obrigatória nova. Opcionais por provedor, todos com
estado indisponível explícito quando ausentes:

| Recurso | Pacote/serviço | Estado na árvore |
|---|---|---|
| Cron timezone/DST | stdlib `zoneinfo` + `tzdata 2026.3` | instalado (pip) |
| HTTP AP nativo | `httpx 0.28.1` | instalado (requirements) |
| NATS JetStream | servidor NATS + consumer TLS (`sentra_runtime/nats_jetstream.py`, Nexo) | transporte injetado; sem consumer → `NATSTransportMissing` |
| Temporal | pacote `temporalio` + servidor | **não instalado** → `RuntimeUnavailable`; SDK verificado por superfície+versão quando o host injetar |
| LangGraph | pacote `langgraph` ou clone `third_party/langgraph` provisionado | **não instalado como dep** → `RuntimeUnavailable`; testado contra fakes duck-typed |
| Piece SDK Node | Node + bundle instalado pelo dono | inalterado (rodada 3) |
| Slack/Telegram/WhatsApp | `ChannelService` (Lume, oficial Slack HTTP/TG Bot API/WA Cloud) + segredos via vault | composto; libsignal/QR **não importado e indisponível explícito** |

Nenhuma lib de licença desconhecida incorporada por nome (contrato C113:
canais usam stdlib; wakes de WhatsApp e distribuição opcional com
Lume/Vitra).

## Comunicação com o Codex principal

- Contrato cedo enviado via `maestri ask "Codex"` antes da implementação
  (resposta chegou como prompt direto no terminal, ilegível via `maestri
  check` — terminal principal ocupado com 5 background tasks).
- Relato final tentado 2x via `maestri ask "Codex"` (timeout de 120s e
  300s, sem output): terminal principal ocupado, entrega não confirmada
  pelo orquestrador. Tentativas registradas; este relatório local
  (`docs/integral/Pulso.md`) é a evidência da conclusão. Re-tentar o
  `ask` após a liberação da etapa de validação.

- Composição da rota e dos resolvers pelo Codex principal (fora do meu
  ownership).
- `bind_provider` das capabilities `workflow:*`/`activepieces:*`/
  `terminal:*`/`goal:iterate` e resolvers protegidos/catálogos pelo host.
- Conta/servidor AP real, consumer NATS TLS, deploy Temporal/LangGraph se
  um subworkload os justificar (meus adaptadores falham explicitamente
  sem eles, por desenho).
- Resposta do Codex às três perguntas de contrato acima.

## Plano de validação futura (somente após liberação do Codex)

```powershell
python -m pytest tests/unit/test_pulso_workflow_adapters.py tests/unit/test_pulso_scheduling.py tests/unit/test_pulso_shell.py -q
python -m pytest tests/unit/test_pulso_runtime.py tests/unit/test_pulso_channels_schedule.py tests/unit/test_pulso_channel_triggers.py -q
python -m pytest tests/unit/test_pulso_runtime_host.py -q
python -m pytest tests/unit/test_sentra_interop_workflow_worker.py tests/unit/test_sentra_interop_activepieces_provider.py -q
```

Entrega registrada somente em arquivo (sem ask-back ao root, conforme
ordem); nenhum processo tocado — previewPID47408 intacto, sem
build/install/restart/QA.

Mais: prova externa com AP server real (ação literal pinada, POST
interrompido sem re-disparo sob mesmo `invocation_id`, cancel observado,
webhook repetido gerando um único WorkItem, disable removendo assinatura
externa); dreno NATS real com perda de ack central; shell bridge
ponta-a-ponta (replay de `request_key`, binding de workspace, falha
fechada sem admissão); retomada de terminal após restart relendo
transcript persistido.
