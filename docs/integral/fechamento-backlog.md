# Backlog de fechamento integral - Meridiano

Leitura estatica de 11/10/2026; snapshot `2026-10-11T10:54:22.008921+00:00`. **Nenhum teste/build/install/lint/benchmark/QA. Nenhuma homologacao.**

69 frentes concretas de fechamento; 449 registros de requisitos, 1366 segmentos internos e 2176 clausulas nao vazias das dez fontes permanecem rastreaveis em [coverage.json](coverage.json) e [fechamento-backlog-data.json](fechamento-backlog-data.json). O indice nao transforma associacao por topico, assinatura, presenca de arquivo ou relato em prova de implementacao.

Ownership vigente: Cobalto=Brisa/Rastro; Prisma=Pacto+UI; Lume=Pulso+interop; Forja=Selo+executores; Tessela=Vitra+docs. Nexo=CP/PG/runtime/governance; Codex=HTTP/Canvas/MCP/configuracao/composicao. Autoria original e takeover anterior preservados em coverage. [Redistribuicao](REDISTRIBUICAO_CODEX.md) prevalece. Nenhum OpenCode reiniciado; nenhuma mensagem ask sincrona enviada.

Prioridade imediata: **FB-01** checkpoint provider; token/admissao ja conectados; **FB-09** colisao LangGraph; **FB-47** kind source entregue; guest/artefatos/provas finais pendentes; **FB-08/11/38/60** bindings de runtimes/Selo/lifecycle; **FB-24/25/67** ultima composicao voz/multimodal e checkpoints; **FB-32/33/34** A08 completo. Sao prioridades de implementacao, nao permissao para validar.

Os rotulos CF05/CF14 usados no ?ltimo relato root identificam a pendencia coordenador. Nao alteram os IDs da fonte OpenDots: OD-CF05 continua autosave, OD-CF14 tarefas persistidas. A pendencia conversacional esta em NOTE-L426/435/438/446 e OD-CF07/14.

## Correcoes de lacunas antigas

- Root ja monta code_propose/execute/cancel/status/discovery na MachineHost, protege source/results e confere receipt central real; MCP usa from_store com durable/context compartilhados, center_inspect mesma autorizacao e alias model-catalog preservado.
- Dispatcher ja reserva before-effect, retorna UNCERTAIN sem replay e recupera resultado completo protegido; falta alinhar status `_a08_execution` ao mesmo resultado/prova.
- Vitra ja reserva maintenance na store CP antes de `_mutate` e exige runner real para repair. A lacuna antiga de receipt apenas pos-efeito nao ? atual.
- Lume ja adicionou fabricas assincronas SDK/Worker/definition_source e checkpointer CP. O problema atual ? composicao no loop owned e `_config` LangGraph, nao ausencia de qualquer SDK.
- Forja ja entregou source novo de SeloHostFacade/build_client/LangfuseClient (rotas prompts/datasets/runs/scores/OTLP) durante esta varredura. Falta binding produto/reconcile; o cliente antigo de spans nao ? mais o ?nico caminho.
- Voz ja possui `_ingest_sideband` servidor autenticado, ciphertext/event dedupe e rebind SDP; shell_multimodal agora transporta binarios inteiros via relay composer. Essas fontes ainda precisam de composicao final/recibos e provas futuras.
- Nexo shared CanvasAuthorityRuntime/execute_optional/native PG e Tessela guards/callbacks ja existem; nao reabrir ausencia generica.

## Estados e criterio de fechamento

`source_connected_acceptance_deferred`: a omissao/conexao especifica foi corrigida no corpo consumidor; requisitos abrangentes e operacao fisica continuam sem aceite. FB-47 esta neste estado, nao em falta de allowlist.

`open_implementation`: corpo atual aponta mecanismo especifico faltante/conflitante. `open_connection`: mecanismos fontes existem mas consumidor/autoridade/configuracao ainda precisa composicao. `open_trace`: fonte entregue, porem a clausula exata ainda precisa mostrar caminho alcancavel produtor->consumidor->admissao->efeito->receipt; nao afirma ausencia global. `conditional_*`: implementacao/variante configuravel permanece no escopo. `future_artifact` e `future_acceptance`: trabalho real reservado ? fase final, sem executa-lo agora.

Cada ticket abaixo contem arquivos concretos, constatacao e mudanca esperada. Os corpos capturados com linhas/hash estao no JSON. ? medida que donos alteram a ?rvore, um achado pode ser superado; relatar arquivo/corpo/consumidor corrigido permite atualizar sem fingir runtime. Nenhum ticket fechado por deny-only, runner injetavel sem cliente, protocolo sem worker ou guest sem artefato.

## Backlog por dono e arquivo

### FB-01 - Coordenador operation-bound conectado; checkpoint provider restante

**P0 | open_trace | dono principal Codex; composicao: Nexo, Prisma, Tessela.**

**Arquivos:** `sentra_canvas/shell_runtime.py`, `sentra_canvas/service.py`, `sentra_mcp/services/shell_coordinator.py`, `sentra_canvas/shell_actor.py`, `sentra_canvas/shell_permissions.py`, `sentra_runtime/coordinator_admission.py`, `sentra_cli/agent.py`, `sentra_cli/client.py`, `sentra_core/provider_usage.py`, `sentra_cli/canvas.py`, `sentra_canvas/desktop_ui/src/shell-turn-permissions.jsx`.

**Constatacao atual:** ShellActorService.register emite token shell:<parent_operation_id>, deadline/epoch volatile; subject confere processo vivo, owner/project/Run/WI/Operation/assignee, provider binding e protected queue original em cada chamada. service.agent_control envia shell token a actors.dispatch ANTES do legado. dispatch chama execute_coordinator_intent, que exige parent required_capabilities explicita (lista vazia nao autoriza), policy/Grant/budget/intent/fence/receipt central. compose create_dot cria metadata/link sem processo; delegate/handoff criam conversation/message pelo cp.shell sob fence. Nexo message_send consome message_capabilities; filho declara model:invoke e aguarda Grant proprio local_owner=False. Worker revalida Grant/assignee/pause antes TaskProcess e a cada .25s, revogando token no finally. Self-pause/cancel usa record_metadata_transition/terminal ACK com efeitos subsequentes negados. ShellTurnPermissions possui tres acoes owner-scoped, journal before-effect e Operation/receipt de metadata; Prisma UI e Tessela shell scope/prompt consomem esquema real.

**Fechar:** Fechar checkpoint IMEDIATAMENTE antes de cada HTTP/tool/provider no CLI com current configured UsageLedger/Run/WI/Operation/assignee e Grant model:invoke do filho, local_owner=False. _before_provider lido chama ledger.require (budget/context), _approved_provider_context apenas retorna snapshot; require lido nao exige model:invoke. Poll .25s do pai nao substitui essa admissao fisica. Conservar token deadline/reassign/cancelrace/replay e ACK self-pause/cancel sem liberar outro efeito. Provar runtime/coordenacao/descendentes/permissoes somente fase final; nao reabrir ausencia do token/admission ja implementados.

**Clausulas fonte:** NOTE-L426, NOTE-L435, NOTE-L438, NOTE-L446, OD-CF07, OD-CF14.

**Corpos/consumidores lidos:** `sentra_canvas/shell_runtime.py:98`, `sentra_canvas/shell_runtime.py:118`, `sentra_canvas/shell_runtime.py:338`, `sentra_canvas/shell_runtime.py:360`, `sentra_canvas/service.py:1535`, `sentra_mcp/services/shell_coordinator.py:554`, `sentra_canvas/shell_actor.py:17`, `sentra_canvas/shell_actor.py:33`, `sentra_canvas/shell_actor.py:152`, `sentra_canvas/shell_actor.py:187`, `sentra_canvas/shell_permissions.py:23`, `sentra_canvas/shell_permissions.py:93`, `sentra_canvas/shell_permissions.py:137`, `sentra_runtime/coordinator_admission.py:94`, `sentra_runtime/coordinator_admission.py:108`, `sentra_runtime/coordinator_admission.py:143`, `sentra_cli/agent.py:229`, `sentra_cli/agent.py:345`, `sentra_core/provider_usage.py:295`, `sentra_canvas/desktop_ui/src/shell-turn-permissions.jsx:15`, `sentra_canvas/desktop_ui/src/shell-turn-permissions.jsx:31`. Hash/corpo no JSON.

**Estado:** conexao em fonte; sem aceite de clausula integral ou evidencia runtime.

### FB-02 - CP compartilhada: capsula CLI e actor scope conectados

**P0 | open_trace | dono principal Codex; composicao: Nexo.**

**Arquivos:** `sentra_canvas/task_runtime.py`, `sentra_canvas/shell_runtime.py`, `sentra_mcp/server.py`, `sentra_mcp/services/control_plane.py`, `sentra_canvas/service.py`, `sentra_runtime/provider_authority.py`, `sentra_cli/authority_environment.py`, `sentra_cli/shell_bridge.py`, `sentra_mcp/services/control_store.py`, `sentra_runtime/machine_host.py`, `sentra_canvas/shell_actor.py`, `sentra_canvas/shell_permissions.py`, `sentra_runtime/coordinator_admission.py`, `sentra_cli/agent.py`, `sentra_mcp/services/pacto_product.py`.

**Constatacao atual:** prepare_provider_binding ja usado nos dois subprocessos e consumido pelo configured control_store/CLI. ShellActorService acrescenta token NOVO operation-bound e SCOPE=shell ao processo atual, valida protected queue/provider binding/process antes coordena??o; Nexo liga message_capabilities e requiredcaps explicitas. ShellTurnPermissions deriva Dot/WI/op/owner servidor e registra audit Operation/receipt proprio, sem renderer escolher GrantID. Fluxo Pacto produto na mesma bridge usa ShellHostRequests antes callback. Ausencias historicas de capsula/token/conexao coordinator estao superadas em fonte; nao ha outra authority criada por esses adapters.

**Fechar:** Conservar rastreio agente-scoped MCP, configured PG/SQLite consumers, selection/TTL/revoke/reassign e before-provider checkpoints. _bind_existing_web_authority do CLI ainda instancia SQLiteControlPlaneStore explicitamente para gateway Web; rastrear esse consumidor no modo PG sem chamar isso automaticamente de autoridade paralela. Resolver env owner BEARER/TOKEN/PORT sem usar token de broker herdado como actor shell. Learning/Selo resolver concreto e outros bindings de dominio continuam abertos. Fonte conectada nao homologa multiusuario ou efeitos.

**Clausulas fonte:** OD-FF01, OD-AF01, NOTE-L241, NOTE-L440, REE-GAP-01.

**Corpos/consumidores lidos:** `sentra_canvas/shell_runtime.py:327`, `sentra_canvas/shell_runtime.py:338`, `sentra_canvas/service.py:297`, `sentra_canvas/shell_permissions.py:91`, `sentra_cli/agent.py:354`. Hash/corpo no JSON.

**Estado:** conexao em fonte; sem aceite de clausula integral ou evidencia runtime.

### FB-03 ? Home e Dots devem projetar Grants reais

**P0 ? open_trace ? dono principal Codex; composicao: Nexo, Prisma.**

**Arquivos:** `sentra_canvas/shell_runtime.py`, `sentra_mcp/services/shell_coordinator.py`, `sentra_canvas/desktop_ui/src/shell-app.jsx`.

**Constatacao atual:** Contrato shell pede capabilities realmente concedidas; catálogo/configuração de provider não equivale a Grant. Fonte do resolvedor e projeção Home devem ser rastreadas por ação e contexto, sem contar disponibilidade estática como autorização.

**Fechar:** Separar available/configured/granted, resolver workspace/Space/conversation/agent no host, manter modelos/effort observados e limites; expor motivo sanitizado para cada capacidade não concedida.

**Clausulas fonte:** OD-CF02, OD-CF18, NOTE-L427, SHELL.

### FB-04 ? Progresso incremental e recibos no chat

**P1 ? open_connection ? dono principal Codex; composicao: Prisma, Cobalto.**

**Arquivos:** `sentra_canvas/shell_runtime.py`, `sentra_canvas/desktop_ui/src/shell-conversation.jsx`, `browser/streaming.py`, `native_bridge/stream_ingest.py`.

**Constatacao atual:** shell_runtime espera communicate terminar e só então lê journal/última resposta; histórico streaming Web por message ID é outra camada. Não há prova de projeção incremental dessa execução CLI no shell.

**Fechar:** Ligar eventos/progresso/tools ao cursor central e message ID/revision, com reconexão/dedupe/overflow protegido; resumo humano conserva Operation/evidência e nunca anuncia conclusão antes de receipt.

**Clausulas fonte:** OD-CF07, OD-FF14, COS-A13, COS-A16, NOTE-L436.

**Corpos lidos:** `sentra_canvas/shell_runtime.py:269`, `sentra_canvas/shell_runtime.py:282`. Snapshot completo e hash no JSON.

### FB-05 ? Elicitation/input_required e aprovações visíveis

**P1 ? open_connection ? dono principal Codex; composicao: Prisma, Lume.**

**Arquivos:** `sentra_canvas/service.py`, `sentra_interop/interactions.py`, `sentra_canvas/desktop_ui/src/shell-dialogs.jsx`.

**Constatacao atual:** interaction_list/reply já está montado no serviço, consultando ProtocolInteractionService. Resta ligação da UI e retomada owner-consumed ao provider, não ausência do endpoint.

**Fechar:** Compor painel de interação com payload schema/revision/deadline/cancel; validar owner/WorkItem/tool/args e consumir decisão uma vez; não auto-fulfil/reload/retry de ferramenta.

**Clausulas fonte:** OD-CF11, OD-AF09, COS-A04, REE-04, REE-07.

**Corpos lidos:** `sentra_canvas/service.py:265`. Snapshot completo e hash no JSON.

### FB-06 ? Pesquisa Web configurável no shell

**P1 ? open_connection ? dono principal Codex; composicao: Cobalto, Lume, Prisma.**

**Arquivos:** `sentra_mcp/services/research.py`, `sentra_canvas/service.py`, `sentra_interop/mcp_http.py`.

**Constatacao atual:** ResearchService contém orquestração real de chats temporários Edge; isso não prova ligação do modo pesquisa/Parallel MCP ao Dot atual. A ausência antiga de qualquer research source foi corrigida por leitura.

**Fechar:** Definir modo configurado browser/MCP e indisponibilidade explícita; admitir pesquisa no WorkItem, catálogos/namespace por backend, referências e limites; ligar escolha e resultados à conversa.

**Clausulas fonte:** OD-CF08.

### FB-07 ? Guardas HTTP/transporte e separação read/action

**P1 ? open_trace ? dono principal Codex; composicao: Cobalto, Nexo.**

