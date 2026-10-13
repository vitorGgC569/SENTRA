# Contratos integrais — Meridiano

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.


Data: 11/10/2026. Base informada pelo usuário: `3639a2e296428db8e3bb0839fac87d9237ec8592` em origin/main. Fonte de implementação: árvore compartilhada, sujeita a mudanças concorrentes. Nada homologado. Este documento registra contratos recebidos, código lido e propostas que ainda exigem composição; não atribui implementação a uma assinatura.

## Ordem e ownership

Implementação integral primeiro; testes/build/lint/benchmark/QA somente depois de todas as frentes integradas e liberação do Codex. Meridiano edita documentação, não código. Não recrutar, commit/push/reset/stash nem remover alterações alheias. Componentes opcionais continuam requisitos: fluxo real configurável, health/indisponibilidade explícita, autorização, recuperação, instalação e remoção. Negação segura é comportamento necessário quando falta configuração, mas **deny-only não implementa a capacidade**.

As expansoes integrais permanecem em docs/integral/tasks/Nome.md. Protocolo ATUAL: redistribuicao Codex vigente; nao relancar/recrutar nem enviar prompts aos OpenCode. Progresso por arquivos, sem ask-back sincrono. HISTORICO: aviso run->PowerShell seguido por TUI persistente; a antiga instrucao de relancamento nao esta vigente.

| Dono | Ownership preservado | Expansão autorizada / parceiros |
|---|---|---|
| Codex | service.py, graph.py, server.py, configuração raiz/pyproject e composição | HTTP/Canvas/Control Plane; registrar ações reais dos serviços |
| Nexo | sentra_core, sentra_runtime, serviços centrais indicados na nota de coordenação | Postgres nativo/migrações/multiusuário; Spaces/Dots/conversas/coordenação |
| Prisma | main.jsx, desktop.css, componentes shell/conversa, package UI | Voz cliente com Brisa; viewer Guacamole com Forja/Codex; ProjectDocuments de Tessela |
| Forja | sentra_executors exceto Goal/ConPTY/receipts/benchmarks | Providers reais e InputLease; terminal Daytona com Pulso |
| Lume | sentra_interop exceto workflow/activepieces | Slack/Telegram/WhatsApp adapters/protocolo com Pulso |
| Tessela | sentra_collab, project_review/project_documents, document-/collaboration- UI | Colaboração e ACL por documento ligada ao shell |
| Cobalto (frente Rastro, autoria anterior Rastro) | native_bridge, model_gateway exceto browser_host_identity, checkpoint/web dispatch/history | Continuidade/outbox/anexos com Brisa e shell |
| Cobalto (frente Brisa, autoria anterior Brisa) | edge_extension/browser/browser identity/evidence/integrations Web | Voz WebRTC/provider/provas com Prisma e Codex |
| Prisma (frente Pacto, autoria anterior Pacto; takeover Cobalto historico) | mcpb/plugin/skill/exposure/chat_access/consent/tool_policy/code_mode/UI existente correspondente | QuickJS bounded real; learning revisado recebido de Selo |
| Lume (frente Pulso, autoria anterior Pulso; takeover Cobalto historico) | workflow/activepieces, Goal/ConPTY/receipts, scheduler/jobs | Temporal/LangGraph runtimes; canais/trigger/outbox com Lume |
| Forja (frente Selo, autoria anterior Selo; takeover Cobalto historico) | quality/memory/authorization/capabilities/telemetry, módulos novos de política/identidade/audit, benchmarks | Learning revisado, Langfuse prompts/datasets/evals; revisão Skill com Pacto |
| Tessela (frente Vitra, autoria anterior Vitra; takeover Cobalto historico) | remote/commander/workflows/electron/launchers/CLI/releases | Instalação/backup/restore/staged update/migrações/notices |

Ownership deste quadro deriva de `SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md`; expansão não concede edição dos pontos centrais nem resolve sobreposições por conta própria. Novos módulos de Selo em domínio reservado a Nexo exigem acordo de arquivo explícito.

## C01 — Shell HTTP e serviço central

Contrato recebido de Prisma/Nexo pelo usuário nesta sessão:

```python
ControlPlaneService.shell_dispatch(owner: str, *, project_id: str, action: str,
    payload: dict[str, Any], request_key: str | None = None) -> dict[str, Any]
Canvas.shell_bridge  # nome recebido; assinatura completa ainda deve ser publicada por Codex
```

Única rota shell: `POST /api/shell/bridge`, JSON e bearer local existente. Identidade/owner/principal/Grant/permissões e caminhos derivam do servidor; nunca do renderer. Alias legado `ws` normaliza a `project_id`; resposta canônica emite `project_id`. Vincular Space ao workspace Canvas por ID persistido e conferir a associação em cada chamada. Paginação e limites do handler existente permanecem obrigatórios.

Leituras: `home`, `space_list`, `space_get`, `dot_list`, `conversation_list`, `message_list`, `events`. Mutações: `space_create`, `dot_create`, `dot_update`, `conversation_create`, `message_send`, `coordinate`, documentos enumerados em C03. Mutações preservam `request_key` e deduplicam intenção imutável, não só a chave. Todos os IDs passam por escopo autenticado. Registro de novas ações de voz/plugin/skill/consent depende de allowlist explícita na composição Codex, não de prefixo genérico.

```json
{"ok":true,"value":{},"request_key":"chave-original"}
```

Leituras usam o mesmo envelope. Erro: `{"error":"motivo sanitizado"}` e HTTP adequado. `message_send` devolve `conversation_id`, `message_id`, `status` (`queued`, `dispatched`, `waiting_approval`; `uncertain` em falha ambígua), `operation_id`, `receipt_id`. Entrega concluída exige receipt. Timeout/reply perdido conserva a mesma chave para consulta/dedupe; não duplica envio.

**Composição pendente:** assinatura completa de Canvas, action schemas/retornos por ação, contexto autenticado, tratamento de async/erro/limites e inscrição da rota. Contrato recebido não é evidência de rota funcional. Prisma preserva PTY ao alternar conversa/Canvas.

## C02 — Coordenador, Dots/Spaces e continuidade

Dot especializado mantém modelo/effort realmente disponíveis, instruções, ferramentas autorizadas, histórico e limites. Dot Coordenador propõe equipe/relacionar/delegar/handoff/pausar/reorganizar em intenção estruturada allowlisted. Prosa é contexto, nunca autorização. Efeitos passam por admissão/aprovação durável do Control Plane; estado pendente não executa efeito.

Chat/Canvas/CLI/Desktop projetam mesmos agentes, Run/WorkItem/Operation/Grant e relações. IDs externos de protocolo/conversa não substituem IDs centrais. A→B conserva agente/filhos, Run/WorkItem/contexto, leases/grants/proveniência, fases open→summary→exclusive claim→preflight→commit→publish/abort e transcrição original. Operação incerta permanece incerta; compactação e undo de plano não desfazem efeitos físicos.

