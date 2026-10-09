# SENTRA OS — Auditoria integral do ecossistema de 37 repositórios

Data: 2026-10-09T00:21:56.311995+00:00 (gerado localmente).

Este documento analisa cada clone como fonte potencial de funcionalidades do SENTRA. A inspeção foi estática (arquivos Git, organização de código, documentação, contratos e interfaces), não uma auditoria linha por linha nem uma certificação de segurança. Código externo não foi executado nem integrado nesta etapa.

## I. Evidência da clonagem e metodologia

- Clones: 37 repositórios novos, além do codex-chatgpt-web pré-existente. Todos os 37 snapshots possuem commit congelado no manifesto.
- Inventários: `third_party/SENTRA_SOURCES_MANIFEST.json`, `third_party/SENTRA_COMPREHENSIVE_SOURCE_INDEX.json` e `third_party/SENTRA_CLONE_VERIFICATION.json`.
- O terceiro código fica fora do Git principal por configuração preexistente; não há upload público, execução de clone, migrações no core ou instalação de serviços.
- Destino da proposta: uso pessoal e entre amigos, com o SENTRA como autoridade durável de tarefas, identidade, permissões e evidência.
- Alguns projetos autorizam cópia e modificação, mas obrigações de autoria, redistribuição ou disponibilização do código ainda podem existir em usos compartilhados, inclusive entre amigos. Conferir avisos do módulo efetivamente incorporado; sem impedir estudo, prototipagem e integração por API.

## II. O que o SENTRA já resolve e não deve reconstruir

| Núcleo | Componentes reais | Capacidade existente e limitação |
|---|---|---|
| Grafo e terminais | `sentra_canvas/{graph,service,terminal,task_runtime}.py`, `sentra_canvas/static/native.js` | Canvas com nós, links dirigidos, ConPTY, equipes, handoffs, política básica e projeção de tasks. Falta colaboração distribuída universal. |
| CLIs/agentes | `sentra_cli/canvas.py` e Model Gateway | Handoff interno e seleção de provedores; necessita ACP/A2A/Agent runtime genérico. |
| Orquestração durável | `sentra_mcp/services/{durable,governance,event_ingress}.py` | WorkItem, Runs, Operations, leasing, budgets, recuperação; falta prova multi-node extensa. |
| Autorização | `sentra_mcp/services/authorization.py` e `plugin_host.py` | Grants de capability e plugins; faltam controles unificados por ação de app/Machine. |
| Sandbox | `sentra_mcp/services/process_sandbox.py` | Docker para algumas execuções; ConPTY Windows ainda roda com privilégios do usuário. |
| Controle remoto | `sentra_remote/{agent,gateway,store}.py` | Device pairing/jobs; falta sessão de aplicação/desktop e inventário de máquinas. |
| Auditoria | `sentra_mcp/audit.py` e `sentra_core/telemetry.py` | Eventos correlacionados e redaction, ainda sem provas externas completas contra adulteração. |
| Entrega | `.github/workflows/ci.yml` | Gates e releases em evolução; inclusão de terceiros exigiria testes e revisão de artefatos. |

## III. Comparativo rápido de encaixe

| Projeto | Família | Impacto | Tratamento inicial |
|---|---|---|---|
| ufo | Agentes, protocolos e descoberta | P0 | extrair/adaptar |
| openhands | Agentes, protocolos e descoberta | P1 | extrair UI |
| openhands-agent-sdk | Agentes, protocolos e descoberta | P1 | provider adapter |
| agent-client-protocol | Agentes, protocolos e descoberta | P0 | adapter de protocolo |
| acp-registry | Agentes, protocolos e descoberta | P2 | catalogo |
| a2a | Agentes, protocolos e descoberta | P0 | gateway interagente |
| mcp-typescript-sdk | Agentes, protocolos e descoberta | P1 | cliente de ferramentas |
| daytona | Execução isolada, máquinas e interfaces | P0 | adapter e serviço |
| pywinauto | Execução isolada, máquinas e interfaces | P0 | biblioteca direta |
| hcsshim | Execução isolada, máquinas e interfaces | P1 | container Windows opcional |
| gvisor | Execução isolada, máquinas e interfaces | P1 | sandbox Linux |
| playwright-mcp | Execução isolada, máquinas e interfaces | P1 | executor browser |
| guacamole-client | Execução isolada, máquinas e interfaces | P1 | viewer web |
| guacamole-server | Execução isolada, máquinas e interfaces | P1 | proxy remoto |
| rustdesk | Execução isolada, máquinas e interfaces | P2 | controle remoto alternativo |
| langgraph | Orquestração e distribuição | P2 | subfluxo opcional |
| temporal | Orquestração e distribuição | P2 | referência worker |
| nats-server | Orquestração e distribuição | P1 | barramento |
| toolhive | Política, confiança e autenticação | P0 | integrar host opcional |
| spire | Política, confiança e autenticação | P1 | identidade de dispositivos |
| keycloak | Política, confiança e autenticação | P2 | serviço opcional |
| openfga | Política, confiança e autenticação | P2 | policy backend |
| opa | Política, confiança e autenticação | P2 | motor de política opcional |
| tessera | Auditoria, telemetria e dependências | P0 | log de transparência |
| immudb | Auditoria, telemetria e dependências | P2 | storage alternativo |
| opentelemetry-collector | Auditoria, telemetria e dependências | P1 | telemetria |
| langfuse | Auditoria, telemetria e dependências | P2 | tracing opcional |
| grype | Auditoria, telemetria e dependências | P1 | scanner CI |
| xyflow | Canvas e colaboração | P2 | referência UI |
| yjs | Canvas e colaboração | P1 | biblioteca CRDT |
| y-protocols | Canvas e colaboração | P1 | protocolo de presença |
| hocuspocus | Canvas e colaboração | P1 | serviço colaborativo |
| activepieces | Integrações, automações e RPA | P2 | conector externo |
| rpaframework | Integrações, automações e RPA | P2 | extrair libs |
| windows-agent-arena | Benchmarks e validação de agentes | P1 | benchmark |
| osworld-v2 | Benchmarks e validação de agentes | P2 | benchmark |
| windowsworld | Benchmarks e validação de agentes | P1 | benchmark |

## IV. Análise individual por projeto com arquivos do clone

### Agentes, protocolos e descoberta

#### ufo — P0, extrair/adaptar

**Resolve.** AgentOS Windows UFO2 e coordenador Galaxy/Constellation para agentes que executam ações em aplicativos e máquinas distribuídas.

**Aproveitamento de código.** Adaptar módulos de ações em apps Windows, critérios de descoberta de capacidades, decomposição de objetivos e estratégias de recuperação.

**Encaixe arquitetural.** MachineRuntime seleciona um Windows executor, cada ação vira Operation idempotente e cada resultado vira Evidence; aproveitar Galaxy como inspiração de DAG.

**Sobreposições e limitações.** SENTRA já possui Goals/WorkItems e Remote Agent; não criar um segundo orquestrador soberano, especialmente baseado só em decisão de LLM.

**Aceite obrigatório.** Abrir app de teste, operar elemento UIA, negar ação fora do PID/escopo, reconectar e auditar resultado.

**Evidências concretas.** `third_party/ufo/galaxy/agents/constellation_agent.py`, `third_party/ufo/galaxy/agents/constellation_agent_states.py`, `third_party/ufo/documents/docs/galaxy/constellation_agent/state.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/command.md`, `third_party/ufo/documents/docs/galaxy/constellation_agent/overview.md`; `third_party/ufo/README.md`. Revisão `a795552d976c`; 931 arquivos versionados; principais extensões: .py: 496, .md: 226, .png: 92, .yaml: 33.