**Arquivos:** `sentra_canvas/__main__.py`, `sentra_canvas/service.py`, `browser/protected_assets.py`, `sentra_mcp/server.py`.

**Constatacao atual:** Bridge bearer, raw ingress 1MiB e paths restritos já existem. Limites/origins/cookies/tunnel/conta por transporte ainda exigem trilha completa no modo configurado.

**Fechar:** Rastrear POST único/Host/Origin/CSP/body/error sanitizado e escopos read/action independentes; separar browser read-only de executor; manter credenciais/tokens server-side e revoke de conexões.

**Clausulas fonte:** OD-CF09, OD-CF19, COS-A10, OD-FF09.

### FB-08 ? Compor runtimes/terminal no loop da MachineHost

**P1 ? open_connection ? dono principal Codex; composicao: Nexo, Lume.**

**Arquivos:** `sentra_canvas/service.py`, `sentra_runtime/machine_host.py`, `sentra_interop/workflow_runtime_machine.py`.

**Constatacao atual:** MachineHost configure_runtime/configure_terminal e restore já existem. configure_runtime chama helper sync dentro de coroutine, enquanto Lume passou a exigir await arestore/aconfigure no loop antes da fábrica. Canvas center_configure_machine não enumera runtime/terminal neste snapshot.

**Fechar:** Compor runtime_host_resolver/canvas_adapter server-only, await construção/restore no loop owned; adicionar kinds/configuração pública bounded e persistência/close; manter identidades binding_id[-8:] coerentes.

**Clausulas fonte:** REE-16, REE-17, COS-G05, REE-GAP-01.

**Corpos lidos:** `sentra_runtime/machine_host.py:368`, `sentra_runtime/machine_host.py:534`. Snapshot completo e hash no JSON.

### FB-09 ? LangGraph: atributo sobrescreve método _config

**P0 ? open_implementation ? dono principal Lume; composicao: proprio dominio.**

**Arquivos:** `sentra_interop/workflow_runtime.py`, `sentra_interop/workflow_runtime_host.py`.

**Constatacao atual:** Base __init__ cria self._config=None e configure grava record; subclass define _config(thread_id), start/status/resume/fork chamam self._config(...). A instância resolve atributo dict/None no lugar do método.

**Fechar:** Separar registro de configuração do construtor RunnableConfig e ajustar consumidores host/adapter; conservar thread/checkpoint/namespace/owner e binding sem mudar autoridade. Constatação estática, sem executar.

**Clausulas fonte:** ECO-16, REE-16.

**Corpos lidos:** `sentra_interop/workflow_runtime.py:84`, `sentra_interop/workflow_runtime.py:191`. Snapshot completo e hash no JSON.

### FB-10 ? SDKs, workers e grafos pinados subordinados

**P1 ? open_connection ? dono principal Lume; composicao: Nexo, Codex.**

**Arquivos:** `sentra_interop/workflow_sdk.py`, `sentra_interop/workflow_sdk_store.py`, `sentra_interop/workflow_runtime_host.py`.

**Constatacao atual:** workflow_sdk agora constrói Client Temporal/TLS, Worker e graph de definition_source SHA, checkpointer configurado CP. Antiga ausência de SDK/factory e raw graph em JSON está superada. Pins/manifesto revisado e wrappers de cada nó/activity ainda são necessários.

**Fechar:** Registrar definições reais por hash/versão; impedir retry SDK de efeito sem gateway CP; ownership/close do Worker/checkpointer/client no loop; compatibilidade worker/history e reconciliação sem replay.

**Clausulas fonte:** ECO-16, ECO-17, REE-16, REE-17.

**Corpos lidos:** `sentra_interop/workflow_sdk.py:53`, `sentra_interop/workflow_sdk.py:68`, `sentra_interop/workflow_sdk.py:85`. Snapshot completo e hash no JSON.

### FB-11 ? Resolvers executam intents, não só os retornam

**P1 ? open_connection ? dono principal Codex; composicao: Lume, Nexo.**

**Arquivos:** `sentra_interop/workflow_shell.py`, `sentra_interop/workflow_shell_host.py`, `sentra_canvas/service.py`.

**Constatacao atual:** PulsoShellDispatch expõe intenções/facade; root task pede resolver executante que seleciona Machine/WorkItem confiáveis. Assinatura sozinha não conecta admissão/efeito/receipt.

**Fechar:** Montar workflow/runtime/terminal/channel resolvers na bridge e center; server-generated operation IDs, target_operation_id nas observações, receipt real e cancel/reconcile até autoridade.

**Clausulas fonte:** OD-CF14, OD-FF08, COS-G05, REE-GAP-01.

### FB-12 ? Outbox/canal->workflow->ack no mesmo WorkItem

**P1 ? open_connection ? dono principal Lume; composicao: Codex.**

**Arquivos:** `sentra_interop/workflow_nats.py`, `sentra_interop/workflow_channel_triggers.py`, `sentra_interop/channels.py`.

**Constatacao atual:** ChannelWorkflowTrigger confirma SUCCEEDED e WorkItem antes de ack; mecanismo já escrito. Consumers/signal execução e publicação root/NATS ainda precisam composição concreta.

**Fechar:** Ligar pull consumers TLS/ACL, durable name/MaxAckPending/backoff/redelivery/replay/retention por classe; publicar por outbox e ack após persistência/receipt correspondente, sem usar broker como idempotência central.

**Clausulas fonte:** ECO-18, REE-18, OD-AF12, OD-FF13.

### FB-13 ? Peças Activepieces e triggers reais

**P1 ? open_connection ? dono principal Lume; composicao: Codex, Nexo.**

**Arquivos:** `sentra_interop/activepieces_worker.py`, `sentra_interop/activepieces_worker.mjs`, `sentra_interop/activepieces_scheduling.py`, `sentra_interop/activepieces_loopback.py`.

**Constatacao atual:** SDK/backend/hook source existe; o root ainda precisa escolher peças provisionadas e callbacks executantes. Catálogo e schema não instalam uma peça ou renovam webhook.

**Fechar:** Pins/lock de peça+helpers; formulários typed/output schemas, enable/disable/renew OAuth/webhook, assinatura/dedupe ingress-only, secrets vault e effect gate por ação; recuperação e cleanup owned.

**Clausulas fonte:** ECO-33, REE-33.

### FB-14 ? Agenda e resultado terminal/canal central

**P1 ? open_connection ? dono principal Lume; composicao: Codex, Nexo.**

**Arquivos:** `sentra_mcp/services/routine_scheduler.py`, `sentra_mcp/services/jobs.py`, `sentra_interop/workflow_scheduling.py`.

**Constatacao atual:** Semânticas timezone/DST/fold/misfire/nonoverlap/autopause foram escritas. Falta rastrear hooks de término real e entrega de resultados no provider configurado.

**Fechar:** Ligar ocorrência única->admissão->resultado->next-after-completion/cost pause; queued/starting/claim/lease restart e deadlines; notificar Telegram só com receipt e não duplicar UNCERTAIN.

**Clausulas fonte:** OD-AF11, OD-AF12, OD-FF12, OD-CF14.

### FB-15 ? Terminal persistente local/remoto com write fenced

**P1 ? open_connection ? dono principal Lume; composicao: Codex, Forja.**

**Arquivos:** `sentra_executors/conpty_sessions.py`, `sentra_executors/daytona_sessions.py`, `sentra_interop/workflow_runtime_machine.py`, `sentra_canvas/service.py`.

**Constatacao atual:** Ledger ConPTY register/cursor/closed e live=False após restart; TerminalWriteMachine source presente. Ligação a PTY Daytona/resize/stdin/kill e fechamento owned precisa completar seleção do host.

**Fechar:** Conectar IDs de ProcessSession ao Canvas preservado, snapshots head/tail/overflow, writes com InputLease/Grant/epoch; restart não recupera handle morto nem reproduz stdin; cancelar só recursos owned.

**Clausulas fonte:** COS-G06, REE-08, REE-GAP-02.

### FB-16 ? Goal/Loop, providers e relações entre Runs

**P1 ? open_connection ? dono principal Lume; composicao: Codex, Forja.**

**Arquivos:** `sentra_executors/goal_loop.py`, `sentra_executors/operation_receipts.py`, `sentra_interop/openhands_provider.py`.

**Constatacao atual:** Goal/Loop e OpenHands condense/health/tool links presentes; builders não provam supervisão real de workers/equipe no turno coordenador.

**Fechar:** Compor workers subordinados, nonoverlap/budget/cancel/lease, system+eventos originais fora do resumo, links tool->Operation e agent_run_memberships em reassign; não trocar agente ao mudar Run.

**Clausulas fonte:** COS-G05, REE-03, NOTE-L273.

### FB-17 ? ACP completo por capabilities negociadas

**P1 ? open_trace ? dono principal Lume; composicao: Codex, Prisma.**

**Arquivos:** `sentra_interop/acp_session.py`, `sentra_interop/acp_provider.py`, `sentra_interop/provider_machine.py`, `sentra_interop/interactions.py`.

**Constatacao atual:** Lifecycle/config/model/usage/null-preservation/elicitation e factory foram entregues. Host fs/terminal privilegiados estão unavailable por padrão, terminal-display é distinto.

**Fechar:** Rastrear UI+CLI/configuração/pin/reconcile/cancel e interação por revisão; quando capability host fs/terminal for configurada, vincular executor/WorkItem/Grants reais em vez de apenas indisponibilidade permanente.

**Clausulas fonte:** ECO-04, REE-04.

### FB-18 ? A2A continuidade/push/artifact e ingresso autorizado

**P1 ? open_trace ? dono principal Lume; composicao: Codex, Nexo.**

**Arquivos:** `sentra_interop/a2a_provider.py`, `sentra_interop/a2a_push.py`, `sentra_interop/a2a_sse.py`, `sentra_canvas/__main__.py`.

**Constatacao atual:** Card pin/HTTPS/SSE/chunks/push/receive_callback e raw ingress agora source presente. Falta traçar task externa recebida até consumo humano/admissão CP e resposta artifact completa.

**Fechar:** Compor callback autenticado com project-before-receive, replay/limites; manter task/context IDs, extendedCard/version, input-required e hash/chunks; nenhum POST ingress dispara efeito automaticamente.

**Clausulas fonte:** ECO-06, REE-06.

### FB-19 ? MCP SDK real por revisão até produto

**P1 ? open_trace ? dono principal Lume; composicao: Prisma, Codex.**

**Arquivos:** `sentra_interop/sdk/mcp_host.mjs`, `sentra_interop/mcp_session.py`, `sentra_interop/provider_machine.py`.

**Constatacao atual:** Cliente TS oficial 2.3.1/subscriptions/input_required source entregue; legacy process restart permanece failclosed e não prova revisão moderna.

**Fechar:** Compor catálogo dinâmico/namespace/resource/prompt e owner-consumed interactions ao shell; handshake revision/schema refresh/lateresponse/cancel/reconnect conservam Operation; sem auto retry/fulfil.

**Clausulas fonte:** OD-CF10, ECO-07, REE-07.

### FB-20 ? Registry instalação/runtime/reconcile no host

**P1 ? open_trace ? dono principal Lume; composicao: Tessela, Codex.**

**Arquivos:** `sentra_interop/registry_install.py`, `sentra_interop/registry_runtime.py`, `sentra_interop/registry_machine.py`.

**Constatacao atual:** Plans staged binary/npx/uvx/hash/lock/process trees já existem. Inventário/download manifest não comprova instalação autorizada e runtime após reinício.

**Fechar:** Compor owner install/revoke/remove/diagnóstico e distribution OS/arch/dependências reais; pin de pacote não só clone; terminar árvore owned e manter receipt por etapa/reconciliação.

**Clausulas fonte:** ECO-05, REE-05.

### FB-21 ? ToolHive opcional além de boundary/descriptor

**P1 ? open_implementation ? dono principal Lume; composicao: Prisma, Forja, Codex.**

**Arquivos:** `sentra_interop/mcp.py`, `sentra_interop/mcp_stdio.py`, `sentra_interop/tool_catalog.py`.

**Constatacao atual:** mcp.py exige cliente conectado injetado; ToolHiveEndpoint não faz I/O; mcp_stdio diz ToolHive NOT started. Descoberta seletiva é ToolHive-inspired, não lifecycle/token exchange de backend.

**Fechar:** Implementar provider configurável ToolHive/toolhive-core pinado ou transportar integralmente mecanismos exigidos: host lifecycle/isolamento/auth por backend, audience/scope exchange, per-call veto CP, token savings; não contar descriptor como serviço.

**Clausulas fonte:** ECO-19, REE-19.

**Corpos lidos:** `sentra_interop/mcp.py:2`, `sentra_interop/mcp.py:137`, `sentra_interop/mcp_stdio.py:1`. Snapshot completo e hash no JSON.

### FB-22 ? Slack/Telegram/WhatsApp Cloud e identidade canal

**P1 ? open_trace ? dono principal Lume; composicao: Codex, Prisma.**

**Arquivos:** `sentra_interop/channels.py`, `sentra_interop/channel_machine.py`, `sentra_canvas/service.py`.

**Constatacao atual:** APIs oficiais reais/assinatura/allowlist/inbox/outbox/protected mappings existem; channel_configure agora montado. provider ACK não é recipient delivery.

**Fechar:** Completar configuração/admin/revoke por servidor, guest/Telegram->Principal sem auto Grant, project/conversation/Space mapping e outbound status/webhook reply; provisionar credenciais/canais depois e reter pending/uncertain.

**Clausulas fonte:** OD-CF16, OD-AF01, OD-AF02, OD-FF13.

### FB-23 ? Variante WhatsApp QR/libsignal preservada

**P2 ? conditional_variant ? dono principal Lume; composicao: Tessela, Codex.**

**Arquivos:** `sentra_interop/channels.py`, `docs/integral/Lume.md`.

**Constatacao atual:** Cloud Graph API implementa a variante oficial. Clone invisible_dots ausente localmente; QR/libsignal não importado, sem fonte/pin aprovado para esta variante.

**Fechar:** Manter variante QR/libsignal explicitamente unavailable e requisito rastreado; se escopo independente confirmado, obter fonte/pin/notice GPL3 e implementar pareamento/keys/revoke/receipts antes de validação. Não trocar Cloud por stub.

**Clausulas fonte:** OD-FF13, OD-FF18.

### FB-24 - Voz: consumidores centrais presentes; prova fisica separada

**P0 | open_trace | dono principal Cobalto; composicao: Codex, Nexo, Prisma.**

**Arquivos:** `browser/voice.py`, `browser/realtime_sideband.py`, `sentra_canvas/shell_optional.py`, `sentra_canvas/desktop_ui/src/shell-voice.jsx`, `sentra_canvas/shell_runtime.py`, `sentra_mcp/services/shell_coordinator.py`.