Migração Canvas→Space é repetível, preserva project IDs, sem renomear/copiar diretórios. Vitra fornece lifecycle do journal; Nexo persiste vínculo e Codex compõe. Recuperação precisa distinguir fase parcialmente aplicada de committed.

## C03 — Documentos e CRDT

Namespace central `canvas_collaboration`. Ações acordadas: `document_list`, `document_get`, `document_create`, `document_save`, `document_history`, `document_restore`, `document_delete`; sessões Yjs exigem enumeração exata por Tessela. Payload snake_case: `project_id`, `space_id`, `document_id`; `expected_revision` CAS, `mutation_id` dedupe e receipt para escrita. Restore cria nova revisão. Draft/source/export/hierarquia/exclusão/conflito precisam funcionar sem executar previews. Autosave diferencia dirty/saving/saved/error/conflict, descarta resposta antiga de outro documento e preserva draft ao falhar ou navegar.

Contrato React Tessela: `bridge({action,...payload})`; props `spaceId`, `projectId`, `documents`, `onRefresh`, `onError`. Prisma relatou ProjectDocuments vivo com draft guards; isso é relato de implementação sem execução de QA.

Grant `canvas.collab.read/write`, WorkItem e sessão devem ficar presos a workspace+Space+documento. Autorização de documento não abrange todo Space. Ticket nonce de uso único; reautorizar conexões/update/precommit e cancelar após revoke. Owner bearer fica no host, nunca browser. CRDT guarda apresentação/conteúdo versionado, nunca Run/Grant/lease/custo. Persistência snapshots/CAS/histórico converge com a autoridade central.

Código lido atual: `CollaborationAuthority(control, *, owner, clock)` e `issue(*, workspace_id, principal_id, work_item_id, principal_type='user', permission='read', ttl_seconds=300)` ainda têm escopo workspace; `commit(*, context, expected_revision, snapshot, presentation)` guarda apresentação. `Canvas.collab_session`, `collab_prepare`, `collab_disable`, `collab_host_call(method, params)` existem. `CentralCollabBridge` Node fala com `/api/collab/host` via bearer privado; métodos resolveGrant/checkGrant/consumeNonce/loadSnapshot/commitSnapshot. Essa é ponte de host existente; não expor credential owner nem inventar segunda rota pública para o renderer.

**Pendência real:** escopo por documento/Space e assinatura final de Tessela. Escolher família wire de Yjs explicitamente: estudo compara @y/y 14 RC/@y/protocols RC com yjs13/y-protocols/Hocuspocus4.7. Snapshot upstream não prova compatibilidade. Undo por origem, relative positions, diffs/state vectors, awareness clock/TTL/identity, reconexão e persistência continuam requisitos. Redis multi-host opcional continua fluxo requerido quando configurado, sem leases de execução CRDT.

## C04 — Máquinas e fronteira física

Código lido em `sentra_runtime/contracts.py`:

```python
Machine(machine_id, kind, owner_principal_id, capabilities)
Capability(capability_id, description, risk_level)
OperationRequest(operation_id, principal_id, machine_id, capability_id,
                 work_item_id, idempotency_key, arguments)
OperationResult(operation_id, state, evidence, error)
```

Estados OperationResult: ACCEPTED/RUNNING/SUCCEEDED/FAILED/CANCELLED/UNCERTAIN. ACEITO, ACK e stdout de modelo não comprovam efeito. Intenção/fingerprint imutável, admissão transacional, grant atual e fencing no I/O antecedem efeito. Evidence precisa conter bytes ou referência recuperável, digest e origem, não somente hash.

Código lido `MachineHost(control, *, owner)`:

```python
dispatch(*, workspace_id, work_item_id, machine_id, capability_id,
         operation_id, arguments, idempotency_key=None) -> dict
observe(*, workspace_id, operation_id, as_owner=False) -> dict
inventory(workspace_id) -> list[dict]
configure_session(*, workspace_id, workspace_root, agent_id, kind, provider_config)
```

O host usa loop próprio existente e valida associação WorkItem/Run/máquina/agente/workspace. Observe recupera receipt; ausência de resultado retorna UNCERTAIN e late_return diagnóstico. Nenhum dispatcher paralelo.

Contrato recebido de Forja e confirmado por leitura de `sentra_executors/integral.py`:

```python
configure_executor(host, *, workspace_id, workspace_root, agent_id,
                   kind, provider_config)
```

Sync chama o loop MachineHost e persiste suas configurations. EXECUTOR_KINDS: windows_uia_semantic, windows_guest_uia, windows_guest_lifecycle, windows_guest_artifact, windows_hcs_native, gvisor_workload. Config não executa provider I/O nem concede grants. Dispatch/cancel/observe/reconcile/cleanup usam CentralExecutorFactory existente. Forja vai incluir InputLease CAS/epoch/TTL/handoff em control.store consumido por providers, observação híbrida screenshot+UIA, persistência/recovery Playwright e Computer Use AT-SPI Daytona SDK pinado. **Itens futuros recebidos, não declarados presentes.**

Desktop Windows GUI isolado e HCS headless são entregas distintas. PID/cwd/JobObject não oferecem isolamento OS completo. Revalidar seletor/PID/janela antes da ação; cache e retry de observação não autorizam repetir clique. Guacamole view/control/input/clipboard/files/audio têm capabilities separadas; playback é só visual. Prisma/Codex compõem viewer/playback/stream existente de Forja. Terminal Daytona e ConPTY permanecem Pulso, com ownership/handle/process tree, streaming head/tail/overflow, input/resize/close e GC sem matar processos alheios.

## C05 — ACP/A2A/MCP/Registry e conectores

Código lido `CentralInteropAdapter(*, control, run_id, owner, machine, principal_type='agent')`; `protocol_gate(*, capabilities=None, constraints=None)` cria CentralDurableIntentAuthority existente; `bind_provider(capability_id, handler, *, constraints=None)`, `register(registry)`, `start(request)`. Não repetir como atual a lacuna histórica de passar control.durable bruto. Provider ausente/fence não composto continua bloqueado e não conta como integração operacional.

Lume: sessão ACP completa por versão anunciada (new/resume/close/list/delete/prompt/cancel/config/models/usage/structured/terminal/file/elicitation), partial updates distinguem absent/null/value, IDs/cursor/reattach duráveis. Registry seleciona binary/npx/uvx por OS/arch, pin/hash/ambiente reservado/process ownership e rollback de instalação. A2A Task/context/cards autenticados, chunks append/final bounded/provenance, input_required/push/SSE/reconnect/revoke; persistir mapa de IDs e artefatos completos. MCP SDK TS real por revisão, tools/resources/prompts/subscriptions/input_required/pagination/error/reconnect; retry interno respeita Operation.

