# SENTRA — Reavaliação técnica dos 37 projetos clonados

Data: 2026-10-09. Projeto: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.

## Resultado da reavaliação

**O alinhamento anterior está correto como direção arquitetural, mas não esgota o reaproveitamento e não fecha todas as lacunas do SENTRA.** Há recursos adicionais úteis em quase todas as famílias: memória de experiências, compactação de contexto, recuperação de streams, descoberta seletiva de ferramentas, terminais remotos persistentes, gravação de sessões, verificadores de resultados e colaboração com histórico.

O principal trabalho restante é conectar essas peças ao produto existente. Um contrato implementado, uma simulação local e um serviço externo funcionando são níveis diferentes de entrega. Copiar mais componentes sem fechar essas conexões aumenta o número de módulos, mas não necessariamente a capacidade do SENTRA.

Para o uso individual informado pelo usuário, a prioridade proposta é: agentes interoperáveis reais, execução Windows/browser confiável, documentos e conectores úteis, diagnóstico e recuperação. Infraestrutura de vários servidores ou usuários entra quando houver uma necessidade concreta. Esta revisão trata exclusivamente de reaproveitamento técnico; licenças não foram reavaliadas.

## Base e alcance

Documentos confrontados:

- [Auditoria integral de 08/10](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md).
- [Estudo de reaproveitamento de 08/10](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md).
- [Matriz de absorção Gate 5](C:/Users/vitor/OneDrive/Desktop/SENTRA/docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md).

A lista de projetos veio do [manifesto local](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/SENTRA_SOURCES_MANIFEST.json). Nesta rodada, os **37 HEADs correspondem aos commits do manifesto e as 37 árvores dos clones estão limpas**. O estudo anterior de reaproveitamento contém etapas históricas de 23 clones; a auditoria integral e o manifesto são a referência para o conjunto atual de 37. `codex-chatgpt-web` está fora desse conjunto.

Foram inspecionados contratos, módulos e trechos de implementação selecionados individualmente em cada clone, além dos pontos correspondentes no SENTRA. Esta é uma reavaliação estática orientada a integração, não uma leitura linha a linha de todos os arquivos dos projetos externos. Nenhum runtime externo foi iniciado nem benchmark externo executado nesta rodada. As propostas e os critérios de entrega abaixo não são resultados de testes já realizados.

Evidência auxiliar da inspeção, com caminhos, linhas e commits:

- [Verificação dos 37 pins](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-pin-verification.json).
- [Trechos por projeto](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-evidence.json).
- [Evidência complementar](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-extra-evidence.json).
- [Leituras focadas de comportamento](C:/Users/vitor/.codex/visualizations/2026/10/09/01a120e0-6942-74a1-8b36-731fc500d980/reuse-focused-evidence.json).

## Ajustes necessários no entendimento do estado atual

1. **Interop ainda não despacha efeitos externos pela ponte central.** [CentralInteropAdapter](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/central.py:69) passa `control.durable` diretamente ao contrato de admissão; essa interface exige métodos diferentes dos oferecidos diretamente pelo serviço. Já existe [CentralDurableIntentAuthority](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_runtime/central_authority.py:23), que adapta a reserva transacional do mesmo banco. Mesmo se essa ligação for corrigida, [o despacho continua bloqueado](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/central.py:152) até existir controle de fencing na fronteira real do provedor. Não basta remover o bloqueio.

2. **A colaboração tem código real de biblioteca, mas a autoridade de referência é local.** [sqlite_host.mjs](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/sqlite_host.mjs:1) se apresenta explicitamente como referência local, sem integração de autenticação. [server.mjs](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/server.mjs:17) exige callbacks de grants, nonce e persistência. Falta vinculá-los ao host autoritativo e ao fluxo real de edição do Canvas.

3. **Os snapshots CRDT não correspondem à família de pacotes usada no SENTRA.** O clone Yjs declara `@y/y` **14.0.0-rc.28**; y-protocols declara `@y/protocols` **1.0.6-rc.1** e importa `@y/y`. Hocuspocus 4.7.0 e o [package.json do SENTRA](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_collab/package.json) dependem de `yjs ^13.6.8` e `y-protocols ^1.0.6`. Tratar os clones como dependências diretamente intercambiáveis é incorreto. Isso evidencia uma divergência de pacote/API; a compatibilidade de dados e wire precisa de teste próprio.

4. **O clone Playwright MCP não contém a implementação completa do executor.** Seu [index.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/index.js:18) exporta `tools.createConnection` de `playwright-core/lib/coreBundle`. O [README de src](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/src/README.md) aponta a implementação para o monorepo Playwright. Portanto, o pin do clone não substitui o pin e a inspeção do pacote efetivamente executado.

5. **HCS, runsc, A2A/SSE, OpenHands e Activepieces possuem mais fronteiras locais do que a matriz de 08/10 registrava.** Isso mostra avanço do código, mas não comprova serviços externos operando. O caso HCS ainda requer um [provider injetado](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_executors/winhcs_boundary.py:64); Activepieces continua com [fixture loopback](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/activepieces_loopback.py:46); o bridge de workflows é [SQLite local](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_interop/workflow_bridge.py:30), não execução Temporal/LangGraph.

6. **O gate Grype interpreta relatórios, não executa a varredura.** [evaluate_grype_json](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_quality/grype_gate.py:40) acrescenta validação útil, mas ainda falta produzir o inventário do artefato e obter o relatório de uma execução real do scanner. O mesmo cuidado vale para OTLP local versus Collector implantado, hash chain versus Tessera e JWT verificado versus login OIDC completo.

## Matriz de decisão técnica

P0 = próximo ciclo de uso real; P1 = próximo ganho funcional ou de qualidade; P2 = condicionado a escala ou necessidade. As frentes são as da matriz anterior, com colaboração indicada quando necessário; não representa atribuição de trabalho a agentes nesta conversa.