#### openhands — P1, extrair UI

**Resolve.** Agent Canvas visual especializado em conversas, execução de agents, terminal, browser, arquivos, seleção de backend e observabilidade.

**Aproveitamento de código.** Comparar componentes de interface, seleção de agentes, estados de conversa, visibilidade de ações e UX de permissões.

**Encaixe arquitetural.** Extrair padrões ou widgets úteis para o Canvas SENTRA sem mudar sua identidade visual nem substituir o grafo de terminais.

**Sobreposições e limitações.** Seu frontend depende de Agent Server; importar a aplicação inteira recriaria estados e telas que já existem.

**Aceite obrigatório.** Duas sessões de agentes em backends diferentes, feedback real, cancelamento e reabertura da UI.

**Evidências concretas.** `third_party/openhands/src/services/canvas-ui.ts`, `third_party/openhands/src/fixtures/canvas-demo-conversation.ts`, `third_party/openhands/src/services/child-conversation-launch.ts`, `third_party/openhands/src/contexts/conversation-websocket-context.tsx`, `third_party/openhands/src/api/backend-registry/last-conversation-store.ts`; `third_party/openhands/README.md`. Revisão `76398bb5c5b9`; 2564 arquivos versionados; principais extensões: .ts: 1094, .tsx: 1059, .svg: 146, .md: 78.

#### openhands-agent-sdk — P1, provider adapter

**Resolve.** Servidor REST/WebSocket, SDK Python, lifecycle de agentes e workspace, stream de eventos e integração ACP.

**Aproveitamento de código.** Extrair contratos tipados de eventos, streams, adaptação de agentes, ferramentas e ciclo de vida de sessões.

**Encaixe arquitetural.** OpenHandsProviderAdapter opcional usando Run/Agent/Chat do SENTRA como identidades duráveis.

**Sobreposições e limitações.** Não delegar credenciais nem decisão de promoção ao Agent Server externo.

**Aceite obrigatório.** Teste com 2 agentes, restart, eventos repetidos, política de workspace e rastreio de tool call.

**Evidências concretas.** `third_party/openhands-agent-sdk/clients/typescript/src/events/websocket-client.ts`, `third_party/openhands-agent-sdk/clients/typescript/src/events/bash-websocket-client.ts`, `third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/conversation/events_list_base.py`, `third_party/openhands-agent-sdk/openhands-workspace/openhands/workspace/agent_sandbox/README.md`, `third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/workspace_router.py`; `third_party/openhands-agent-sdk/README.md`. Revisão `2804c1273b40`; 1855 arquivos versionados; principais extensões: .py: 1401, .ts: 117, .md: 88, .json: 83.

#### agent-client-protocol — P0, adapter de protocolo

**Resolve.** Padrão de sessões, capabilities e comunicação entre clientes e agentes CLI.

**Aproveitamento de código.** Implementar JSON-RPC stdio, session/new, prompt, progress, tool updates, solicitações de consentimento e cancelamento.

**Encaixe arquitetural.** ACPAdapter por agente, plugável no Canvas e no SENTRA CLI; mensagens podem usar contexto tipado interno.

**Sobreposições e limitações.** As diretivas internas do Canvas não substituem o protocolo ACP.

**Aceite obrigatório.** Testes de contrato, dois CLI ACP, recusa de permissão, encerramento incerto e reconexão.

**Evidências concretas.** `third_party/agent-client-protocol/agent-client-protocol-schema/src/v1/tool_call.rs`, `third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs`, `third_party/agent-client-protocol/schema/v1/src/lib.rs`, `third_party/agent-client-protocol/schema/v2/src/lib.rs`, `third_party/agent-client-protocol/schema/v1/CHANGELOG.md`; `third_party/agent-client-protocol/README.md`. Revisão `8c4b8faff610`; 273 arquivos versionados; principais extensões: .mdx: 168, .rs: 33, .md: 11, .json: 11.

#### acp-registry — P2, catalogo

**Resolve.** Catálogo interoperável de agentes compatíveis com ACP.

**Aproveitamento de código.** Ler descritores, versões, capacidades declaradas, compatibilidade e instruções de instalação.

**Encaixe arquitetural.** Catálogo de agentes do Canvas com version pin e importação autorizada.

**Sobreposições e limitações.** Registry não é fonte confiável de executáveis; exigir aprovação/pin/verificação.

**Aceite obrigatório.** Bloquear agente incompatível, link malicioso, downgrade e instalações sem consentimento.

**Evidências concretas.** `third_party/acp-registry/.github/workflows/build_registry.py`, `third_party/acp-registry/.github/workflows/registry_utils.py`, `third_party/acp-registry/.github/workflows/build-registry.yml`; `third_party/acp-registry/README.md`. Revisão `f44424b681c1`; 551 arquivos versionados; principais extensões: .json: 256, .md: 218, .svg: 42, .py: 20.

#### a2a — P0, gateway interagente

**Resolve.** Protocolo de interoperabilidade entre agentes, tasks, Agent Cards, artefatos e atualizações.

**Aproveitamento de código.** Aproveitar schemas e patterns de agent discovery, handoff, task progress e artefatos.

**Encaixe arquitetural.** A2A gateway externo que converte task em WorkItem, preservando owner e source identity.

**Sobreposições e limitações.** A2A é transporte e semântica de troca, não autoridade de custo, lease ou aprovação.

**Aceite obrigatório.** Duas instâncias SENTRA trocam tarefa, duplicata bloqueada, artifact validado e revogação.

**Evidências concretas.** `third_party/a2a/docs/topics/streaming-and-async.md`, `third_party/a2a/docs/tutorials/python/7-streaming-and-multiturn.md`; `third_party/a2a/README.md`. Revisão `12e9d2fbb9ba`; 142 arquivos versionados; principais extensões: .md: 48, .yml: 12, .png: 11, .yaml: 10.

#### mcp-typescript-sdk — P1, cliente de ferramentas

**Resolve.** SDK oficial TypeScript para clients/servers MCP e transports de tools, resources e prompts.

**Aproveitamento de código.** Reaproveitar cliente MCP tipado e contracts, tools schemas, transport safety e testes cruzados.

**Encaixe arquitetural.** Expor API do SENTRA para frontends/plug-ins TypeScript sem criar outra implementação de autorização.

**Sobreposições e limitações.** SENTRA já tem sentra_mcp Python; ambos devem negociar contratos idênticos.

**Aceite obrigatório.** Contract tests Python/TS, permissões, paginação, erros semânticos e versão.

**Evidências concretas.** `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/clients.ts`, `third_party/mcp-typescript-sdk/packages/server-legacy/src/auth/middleware/clientAuth.ts`, `third_party/mcp-typescript-sdk/docs/servers/resources.md`, `third_party/mcp-typescript-sdk/docs/clients/server-requests.md`, `third_party/mcp-typescript-sdk/packages/server/src/server/perRequestTransport.ts`; `third_party/mcp-typescript-sdk/README.md`. Revisão `b022522089a0`; 1143 arquivos versionados; principais extensões: .ts: 667, .json: 279, .md: 124, .mjs: 20.

### Execução isolada, máquinas e interfaces

#### daytona — P0, adapter e serviço