Slack/Telegram/WhatsApp: usuário designou Lume adapters/protocolo e Pulso triggers/Activepieces/workflows. ConnectorConnection guarda provider/principal/workspace/secret refs/scopes/renew/revoke/idempotency support. Inbound autentica webhook/bot/signature/replay e allowlist; identidade externa não concede grant. Outbound usa outbox central e receipt por destinatário; ACK de serviço não é conclusão de tarefa. Disable remove subscription externa com receipt. Canais não herdam prova/trust ChatGPT. WhatsApp e libs selecionadas precisam de manifesto/notice e distribuição opcional explícita; não incorporar dependência de licença desconhecida por nome.

**Ainda proposto:** schemas/signatures exatos de canais, formato de receipt por provider e composição HTTP; publicar em Lume.md/Pulso.md e fechar com Codex.

## C06 — Temporal/LangGraph e scheduling

Pulso implementa runtimes reais SDK/worker configuráveis, não apenas worker checkpoint local. Workflows/subflows subordinados a Run/WorkItem, Operation separada por atividade; persistir IDs externos, definition/worker version e compatibilidade. Temporal history/retries classifica nonretryable/transient/uncertain; resposta incerta reconcilia antes de novo efeito. LangGraph checkpoint parent/pending writes, interrupt/resume/fork, no-progress timeout, memória namespace/TTL; time travel não desfaz efeito.

Routine ocorrência central durável única, cron/timezone/DST, calendário/day-of-week, misfire, nonoverlap, pausa por falhas/intervenção e budgets. Intervalo após conclusão é modalidade distinta de cron. Notificação marca entregue só após receipt, nunca antes de send. NATS outbox/inbox/ACK após persistir, replay por cursor/tempo, finite broker dedupe vs central durable dedupe, bounded queues/backoff/retention por classe; terminal streams não seguem retenção indiscriminada de comandos.

**Pendências:** adapters/runtime definitions e assinatura `configure`/`start`/`advance`/`signal`/`cancel`/`observe`/`reconcile` por Pulso. A presença de `CheckpointedWorkflowWorker` e `SubagentWorkflowBridge` não prova Temporal/LangGraph operantes.

## C07 — Voz WebRTC

Prisma publicou proposta (não contrato de provider concluído):

```text
voice_start(offer_sdp, microphone_opt_in, conversation_id)
    -> {call_id, answer_sdp, status}
voice_status -> transcript
voice_stop / voice_revoke -> idempotentes
```

Prisma implementa cliente/media controls; Brisa fornece sessão/sinalização/provider/transcript/evidência; Codex compõe allowlist/capability no bridge. Vincular call_id a conta/sessão/principal autenticado/project/Space/conversa/Run/WorkItem e generation; browser não escolhe owner. Microfone opt-in explícito, escopo/consentimento provider, stop/revoke/cancel/reconnect bounded; tool calls do áudio continuam centrais. Transcript por message/revision e proveniência; recibo do provider e status real, nunca afirmação pelo modelo. ICE/SDP/config/credenciais não devem vazar; token restrito não é bearer owner. Sem provider configurado, mostrar motivo; este fallback não encerra requisito de provider implementado.

**A fechar cedo Brisa/Codex/Prisma:** action schemas finais, session expiry, limites SDP, stream/poll/pagination, capabilities, provider configuration, error/receipt model e integração com conversa existente. Referências de anexos apenas após upload receipt real, conforme contrato Rastro/Brisa.

## C08 — Plugins/Skills/Code Mode e consentimento

Pacto mantém MCPB ZIP bounded/traversal/symlink/case-collision/Windows names, manifests/source/pin, stdio/HTTP/OAuth PKCE/vault/health/restart/supervisor/sandbox/uninstall, conflitos até para provider disabled e tool publication/schema limits. ToolHive NoopPolicyGate allow-all não é autorização por tool call; catálogo seletivo busca só conjunto já permitido.

Skills immutable por SHA/review/provenance/manifests/capabilities, import size/files bounds, activation/update/revoke/rollback, WorkItem binding/progressive disclosure; skill nunca cria grant/cwd/secret access. Selo learning gera sugestão revisável com origem/validade; Pacto ativa só após revisão/pin e grant preexistente. Nenhuma publicação automática de aprendizado.

ChatTrust/block é filtro adicional: block vence, unknown nega modo estrito, successor só herda depois de commit comprovado. RequestCorrelation prova origem exata MCP request ID↔Web message metadata↔conversa/doc/epoch, nunca grant e sem atribuição temporal. Approval ChatGPT e aprovação SENTRA são estados/autoridades diferentes. Dois consentimentos read/action com clique owner/session/body/target/revision e revogação em voo.

**A08 gap explícito:** `QuickJSWasmAdmission.execute` lido só lança CodeModeDisabled. `docs/integral/Pacto.md` relata Dispatcher também deny-only. Isso não cumpre implementação integral. Usuário vai reabrir Pacto via task file. Exigir runtime QuickJS WASM pin+SBOM, sem IO/imports host, fuel/CPU/mem/wall/tool calls/source/results bounded, watchdog/cancel. Cada tool usa OperationRequest/Grant/fencing. Nenhum fallback eval/Node VM/intérprete no processo privilegiado. Não declarar auditado sem validação final futura.

## C09 — Identidade/política/audit/learning/avaliação

SPIRE SVID/attestation/rotation/subscriptions/trust bundles mapeiam Principal; Keycloak login/OIDC/logout/revoke/token-exchange audience/session lifecycle; OpenFGA model version/ListObjects/ReadChanges/cache invalidation/transitive scopes; OPA bundle revision/activation/rollback/undefined/timeout fail-closed e redacted decision IDs. Serviços consultados não criam segunda fonte de grants. Logout/revoke alteram novas admissões e conexões abertas.

Tessera inclusão/consistência/checkpoints assinados/quorum/witness independente e divergência; immudb verified set/get/linear proof/trusted previous state/transaction export. Append/ACK/hash chain local não provam completude; instrumentar fronteira de efeito e guardar prova ligada ao evento/receipt. OTel bounded persistent queues/batch/retries/cardinality/retention/loss/redaction correla IDs; exportação falha não repete efeito nem falseia sucesso operacional.

Selo learning/Langfuse: prompts version/labels/config, datasets expected input/output e run-items/trace, scores tipados/correções humanas, experiência com escopo/origem/validade/resultado, QualityGate/custos centrais. Dataset versiona ambiente/provider/prompt/model/tools/verifier; avaliação independente de agente; resultados probabilísticos identificados. Windows Arena híbrido UIA/visão e VM/reset/trajectory; OSWorld métricas compostas/short-circuit/structured/eval checkpoints; WindowsWorld verificadores de arquivo/tabelas/CSV e cross-app checkpoints. Benchmark fica fora runtime de produto e não executa nesta fase.