| Projeto | Principal ampliação recomendada | Prioridade | Frente |
|---|---|---|---|
| ufo | Memória de experiências, edição reversível de planos e seleção por capacidade | P1 | EXEC-001 + COORDENADOR |
| openhands | Recuperação de eventos por sequência, saúde de backends e relações pai/filho | P1 | CRIT-003 + CRIT-002 |
| openhands-agent-sdk | Compactação de contexto, análise de comandos e recuperação de sessão | P0 | CRIT-002 + COORDENADOR |
| agent-client-protocol | Lifecycle completo de sessão, configuração e semântica correta de updates | P0 | CRIT-002 |
| acp-registry | Distribuição por plataforma, ambiente reservado e diagnóstico de instalação | P1 | CRIT-002 |
| a2a | Artefatos incrementais, continuidade de tarefa e notificações assíncronas | P1 | CRIT-002 |
| mcp-typescript-sdk | Negociação de revisão, subscriptions e interação com input_required | P0 | CRIT-002 |
| daytona | PTY persistente, entradas/logs, previews e políticas de ciclo de vida | P1 | EXEC-001 |
| pywinauto | Esperas limitadas, cache de observação e seletores mais estáveis | P0 | EXEC-001 |
| hcsshim | Recursos, identidade de processo e limpeza de workloads headless | P2 | EXEC-001 |
| gvisor | Perfil de FS/rede e checkpoint experimental de workloads Linux | P2 | EXEC-001 |
| playwright-mcp | Contextos isolados, evidência de browser e política de rede | P0 | EXEC-001 + CRIT-002 |
| guacamole-client | Viewer e reprodução temporal de sessões | P1 | EXEC-001 + CRIT-003 |
| guacamole-server | Gravação seletiva e canais RDP/VNC/SSH separados por capability | P1 | EXEC-001 |
| rustdesk | Provedor alternativo para máquinas sem RDP/VNC acessível | P2 | EXEC-001 |
| langgraph | Subfluxos, memória por namespace e recuperação de etapas | P1/P2 | CRIT-002 |
| temporal | Semântica de retries, recuperação e versionamento de workers | P2 | COORDENADOR |
| nats-server | Transporte com ack, backpressure, replay e retenção limitada | P2 | COORDENADOR |
| toolhive | Descoberta seletiva de ferramentas e autenticação por backend | P1 | CRIT-002 |
| spire | Identidade de workloads, rotação e bundles de confiança | P2 | COORDENADOR |
| keycloak | Lifecycle de login/sessão, revogação e token exchange | P2 | COORDENADOR |
| openfga | Descoberta autorizada de recursos e invalidação de relações | P2 | COORDENADOR |
| opa | Políticas versionadas, distribuição e decisão explicável | P1/P2 | COORDENADOR |
| tessera | Verificação independente de checkpoints e provas | P2 | COORDENADOR |
| immudb | Estado confiável no verificador e exportação verificável | P2 | COORDENADOR |
| opentelemetry-collector | Batching, filas limitadas, retries e correlação transversal | P1 | COORDENADOR |
| langfuse | Datasets de regressão, versões de prompts e avaliações | P1 | COORDENADOR |
| grype | Scan real, estado de correção e validade da base de vulnerabilidades | P1 | COORDENADOR |
| xyflow | Renderização de nós visíveis e acessibilidade de grafo | P1 | CRIT-003 |
| yjs | Undo por origem, cursores relativos e sincronização por diferenças | P1 | CRIT-003 |
| y-protocols | Presença com expiração, clocks e vínculo à conexão | P1 | CRIT-003 |
| hocuspocus | Persistência, reconexão e limites; Redis quando houver vários hosts | P1/P2 | CRIT-003 |
| activepieces | SDK de peças, forms, triggers e dedupe sem importar o produto inteiro | P1 | CRIT-002 |
| rpaframework | Excel, PDF e tabelas como capacidades determinísticas | P0/P1 | EXEC-001 |
| windows-agent-arena | Observação híbrida UIA/visão e harness em VM | P1 | EXEC-001 |
| osworld-v2 | Verificadores compostos e avaliação em checkpoints | P1 | EXEC-001 + COORDENADOR |
| windowsworld | Verificação semântica de artefatos e fluxos entre aplicativos | P1 | EXEC-001 + COORDENADOR |

## Reavaliação individual

### 01. ufo

**Alinhamento anterior:** automação Windows e padrões Galaxy/Constellation continuam úteis. A decomposição em DAG se sobrepõe ao OMA; seu valor adicional deve estar na operação de aplicativos e na qualidade dos planos.

**Ampliar:** transformar execuções bem-sucedidas e malsucedidas em experiências recuperáveis; usar edição com histórico para revisar planos; aproveitar critérios de escolha de dispositivo por capacidade e carga como sugestões para o controlador SENTRA.

**Evidência:** [ExperienceSummarizer](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/ufo/experience/summarizer.py:165) cria documentos com metadados e índice vetorial; [CommandHistory](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/editor/command_history.py:15) mantém undo/redo; [ConstellationManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/ufo/galaxy/constellation/orchestrator/constellation_manager.py:132) oferece estratégias de atribuição.

**Encaixe e limite:** acrescentar experiências à memória existente do SENTRA, com origem, escopo, resultado e validade. O carregamento FAISS do clone usa `allow_dangerous_deserialization=True`; esse trecho não deve ser transplantado como importador de memória externa. Undo de plano não desfaz ações já executadas em aplicativos.

**Entrega verificável:** uma segunda tarefa recupera uma experiência pertinente e mostra sua origem; uma experiência obsoleta não é usada; edição do plano gera revisão sem repetir efeitos anteriores.

### 02. openhands

**Alinhamento anterior:** aproveitar UX de agentes, conversas, arquivos e ações continua adequado. A aplicação inteira exigiria outra pilha de frontend e estados paralelos.

**Ampliar:** recuperação de eventos após reconexão, representação de relações entre conversas e indicação de backends que falham repetidamente. Isso melhora o Canvas e as sessões existentes sem exigir sua substituição.

**Evidência:** [session-seq-cursor.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/utils/session-seq-cursor.ts:1) trata gaps e replay de sequências; [health-store.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/api/backend-registry/health-store.ts:46) conta falhas e desabilita probes; [child-conversation-launch.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands/src/services/child-conversation-launch.ts) mantém metadados de lançamento e relação com conversas.

**Encaixe e limite:** adaptar cursor e deduplicação ao journal do SENTRA; relações pai/filho precisam continuar em Run/WorkItem/Chat no backend. `localStorage` pode guardar preferências de UI, mas não ser o registro durável de lançamentos.

**Entrega verificável:** derrubar a conexão durante eventos fora de ordem; reabrir o Canvas e recuperar todos os eventos persistidos sem duplicar mensagem nem lançar outro agente.

### 03. openhands-agent-sdk

**Alinhamento anterior:** usar provider e eventos tipados é correto, mas o SDK oferece mais do que uma conexão com Agent Server. Os adapters SENTRA atuais ainda não comprovam uma sessão no servidor externo.

**Ampliar:** compactação de contexto que preserva o system prompt e eventos iniciais; analisadores estruturados de comandos; política de confirmação por risco; recuperação da posse de sessão com geração e expiração.

**Evidência:** [LLMSummarizingCondenser](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py:54), [policy_rails.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-sdk/openhands/sdk/security/defense_in_depth/policy_rails.py:68) e [conversation_lease.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/conversation_lease.py:24).

**Encaixe e limite:** adotar esses padrões no gerenciamento de contexto e no provider. Manter transcrição original e referências às operações fora do resumo. A classificação de risco ajuda a decidir o fluxo; não concede capability. O lease do Agent Server é posse interna do processo externo, subordinada à admissão do SENTRA.

**Entrega verificável:** conversa longa resume contexto sem perder instruções ou pendências; servidor reinicia e reanexa à mesma sessão; uma tool call aponta para a Operation correspondente.

### 04. agent-client-protocol

**Alinhamento anterior:** o subconjunto `session/new`, prompt, updates e cancel constitui um primeiro adapter, não a cobertura completa de um cliente de agentes.

**Ampliar:** resume, close, list e delete quando anunciados pelo agente; configuração de sessão/modelo; uso/custos reportados; conteúdo estruturado, terminais e arquivos; interação para coletar dados ou decisões do usuário.

**Evidência:** [agent.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/agent.rs:1228) contém lifecycle de sessão; [tool_call.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/tool_call.rs:18) explicita a diferença entre campo ausente, `null` e valor; [elicitation.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/agent-client-protocol/agent-client-protocol-schema/src/v2/elicitation.rs) contém os tipos de interação.

**Encaixe e limite:** negociar versão e capabilities antes de oferecer controles na UI. Não apagar dados recebidos ao aplicar um update parcial. Recursos experimentais do schema precisam continuar condicionados à revisão e à implementação do agente escolhido.