**Resolve.** Compute/control plane de sandboxes, runners, daemon, snapshots, tools, files, processos, SSH e computer-use.

**Aproveitamento de código.** Adaptar SDK Python, processo de sandbox, snapshots, endpoints de ComputerUse e acessibilidade AT-SPI para Linux.

**Encaixe arquitetural.** DaytonaExecutor opcional gerenciado por WorkItem/Run/Operation SENTRA; sandbox é um recurso de máquina e não uma autoridade de projeto.

**Sobreposições e limitações.** Operar a infraestrutura inteira é mais custoso que instalar uma lib; ambiente Linux não restaura ConPTY Windows.

**Aceite obrigatório.** Criar sandbox, limitar FS e rede, executar, snapshot/recover, encerrar/revogar e confirmar cleanup.

**Evidências concretas.** `third_party/daytona/apps/daemon/pkg/toolbox/process/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/execute.go`, `third_party/daytona/apps/runner/pkg/docker/snapshot_sandbox.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/types.go`, `third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go`; `third_party/daytona/README.md`. Revisão `fc98a5032c04`; 5702 arquivos versionados; principais extensões: .ts: 1367, .go: 818, .py: 803, .java: 733.

#### pywinauto — P0, biblioteca direta

**Resolve.** Automação de aplicativos Windows por elementos UI Automation e Win32.

**Aproveitamento de código.** Usar wrappers de controles, investigação de janelas/elementos, estado e esperas semânticas.

**Encaixe arquitetural.** WindowsUIAExecutor com PID, janela, selector, capability e approval; preferir UIA a cliques cegos.

**Sobreposições e limitações.** Pode não funcionar em apps com UI customizada, privilégios elevados ou sem árvore de acessibilidade.

**Aceite obrigatório.** Executar fluxo em Notepad/Calculator de teste, negar janela errada, tratar timeout e foco.

**Evidências concretas.** `third_party/pywinauto/pywinauto/controls/uiawrapper.py`, `third_party/pywinauto/pywinauto/controls/uia_controls.py`, `third_party/pywinauto/pywinauto/controls/win32_controls.py`, `third_party/pywinauto/pywinauto/windows/uia_element_info.py`, `third_party/pywinauto/pywinauto/windows/win32_element_info.py`; `third_party/pywinauto/README.md`. Revisão `18d2a95cebed`; 293 arquivos versionados; principais extensões: .py: 123, .exe: 77, .txt: 67, .yml: 5.

#### hcsshim — P1, container Windows opcional

**Resolve.** Interface com Windows Host Compute Service e containers Windows, integração com HCS/OCI.

**Aproveitamento de código.** Estudar lifecycle de instâncias Windows e execução confinada de processos/containers, com integração opcional ao sistema.

**Encaixe arquitetural.** WindowsContainerExecutor para workloads headless, sob o mesmo ExecutorAdapter e policy engine.

**Sobreposições e limitações.** Windows containers não são desktop interativo genérico; exigem versão/recursos específicos do host.

**Aceite obrigatório.** Provisionar e destruir container isolado, testar filesystem, privilégios e filhos.

**Evidências concretas.** `third_party/hcsshim/cmd/runhcs/container.go`, `third_party/hcsshim/internal/runhcs/container.go`, `third_party/hcsshim/internal/jobcontainers/doc.go`, `third_party/hcsshim/internal/jobcontainers/env.go`, `third_party/hcsshim/internal/jobcontainers/oci.go`; `third_party/hcsshim/README.md`. Revisão `ab8249e8a111`; 5443 arquivos versionados; principais extensões: .go: 4486, (sem extensão): 270, .md: 199, .json: 167.

#### gvisor — P1, sandbox Linux

**Resolve.** User-space kernel para aumentar isolamento de contêineres Linux não confiáveis.

**Aproveitamento de código.** Reaproveitar runsc como runtime de sandboxes de código e ferramenta em executores Linux.

**Encaixe arquitetural.** SandboxProfile gVisor no Daytona/Docker quando compatível; recurso opcional.

**Sobreposições e limitações.** Não resolve privilégios de um terminal ConPTY host Windows; compatibilidade de syscalls precisa teste.

**Aceite obrigatório.** Testes adversariais de filesystem, networking, syscall e impacto no desempenho.

**Evidências concretas.** `third_party/gvisor/pkg/sentry/platform/context.go`, `third_party/gvisor/pkg/sentry/platform/kvm/kvm.go`, `third_party/gvisor/pkg/sentry/platform/platform.go`, `third_party/gvisor/pkg/sentry/platform/kvm/config.go`, `third_party/gvisor/pkg/sentry/platform/cpuid_amd64.go`; `third_party/gvisor/README.md`. Revisão `25e4d4778b06`; 4413 arquivos versionados; principais extensões: .go: 2526, (sem extensão): 658, .cc: 370, .md: 137.

#### playwright-mcp — P1, executor browser

**Resolve.** Serviço MCP de operação de navegador, snapshots de acessibilidade e ações contextuais.

**Aproveitamento de código.** Adaptar ferramentas de browser de alto nível e mapeamento de ações DOM/ARIA.

**Encaixe arquitetural.** BrowserExecutor separado e consentido para tarefas web, dentro de scope SENTRA.

**Sobreposições e limitações.** Não pode tomar controle do Edge principal protegido nem herdar cookies sem autorização.

**Aceite obrigatório.** Teste isolamento entre sessões, navegação restrita, tentativas de exfiltração e timeout.

**Evidências concretas.** Nenhum arquivo candidato indexado; `third_party/playwright-mcp/README.md`. Revisão `b8b4183e099f`; 39 arquivos versionados; principais extensões: .ts: 10, .md: 6, .yml: 5, (sem extensão): 5.

#### guacamole-client — P1, viewer web

**Resolve.** Frontend HTML5 para desktops remotos RDP/VNC/SSH.

**Aproveitamento de código.** Reaproveitar interface de stream remoto, teclado, mouse, clipboard restrito e sessão visual.

**Encaixe arquitetural.** Nó Machine no Canvas abre view Guacamole limitada pelo grant da máquina.

**Sobreposições e limitações.** Somente renderiza e transmite interação; não é controlador de privilégio nem tool semântico.

**Aceite obrigatório.** Abrir e fechar sessão remota, revogar ao vivo e registrar evidências de operação.

**Evidências concretas.** `third_party/guacamole-client/guacamole/src/main/frontend/src/app/client/types/ManagedDisplay.js`, `third_party/guacamole-client/extensions/guacamole-display-statistics/src/main/resources/directives/guacClientStatistics.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Display.js`, `third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Keyboard.js`. Revisão `38e8cb8ff5cd`; 2033 arquivos versionados; principais extensões: .java: 853, .js: 293, .json: 153, (sem extensão): 149.

#### guacamole-server — P1, proxy remoto

**Resolve.** Gateway guacd e suporte de protocolos de desktop remoto.

**Aproveitamento de código.** Executar proxy RDP/VNC/SSH, gerenciamento de conexões e separação de frontend/servidor.

**Encaixe arquitetural.** RemoteDesktopTransport para Máquina existente com credenciais efêmeras SENTRA.

**Sobreposições e limitações.** Não expor RDP/VNC público; proxy precisa isolamento e atualizações.

**Aceite obrigatório.** Testar duas conexões, queda de rede, revogação e recursos de clipboard transfer.