**Contrato ainda a receber:** Selo→Pacto sugestão/revisão/ativação SkillPack; Selo→Codex traces/prompts/datasets/eval e AuditHost/config/dispatch/delivery/proofs. Grype real scanner/Syft inventory/SBOM digest/freshness/fix/diff/report do pacote final, não só parser.

## C10 — Postgres, migração e distribuição

Código lido `create_control_plane_store(state_root, *, backend='sqlite')`: só SQLiteControlPlaneStore; outros backends lançam UnsupportedControlPlaneBackend. Interface atual connect→sqlite3.Connection, path_for(namespace) e várias consultas/ATTACH/BEGIN IMMEDIATE são SQLite-específicas. Nexo deve entregar backend Postgres nativo com migrations/schema/transações/locking/fencing/tenant isolation, adaptar consumidores (grants/runs/workitems/docs/audit/etc.), preservar modo local e explicitar failover/recovery. Não compartilhar SQLite pela rede nem anunciar suporte por aceitar uma URL.

Vitra/Nexo: backup coordenado DB+artefatos+config+keys, consistent checkpoint e restore verificável futuro, upgrades schema/app/extension/MCPB/WebModels/sidecars, rollback e sessions intactas. Vitra journal Space linkage preserva IDs e staged update aplicado no fechamento sem matar ConPTY. Serviços opcionais têm install/health/repair/renew/recovery/remove reais com prerequisitos visíveis.

Release: pins originais/SHA/hash/imagens/transitivos/SBOM, LICENSE/NOTICE por arquivo/módulo/modificação, assinatura legítima e MSI/clean install futuro. CopilotKit MIT não torna Intelligence gratuito/obrigatório; Anil licença incerta no estudo bloqueia cópia, permite implementação original de ideias; feder sem root SHA no estudo impede promover fontes main a pin; avisos Apache/AGPL/BSL/enterprise/GPL/LGPL preservados conforme componentes concretos. Não usar números históricos de clones como prova do estado atual.

Setup distingue LOCAL_MCP_READY/TUNNEL_ONLINE/CHATGPT_APP_OBSERVED/TOOLS_AUTHORIZED/VERSION_CURRENT e extension installed/paired/login/revoked/profile ID. Preparação local não prova instalação na conta. Doctor interno separado de export redigido com preview (IPs/URLs/paths/usernames/email/títulos/projetos/secrets), retention/exclusão. Não exportar cookies/credenciais/gravação indiscriminada.

## Dependências de integração e fechamento futuro

1. Nexo assinatura central/namespace/migration → Codex HTTP/Canvas → Prisma shell/CLI Vitra; grants/context sempre servidor.
2. Tessela document schemas/ACL/CAS → Nexo association project/Space → Codex bridge → Prisma ProjectDocuments; Yjs host protocol sem credencial renderer.
3. Brisa proof/voice provider → Rastro outbox/continuation/history → Nexo dispatch → Codex bridge → Prisma call/transcript; nenhuma entrega sem receipt.
4. Lume protocol/providers ↔ Pulso workflow/triggers/notifications → Forja effect boundary → Codex composition; runtime externo nunca cria autoridade independente.
5. Selo review/learning → Pacto SkillPack/Code Mode/exposure → Codex composition; prompts/skill/catálogo não autorizam efeito.
6. Nexo/Postgres + todos manifests/contracts → Vitra package/backup/update → Codex liberação final; somente então validar requisito a requisito com evidence contemporânea.

Nada nesta lista foi homologado. Cada proprietário deve registrar assinatura concreta, arquivos, retorno/error schemas, dependências reais e plano de validação futura em seu relatório. Meridiano solicita expansão de lacunas ao principal e mantém coverage sem declarar aprovação por leitura.

## Atualizacao concorrente ? leitura posterior e relatos dos donos

- C01: assinatura keyword-only acima foi confirmada no codigo. ControlPlaneService instancia ShellCoordinatorService e fornece attach_shell_runtime(runtime). Handler POST bearer em __main__.py ja encaminha a.shell_bridge(p) e limita body a 800000 bytes. Na busca posterior, Canvas.service ainda nao mostrava declaracao shell_bridge: composicao em andamento, sem executar rota.
- C10: primeira leitura do store era SQLite-only. Leitura posterior adiciona ramo postgres/postgresql importando .postgres_store e ControlPlaneService.from_store(state_root, *, backend, dsn, tenant_id, principal_id). postgres_store.py nao foi encontrado naquele instante. Nexo trabalha concorrente; nao promover ramo/config a backend completo. Snapshots separados em coverage.json.
- C06: Pulso.md declara explicitamente workflow_temporal sem servidor Temporal e workflow_langgraph sem runtime LangGraph. Suas classes semanticas nao fecham a expansao de runtimes autorizada. PulsoShellDispatch fornece 18 acoes exatas; Codex precisa registrar/resolver e ligar providers centrais.
- C09: Selo.md agora reporta otel_langfuse.py exporter opt-in e servicos de policy/memory/audit. Isso substitui busca anterior sem exporter; nao demonstra prompts versionados/datasets/evals/correcoes humanas/learning revisado, ainda expansion tasks Selo/Pacto.
- C08: Pacto.md relata Dispatcher.execute deny-only. Usuario rejeitou esse resultado para A08 e reabre mesmo terminal pelo arquivo de tarefa.
- C02: Rastro.md publica AccountModelCatalog.observe/select/cached_view, CompactResumeService.begin/preflight/commit/abort/status e recovery somente observacao. Faltam account_attestor/assistant_attestor reais de Brisa e composicao shell/CLI/boot; guard DENY nao entrega modelo operante.
- C03/C07: Prisma informa ProjectDocuments vivo com draft guards e cliente WebRTC em implementacao; voice provider/capability ainda precisam Brisa/Codex.

### Lacunas adicionais dos relatos, alem dos handoffs anteriores

1. A12: Brisa descreve anexos por fingerprints; Rastro afirma READY_LOCAL nao equivale a upload. Conteudo/ref recuperavel, upload real ao composer e receipt exato continuam implementacao requerida (Brisa/Rastro/Prisma).
2. Host evidencia: Brisa relata ausencia de /v1/sentra/approval-snapshot e /v1/sentra/account-catalog; read_host_* fica deny. Implementar host em seu ownership e compor Codex/Vitra. Extensao 1.7.0 com source-hash/bootstrap antigos 1.6.52 exige coordenacao release de Vitra, sem executar build agora.
3. A13: relato content-script revision por indice de mensagem precisa vinculo a message_id logico duravel quando DOM virtualiza/reordena/recarrega. Indice/frame nao substitui identidade/revisao e overflow recuperavel; Brisa/Rastro precisam fechar contrato.