**Entrega verificável:** conectar um agente ACP externo, retomar sua sessão e configurar um recurso suportado; updates parciais preservam os campos antigos; recurso não anunciado não aparece como disponível.

### 05. acp-registry

**Alinhamento anterior:** o catálogo deve continuar separado de instalação e execução. O descriptor local existente cobre somente parte do problema de entregar um agente utilizável.

**Ampliar:** seleção de distribuição por sistema/arquitetura, diferenças entre binary/npx/uvx, ambiente reservado, diagnóstico de instalação e encerramento da árvore de processos.

**Evidência:** [agent.schema.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/agent.schema.json:68) descreve variantes de distribuição; [registry_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/acp-registry/.github/workflows/registry_utils.py:116) filtra variáveis reservadas e oferece helpers de grupos de subprocessos.

**Encaixe e limite:** evoluir o catálogo para responder “qual distribuição roda aqui e quais dependências faltam?”. O hash do clone não autentica automaticamente cada pacote ou binário baixado. Aproveitar verificação de artefatos e um plano de instalação com versão fixada. Não transformar atualização de catálogo em execução automática.

**Entrega verificável:** escolher a variante Windows correta, rejeitar descriptor incompatível e manter a configuração conhecida quando a nova instalação falhar.

### 06. a2a

**Alinhamento anterior:** converter tasks e artifacts para WorkItem e Artifact é adequado. O código local evoluiu para fixtures de transporte e SSE; continua faltando um par de agentes externos reais.

**Ampliar:** continuidade de tarefas que aguardam entrada, artefatos em chunks, Agent Card autenticado/estendido, capacidades opcionais e push notifications para tarefas demoradas.

**Evidência:** [a2a.proto](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:167) define Task/context; [TaskArtifactUpdateEvent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:308) diferencia append e último chunk; [AgentCapabilities](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/a2a/specification/a2a.proto:412) anuncia streaming, push e extensões.

**Encaixe e limite:** persistir a correspondência entre IDs externos e internos. Chunks precisam formar um artefato completo verificável, com limites e proveniência. O protocolo e o schema não fornecem, sozinhos, um runtime A2A nem a autoridade de execução.

**Entrega verificável:** tarefa externa pausa por entrada e retoma; reconexão recupera o artefato completo sem duplicar chunks; callback de outra identidade não altera a tarefa.

### 07. mcp-typescript-sdk

**Alinhamento anterior:** usar o SDK como cliente de tools/resources/prompts é correto. O `MCPTypescriptCompatClient` SENTRA é uma implementação Python para fixtures; isso não prova compatibilidade com o SDK TypeScript real.

**Ampliar:** negociação de revisão do protocolo, subscriptions de mudança de catálogo, interações `input_required`, validação de respostas e streams com reconexão. São recursos particularmente úteis para ferramentas dinâmicas e solicitações de dados durante uma chamada.

**Evidência:** [client.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/client/src/client/client.ts:237), [protocol.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/packages/core-internal/src/shared/protocol.ts:1012) e [subscriptions.md](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/mcp-typescript-sdk/docs/clients/subscriptions.md:7).

**Encaixe e limite:** o snapshot distingue conexões de 2025 e a revisão 2026-07-28; também documenta depreciação de roots/sampling e Tasks como extensão em determinados caminhos. Implementar por revisão negociada, não por uma lista genérica de métodos. Auto-fulfilment e retry interno do cliente precisam respeitar a identidade da Operation e a admissão de efeitos.

**Entrega verificável:** cliente TS real conversa com servidor SENTRA, anuncia apenas recursos compatíveis e trata uma interação sem executar a mesma ação externa duas vezes.

### 08. daytona

**Alinhamento anterior:** sandbox Linux, Computer Use e snapshots continuam valiosos. O adapter atual e o lifecycle separado são uma base, não prova de provisionamento operacional completo.

**Ampliar:** PTYs persistentes com conexão/resize/kill; sessões de comandos, entrada stdin e logs separados; previews de serviços; rede e políticas de auto-stop/archive/delete; volumes e metadados de ambiente.

**Evidência:** [process.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/process.py:562) oferece lifecycle de PTY; [sandbox.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py:79) modela volumes, intervalos e rede; [PTYManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/daytona/apps/daemon/pkg/toolbox/process/pty/manager.go:18) mantém sessões.

**Encaixe e limite:** tratar o terminal remoto como ProcessSession exibida pelo Canvas existente. Provisionamento, escrita stdin, preview e destruição são capacidades distintas. Snapshot de disco, backup de ambiente e estado de processo precisam ter garantias separadas; restore não autoriza repetir uma Operation incerta.

**Entrega verificável:** terminal persiste após desconexão da UI, logs retomam, rede segue o perfil escolhido e o encerramento remove apenas os recursos daquela execução.

### 09. pywinauto

**Alinhamento anterior:** UIA/Win32 e esperas semânticas são a opção mais direta para aplicativos Windows acessíveis. Os bindings SENTRA existentes ainda precisam de comprovação nos aplicativos alvo.

**Ampliar:** construir um repertório de seletores por aplicativo, esperar estado do controle em vez de tempos fixos, aproveitar cache de propriedades em observações grandes e combinar backend UIA/Win32 quando necessário.

**Evidência:** [timings.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/timings.py:309), [UIAElementInfo](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/uia_element_info.py:104) e [Application.connect](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/pywinauto/pywinauto/windows/application.py:299).

**Encaixe e limite:** cache melhora observação, mas uma ação precisa revalidar elemento e processo. Retry de localizar/observar não equivale a retry de clique ou envio. PID restringe o alvo; não cria isolamento do sistema operacional. Interfaces sem árvore exigem outro método de observação.

**Entrega verificável:** fluxo de aplicativo com carregamento variável funciona com timeout limitado; controle recriado não recebe ação por referência antiga; resultado é confirmado semanticamente.

### 10. hcsshim

**Alinhamento anterior:** manter como backend opcional para workloads Windows headless. Sua existência não fecha a necessidade de um desktop interativo isolado.

**Ampliar:** padrões de JobContainer, limites de recursos, associação de processos, obtenção de token de usuário, lifecycle HCS/uVM, mounts e limpeza de processos descendentes.

**Evidência:** [jobcontainer.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/jobcontainer.go), [logon.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/jobcontainers/logon.go:98) e [create_wcow.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hcsshim/internal/uvm/create_wcow.go:63).

**Encaixe e limite:** o [binding SENTRA](C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_executors/winhcs_boundary.py) tem create/status/terminate condicionados ao provider. Falta um provider real e diagnóstico de suporte do host. Grande parte do código upstream está em pacotes Go `internal`; o caminho prático é um serviço/shim com API estreita, não importar esses arquivos diretamente para Python.

**Entrega verificável:** workload headless inicia no host suportado, respeita limites e termina com seus filhos; uma VM com sessão GUI deve ser uma prova separada.

### 11. gvisor

**Alinhamento anterior:** reforço de sandbox Linux por runsc continua válido. Há agora uma fronteira local SENTRA para runsc, sem equivaler a uma implantação demonstrada.

**Ampliar:** perfis de acesso a filesystem, rede e capabilities; diagnóstico de syscalls/workloads incompatíveis; checkpoint/restore de processos quando aplicável.

**Evidência:** [config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/config/config.go:93), [checkpoint.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/checkpoint.go:64) e [restore.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/gvisor/runsc/cmd/restore.go:69). O próprio clone descreve checkpoint/restore como experimental.