**Evidências concretas.** `third_party/guacamole-server/src/protocols/rdp/doc/svc-example/README.md`. Revisão `ae12b8e51aa6`; 602 arquivos versionados; principais extensões: .c: 282, .h: 234, .keymap: 25, (sem extensão): 21.

#### rustdesk — P2, controle remoto alternativo

**Resolve.** Sistema de desktop remoto multiplataforma, rede e relay para suportar máquinas existentes.

**Aproveitamento de código.** Estudar comunicação P2P/relay e, opcionalmente, incorporar cliente/serviço separado.

**Encaixe arquitetural.** Alternativa a Guacamole para máquinas de amigos, gerenciada por aprovações SENTRA.

**Sobreposições e limitações.** Remote desktop visual não equivale a automação semântica; superfície de rede e consentimento elevados.

**Aceite obrigatório.** Parear duas máquinas, negar comando sem consentimento, medir reconexão e revogação.

**Evidências concretas.** `third_party/rustdesk/src/client.rs`, `third_party/rustdesk/src/server.rs`, `third_party/rustdesk/src/server/dbus.rs`, `third_party/rustdesk/src/client/helper.rs`, `third_party/rustdesk/src/custom_server.rs`; `third_party/rustdesk/README.md`. Revisão `1d4abd0258bb`; 1000 arquivos versionados; principais extensões: .rs: 289, .dart: 140, .md: 81, .png: 61.

### Orquestração e distribuição

#### langgraph — P2, subfluxo opcional

**Resolve.** Grafos de estado para agentes com checkpoints e interrupções.

**Aproveitamento de código.** Reaproveitar subflows LLM com state persistence, interrupt/resume e human-in-loop.

**Encaixe arquitetural.** LangGraphTaskAdapter opcional operando dentro de WorkItem e relatando progressos.

**Sobreposições e limitações.** Não substituir Durable Run, lease, Quality Gate nem política de promoção.

**Aceite obrigatório.** Crash entre etapas, checkpoint reaberto e side effects sem repetição.

**Evidências concretas.** `third_party/langgraph/libs/checkpoint/langgraph/store/base/batch.py`, `third_party/langgraph/libs/checkpoint/langgraph/store/base/embed.py`, `third_party/langgraph/libs/prebuilt/langgraph/prebuilt/interrupt.py`, `third_party/langgraph/libs/langgraph/langgraph/pregel/_checkpoint.py`, `third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/id.py`; `third_party/langgraph/README.md`. Revisão `bfcfea554ed5`; 684 arquivos versionados; principais extensões: .py: 465, .ipynb: 35, .json: 30, .yml: 28.

#### temporal — P2, referência worker

**Resolve.** Engine durável distribuída para workflows, activities, histories, timers e retries.

**Aproveitamento de código.** Utilizar padrões de worker queues, liveness, reconciliation e retries como referência/adapter futuro.

**Encaixe arquitetural.** TemporalWorkerAdapter opcional se benchmarks provarem ganho sobre scheduler atual.

**Sobreposições e limitações.** Segundo workflow authority aumenta complexidade e split-brain se não houver limites claros.

**Aceite obrigatório.** Failover de dois workers, evento incerto, recuperação, idempotência e compensação.

**Evidências concretas.** `third_party/temporal/service/history/workflow/activity.go`, `third_party/temporal/service/history/workflow/matcher/activity_matcher.go`, `third_party/temporal/service/history/workflow/matcher/activity_evaluator.go`, `third_party/temporal/service/history/workflow/retry.go`, `third_party/temporal/service/history/tasks/activity_retry_timer.go`; `third_party/temporal/README.md`. Revisão `bae8771853cf`; 3971 arquivos versionados; principais extensões: .go: 3006, .gz: 370, .json: 118, .sql: 111.

#### nats-server — P1, barramento

**Resolve.** Broker pubsub e JetStream para filas e consumo persistente distribuído.

**Aproveitamento de código.** Reaproveitar streams, consumers, ack, redelivery, retenção e observabilidade de eventos.

**Encaixe arquitetural.** Barramento entre SENTRA Gateway, remote agents e executor; envelope idempotente SENTRA permanece autoridade.

**Sobreposições e limitações.** Ack de mensagem não é prova de efeito concluído, e consumers podem reenviar.

**Aceite obrigatório.** Teste queda de rede, message duplicate, ordem, backpressure e revogação.

**Evidências concretas.** `third_party/nats-server/server/jetstream.go`, `third_party/nats-server/server/jetstream_api.go`, `third_party/nats-server/server/jetstream_errors.go`, `third_party/nats-server/server/jetstream_events.go`, `third_party/nats-server/server/jetstream_cluster.go`; `third_party/nats-server/README.md`. Revisão `6af2d22525d5`; 598 arquivos versionados; principais extensões: .go: 258, .pem: 144, .conf: 107, .key: 15.

### Política, confiança e autenticação

#### toolhive — P0, integrar host opcional

**Resolve.** Registro, proxy e isolamento de servidores MCP com policy gates, auth e telemetria.

**Aproveitamento de código.** Incorporar ToolHost/runner MCP, catálogo de servidores, interceptação de tools e isolamento por instância.

**Encaixe arquitetural.** ToolHiveExecutor opcional executa ferramentas após autorização no SENTRA Policy Gate.

**Sobreposições e limitações.** Não permitir tool registry independente expondo ferramentas além de grants.

**Aceite obrigatório.** Testes tool injection, registro indevido, policy deny, sandbox FS/rede, shutdown e rastreabilidade.

**Evidências concretas.** `third_party/toolhive/pkg/runner/policy_gate.go`, `third_party/toolhive/pkg/telemetry/registry.go`, `third_party/toolhive/pkg/registry/policy_gate.go`, `third_party/toolhive/pkg/runner/telemetry_config.go`, `third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go`; `third_party/toolhive/README.md`. Revisão `33ba170aad63`; 2877 arquivos versionados; principais extensões: .go: 2229, .yaml: 287, .md: 250, .yml: 38.

#### spire — P1, identidade de dispositivos

**Resolve.** Identidade de workloads SPIFFE com SVID, attestation, mTLS e rotação.

**Aproveitamento de código.** Reaproveitar identidade criptográfica por máquina, agent/daemon e serviços conectados.

**Encaixe arquitetural.** DeviceIdentityProvider mapeia SPIFFE ID à identidade de principal SEN​TRA e autorização.

**Sobreposições e limitações.** É infraestrutura de confiança para multidevice; desnecessário impor ao uso local simples.

**Aceite obrigatório.** Rotação, clone de agente, certificado vencido, revogação e falha de attest.

**Evidências concretas.** `third_party/spire/cmd/spire-server/cli/federation/list.go`, `third_party/spire/cmd/spire-server/cli/federation/show.go`, `third_party/spire/cmd/spire-server/cli/federation/common.go`, `third_party/spire/cmd/spire-server/cli/federation/create.go`, `third_party/spire/cmd/spire-server/cli/federation/delete.go`; `third_party/spire/README.md`. Revisão `9dbd864e8923`; 2210 arquivos versionados; principais extensões: .go: 1230, (sem extensão): 371, .conf: 144, .md: 136.

#### keycloak — P2, serviço opcional

**Resolve.** Identity server com OIDC, SAML, SSO, MFA, realms e federação.

**Aproveitamento de código.** Reaproveitar login de humanos, acesso de amigos e integração OIDC/MFA.

**Encaixe arquitetural.** OIDCIdentityProvider autenticando humanos; autorizações granulares continuam no SENTRA.