Relatos completos dos seis OpenCode foram preservados como claims com hash em coverage.json. Nenhuma afirmacao do dono e promovida a homologacao; leitura posterior nao altera a regra de nao validar.

## Contrato Lume recebido e confirmado por leitura

InteropProviderMachine em sentra_interop/provider_machine.py:

```python
InteropProviderMachine(control, *, owner, agent_id, machine_id,
                       workspace_root, kind, configuration)
catalog()
dispatch_request(*, run_id, work_item_id, machine_id, capability_id,
                 operation_id, arguments, idempotency_key=None)
submit(*, run_id, request)  # async
shutdown()                # async
```

Factory ACP/A2A/MCP para MachineHost existente, sem criar WorkItem/Grant nem iniciar agente implicitamente. Config host enabled, executable pin/consent para ACP/MCP, secret refs vault e destination/identity/process derivados do host. Catalog reporta transport_ready unverified e validation_status pending.

Lume informa em implementacao: projections cifradas ControlStore; ACP lifecycle/config/usage/absent-null preservados e elicitation duravel; A2A HTTPS AgentCard pin/context/continuidade/SSE/chunks/push; SDK MCP TS real 2.3.1 por revisao sem auto-retry/auto-fulfillment; registry instalacao real. Assinatura enviada a Nexo para composicao. Nada homologado.

Canais escolhidos: Slack/Telegram/WhatsApp **Cloud via APIs oficiais**, signature/replay/allowlists/outbox+receipts, alinhamento Pulso. Essa escolha e estado em andamento supersedem busca anterior sem adapters. Nao impor libsignal por analogia com feder; inventariar somente dependencias concretamente selecionadas e notices de distribuicao. Contratos finais serao publicados por Lume em docs/integral/Lume.md.

## Atualizacao Tessela - contrato implementado recebido

Contrato recebido em 11/10/2026 e confirmado por leitura estatica de codigo. Nao foram executados testes, build, lint, benchmark ou QA. GAP-07 anterior de escopo workspace-only foi superado no novo ProjectDocuments; watch renames e evidencia final permanecem pendentes.

```python
ProjectDocuments(control, *, owner, resolve_space, resolve_run=None, clock=time.time)
dispatch(action, payload, *, project_id, principal_id,
         principal_type="user", work_item_id=None)
host_call(method, params)
```

Allowlist completa: document_list, document_get, document_create, document_save, document_history, document_restore, document_delete, document_diff, document_export, document_session, document_session_close. Namespace canvas_collaboration; project_id canonico corresponde ao workspace_id das metadata do WorkItem, com space_id/document_id e Grants read/write por tarefa/documento. Escritas: expected_revision CAS, mutation_id ligada a intent fingerprint, Operation e receipt; hierarquia/ciclos, tombstones, historico imutavel e restore cria nova revisao. Snapshots Yjs binary/precommit pertencem a mesma historia.

Callbacks privados em /api/collab/host: documentResolveGrant, documentCheckGrant, documentConsumeNonce, documentLoadSnapshot, documentCommitSnapshot. CentralCollabBridge seleciona callbacks document quando documentId presente. Canvas _document_service compoe ProjectDocuments, dispatch repassa identidade de servidor e collab_host_call delega a DOCUMENT_HOST_METHODS; leitura confirma pontos de composicao, sem prova runtime. Owner credential nunca vai ao renderer.

UI named export ProjectDocuments({bridge, spaceId, projectId, documents, onRefresh, onError, onDirtyChange}); TipTap 3.31.3 Markdown/TableKit, CodeMirror 6, IndexedDB drafts, estados dirty/saving/saved/error/conflict e guard onDirtyChange. Prisma consome props/bridge; nao edita componentes document-* pertencentes a Tessela.

Ownership: Tessela implementa servico/documentos/collab/componentes; Nexo preserva associacao Space/project e Control Plane; Codex compoe HTTP/Canvas/identity, Prisma encaixa shell e dirty-navigation guard. Compatibilidade com Postgres/migracoes de Nexo continua dependencia transversal; presenca de SQL SQLite/ATTACH no servico nao prova multiusuario.

Pendencias declaradas: finalizar watch/renames e entregar docs/integral/Tessela.md com contratos finais. Validacao somente na etapa final liberada pelo Codex. Nenhum requisito promovido a homologado por este relato.

### Alinhamento de contrato documento/shell ainda pendente

Leitura posterior confirma Canvas.shell_bridge(self, payload) presente: identidade derivada de servidor, project_id/ws consistentes, dispatch DOCUMENT_ACTIONS para ProjectDocuments e restante para control.shell_dispatch. Isso supera registro anterior de facade Canvas nao encontrada; nao houve execucao HTTP.

Diferenca textual: collaboration-document.js envia document_session com permission='write', enquanto Canvas.shell_bridge rejeita permission globalmente. O contrato central exige permissao derivada da sessao/grants, nunca autoridade do renderer. Codex/Tessela/Prisma devem alinhar schema do pedido e derivacao do servidor preservando esse limite; nao tratar como erro validado em runtime e nao editar arquivo de outro dono. GAP-07 mantem esse alinhamento, watch renames/relatorio final e homologacao futura abertos.

## Ordem atual - OpenCode TUI persistente e composicao shell

Atualizacao do usuario em 11/10/2026: seis OpenCode corrigidos para TUI interativa persistente com --session dos IDs existentes e --auto, sem run; processos/telas high confirmados pelo principal. Essa ordem SUPERA as instrucoes historicas de relancar opencode run --file via raw. Nao relancar tarefas via raw agora. Prompts simples somente apos confirmar UI do agente; progresso por docs/integral/Nome.md, evitando ask sincrono. Meridiano nao reiniciou terminais nem enviou novo ask neste checkpoint.

Documento do principal: docs/integral/COORDINATOR_TERMINALS.md. Nao editar esse arquivo, nem os terminais, para registrar progresso de Meridiano. Arquivos tasks/Nome.md continuam referencia de escopo, sem ordem ativa de relaunch.

Principal informa _shell_service/shell_bridge/ProjectReviewService/document callbacks e shell_runtime CLI real criados. Leitura estatica confirma Canvas._shell_service compoe CanvasShellRuntime(canvas, host.control, owner=host.owner) e attach_shell_runtime na mesma autoridade; ProjectReviewService tem dispatch escopado ao projeto; documento/callbacks seguem contrato Tessela. CanvasShellRuntime conserva protected queue vinculada a Operations centrais, so recupera queued se operacao central tambem QUEUED e marca submissao interrompida UNCERTAIN sem automatic_retry. Transporte de anexos ainda exige configuracao explicita.