**Encaixe e limite:** perfil de runsc deve ser uma propriedade de execução, registrada com o ambiente e a imagem. Não transforma o Windows host em sandbox Linux nem garante recuperação transparente de sockets e efeitos externos. O arquivo de checkpoint é um artefato de ambiente com compatibilidade própria.

**Entrega verificável:** um workload Linux representativo passa com o perfil escolhido; tentativa fora do mount/rede é recusada; teste de restore declara exatamente quais estados foram recuperados.

### 12. playwright-mcp

**Alinhamento anterior:** browser isolado e operações estruturadas continuam prioridade alta. O browser lab somente leitura do SENTRA não constitui ainda esse executor completo.

**Ampliar:** contextos isolados, configuração explícita de perfil, traces de sessão, evidência de rede/console e capacidades opcionais para PDF/visão/devtools; vincular referências de elementos à observação atual.

**Evidência:** [config.d.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:130) anuncia capabilities e opções de evidência; [network config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/config.d.ts:181) contém allow/block de origins. [index.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/index.js:18) e [package.json](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/playwright-mcp/package.json:39) mostram a dependência efetiva em Playwright.

**Encaixe e limite:** obter e validar o pacote exato que implementa as tools. Configuração de origem é uma camada de controle do browser, não prova de confinamento completo da rede. Trace é evidência de browser e pode conter conteúdo; requer armazenamento e escopo definidos pelo SENTRA.

**Entrega verificável:** navegar, interagir e gerar resultado em um contexto dedicado; coletar diagnóstico quando falha; descartar contexto sem afetar o perfil principal do usuário.

### 13. guacamole-client

**Alinhamento anterior:** viewer web de desktop remoto é adequado, mas o maior ganho adicional é uma interface de revisão do que aconteceu na sessão.

**Ampliar:** gravação reproduzível com play/pause/seek, estados de conexão, renderização de display e suporte a diferentes canais de entrada/saída. Uma timeline de sessão pode ligar imagem observada, ação e resultado ao journal do SENTRA.

**Evidência:** [SessionRecording.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/SessionRecording.js:1128) implementa controles de reprodução e keyframes; [Client.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-client/guacamole-common-js/src/main/webapp/modules/Client.js:366) envia eventos de entrada e recebe streams.

**Encaixe e limite:** separar `session.view` de `session.control`, inclusive na UI. Reprodução de gravação deve ser somente visual; nunca reenviar as ações gravadas à máquina. O cliente precisa de um tunnel/proxy operacional; importar o JS não cria a sessão remota.

**Entrega verificável:** acompanhar uma sessão real e depois revisar um intervalo gravado, sem qualquer entrada ser enviada durante o playback.

### 14. guacamole-server

**Alinhamento anterior:** guacd como tradução RDP/VNC/SSH continua complementar aos executores e ao viewer.

**Ampliar:** gravação com escolha explícita de output/mouse/touch/teclado/clipboard; canais de filesystem, clipboard e áudio separados; lifecycle e metadados de conexão para diagnóstico.

**Evidência:** [recording.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/libguac/recording.c:42) permite selecionar o que registrar; [rdp.c](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/guacamole-server/src/protocols/rdp/rdp.c:84) prepara redirecionamentos e plugins da sessão.

**Encaixe e limite:** projetar cada canal como capability do MachineSession. Uma conexão autorizada para visualizar não deve habilitar implicitamente upload, clipboard ou teclado. O proxy de tunnel precisa integrar o principal do SENTRA e não expor credenciais remotas ao frontend.

**Entrega verificável:** sessão somente visual rejeita entrada e transferência; gravação respeita os canais escolhidos; revogação encerra o tunnel e deixa recibo no journal.

### 15. rustdesk

**Alinhamento anterior:** manter como provedor alternativo de controle remoto. Seu encaixe deve depender de um cenário que Guacamole ou o agente remoto existente não resolvam.

**Ampliar:** considerar caminhos de conexão para máquinas fora da rede local, permissões por sessão/canal, clipboard de arquivos, controle de privacidade e gravação. São possibilidades de provider, não motivos para incorporar o cliente inteiro.

**Evidência:** [connection.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/server/connection.rs) contém login/permissões e canais; [clipboard_file.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/clipboard_file.rs:4) traduz mensagens de clipboard; [record_upload.rs](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rustdesk/src/hbbs_http/record_upload.rs:27) processa gravações.

**Encaixe e limite:** não presumir uma API pública e estável de embedding a partir desses módulos internos. Começar por um contrato de provider e uma prova de controle/revogação. Pareamento SENTRA deve continuar identificando a máquina e sua sessão.

**Entrega verificável:** mesma máquina é endereçada pelos IDs internos, sessão pode ser revogada pelo SENTRA e os canais permitidos são demonstrados. Se não houver esse cenário, adiar.

### 16. langgraph

**Alinhamento anterior:** subfluxo subordinado a WorkItem continua apropriado. Evitar outro scheduler global não exige descartar suas bibliotecas e padrões de estado.

**Ampliar:** checkpoints com parent e pending writes, etapas interrompíveis, recuperação seletiva, timeout por ausência de progresso e memória pesquisável por namespace com TTL.

**Evidência:** [checkpoint/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/checkpoint/base/__init__.py:140), [pregel/_retry.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/langgraph/langgraph/pregel/_retry.py:215) e [store/base](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langgraph/libs/checkpoint/langgraph/store/base/__init__.py:203).

**Encaixe e limite:** memória e checkpoint podem complementar o contexto existente. Cada nó com efeito deve invocar o gateway SENTRA; um retry do grafo não pode repetir escrita externa por conta própria. Time travel/fork de estado computacional não desfaz efeitos no mundo.

**Entrega verificável:** subfluxo interrompe por entrada, retoma de checkpoint e preserva etapas concluídas; consulta de memória fica no namespace autorizado. Biblioteca é P1 quando resolve um subfluxo concreto; runtime adicional é P2.

### 17. temporal

**Alinhamento anterior:** extrair semântica de execução durável antes de instalar o servidor é uma boa decisão para o modo individual.

**Ampliar:** distinguir falha transitória de não repetível, impor expiração e máximo de tentativas, representar atualizações admitidas versus concluídas e estudar evolução de workers de fluxos longos.

**Evidência:** [retry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/retry.go:43) calcula retry a partir do tipo de falha e da política; [update/registry.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/temporal/service/history/workflow/update/registry.go:26) mantém updates admitidos e sua recuperação.

**Encaixe e limite:** o clone é principalmente o servidor Temporal; uma integração de aplicação também exige SDK/worker compatíveis. O SENTRA já tem Runs, leases e recuperação. Usar Temporal somente para subworkloads em que histórico determinístico e timers duráveis justifiquem a operação adicional.

**Entrega verificável:** falha não repetível termina sem retry; atividade com resposta incerta reconcilia antes de tentar outra vez; atualização de worker não altera o resultado de um fluxo em andamento.

### 18. nats-server

**Alinhamento anterior:** JetStream é adequado para transporte entre nós. No uso individual em uma máquina, um broker adicional precisa de uma razão operacional.

**Ampliar:** consumers duráveis com ack explícito, MaxAckPending, backoff e limite de redelivery; replay por posição/tempo; retenção e janela de deduplicação configuradas por classe de evento.

**Evidência:** [ConsumerConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/consumer.go:93) e [StreamConfig](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/nats-server/server/stream.go:56).