**Constatacao atual:** ShellCoordinator._optional resolve Space/conversation no host e envia voice mutations a execute_optional; CanvasShellRuntime.voice_dispatch -> OptionalShellServices -> VoiceRuntime usa shared control.store e revalida call/project/Space/conversation. VoiceRuntime._ingest_sideband protege/deduplica eventos do provider e verifica generation/status. O novo attach_shell_relay_observers e ShellWebRuntime sao a composicao de resposta ChatGPT relay, nao substituem transcript/autenticacao Realtime de voz.

**Fechar:** Manter tracing por call/generation/message/revision/overflow e checkpoints rebind/status/stop/revoke ate o cliente Realtime configurado; finalizar lifecycle e disponibilidade honestos. Observer callable de relay nao prova transcript de voz, nem conta/perfil instalado. Provas audio/provider/conta sao etapa final; tools de voz so por admissao CP independente.

**Clausulas fonte:** OD-CF15.

**Corpos/consumidores lidos:** `browser/voice.py:685`, `browser/voice.py:989`, `sentra_canvas/shell_optional.py:67`, `sentra_mcp/services/shell_coordinator.py:692`. Hash e corpo completo no JSON.

**Estado:** conexao em fonte, sem aceite de clausula/capacidade integral e sem evidencia runtime.

### FB-25 - Turno binario ligado a fila shell; observadores/worker reais abertos

**P0 | open_connection | dono principal Cobalto; composicao: Codex, Prisma, Tessela, Nexo.**

**Arquivos:** `native_bridge/shell_multimodal.py`, `native_bridge/attachment_transport.py`, `browser/attachments.py`, `sentra_canvas/shell_optional.py`, `sentra_remote/run_cli.py`, `sentra_canvas/shell_web.py`, `sentra_canvas/shell_runtime.py`, `sentra_canvas/service.py`, `native_bridge/stream_ingest.py`, `native_bridge/relay.py`.

**Constatacao atual:** CanvasShellRuntime cria ShellWebRuntime e _execute_locked direciona refs OU conversa relay existente a web.grants/web.execute. ShellWebRuntime reserva protected_turn antes de staging, re-resolve bytes owner/project/Space/conversation/SHA, usa Grants originais web:send/web:attach, budget e lease/fence centrais, chama dispatch_shell_turn com modelo/effort canonicos e um job/Send. observe so consulta o intent original: exige ANSWERED/collector_message_attested, receipt e ChatResult COMPLETED com task/conversation exatos. reconcile_message/recover_completed publicam mesmo final sem readmitir/reenviar; conversa CLI preexistente exige continuation explicita. Helper/fila/publish source ja estao conectados.

**Fechar:** Compor account_attestor e assistant_observer como CLIENTES FISICOS independentes do browser/perfil revisado, com selection/account reatestados na fase sending e FULL body/parent/role/complete/host revision/collector/source/document/epoch. Fechar produtor worker de /jobs/response-frame com lease original e esquema exato Cobalto; nao copiar selectors como prova, nao trocar perfil Edge por Electron nem JSON/cache/renderer por observacao. Slot callable/config enabled nao fecha clausula: availability ainda testa callable e proves_model_delivery=False. Provisionamento/receipt do conjunto binario e prova real futura continuam pendentes.

**Clausulas fonte:** COS-A12, OD-A12, NOTE-L301.

**Corpos/consumidores lidos:** `sentra_canvas/shell_web.py:32`, `sentra_canvas/shell_web.py:40`, `sentra_canvas/shell_web.py:81`, `sentra_canvas/shell_web.py:125`, `sentra_canvas/shell_web.py:162`, `sentra_canvas/shell_web.py:188`, `sentra_canvas/shell_runtime.py:150`, `sentra_canvas/shell_runtime.py:152`, `sentra_canvas/shell_runtime.py:342`, `sentra_canvas/shell_runtime.py:368`. Hash e corpo completo no JSON.

**Estado:** conexao em fonte, sem aceite de clausula/capacidade integral e sem evidencia runtime.

### FB-26 ? Assets protegidos/quotas/GC em todas as projeções

**P1 ? open_trace ? dono principal Cobalto; composicao: Codex, Nexo.**

**Arquivos:** `browser/attachments.py`, `browser/protected_assets.py`, `sentra_mcp/services/web_history_assets.py`, `native_bridge/job_store.py`.

**Constatacao atual:** Novos protected_assets e refs/chunks presentes; bytes e journals precisam política uniforme, não basta cifra um componente.

**Fechar:** Rastrear quotas por owner/conversation/mensagem/provider, hash/CRC/ordem e chunk retry, TTL cleanup owned sem apagar evidência necessária, protected source/results/transcript, restore keys e grants de leitura.

**Clausulas fonte:** COS-A12, COS-A13, REE-GAP-06.

### FB-27 ? Join exato conta/conversa/request/message/epoch

**P0 ? open_trace ? dono principal Cobalto; composicao: Codex, Prisma.**

**Arquivos:** `native_bridge/message_identity.py`, `native_bridge/web_evidence_ingress.py`, `sentra_model_gateway/browser_host_identity.py`, `edge_extension/content-script.js`.

**Constatacao atual:** Identidade/provas v2 fontes existentes, mas extension1.7/bootstrap/host/gateway precisam estar coerentes; source signature não é prova de worker instalado.

**Fechar:** Fechar join origin MCP x-request-id->metadata request_id->conversation/message/document epoch/account/worker live; conflito não transfere dono, identidade comprovada não vira TTL heuristic; pares/receipts independentes.

**Clausulas fonte:** COS-A01, COS-A09, COS-G12.

### FB-28 ? Conta/model/effort/quota e login realmente observados

**P1 ? open_trace ? dono principal Cobalto; composicao: Prisma, Codex.**

**Arquivos:** `browser/account_catalog.py`, `sentra_model_gateway/account_models.py`, `sentra_mcp/services/web_history_usage.py`, `integrations/codex_chatgpt_web/account_catalog.py`.

**Constatacao atual:** Catalog/Automatic/usage/account source entregue; modelos Platform e conta Web são fontes diferentes e UNKNOWN não habilita account capability.

**Fechar:** Conectar snapshots upstream observados, freshness/resetwindow/backendfailures, seleção de model/effort/Automatic sem inferir plano; OAuth/device flow server-only/rotações/loginlogout/revoke da variante configurada.

**Clausulas fonte:** COS-G02, COS-A14, OD-AF04.

### FB-29 ? ChatTrust, bloqueio, app proof e refresh

**P0 ? open_trace ? dono principal Cobalto; composicao: Prisma, Codex.**

**Arquivos:** `browser/approval.py`, `sentra_mcp/services/chat_access.py`, `sentra_remote/connector_proof.py`, `edge_extension/service-worker.js`.

**Constatacao atual:** Serviços de confiança/consent/approval/proof existem; fresh schema e app instalado na conta não se provam por tunnel aberto/clone.

**Fechar:** Rastrear block imediato, trust sucessor comprovado, aprovação humana externa sem reload, prova durable invalida por tunnel/profilechange, debounce/grace/late replies/schema refresh bounded com capturas corretas.

**Clausulas fonte:** COS-A02, COS-A03, COS-A04, COS-A05, COS-A06.

### FB-30 ? Continuation e outbox sem replay ambíguo

**P1 ? open_trace ? dono principal Cobalto; composicao: Codex, Nexo.**

**Arquivos:** `native_bridge/conversation_continuation.py`, `native_bridge/compact_resume.py`, `native_bridge/outbox_recovery.py`, `sentra_mcp/services/session_checkpoint.py`.

**Constatacao atual:** Continuation/outbox source existe; root recover_completed agora verifica journal hash/receipt e não repete modelo. Prova de upload/external Send segue outro receipt.

**Fechar:** Rastrear fases summary/exclusiveclaim/preflight/commit/publish/abort no provider real, preserving system/original/children/grants/leases; atomic transcript+outbox, late replies/conflito e uncertain reconcilia sem replay.

**Clausulas fonte:** COS-G03, COS-G04, OD-FF07, OD-AF06, REE-GAP-05.

### FB-31 ? Busca/export/histórico com overflow completo

**P1 ? open_connection ? dono principal Cobalto; composicao: Prisma, Codex.**

**Arquivos:** `sentra_mcp/services/search_sessions.py`, `sentra_mcp/services/web_history_store.py`, `sentra_canvas/desktop_ui/src/shell-conversation.jsx`.

**Constatacao atual:** Busca incremental, histórico Web e export UI source presentes; shell/CLI/provider journals são camadas diferentes.

**Fechar:** Conectar índice incremental por sessão, text search ACL e páginas IDs/revisions; export mensagem/sessão resolve overflow autorizado integralmente e protege original; não reler journals enormes nem exportar só frame/resumo.

**Clausulas fonte:** COS-A11, COS-A20, COS-A13.

### FB-32 - A08 status/resultado protegido e receipt central conectados

**P1 | source_connected_acceptance_deferred | dono principal Prisma; composicao: Codex, Nexo.**

**Arquivos:** `sentra_code_mode/dispatcher.py`, `sentra_canvas/code_machine.py`, `sentra_code_mode/quickjs_runtime.py`.

**Constatacao atual:** Dispatcher._a08_execution agora chama _protected_receipt, revalida owner/operation/proposal/intent/execution/digest/tamanho e runtime proof wasmtime/ABI1/noWASI/guest_completed/fuel/memory/cpu/epoch + wasm/SBOM SHA. Historico digest-only retorna False; propose permanece False. Root CodeMachine._effect exige cap code:execute e ok/a08_satisfied/execution_verified literal True para evidence; status exige Run/WI/Machine e SUCCEEDED central receipt com proposta exata, e result compara protected value SHA com receipt. Antiga lacuna status baseado apenas no nome/digest do engine foi corrigida em ambos consumidores.

**Fechar:** Preservar resultado completo/replay exato/RUNNING UNCERTAIN/cancel/watchdog/finish failure sem nova execucao. Exigir artefato guest real/pins/SBOM e evidencia runtime autentica no caminho FB-33; quatro booleans sao condicao necessaria, nao prova por si so. Nenhuma clausula A08 aceita por existencia de source/wasm, header de engine ou bool fornecido pelo renderer. Final acceptance/restart/concurrency somente etapa autorizada.

**Clausulas fonte:** COS-A08, OD-A08.

**Corpos/consumidores lidos:** `sentra_code_mode/dispatcher.py:596`, `sentra_code_mode/dispatcher.py:642`, `sentra_code_mode/dispatcher.py:649`, `sentra_canvas/code_machine.py:95`, `sentra_canvas/code_machine.py:211`, `sentra_canvas/code_machine.py:232`. Hash/corpo no JSON.

**Estado:** conexao em fonte; sem aceite de clausula integral ou evidencia runtime.

### FB-33 - QuickJS bounded: bridge/receipt fontes; guest e execucao real pendentes

**P0 | open_connection | dono principal Prisma; composicao: Codex, Nexo, Tessela.**

**Arquivos:** `sentra_code_mode/quickjs_runtime.py`, `sentra_code_mode/dispatcher.py`, `sentra_code_mode/artifact_config.py`, `sentra_canvas/code_machine.py`, `sentra_canvas/service.py`, `sentra_canvas/shell_requests.py`, `sentra_mcp/services/pacto_product.py`, `sentra_mcp/services/learning_skills.py`.

**Constatacao atual:** Root code_* e MachineHost adapter source ja conectados, com handler antes restore. Dispatcher persiste protected receipt/runtime_proof e root condiciona evidence a execute+ok+a08_satisfied+execution_verified e central receipt/hash. service registra PACTO_ACTIONS/READS e dispatch_pacto_product, reservando mutacoes em ShellHostRequests antes callbacks; catalog/config nao executam ferramenta. Mecanismos guest C/ABI/wasmtime/fuel/epoch/watchdog/hostcall sao fontes, nao artefato materializado nem execucao nesta fase.

**Fechar:** Concluir guest ABI/pin/SBOM/wasmtime ship/pipeline Tessela-Prisma e cada tool handler com code-tool Grant/WorkItem/intento/fence/outbox central, limites CPU/memory/time/calls/output e cancel/reconcile sem replay. Learning/Selo->ReviewedLearningSkills resolver protegido concreto continua pendencia root/Forja/Prisma, sem store independente como substituto. Artefato e provas reais na fase final; bounded-js/deny-only nao substitui A08.

**Clausulas fonte:** COS-A08, OD-A08, COS-A07.

**Corpos/consumidores lidos:** `sentra_canvas/code_machine.py:211`, `sentra_canvas/service.py:297`, `sentra_mcp/services/pacto_product.py:43`, `sentra_mcp/services/pacto_product.py:70`. Hash/corpo no JSON.

**Estado:** conexao em fonte; sem aceite de clausula integral ou evidencia runtime.

### FB-34 ? Produto Code Mode integrado ao bridge único

**P1 ? open_connection ? dono principal Prisma; composicao: Codex.**

**Arquivos:** `sentra_canvas/desktop_ui/src/shell-bridge.js`, `sentra_canvas/desktop_ui/src/shell-dialogs.jsx`, `sentra_canvas/shell_code.py`.

**Constatacao atual:** code_* ações server prontas; Prisma-fechamento registra UI em implementação e source não deve entrar no sessionStorage mutation journal.

**Fechar:** Concluir propose/review/execute/cancel/status/discovery UI, samekey pending recovery, WorkItem/Grants existentes, fonte/resultados privados protegidos e disponibilidade real; nenhum segundo adapter.

**Clausulas fonte:** COS-A08, NOTE-L430.

### FB-35 ? MCPB lifecycle inteiro e cleanup owned

**P1 ? open_trace ? dono principal Prisma; composicao: Codex, Tessela.**

**Arquivos:** `sentra_mcp/services/mcpb_lifecycle.py`, `sentra_mcp/services/mcpb_http.py`, `sentra_mcp/services/mcpb_oauth.py`, `sentra_mcp/services/mcpb_supervision.py`, `sentra_canvas/service.py`.

**Constatacao atual:** Root center plugin monta stage/inspect/register/disable/supervision; lifecycle STDIO/HTTP/OAuth/sandbox source existe, mas catálogo registado não é live runtime e lista é subconjunto.

**Fechar:** Conectar install/start/probe/restart/reconcile/update/rollback/uninstall, OAuthcallback/refresh/revoke audience/scopes, evitar duplicates busyworkers/orphans, central consent e provedores reais/pins/notices.

**Clausulas fonte:** COS-G01, OD-G01.