Dependencia ainda aberta: binding provider_usage por Nexo para consumidor CanvasShellRuntime/ControlPlaneService, contabilizacao/budget/quota autoritativos e custo desconhecido explicitamente representado. Nao tratar CLI criada como provider real homologado nem zero-custo conhecido. GAP-08 foi atualizado para esse binding e evidencias futuras; demais lacunas/contratos de expansao permanecem abertos. Nenhum requisito foi removido ou homologado. Nenhum teste/build/lint/benchmark/QA ou execucao de CLI foi realizado por Meridiano.

## Inventario atual de callbacks e dependencias de execucao

Inventario conciso em docs/integral/composition_inventory.md: doze owners (Codex + onze implementadores), callbacks/consumidores e dez dependencias concretas de composicao/artefato/ambiente. coverage.json tem composition_inventory e execution_dependencies, snapshots contemporaneos e relatos atualizados. Nenhuma fonte antiga ausente foi promovida a ausencia atual sem releitura; nenhum artefato/binding foi promovido a operante pela existencia de callback.

Prisma UI e expansoes Forja entregues por relato explicito/fontes; Tessela permission corrigida. Host QuickJS existe mas guest QuickJS/wasmtime faltam; workflow adapters existem mas SDK client/worker/definition/server faltam; voice/API/anexo bytes existem mas delegacao Canvas/runtime/provider configurado e chunks >512KiB faltam; canais APIs existem mas ingress/admitter/sender/unsubscribe enrollment faltam; learning/eval local existe mas binding central/servicos/verificadores faltam. Postgres store existe mas ProjectDocuments._guard ainda ATTACH enquanto backend rejeita ATTACH/path_for=None; compor guarda transacional nativa Nexo/Tessela/Codex. Vitra runners existem mas binarios/PKI/manifests assinados/exit-helper/keys callbacks finais pendem. provider_usage Nexo permanece pendente pelo principal.

Fonte entregue != integrado != homologado. Todas as clausulas/aceites e opcionais mantidos; nenhuma validacao, ask sincrono ou relaunch raw executado neste inventario. Pendencias ao Codex por este arquivo conforme protocolo TUI.

## Atualizacao Nexo/Lume/Forja/Tessela - entregas atuais

Inventario composition_inventory.md/coverage.json atualizado sem reduzir escopo. Nexo entregou binding shell provider_usage, reassign transacional/agent_run_memberships e MachineHost channels/acp_registry/executors/input/UFO; backup/restore/migrate/rollback/principals Postgres seguem em andamento. _shell_context fonte presente vincula conversa a Run/WorkItem/Operation; caminho SQLite/ATTACH ainda inspecionado, sem inferir aceite Postgres.

Tessela entregou relatorio final e authority_guard Postgres nativo: mesmos tenant schemas, sorted advisory locks, FOR UPDATE membership/Grant/WorkItem/Run/Operation, reader nega escrita, sem fallback SQLite. Watch/debounce/rename/TTL e permission corrigidos. Antiga lacuna ATTACH-only documental superada; deps/lock/bundle e provas nativas/runtime continuam pendentes.

Forja entregou Forja.md final e INTEGRAL_PROVENANCE.json (SHAs completos/upstreams/license_files declarados, nao verificados por Meridiano). Expansoes providers/InputControl/UFO/hybrid/Playwright/Daytona/Guacamole/RustDesk prontas para integrar; callback application_action posicional async alinhado Nexo. HTTP/UI/MCP + builds/VMs/SDK/guacd/peer/config/aceitacao sao pendencias reais, nao declarar operabilidade.

Lume: channels.py/ChannelProviderMachine concretos para Slack Events/WebAPI, Telegram webhook/BotAPI e WhatsApp Cloud Graph API(api_version), inbox/outbox OS-cifrados, assinatura/replay/allowlists/mapping e ACK distinto de recipient statuses/reply/claims. Cloud nao precisa/importa libsignal. Variante QR/libsignal permanece separada explicitly unavailable; invisible_dots local ausente conforme pesquisa/relato. Se variante QR independente for explicitamente exigida, encaminhar escopo/pin-fonte aprovado e notices GPL-3.0 pertinentes antes de implementar/validar. Nao inferir grant/prova QR de Cloud e nao fechar FF13 por stub. Fonte original, variante escolhida e alternativa indisponivel permanecem na matriz.

Nenhum teste/build/lint/benchmark/QA/execucao externa, ask sincrono ou relaunch raw. ZERO requisitos homologados. Fontes finais e protocolos nao substituem evidencias contemporaneas.

## Lume - entrega final de dominio registrada

Fonte final docs/integral/Lume.md preservada com hash em coverage.json. Factories ACP/A2A/MCP/channels/acp_registry exp?em catalog/dispatch_request/submit/shutdown para MachineHost; projections OS-cifradas no ControlStore. Namespaces: interop_projections, interop_interactions, interop_installations, interop_push, channels; provider_content reutilizado. Registro de namespace/factory/facade em arquivo nao e runtime homologado.

Implementacao entregue: lifecycle/elicitation/config/usage/absent-null/terminal-display; A2A Card/push/SSE/chunks/recovery; MCP SDK oficial 2.3.1 por revision/subscriptions/input_required owner-consumed; staged binary/npx/uvx com lock/pins/manifests/reconcile; OpenHands condense/transcricao preservada/health/tool links/delete; Slack/Tg/WA Cloud autenticacao/inbox/outbox/receipts/revoke. Quatro testes de persistencia/canais foram preparados em tests/unit/test_sentra_interop_integral_lume.py e NAO executados.

Callbacks adicionais Codex/Nexo: factory.receive_callback(raw_body,headers) para push A2A autenticado e limitado; ChannelService.receive(connector_id,raw_body,headers) para webhook raw <=1MiB e challenge WhatsApp; ProtocolInteractionService.pending/reply/consume_embedded para entrada owner; Pulso pending_inbound/claim/ack para admissao, send/receipt/lifecycle para canal. Ingestao so persiste inbox; nao cria WorkItem/Grant nem dispara efeito.

Limites retidos na matriz: ACP host filesystem/terminal privileged requests indisponiveis por padrao (terminal do agente display-only; executor/Pulso exige grants); restart SDK MCP legado fail-closed sem replacement/replay, requer reconciliacao; QR/libsignal separado nao incorporado, Cloud API real configuravel nao prova essa variante, notice separado. Nao reduzir requisito ao estado unavailable: manutencao da pendencia, provisionamento/runtime e composicao outros donos continuam explicitos.

Codex/Nexo receberam os contratos pelo relato do dono. Este update reporta via documentos conforme protocolo TUI; sem novo ask sincrono/raw, nenhum codigo alterado, nenhum teste/build/lint/benchmark/QA. Entrega de dominio != integracao integral aceita != homologacao. ZERO requisitos homologados.

### Lume - composicao central presente em fonte

