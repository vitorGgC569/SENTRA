# Brisa — entrega da implementação integral (Edge/browser, identidade/provas, streaming/anexos/aprovação observada, catálogo autenticado, voz WebRTC, anexos reais)

Data: 2026-10-11 (atualizado: voz + anexos reais + vínculo stream→message_id).
Sem validação executada (testes/build/lint/QA diferidos à etapa final do Codex).
Sem commit/push/reset/stash. Sem skills/MCP SENTRA. Arquivos alheios preservados.

## Requisitos cobertos (estudos do domínio)

- Chat On Steroids A01 (join exato request-ID da página → chamada MCP, nunca grant), A04
  (espera pela aprovação humana na própria página, sem auto-clique), A09 (prova de
  extensão instalada/pareada/login entre reinícios), A13 (histórico de streaming por
  message ID, não por frame), fatias 2/3 (correlação segura, conversas duráveis).
- OpenDots/invisible_dots: aprovações duráveis observadas, recibos/evidence como dados,
  isolamento host/executor (nada no browser cria Run/Grant/Lease/efeito).
- Contrato shell bridge 2026-10-11: nenhuma rota nova, nenhum `owner`/Grant via browser;
  identidade e escopo derivam da sessão autenticada + Control Plane.

## Arquivos alterados/criados (todos de propriedade Brisa)

**Novos — `browser/`**
- `browser/streaming.py`: `StreamingLedger` — frames parciais por
  `(principal, conversation_id, message_id)` com revisão monotônica, teto 32k chars,
  overflow referenciado, máx 512 frames/mensagem. Dados, nunca prova de entrega.
- `browser/attachments.py`: `describe_attachments`/`evidence_summary` — descritores
  tipados image/pdf/text/code, quotas (máx 4/turno, 8MB imagem, 20MB documento),
  validação base64-data-URL, somente fingerprints (sha256/bytes) no ledger.
- `browser/approval.py`: `ApprovalLedger.observe/status` — observação deny-only
  (`pending/cleared/unknown`), `effect_performed: False` sempre, freshness fail-closed.
- `browser/account_catalog.py`: `AccountCatalog.publish/status` — catálogo
  modelos/esforços vinculado a (collector, worker, document, epoch, auth revision),
  fail-closed (`no_attested_catalog`/`attestation_stale`).

**Estendidos**
- `browser/protocol.py`: `TAB_OPS` + `BROWSER_EXTRACT/CLICK/TYPE` (paridade real com o
  content-script) + `STREAM_SNAPSHOT/APPROVAL_STATUS/ATTACH_INFO/MODEL_CATALOG_OBSERVE`.
- `browser/__init__.py`: exporta os quatro novos módulos.
- `browser/evidence_http_v2.py`: rotas V2-only `/browser-evidence/approval` e
  `/browser-evidence/account-catalog`, envelopes exatos, binding de collector imutável.
- `sentra_model_gateway/browser_host_identity.py`: `read_host_approval` (deny-only) e
  `read_host_account_catalog` (exige `account_verified`, revision int, catálogo válido;
  falha fechado). Mesmo padrão loopback autenticado; sem IDs de conta em erros.
- `sentra_mcp/services/browser_evidence.py` (aditivo, comportamento existente intacto):
  tabelas `browser_approval_observations`, `browser_account_catalogs`; métodos
  `observe_approval`, `approval_status`, `publish_account_catalog`,
  `account_catalog_status`. `pending` espelha `awaiting_approval` no gate existente.
- `edge_extension/selectors.js`: grupos `approvalCard`/`attachmentChip` (ChatGPT + Gemini).
- `edge_extension/content-script.js` (1.7.0): `omaApprovalDetail`, `omaAttachInventory`,
  `omaStreamSnapshot` (revisão por índice de mensagem), `omaObservedModelCatalog`
  (`verified:false`), ops `STREAM_SNAPSHOT/APPROVAL_STATUS/ATTACH_INFO/MODEL_CATALOG_OBSERVE`,
  `GET_STATUS` enriquecido, `BROWSER_CLICK` recusa UI de aprovação
  (`APPROVAL_CLICK_REFUSED`).