**Sobreposições e limitações.** Serviço Java pesado para uso casual; opcional/hosted e não obrigatório no desktop.

**Aceite obrigatório.** Convidar amigo, multiworkspace, logout/revoke, MFA e troca de identidade.

**Evidências concretas.** `third_party/keycloak/js/apps/admin-ui/src/identity-providers/add/OIDCAuthentication.tsx`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/IdentityStore.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/LDAPIdentityStoreRegistry.java`, `third_party/keycloak/federation/ldap/src/main/java/org/keycloak/storage/ldap/idm/store/ldap/LDAPIdentityStore.java`, `third_party/keycloak/server-spi-private/src/main/java/org/keycloak/broker/provider/UserAuthenticationIdentityProvider.java`; `third_party/keycloak/README.md`. Revisão `c7de391ae4d8`; 13514 arquivos versionados; principais extensões: .java: 8580, .png: 686, .adoc: 680, .tsx: 630.

#### openfga — P2, policy backend

**Resolve.** ReBAC de relacionamentos, tuplas e avaliação de permissões.

**Aproveitamento de código.** Modelar relações user/team/agent/workspace/machine e compartilhamento de recursos.

**Encaixe arquitetural.** ReBACPolicyBackend consultado pela autoridade única AuthorizationService.

**Sobreposições e limitações.** Evitar duas bases de grants com estados diferentes e cache incorreto.

**Aceite obrigatório.** Acesso transitivo, revogação, concorrência, negação fora de workspace.

**Evidências concretas.** `third_party/openfga/pkg/server/authorization_models.go`, `third_party/openfga/pkg/storage/storagewrappers/cached_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/bounded_datastore.go`, `third_party/openfga/pkg/storage/storagewrappers/sharediterator/shared_iterator_datastore.go`; `third_party/openfga/README.md`. Revisão `526995eb2024`; 578 arquivos versionados; principais extensões: .go: 476, .md: 22, .yaml: 19, .sql: 16.

#### opa — P2, motor de política opcional

**Resolve.** Policy Decision Point com Rego, bundles e condições de contexto.

**Aproveitamento de código.** Reaproveitar regras versionadas para risco de operação, contexto de app, rede e escopo.

**Encaixe arquitetural.** PDP externo consultado pelo SENTRA para regras complexas, com fail-closed.

**Sobreposições e limitações.** OPA não cria identidade e não deve administrar grants em paralelo.

**Aceite obrigatório.** Rego test, negative policy, timeout, atualização e rollback de bundle.

**Evidências concretas.** `third_party/opa/docs/blog/2025-05-14-introducing-swift-opa-native-policy-evaluation-for-swift-d5136c8a662e.md`, `third_party/opa/bundle/bundle.go`, `third_party/opa/v1/ast/policy.go`, `third_party/opa/v1/bundle/file.go`, `third_party/opa/v1/bundle/hash.go`; `third_party/opa/README.md`. Revisão `4dcda5da919a`; 7910 arquivos versionados; principais extensões: .yaml: 2398, .stmt: 1914, .go: 1030, .json: 703.

### Auditoria, telemetria e dependências

#### tessera — P0, log de transparência

**Resolve.** Infrastructure de transparency log append-only e checkpoints/witness verificáveis.

**Aproveitamento de código.** Reaproveitar logs Merkle, provas de inclusão, checkpoints assinados e mecanismos de witness.

**Encaixe arquitetural.** AuditWitness externaliza hashes canônicos dos eventos SENTRA; guardar provas por Operation.

**Sobreposições e limitações.** Registro verificável não garante que todas as ações foram registradas ou que não houve side effects fora da plataforma.

**Aceite obrigatório.** Alterar/apagar evento e verificar prova offline; retenção e falha segura.

**Evidências concretas.** `third_party/tessera/witness.go`, `third_party/tessera/append_lifecycle.go`, `third_party/tessera/internal/witness/otel.go`, `third_party/tessera/internal/witness/client.go`, `third_party/tessera/cmd/mtc/log/internal/checkpoint/reader.go`; `third_party/tessera/README.md`. Revisão `0489e17418aa`; 295 arquivos versionados; principais extensões: .go: 152, (sem extensão): 43, .md: 34, .tf: 18.

#### immudb — P2, storage alternativo

**Resolve.** Banco verificável com provas criptográficas de registros e consistência.

**Aproveitamento de código.** Usar como backend opcional para event ledgers e checagem de integridade.

**Encaixe arquitetural.** AuditStorageAdapter opcional para trilha externa, com somente hashes/metadados sensíveis redigidos.

**Sobreposições e limitações.** Mais complexo que log merkle leve; verificar implicações de licença BSL se compartilhado.

**Aceite obrigatório.** Prova de escrita/leitura, prova inválida, interrupção e restauração.

**Evidências concretas.** `third_party/immudb/pkg/server/remote_storage.go`, `third_party/immudb/embedded/store/verification.go`, `third_party/immudb/embedded/ahtree/verification.go`, `third_party/immudb/pkg/verification/verification.go`, `third_party/immudb/embedded/appendable/remoteapp/remote_storage_reader.go`; `third_party/immudb/README.md`. Revisão `bfdce03649f5`; 1203 arquivos versionados; principais extensões: .go: 970, (sem extensão): 38, .md: 26, .sh: 18.

#### opentelemetry-collector — P1, telemetria

**Resolve.** Pipelines de traces, logs e métricas com receivers, processors e exporters.

**Aproveitamento de código.** Exportar sinais de brokers, machine runtimes, agentes e gateways; padronizar OTLP.

**Encaixe arquitetural.** TelemetryExporter SENTRA -> Collector com run_id/operation_id/device_id.

**Sobreposições e limitações.** Tracing operacional não é trilha auditável criptográfica; proteger conteúdos dos usuários.

**Aceite obrigatório.** Rastreio distribuído completo, redaction, quotas de logs e perda de collector.

**Evidências concretas.** `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_exporter.go`, `third_party/opentelemetry-collector/processor/memorylimiterprocessor/internal/mock_receiver.go`, `third_party/opentelemetry-collector/receiver/doc.go`, `third_party/opentelemetry-collector/exporter/README.md`, `third_party/opentelemetry-collector/pipeline/signal.go`; `third_party/opentelemetry-collector/README.md`. Revisão `cee245c32ca5`; 2860 arquivos versionados; principais extensões: .go: 1802, .yaml: 419, .md: 131, (sem extensão): 119.

#### langfuse — P2, tracing opcional

**Resolve.** Tracing e avaliação de aplicações LLM, scores, custo e experimentos.

**Aproveitamento de código.** Dashboards por tarefa/modelo, spans de inferência e comparação de agentes.

**Encaixe arquitetural.** LLMTraceSink opcional correlacionando WorkItem ao provider turn.

**Sobreposições e limitações.** Custo efetivo, quota e hard stop pertencem ao SENTRA, não ao dashboard.

**Aceite obrigatório.** Observar falhas/custo sem registrar prompt secreto nem duplicar orçamento.

**Evidências concretas.** `third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts`, `third_party/langfuse/web/src/features/traces/fns/nodeScores.ts`, `third_party/langfuse/web/src/features/scores/lib/prepareTraceAnnotation.ts`, `third_party/langfuse/web/src/features/traces/hooks/useParsedObservation.ts`, `third_party/langfuse/web/src/features/traces/hooks/usePrefetchObservation.ts`; `third_party/langfuse/README.md`. Revisão `c106bb3d9453`; 6811 arquivos versionados; principais extensões: .ts: 3641, .tsx: 1849, .sql: 552, .md: 305.

#### grype — P1, scanner CI

**Resolve.** Varredura de CVEs em código, dependências, containers e SBOMs.

**Aproveitamento de código.** Integrar scan em CI e avaliação de snapshots de terceiros instaláveis.

**Encaixe arquitetural.** Release Gate analisa SBOM/artefato antes de instalar ferramenta externa.

**Sobreposições e limitações.** Não substitui threat modeling, análise de código nem execução isolada.

**Aceite obrigatório.** Scan executável/imagen Docker de teste, CVE threshold, relatório e exceções.

**Evidências concretas.** `third_party/grype/grype/vulnerability_matcher.go`, `third_party/grype/cmd/grype/cli/ui/handle_update_vulnerability_database.go`, `third_party/grype/grype/match/matcher.go`, `third_party/grype/grype/matcher/matchers.go`, `third_party/grype/grype/vulnerability/fix.go`; `third_party/grype/README.md`. Revisão `5dbdab183e88`; 1624 arquivos versionados; principais extensões: .go: 753, .json: 574, (sem extensão): 106, .yaml: 53.

### Canvas e colaboração

#### xyflow — P2, referência UI

**Resolve.** Engine React Flow de nodes, edges, handles, zoom e ergonomia de grafos.

**Aproveitamento de código.** Extrair padrões de seleção, acessibilidade e performance para canvases grandes.

**Encaixe arquitetural.** Benchmark de interação UI versus renderer próprio; integrar apenas se melhorar e preservar física.

**Sobreposições e limitações.** Uma migração React inteira duplicaria interface e arriscaria estética e ConPTY/xterm.

**Aceite obrigatório.** 100 nós, 200 cabos, FPS, resize, zoom e keyboard a11y.

**Evidências concretas.** `third_party/xyflow/packages/svelte/src/lib/hooks/useNodesEdgesViewport.svelte.ts`, `third_party/xyflow/packages/react/src/hooks/useViewport.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportSync.ts`, `third_party/xyflow/packages/react/src/hooks/useViewportHelper.ts`, `third_party/xyflow/packages/react/src/container/Viewport/index.tsx`; `third_party/xyflow/README.md`. Revisão `3d35b5731757`; 697 arquivos versionados; principais extensões: .ts: 253, .tsx: 198, .svelte: 128, .css: 27.

#### yjs — P1, biblioteca CRDT

**Resolve.** CRDT para sincronizar alterações concorrentes entre clientes.

**Aproveitamento de código.** Replicar layout, notas, tamanho/posição de nós e cursores offline/online.

**Encaixe arquitetural.** CanvasSharedDocument recebe atualizações por workspace autorizado.

**Sobreposições e limitações.** CRDT não guarda grants, locks, WorkItems nem quotas.

**Aceite obrigatório.** Dois clientes, desconexão, merge, revogação e limites de payload.

**Evidências concretas.** `third_party/yjs/src/utils/updates.js`, `third_party/yjs/src/utils/encoding.js`, `third_party/yjs/src/utils/Transaction.js`, `third_party/yjs/src/utils/UpdateDecoder.js`, `third_party/yjs/src/utils/UpdateEncoder.js`; `third_party/yjs/README.md`. Revisão `d01eefc997cf`; 75 arquivos versionados; principais extensões: .js: 51, .md: 9, .json: 6, .yml: 4.

#### y-protocols — P1, protocolo de presença

**Resolve.** Protocolos Yjs de sync, awareness e mensagem de autorização.

**Aproveitamento de código.** Usar presença/cursores, encode de updates e handshake eficiente.

**Encaixe arquitetural.** Módulo de presença de amigos/agentes no Canvas Web com servidor Hocuspocus.

**Sobreposições e limitações.** Awareness é sinalização efêmera e não política de autorização.

**Aceite obrigatório.** Stale clients, heartbeat, reconexão, erro de permissão e dados malformados.

**Evidências concretas.** `third_party/y-protocols/src/awareness.js`; `third_party/y-protocols/README.md`. Revisão `73b2ff75486c`; 13 arquivos versionados; principais extensões: .js: 5, .json: 4, (sem extensão): 2, .md: 2.

#### hocuspocus — P1, serviço colaborativo

**Resolve.** Servidor WebSocket Yjs com auth hooks, colaboração e provider.

**Aproveitamento de código.** Sincronização e persistência em tempo real do layout do Canvas sem reimplementar CRDT protocol.

**Encaixe arquitetural.** CanvasCollaborationService verifica principal/workspace em cada sessão e recebe atualizações Yjs.

**Sobreposições e limitações.** Não expor direto o estado autoritativo SENTRA em documentos CRDT.

**Aceite obrigatório.** E2E com dois amigos, colaboração simultânea, token revogado e offline sync.

**Evidências concretas.** `third_party/hocuspocus/packages/provider/src/HocuspocusProviderWebsocket.ts`, `third_party/hocuspocus/packages/provider/src/OutgoingMessages/AuthenticationMessage.ts`, `third_party/hocuspocus/packages/provider-react/src/HocuspocusProviderWebsocketComponent.tsx`, `third_party/hocuspocus/packages/server/README.md`, `third_party/hocuspocus/packages/provider/README.md`; `third_party/hocuspocus/README.md`. Revisão `ee7c6e123c3a`; 266 arquivos versionados; principais extensões: .ts: 163, .md: 39, .json: 24, .tsx: 15.

### Integrações, automações e RPA

#### activepieces — P2, conector externo

**Resolve.** Motor de automações com peças para SaaS/APIs, trigger/ação, OAuth e webhook.

**Aproveitamento de código.** Adaptar conectores e catálogos de receitas para automações de trabalho pessoal.

**Encaixe arquitetural.** ConnectorExecutor aciona fluxo em serviço externo governado por WorkItem e approvals.

**Sobreposições e limitações.** Não duplicar scheduler/retry e controle de segredos em dois sistemas.

**Aceite obrigatório.** E2E webhook assinado, OAuth por usuário, aprovação para ação irreversível e dedupe.

**Evidências concretas.** `third_party/activepieces/packages/pieces/community/microsoft-copilot/src/lib/triggers/copilot-interaction-webhook.ts`, `third_party/activepieces/packages/pieces/community/knock/src/lib/actions/trigger-workflow.ts`, `third_party/activepieces/packages/pieces/community/feedhive/src/lib/actions/fire-workflow-trigger.ts`, `third_party/activepieces/packages/pieces/community/github/src/lib/actions/trigger-workflow-dispatch.ts`, `third_party/activepieces/packages/pieces/community/savvycal/src/lib/triggers/workflow-action-triggered.ts`; `third_party/activepieces/README.md`. Revisão `a9b86f6ed9e5`; 30020 arquivos versionados; principais extensões: .ts: 17001, .json: 10309, .md: 967, .tsx: 943.

#### rpaframework — P2, extrair libs

**Resolve.** Bibliotecas Python de RPA para GUI, sites, documentos, Excel e automações repetitivas.

**Aproveitamento de código.** Reaproveitar tarefas específicas e bibliotecas Robot Framework/Python para fluxos determinísticos.

**Encaixe arquitetural.** RPAExecutor para sequências aprovadas dentro do sandbox Windows/Linux.

**Sobreposições e limitações.** Seletores frágeis e riscos de credencial; RPA não é arquitetura de agente.

**Aceite obrigatório.** Preencher formulário de teste, Excel/PDF mock, falha de UI, evidência e cancelamento.

**Evidências concretas.** `third_party/rpaframework/packages/main/src/RPA/Desktop/utils.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/common.py`, `third_party/rpaframework/packages/windows/src/RPA/Windows/main.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/Selenium.py`, `third_party/rpaframework/packages/main/src/RPA/Browser/__init__.py`; `third_party/rpaframework/README.rst`. Revisão `7a419fb7a7bd`; 704 arquivos versionados; principais extensões: .py: 250, .rst: 110, .jpg: 65, .robot: 39.

### Benchmarks e validação de agentes

#### windows-agent-arena — P1, benchmark

**Resolve.** Benchmark de execução de tarefas no Windows com aplicativos reais.

**Aproveitamento de código.** Criar suíte de aferição de agente e ambiente reproduzível para Machine Runtime.

**Encaixe arquitetural.** SENTRA BenchRunner executa tarefas em VM e reporta sucesso/latência/custo.

**Sobreposições e limitações.** Passar benchmark não certifica permissão, segurança ou robustez em ambiente não controlado.

**Aceite obrigatório.** Baseline repetível com 3 execuções, avaliações e evidência anexada.

**Evidências concretas.** `third_party/windows-agent-arena/src/win-arena-container/client/evaluation_examples_windows/create_json.py`, `third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/evaluators/getters/windows_clock.py`; `third_party/windows-agent-arena/README.md`. Revisão `6d39ed88c545`; 514 arquivos versionados; principais extensões: .json: 314, .py: 127, .png: 19, .md: 11.

#### osworld-v2 — P2, benchmark

**Resolve.** Benchmark de tarefas de computador multietapas em ambientes padronizados.

**Aproveitamento de código.** Medir eficácia de ações de interface, recuperação e impacto do contexto longo.

**Encaixe arquitetural.** Harness de benchmark externo para comparar WindowsUIA/Playwright/RPA e agent providers.

**Sobreposições e limitações.** Infraestrutura/VM grande; não testar em estação pessoal com dados reais.

**Aceite obrigatório.** Execuções isoladas com métricas e comparações por tarefa.

**Evidências concretas.** `third_party/osworld-v2/benchmark_releases/README.md`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE.md`, `third_party/osworld-v2/mm_agents/anthropic/tools/computer.py`, `third_party/osworld-v2/docs/PUBLIC_EVALUATION_GUIDELINE_v2.1.md`, `third_party/osworld-v2/hybrid_agents/codex/evaluation_transport.py`; `third_party/osworld-v2/README.md`. Revisão `acdd3493808e`; 1256 arquivos versionados; principais extensões: .py: 642, .json: 407, .md: 75, .png: 46.