**Encaixe e limite:** publicar pela outbox e reconhecer consumo somente depois da persistência necessária no SENTRA. Deduplicação do broker tem janela finita; não substitui idempotência de Operation. Não transportar streams de terminal e comandos de execução com a mesma política de retenção indiscriminadamente.

**Entrega verificável:** consumer cai depois de receber uma mensagem, recupera e não repete o efeito; backlog permanece limitado e observável. Fila de falhas e reconciliação são decisões da aplicação.

### 19. toolhive

**Alinhamento anterior:** ToolHost, isolamento e autenticação são úteis. Há uma oportunidade adicional de reduzir o catálogo de ferramentas enviado ao modelo.

**Ampliar:** descoberta seletiva por descrição/keywords, métricas de economia de tokens, autenticação específica por backend e token exchange com audience/scope. Isso pode evoluir o catálogo MCP do SENTRA com menos consumo de contexto.

**Evidência:** [optimizer.FindTool](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/optimizer/optimizer.go:379), [TokenExchangeStrategy](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/strategies/tokenexchange.go:99) e [OutgoingAuthRegistry](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/vmcp/auth/outgoing_registry.go:30).

**Encaixe e limite:** buscar dentro do conjunto de ferramentas já autorizado ao agente; similaridade não concede acesso. [PolicyGate](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/toolhive/pkg/runner/policy_gate.go:11) controla criação de servidor e usa allow-all por padrão, portanto não comprova autorização por tool call. Parte da auditoria está delegada a `toolhive-core`, outra dependência a fixar.

**Entrega verificável:** agente encontra ferramentas pertinentes sem receber as não autorizadas; chamada e credencial ficam vinculadas à Operation; parar o host não perde o diagnóstico.

### 20. spire

**Alinhamento anterior:** identidade de daemons/dispositivos é coerente. O ganho principal é identidade verificável de workloads, além de um identificador de máquina.

**Ampliar:** atestação de processo por seletores, SVID X.509/JWT de curta duração, renovação por subscriptions e bundles de confiança/federação quando houver mais de um domínio.

**Evidência:** [Workload API handler](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/endpoints/workload/handler.go:54), [workload attestor](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/attestor/workload/workload.go:27) e [X509 cache](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/spire/pkg/agent/manager/cache/x509_lru_cache.go:45).

**Encaixe e limite:** identidade autenticada se converte em Principal; a capability continua sendo uma decisão SENTRA. Validar atestador adequado ao Windows e ao ambiente real escolhido. Uma instalação local simples pode manter pareamento existente até ter múltiplos workers ou relays que justifiquem SPIRE.

**Entrega verificável:** worker renova credencial sem identidade instável; processo de outro escopo não obtém o SVID; certificado vencido não permite uma nova operação.

### 21. keycloak

**Alinhamento anterior:** login OIDC opcional é apropriado para uso com outras pessoas. Para uma única identidade local, não é requisito para evoluir agentes e executores.

**Ampliar:** ciclo de sessão e logout, revogação de tokens, consentimentos e token exchange para uma audience específica. Isso resolve mais do que apenas verificar a assinatura de um JWT.

**Evidência:** [TokenRevocationEndpoint](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenRevocationEndpoint.java:62) e [StandardTokenExchangeProvider](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/keycloak/services/src/main/java/org/keycloak/protocol/oidc/tokenexchange/StandardTokenExchangeProvider.java:232).

**Encaixe e limite:** o verificador JWT local SENTRA não constitui ainda login/logout OIDC completo. Um token com assinatura válida pode continuar tecnicamente válido após uma mudança de sessão, conforme a estratégia escolhida; definir como revogação externa altera novas admissões internas e conexões abertas.

**Entrega verificável:** login cria Principal coerente; logout/revogação impede novas operações e trata sessões existentes; token de outra audience não é aceito como identidade SENTRA.

### 22. openfga

**Alinhamento anterior:** ReBAC como decisão consultada é útil quando surgem relações entre pessoas, projetos, máquinas e documentos. O veto local existente não é implantação OpenFGA.

**Ampliar:** `ListObjects` para montar um catálogo de recursos acessíveis, `ReadChanges` para invalidar projeções/caches, assertions para testar o modelo e consistência diferenciada para operações sensíveis.

**Evidência:** [list_objects.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/list_objects.go:86), [read_changes.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/read_changes.go:19) e [check_command.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/openfga/pkg/server/commands/check_command.go:44).

**Encaixe e limite:** navegar recursos permitidos melhora a UX, mas listagem não substitui autorização da ação. Fixar versão do modelo de relações e registrar a decisão consultada. Não usar contextual tuples fornecidas pelo próprio agente como fonte independente de privilégios.

**Entrega verificável:** alteração de relação remove o recurso da descoberta e bloqueia a próxima ação; cache antigo não permite escrita. Adiar o serviço enquanto a autorização individual existente resolver o cenário.

### 23. opa

**Alinhamento anterior:** PDP contextual opcional é adequado; o módulo local SENTRA já oferece uma fronteira de veto, sem equivaler a um OPA externo integrado.

**Ampliar:** políticas versionadas em bundles, ativação controlada, logs de decisão com revision/decision ID e mascaramento de campos. Regras contextualizadas podem ficar auditáveis e testáveis fora de condicionais espalhadas pelo código.

**Evidência:** [bundle/plugin.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/bundle/plugin.go:444), [EventV1](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/plugins/logs/plugin.go:49) e [sdk/opa.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opa/v1/sdk/opa.go:145).

**Encaixe e limite:** iniciar por políticas de rede, ambiente e classes de ação, subordinadas aos grants. Definir semântica para decisão indefinida, indisponibilidade e mudança de versão durante uma operação. Bundle/versionamento é aproveitável mesmo quando o motor completo permanecer opcional.

**Entrega verificável:** mesma entrada e mesma versão produzem a mesma decisão; troca inválida preserva a última política válida; log explica a regra aplicada sem conteúdo sensível desnecessário.

### 24. tessera

**Alinhamento anterior:** testemunhar heads de auditoria é uma boa opção de transparência. Para uso individual, eu reduziria sua prioridade de implantação frente a agentes, executores e recuperação operacional.

**Ampliar:** cliente verificador independente, provas de inclusão/consistência, checkpoints assinados, quorum explícito de witnesses e conservação de evidência de divergência.

**Evidência:** [witness.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/witness.go:29), [client/client.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/client/client.go:44) e [append_lifecycle.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/tessera/append_lifecycle.go).

**Encaixe e limite:** exportar digests/checkpoints pela outbox do ledger. Hash chain local e witness independente têm garantias diferentes. Quorum configurado como nenhum não entrega testemunho externo. Prova de inclusão demonstra que um registro foi incluído; não demonstra que todo efeito real foi registrado.

**Entrega verificável:** verificador com estado anterior detecta checkpoint incompatível; receipt aponta ao evento correto. A cobertura de efeitos precisa ser demonstrada pela instrumentação SENTRA.

### 25. immudb

**Alinhamento anterior:** storage verificável alternativo continua possível, mas sua adoção integral concorre com bancos e journals já existentes.

**Ampliar:** provas de inclusão e avanço linear, conservação de estado confiável no cliente/verificador e exportação de transações para recuperação/replicação.

**Evidência:** [verification.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/embedded/store/verification.go:28), [StateService](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/client/state/state_service.go:28) e [stream_replication.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/immudb/pkg/server/stream_replication.go:29).