Leitura posterior confirma cinco namespaces em control_store.py, MachineHost.receive_interop_callback(machine_id,raw_body,headers) e handlers POST /api/interop/webhook/<machine_id>, POST /api/channels/webhook/<connector_id> e GET handshake no handler Canvas. Supera ausencia/solicitacao historica desses pontos. Status: composicao presente em fonte, sem request HTTP, processo provider ou runtime executado. UI/claims/resolvers restantes, provisionamento externo, compatibilidade Postgres e evidencias continuam pendentes. Nenhuma homologacao.

## Delta root - composicao protegida, machines e optional

Fonte atual docs/integral/Codex.md registrada com hash/snapshots. ShellHostRequests(control,owner).invoke(project_id,action,payload,request_key,callback) reserva fingerprint/payload protegido antes do efeito e deixa interrupcao UNCERTAIN sem replay; operation_id derivado servidor. Journal duravel nao substitui central effect fence/lifecycle ainda pendente.

ShellMachineServices(canvas).dispatch(project_id,action,params,request_key): machine_list/input_status/input_handoff/remote_viewer_open/remote_viewer_close/machine_execute/machine_observe. WorkItem/Run/agente/projeto/grant/live epoch conferidos, capability derivada so quando unica. Viewer exige scope_verified/transporte vivo; listener loopback lazy port=0/origins Canvas, tickets view/human, dispatch_human com epoch, revoke-all/shutdown. Fonte composta, nao listener/provider executado.

OptionalShellServices(runtime): voice_availability/attachment_availability/voice_dispatch/attachment_dispatch/validate_attachments/attachment_bytes; VoiceRuntime/AttachmentStore no control.store; call/ref/upload escopados projeto/Space/conversa, bindings upload duraveis, chunks/status request key CP. CanvasShellRuntime ja delega metodos optional; antiga ausencia de delegates/chunks superada. A2A raw POST 1MiB com factory/projeto conferidos antes do receive; ingress-only, nao admissao/efeito. Channels/acp_registry na configuracao central existente.

Shell runtime instala binding provider apenas sob execution-lock de conversa; recover_completed valida Operation SUCCEEDED e protected journal hash/sequence/receipt para publicar resposta ja confirmada, SEM model replay. Isso nao fecha fluxo hosted/nativo por si.

PENDENCIAS EXPLICITAS DO ROOT (nao encerrar): helper multimodal Rastro; central optional fence/lifecycle Nexo; hosted TaskRuntime factory Nexo/Codex; Pulso runtime machine factory; bindings Selo/Pacto/Vitra. Registradas em coverage.composition_inventory.root_remaining, GAP-16/GAP-17 novas e demais gaps correspondentes. Todos artefatos/providers/builds/ambientes/acceptance futuros continuam em escopo.

Preview autorizado isolado PID47408 permanece intocado por Meridiano. Root relata dependencias/assets materializados pela excecao visual, sem liberar validacao geral; nao confundir com nenhuma execucao de teste/build/QA por Meridiano nem com homologacao. Este delta nao executou testes/lint/QA/build novo, provider, listener, preview ou terminal. Reporte somente por arquivo; SEM ask-back root. ZERO requisitos homologados.

## Adendos atuais Prisma e Nexo - fontes presentes, integracao em andamento

Prisma: novos shell-mascot/shell-attachments/shell-machines registrados; uploads begin/chunk/complete/abort/status reais no bridge,4 refs/imagem8MiB/docs20MiB/chunks512KiB/SHA/TTL1800/same-key retry/status incerto/reselect hash apos reload.512KiB e chunk, nao mais limite total UI. Viewer/InputControl contextual readonly default/human epoch-live-granted/scopes-opID servidor, closes transport nao OS, playback local sem input. Fonte e composicao entregues; servicos/pacote/config/receipts/aceitacao pendentes.

Assets fonte Prisma:4 PNG originais OpenDots pin625452e/MIT/copyright/PROVENANCE; Guacamole-common-js1.5.0 repack padarom (nao cloneApacheatual), SRI conforme PROVENANCE.json,Apache LICENSE/NOTICE/PROVENANCE, TipTap menus3.31.3 pins/overrides. Vitra informado para transportar notices/payload/manifest. Nenhuma install/build/lock/bundle/QA nova; preview PID47408/lock/assets preservados. Historica pesquisa sem mascotes superada por feedback visual explicito do usuario registrado Prisma; nao modificar fontes historicas.

Nexo delta concretizado: postgres_store native psycopg/tenant/RLS/DDL/migration/advisory locks/fence/backup-restore; NativeAuthorityMigration prepare -> native atomic commit -> protected CAS activate -> rollback/export_sqlite_rollback, fonteSQLite preservada, RunRECOVERING/OpUNCERTAIN/leases invalidated sem replay. Default factory/store selection compartilhada durable/context/governance semSQLitefallback.

CanvasAuthorityRuntime(state_root,canvas_store,*,control,owner) herda TaskRuntime e injeta cp durable/governance/budgets/UsageLedger(control=control). Antiga falta de hosted factory superada em fonte; integracao completa/aceitacao nao inferidas. Componente recebido como ShellOptionalAuthority tem entrada atual execute_optional(shell,*,owner,project,action,payload,key,callback), pre-effect Grant/intent/OSlock/fence/budget, signaling/storage receipts seguros nunca completion model/audio. Antiga ausencia de gate superada em fonte; lifecycle integral/final evidence permanecem abertos.

PENDENCIAS: multimodal helperRastro, runtime machinefactoryPulso, bindingsSelo/Pacto/Vitra, native full-file backup/keys prerequisite Nexo em implementacao, finalNexo.md e toda aceitacao provider/duas maquinas/PG/pacote/lock/bundle. GAP-02/07/08/10 seguem implementacao/integracao em andamento por instrucao Nexo; GAP-16/17 agora registram fonte presente e evidencia/integracao pendente, nao ausencia antiga. Escopo integral e textos de aceites preservados.

Zero testes/build/lint/benchmark/QA/install/execucao provider/preview, nenhuma homologacao. A primeira tentativa de gerar adendoPrisma falhou antes de gravar por variavel indefinida; esta grava todos os registros. Reporte ao principal por arquivo, sem ask-back/sincrono/raw.

## Ownership ATUAL - Cobalto sucessor dos seis dominios OpenCode

Autorizacao explicita usuario 11/10/2026: Cobalto gpt-6.1-sol/high ja recrutado pelo root, PID28432/high/YOLO informado, conectado nota+Meridiano e implementadores ativos. Meridiano nao recrutou/reiniciou; maestri list confirma Cobalto e nota disponiveis a Meridiano. Seis dominios Rastro/Brisa/Pacto/Pulso/Selo/Vitra transferidos para Cobalto. Nomes anteriores agora autoria/frente HISTORICA, nao dono atual de nova implementacao. Codex raiz/Nexo/Prisma/Forja/Lume/Tessela/Meridiano conservam ownership; root reserva code_machine.py e arquivos Canvas/HTTP/MCP/root.