#### windowsworld — P1, benchmark

**Resolve.** Benchmark Windows multiaplicativo com tarefas empresariais e checkpoints.

**Aproveitamento de código.** Avaliação por etapas e objetivos finais, útil para agentes que trabalham entre aplicativos.

**Encaixe arquitetural.** Adaptador de AcceptanceSuite por WorkItem e operações de interface real.

**Sobreposições e limitações.** Depende de apps e imagens com configuração própria; pontuação não substitui auditoria.

**Aceite obrigatório.** Avaliar etapas intermediárias, falhas, retry seguro e resultados finais.

**Evidências concretas.** `third_party/windowsworld/desktop_env/evaluators/metrics/libreoffice.py`, `third_party/windowsworld/desktop_env/evaluators/README.md`, `third_party/windowsworld/desktop_env/evaluators/__init__.py`, `third_party/windowsworld/desktop_env/evaluators/getters/vlc.py`, `third_party/windowsworld/desktop_env/evaluators/metrics/pdf.py`; `third_party/windowsworld/README.md`. Revisão `fbccd464f94f`; 547 arquivos versionados; principais extensões: .py: 457, .md: 24, .txt: 21, .json: 17.

## V. Arquitetura proposta sem duplicar autoridades

Plataforma de controle principal: SENTRA guarda Principal, WorkItem, Run, Operation, Artifact, PolicyDecision, Budget, Lease, Fencing e Audit.
Camada de transporte: ACP para CLIs; A2A para serviços/agentes; MCP para ferramentas; NATS para eventos. Transporte não substitui commit durável.
Camada de execução: WindowsUIA/UFO, Daytona/gVisor, WindowsContainers/hcsshim, browsers Playwright, workflows RPA/Activepieces, desktop Guacamole/RustDesk.
Camada de confiança: autorização do SENTRA recebe identidades SPIRE/OIDC e decisões opcionais OpenFGA/OPA; ToolHive isola ferramentas; Tessera recebe raízes de auditoria; OpenTelemetry transporta sinais.
Camada visual: Canvas próprio e physics rope; Yjs/Hocuspocus para layout/notas/presença; OpenHands/xyflow fornecem padrões visuais selecionados.