**Encaixe e limite:** aproveitar o modelo de cliente que guarda o último estado confiável, inclusive para o audit local. Se a necessidade for apenas provar a cadeia existente, começar por um verificador/arquivo de checkpoints é mais simples. Replicar registros não prova que a restauração de todos os artefatos do SENTRA funciona.

**Entrega verificável:** cliente com checkpoint antigo detecta histórico incompatível; restauração recupera os registros previstos e compara o head. Escolher uma necessidade distinta antes de implantar immudb junto de Tessera.

### 26. opentelemetry-collector

**Alinhamento anterior:** exportação OTLP redigida continua adequada. O sink local atual é um ponto de integração inicial, não um pipeline operacional completo.

**Ampliar:** batching por tamanho/tempo, limite de cardinalidade, memory limiter, filas limitadas, retries e exportação desacoplada. Isso pode tornar o diagnóstico resistente a indisponibilidade sem bloquear a execução principal.

**Evidência:** [batchprocessor/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/batchprocessor/config.go:16), [queuebatch/config.go](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/exporter/exporterhelper/internal/queuebatch/config.go:18) e [memorylimiter config](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/opentelemetry-collector/processor/memorylimiterprocessor/config.go).

**Encaixe e limite:** correlacionar Run/WorkItem/Operation/Provider/Machine nos spans, sem transformar traces em ledger de autoridade. Fila persistente depende da storage extension configurada; o campo `StorageID` não garante persistência por si. Redação adicional e determinados exporters podem exigir componentes fora do clone core.

**Entrega verificável:** sink fica indisponível, o pipeline respeita limites e depois exporta conforme a retenção definida; diagnóstico mostra perda/fila sem fingir completude de auditoria.

### 27. langfuse

**Alinhamento anterior:** tracing LLM e custos são úteis, mas limitar o projeto a esse papel deixa um dos seus maiores ganhos de fora: aprendizado por avaliação.

**Ampliar:** prompts com versão/labels/config, datasets com entrada e saída esperada, ligação entre dataset run e trace, scores numéricos/categóricos/booleanos/textuais e correções humanas.

**Evidência:** [prompts.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/prompts.ts:5), [dataset-run-items.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/domain/dataset-run-items.ts:5) e [score validation](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/langfuse/packages/shared/src/features/scores/interfaces/ingestion/validation.ts:8).

**Encaixe e limite:** converter tarefas pessoais repetidas em regressões do SENTRA, fixando prompt, modelo, ferramentas, ambiente e critério de resultado. Pode-se adotar primeiro o formato e um runner local; a implantação completa é uma decisão posterior. Scores externos auxiliam comparação, sem substituir o QualityGate nem contabilização autoritativa de orçamento.

**Entrega verificável:** comparar duas versões de prompt/provider no mesmo conjunto de casos, mostrando sucesso objetivo, custo, latência e regressões por tarefa.

### 28. grype

**Alinhamento anterior:** scanner de dependências/artefatos continua útil mesmo para uso pessoal. Corrigir a descrição: o objetivo é identificar pacotes e vulnerabilidades conhecidas; não é análise estática geral de cada linha do código.

**Ampliar:** registrar versões com correção disponível, motivo do match, validade da base e diferenças entre scans para orientar atualização de dependências.

**Evidência:** [Fix](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/vulnerability/fix.go:23), [Matcher](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/grype/match/matcher.go:13) e [DBCheck](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/grype/cmd/grype/cli/commands/db_check.go:59).

**Encaixe e limite:** conectar execução real do binário ao parser SENTRA. A identificação de pacotes envolve Syft e formatos de inventário; essas dependências também precisam de versão e procedência registradas. Varredura do checkout não equivale à varredura do pacote/instalador final.

**Entrega verificável:** scan de um artefato conhecido produz relatório correlacionado ao seu digest; base ausente/obsoleta é diagnosticada; recomendação de atualização distingue vulnerabilidade corrigível de sem correção.

### 29. xyflow

**Alinhamento anterior:** extrair ergonomia/performance sem migrar todo o Canvas continua a melhor escolha. Existem algoritmos e padrões concretos para além do aspecto visual de nodes/edges.

**Ampliar:** renderizar somente nós visíveis, seleção e bounds de grafo, descoberta de vizinhos/arestas e descrição acessível com aria-live. Adaptar os princípios ao renderer e à física de cabos existentes.

**Evidência:** [useVisibleNodeIds.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/hooks/useVisibleNodeIds.ts:8), [graph.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/system/src/utils/graph.ts) e [A11yDescriptions](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/xyflow/packages/react/src/components/A11yDescriptions/index.tsx:26).

**Encaixe e limite:** o SENTRA já tem módulos locais de acessibilidade e cabos; verificar a ligação ao Canvas antes de reimplementá-los. Desmontar nó fora da viewport não deve destruir a ProcessSession nem perder estado de terminal. Desenho, física e sessão precisam ter lifecycles separados.

**Entrega verificável:** medir pan/zoom/seleção com 100 e 500 nós; esconder nó não encerra o processo; navegação por teclado encontra nós e anuncia mudanças relevantes.

### 30. yjs

**Alinhamento anterior:** CRDT limitado à apresentação permanece correto. Há ganhos além de sincronizar coordenadas e notas.

**Ampliar:** undo/redo limitado à origem do usuário, posições relativas em texto colaborativo e sincronização por state vectors/diffs. Isso permite edição concorrente com histórico local e tráfego incremental.

**Evidência:** [UndoManager](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/UndoManager.js:164), [RelativePosition](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/RelativePosition.js:154) e [updates.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/yjs/src/utils/updates.js:178).

**Encaixe e limite:** o clone é `@y/y` 14 RC; a biblioteca atualmente usada pelo sidecar é `yjs` 13. Adotar primeiro o recurso equivalente na família já integrada, ou estudar uma migração explícita. Undo colaborativo não pode reverter grants, iniciar/encerrar Runs ou repetir execução.

**Entrega verificável:** dois clientes editam notas; desfazer a alteração de um não remove o trabalho do outro; reconexão transmite diferenças; snapshots existentes continuam legíveis na versão escolhida.

### 31. y-protocols

**Alinhamento anterior:** sync e awareness devem permanecer separados de autorização. Presença não precisa virar estado durável do controlador.

**Ampliar:** expiração de presença, clocks de atualização, remoção de clientes desconectados e vínculos entre awareness client ID e sessão autenticada.

**Evidência:** [awareness.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/awareness.js:13) usa timeout e clocks; [sync.js](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/y-protocols/src/sync.js:38) define sync step 1/2 e updates.

**Encaixe e limite:** o clone usa `@y/protocols` e importa `@y/y`, diferente dos pacotes atuais do SENTRA. Awareness pode representar cursor/nome/status visual, mas “online” não demonstra que um agente está executando ou possui o lease. O módulo local `awareness_guard.mjs` já cobre parte do vínculo e da filtragem; falta comprovar isso no Canvas conectado.

**Entrega verificável:** presença expira e reaparece corretamente; cliente não publica estado de outro usuário; uma sessão revogada não permanece enviando awareness.

### 32. hocuspocus

**Alinhamento anterior:** sidecar colaborativo com callbacks de host continua adequado e já usa a biblioteca real em laboratório.

**Ampliar:** persistência por extensão Database, limites de conexão, reconexão e, somente quando houver múltiplas instâncias, propagação por Redis com coordenação de documentos.

