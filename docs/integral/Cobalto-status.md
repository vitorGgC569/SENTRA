# Cobalto — estado inicial e fechamento das seis frentes

Data: 11/10/2026. Fase: implementação. **ZERO requisitos homologados.**
Ownership ATUAL: `REDISTRIBUICAO_CODEX.md` supera o baseline abaixo.
Cobalto implementa somente Brisa + Rastro; Prisma=Pacto, Lume=Pulso,
Forja=Selo, Tessela=Vitra. Alteração anterior em dispatcher Pacto e suas
pontas abertas estão em `Cobalto-handoff.md`. Os seis inventários abaixo
preservam o levantamento inicial, não atribuem ownership atual a Cobalto.
Este registro separa fontes existentes, implementação faltante, composição de
outros donos e ambiente externo. Não representa execução ou aceitação.
Preview PID47408, janela, lock e assets não serão tocados. Sem testes, lint,
build, instalação, benchmark, QA, recrutamento, commit ou push.

## Fontes atuais

- Nota Maestri `todos-os-projetos-ja-estao-clo`, integral (465 linhas).
- `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md` e
  `docs/integral/tasks/Cobalto.md` (ordem e ownership atuais).
- `docs/integral/{Rastro,Brisa,Pacto,Pulso,Selo,Vitra}.md` e respectivas
  tarefas: entregas anteriores preservadas, expansões continuam no escopo.
- `docs/integral/requirements.md`, `contracts.md`, `coverage.json`:
  matriz Meridiano; snapshots históricos não substituem código atual.
- Estudos referenciados: OpenDots, auditoria/reavaliação dos 37 projetos,
  Chat On Steroids, third-party reuse, Gate5 e checkpoint 09/10.
- Contrato Nexo recebido em 11/10: PostgreSQL nativo via `store.schema(ns)`,
  `store.lock_key(ns)`, `store.connect(ns).raw`; `path_for=None`, sem ATTACH
  nem fallback SQLite; seleção autoritativa protegida; checkpoint de efeito
  antes de cada HTTP/efeito composto. Backup C09 permanece de Nexo.

## Rastro

Fontes existentes: `native_bridge/{web_send,web_delivery,job_store,
conversation_continuation,compact_resume,attachment_upload,
attachment_transport,shell_multimodal,host_boot,stream_ingest,
message_identity,outbox_recovery}.py`; `sentra_model_gateway/{gateway,
web_transport,account_models,turn_authority}.py`;
`sentra_mcp/services/{session_checkpoint,web_account_dispatch,
web_history_store,web_history_assets,web_history_usage}.py`.
O helper multimodal já admite UM conjunto/turno; PDF é export textual
limitado, não transporte do binário. Storage não comprova entrega.

Implementação pendente: transporte real de arquivos maiores/PDF binário,
quotas consistentes e recibo exato do conjunto; revisar consumidores PG
contra contrato nativo atual, ciphertext e checkpoint por efeito.
Composição: root liga dispatch ao modelo e recuperação/attestors; CLI é
domínio transferido Vitra. Ambiente: conta autenticada/host/relay/provider.
Próximo: ler transporte e protocolo completos, fechar payload protegido e
recibo sem reenviar uncertain. Responsável: Cobalto; root/Nexo na composição.

## Brisa

Fontes existentes: `browser/{voice,attachments,streaming,approval,
account_catalog,evidence_http_v2}.py`,
`sentra_mcp/services/browser_evidence.py`,
`sentra_model_gateway/browser_host_identity.py`,
`edge_extension/{content-script,service-worker,selectors}.js`,
`integrations/codex_chatgpt_web/{sentra-upstream.patch,account_catalog.py}`.
VoiceRuntime já sinaliza OpenAI Realtime; segmentos do renderer são
provisórios, nunca tool-role verificado. Chunks e refs locais existem.

Implementação pendente: prova servidor do transcript, snapshots upstream
approval/catalog, identidade 1.7/re-stamp preparado, upload composer real,
proteção at-rest e consistência de quotas; consumidores PG/checkpoints.
Composição: root/Nexo authority wrapper; Prisma cliente preservado.
Ambiente: provider Realtime/conta/host pinado, extensão emparelhada.
Próximo: corrigir transporte/checkpoints/proteção antes de publicar contrato.
Responsável: Cobalto; root/Nexo/Prisma mantêm seus arquivos.

## Pacto

Fontes existentes: `sentra_code_mode/{dispatcher,quickjs_runtime,
bounded_js,composition,artifact_config,schema}.py`, guest C/ABI/build.sh;
`sentra_mcp/services/{mcpb_lifecycle,mcpb_supervision,skill_library,
tool_exposure,chat_access,action_consent_gate}.py`; `sentra_mcp/tool_policy.py`.
Guest tem fonte/ABI e pipeline, mas binário/SBOM construídos não são alegados.