### Contratos recomendados no SENTRA

- Machine: ID, principal proprietário, capacidades tipadas, provider, atestação e estado observado.
- AgentSession: agente lógico, modelo/CLI/provedor, transporte ACP/A2A/MCP, permissions e estado de conversa isolado.
- ToolSession: autoridade de autorização, escopo workspace, limites de FS/network, audit context.
- ExecutorAdapter: discover, authorize, start, observe, cancel, reconcile, snapshot opcional, cleanup e evidence.
- EventEnvelope: source_instance_id, source_epoch, source_seq, operation_id, idempotency_key, content hash e timestamps.
- AuditProof: hash de evento canônico, hash chain ou Merkle, checkpoint assinado, prova de inclusão e verificador independente.

### Lacunas ainda não resolvidas apenas por clones

1. Sandbox Windows interativa com isolamento verdadeiro e acesso GUI — combinar conta restrita/VM, Windows UIA, HCS e aprovação, não usar somente Job Objects.
2. Storage transacional hospedado e multiusuário (Postgres nativo com migrations) ainda precisa ser projetado/implementado.
3. Segurança por ação e gerenciamento de consentimento durável, com revogação imediata e sem dois pontos de decisão.
4. Auditoria realmente verificável — projetos de log não garantem completude se recursos executam fora do gateway.
5. Integração total do Canvas com eventos de máquina, rollback, retries, budgets e approval comum.
6. UI refinada com performance de centenas de nós e sessões, além de fonte de dados e estratégia de multiuser.
7. Engenharia de produção: instalação opcional de serviços, licenciamento de componentes individuais, atualizações e testes end-to-end.

## VI. Ordem de integração priorizada

| Etapa | Objetivo testável | Projetos |
|---|---|---|
| A | Contrato Machine + Executor + PolicyDecision em todo side effect | Núcleo SENTRA / UFO / ACP / A2A |
| B | Computer Use Windows real com autorização e isolamento | pywinauto / UFO / hcsshim |
| C | Sandbox opcional de agentes com snapshot/recovery | Daytona / gVisor |
| D | MCP seguro e descoberta de agentes | ToolHive / OpenHands SDK / ACP registry |
| E | Eventos multinó e identidades rotativas | NATS / SPIRE |
| F | Auditoria forte e tracing | Tessera / OTEL Collector / Langfuse |
| G | Web Canvas compartilhado e presença | Yjs / y-protocols / Hocuspocus |
| H | Controle visual de máquinas remotas | Guacamole; RustDesk opcional |
| I | Apps, SaaS, automações e catálogo de fluxos | Playwright MCP / Activepieces / RPA Framework |
| J | Qualidade: benchmarks + supply chain | WindowsWorld / WindowsAgentArena / OSWorld-V2 / Grype |