**Corpos lidos:** `sentra_canvas/service.py:356`, `sentra_canvas/service.py:392`. Snapshot completo e hash no JSON.

### FB-36 ? Superfície mínima/consent/comandos por chamada

**P1 ? open_trace ? dono principal Prisma; composicao: Codex, Lume.**

**Arquivos:** `sentra_mcp/services/tool_exposure.py`, `sentra_mcp/tool_policy.py`, `sentra_mcp/services/action_consent_gate.py`, `sentra_interop/tool_catalog.py`.

**Constatacao atual:** Exposure/tool-policy/read-action consent e risco shell source existem. Selective similarity e classifier Git não podem conceder autorização.

**Fechar:** Ligar Core/Desktop/Plugins surfaces e snapshot epoch/schema ao modelo, read/action consent separados; allow/deny/ask sem shell string bypass ou Grant de renderer, git scopes/timeouts e recheck de cada tool.

**Clausulas fonte:** COS-A07, COS-A10, COS-G11, OD-AF08, OD-AF10.

### FB-37 ? Learning revisado->Skill pinada->ativação central

**P1 ? open_connection ? dono principal Prisma; composicao: Forja, Codex, Nexo.**

**Arquivos:** `sentra_mcp/services/skill_library.py`, `sentra_quality/learning_review.py`, `sentra_canvas/service.py`.

**Constatacao atual:** Root skill review/upgrade/rollback agora montados; source library/learning existem. Candidate/review não são Grant e pacote GitSHA não prova conteúdo executado.

**Fechar:** Ligar candidate experiência->QualityGate/custo->review SHA/manifest/capabilities->import/version->explicitactivate WorkItem; update/rollback/revoke/dedupe e disclosure autorizado, memória não eleva privilégios.

**Clausulas fonte:** COS-G07, COS-A21, OD-CF17, OD-FF10.

**Corpos lidos:** `sentra_canvas/service.py:417`, `sentra_canvas/service.py:418`. Snapshot completo e hash no JSON.

### FB-38 ? Composição Selo real no host/center/MCP

**P1 ? open_connection ? dono principal Forja; composicao: Codex, Nexo.**

**Arquivos:** `sentra_quality/provider_clients.py`, `sentra_quality/protected_state.py`, `sentra_mcp/services/policy_identity_audit.py`, `sentra_mcp/services/selo_composition.py`.

**Constatacao atual:** Na ultima releitura, build_client/SeloHostFacade ja existe: valida store/tenant, CAS/vault e contexto CentralEffectContext com intent/capability exatos antes de dispatch. A antiga ausencia do helper esta superada. Binder root/center/shell/MCP e trusted identity callbacks ainda exigem composicao.

**Fechar:** Entregar facade server-only configurável CAS/vault/tenant/workspace, dispatch/status/close com CP preeffect intent; root compõe allowlist. Reusar clientes Nexo com acordo, sem editar core/runtime alheios.

**Clausulas fonte:** ECO-20, ECO-21, ECO-22, ECO-23, REE-20, REE-21, REE-22, REE-23.

**Corpos lidos:** `sentra_mcp/services/selo_composition.py:55`, `sentra_mcp/services/selo_composition.py:182`, `sentra_mcp/services/selo_composition.py:194`. Snapshot completo e hash no JSON.

### FB-39 ? OPA/OpenFGA: veto externo com versões/consistência

**P1 ? open_connection ? dono principal Forja; composicao: Nexo, Codex.**

**Arquivos:** `sentra_quality/policy_veto_chain.py`, `sentra_mcp/services/authorization.py`, `sentra_quality/provider_clients.py`.

**Constatacao atual:** Local veto/corePDP e wrappers provider source existem; existência do cliente não liga admission. OPA indefinido/timeout é distinto de allow, FGA list não é check.

**Fechar:** Compor pós-Core allow preservando constraints/decisionID/revision/modelID; bundle activation CAS, Mask logs, ListObjects/ReadChanges invalidação e assertions preparadas; sensitive consistency e unavailable failclosed.

**Clausulas fonte:** ECO-22, ECO-23, REE-22, REE-23.

### FB-40 ? OIDC/SPIRE sessão, revogação e atestação

**P1 ? open_connection ? dono principal Forja; composicao: Nexo, Codex, Tessela.**

**Arquivos:** `sentra_quality/identity_registry.py`, `sentra_quality/provider_clients.py`, `sentra_mcp/services/policy_identity_audit.py`.

**Constatacao atual:** JWT verificado ou DeviceID não implementa login/logout/revocation/mTLS workload session. Config/client/pins e source precisam caminho até Principal.

**Fechar:** Compor OIDC callback/session/logout/revoke/consent/audience exchange e SPIRE selector attestation SVID renewal/trust federation; mapear Principal e suspender novas admissions/conexões quando revogado; sem derivar Grants.

**Clausulas fonte:** ECO-20, ECO-21, REE-20, REE-21, OD-AF05.

### FB-41 ? Audit witness independente e ledger->outbox

**P1 ? open_connection ? dono principal Forja; composicao: Codex, Nexo.**

**Arquivos:** `sentra_quality/audit_anchor.py`, `sentra_quality/audit_state.py`, `sentra_mcp/services/policy_identity_audit.py`.

**Constatacao atual:** Âncoras/proofs/quorum/trusted verifier state source existem; hashchain local não comprova witness independente nem que todos efeitos foram registrados.

**Fechar:** Compor ledger completo->outbox digests->Tessera/immudb provider real; inclusion/consistency/signed checkpoint/quorum>0/trustedstate/divergência conservada, export/restore com último estado confiável.

**Clausulas fonte:** ECO-24, ECO-25, REE-24, REE-25, REE-GAP-18.

### FB-42 ? Langfuse: cliente prompts/datasets/runs/scores

**P1 ? open_connection ? dono principal Forja; composicao: Codex.**

**Arquivos:** `sentra_quality/otel_langfuse.py`, `sentra_quality/langfuse_eval.py`, `sentra_quality/provider_clients.py`, `sentra_mcp/services/selo_composition.py`.

**Constatacao atual:** NOVO LangfuseClient contem rotas reais prompts v2/labels, datasets/items/run-items/run-get, scores v3 e OTLP, com Basic public/secret keys. O flush legado de spans nao cobre eval, mas ja nao ? o ?nico cliente. Falta rastrear uso dessa nova facade no produto e reconcile/export de cada objeto local.

**Fechar:** Compor LangfuseClient/SeloHostFacade no host com vault/profile compativel, versoes/labels/config, dataset expected, run->trace/items e scores typed/human corrections; fila/reconcile/idempotencia de cada efeito export e QualityGate/usage central. Nao reimplementar rotas ja entregues.

**Clausulas fonte:** ECO-27, REE-27.

**Corpos lidos:** `sentra_quality/provider_clients.py:103`, `sentra_quality/provider_clients.py:122`, `sentra_quality/provider_clients.py:139`, `sentra_quality/provider_clients.py:144`. Snapshot completo e hash no JSON.

### FB-43 ? OTLP pipeline configurado e diagnóstico transversal

**P1 ? open_connection ? dono principal Forja; composicao: Codex, Nexo.**

**Arquivos:** `sentra_quality/otel_langfuse.py`, `sentra_mcp/services/telemetry.py`.

**Constatacao atual:** Batch/queue/redaction fontes existem, mas sink local não configura collector externo nem persistent storage extension. SafeTelemetry nunca substitui ledger.

**Fechar:** Compor collector URL TLS/vault/optout, batching time/size/cardinality/memory/queue/retry/storage persistente real, Run/WorkItem/Op/provider/machine correlacionados; sanitizar export e relatório anonimizado.

**Clausulas fonte:** ECO-26, REE-26, OD-CF22, REE-GAP-14.

### FB-44 ? Memória/experiências/custo com escopo e validade

**P1 ? open_trace ? dono principal Forja; composicao: Nexo, Prisma.**

**Arquivos:** `memory/store.py`, `memory/costs.py`, `sentra_mcp/services/memory_costs.py`, `sentra_quality/learning_runtime.py`.

**Constatacao atual:** Store local e projeções de custo/learning existem. Memória não é autoridade; origem/validade/failure experience e proteção devem preservar instruções/ações originais.

**Fechar:** Rastrear host CP owner/tenant ACL, ciphertext/retention TTL/revoke, namespace native PG quando hospedado, search sem deserialize perigoso; custos reportados não completam budget authority nem ativam Skill.

**Clausulas fonte:** OD-CF17, OD-FF10, REE-01, REE-07, REE-GAP-07.

### FB-45 ? Release Grype/Syft sobre artefato final

**P1 ? open_connection ? dono principal Forja; composicao: Tessela, Codex.**

**Arquivos:** `sentra_quality/grype_scan.py`, `sentra_quality/grype_gate.py`, `sentra_mcp/services/grype_release.py`, `sentra_quality/release_gate.py`.

**Constatacao atual:** Runner real Grype source existe; parser-only antigo gap superado. Inventário/scan do checkout não é scanner do instalador final.

**Fechar:** Compor pipeline Syft/SBOM+Grypebinary/pins/DB freshness/matchreason/fixversion/diff/digests e gates por artefato/package, candidatos aprovados por host; preparar agora, executar somente fase final.

**Clausulas fonte:** ECO-28, REE-28.

### FB-46 ? Benchmarks: judges, datasets e snapshot separados do agente

**P1 ? open_connection ? dono principal Forja; composicao: Nexo, Lume, Codex.**

**Arquivos:** `sentra_executors/benchmark_acceptance.py`, `sentra_executors/benchmark_dataset_deployment.py`, `sentra_executors/benchmark_selo.py`, `sentra_executors/benchmark_dataset_metrics.py`.

**Constatacao atual:** Verificadores CSV/tabelas/documentos/conjunção source existem. Callback de agente ou fixture não instala datasets/VM/appreset/judgeindependent.

**Fechar:** Compor datasets pinned/goldens/evalpostconfig em snapshot, reset/captura latency/cost/trajectory, seleção fallback e structured criteria; classificar LLMjudge probabilístico e nunca expor pyautogui arbitrary replay.

**Clausulas fonte:** ECO-35, ECO-36, ECO-37, REE-35, REE-36, REE-37, REE-GAP-13.

### FB-47 - Sexto executor guest artifact: entrada Canvas entregue

**P0 | source_connected_acceptance_deferred | dono principal Codex; composicao: Forja, Nexo.**

**Arquivos:** `sentra_canvas/service.py`, `sentra_executors/integral.py`, `sentra_runtime/machine_host.py`.

**Constatacao atual:** center_configure_machine inclui windows_guest_artifact e chama host.configure_executor pelo mesmo caminho dos seis EXECUTOR_KINDS. MachineHost.restore enumera o kind; Canvas/adaptador e handler code-mode agora sao registrados antes desse restore. A omissao na allowlist Canvas foi corrigida: nao resta adicionar o kind.

**Fechar:** Conservar configuracao/identidade/WorkItem/Grant/action scopes/observe/artifact/reconcile do provider existente. Guest real/VM/builds/artefatos/provisionamento e evidencia final pertencem Forja/Nexo/Tessela/root e seguem pendentes FB-53/63/64/65. Este ticket registra a conexao em fonte, nao fecha OD-CF12/FF03/FF04/ECO-10/REE-GAP-03 nem homologa isolamento.

**Clausulas fonte:** OD-CF12, OD-FF03, OD-FF04, ECO-10, REE-GAP-03.

**Corpos/consumidores lidos:** `sentra_canvas/service.py:777`, `sentra_runtime/machine_host.py:570`. Hash e corpo completo no JSON.

**Estado:** conexao em fonte, sem aceite de clausula/capacidade integral e sem evidencia runtime.

### FB-48 ? InputLease/UIA/UFO da superfície até efeito

**P1 ? open_trace ? dono principal Forja; composicao: Codex, Nexo.**

**Arquivos:** `sentra_executors/input_control.py`, `sentra_executors/ufo_actions.py`, `sentra_canvas/shell_machines.py`.

**Constatacao atual:** InputControl durable CAS/TTL/requestkey/epoch e UFO centralUIA source entregue; mutex aliases/password redaction/hybrid source também. Interface simples não prova handoff/resolvedor por provider.

**Fechar:** Rastrear keyboard/mouse/clipboard/human+agent/preflightliveepoch em todos providers; UIA revalida PID/selector/observation antes da ação, cache e wait sem retry de efeito; plano undo não desfaz app.

**Clausulas fonte:** ECO-01, REE-01, REE-GAP-04, REE-09.

### FB-49 ? Daytona computer/PTY/preview/network/lifecycle

**P1 ? open_trace ? dono principal Forja; composicao: Lume, Codex.**

**Arquivos:** `sentra_executors/daytona_computer.py`, `sentra_executors/daytona_lifecycle.py`, `sentra_executors/daytona_sessions.py`.

**Constatacao atual:** AT-SPI real SDK, privatepreview.fetch e archive/network source entregues; token preview server-side não prova sandbox terminal completo.

**Fechar:** Compor ComputerUse/terminal volumes metadata profiles autosstop/archive/delete/reconcile, stdin/resize/kill separateGrants; distinguir disco/envsnapshot/processsession/efeito uncertain e expor health/provisioning reais.

**Clausulas fonte:** ECO-08, REE-08.

### FB-50 ? Playwright persistência, evidência e isolamento

**P1 ? open_trace ? dono principal Forja; composicao: Cobalto, Codex.**

**Arquivos:** `sentra_executors/playwright_browser.py`, `sentra_executors/browser_sessions.py`, `sentra_executors/identity_sessions.py`.

**Constatacao atual:** SessionJournal/LOST/no replay/isolatedcontexts source presente. Browser lab read-only não é executor; origin config não confina rede.

**Fechar:** Rastrear context identity/profiles/packagepins, currentelementreferences, trace/network/console/PDF/vision/devtools optin, grantnetwork/profile/secretscope, passwordredaction/protected artifacts; recuperação LOST exige nova admissão.

**Clausulas fonte:** ECO-12, REE-12, OD-FF11.

### FB-51 ? Guacamole viewer/controle/playback e canais

**P1 ? open_connection ? dono principal Forja; composicao: Prisma, Codex, Nexo.**

**Arquivos:** `sentra_executors/remote_guacamole.py`, `sentra_executors/remote_guacamole_tunnel.py`, `sentra_canvas/shell_machines.py`, `sentra_canvas/desktop_ui/src/shell-machines.jsx`.

**Constatacao atual:** Root listener lazy port0/Canvasorigin/human epoch, UIviewer e backendclipboard/selective recording presentes; importing lib não cria guacd/session.

**Fechar:** Completar conexão/provider ticket principal, display/timeline/playpause/seek e receipt actionobservations; cada audio/fs/upload/clipboard/mouse/key/touch com capability real opcional, playback nunca reenvia input.