Implementação pendente: proposta/status/inventory atualmente atribuem
`a08_satisfied` pelo engine; resultado completo protegido em replay,
RUNNING/uncertain sem reexecução, adequação PG/escopo central.
Composição: `sentra_canvas/code_machine.py` pertence ao root, não duplicar;
callbacks de inner tools e configuração artifact ficam na autoridade central.
Ambiente: wasmtime e guest WASM/SBOM materializados na etapa futura.
Próximo: corrigir semântica de execução e reserva/resultados duráveis.
Responsável: Cobalto (módulos Pacto); root (adapter/composição).

## Pulso

Fontes existentes: `sentra_interop/workflow_runtime{,_host,_machine}.py`,
`workflow_channel_triggers.py`, `workflow_shell.py`, `workflow_channels.py`,
`workflow_nats.py`, `workflow_temporal.py`, `workflow_langgraph.py`,
`workflow_scheduling.py`, `activepieces_scheduling.py`;
`sentra_executors/{goal_loop,conpty_sessions,operation_receipts}.py`;
`sentra_mcp/services/{routine_scheduler,jobs}.py`.

Implementação pendente: SDK/factory/restore/policy coerentes no host,
terminal_write fenced; ack de canal somente após Operation SUCCEEDED no
mesmo WorkItem; PG nativo nas projeções e reservas, proteção de payload.
Composição: MachineHost/control/runtime são Nexo; root liga facades/resolvers.
Ambiente: Temporal/LangGraph/NATS/AP e canais/vault conforme configuração.
Próximo: ler máquinas/triggers/gate completos e publicar ligações concretas.
Responsável: Cobalto; Nexo/Lume/root nos contratos comuns.

## Selo

Fontes existentes: `sentra_quality/{learning_review,langfuse_eval,
otel_langfuse,audit_anchor,policy_veto_chain,identity_registry,
release_gate,grype_scan}.py`, `memory/{store,costs}.py`;
`sentra_mcp/services/{learning_eval,policy_identity_audit,memory_costs,
diagnostics,grype_release,authorization,capabilities,telemetry}.py`.
Learning/eval e pipeline locais são fontes, não prova de export Langfuse.

Implementação pendente: cliente real prompts/datasets/runs/items/scores,
OTLP configurado por vault/scopes/CAS; proteção/política externa e guards PG.
Composição: root pediu build_client; serviços centrais/budgets de Nexo.
Ambiente: Langfuse/collector, OPA/FGA/Keycloak/SPIRE/Tessera/immudb/Grype.
Próximo: alinhar ownership PG ANTES de editar guards comuns; fechar clientes
configuráveis com indisponibilidade explícita e intent durável.
Responsável: Cobalto; Nexo confirma ownership antes de toque comum.

## Vitra

Fontes existentes: `sentra_remote/{host_facade,guest_runners,
coordinated_backup,coordinated_upgrade,shell_migration,optional_providers,
sidecar_manifests,setup_states}.py`; `scripts/commander/{extension_identity,
release_assets,release_doctor,release_signing,clean_install_plan}.py`;
`sentra_cli/{repl,shell_bridge,maintenance}.py`; Electron/native launchers.

Implementação pendente: reservation-before-effect e crash/replay no facade,
parâmetros/caminhos host-trusted, quiesce antes de restore/update/migração;
CLI/gateway selecionam mesma autoridade configurada; release guest/sidecars.
Composição: root injeta facade; backup PG/crypto-file C09 pertence Nexo.
Ambiente: binários native/WASM, signer legítimo, SDKs/pacotes/manifests finais.
Próximo: fechar facade e contrato release sem executar geração/build/re-stamp.
Responsável: Cobalto; Nexo/root mantêm autoridade/configuração central.

## Regras de andamento

Atualizar por arquivo conforme implementação, mantendo pendências de composição
e ambiente separadas. Request_key permanece durável; bytes/intenções protegidos;
RUNNING/uncertain exigem reconciliação, nunca reenvio automático. Só Control
Plane cria Run/WorkItem/Operation/Grant. Validação futura depende da liberação
do root após TODAS as implementações, sem evidência alegada nesta fase.


## Atualizacao 11/10 - composicao relay e cliente fisico

Ownership final: Brisa/Rastro Cobalto; demais quatro dominios preservados. Fontes
atuais e relato por arquivo em `Cobalto-fechamento.md`; contrato Edge/worker/
frames em `Cobalto-relay-observers.md`. Cliente fisico CDP e producer implementados
nesta rodada, alem de atestacao full-body/parent/scope e helper requested_model/
effort. Fonte root em `Codex-composicao-relay.md` liga helper/CP/queue/original
grant/result sem resend. Nao foi editada por Cobalto.

Proximas pendencias de composicao: Codex conecta objeto EdgeRelayObservers e
availability por projeto, review/enrollment host-only e stores atuais ao boot;
Tessela liga/distribui CLI e extensao restamp no mesmo helper; Nexo preserva
factory/capsule/PG/crypto. Ambiente externo (Edge CDP, perfil/conta/review, provider
Realtime e websocket) nao foi disponibilizado ou validado por esta fonte. Backlog
Meridiano e clauses continuam integros; nao reduzir opcional a assinatura/stub.
ZERO homologados; testes/build/install/lint/QA e preview permanecem intocados.