## VII. Como aproveitar código diretamente com menos risco de quebrar o projeto

- **Incorporar bibliotecas pontuais primeiro:** pywinauto, Yjs, y-protocols, cliente MCP TS, handlers de ferramentas/browser, algumas libs do RPA Framework.
- **Serviço externo com adapter quando pesado:** Daytona, Guacamole, ToolHive, NATS, SPIRE, Keycloak, Hocuspocus, Activepieces, OpenTelemetry Collector.
- **Adaptar protocolos ou padrões sem copiar o app completo:** ACP/A2A, UFO Galaxy, OpenHands Agent Server, Temporal, LangGraph, OpenFGA/OPA.
- **Não incluir em produto executável:** suites de benchmark, assets de treino, imagens de avaliação, dados privados de teste.
- Para módulos incorporados, armazenar o SHA original, LICENSE/NOTICE, arquivo de origem, alteração local e testes. A ausência de intenção comercial não elimina necessariamente obrigações ao distribuir aos amigos.

## VIII. Critérios de conclusão de engenharia

- Todo adapter novo deve ter sucesso, falha, timeout, concorrência, duplicação, cancelamento, revogação e reconciliação testados.
- Modelos externos só contam como operantes quando houver uma resposta real autenticada, não apenas subprocesso vivo.
- Toda operação irreversível exige aprovação por policy, com prova de identidade, escopo e artefato resultante.
- CRDT só gerencia interface; GitHub code/CI nunca embute credenciais; clones não rodam em nome do usuário sem avaliação.
- Antes de dizer que o produto está pronto: E2E em dois computadores reais e dois amigos, com cabo visual, agentes comunicando, sessão desktop remota e audit proofs verificáveis.

## IX. Arquivos de pesquisa

- `third_party/SENTRA_SOURCES_MANIFEST.json` — SHA e origens de 37 repositórios.
- `third_party/SENTRA_COMPREHENSIVE_SOURCE_INDEX.json` — estrutura e candidatos de código.
- `third_party/SENTRA_CLONE_VERIFICATION.json` — verificação de Git.
- `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md` — este estudo.

## X. Evidências adicionais descobertas na inspeção de código (prioridade para decisões)

1. **UFO / Constellation já implementa DAG real.** Em third_party/ufo/galaxy/agents/constellation_agent.py, a classe ConstellationAgent implementa processamento de pedidos/resultados, invoca TaskConstellationOrchestrator, cria e atualiza DAGs e mantém estados de tarefas. Os objetos do SENTRA Goal/WorkItem podem reutilizar a estratégia de composição, mantendo a validação e a autoridade durável no SENTRA. Isso reduz a necessidade de construir outro motor de planejamento visual desde zero.
2. **ToolHive requer política obrigatória configurada pelo integrador.** third_party/toolhive/pkg/runner/policy_gate.go contém PolicyGate.CheckCreateServer(), mas sua implementação padrão NoopPolicyGate devolve allow. O SENTRA não deve confiar nessa configuração por padrão: registrar uma implementação customizada deny-by-default ainda no startup, exigir verificação por tool call e bloquear iniciação se autorização externa não estiver funcional. PolicyGate de criação não prova que todo método executado pelo MCP ficou protegido.
3. **Tessera já oferece lifecycle com batching e witness.** third_party/tessera/append_lifecycle.go implementa limites e tempos de lote, publicação de checkpoints, witness, mirror e tratamento de filas. Bons padrões para log de provas do SENTRA. Isso NÃO significa que o SENTRA automaticamente capturará todas as operações; a instrumentação precisa morar no ponto de autorização/efeito.
4. **Hocuspocus fornece ganchos suficientes para um Canvas com amigos.** third_party/hocuspocus/packages/server/src/Hocuspocus.ts implementa onConnect, onRequest, beforeSync, beforeHandleMessage, awareness e onStoreDocument, além de quotas para mensagens não autenticadas e estados de documentos. É possível configurar autorização/limite por workspace; políticas de execução continuam no Control Plane.
5. **WindowsWorld já disponibiliza métricas para fluxos de escritório.** third_party/windowsworld/README.md documenta 181 tarefas, 17 aplicações, 77,9% com múltiplos apps e aproximadamente 4,97 checkpoints intermediários por tarefa. Necessita ambiente Windows em VM e utilitários de provisionamento; é um excelente critério mensurável para avaliar o SENTRA Machine Runtime sem tocar em dados pessoais.
6. **Daytona pode fornecer Computer Use estruturado, além de pixels.** third_party/daytona/libs/computer-use/pkg/computeruse/accessibility.go modela escopos focused/PID/all, ações e estados por AT-SPI; third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py expõe process, fs, git e computer_use como subsistemas do Sandbox. Sugestão: adaptar o SDK por API e mapear cada ação a uma operação autorizada SENTRA.
7. **A aplicação Web e os agentes devem continuar desacoplados.** Em third_party/openhands/docs/architecture.md, o Agent Canvas é frontend de estado/apresentação e o OpenHands Agent Server é responsável pelo runtime; third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/README.md descreve REST/WebSocket. Preservar essa fronteira na migração multiusuário do SENTRA.

### Decisões de reaproveitamento imediato

- Código **copiável/encapsulável** com pouco acoplamento: pywinauto para UIA Windows, bibliotecas Yjs/y-protocols, cliente MCP TypeScript, componentes RPA especializados, classes de contratos ACP/A2A.
- **Serviços implantáveis isoladamente:** Daytona, ToolHive, NATS, SPIRE, Hocuspocus, Guacamole, OpenTelemetry Collector.
- **Padrões arquiteturais para adaptar, não substituir:** Constellation do UFO, OpenHands Server, Temporal, LangGraph, OpenFGA e OPA.
- **Evidência/qualidade:** Tessera (trilha), Grype (vulnerabilidades), WindowsWorld e WindowsAgentArena (tarefas Windows), OSWorld-V2 (cross-platform).
- **Nenhum clone foi executado**; essas decisões ainda requerem protótipos isolados com testes positivos, negativos e de recuperação antes da incorporação ao SENTRA.

### Sequência mínima de entregas técnicas para transformar pesquisa em produto

A) Criar schemas de Machine, Capability, AgentSession e ExecutorAdapter (test-first) usando Run/Operation/WorkItem/PolicyDecision existentes.

B) Integrar pywinauto e ações Windows do UFO como adaptadores tipados com UIA sob um usuário/VM restritos; autorização por PID/aplicação/ação e logs de resultado verificáveis.

C) Adicionar DaytonaProvider por SDK externo sem exigir Daytona para quem usa apenas máquinas locais; testar sandbox lifecycle/snapshots e fallback explícito.

D) Envelopar ToolHive como MCP ToolHost deny-by-default e compatibilizar ACP/A2A nas fronteiras de agentes externos.

E) Introduzir NATS + SPIRE para dispositivos remotos e Tessera + OpenTelemetry para transparência/observabilidade, mantendo SQLite local no modo single-user.

F) Ligar Hocuspocus + Yjs à apresentação (somente layout/anotações/presença) e planejar armazenamento hospedado transacional separado do grafo UI.

G) Estabelecer suíte WindowsWorld + WindowsAgentArena + Grype como critérios de aceitação do Machine Runtime, com fixtures/desktops isolados.