**Clausulas fonte:** ECO-13, ECO-14, REE-13, REE-14, REE-GAP-04.

### FB-52 ? RustDesk native protocolo e canais ainda delimitados

**P1 ? open_trace ? dono principal Forja; composicao: Tessela, Codex, Prisma.**

**Arquivos:** `sentra_executors/remote_rustdesk.py`, `sentra_executors/remote_rustdesk_build.py`, `sentra_executors/remote_deployment.py`.

**Constatacao atual:** Patch control_extension v1 login/status/heartbeat/frame/input source entregue; GUI input/extras blocked. Isso fecha subset contratado, não fileclipboard/privacy/recording/relay de todas variantes.

**Fechar:** Manter backlog dos canais adicionais requeridos com API native estreita, sessão/pairing/inputlease/relayrevocation reais; preparar build/distribuição pins/licenses, sem inventar embeddingAPI ou habilitar controles GUI fora do gate.

**Clausulas fonte:** ECO-15, REE-15.

### FB-53 ? HCS/gVisor/guest isolamento e recuperação real

**P1 ? open_trace ? dono principal Forja; composicao: Tessela, Nexo.**

**Arquivos:** `sentra_executors/hcs_provider.py`, `sentra_executors/winhcs_boundary.py`, `sentra_executors/gvisor_workload.py`, `sentra_executors/gvisor_runsc.py`, `sentra_executors/windows_guest.py`.

**Constatacao atual:** Seisproviders/source limites/lifecycle/native shim presentes; VM desktop, HCS headless e Linux runsc são ambientes distintos; builds/VMs não foram feitos.

**Fechar:** Compor JobContainer/user token/uVM/mounts/limits/processdescendants, runscfs/net/caps/syscalldiag/checkpointcompat e guest separado/guestartifact; goldenimage/runtime atualização e cleanup reais por Grant, sem prometer process/socketsrestore.

**Clausulas fonte:** ECO-10, ECO-11, REE-10, REE-11, OD-FF03, OD-FF04, OD-FF16.

### FB-54 ? RPA determinística de documentos e promoção validada

**P1 ? open_trace ? dono principal Forja; composicao: Nexo, Codex.**

**Arquivos:** `sentra_executors/rpa.py`, `sentra_executors/documents.py`, `sentra_runtime/machine_host.py`.

**Constatacao atual:** Libraries/capabilities documentos são distintas de UIA macros; requisito inclui ExcelFiles/tables/PDF e temporarypromotion, não só scripts GUI.

**Fechar:** Rastrear read/write/filter/group/convert/extract/manipulate em file-scoped WorkItem, tempresult->objectivevalidator->atomicpromotion receipt; distinguir formula vs cachedvalue/recalc backend e OCR/fidelidadevisual.

**Clausulas fonte:** ECO-34, REE-34.

### FB-55 ? Viewport culling preservando sessões/PTys

**P1 ? open_implementation ? dono principal Prisma; composicao: Tessela, Codex.**

**Arquivos:** `sentra_canvas/desktop_ui/src/main.jsx`, `sentra_canvas/desktop_ui/src/terminal-pool.js`.

**Constatacao atual:** main.jsx ReactFlow onlyRenderVisibleElements=False permanece. aria-live/acessibilidade/cabos existentes não cobrem render somente visível.

**Fechar:** Separar lifecycle gráfico de ProcessSession/TerminalPool, render somente nodes visíveis/bounds/selection/neighbors/cables e retenção de terminal independente; preparar performance acceptance futura sem benchmark agora.

**Clausulas fonte:** ECO-29, REE-29, REE-GAP-12, COS-G13.

**Corpos lidos:** `sentra_canvas/desktop_ui/src/main.jsx:377`. Snapshot completo e hash no JSON.

### FB-56 ? Docs ricos: fonte pronta, conservação de todas as guardas

**P1 ? open_trace ? dono principal Tessela; composicao: Prisma, Nexo, Codex.**

**Arquivos:** `sentra_canvas/project_documents.py`, `sentra_canvas/desktop_ui/src/document-panel.jsx`, `sentra_collab/central_bridge.mjs`, `sentra_collab/authority_guard.py`.

**Constatacao atual:** Tessela final entrega hierarchy/tombstones/restore/history/CAS/receipts/drafts/TipTap/CodeMirror; PGguard sortedlocks/FORUPDATE e serverpermission mismatch foram corrigidos. Não reabrir ausência de HTTP/guard.

**Fechar:** Rastrear últimos watchrenames/pendingcreate/restore/delete/export/source/dirtyguards por documento; manter history comum/precommit/cancelrace/WorkItemGrant exato e produto sem perda na troca chatCanvas. Locks/bundle só final.

**Clausulas fonte:** OD-CF03, OD-CF04, OD-CF05, OD-CF06, COS-G10, REE-GAP-11.

### FB-57 ? CRDT callbacks/presença/autorização durável

**P1 ? open_trace ? dono principal Tessela; composicao: Codex, Prisma, Nexo.**

**Arquivos:** `sentra_collab/server.mjs`, `sentra_collab/central_bridge.mjs`, `sentra_collab/awareness_guard.mjs`, `sentra_canvas/service.py`.

**Constatacao atual:** Yjs13/Y.Text+metadata, token onetime/precommit/reauth/quarantine/undoorigin/relativecursor TTL source entregue e root callbacks ligados; não igualar awareness a lease de execução.

**Fechar:** Manter exacthostcallbacks load/commit/checkgrant/nonce e owner snapshots history, y13/y-protocols1 pin compat, clientSession clocks/expiry/dedupe/quarantine reconnection e diffstatevectors; duasmáquinas proof fase final.

**Clausulas fonte:** ECO-30, ECO-31, ECO-32, REE-30, REE-31, REE-32.

### FB-58 ? Hocuspocus multi-instância Redis permanece no escopo

**P2 ? conditional_implementation ? dono principal Tessela; composicao: Nexo, Codex.**

**Arquivos:** `sentra_collab/server.mjs`, `sentra_collab/package.json`.

**Constatacao atual:** Snapshot server constrói callbacks localhost; não localizou extensão Redis/config no server/package. Fonte prevê só quando múltiplas instâncias, e opcional não remove implementação configurável.

**Fechar:** Implementar seleção Redis quando multihost, pinned extension/networkauth/boundedlimits/propagation/coordenação sem substituir precommit CP; Redis locks de documento nunca leases de efeito.

**Clausulas fonte:** REE-32, REE-GAP-17.

### FB-59 ? Project review oito reads com versões/watchers

**P1 ? open_trace ? dono principal Tessela; composicao: Prisma, Codex.**

**Arquivos:** `sentra_canvas/project_review.py`, `sentra_canvas/desktop_ui/src/document-panel.jsx`, `sentra_canvas/service.py`.

**Constatacao atual:** ProjectReview/read-only code/diff/PDF passivo e boundedwatch renameTTL estão montados no bridge. paths existem só neste allowlist, não autorização geral fs.

**Fechar:** Conservar revision/externalchange/rootcontainment/debounce/cancelwatch and passivePDF semantics; native PDFium/deps distribution final; contextual files/terminal/activity results no shell sem desmontar PTY.

**Clausulas fonte:** COS-A18, COS-G10, OD-CF06.

### FB-60 ? Vitra facade composição central: reserva já corrigida

**P0 ? open_connection ? dono principal Tessela; composicao: Codex, Nexo.**

**Arquivos:** `sentra_remote/host_facade.py`, `sentra_remote/maintenance_ledger.py`, `sentra_remote/lifecycle_effects.py`, `sentra_canvas/service.py`.

**Constatacao atual:** host_facade agora ledger.reserve before _mutate, protectedintent/CAS/uncertain e repair runner real; antiga lacuna de pós-effectreceipt está superada. Root binder/hostresolve/checkpoint ainda necessário.

**Fechar:** Compor facade trustedpaths/IDs/config/tenant/installation, centralauthorize/offlinequiesce proof, requestkey fingerprint; body receiptstatus não pode reexecutar maintenance. Root/center/MCP executam apenas allowlist.

**Clausulas fonte:** COS-G09, REE-GAP-15, REE-GAP-16.

**Corpos lidos:** `sentra_remote/host_facade.py:258`, `sentra_remote/host_facade.py:272`, `sentra_remote/host_facade.py:401`. Snapshot completo e hash no JSON.

### FB-61 ? Backup/restauração completa/keys e migração nativa

**P1 ? open_connection ? dono principal Tessela; composicao: Nexo, Codex.**

**Arquivos:** `sentra_remote/coordinated_backup.py`, `sentra_remote/host_facade.py`, `sentra_mcp/services/authority_snapshot.py`, `sentra_mcp/services/authority_migration.py`, `sentra_mcp/services/postgres_store.py`.

**Constatacao atual:** PGnative selection/migration/rollback/backup source Nexo entregue/em andamento, Vitra delega store.backup/restore. SQLite origem preservada, recovering/uncertain/leases invalidated; não é wrapper que converteSQL.

**Fechar:** Fechar full-file roots/keys/recoverykeycustody/quiescence/nativeatomic manifests/DSNprincipalRLS/fence migrations rollback/exportSQLite e activationCAS; provar restoredfiles+cipher+providers depois sem replay de efeitos.

**Clausulas fonte:** OD-AF14, REE-GAP-15, REE-GAP-17, COS-A19.

**Corpos lidos:** `sentra_remote/host_facade.py:414`. Snapshot completo e hash no JSON.

### FB-62 ? Upgrade staged/app-exit coordenado

**P1 ? open_connection ? dono principal Tessela; composicao: Codex, Cobalto, Nexo.**

**Arquivos:** `sentra_remote/coordinated_upgrade.py`, `sentra_remote/update_helper.py`, `sentra_remote/staged_upgrade.py`, `sentra_remote/release_migration.py`.

**Constatacao atual:** APPLY_ON_EXIT/helper source existe. App/extension/WebModels/schema e handles vivos exigem um mesmo plano journal/recovery, sem parar preview.

**Fechar:** Compor staged verification->closecontrolled->helper apply->health->rollback lastfunctional; preserve liveConPTY e no blockingstartup; hostidentity1.7/pins/hashes/selection schema compatibility e fases uncertain.

**Clausulas fonte:** COS-A19, OD-FF16, REE-GAP-15.

### FB-63 ? Setup/doctor/install/remove reais de todos opcionais

**P1 ? open_connection ? dono principal Tessela; composicao: Forja, Lume, Cobalto, Prisma, Codex.**

**Arquivos:** `sentra_remote/optional_providers.py`, `sentra_remote/guest_runners.py`, `sentra_remote/sidecar_manifests.py`, `scripts/commander/release_assets.py`.

**Constatacao atual:** winget/install/probes/runners e sidecar manifest source existem; declaration manifest não configura serviço/VM/guacd/peer ou comprova executor saudável.

**Fechar:** Preparar inventory os/arch/missing/config prereqs+trusted install/renew/revoke/remove/offlinequiesce e ownedcleanup por provider; manifests de produtores pinned/SBOM/NOTICE/tlshealth e diagnostics scrubbed, sem rodar install agora.

**Clausulas fonte:** COS-G09, REE-GAP-16, OD-CF13, OD-FF16.

### FB-64 ? Pacote final/locks/builds/notices/signing reservados

**P1 ? future_artifact ? dono principal Tessela; composicao: Prisma, Forja, Lume, Cobalto, Codex.**

**Arquivos:** `sentra_remote/sidecar_manifests.py`, `scripts/commander/release_assets.py`, `scripts/commander/release_signing.py`, `sentra_canvas/desktop_ui/package.json`, `sentra_executors/INTEGRAL_PROVENANCE.json`.

**Constatacao atual:** Mascots OpenDots MIT e Guacamole1.5.0 repack SRI/LICENSE/NOTICE source entregues; pins fontes/guest pipelines existem, locks/bundle/native/WASM não materializados nesta fase.

**Fechar:** Preparar pipeline/manifest completo de SDKs/TS/nodepins/Guacamole/mascots/HCS/RustDesk/QuickJS/extension/WebModels/thirdparty hardfork e cleaninstall/rollback; executar install/build/signing legítimo apenas após liberação final.

**Clausulas fonte:** OD-CF21, OD-AF15, OD-FF17, OD-FF18, COS-G13, REE-GAP-16.

### FB-65 ? Aceitação completa posterior à integração

**P1 ? future_acceptance ? dono principal Codex; composicao: Nexo, Cobalto, Prisma, Lume, Forja, Tessela.**

**Arquivos:** `docs/integral/coverage.json`, `docs/integral/contracts.md`, `docs/integral/REDISTRIBUICAO_CODEX.md`.

**Constatacao atual:** ZERO runtime evidence produzido por Meridiano. Testes preparados de donos e leitura não homologam; externos/VMs/twohosts/PG/provideraccount pendentes reais.

**Fechar:** Somente após todas implementações/conexões integradas e liberação: realizar evidências cenários reais, restart/cancel/concurrency/permissions/uncertain/revoke/restore/cleaninstall/protocolcompat/benchmarks. Nenhum opcional desaparece.

**Clausulas fonte:** REE-GAP-01, REE-GAP-17, NOTE-L332, NOTE-L335, NOTE-L447.

### FB-66 ? GC owned e deadlines independentes da retenção

**P1 ? open_trace ? dono principal Lume; composicao: Tessela, Cobalto, Codex.**

**Arquivos:** `sentra_executors/conpty_sessions.py`, `sentra_mcp/services/mcpb_orphans.py`, `sentra_remote/managed_providers.py`, `browser/tab_pool.py`.

**Constatacao atual:** Owned process/terminal/tab cleanup source em módulos separados; fechar conversa não significa destruir todos recursos OS, deadline não comprova limpeza.

**Fechar:** Ligar ownership registry/lease+retention por recurso/tenant a close/revoke/reconcile/shutdown, não matar handles de outro Run ou preview; cancelar gate/epoch antes cleanup e preservar receipt/evidence histórica.

**Clausulas fonte:** COS-A17, REE-GAP-02, REE-GAP-09.

### FB-67 - Optional authority/lifecycle e relay: gates fontes, efeito fisico aberto

**P1 | open_trace | dono principal Nexo; composicao: Codex, Forja, Cobalto.**

**Arquivos:** `sentra_runtime/shell_optional_authority.py`, `sentra_mcp/services/shell_coordinator.py`, `sentra_canvas/shell_optional.py`, `sentra_canvas/shell_web.py`, `sentra_canvas/shell_runtime.py`.