**Evidência:** [Database.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-database/src/Database.ts:45), [Throttle](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-throttle/src/index.ts:3) e [Redis.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/hocuspocus/packages/extension-redis/src/Redis.ts:78).

**Encaixe e limite:** persistência genérica upstream não substitui o precommit/CAS já construído no SENTRA. Redis locks de documentos não são leases de execução. O passo prioritário é ligar callbacks ao host e edição ao Canvas; adicionar Redis antes disso não fecha o fluxo.

**Entrega verificável:** dois clientes reais editam o Canvas, host recusa update inválido antes de publicar, reinício restaura documento e revogação é aplicada às conexões abertas.

### 33. activepieces

**Alinhamento anterior:** catálogo de conectores SaaS e automações é útil. Importar somente workflows completos de um servidor externo não é a única forma de aproveitamento.

**Ampliar:** reaproveitar o SDK de peças e conectores específicos; propriedades tipadas para gerar formulários; output schemas; hooks de enable/disable, renovação de webhook e dedupe de triggers.

**Evidência:** [action.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/action/action.ts:23), [trigger.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/trigger/trigger.ts:11) e [oauth2-prop.ts](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/activepieces/packages/pieces/framework/src/lib/property/authentication/oauth2-prop.ts:38).

**Encaixe e limite:** escolher conectores usados de fato e hospedá-los por um executor Node subordinado, ou acionar serviço externo quando necessário. Contexto, storage e helpers do framework são dependências dos conectores; copiar só um arquivo de ação pode não bastar. Retry interno da peça precisa se alinhar à idempotência externa e ao SENTRA.

**Entrega verificável:** um trigger real cria apenas um WorkItem para eventos duplicados; uma ação usa credencial vinculada à conexão escolhida; desligar o trigger remove sua assinatura externa.

### 34. rpaframework

**Alinhamento anterior:** bibliotecas pontuais Python são um ganho direto. A análise anterior deu mais destaque à GUI/browser do que às capacidades determinísticas de documentos.

**Ampliar:** leitura/escrita de Excel sem GUI, tabelas com filtros/agrupamento/conversão, extração/manipulação de PDFs e workflows que verificam seus próprios resultados. Priorizar isso antes de macros baseadas em coordenadas.

**Evidência:** [Excel/Files.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Excel/Files.py:194), [Tables.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/main/src/RPA/Tables.py:772) e [PDF document.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/rpaframework/packages/pdf/src/RPA/PDF/keywords/document.py:588).

**Encaixe e limite:** disponibilizar capacidades explícitas de transformação de arquivos, com escrita temporária e promoção do resultado validado. Excel Files distingue fórmula de valor armazenado; não presumir que editar uma fórmula recalcula o workbook. Extração de texto PDF também não garante OCR ou fidelidade visual.

**Entrega verificável:** tarefa transforma planilha/PDF conhecido e compara conteúdo esperado; falha preserva original; necessidade de recalcular ou renderizar aciona o backend apropriado.

### 35. windows-agent-arena

**Alinhamento anterior:** benchmark Windows em VM continua útil, mas o clone também oferece um laboratório de observação para melhorar o executor.

**Ampliar:** comparação entre UIA, visão e observação mista; representação de elementos numerados na imagem; escolha entre janela e tela; harness de VM e captura de trajetória.

**Evidência:** [Navi agent](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/mm_agents/navi/agent.py:74) anuncia origens de observação a11y/visão/mistas; [vm.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windows-agent-arena/src/win-arena-container/client/desktop_env/controllers/vm.py:8) gerencia conexão QMP.

**Encaixe e limite:** usar isso para comparar métodos e definir fallback do WindowsUIAExecutor. O adapter do SENTRA continua recebendo ações tipadas; não expor diretamente o executor de código arbitrário de benchmark ao produto. Modelos de visão/OCR e imagens de VM são dependências adicionais.

**Entrega verificável:** mesmo conjunto pequeno de tarefas é repetido com UIA e modo híbrido; diferenças de sucesso/latência são acompanhadas de evidência, versão do ambiente e reset reproduzível.

### 36. osworld-v2

**Alinhamento anterior:** benchmark multietapas continua adequado. O maior reaproveitamento para o SENTRA pode estar no avaliador, sem importar todos os agentes da suíte.

**Ampliar:** composição de métricas com conjunção/short-circuit, resultado estruturado além do score, avaliação intermediária e backend de avaliador separado do agente executante.

**Evidência:** [generated_task_utils.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/evaluation_examples/task_class/generated_task_utils.py:57), [backend/base.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/desktop_env/evaluators/backends/base.py:66) e [lib_run_single.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/osworld-v2/lib_run_single.py:27).

**Encaixe e limite:** enriquecer AcceptanceSuite com verificadores objetivos e explicação do resultado. Avaliação por LLM pode ajudar quando necessária, mas é probabilística e deve ser marcada como tal. `postconfig` de avaliador pode alterar ambiente; medir em clone/snapshot ou registrar essa mutação separadamente.

**Entrega verificável:** tarefa apresenta score e evidência de cada critério; checkpoints de avaliação não alteram a conclusão por efeito colateral oculto; resultados se mantêm comparáveis entre providers.

### 37. windowsworld

**Alinhamento anterior:** tarefas Windows entre aplicativos e avaliação por etapas continuam valiosas. Também há verificadores diretamente reutilizáveis para artefatos de trabalho.

**Ampliar:** comparar tabelas/CSV e propriedades de documentos, conferir resultado final em arquivo, reset/snapshot do ambiente e explicar quais critérios foram satisfeitos.

**Evidência:** [metrics/table.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/metrics/table.py:239), [desktop_env.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/desktop_env.py:469) e [getters/replay.py](C:/Users/vitor/OneDrive/Desktop/SENTRA/third_party/windowsworld/desktop_env/evaluators/getters/replay.py:4).

**Encaixe e limite:** adaptar os verificadores como funções puras sobre artefatos autorizados. O replay do clone constrói comandos pyautogui a partir de strings e inclui um TODO sobre selecionar a janela correta; não é um mecanismo pronto para repetir ações no host. Checkpoint de avaliação, snapshot de VM e recuperação de execução são conceitos diferentes.

**Entrega verificável:** workflow entre aplicativos termina com documento/planilha verificável, critérios por etapa e evidência final; falha no aplicativo é distinguida de falha no avaliador.

## Lacunas que continuam exigindo engenharia no SENTRA

Os 37 projetos fornecem implementações ou padrões para quase todas essas áreas. Nenhum deles conecta automaticamente suas garantias à identidade, ao journal e às interfaces do SENTRA.

