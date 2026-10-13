# Meridiano ? consolidacao integral

> Ownership ATUAL: Cobalto=Brisa/Rastro; Prisma=Pacto; Lume=Pulso; Forja=Selo; Tessela=Vitra. REDISTRIBUICAO_CODEX.md supera transferencia anterior. Autoria historica preservada; root/Nexo e demais donos mantidos. Nenhuma homologacao.


Data: 11/10/2026. Implementacao primeiro; validacao nao liberada. Nenhum codigo editado; nenhum teste/build/lint/benchmark/QA, recrutamento, commit/push/reset/stash.

## Requisitos e arquivos

- requirements.md: nota integral 465 linhas, dez fontes completas, 55 CF/AF/FF, 34 CoS, 34 crosswalk G/A, 37 auditorias individuais + 37 ampliacoes, 18 lacunas transversais e 234 clausulas da nota.
- coverage.json: textos/hashes/linhas de fontes, 2176 clausulas documentais rastreaveis, snapshots de declaracoes, matrizes historicas, relatos dos donos, 15 lacunas atuais, tarefas e estados sem homologacao.
- contracts.md: C01-C10 com ownership, assinaturas lidas/recebidas, propostas explicitamente pendentes, dependencias e atualizacao concorrente.
- tasks/Nome.md: onze expansoes autorizadas; adendos Brisa/Rastro/Vitra de anexos/evidencia/streaming/re-stamp.

## Contratos recebidos

Nexo ControlPlaneService.shell_dispatch keyword-only e ShellCoordinatorService; HTTP bearer shell ja encaminha Canvas.shell_bridge, composicao em andamento. Forja configure_executor sync loop/configurations MachineHost e CentralExecutorFactory; InputLease/hybrid/recovery/AT-SPI futuros. Prisma proposta voice_start offer/answer, voice_status transcript, stop/revoke; provider Brisa/Codex pendente. Os seis relatos OpenCode atuais sao claims, nao evidencia runtime.

## Lacunas e expansoes

Nexo Postgres/migrations/multiusuario; Pacto QuickJS bounded real (deny-only rejeitado); Pulso Temporal/LangGraph runtimes; Brisa/Prisma voz; Lume/Pulso Slack/Telegram/WhatsApp; Selo/Pacto learning revisado e Langfuse prompts/datasets/evals. Adicionais: ACL documento/Space, Guacamole viewer, InputLease, anexos com upload/receipt, message_id duravel, Host evidence endpoints e re-stamp extensao, distribuicao/backup/restore/pacotes reais. Nenhum opcional removido.

## Comunicacao e impedimentos

maestri list executado primeiro. Nota conectada depois foi lida integralmente. Contratos/lacunas e expansoes enviados ao Codex cedo. Batch aos onze foi emitido antes do aviso de OpenCode run voltar ao PowerShell; nao houve novos prompts simples aos OpenCode depois do aviso. Arquivos tasks sao entrada --file para principal relancar no MESMO terminal via raw comando. Sem novos agentes.

## Pendencias e plano futuro

Implementadores devem fechar assinaturas/retornos/allowlists/identity/error/receipt e composicao Codex. Todas as frentes e opcionais permanecem sem homologacao; zero requisitos aprovados por Meridiano. Validacao somente depois de todas implementacoes/composicoes e liberacao expressa do principal: criterios individuais de fontes, providers reais autorizados, concorrencia/recovery/permissions, UX/fidelidade OpenDots, conta instalada, backup/restore/migracoes e release assinado/clean install. Nenhum comando de validacao foi executado.

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

Fonte de prioridades em fechamento-backlog.md (entregue; varredura estatica por clausula); Codigo root code_* e MCP CP compartilhado presentes, nao ausencias antigas. Coordinator chat ainda exige token CLI operationbound e CP Grant/admissao antes legacy_coordagent. Sem ask-back/test/build/QA/restart/recrutamento; PID47408 preservado.


## Entrega do backlog integral de fechamento

[fechamento-backlog.md](fechamento-backlog.md) entregue com 69 frentes, por arquivo/dono/acao e constatacao atual. [fechamento-backlog-data.json](fechamento-backlog-data.json) e coverage conservam 449 registros, 1.366 segmentos internos e 2.176 clausulas nao vazias das dez fontes, incluindo contexto/proveniencia/aceites e opcionais. Associacao por topico ? encaminhamento, nao prova semantica de implementacao; clausulas continuam abertas ate corpo+consumidor+autoridade+receipt ou condicao explicitamente implementada.

Atualizados ownership atual/historico, contracts, callback inventory e tasks originais sem editar fontes dos donos. Prioridades reais: coordenador token/admissao FB-01; LangGraph colisao atributo/metodo FB-09; guest-artifact allowlist root FB-47; bindings runtime/Selo/Vitra/voz/multimodal. Corrigidas ausencias historicas ja superadas (code_*, CPshared, lifecycle reserve, SDKasync, SeloLangfuse, transcript sideband e binary composer).

Relato por arquivos conforme protocolo vigente; maestri list executado, sem ask-back sincrono, recrutamento/restart, skills/MCP SENTRA, commit/push/reset/stash. Nenhum teste/build/install/lint/benchmark/QA/provider externo executado. ZERO homologados; preview preservada.


## Delta corpos/consumidores relay e autoridade CLI - 2026-10-11T11:01:47.767285+00:00

[Codex-composicao-relay.md](Codex-composicao-relay.md) incorporado em FB-02/47/24/25/67 de [fechamento-backlog.md](fechamento-backlog.md), com corpos/linhas/hash e historico no JSON/coverage. Provider binding fonte consumido antes dos dois subprocessos; Canvas/code handler antes restore; guest_artifact passa por configure_executor. Binario segue fila shell/shared CP/protectedreserve/grantsoriginais/budget/lease e exige final/receipt attested.

Restam CLIENTES FISICOS account/assistant do perfil revisado e produtor worker de frames exatos; callable/config/renderer/cache nao sao prova. Voice transcript/provider separado, optional receipt continua signaling/storage, nao model/audio completion. FB-47 apenas rota source entregue, requisitos guest/isolamento nao homologados. FB-01 coordenador, MCP agent-scoped e demais clausulas continuam abertas. Observacao FB-02: conferir BEARER lido em CLI ShellBridge vs TOKEN/PORT retirados nos produtores; nao herdar owner broker como token operation-bound.

Somente documentos editados; sem teste/build/install/lint/benchmark/QA/provider, recrutamento/restart ou mensagem sincrona. Relato por arquivos; preview intacta; ZERO homologados.


## Delta coordenador e Pacto por corpos - 2026-10-11T11:20:21.279185+00:00

Fonte: [Codex-coordinator-contract.md](Codex-coordinator-contract.md). FB-01/02/32/33 atualizados em backlog/coverage com linhas/hash e historico. Shell actor token operation-bound + CP coordinator admission + parent requiredcaps + child own Grant model:invoke estao conectados; list/grant/revoke de turno tem journal/Operation/audit receipt e UI/CLI consumidores. Pacto product actions seguem bridge journal; dispatcher/root A08 requerem protected execution proof e receipt/hash, nunca engine/digest historico apenas.

Pendencias: before-provider imediato no CLI (poll .25s nao substitui HTTP checkpoint), MCP agent-scoped/consumers PG, learning/Selo resolver real, runtime/guest/artefatos/provider/physical observers/worker e todas clausulas restantes. Nenhum slot callable nem relato fecha requisito. Zero testes/build/install/lint/benchmark/QA/runtime, sem resposta sincrona. Ownership preservado e preview intacta.