**Constatacao atual:** execute_optional permanece no consumidor ShellCoordinator._optional antes de voice/upload mutations e registra apenas signaling/storage receipts, external_completion_claimed=False. ShellWebRuntime usa caminho separado na mesma CP: grants web:send/web:attach, protected pre-staging reserve, budget reservation, lease/fence; progress sending chama _live_account de novo, observe/recovery nunca readmitem. CanvasShellRuntime.close encerra processos, espera workers e depois web.close para parar relay. Ausencia generica de gate/lifecycle/binary consumer e superada em fonte.

**Fechar:** Conferir checkpoint/revoke/cancel/reassign/budget em cada I/O composto e canal, scopes call/ref/upload, cleanup e recovery de reserved/uncertain sem replay. Fechar clientes fisicos dos observers e produtor de frames no FB-25/27; signaling/storage e callable attachment readiness nunca completam model/audio delivery. Nenhum Gate/Grant novo pela composicao e nenhuma homologacao.

**Clausulas fonte:** REE-GAP-01, REE-GAP-05, REE-GAP-09.

**Corpos/consumidores lidos:** `sentra_runtime/shell_optional_authority.py:14`, `sentra_runtime/shell_optional_authority.py:72`, `sentra_canvas/shell_web.py:68`, `sentra_canvas/shell_web.py:155`, `sentra_canvas/shell_web.py:188`, `sentra_canvas/shell_web.py:224`, `sentra_canvas/shell_runtime.py:436`. Hash e corpo completo no JSON.

**Estado:** conexao em fonte, sem aceite de clausula/capacidade integral e sem evidencia runtime.

### FB-68 ? Consumers PG e projeções nunca dão fallback de autoridade

**P1 ? open_trace ? dono principal Nexo; composicao: Codex, Lume, Forja, Cobalto, Tessela.**

**Arquivos:** `sentra_mcp/services/postgres_store.py`, `sentra_interop/provider_store.py`, `sentra_quality/authority_guard.py`, `sentra_mcp/services/search_sessions.py`, `sentra_mcp/services/research.py`.

**Constatacao atual:** Document native guard e workflow hosted control.store estão sendo entregues; antigas afirmações globais SQLite-only devem ser substituídas. Alguns componentes legacy mantêm sqlite local de projeção.

**Fechar:** Percorrer TODOS consumers no modo PG tenant: schema/rawparams/locks/RLS/controlstore, ownerguard e proteção, classificar projection-only vs authority explicitamente. Não inferir segunda autoridade por import sqlite, nem admitir fallback silencioso.

**Clausulas fonte:** REE-GAP-17, OD-AF14, REE-GAP-10.

### FB-69 ? UX/acessibilidade contextual e identidade SENTRA

**P2 ? open_trace ? dono principal Prisma; composicao: Codex, Tessela.**

**Arquivos:** `sentra_canvas/desktop_ui/src/main.jsx`, `sentra_canvas/desktop_ui/src/shell-app.jsx`, `sentra_canvas/desktop_ui/src/shell-dialogs.jsx`.

**Constatacao atual:** UI Home/Dots/Spaces/Canvasinternal/portal/mascots/theme e draftguards source entregue; reducedmotion/aria-live já existem. Não declarar desenho todo ausente nem substituir UX por painel técnico.

**Fechar:** Rastrear keyboardfocus/focusreturn/settingssearch/shortcuts/ARIA/polling errors/composer/navigation persistence com mesmo agentID/context, painel técnico só quando necessário; source entregue, evidências finais ainda pendentes.

**Clausulas fonte:** COS-G13, OD-CF20, NOTE-L425, NOTE-L457, NOTE-L458.

## indice requisito por requisito

Cada registro mantem texto e fonte integrais na matriz. Os IDs abaixo encaminham todas as clausulas do registro; tickets de rastreio nao significam que a funcionalidade inteira esteja ausente. Crosswalk OD G/A permanece referencia da mesma capacidade COS, sem dupla contagem de implementacao.