| Lacuna | Fontes úteis | Parte que ainda precisa ser entregue no SENTRA |
|---|---|---|
| Admissão e efeito externo ligados ponta a ponta | ACP, A2A, MCP, ToolHive, SDK OpenHands | Ligar CentralDurableIntentAuthority, provider e verificação na fronteira do efeito; observar/reconciliar a mesma Operation |
| Sessão persistente de agente/terminal | ACP, OpenHands SDK/UI, Daytona | Mapa durável de IDs, cursor, reattach e estados após perda de conexão; não recriar sessão por heurística de terminal |
| Desktop Windows isolado e interativo | pywinauto, UFO, Arena, hcsshim | Provedor de VM/sessão compatível, ciclo de vida, arquivos, observação e execução reais; headless HCS não fecha essa entrega |
| Posse de foco/teclado/clipboard | pywinauto, Guacamole, RustDesk | Serializar o recurso compartilhado e definir handoff humano/agente; validar alvo antes de cada ação |
| Recuperação de efeito incerto | Temporal, LangGraph, Daytona, NATS | Consultar estado externo, usar IDs idempotentes quando disponíveis e representar impossibilidade de saber; snapshot não resolve sozinho |
| Evidência e artefatos recuperáveis | A2A, Guacamole, benchmarks, immudb | Guardar bytes/referências/digests e proveniência; digest sem conteúdo não permite inspeção nem restauração |
| Memória útil sem perder instruções | UFO, OpenHands SDK, LangGraph | Memória por escopo, origem, validade e resultado; compactação com transcrição preservada e avaliação de qualidade |
| Descoberta e compatibilidade de ferramentas | Registry, MCP SDK, ToolHive | Negociar versão/capability, validar schema e instalar distribuição correta; catálogo filtra o conjunto autorizado |
| Credenciais e revogação transversal | Activepieces, Keycloak, SPIRE, ToolHive | Vincular conexão/segredo ao principal e operação, invalidar sessões e definir renovação; identidade não é grant |
| Eventos recuperáveis sem duplicar efeitos | OpenHands UI, NATS, MCP | Cursor/outbox/inbox, dedupe durável, limites de fila e revisão do estado projetado |
| Colaboração no Canvas real | Yjs, y-protocols, Hocuspocus | Compatibilidade de pacotes, callbacks do host, edição real, precommit, reautorização e recuperação |
| Canvas com muitos nós | xyflow | Viewport culling sem destruir terminais, limites da física e medição com carga real |
| Qualidade objetiva de tarefas | Arena, OSWorld V2, WindowsWorld, Langfuse | Dataset pessoal, verificadores por artefato, reset e comparação de providers/prompts; incorporar ao QualityGate |
| Diagnóstico atravessando serviços | OTel, Langfuse, ToolHive | Correlação de IDs, redação, política de filas e separação entre resultado operacional e sucesso de exportação |
| Backup e atualização recuperáveis | Daytona, immudb, Temporal como referências | Backup coordenado de SQLite, artefatos e configuração; migrações e teste de restauração do SENTRA inteiro |
| Entrega e instalação das integrações | Registry, Grype, ToolHive | Dependências transitivas fixadas, diagnóstico, serviços opcionais, instalação/remoção e teste de pacote final |
| Vários usuários/hosts, quando necessário | NATS, SPIRE, Keycloak, OpenFGA, OPA | Modelo transacional e migrações para esse modo; o ControlStore atual aceita SQLite, não entrega backend Postgres |
| Independência da prova de auditoria | Tessera, immudb | Verificador com estado confiável e witnesses independentes; demonstrar a cobertura dos efeitos instrumentados |

### Contratos que vale especificar explicitamente

Esses nomes descrevem propostas de integração, não classes já implementadas:

- **AgentSession / ProcessSession:** ID SENTRA e externo, versão/capabilities, cursor, estado de conexão, proprietário, recovery e vínculo a Run.
- **MachineSession / InputLease:** recurso de desktop/browser, contexto/PID/janela, epoch, posse de entrada e handoff entre humano e agentes.
- **Observation / Evidence / Artifact:** instante e revisão de observação, origem, dados ou referência recuperável, digest, estado completo/incremental e vínculo à Operation.
- **ConnectorConnection:** provider, principal, referências a segredos, scopes, renovação/revogação e idempotência suportada pelo serviço externo.
- **ProviderHealth / Compatibility:** dependências disponíveis, revisões suportadas, estado operacional e razão de indisponibilidade mostrada ao usuário.
- **AcceptanceCase:** ambiente/versionamento, resultado esperado, verificadores, custo/latência, seed quando aplicável e evidência da avaliação.

## Ordem proposta para o uso individual

### Ciclo 1 — Tornar o caminho existente utilizável

1. Ligar a autoridade durável à ponte interop e ao provider, mantendo o bloqueio até a fronteira real de efeitos estar resolvida.
2. Demonstrar um agente ACP externo e um cliente MCP TypeScript real, com versão negociada, streaming e reattach.
3. Demonstrar execução Windows em ambiente controlado e browser em contexto isolado, com resultado verificável.
4. Fechar o armazenamento de evidência e a recuperação de operações incertas desses dois caminhos.

Frentes: COORDENADOR + CRIT-002 + EXEC-001. **Aceite:** uma tarefa real passa pelo Canvas/CLI → WorkItem/Run → Operation → provider → artefato → verificador; reinício não cria outro efeito.

### Ciclo 2 — Aumentar utilidade e reduzir custo de contexto

1. Expor capacidades determinísticas de planilha/PDF/tabelas do RPA Framework.
2. Introduzir compactação de contexto do SDK OpenHands e experiências inspiradas no UFO, avaliadas no histórico de tarefas pessoais.
3. Implantar descoberta seletiva de ferramentas inspirada no ToolHive.
4. Selecionar dois ou três conectores Activepieces que o usuário realmente usa.

Frentes: EXEC-001 + CRIT-002 + COORDENADOR. **Aceite:** tarefas repetidas resolvem trabalho concreto, com menos falhas e custo mensurado; memória mostra a experiência usada.

### Ciclo 3 — Diagnóstico, recuperação e regressão

1. Corpus pessoal com formatos Langfuse e verificadores WindowsWorld/OSWorld.
2. Observação híbrida a partir de Arena/UFO quando UIA for insuficiente.
3. OTel com IDs correlacionados e filas limitadas; Grype executado sobre o pacote real.
4. Se máquina remota fizer parte do uso, Guacamole com viewer e playback; se execução Linux fizer parte do uso, Daytona com PTY e lifecycle real.

Frentes: EXEC-001 + COORDENADOR + CRIT-003. **Aceite:** regressões mostram qual critério quebrou; falhas têm evidência recuperável; restauração do conjunto de dados do SENTRA é demonstrada.

### Ciclo 4 — Colaboração e escala sob demanda

1. Ligar o sidecar ao Canvas e à autoridade real, antes de distribuir instâncias.
2. Resolver a escolha Yjs 13 versus família @y 14 e medir desempenho do Canvas usando padrões xyflow.
3. Adicionar NATS/SPIRE/Keycloak/OpenFGA/OPA somente para cenários que exijam essas capacidades.
4. Considerar Temporal, Redis multinó, Tessera, immudb, HCS e gVisor a partir de requisitos concretos e provas próprias.

Frentes: CRIT-003 + COORDENADOR, com CRIT-002/EXEC-001 conforme o provider. **Aceite:** cada serviço novo fecha uma lacuna definida e tem instalação, health, recovery e remoção demonstrados.

## Decisão final

Manter o alinhamento de preservar Canvas, ConPTY, OMA e a autoridade SENTRA. Ampliar o estudo anterior com os módulos concretos apresentados aqui. Para o cenário individual, elevar documentos/RPA, contexto e avaliação objetiva; condicionar infraestrutura distribuída e serviços de identidade à demanda.

A próxima entrega de maior valor é **um fluxo completo real e recuperável**, seguido de capacidades pessoais úteis. O catálogo de 37 projetos é suficiente para fornecer muitas das peças; a integração dessas peças, o isolamento Windows interativo, a recuperação de efeitos e a verificação do resultado continuam sendo trabalho próprio do SENTRA.