- `edge_extension/service-worker.js` (1.7.0): `BROWSER_ACTION` read-only
  `stream_snapshot/approval_status/attach_info/model_catalog`; prova V2 continua
  ChatGPT-only, rotas Gemini negam fechado (`identity_unknown`).
- `edge_extension/recovery-guard.js`, `manifest.json` (1.7.0, build `durable-r28`),
  `README.md` (seção Brisa 1.7.0 + nota de re-stamp).
- `integrations/codex_chatgpt_web/account_catalog.py` (novo): `merge_catalogs` —
  interseção fail-closed catálogo Codex × catálogo atestado, sem expor auth.

## Voz WebRTC real (ordem `docs/integral/tasks/Brisa.md`, com Prisma)

**Novo — `browser/voice.py`**
- `VoiceRuntime(state_root, config)` com `voice_availability`/`voice_dispatch`
  (assinaturas do `ShellCoordinator`); esquemas em `VOICE_ACTION_SCHEMAS`.
- Transporte real único e documentado: `OpenAIRealtimeTransport`
  (kind `openai-realtime`, default) — Realtime API pública REST+SDP: mint de
  `client_secret` efêmero server-side (`POST /realtime/sessions`, chave
  longa só no servidor), troca SDP (`POST /realtime/calls?model=`,
  `application/sdp`), poll (`GET /realtime/calls/{id}`), close (`DELETE`).
  Kind desconhecido → deny em config. Sem chave (`voice_provider.api_key` /
  `bearer_file` / `SENTRA_VOICE_PROVIDER_API_KEY`) → `available:false`
  explícito. Nenhum bearer/TURN publicado ao renderer; `ice_servers` sai como
  `[{urls:[...]}]` (RTCIceServer; credenciais TURN removidas).
- `voice_start` idempotente por `request_key` (fingerprint; replay/conflito/
  reconcile sem duplicar efeito); opt-in `True` literal; falha → `uncertain`.
- `voice_signal transcript`: segmentos persistem **content + receipt +
  verified** server-side; verificação server-side via `verify_segment`
  (poll da chamada; sem ref → mint efêmero fresco prova conta viva). O
  protocolo documentado não tem endpoint REST de item → segmentos ficam
  `verified:false` (provisórios p/ exibição) e `role:tool` é NEGADO
  (nunca autoriza efeito). `voice_status` retorna
  `{message_id, role, content, revision, receipt, verified}`.
- `rebind` com renegociação HTTP real: nova troca SDP (nova ref, fecha a
  antiga best-effort), mesma `call_id`, generation+1, dentro de 300s; falha →
  `uncertain` sem consumir generation. UI recebe `answer_sdp` p/ retomar mídia.
- `voice_stop/voice_revoke` idempotentes (`DELETE` best-effort; revoke sela
  transcript). TTL 3600 c/ heartbeat; expirado → `expired`.
- Limite honesto registrado: `call_ref` REST-endereçável ainda não extraído do
  fluxo pinado (resposta é só SDP) → poll por ref pendente de pinagem do
  formato na QA final; liveness via sessão efêmera até lá. Nada homologado.
- Correção Codex (placeholders + reserva): `INSERT voice_calls` com 16
  placeholders/16 parâmetros nas duas branches; reserva `voice_requests`
  com COMMIT antes do `exchange_offer` (nenhuma transação segura rede);
  crash entre reserva e outcome → mesma `request_key` reconcilia
  (`_reconcile_start`/`_status` retornam `uncertain`, nunca duplicam efeito).
- Scope verificado em status/signal/finish via `_check_scope`: projeto sempre;
  space/conversation quando o envelope (conversa canônica do root) os traz;
  owner segue servidor. `validate_attachments` aceita
  `project_id/space_id/conversation_id` com a mesma regra.