Handoff completo: tasks/Cobalto-priorities.md (P0/P1/GAPs/fontes presentes/pendencias reais/interfaces) e tasks/Cobalto-sources.md (nota integral e dezfontes/hash/caminhos) associados aqui para leitura de Cobalto. Taskroot tasks/Cobalto.md preservada. Atual owners em coverage requirements/current_gaps mapeados a Cobalto, historical_owners/ownership_history preservam autoria. Clauses da fonte original nunca alteradas.

Prioridade: QuickJS guest/flags A08/replay RUNNINGuncertain/fullresult; one-turn multimodal receipts e quota2/PDFbinary vs4localrefs; Host account/approval/voz transcript verificado/restamp; RuntimeProviderHost/RuntimeMachine/TerminalWriteMachine factory/policy/restore/claims; VitraHostFacade admission-before-effect/trustedpaths/quiesce/keys/notices; Selo build_client real config/vault/scopes/CAS e policy/audit/learning/Langfuse/OTLP. Novas fontes Pulso factories/QuickJS guestC/hostfacade presentes, nao manter ausencia antiga nem inventar pacote/servico emexecucao.

Cobalto vai criar Cobalto-status.md por frente e IMPLEMENTAR; nao apenas auditar. Prioridades nao reduzemescopo; todos mecanismos/opcionais/aceites mantidos. Relato arquivos, sem ask-back root. Sem validacao/test/build/install/lint/benchmark/QA/runtime/recrutamento/restart/commit/push/reset/stash; previewPID47408 intacto. ZERO homologados.

## Redistribuicao vigente e delta root

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.

Fonte de prioridades em fechamento-backlog.md (em preparacao por varredura integral); Codigo root code_* e MCP CP compartilhado presentes, nao ausencias antigas. Coordinator chat ainda exige token CLI operationbound e CP Grant/admissao antes legacy_coordagent. Sem ask-back/test/build/QA/restart/recrutamento; PID47408 preservado.


## Contratos atuais de fechamento e clausulas pendentes

Fonte temporal: [fechamento-backlog.md](fechamento-backlog.md) e seus snapshots de corpos/linhas/hash em JSON. 69 frentes, 449 registros e 2.176 clausulas fontes retidas, sem homologacao. Nao contar associacao de topico como cobertura implementada.

- Codex/Nexo: token shell NOVO operation-bound para chat coordenador e CP Grants/admissao antes legacy_coordagent; o CLI limpa tokens herdados. Cf FB-01, sem renumerar CF05 autosave da fonte.
- Root: code_* e protected central receipt ja montados; MCP from_store mesma durable/context/authorization, model-catalog alias preservado. FB-02/32/33/34 conservam only pendencias atuais.
- Lume/Nexo/root: RuntimeProviderHost.aconfigure/arestore no loop MachineHost, factories pinned definition_source/checkpointer/Worker; wrappers configure/restore existem. Ainda compor resolvers EXECUTANTES e corrigir self._config versus _config(thread_id). FB-08..16.
- Forja/root: build_client/SeloHostFacade nova implementada server-only sharedstore/CAS/vault/CentralEffectContext; LangfuseClient real prompts/datasets/runs/scores/OTLP tambem. Compor center/shell/MCP e host identity binding; nao atribuir implementacao ? assinatura isolada. FB-38..43.
- Tessela/root/Nexo: VitraHostFacade agora reserve protegido BEFORE mutation na CP, uncertain sem replay e repair real. Resolver/authorize/offline/quiesced/checkpoint trusted host ainda precisa binding; backup/keys/native authority continuam Nexo. FB-60..64.
- Cobalto/root/Prisma/Nexo: sideband provider-authenticated transcript e rebind SDP fontes novas; full binary relay composer source substitui PDF textual como ?nica variante. Binding de turno/provider/CLI/asset-set receipts e lifecycle ainda em andamento. FB-24..31/67.
- Codex/Forja: windows_guest_artifact agora roteado por center_configure_machine -> configure_executor; handler Canvas/code-mode antes de restore. FB-47 registra conexao source entregue, sem aceite de isolamento/provider/artifacts reais.

Assinaturas finais e arquivos dos quatro implementadores em fechamento permanecem seus reports *-fechamento.md; esta documentacao nao edita fontes nem homologa operacao externa.


## Delta corpos/consumidores relay e autoridade CLI - 2026-10-11T11:01:47.767285+00:00

[Codex-composicao-relay.md](Codex-composicao-relay.md) incorporado em FB-02/47/24/25/67 de [fechamento-backlog.md](fechamento-backlog.md), com corpos/linhas/hash e historico no JSON/coverage. Provider binding fonte consumido antes dos dois subprocessos; Canvas/code handler antes restore; guest_artifact passa por configure_executor. Binario segue fila shell/shared CP/protectedreserve/grantsoriginais/budget/lease e exige final/receipt attested.

Restam CLIENTES FISICOS account/assistant do perfil revisado e produtor worker de frames exatos; callable/config/renderer/cache nao sao prova. Voice transcript/provider separado, optional receipt continua signaling/storage, nao model/audio completion. FB-47 apenas rota source entregue, requisitos guest/isolamento nao homologados. FB-01 coordenador, MCP agent-scoped e demais clausulas continuam abertas. Observacao FB-02: conferir BEARER lido em CLI ShellBridge vs TOKEN/PORT retirados nos produtores; nao herdar owner broker como token operation-bound.

Somente documentos editados; sem teste/build/install/lint/benchmark/QA/provider, recrutamento/restart ou mensagem sincrona. Relato por arquivos; preview intacta; ZERO homologados.


## Delta coordenador e Pacto por corpos - 2026-10-11T11:20:21.279185+00:00

Fonte: [Codex-coordinator-contract.md](Codex-coordinator-contract.md). FB-01/02/32/33 atualizados em backlog/coverage com linhas/hash e historico. Shell actor token operation-bound + CP coordinator admission + parent requiredcaps + child own Grant model:invoke estao conectados; list/grant/revoke de turno tem journal/Operation/audit receipt e UI/CLI consumidores. Pacto product actions seguem bridge journal; dispatcher/root A08 requerem protected execution proof e receipt/hash, nunca engine/digest historico apenas.

Pendencias: before-provider imediato no CLI (poll .25s nao substitui HTTP checkpoint), MCP agent-scoped/consumers PG, learning/Selo resolver real, runtime/guest/artefatos/provider/physical observers/worker e todas clausulas restantes. Nenhum slot callable nem relato fecha requisito. Zero testes/build/install/lint/benchmark/QA/runtime, sem resposta sincrona. Ownership preservado e preview intacta.
