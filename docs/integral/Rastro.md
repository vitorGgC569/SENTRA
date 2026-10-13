# Rastro — entrega integral (continuidade, outbox, gateway)

Data: 2026-10-11. Papel: Rastro (OpenCode Muse Spark 1.3 Free, high).
Escopo exclusivo: `native_bridge/*`, `sentra_model_gateway/*` (exceto
`browser_host_identity.py`), `sentra_mcp/services/session_checkpoint.py`,
`web_account_dispatch.py`, `web_history_*`. Nenhum arquivo de outro dono
foi editado. Nenhum teste/build/lint/benchmark/QA foi executado, conforme
ordem de implementação-integral-primeiro. Expansão autorizada:
`docs/integral/tasks/Rastro.md` (Meridiano, 11/10/2026).

## Requisitos cobertos

- Continuidade A→B (COS-G03/G04, OD-G03/G04, OD-FF07, nota 465):
  `native_bridge/continuation_web.py` (preservado) compõe
  `ControlPlaneService.prepare/commit/reconcile/cancel_chat_continuation`
  com o outbox durável do relay (`delivery_key`, fingerprint,
  `prompt_sha256`, receipt exato). `stage`/`commit`/`allocate_new_target`/
  `claim_new_target` exigem aprovação humana, grant `web:send` vivo e
  receipt exato + atestado do coletor; `reconcile` é só observação.
  EXPANSÃO: `conversation_continuation.py` agora fixa a transcrição
  original no checkpoint (`transcript_sha256`, `transcript_message_ids`
  1..500, `children_snapshot` ≤200KB via `_transcript_binding`);
  `status` expõe o fixado e `resume` (novo kwarg `transcript_sha256`)
  recusa commit de transcrição divergente — OD-FF07 (transcript+outbox num
  só intento: outbox prende `prompt_sha256`, checkpoint prende
  `transcript_sha256`; crash/uncertain nunca repete, diverge → reconciliação
  do operador). `compact_resume.py::CompactResumeService` repassa os três
  campos em `begin`/`commit` (fases open→summary→exclusive claim→preflight→
  durable commit→publish/abort, mesma Run/Chat/WorkItem/agente/filhos/Grant,
  um handoff aberto por chat, abort preserva a origem).
- Prova exata request/message/document/epoch com Brisa (COS-A01/A03/A04):
  `web_evidence_ingress.py` (preservado) + NOVO
  `native_bridge/message_identity.py` (`resolve_by_request`,
  `resolve_by_message`, `require_index_resolution`): índice posicional do
  content-script (Brisa) é só metadado descritivo — a identidade durável vem
  de `browser_request_messages` + `browser_document_epochs`; índice sem
  correlação comprovada falha fechado, nunca inventa `message_id` sob DOM
  virtualizado. `web_account_dispatch.py` + `verified_account_from_catalog`
  (novo factory): o guard continua DENY sem `verified_account` real do host;
  o factory aprova só com `account_catalog_status` fresco+verificado de
  Brisa para o mesmo principal/provider e conversa correlata.
- Outbox cifrada/recibos (COS-G04, invisible outbox): `job_store.py` +
  `web_delivery.py` (preservados: DPAPI/keyring, `not_sent/pending/
  unconfirmed/sent`, um envio por chat, `CONVERSATION_DELIVERY_BUSY`,
  single-use fence) + `outbox_recovery.py` (só-observação,
  `automatic_resend: False`).
- Anexos (COS-A12 + ADENDO upload real): `web_history_assets.py`
  (preservado: chunks bounded, quotas 4MB/16MB, `READY_LOCAL` ≠ upload) +
  NOVO `native_bridge/attachment_upload.py::AttachmentUploads`
  (`bind_asset_to_job` com verificação de job existente + colisão de
  identidade, `bound_image` dentro do teto do relay, `upload_status` com
  `web_uploaded` só sob receipt exato, `read_asset` recuperável bounded).
  Descritores viewer-safe de Brisa (`describe_attachments`, só fingerprints)
  continuam a camada descritiva; bytes viajam só pelo caminho autorizado
  relay/WebSend com receipt de contagem.