| Requisito | Fonte:linha | Ownership atual | Backlog |
|---|---|---|---|
| OD-CF01 | OD:142 | Codex, Tessela | FB-02, FB-03, FB-63 |
| OD-CF02 | OD:143 | Nexo, Prisma | FB-01, FB-03, FB-69 |
| OD-CF03 | OD:144 | Tessela | FB-56, FB-57 |
| OD-CF04 | OD:145 | Tessela, Prisma | FB-56, FB-59 |
| OD-CF05 | OD:146 | Tessela, Prisma | FB-56 |
| OD-CF06 | OD:147 | Tessela, Cobalto | FB-31, FB-56, FB-59 |
| OD-CF07 | OD:148 | Nexo, Lume, Prisma | FB-01, FB-04, FB-36 |
| OD-CF08 | OD:149 | Forja, Lume | FB-06 |
| OD-CF09 | OD:150 | Forja, Cobalto | FB-07, FB-50 |
| OD-CF10 | OD:151 | Prisma, Lume | FB-19, FB-21, FB-36 |
| OD-CF11 | OD:152 | Prisma, Nexo | FB-05, FB-29, FB-36 |
| OD-CF12 | OD:153 | Forja | FB-47, FB-48, FB-49, FB-53 |
| OD-CF13 | OD:154 | Forja, Tessela | FB-20, FB-53, FB-63, FB-64 |
| OD-CF14 | OD:155 | Lume, Nexo | FB-01, FB-11, FB-14, FB-30 |
| OD-CF15 | OD:156 | Cobalto, Prisma, Codex | FB-24, FB-67 |
| OD-CF16 | OD:157 | Lume | FB-12, FB-22 |
| OD-CF17 | OD:158 | Forja, Prisma | FB-37, FB-44, FB-53 |
| OD-CF18 | OD:159 | Nexo, Cobalto | FB-03, FB-27, FB-28, FB-68 |
| OD-CF19 | OD:160 | Codex, Tessela | FB-07 |
| OD-CF20 | OD:161 | Prisma | FB-69 |
| OD-CF21 | OD:162 | Tessela, Codex | FB-64, FB-65 |
| OD-CF22 | OD:163 | Forja, Tessela | FB-43 |
| OD-AF01 | OD:212 | Lume | FB-02, FB-22 |
| OD-AF02 | OD:213 | Nexo, Cobalto | FB-22, FB-40 |
| OD-AF03 | OD:214 | Forja | FB-49, FB-53, FB-63 |
| OD-AF04 | OD:215 | Cobalto, Tessela | FB-28, FB-40 |
| OD-AF05 | OD:216 | Forja, Tessela | FB-26, FB-40, FB-61 |
| OD-AF06 | OD:217 | Cobalto, Lume | FB-15, FB-25, FB-30 |
| OD-AF07 | OD:218 | Lume, Nexo | FB-14, FB-30 |
| OD-AF08 | OD:219 | Prisma, Forja | FB-36, FB-39 |
| OD-AF09 | OD:220 | Prisma | FB-05, FB-29 |
| OD-AF10 | OD:221 | Forja, Prisma | FB-36 |
| OD-AF11 | OD:222 | Lume | FB-14 |
| OD-AF12 | OD:223 | Lume | FB-12, FB-14, FB-22 |
| OD-AF13 | OD:224 | Cobalto, Prisma | FB-04, FB-31 |
| OD-AF14 | OD:225 | Nexo, Tessela | FB-61, FB-68 |
| OD-AF15 | OD:226 | Codex, Tessela | FB-65 |
| OD-FF01 | OD:286 | Codex, Nexo | FB-02, FB-03 |
| OD-FF02 | OD:287 | Tessela, Lume | FB-02, FB-25, FB-60 |
| OD-FF03 | OD:288 | Forja, Tessela | FB-47, FB-53 |
| OD-FF04 | OD:289 | Forja | FB-47, FB-53, FB-63 |
| OD-FF05 | OD:290 | Prisma | FB-36, FB-39 |
| OD-FF06 | OD:291 | Prisma, Nexo | FB-05, FB-29, FB-36 |
| OD-FF07 | OD:292 | Cobalto, Nexo | FB-12, FB-25, FB-30 |
| OD-FF08 | OD:293 | Nexo, Lume | FB-02, FB-14, FB-30 |
| OD-FF09 | OD:294 | Forja | FB-07, FB-48, FB-50, FB-54 |
| OD-FF10 | OD:295 | Forja, Prisma | FB-37, FB-44, FB-53 |
| OD-FF11 | OD:296 | Forja, Cobalto | FB-27, FB-50 |
| OD-FF12 | OD:297 | Lume | FB-14 |
| OD-FF13 | OD:298 | Lume | FB-12, FB-22, FB-23 |
| OD-FF14 | OD:299 | Codex, Lume | FB-04, FB-07, FB-18 |
| OD-FF15 | OD:300 | Prisma | FB-05, FB-36, FB-69 |
| OD-FF16 | OD:301 | Tessela, Forja | FB-53, FB-62, FB-63, FB-64 |
| OD-FF17 | OD:302 | Tessela, Codex | FB-64, FB-65 |
| OD-FF18 | OD:303 | Tessela, Forja | FB-23, FB-64 |
| OD-G01 | OD:398 | Prisma, Tessela, Codex | FB-35 |
| OD-G02 | OD:399 | Cobalto, Prisma, Tessela | FB-28 |
| OD-G03 | OD:400 | Cobalto, Nexo | FB-30 |
| OD-G04 | OD:401 | Cobalto | FB-25, FB-27, FB-30 |
| OD-G05 | OD:402 | Lume, Nexo | FB-01, FB-11, FB-16 |
| OD-G06 | OD:403 | Lume | FB-15, FB-66 |
| OD-G07 | OD:404 | Prisma | FB-37 |
| OD-G08 | OD:405 | Prisma, Codex | FB-07, FB-36 |
| OD-G09 | OD:406 | Tessela | FB-60, FB-63 |
| OD-G10 | OD:407 | Tessela, Prisma | FB-56, FB-59 |
| OD-G11 | OD:408 | Forja, Prisma | FB-36 |
| OD-G12 | OD:409 | Cobalto | FB-27, FB-29, FB-50 |
| OD-G13 | OD:410 | Prisma, Tessela | FB-55, FB-64, FB-65, FB-69 |
| OD-A01 | OD:411 | Cobalto, Prisma, Codex | FB-27 |
| OD-A02 | OD:412 | Prisma | FB-29 |
| OD-A03 | OD:413 | Prisma, Cobalto | FB-29 |
| OD-A04 | OD:414 | Cobalto, Prisma | FB-05, FB-29 |
| OD-A05 | OD:415 | Cobalto, Tessela | FB-29 |
| OD-A06 | OD:416 | Prisma, Cobalto, Tessela | FB-19, FB-29, FB-35 |
| OD-A07 | OD:417 | Prisma, Lume | FB-21, FB-33, FB-36 |
| OD-A08 | OD:418 | Prisma | FB-32, FB-33, FB-34 |
| OD-A09 | OD:419 | Cobalto, Tessela | FB-27, FB-64 |
| OD-A10 | OD:420 | Prisma, Codex | FB-07, FB-36 |
| OD-A11 | OD:421 | Cobalto, Nexo, Prisma | FB-31 |
| OD-A12 | OD:422 | Cobalto, Prisma | FB-25, FB-26 |
| OD-A13 | OD:423 | Cobalto | FB-04, FB-26, FB-31 |
| OD-A14 | OD:424 | Cobalto, Forja | FB-28 |
| OD-A15 | OD:425 | Tessela, Forja | FB-43, FB-63 |
| OD-A16 | OD:426 | Lume, Prisma, Tessela | FB-04, FB-36, FB-48 |
| OD-A17 | OD:427 | Lume, Forja | FB-15, FB-66 |
| OD-A18 | OD:428 | Tessela, Prisma | FB-59 |
| OD-A19 | OD:429 | Tessela | FB-61, FB-62 |
| OD-A20 | OD:430 | Cobalto, Prisma | FB-31, FB-56 |
| OD-A21 | OD:431 | Prisma, Tessela | FB-37 |
| COS-G01 | COS:24 | Prisma, Tessela, Codex | FB-35 |
| COS-G02 | COS:25 | Cobalto, Prisma, Tessela | FB-28 |
| COS-G03 | COS:26 | Cobalto, Nexo | FB-30 |
| COS-G04 | COS:27 | Cobalto | FB-25, FB-27, FB-30 |
| COS-G05 | COS:28 | Lume, Nexo | FB-01, FB-11, FB-16 |
| COS-G06 | COS:29 | Lume | FB-15, FB-66 |
| COS-G07 | COS:30 | Prisma | FB-37 |
| COS-G08 | COS:31 | Prisma, Codex | FB-07, FB-36 |
| COS-G09 | COS:32 | Tessela | FB-60, FB-63 |
| COS-G10 | COS:33 | Tessela, Prisma | FB-56, FB-59 |
| COS-G11 | COS:34 | Forja, Prisma | FB-36 |
| COS-G12 | COS:35 | Cobalto | FB-27, FB-29, FB-50 |
| COS-G13 | COS:36 | Prisma, Tessela | FB-55, FB-64, FB-65, FB-69 |
| COS-A01 | COS:101 | Cobalto, Prisma, Codex | FB-27 |
| COS-A02 | COS:102 | Prisma | FB-29 |
| COS-A03 | COS:103 | Prisma, Cobalto | FB-29 |
| COS-A04 | COS:104 | Cobalto, Prisma | FB-05, FB-29 |
| COS-A05 | COS:105 | Cobalto, Tessela | FB-29 |
| COS-A06 | COS:106 | Prisma, Cobalto, Tessela | FB-19, FB-29, FB-35 |
| COS-A07 | COS:107 | Prisma, Lume | FB-21, FB-33, FB-36 |
| COS-A08 | COS:108 | Prisma | FB-32, FB-33, FB-34 |
| COS-A09 | COS:109 | Cobalto, Tessela | FB-27, FB-64 |
| COS-A10 | COS:110 | Prisma, Codex | FB-07, FB-36 |
| COS-A11 | COS:116 | Cobalto, Nexo, Prisma | FB-31 |
| COS-A12 | COS:117 | Cobalto, Prisma | FB-25, FB-26 |
| COS-A13 | COS:118 | Cobalto | FB-04, FB-26, FB-31 |
| COS-A14 | COS:119 | Cobalto, Forja | FB-28 |
| COS-A15 | COS:120 | Tessela, Forja | FB-43, FB-63 |
| COS-A16 | COS:121 | Lume, Prisma, Tessela | FB-04, FB-36, FB-48 |
| COS-A17 | COS:126 | Lume, Forja | FB-15, FB-66 |
| COS-A18 | COS:127 | Tessela, Prisma | FB-59 |
| COS-A19 | COS:128 | Tessela | FB-61, FB-62 |
| COS-A20 | COS:129 | Cobalto, Prisma | FB-31, FB-56 |
| COS-A21 | COS:130 | Prisma, Tessela | FB-37 |
| ECO-01 | ECO:74 | Forja, Nexo | FB-37, FB-44, FB-48 |
| ECO-02 | ECO:88 | Lume, Prisma, Nexo | FB-04, FB-16, FB-69 |
| ECO-03 | ECO:102 | Lume, Cobalto, Nexo | FB-16, FB-30, FB-36 |
| ECO-04 | ECO:116 | Lume | FB-05, FB-17 |
| ECO-05 | ECO:130 | Lume, Tessela | FB-20, FB-63 |
| ECO-06 | ECO:144 | Lume | FB-05, FB-18 |
| ECO-07 | ECO:158 | Lume, Prisma | FB-05, FB-19 |
| ECO-08 | ECO:174 | Forja, Lume | FB-15, FB-49 |
| ECO-09 | ECO:188 | Forja | FB-48 |
| ECO-10 | ECO:202 | Forja, Tessela | FB-47, FB-53 |
| ECO-11 | ECO:216 | Forja, Tessela | FB-53 |
| ECO-12 | ECO:230 | Forja, Cobalto | FB-27, FB-50 |
| ECO-13 | ECO:244 | Forja, Prisma, Codex | FB-51 |
| ECO-14 | ECO:258 | Forja, Tessela | FB-51 |
| ECO-15 | ECO:272 | Forja, Tessela | FB-52 |
| ECO-16 | ECO:288 | Lume | FB-08, FB-09, FB-10, FB-11 |
| ECO-17 | ECO:302 | Lume | FB-08, FB-10, FB-11, FB-14 |
| ECO-18 | ECO:316 | Lume, Forja, Codex | FB-12 |
| ECO-19 | ECO:332 | Lume, Prisma | FB-21, FB-36 |
| ECO-20 | ECO:346 | Forja | FB-38, FB-40 |
| ECO-21 | ECO:360 | Forja | FB-38, FB-40 |
| ECO-22 | ECO:374 | Forja | FB-38, FB-39 |
| ECO-23 | ECO:388 | Forja | FB-38, FB-39 |
| ECO-24 | ECO:404 | Forja | FB-38, FB-41 |
| ECO-25 | ECO:418 | Forja | FB-38, FB-41 |
| ECO-26 | ECO:432 | Forja | FB-38, FB-43 |
| ECO-27 | ECO:446 | Forja | FB-37, FB-38, FB-42, FB-44 |
| ECO-28 | ECO:460 | Forja, Tessela | FB-45, FB-64 |
| ECO-29 | ECO:476 | Prisma, Codex | FB-55, FB-69 |
| ECO-30 | ECO:490 | Tessela | FB-56, FB-57 |
| ECO-31 | ECO:504 | Tessela | FB-57 |
| ECO-32 | ECO:518 | Tessela | FB-57, FB-58 |
| ECO-33 | ECO:534 | Lume | FB-13 |
| ECO-34 | ECO:548 | Forja, Tessela | FB-54 |
| ECO-35 | ECO:564 | Forja | FB-46 |
| ECO-36 | ECO:578 | Forja | FB-46 |
| ECO-37 | ECO:592 | Forja | FB-46 |
| REE-01 | REE:92 | Forja, Nexo | FB-37, FB-44, FB-48 |
| REE-02 | REE:104 | Lume, Prisma, Nexo | FB-04, FB-16, FB-69 |
| REE-03 | REE:116 | Lume, Cobalto, Nexo | FB-16, FB-30, FB-36 |
| REE-04 | REE:128 | Lume | FB-05, FB-17 |
| REE-05 | REE:140 | Lume, Tessela | FB-20, FB-63 |
| REE-06 | REE:152 | Lume | FB-05, FB-18 |
| REE-07 | REE:164 | Lume, Prisma | FB-05, FB-19 |
| REE-08 | REE:176 | Forja, Lume | FB-15, FB-49 |
| REE-09 | REE:188 | Forja | FB-48 |
| REE-10 | REE:200 | Forja, Tessela | FB-47, FB-53 |
| REE-11 | REE:212 | Forja, Tessela | FB-53 |
| REE-12 | REE:224 | Forja, Cobalto | FB-27, FB-50 |
| REE-13 | REE:236 | Forja, Prisma, Codex | FB-51 |
| REE-14 | REE:248 | Forja, Tessela | FB-51 |
| REE-15 | REE:260 | Forja, Tessela | FB-52 |
| REE-16 | REE:272 | Lume | FB-08, FB-09, FB-10, FB-11 |
| REE-17 | REE:284 | Lume | FB-08, FB-10, FB-11, FB-14 |
| REE-18 | REE:296 | Lume, Forja, Codex | FB-12 |
| REE-19 | REE:308 | Lume, Prisma | FB-21, FB-36 |
| REE-20 | REE:320 | Forja | FB-38, FB-40 |
| REE-21 | REE:332 | Forja | FB-38, FB-40 |
| REE-22 | REE:344 | Forja | FB-38, FB-39 |
| REE-23 | REE:356 | Forja | FB-38, FB-39 |
| REE-24 | REE:368 | Forja | FB-38, FB-41 |
| REE-25 | REE:380 | Forja | FB-38, FB-41 |
| REE-26 | REE:392 | Forja | FB-38, FB-43 |
| REE-27 | REE:404 | Forja | FB-37, FB-38, FB-42, FB-44 |
| REE-28 | REE:416 | Forja, Tessela | FB-45, FB-64 |
| REE-29 | REE:428 | Prisma, Codex | FB-55, FB-69 |
| REE-30 | REE:440 | Tessela | FB-56, FB-57 |
| REE-31 | REE:452 | Tessela | FB-57 |
| REE-32 | REE:464 | Tessela | FB-57, FB-58 |
| REE-33 | REE:476 | Lume | FB-13 |
| REE-34 | REE:488 | Forja, Tessela | FB-54 |
| REE-35 | REE:500 | Forja | FB-46 |
| REE-36 | REE:512 | Forja | FB-46 |
| REE-37 | REE:524 | Forja | FB-46 |
| REE-GAP-01 | REE:542 | Lume | FB-01, FB-02, FB-11, FB-67 |
| REE-GAP-02 | REE:543 | Forja, Lume | FB-15, FB-66 |
| REE-GAP-03 | REE:544 | Forja | FB-47, FB-53 |
| REE-GAP-04 | REE:545 | Forja, Cobalto | FB-48, FB-51, FB-52 |
| REE-GAP-05 | REE:546 | Lume, Forja | FB-25, FB-30, FB-60, FB-67 |
| REE-GAP-06 | REE:547 | Forja, Lume | FB-26, FB-46, FB-50 |
| REE-GAP-07 | REE:548 | Lume, Forja, Cobalto | FB-37, FB-44 |
| REE-GAP-08 | REE:549 | Lume, Tessela | FB-17, FB-19, FB-20, FB-21, FB-35, FB-36 |
| REE-GAP-09 | REE:550 | Forja | FB-27, FB-29, FB-35, FB-40, FB-66 |
| REE-GAP-10 | REE:551 | Lume, Cobalto | FB-04, FB-12, FB-18, FB-30, FB-68 |
| REE-GAP-11 | REE:552 | Tessela, Prisma | FB-56, FB-57, FB-69 |
| REE-GAP-12 | REE:553 | Prisma | FB-55 |
| REE-GAP-13 | REE:554 | Forja | FB-37, FB-42, FB-46, FB-54 |
| REE-GAP-14 | REE:555 | Forja | FB-38, FB-43, FB-63 |
| REE-GAP-15 | REE:556 | Forja, Lume, Tessela | FB-60, FB-61, FB-62 |
| REE-GAP-16 | REE:557 | Forja, Lume, Tessela | FB-20, FB-33, FB-45, FB-53, FB-63, FB-64 |
| REE-GAP-17 | REE:558 | Nexo, Forja, Cobalto | FB-58, FB-61, FB-68 |
| REE-GAP-18 | REE:559 | Forja | FB-41 |
| NOTE-L001 | NOTE:1 | Codex | FB-34 |
| NOTE-L003 | NOTE:3 | Codex | FB-01 |
| NOTE-L004 | NOTE:4 | Codex | FB-03 |
| NOTE-L005 | NOTE:5 | Codex | FB-01 |
| NOTE-L006 | NOTE:6 | Lume, Forja | FB-08, FB-16, FB-41, FB-49, FB-55 |
| NOTE-L007 | NOTE:7 | Codex | FB-01 |
| NOTE-L008 | NOTE:8 | Codex | FB-03, FB-06 |
| NOTE-L018 | NOTE:18 | Codex | FB-03 |
| NOTE-L019 | NOTE:19 | Tessela | FB-44, FB-48, FB-56, FB-57 |
| NOTE-L020 | NOTE:20 | Prisma | FB-28, FB-59, FB-69 |
| NOTE-L021 | NOTE:21 | Tessela, Prisma | FB-04, FB-56 |
| NOTE-L034 | NOTE:34 | Codex | FB-03 |
| NOTE-L035 | NOTE:35 | Cobalto | FB-48 |
| NOTE-L036 | NOTE:36 | Lume | FB-14 |
| NOTE-L037 | NOTE:37 | Codex | FB-01 |
| NOTE-L050 | NOTE:50 | Codex | FB-03, FB-23 |
| NOTE-L051 | NOTE:51 | Codex | FB-48 |
| NOTE-L052 | NOTE:52 | Forja, Cobalto | FB-04, FB-12, FB-30, FB-53 |
| NOTE-L053 | NOTE:53 | Codex | FB-01 |
| NOTE-L057 | NOTE:57 | Codex | FB-07 |
| NOTE-L058 | NOTE:58 | Codex | FB-03 |
| NOTE-L059 | NOTE:59 | Codex | FB-01 |
| NOTE-L060 | NOTE:60 | Tessela | FB-56, FB-59 |
| NOTE-L061 | NOTE:61 | Tessela | FB-56 |
| NOTE-L062 | NOTE:62 | Codex | FB-31 |
| NOTE-L063 | NOTE:63 | Nexo | FB-01, FB-03, FB-16 |
| NOTE-L064 | NOTE:64 | Codex | FB-01 |
| NOTE-L065 | NOTE:65 | Lume | FB-14 |
| NOTE-L066 | NOTE:66 | Codex | FB-01 |
| NOTE-L067 | NOTE:67 | Prisma | FB-05, FB-29, FB-36 |
| NOTE-L068 | NOTE:68 | Cobalto | FB-12, FB-30 |
| NOTE-L069 | NOTE:69 | Codex | FB-04 |
| NOTE-L070 | NOTE:70 | Forja | FB-53 |
| NOTE-L071 | NOTE:71 | Codex | FB-01 |
| NOTE-L072 | NOTE:72 | Cobalto | FB-03, FB-28 |
| NOTE-L073 | NOTE:73 | Codex | FB-01 |
| NOTE-L074 | NOTE:74 | Codex | FB-03, FB-41 |
| NOTE-L075 | NOTE:75 | Codex | FB-01 |
| NOTE-L076 | NOTE:76 | Lume, Prisma | FB-15, FB-16, FB-50, FB-69 |
| NOTE-L077 | NOTE:77 | Forja | FB-38 |
| NOTE-L078 | NOTE:78 | Lume | FB-17 |
| NOTE-L079 | NOTE:79 | Lume | FB-17 |
| NOTE-L080 | NOTE:80 | Forja | FB-49 |
| NOTE-L081 | NOTE:81 | Forja | FB-38 |
| NOTE-L082 | NOTE:82 | Codex | FB-50 |
| NOTE-L083 | NOTE:83 | Prisma | FB-55 |
| NOTE-L084 | NOTE:84 | Lume, Tessela | FB-14, FB-57 |
| NOTE-L085 | NOTE:85 | Lume | FB-08, FB-10, FB-11 |
| NOTE-L086 | NOTE:86 | Lume, Prisma | FB-08, FB-09, FB-10 |
| NOTE-L087 | NOTE:87 | Lume | FB-12, FB-14 |
| NOTE-L088 | NOTE:88 | Codex | FB-21, FB-36, FB-53 |
| NOTE-L089 | NOTE:89 | Forja, Tessela | FB-38, FB-39 |
| NOTE-L090 | NOTE:90 | Forja | FB-04, FB-42, FB-43 |
| NOTE-L091 | NOTE:91 | Codex | FB-10, FB-11, FB-13 |
| NOTE-L092 | NOTE:92 | Codex | FB-50 |
| NOTE-L093 | NOTE:93 | Tessela | FB-41 |
| NOTE-L094 | NOTE:94 | Codex | FB-01 |
| NOTE-L095 | NOTE:95 | Codex | FB-01 |
| NOTE-L096 | NOTE:96 | Codex | FB-01 |
| NOTE-L097 | NOTE:97 | Cobalto | FB-27 |
| NOTE-L098 | NOTE:98 | Cobalto | FB-30 |
| NOTE-L099 | NOTE:99 | Cobalto | FB-12, FB-30 |
| NOTE-L100 | NOTE:100 | Codex | FB-27 |
| NOTE-L101 | NOTE:101 | Codex | FB-05, FB-29 |
| NOTE-L102 | NOTE:102 | Lume | FB-11, FB-16, FB-35 |
| NOTE-L103 | NOTE:103 | Cobalto | FB-03, FB-28 |
| NOTE-L104 | NOTE:104 | Prisma, Tessela | FB-35, FB-41 |
| NOTE-L105 | NOTE:105 | Prisma, Tessela | FB-19, FB-37 |
| NOTE-L106 | NOTE:106 | Lume | FB-15 |
| NOTE-L107 | NOTE:107 | Codex | FB-05, FB-06, FB-31 |
| NOTE-L108 | NOTE:108 | Tessela, Cobalto, Prisma | FB-25, FB-67, FB-69 |
| NOTE-L109 | NOTE:109 | Codex | FB-43 |
| NOTE-L110 | NOTE:110 | Tessela | FB-20, FB-60, FB-63 |
| NOTE-L111 | NOTE:111 | Codex | FB-10, FB-65 |
| NOTE-L112 | NOTE:112 | Codex | FB-01 |
| NOTE-L113 | NOTE:113 | Codex | FB-01 |
| NOTE-L115 | NOTE:115 | Codex | FB-01 |
| NOTE-L116 | NOTE:116 | Cobalto | FB-04, FB-05, FB-12, FB-29, FB-30 |
| NOTE-L120 | NOTE:120 | Cobalto | FB-03, FB-28 |
| NOTE-L121 | NOTE:121 | Cobalto | FB-01, FB-30 |
| NOTE-L125 | NOTE:125 | Prisma | FB-69 |
| NOTE-L126 | NOTE:126 | Tessela, Prisma | FB-31, FB-56, FB-57, FB-69 |
| NOTE-L130 | NOTE:130 | Forja | FB-35 |
| NOTE-L131 | NOTE:131 | Forja | FB-49, FB-50 |
| NOTE-L135 | NOTE:135 | Prisma, Lume | FB-35, FB-37 |
| NOTE-L136 | NOTE:136 | Prisma, Lume | FB-28, FB-35, FB-53 |
| NOTE-L140 | NOTE:140 | Codex | FB-01 |
| NOTE-L141 | NOTE:141 | Lume | FB-10, FB-11, FB-14 |
| NOTE-L145 | NOTE:145 | Codex | FB-03, FB-07 |
| NOTE-L146 | NOTE:146 | Tessela | FB-56 |
| NOTE-L147 | NOTE:147 | Codex | FB-03, FB-06, FB-31 |
| NOTE-L150 | NOTE:150 | Tessela | FB-06, FB-56 |
| NOTE-L151 | NOTE:151 | Lume, Cobalto, Prisma | FB-02, FB-03, FB-16 |
| NOTE-L152 | NOTE:152 | Cobalto | FB-03, FB-28, FB-35 |
| NOTE-L169 | NOTE:169 | Tessela | FB-56 |
| NOTE-L182 | NOTE:182 | Codex | FB-01 |
| NOTE-L189 | NOTE:189 | Codex | FB-03, FB-06, FB-31, FB-41, FB-47 |
| NOTE-L190 | NOTE:190 | Prisma | FB-47, FB-65 |
| NOTE-L191 | NOTE:191 | Tessela | FB-07, FB-56 |
| NOTE-L192 | NOTE:192 | Codex | FB-01 |
| NOTE-L194 | NOTE:194 | Forja | FB-38 |
| NOTE-L195 | NOTE:195 | Codex | FB-01 |
| NOTE-L196 | NOTE:196 | Codex | FB-01 |
| NOTE-L199 | NOTE:199 | Tessela | FB-56 |
| NOTE-L200 | NOTE:200 | Tessela | FB-56 |
| NOTE-L201 | NOTE:201 | Codex | FB-34, FB-41 |
| NOTE-L202 | NOTE:202 | Codex | FB-01 |
| NOTE-L203 | NOTE:203 | Tessela | FB-60 |
| NOTE-L204 | NOTE:204 | Lume, Prisma, Cobalto | FB-03, FB-11, FB-12, FB-16, FB-28, FB-30, FB-35, FB-37, FB-43, FB-59 |
| NOTE-L205 | NOTE:205 | Codex | FB-01 |
| NOTE-L206 | NOTE:206 | Codex | FB-10, FB-65 |
| NOTE-L207 | NOTE:207 | Forja, Lume, Tessela | FB-08, FB-09, FB-13, FB-16, FB-21, FB-36, FB-38, FB-39, FB-49, FB-55 |
| NOTE-L208 | NOTE:208 | Tessela | FB-07, FB-56 |
| NOTE-L209 | NOTE:209 | Tessela | FB-03, FB-56 |
| NOTE-L210 | NOTE:210 | Codex | FB-03, FB-06 |
| NOTE-L212 | NOTE:212 | Codex | FB-01 |
| NOTE-L213 | NOTE:213 | Codex | FB-03, FB-06, FB-31 |
| NOTE-L214 | NOTE:214 | Codex | FB-01 |
| NOTE-L217 | NOTE:217 | Codex | FB-01 |
| NOTE-L218 | NOTE:218 | Codex | FB-03 |
| NOTE-L219 | NOTE:219 | Codex | FB-03 |
| NOTE-L220 | NOTE:220 | Codex | FB-03, FB-23 |
| NOTE-L221 | NOTE:221 | Tessela | FB-06, FB-56 |
| NOTE-L222 | NOTE:222 | Codex | FB-03 |
| NOTE-L223 | NOTE:223 | Codex | FB-41 |
| NOTE-L224 | NOTE:224 | Codex | FB-65 |
| NOTE-L225 | NOTE:225 | Lume, Tessela, Cobalto | FB-03, FB-04, FB-06, FB-07, FB-12, FB-14, FB-28, FB-30, FB-31, FB-59 |
| NOTE-L226 | NOTE:226 | Cobalto | FB-28 |
| NOTE-L227 | NOTE:227 | Codex | FB-31, FB-41, FB-56 |
| NOTE-L229 | NOTE:229 | Codex | FB-01 |
| NOTE-L230 | NOTE:230 | Codex | FB-01 |
| NOTE-L231 | NOTE:231 | Codex | FB-01 |
| NOTE-L232 | NOTE:232 | Codex | FB-01 |
| NOTE-L234 | NOTE:234 | Tessela | FB-04 |
| NOTE-L235 | NOTE:235 | Codex | FB-01 |
| NOTE-L236 | NOTE:236 | Prisma | FB-69 |
| NOTE-L237 | NOTE:237 | Codex | FB-01 |
| NOTE-L240 | NOTE:240 | Codex | FB-02 |
| NOTE-L241 | NOTE:241 | Codex | FB-02, FB-04 |
| NOTE-L244 | NOTE:244 | Cobalto | FB-03, FB-28 |
| NOTE-L245 | NOTE:245 | Codex | FB-01 |
| NOTE-L248 | NOTE:248 | Codex | FB-01 |
| NOTE-L249 | NOTE:249 | Forja | FB-49, FB-50 |
| NOTE-L252 | NOTE:252 | Codex | FB-01 |
| NOTE-L253 | NOTE:253 | Lume | FB-10, FB-11, FB-14 |
| NOTE-L256 | NOTE:256 | Codex | FB-68 |
| NOTE-L257 | NOTE:257 | Codex | FB-31, FB-37, FB-41, FB-44 |
| NOTE-L262 | NOTE:262 | Codex | FB-01 |
| NOTE-L272 | NOTE:272 | Codex | FB-01 |
| NOTE-L273 | NOTE:273 | Codex | FB-05, FB-31, FB-65 |
| NOTE-L286 | NOTE:286 | Codex | FB-01 |
| NOTE-L287 | NOTE:287 | Tessela, Forja | FB-56 |
| NOTE-L300 | NOTE:300 | Codex | FB-01 |
| NOTE-L301 | NOTE:301 | Tessela, Cobalto | FB-05, FB-25, FB-27, FB-56, FB-67 |
| NOTE-L314 | NOTE:314 | Codex | FB-35 |
| NOTE-L315 | NOTE:315 | Codex | FB-44 |
| NOTE-L319 | NOTE:319 | Codex | FB-01 |
| NOTE-L320 | NOTE:320 | Codex | FB-01 |
| NOTE-L321 | NOTE:321 | Tessela | FB-56, FB-65 |
| NOTE-L323 | NOTE:323 | Tessela | FB-60 |
| NOTE-L324 | NOTE:324 | Prisma | FB-05 |
| NOTE-L325 | NOTE:325 | Codex | FB-01 |
| NOTE-L326 | NOTE:326 | Codex | FB-01 |
| NOTE-L327 | NOTE:327 | Codex | FB-01 |
| NOTE-L328 | NOTE:328 | Codex | FB-01 |
| NOTE-L329 | NOTE:329 | Codex | FB-06 |
| NOTE-L330 | NOTE:330 | Codex | FB-01 |
| NOTE-L331 | NOTE:331 | Prisma | FB-69 |
| NOTE-L332 | NOTE:332 | Codex | FB-65 |
| NOTE-L333 | NOTE:333 | Tessela | FB-60 |
| NOTE-L334 | NOTE:334 | Codex | FB-28, FB-65 |
| NOTE-L335 | NOTE:335 | Tessela | FB-19, FB-64, FB-65 |
| NOTE-L337 | NOTE:337 | Codex | FB-47, FB-57 |
| NOTE-L338 | NOTE:338 | Forja | FB-38 |
| NOTE-L339 | NOTE:339 | Codex | FB-44 |
| NOTE-L356 | NOTE:356 | Prisma | FB-01, FB-03, FB-69 |
| NOTE-L369 | NOTE:369 | Codex | FB-01 |
| NOTE-L376 | NOTE:376 | Prisma | FB-03, FB-44, FB-69 |
| NOTE-L377 | NOTE:377 | Codex | FB-01 |
| NOTE-L378 | NOTE:378 | Nexo, Tessela | FB-03, FB-34, FB-47, FB-56 |
| NOTE-L380 | NOTE:380 | Codex | FB-01 |
| NOTE-L381 | NOTE:381 | Codex | FB-01 |
| NOTE-L385 | NOTE:385 | Codex | FB-01 |
| NOTE-L386 | NOTE:386 | Codex | FB-01 |
| NOTE-L388 | NOTE:388 | Codex | FB-01 |
| NOTE-L391 | NOTE:391 | Codex | FB-01 |
| NOTE-L392 | NOTE:392 | Codex | FB-01 |
| NOTE-L394 | NOTE:394 | Codex | FB-03 |
| NOTE-L396 | NOTE:396 | Nexo | FB-03 |
| NOTE-L398 | NOTE:398 | Prisma | FB-69 |
| NOTE-L400 | NOTE:400 | Codex | FB-01 |
| NOTE-L404 | NOTE:404 | Nexo | FB-01 |
| NOTE-L406 | NOTE:406 | Codex | FB-01 |
| NOTE-L407 | NOTE:407 | Codex | FB-01 |
| NOTE-L409 | NOTE:409 | Codex | FB-01 |
| NOTE-L410 | NOTE:410 | Codex | FB-02 |
| NOTE-L411 | NOTE:411 | Codex | FB-01 |
| NOTE-L414 | NOTE:414 | Prisma | FB-69 |
| NOTE-L416 | NOTE:416 | Prisma | FB-01, FB-04, FB-69 |
| NOTE-L422 | NOTE:422 | Codex | FB-01 |
| NOTE-L423 | NOTE:423 | Codex | FB-01 |
| NOTE-L424 | NOTE:424 | Codex | FB-44 |
| NOTE-L425 | NOTE:425 | Prisma | FB-03, FB-69 |
| NOTE-L426 | NOTE:426 | Nexo | FB-01, FB-16, FB-35 |
| NOTE-L427 | NOTE:427 | Cobalto | FB-03, FB-28, FB-31 |
| NOTE-L428 | NOTE:428 | Nexo, Tessela | FB-03, FB-56 |
| NOTE-L429 | NOTE:429 | Prisma | FB-69 |
| NOTE-L430 | NOTE:430 | Codex | FB-15, FB-50, FB-69 |
| NOTE-L431 | NOTE:431 | Prisma | FB-69 |
| NOTE-L432 | NOTE:432 | Codex | FB-01 |
| NOTE-L433 | NOTE:433 | Prisma | FB-01, FB-06, FB-65 |
| NOTE-L435 | NOTE:435 | Prisma | FB-01, FB-35 |
| NOTE-L436 | NOTE:436 | Prisma | FB-03, FB-69 |
| NOTE-L437 | NOTE:437 | Codex | FB-01 |
| NOTE-L438 | NOTE:438 | Codex | FB-02, FB-06 |
| NOTE-L440 | NOTE:440 | Prisma | FB-69 |
| NOTE-L441 | NOTE:441 | Codex | FB-01 |
| NOTE-L442 | NOTE:442 | Prisma | FB-02, FB-08, FB-55 |
| NOTE-L443 | NOTE:443 | Codex | FB-61 |
| NOTE-L444 | NOTE:444 | Nexo | FB-03 |
| NOTE-L445 | NOTE:445 | Prisma | FB-69 |
| NOTE-L446 | NOTE:446 | Nexo | FB-01, FB-02, FB-16, FB-36 |
| NOTE-L447 | NOTE:447 | Lume, Prisma | FB-14, FB-65, FB-66 |
| NOTE-L448 | NOTE:448 | Codex | FB-02, FB-03 |
| NOTE-L449 | NOTE:449 | Tessela, Prisma | FB-03, FB-28, FB-44, FB-69 |
| NOTE-L451 | NOTE:451 | Codex | FB-01 |
| NOTE-L452 | NOTE:452 | Codex | FB-01 |
| NOTE-L456 | NOTE:456 | Codex | FB-27, FB-34 |
| NOTE-L457 | NOTE:457 | Codex | FB-03 |
| NOTE-L458 | NOTE:458 | Prisma | FB-69 |
| NOTE-L459 | NOTE:459 | Codex | FB-44 |
| NOTE-L461 | NOTE:461 | Nexo, Prisma | FB-03, FB-07, FB-61, FB-69 |
| NOTE-L463 | NOTE:463 | Prisma | FB-69 |
| NOTE-L465 | NOTE:465 | Codex | FB-03, FB-07 |