- Disponibilidade honesta: `voice_availability` declara `probed:false`,
  `transport:"server signaling only"`, `proves_delivery:false`;
  `attachment_availability` declara `proves_model_delivery:false`
  (armazenamento local ≠ envio ao modelo; entrega exige send no composer +
  receipt exato). Injeção de autoridade CP antes de efeitos + allowlist dos
  chunks: aguardar Nexo/Codex (composição deles; callbacks finais do runtime
  após schema final).

## Anexos reais + vínculo stream→message_id (lacunas contracts.md 1 e 3)

- `AttachmentStore` (`browser/attachments.py`): `attachment_register(project_id,
  owner, action, payload, key)` — **CAS por request_key** (fingerprint de
  projeto/espaço/conversa+descritores; replay/conflito; perda de reply nunca
  duplica), blobs vinculados a **(owner, project, space, conversation)** +
  `operation_id/work_item_id` do envelope servidor (receipt amarra a origem;
  `validate_attachments(owner, refs, project_id?)` nega escopo cruzado e
  **re-verifica SHA-256 + tamanho a cada chamada**). Bytes content-addressed
  (`state_root/attachments/xx/sha`, escrita atômica, dirs 0o700/arquivos 0o600;
  criptografia at-rest além de ACL de SO = escopo release/Vitra declarado).
- Chunks p/ acima do body budget: `upload_begin` (declara total+SHA) /
  `upload_chunk` (request_key própria por chunk + `chunk_sha256` opcional,
  index ordenado, ≤512KiB p/ caber no POST 800k da bridge, replay idempotente,
  conflito em reuso indevido) / `upload_complete` (verifica SHA total, receipt
  CAS, idempotente) / `upload_abort` (idempotente, limpa staging) /
  `upload_status` (read-only por `upload_id` ou qualquer `request_key` p/
  consulta dedup após reply ambíguo). Ações shell finais em
  `ATTACHMENT_UPLOAD_SCHEMAS`: `attachment_upload_begin/chunk/complete/abort/
  status`; entrada `attachment_dispatch(project_id, owner, action, payload,
  key)` p/ composição do runtime (Codex registra na allowlist; POST 800k e
  envelope request_key existentes preservados). UI: progresso local por
  (upload_id, index, sha), retry com a MESMA key, sem reenvio automático.
- `AttachmentStore.attachment_availability()` p/ composição do Codex:
  `home.attachments = {available:true, max_attachments_per_turn:4,
  max_image_bytes:8MB, max_document_bytes:20MB, kinds:[code,image,pdf,text],
  chunk_bytes:1MB, max_chunks_per_upload:20}`.
- `StreamingLedger.record_extension_snapshot(principal, conversation_id,
  message_index, revision, text)`: resolve índice DOM → message_id lógico durável
  (mensagens com evidência, ordem rowid); fora de alcance → deny. Fecha lacuna 3
  lado Brisa; Rastro/history leem pelo message_id lógico.

## Contrato de integração (para Codex compor; Rastro/Pacto/Nexo consumir)

1. Relay publica (após auth existente + `authorized_worker` + atestação de conta do Host):
   `POST /browser-evidence/approval {source_sha256,worker,conversation_id,state,tool_name}` e
   `POST /browser-evidence/account-catalog {source_sha256,worker,provider,models,efforts,document_id,identity_epoch,authentication_revision}` via `dispatch_authenticated_v2`.
2. `BrowserEvidenceService.approval_status(principal, conversation_id)` → Pacto
   (consent gate) e shell: `send_blocked=True` em `pending`/stale; nunca executa efeito.
3. `BrowserEvidenceService.account_catalog_status(principal, provider)` → shell home +
   `merge_catalogs(cached_model_catalog, attested)`: só lista modelos presentes em AMBOS.
4. `StreamingLedger.record_frame/latest/history` → Rastro (`web_history_*`) e viewers;
   `describe_attachments` no caminho de envio antes do `SEND_MESSAGE`.
5. Shell bridge: sem ações novas; `message_send`/`coordinate` consomem estes status como
   filtros deny-only sob autoridade Nexo/Codex.