- Streaming por message ID/revisão/overflow (COS-A13 + lacuna A13 do
  contracts.md): NOVO `native_bridge/stream_ingest.py`
  (`record_stream_frame` grava Brisa `StreamingLedger` + `WebHistoryStore`
  sob a mesma prova exata e revisão monotônica nos DOIS ledgers;
  `assistant_attestor_from_streaming` autentica o assistente pelo vínculo
  duradouro do receipt + revisão mais recente do ledger Brisa + mesmo
  document/epoch, com `host_observation` para a segunda prova — payload de
  página sozinho nunca atesta; sequência nunca vem de índice (índice do
  content-script só entra via `message_identity.require_index_resolution`,
  que resolve pelo request comprovado ou falha fechado).
- Conta/modelo/effort/Automatic (COS-G02, OD-G02): `account_models.py`
  (unknown/pending/ready/unavailable+stale, nonce+generation, Automatic só
  do observado, seleção reconciliada) + NOVO `merge_attested` (interseção
  fail-closed com o catálogo verificado de Brisa e opcional
  `merge_catalogs` do Codex; `gateway.py`: `observe_account_models`,
  `account_model_view`, `select_account_model`, GET `/sentra/account-models`,
  fallback `/v1/models` sem modelos inventados).
- Search/history/export/delete (COS-A11/A20, OD-CF06/AF13):
  `web_history_store.py` + `list_observed_conversations()`,
  `export_message()` (uma resposta, com proveniência e redação opcional),
  `delete_workspace()` (mensagens+termos+observações+prefs juntos;
  `set_index(enabled=False)` apaga só termos), stoplist de segredos em
  `_terms` (hashes/keys nunca indexados por padrão; índice continua opt-in
  por owner/workspace com `operator_approved`).
- Usage (COS-A14): `web_history_usage.py` preservado + `host_boot.py::
  usage_projection` (SENTRA-accounted vs Web-observed lado a lado,
  `equivalent: False`, indisponibilidade explícita do ledger).
- Shell/CLI/boot com Codex (sem editar arquivos centrais):
  NOVO `native_bridge/host_boot.py` (`boot_recovery`, `attach_attestors`,
  `shell_projection` para `conversation_list`/`message_list`/outbox,
  `usage_projection`, `cli_status` para `/model`+/resume) — pontos de
  composição documentados no docstring para o Codex ligar em
  `POST /api/shell/bridge`, `sentra_cli/repl.py` e boot do host.

## Arquivos (só domínio Rastro)

- `WebSendAuthority.admit` aceita `images=[data-URL]` (0..2, tetos do
  `ChatJob`): bytes entram no digest do intento — replay com bytes
  diferentes é conflito, nunca substituição silenciosa.
- Criados: `sentra_model_gateway/account_models.py`,
  `native_bridge/outbox_recovery.py`, `native_bridge/compact_resume.py`,
  `native_bridge/message_identity.py`, `native_bridge/stream_ingest.py`,
  `native_bridge/attachment_upload.py`, `native_bridge/attachment_transport.py`,
  `native_bridge/shell_multimodal.py`, `native_bridge/host_boot.py`,
  `docs/integral/Rastro.md`.
- Editados (aditivos; único comportamento corrigido: fallback `/v1/models`
  não inventa modelos): `sentra_model_gateway/gateway.py`,
  `native_bridge/relay.py` (rotas `/browser-evidence/approval` e
  `/browser-evidence/account-catalog` via adapter V2 de Brisa, worker-online
  exigido), `native_bridge/web_send.py` (`admit(..., images=)`),
  `sentra_model_gateway/web_transport.py` (preflight aceita `attachments:
  [{asset_id, sha256}]` resolvidos host-side + `gateway_web_attachment_links`
  anti-substituição em replay),
  `sentra_mcp/services/session_checkpoint.py` (`history`,
  `latest_summary`), `sentra_mcp/services/web_history_store.py`
  (`list_observed_conversations`, `export_message`, `delete_workspace`,
  stoplist), `sentra_mcp/services/web_account_dispatch.py`
  (`verified_account_from_catalog`),
  `native_bridge/conversation_continuation.py` (transcrição fixada),
  `native_bridge/compact_resume.py` (repassa transcrição).
- Preservados sem edição: resto de `native_bridge/*`,
  `sentra_model_gateway/turn_authority.py`, `web_transport.py`,
  `web_history_usage.py`, `web_history_assets.py`, e tudo fora do escopo
  (central Codex, Brisa `browser/*`, Nexo, Prisma, demais donos).

## Assinaturas finais para composição (Nexo/Codex/Prisma/Brisa/Vitra)

```python
# Continuidade (Rastro; autoridade: Control Plane Nexo; rota: Codex)
CompactResumeService(control, jobs, conversations=None, account_attestor=None)
  .begin(owner, conversation_id, *, run_id, chat_id, work_item_id, principal_id,
         request_key, summary, cursor=None, target_url=None, operator_approved,
         transcript_sha256=None, transcript_message_ids=None, children_snapshot=None)
  .preflight(owner, conversation_id, *, allocation_id=None, continuation_id=None)
  .commit(owner, conversation_id, *, allocation_id=None, continuation_id=None,
          operator_approved, transcript_sha256=None)
  .abort(owner, continuation_id, *, operator_approved)
  .status(owner, conversation_id, *, allocation_id=None, continuation_id=None)
# -> {phase: claimed|blocked|preflight_ok|preflight_blocked|published|aborted|
#     waiting_receipt|unconfirmed, ..., transcript_sha256, transcript_message_ids,
#     children_snapshot, successor_ready, automatic_retry: False}

# Identidade durável sob DOM virtualizado (Rastro; prova Brisa prévia)
message_identity.resolve_by_request(control, *, browser_principal, request_id)
message_identity.resolve_by_message(control, *, browser_principal, message_id)
message_identity.require_index_resolution(control, *, browser_principal,
  conversation_id, observed_index, request_id)

# Outbox / recovery (Rastro; só observação)
recover_outbox(jobs, control=None) -> {jobs:[{job_id, relay_state, delivery_state,
  requires_operator_reconciliation, suggested_action, automatic_resend: False}]}
recover_continuations(control, owner) / recover_web_sends(control, jobs, owner)
host_boot.boot_recovery(control, jobs, owner) -> {outbox, continuations, web_sends,
  requires_operator_reconciliation, operator_items, automatic_resend: False}

# Streaming / attestors (Rastro sobre ledgers Brisa)
stream_ingest.record_stream_frame(control, history, streaming, *, owner, run_id,
  browser_principal, request_id, worker, conversation_id, message_id, revision,
  role, state, text, identity_epoch=None)
stream_ingest.assistant_attestor_from_streaming(control, streaming)  # p/ WebSendAuthority
host_boot.attach_attestors(*, web_transport=None, web_send=None, control=None,
  streaming=None) -> {account: bool, assistant: bool}
web_account_dispatch.verified_account_from_catalog(control, provider="chatgpt",
  max_age_s=600.0)  # p/ WebMCPMessageDispatchGuard(..., verified_account=...)

# Anexos com upload real (Rastro; bytes via relay/WebSend, receipt exato)
AttachmentUploads(control, jobs, drafts).bind_asset_to_job(owner, asset_id, job_id)
AttachmentUploads(...).bound_image(owner, asset_id) -> data-URL (teto relay)
AttachmentUploads(...).upload_status(owner, asset_id)
  -> {state, job_id?, web_uploaded: bool, delivery_state, ...}  # READY_LOCAL≠upload

# Transporte shell de anexos — dispatcher REAL + refs scoped (Rastro)
attachment_transport.attachment_ref(control, drafts, owner, asset_id)
  -> {asset_id, workspace, run_id, work_item_id, sha256, state, ...}  # sem bytes
attachment_transport.validate_ref_for_bridge(control, drafts, ref, *,
  browser_principal, request_id) -> {**ref, bridge_admitted: True, ...}
attachment_transport.dispatch_attachment(control, jobs, drafts, web, *, owner,
  asset_id, request_identity, run_id, operation_id, work_item_id, principal_id,
  grant_id, workspace, conversation_key, prompt, conversation_url=None,
  submission_index=0, timeout_s=180)
  -> {job_id, asset_id, ref, state, send_fence, web_uploaded: False, ...}
  # mesma Operation/WorkItem (admit fenced); bytes no intent; receipt exato depois
attachment_transport.receipt_status(control, jobs, drafts, owner, asset_id)
attachment_transport.resolve_ref_for_host(control, drafts, ref, *,
  browser_principal, request_id) -> bytes  # só host, pós-validação

# Shell multimodal Brisa att-* + bytes -> UM turno (Rastro, atômico)
shell_multimodal.dispatch_shell_turn(control, jobs, drafts, web, *, owner,
  run_id, work_item_id, operation_id, principal_id, grant_id, workspace,
  project_id?, space_id?, conversation_id, conversation_url?, request_identity,
  prompt, attachments=[{attachment_id, kind, name, mime, bytes, sha256, data}],
  operator_approved=True, timeout_s=180)
  -> {request_identity_sha256, project_id, space_id, conversation_id,
      intent: {submission_index: 0, job_id, asset_ids, state, send_fence},
      refs, evidence: {images, inline_texts, pdf_exports, sha256},
      web_uploaded: False, automatic_resend: False}
  # UM admit para o conjunto inteiro (1 fence, 1 receipt do set). PNG/JPEG
  # (máx 2, senão quota explícita, nunca split) -> images; text/plain ->
  # bloco inline citado; PDF -> TEXT EXPORT verificado via pypdf pinado
  # (páginas/chars bounded, rotulado export, binário staged não-transmitido;
  # sem pypdf/parse -> dispatch inteiro recusado). caller resolve att-*
  # antes via Brisa validate_attachments+read_bytes. Ids canônicos:
  # conversation-* com hífens OK, owner canvas:* validado, workers TAB-*
  # só de leases/proofs do host, nunca de argumentos.
# Set bindings — vários assets, UM job (Rastro)
AttachmentUploads(...).bind_asset_set(owner, [(asset_id, sha256)], job_id)
attachment_transport.dispatch_asset_set(control, jobs, drafts, web, *, owner,
  asset_ids[1..2], request_identity, run_id, operation_id, work_item_id,
  principal_id, grant_id, workspace, conversation_key, prompt, ...)
  -> {job_id, asset_ids, refs, state, send_fence, web_uploaded: False, ...}

# Gateway multimodal (Rastro; turno com anexos admitido, sem 2ª autoridade)
DurableWebTransport.browser_event("preflight", {capability, traceId,
  submission_index, prompt, prompt_sha256, model?, effort?, document_id,
  identity_epoch, surface_id?, attachments?: [{asset_id, sha256}]})
  -> admit(..., images=[host-materialized]) + gateway_web_attachment_links;
     replay com attachments diferentes -> 409 (nunca substitui)
DurableWebTransport._staged_images(binding, refs) / ._attachment_links(cap, index)

# Relay nativo (Rastro) + adapter V2 (Brisa) — endpoints reais
POST /browser-evidence/approval {source_sha256,worker,conversation_id,state,tool_name}
  -> BrowserEvidenceService.observe_approval (deny-only; pending bloqueia dispatch)
POST /browser-evidence/account-catalog {source_sha256,worker,provider,models,efforts,
  document_id,identity_epoch,authentication_revision}
  -> BrowserEvidenceService.publish_account_catalog (bound a document/epoch)
  # bearer+origem+build+worker-online verificados antes; worker sem heartbeat
  # vivo é negado; sem adapter Brisa -> 503 explícito

# Conta/modelos (Rastro; atestado Brisa; composição Codex/Prisma/Vitra-CLI)
AccountModelCatalog.observe(...) / .cached_view(fp|None) / .select(...)
  / .merge_attested(account_fingerprint, attested, gateway_catalog=None)
GatewayServer.observe_account_models / .account_model_view / .select_account_model
GET /sentra/account-models?account_fingerprint=… (admin/interno)
host_boot.cli_status(gateway_server, account_fingerprint=None)  # p/ CLI /model

# Histórico (Rastro; leitura p/ shell Home — composição Codex/Prisma)
WebHistoryStore.history→(checkpoint) history()/latest_summary()
WebHistoryStore.list_observed_conversations(owner, workspace, limit)
  / .messages / .search(opt-in) / .export_markdown / .export_message
  / .purge(conversa, approval) / .delete_workspace(approval) / .set_index(approval)
host_boot.shell_projection(control, jobs, owner, workspace, conversation_id?, limit?)
host_boot.usage_projection(control, owner, workspace, account_fingerprint, quota_bucket)
```

Wire-up pedido ao Codex (arquivos centrais intactos): chamar
`boot_recovery` no boot do host e expor itens `operator_items` no
Doctor/home; servir `shell_projection` em `POST /api/shell/bridge`
(`conversation_list`, `message_list`, visões de entrega) e `cli_status`
em `/model`+`/resume`; injetar `attach_attestors` com o `StreamingLedger`
e o store reais. Grant/Run/WorkItem/Operation continuam só no Control
Plane (Nexo).

## Composição CLI multimodal (concreta; `sentra_cli/*` é da Vitra, não editado)

Busca estática confirma: o CLI não tem flag `images` hoje e o runtime shell
raiz executa `sentra-cli --prompt-stdin` só-texto. Composição proposta
(Vitra/Codex, sem mudar autoridade, sem repetir prompts — UM turno por
chamada):

1. Nova flag `--attach att-...` (repetível, máx 4) em `sentra_cli/repl.py`:
   o runtime shell resolve cada ref via Brisa
   `validate_attachments(owner, refs, project_id, space_id, conversation_id)`
   e lê bytes via `read_bytes` (owner-checked, host-only).
2. Em vez de `--prompt-stdin` puro, o runtime chama
   `shell_multimodal.dispatch_shell_turn` com os IDs servidores já
   admitidos (Run/WI/Operation/owner/project/space/conversation) +
   `request_identity` estável + prompt + anexos resolvidos; recebe UM
   `intent` (job id) e acompanha o receipt do conjunto via
   `attachment_transport.receipt_status` por asset (mesmo job/receipt;
   nunca `READY_LOCAL` como prova). >2 imagens ou PDF sem parse →
   erro explícito, nunca N sends.
3. Caminho Gateway (turnos `sentra/chatgpt-web`): o cliente interno envia
   `attachments: [{asset_id, sha256}]` no `browser-preflight` (refs de
   assets já staged pelo helper ou pela API de drafts); o preflight admite
   com `images` e registra links — replay divergente dá 409.
4. Composição recíproca Brisa: `AttachmentStore.read_bytes` já anota
   `(Rastro/relay)` como consumidor; shell `message_send` valida refs via
   `validate_attachments` (Brisa) e o upload real segue
   admit→fence→SEND→receipt exato→attested (Rastro).

## Compatibilidade Postgres (contrato Nexo, sem editar arquivos alheios)

`PostgresControlPlaneStore` (Nexo, `sentra_mcp/services/postgres_store.py`:
tenant schemas, RLS de owner, advisory locks, `path_for`=None, dialeto só
DDL/identity/json_extract/ignore/table_info/user_version + locks
transacionais) lido integralmente; `prepare/commit/reconcile` e
write/latest checkpoints com assinaturas preservadas. Ajustes só em
arquivos Rastro:

- `session_checkpoint.py`: `self.path` documentado como None-em-postgres
  (sem ATTACH/semântica de arquivo); `PRAGMA secure_delete=ON` mantido como
  benigno (adapter retorna 0 + registra limitação, nunca garantia);
  `_migrate_protected_checkpoints` com ramo postgres — qualquer linha
  legada em plaintext OU marcador pendente **falha fechado** exigindo purge
  explícito de retenção do administrador (MVCC/backups não são erasure);
  marcador nunca limpo, VACUUM/WAL nunca executados como prova.
- `web_evidence_ingress.py`: `strftime('%s','now')` (inexistente no
  PostgreSQL) trocado por `time.time()` ligado como parâmetro — mesma
  semântica de epoch, ambos os backends.
- `gateway.py::web_transport_mode`: ausência de tabela também aceita
  `relation does not exist`/undefined do PostgreSQL como `legacy`; demais
  erros propagam.
- `PRAGMA table_info` (evidence_ingress, turn_authority, web_transport),
  todo DDL (`CREATE TABLE/INDEX`, parcial `WHERE`, `ALTER TABLE`),
  `INSERT OR IGNORE`/`ON CONFLICT`, `BEGIN IMMEDIATE` e `sqlite3.
  IntegrityError` (remapeado pelo adapter) já passam no dialeto — sem
  mudança. `DROP TABLE` legado em `web_transport` só corre em SQLite
  antigo; em postgres falharia fechado, nunca silencioso.
- `job_store.py` (outbox do relay) e `TurnAuthority.store`/`account_models`
  (cache do gateway): **SQLite local de host por desenho** (fila loopback +
  capabilities do processo gateway, nunca autoridade de Runs/Grants);
  erasure ali continua escopo do arquivo local. Nenhum desses recebe
  `cp.store`. `DurableWebTransport`/`WebSendAuthority`/`CompactResumeService`
  e projeções operam via `cp.store`/`control.store` e são backend-agnósticos.
- `docs/integral/Nexo.md` é do Nexo — não editado; este registro é o meu
  lado do contrato para composição.

## Pendências reais (não homologado; sem guests/runners/providers afirmados)

- Endpoints nativos de approval/account-catalog EXISTEM no relay
  (`native_bridge/relay.py`, composição com adapter+serviço Brisa; `pending`
  bloqueia dispatch via `require_dispatch_ready`). Resta Brisa/Host: snapshot
  físico (`selection_verified`, modelo/effort da página, `approval-snapshot`
  no launcher) para `_proof` liberar dispatches sensíveis à conta.
- `browser_host_identity.py` é da Brisa (excluído do meu escopo): não
  implementei atestador de conta lá; meu `verified_account_from_catalog` e
  `attach_attestors` são o lado Rastro, prontos para plugar.
- E2E/composição (Codex/Nexo/Prisma/Vitra) e qualquer runtime externo
  (guests de VM, runners, providers de voz/canais) NÃO estão declarados
  prontos por este relatório: implementação integral aqui significa fluxos
  reais no meu domínio + contratos de composição, sem artefatos de
  providers faltantes.
- Proveniência: Chat On Steroids (MIT, pin `151e7ef9…`, licença retida) e
  `SENTRA_RESEARCH_OPENDOTS` usados como referência; nenhum blob copiado
  sem aviso; docstrings citam a fonte.

## Plano de validação futura (NÃO executado)

- Herméticos (escrever, não rodar): catálogo sem picker/modelo sumido/conta
  trocada/seleção inválida/generation concorrente; perda de POST/reply,
  reload, reenvio tardio, `unconfirmed` sem duplicar; handoff duplo, crash
  em cada fase, abort preserva origem, transcrição divergente recusa commit,
  índice DOM sem correlação é descartado; quotas de anexo, revisão
  monotônica, overflow, `delete_workspace` apaga índice junto, segredos fora
  do índice.
- Integração: Control Plane real em SQLite temporário + relay JobStore real,
  duas abas/dois chats, revogação no meio da chamada, restart durante send,
  conta/perfil trocados — sem segunda autoridade.
- E2E autorizado + QA visual/fidelidade, concorrência/recovery/permissões,
  instalação/release — só após liberação do Codex.


## Fechamento Cobalto 11/10 - fontes atuais, sem homologacao

Autoria e relato historicos acima preservados. Delta atual por arquivo em
[Cobalto-fechamento.md](Cobalto-fechamento.md); contrato concreto do cliente
Edge/CDP e producer/receipt/frame em
[Cobalto-relay-observers.md](Cobalto-relay-observers.md). Cobalto mantem somente
Brisa/Rastro conforme REDISTRIBUICAO_CODEX.md; outros dominios/root/PG preservados.
Fontes implementadas nao significam ambiente provisionado, composicao do review
ou evidencias reais. ZERO homologados; nenhum teste/build/install/lint/QA agora.