## Clausulas fora das linhas de catalogo

As 2.176 clausulas nao vazias incluem ordem, contrato shell, narrativa da nota, mecanismos de estudo, tabelas, exemplos, limitacoes, proveniencia e gates finais. `source_clause_audit` conserva cada texto/linha/heading/dono/associacao. Contexto nao ? removido; classificacao nao concede aceite nem reduz escopo. Toda clausula normativa sem vinculo inequivoco de corpo/consumidor continua rastreio aberto do dono listado. Keyword mapping auxilia encaminhamento e **nao comprova cobertura semantica integral**.

Nenhuma implantacao/conta autenticada/SDK instalado/VM/guacd/peer/PG/Redis/witness/collector/assinatura/guestWASM ? simulada. Variantes opcionais continuam presentes; QR/libsignal tem condicao de fonte/pin aprovado, Cloud API ? variante real distinta. Fase final tera materializacao/locks/builds e evidencias de operacao somente apos liberacao.

## Delta relay/CLI - 2026-10-11T11:01:47.767285+00:00

Fonte root: [Codex-composicao-relay.md](Codex-composicao-relay.md). FB-02/47 corrigem ausencia de binding CLI/restorehandler/guest-artifact. FB-24/25/67 registram corpos e consumidores, sem fechar observadores fisicos independentes, profile review/enrollment, worker frame producer ou aceitar slot callable como entrega. FB-01 coordenador conversacional continua aberto; capsula provider nao o implementa. Zero validacao.

## Delta coordenador/Pacto - 2026-10-11T11:20:21.279185+00:00

[Codex-coordinator-contract.md](Codex-coordinator-contract.md) incorporado por corpos/consumidores a FB-01/02/32/33. Tokens/admission/parent requiredcaps/children own model:invoke/permission Operations e A08 runtime proof+central receipt source nao sao mais ausencias. Resta before-provider checkpoint imediato, MCP agent-scoped, Selo/learning resolver protegido, artefatos/guest e todos provedores/observadores/workers/aceites reais. Fontes conectadas nao homologam nenhuma clausula.