6. Voz p/ Codex compor: `VoiceRuntime(state_root, config)` como shell runtime
   (`voice_availability`/`voice_dispatch`); config
   `{voice_provider:{kind:"openai-realtime", base_url?, model?, voice?,
   api_key?|api_key_file?, ice_servers:[str|{urls}]}}` ou env
   `SENTRA_VOICE_PROVIDER_API_KEY`; sem chave → `home.voice.available:false`.
   (Asks a Codex/Prisma enfileirados com ambos ocupados — `maestri check`
   confirma recebimento na fila; integral preservado aqui, sem reenvio.)
- Prisma compõe UI chunks em `shell-attachments.jsx` (staged, SHA-256,
  512KiB, request_key por chunk, status-dedup, reseleção por hash/tamanho,
  complete/abort idempotentes, só refs `att-*` pós-receipt, limites
  8MiB/20MiB, 4 refs, TTL expired visível). Repasse de disponibilidade ao
  Codex enfileirado (ocupado; conteúdo neste arquivo). `home.attachments`
  permanece server-authoritative via `attachment_availability()`.
   `attachment_register` via `AttachmentStore(state_root).attachment_register`;
   `home.attachments = AttachmentStore(...).attachment_availability()`;
   `message_send` valida refs via `validate_attachments(owner, refs,
   project_id=...)`. Prisma: `VOICE_ACTION_SCHEMAS` em
   `browser/voice.py` (ice `[{urls}]`, transcript c/ content+receipt+verified,
   rebind c/ `answer_sdp`); nenhum GET novo criado. Rastro: transcripts por
   `(call_id, message_id, revision)` p/ history; `read_bytes` p/ upload real ao
   composer com receipt exato. Runtime callbacks do Codex: aguardar schema
   final; nenhuma concessão parte do renderer; nenhum bearer publicado.

## Pendências reais (não homologado)

- `sentra_source_hash` + `sentra-bootstrap.json` (proof) com valores da 1.6.52: Vitra/release
  deve regenerar via `scripts/commander/extension_identity.py` (arquivo de Vitra, não tocado).
  Até lá, testes de identidade da extensão falham explícito — correto, não homologação.
- Host (`launcher/electron/*`, upstream patch) ainda não serve `/v1/sentra/approval-snapshot`
  nem `/v1/sentra/account-catalog`: `read_host_*` falham fechado até o Host implementar
  (dono do patch: Brisa detém `integrations/codex_chatgpt_web/*`, mas o runtime Electron é
  upstream; coordenar com Codex/Vitra).
- Gemini: sem prova V2 (deny explícito); catálogo Gemini limitado a efforts observados.
- Nenhuma validação executada nesta fase por ordem do usuário.

## Plano de validação futura (etapa final, após liberação do Codex)

- Testes herméticos: envelopes V2 exatos, revisão monotônica, quotas de anexo, deny de
  clique em aprovação, merge fail-closed, Gemini deny, conflito/quarentena preservados.
- E2E com provider autorizado + Control Plane real em SQLite temporário: gate
  `awaiting_approval` bloqueia envio; aprovação humana na página libera; catálogo reflete
  a conta; streaming reconcilia por revisão; re-stamp de identidade verificado.
- Fidelidade visual shell (Prisma) consumindo `approval_status`/catálogo sem nova autoridade.


## Fechamento Cobalto 11/10 - fontes atuais, sem homologacao

Autoria e relato historicos acima preservados. Delta atual por arquivo em
[Cobalto-fechamento.md](Cobalto-fechamento.md); contrato concreto do cliente
Edge/CDP e producer/receipt/frame em
[Cobalto-relay-observers.md](Cobalto-relay-observers.md). Cobalto mantem somente
Brisa/Rastro conforme REDISTRIBUICAO_CODEX.md; outros dominios/root/PG preservados.
Fontes implementadas nao significam ambiente provisionado, composicao do review
ou evidencias reais. ZERO homologados; nenhum teste/build/install/lint/QA agora.
