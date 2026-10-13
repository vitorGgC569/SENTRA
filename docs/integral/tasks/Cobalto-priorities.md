# Cobalto - prioridades atuais da matriz (Meridiano)

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.

Prioridades das quatro frentes redistribuidas sao historicas aqui; usar tasks/*-fechamento.md e novo fechamento-backlog.md.


Snapshot: 2026-10-11T10:23:36.836602+00:00. Autorizacao explicita usuario: Cobalto gpt-6.1-sol/high, PID28432 informado pelo root, seis dominios OpenCode transferidos. Meridiano nao recrutou nem reiniciou terminal. ZERO homologados.

Ler primeiro tasks/Cobalto.md (root), este arquivo, tasks/Cobalto-sources.md (nota integral/fontes) e contracts/coverage/requirements. Nota ja conectada conforme usuario; list confirma Cobalto e nota disponiveis a Meridiano. Relato somente por arquivos; nao usar ask-back root.

## Ownership vigente

Cobalto e implementador atual dos dominios Rastro/Brisa/Pacto/Pulso/Selo/Vitra. Nomes anteriores indicam autoria/frente historica. Codex/Nexo/Prisma/Forja/Lume/Tessela/Meridiano conservam ownership; root continua composicao central e code_machine.py. Coordenar Nexo antes de editar guards Postgres compartilhados. Nao duplicar terminal/adapter/autoridade.

| Frente herdada | Escopo transferido |
|---|---|
| Rastro | native_bridge/*; sentra_model_gateway/* EXCEPT browser_host_identity.py; services session_checkpoint.py, web_account_dispatch.py, web_history_* |
| Brisa | browser/*; edge_extension/*; browser_host_identity.py/browser_evidence.py; integrations/codex_chatgpt_web/* |
| Pacto | sentra_mcp/services/mcpb_*/plugin_*/skill_library.py/tool_exposure.py/chat_access.py/action_consent_gate.py; sentra_mcp/tool_policy.py; sentra_code_mode/*; three existing plugin/skill/chat-access dialogs only |
| Pulso | sentra_interop/workflow* and activepieces*; goal_loop.py/conpty_sessions.py/operation_receipts.py; routine_scheduler.py/jobs.py |
| Selo | sentra_quality/*; memory/*; domain authorization/capabilities/telemetry/cost/service modules; executor benchmarks; agree with Nexo before shared Postgres guards |
| Vitra | sentra_remote/*; scripts/commander/*; release workflows; Electron/CLI/launchers; EXCLUDE sentra_canvas/__main__.py/service.py/graph.py and sentra_mcp/server.py |

## Ordem de implementacao e gaps atuais

P0/P1 ordenam trabalho, nao descartam requisito. Fonte presente != integrado != configurado != homologado; avancos recentes abaixo superam antigas buscas negativas.

### CB-P0-01 - P0 - Pacto

Gaps: GAP-01; requisitos: COS-A08, OD-A08.

Ja presente: QuickJS host runner/dispatcher and guest C source exist. Root owns concrete code_machine.py adapter and already gates its public a08 metadata.

Realmente aberto: No QuickJS wasm/SBOM artifact found in scoped source inventory; wasmtime distribution/build awaits authorized final phase. Dispatcher propose/status/list still sets a08_satisfied from engine alone; replay source handles success/failure but RUNNING/UNCERTAIN must never fall through to new run.

Implementar: Fix dispatcher/composition flags: proposals, readiness, inventory never mean A08 satisfied; only actual pinned QuickJS successful receipt with source/result provenance. Store/protect full replay result, enforce no-repeat RUNNING/UNCERTAIN and explicit reconciliation. Finish real guest ABI/source/pins/manifest/build-release plan without build/install now; bounded-js interim cannot close A08.

Contrato/consumer: CodeModeDispatcher/QuickJSWasmRunner/CODE_MODE_SIGNATURE -> root code_machine.py; never duplicate/edit root adapter.

Entrega nesta fase: concrete implementation and exact callbacks/manifest paths; executed evidence remains empty

### CB-P0-02 - P0 - Rastro + Brisa

Gaps: GAP-13, GAP-12; requisitos: COS-G04, COS-A12, OD-CF15.

Ja presente: Root optional/upload scope + Prisma4refs 8MiB/20MiB512KiB chunks/TTL1800 implemented. shell_multimodal stages ONE set/turn, max2images, PDF text export20pages/20000chars, web_uploaded=False until receipt.

Realmente aberto: 2-image composer quota !=4 local refs; PDF textual export !=binary upload; helper present !=rootCLI/model configured transport; whole-set exact recipient upload receipts absent from source-only claims.

Implementar: Complete single-turn dispatcher + approved real provider transport/attachments-set receipt contracts. Retain explicit quota; implement actual applicable full set/binary PDF path rather than N duplicated prompts or silently discarded refs/text-only equivalence. Uncertain dispatch no resend; root composes helper.

Contrato/consumer: dispatch_shell_turn + AttachmentStore bytes + WebSendAuthority/admit/assets receipt -> root OptionalShellServices/CanvasShellRuntime/CLI; content scope/protection checked.

Entrega nesta fase: one request/turn/set, durable intent/set hash/receipt schema, all attachment formats with true compatibility/unavailability reasons

### CB-P0-03 - P0 - Brisa + Rastro + Vitra

Gaps: GAP-14, GAP-15, GAP-04; requisitos: COS-G02, COS-G12, COS-A01, COS-A04, COS-A05, COS-A06, COS-A09, COS-A13, COS-A14, OD-CF15.

Ja presente: VoiceRuntime actual Realtime client + root optional delegates/storage/chunks, scoped calls and transcript persistence; index/message resolver and account catalog helpers exist.

Realmente aberto: Host approval/account-catalog snapshots and verified physical selection upstream not installed/composed; provisional voice text must not become tool-role/verified transcript; extension1.7 identity/restamp pending, at-rest proof/quotas binding need finish.

Implementar: Finish pinned Host patch real endpoints/readers/attestors, exact account/profile/doc/epoch/model-effort selection. Authenticated server receipt for voice transcript/tool-role, status/rebind/stop/revoke/TTL lifecycle; secret refs only. Coordinate identity/restamp with inherited Vitra domain; no provider runtime now.

Contrato/consumer: BrowserEvidence/read_host_* -> Rastro attach_attestors/account catalog/stream_ingest; VoiceRuntime->root optional; Prisma schemas preserved.

Entrega nesta fase: source endpoints and authenticated receipts/selection schema tied to server identity; no DOM/provisional/engine/name inference

### CB-P0-04 - P0 - Pulso

Gaps: GAP-03, GAP-05; requisitos: REE-16, REE-17, REE-18, REE-33, COS-G05, COS-G06, OD-CF16, OD-FF13.

Ja presente: workflow_runtime_host RuntimeProviderHost now has actual temporalio/client and compiled LangGraph factories; workflow_runtime_machine runtime/terminal machine functions exist; ChannelService official APIs Lume and host HTTP source already present.

Realmente aberto: Built-in factories/machines are sources, Nexo/root configure/restore/policy/task capability binding still not confirmed. SDK/worker/server remains runtime prerequisite; fenced terminal_write and channel claim ack same WorkItem/OperationSUCCEEDED need exact composition.

Implementar: Finish owned runtime/terminal bridge/factory signatures and persisted restore bindings, real SDK constructors, per-activity central effect gates, interrupts/signals/reconcile without replay. Pulso channel consumers invoke Lume claim/ack and only ACK after matching central SUCCEEDED.

Contrato/consumer: configure_runtime_machine/configure_terminal_machine/RuntimeProviderHost -> Nexo MachineHost; PulsoShellDispatch/resolvers/schedule_handler -> root; Lume callbacks unchanged.

Entrega nesta fase: concrete factory bindings and safe lifecycle/restoration callbacks; external runtime evidence still deferred

### CB-P0-05 - P0 - Vitra

Gaps: GAP-11; requisitos: COS-G09, COS-A19, REE-GAP-15, REE-GAP-16.

Ja presente: host_facade.py runners/config/admission/release helpers and native backup migration pieces exist; Prisma source asset pins/notices ready.

Realmente aberto: File facade is not root-composed runner lifecycle; reserve-before-effect/crash/replay/full protected receipts, trusted paths/params/quiesce, final key backup and release artifacts need close. Real signed manifests/PKI/native binaries environments unproven.

Implementar: Finish VitraHostFacade durable pre-effect reservation/no repeat after crash, exact owner scope+approved parameters/paths, quiesce and app-exit-only update, real runner callbacks. Carry OpenDots MIT/provenance and Guacamole padarom1.5Apache/SRI/notices in manifest. Coordinate Nexo full-file backup/keys source; no destructive restore/update/runtime/install now.

Contrato/consumer: VitraHostFacade/admit+runner+quiesce/key callbacks -> root; Nexo authority migration/restore preserved; compile/signing external requirements explicit.

Entrega nesta fase: reviewable safe source + manifests/callbacks; no unsigned/digest-only success

### CB-P1-06 - P1 - Selo

Gaps: GAP-06, GAP-12; requisitos: REE-20, REE-21, REE-22, REE-23, REE-24, REE-25, REE-26, REE-27, REE-28, OD-CF17, OD-FF10.

Ja presente: Local policy/identity/audit/learning/langfuse_eval/prompts/datasets/scores/OTLP facades are delivered.

Realmente aberto: Root-requested real build_client configuration/vault/scopes/CAS and external policy/identity/audit/learning/Langfuse/OTLP client composition cut by quota; provider/independent verifier/dataset judge absent or unconfigured.

Implementar: Implement real host client constructors and lifecycle with secret refs/CAS and current central authority, no allow-by-default. Wire reviewed learning to Pacto Skill candidates without activation/grants; bind prompt/dataset/run/score/trace/gate/cost projections and external sinks/proofs. Coordinate native guards with Nexo before shared file edit.

Contrato/consumer: build_client + LearningEvalService/PolicyIdentityAuditService/DiagnosticsService/GrypeReleaseService -> root and inherited Pacto activation, Nexo authority.

Entrega nesta fase: actual client/adapters/config/renew/revoke/cancel/reconcile source + exact contracts, not merely injection callables or local scores

## Itens que NAO devem ser reabertos como codigo ausente

- Prisma chunks512KiB/fullsize4refs e viewer/input/mascots/pins/notices fonte entregues; finalpackage/bundle/runtime sao pendencias distintas.
- Forja finalsource/InputControl/UFO/hybrid/Daytona/Playwright/Guacamole/RustDesk entregues; guests/builds/servicos/peer/config continuam ambientes sem evidencia.
- Tessela rich/doc/ACL/Yjs/native PG guard/watch/rename e permission corrigidos; finaldeps/bundle/PG/PDFium/runtime evidencia pendem.
- Nexo CanvasAuthorityRuntime/shared CP/default store selection/native migration/optional execute_optional gates fonte presentes; full-file keys/backup e native integral integration pending.
- Lume factories/official APIs namespaces/HTTP ingress A2A+channels fonte presentes; preencher claims/Pulso/SDK/provisioning e nao editar Lume files.
- WhatsApp Cloud e API oficial concreta, QR/libsignal e outra variante unavailable. Nao impor libsignal ao Cloud. Se variante QR for explicitamente selecionada independente, requer pin-fonte/scope/noticesGPL3 aprovados antes implementar; nao stub.

## Cobalto-status exigido

Criar docs/integral/Cobalto-status.md com seis secoes (Rastro/Brisa/Pacto/Pulso/Selo/Vitra): fontes lidas e arquivos herdados, fonte que implementou, callbacks e dono da composicao, implementacao/binding/ambiente ainda ausentes, proximo passo, requisito/GAP original, ZERO homologados. Nao substituir implementacao por inventario. Manter codigo e metadata de readiness/proposal/receipt honestos.

Nao testes/build/install/lint/benchmark/QA/runtime, nem novos recrutas/restarts/commits/push/reset/stash. Preview47408/state/window/lock/assets intocados. Encaminhar ao root por arquivos, sem ask-back.
