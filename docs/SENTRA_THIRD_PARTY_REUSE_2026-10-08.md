# SENTRA: análise comparativa de fontes terceirizadas

Data: 8 outubro 2026 (Sao Paulo). Auditados por inspeção estática os diretórios de third_party; projetos externos NÃO foram executados, compilados, nem integrados.

## 1. Integridade e limites

- Fontes independentes e rasas (shallow clones), registradas com SHA completo em third_party/SENTRA_SOURCES_MANIFEST.json.
- O Git principal já ignora third_party, portanto versões e licenças precisam ser registradas em manifest e processadas pelo release apenas se explicitamente aprovadas.
- Licença abaixo refere-se somente a indicação do LICENSE de raiz. Não valida módulos, fontes, assets nem dependências transitivas.
- Revisões clonadas não demonstram segurança, compatibilidade nem funcionamento. Nenhum clone recebeu instalação de dependências, tokens ou execução.

## 2. Inventário por repositório

| Projeto | Clone | Commit | Licença aparente da raiz | Evidência de código |
| --- | --- | --- | --- | --- |
| daytona | ok | fc98a5032c04 | AGPL (root) | apps/runner, apps/daemon, apps/snapshot-manager |
| openhands | ok | 76398bb5c5b9 | MIT (root) | docs/architecture.md, src/api, src/stores |
| agent-client-protocol | ok | 8c4b8faff610 | Apache-2.0 (root) | schema/v2, docs/protocol, agent-client-protocol-schema |
| a2a | ok | 12e9d2fbb9ba | Apache-2.0 (root) | specification/a2a.proto, docs/specification.md, specification/json |
| mcp-typescript-sdk | ok | b022522089a0 | Apache-2.0 (root) | packages, README.md |
| langgraph | ok | bfcfea554ed5 | MIT (root) | libs/langgraph, libs/checkpoint, README.md |
| temporal | ok | bae8771853cf | MIT (root) | service, common, client |
| xyflow | ok | 3d35b5731757 | MIT (root) | packages/react, packages/system, examples |
| yjs | ok | d01eefc997cf | MIT (root) | src, tests, README.md |
| playwright-mcp | ok | b8b4183e099f | Apache-2.0 (root) | src, tests, README.md |
| guacamole-client | ok | 38e8cb8ff5cd | Apache-2.0 (root) | guacamole, extensions |
| guacamole-server | ok | ae12b8e51aa6 | Apache-2.0 (root) | src, src/protocols, README |
| openfga | ok | 526995eb2024 | Apache-2.0 (root) | pkg, cmd, README.md |
| opa | ok | 4dcda5da919a | Apache-2.0 (root) | rego, topdown, server |
| gvisor | ok | 25e4d4778b06 | Apache-2.0 (root) | runsc, pkg/sentry, README.md |
| opentelemetry-collector | ok | cee245c32ca5 | Apache-2.0 (root) | receiver, processor, exporter |
| langfuse | ok | c106bb3d9453 | MIT (root) | web, packages, worker |
| activepieces | ok | a9b86f6ed9e5 | MIT (root) | packages/pieces, packages/server, packages |
| rustdesk | ok | 1d4abd0258bb | needs review | src, libs, flutter |
| immudb | ok | bfdce03649f5 | BSL (root) | pkg, embedded, cmd |

## 3. Reaproveitamento técnico - projeto por projeto

### daytona - Compute plane / sandboxes
Optional external sandbox provider. Analyze snapshots, computer use, daemon and lifecycle first; AGPL obligations.
Locais de código verificados: third_party/daytona/apps/runner, third_party/daytona/apps/daemon, third_party/daytona/apps/snapshot-manager, third_party/daytona/libs/computer-use, third_party/daytona/libs/sdk-python, third_party/daytona/apps/otel-collector, third_party/daytona/apps/daytona-e2e

### openhands - Agent Canvas + backend selection
Reuse backend registry, conversation and observability UI patterns without replacing the SENTRA Canvas.
Locais de código verificados: third_party/openhands/docs/architecture.md, third_party/openhands/src/api, third_party/openhands/src/stores, third_party/openhands/src/hooks, third_party/openhands/docs/ACP_AGENTS.md

### agent-client-protocol - Agent-editor sessions
Implement ACP adapter for session creation, progression, permission, cancel and resume.
Locais de código verificados: third_party/agent-client-protocol/schema/v2, third_party/agent-client-protocol/docs/protocol, third_party/agent-client-protocol/agent-client-protocol-schema

### a2a - Inter-agent interoperability
Expose and consume bounded tasks across agent servers while retaining SENTRA authority.
Locais de código verificados: third_party/a2a/specification/a2a.proto, third_party/a2a/docs/specification.md, third_party/a2a/specification/json

### mcp-typescript-sdk - Tooling and resources
Generate typed clients for SENTRA MCP capabilities; assess interoperability.
Locais de código verificados: third_party/mcp-typescript-sdk/packages, third_party/mcp-typescript-sdk/README.md

### langgraph - Agent state graphs
Compare checkpoint and human-in-loop patterns; avoid swapping SENTRA durable core.
Locais de código verificados: third_party/langgraph/libs/langgraph, third_party/langgraph/libs/checkpoint, third_party/langgraph/README.md

### temporal - Durable workflow engine
Borrow cancellation/recovery and worker lifecycle patterns; avoid a second task authority.
Locais de código verificados: third_party/temporal/service, third_party/temporal/common, third_party/temporal/client, third_party/temporal/README.md

### xyflow - Node editor
Compare accessibility, edge performance, graph APIs; migration only if objectively better.
Locais de código verificados: third_party/xyflow/packages/react, third_party/xyflow/packages/system, third_party/xyflow/examples, third_party/xyflow/packages

### yjs - Collaborative CRDT
Sync layout and annotations only; execution and policy state remains server authoritative.
Locais de código verificados: third_party/yjs/src, third_party/yjs/tests, third_party/yjs/README.md

### playwright-mcp - Browser automation
Optional audited browser toolset with separate browser session and permissions.
Locais de código verificados: third_party/playwright-mcp/src, third_party/playwright-mcp/tests, third_party/playwright-mcp/README.md

### guacamole-client - Browser remote desktop
Study browser RDP/VNC/SSH session UX.
Locais de código verificados: third_party/guacamole-client/guacamole, third_party/guacamole-client/extensions

### guacamole-server - Remote desktop gateway
Consider guacd as separately deployed desktop proxy, not as agent authority.
Locais de código verificados: third_party/guacamole-server/src, third_party/guacamole-server/src/protocols, third_party/guacamole-server/README

### openfga - Relationship permissions
Assess optional ReBAC implementation behind SENTRA authorization interface.
Locais de código verificados: third_party/openfga/pkg, third_party/openfga/cmd, third_party/openfga/README.md

### opa - Policy engine
Assess external decision engine for conditional policy without split-brain.
Locais de código verificados: third_party/opa/rego, third_party/opa/topdown, third_party/opa/server, third_party/opa/README.md

### gvisor - Linux sandbox isolation
Compare Linux isolation for remote executor, not for Windows host ConPTY.
Locais de código verificados: third_party/gvisor/runsc, third_party/gvisor/pkg/sentry, third_party/gvisor/README.md

### opentelemetry-collector - Distributed telemetry
Export correlated traces/metrics with redaction and bounded retention.
Locais de código verificados: third_party/opentelemetry-collector/receiver, third_party/opentelemetry-collector/processor, third_party/opentelemetry-collector/exporter, third_party/opentelemetry-collector/service

### langfuse - LLM observability
Optional LLM spans, cost and experiments; control retention and prompt privacy.
Locais de código verificados: third_party/langfuse/web, third_party/langfuse/packages, third_party/langfuse/worker, third_party/langfuse/README.md

### activepieces - Enterprise integrations
Enterprise connector catalog, webhooks and triggers via out-of-process plugin.
Locais de código verificados: third_party/activepieces/packages/pieces, third_party/activepieces/packages/server, third_party/activepieces/packages

### rustdesk - Remote desktop alternative
Separate remote screen transport option; AGPL and packaging require legal review.
Locais de código verificados: third_party/rustdesk/src, third_party/rustdesk/libs, third_party/rustdesk/flutter, third_party/rustdesk/README.md

### immudb - Verifiable event storage
Compare immutable-verifiable log strategy; commercial use requires BSL review.
Locais de código verificados: third_party/immudb/pkg, third_party/immudb/embedded, third_party/immudb/cmd, third_party/immudb/README.md

## 4. Capacidades já presentes no SENTRA (evitar reconstrução)

- Canvas próprio: sentra_canvas/static/native.js, native.css, rope-physics.js e fractal-grid.js; nós, links, PTY e estado persistente em sentra_canvas/graph.py.
- SENTRA CLI -> Canvas: sentra_cli/canvas.py e sentra_canvas/service.py; handoffs endereçados e recibos; ainda não equivale a um cliente ACP completo.
- Durable Run/WorkItem: sentra_mcp/services/durable.py, governance.py, control_store.py, sentra_canvas/task_runtime.py; já há identidade, leases, budgets e workflow.
- Integração MCP e plugins: sentra_mcp/server.py, sentra_mcp/services/plugin_host.py; não criar gateway concorrente de autorização.
- Acesso remoto: sentra_remote/gateway.py e agent.py; complementar com MachineSession e desktop remoto, sem duplicar o pairing.
- Auditoria: sentra_mcp/audit.py, sentra_core/telemetry.py; correlação e redaction existentes, porém não comprovam integridade contra adulteração.
- Sandbox: sentra_mcp/services/process_sandbox.py usa Docker para escopos próprios. Já sentra_canvas/terminal.py + owned_process.py executa PTY como usuário Windows: Job Objects não reduzem privilégios do processo.

## 5. Lacunas, prioridade e aceitação

| Ordem | Lacuna | Mudança proposta | Teste necessário |
| --- | --- | --- | --- |
| P0 | Isolamento real de Canvas CLI | Criar ExecutorAdapter com sandbox, denies e credenciais efêmeras por operação | tentativa de fuga de pasta/host/rede, filhos e privilégio |
| P0 | Protocolo interoperável | ACP com sessão/permits/progressos/cancel, A2A na fronteira externa | dois agentes distintos em comunicações reais, reinício e deduplicação |
| P0 | Auditoria verificável | Encadear hashes, checkpoints assinados, verificador externo e retenção política | alterar/remover evento e comprovar detecção sem vazamento de segredos |
| P1 | Sandbox externa Daytona | Criar DaytonaAdapter sem colar código AGPL no core | provisionar -> executar -> snapshot -> recuperar -> destruir, cleanup garantido |
| P1 | Máquina e aplicações como recursos | Machine, Capability, Session, Executor e inventário unificado | selecionar máquina permitida, negar ações fora de escopo, revogar a quente |
| P1 | Multi-tenant hospedado | Storage adapter Postgres com transações/locks nativos + identidade federada | concorrência/isolamento de 2 locatários, quedas e lock/fencing |
| P1 | Canvas colaborativo | SSE/WebSocket para execução; Yjs só para layout/notas | editar em dois clientes, offline/reconexão, concorrência e permissão |
| P2 | Integração empresarial | Adaptador Activepieces com catálogo e webhooks assinados | consentimento por ação, idempotência e ataques via webhook |
| P2 | Telemetria ponta a ponta | OpenTelemetry e endpoint de observabilidade opcional | rastros por Run/Operation/Device com redaction e hard-stop |
| P2 | Guias de sandbox desktop | Guacamole/RustDesk para acesso consentido e observável | sessão RDP/VNC/SSH autorizada, cancelamento e auditoria |

## 6. Daytona: análise de arquitetura e licença

- Revisão fixada: daytonaio/daytona v0.188.0, commit fc98a5032c04e13de737b8d4d45dd2c7e5d1291a. O repositório upstream parou de receber manutenção em junho de 2026.
- Control Plane: apps/api (NestJS); Compute Plane: apps/runner; agent interno: apps/daemon. Separação de autoridade semelhante à que SENTRA precisa para execução em máquinas externas.
- Persistência/recuperação: apps/snapshot-manager + libs/sdk-python e libs/sdk-typescript. Explorar como contrato de snapshot de sandbox; não confundir com reattachment de terminais Windows que caíram.
- Computer Use: libs/computer-use/README.md descreve Xvfb, XFCE, acessibilidade AT-SPI, x11vnc/noVNC e processo supervisionado para Linux.
- Rede e inspeção: apps/proxy, apps/ssh-gateway, apps/otel-collector e apps/daytona-e2e. Boas referências para gateway, isolamento e E2E.
- Integração recomendada: adapter SENTRA -> Daytona API isolada, com SENTRA governando principal/policy/Run/Operation/budgets/logs. Começar com SDK como cliente; evitar importar o daemon e UI ao núcleo.
- Risco jurídico importante: LICENSE raiz é GNU AGPL-3.0. Estudar alcance do copyleft na modificação e disponibilização pela rede; componentes independentes podem ter outra licença.
- Risco operacional: demanda imagens, compute nodes, rede, manutenção de forks, correções de CVEs e políticas de egress. Não tratar como biblioteca plug-and-play.

## 7. Contrato único proposto

Principal + Capability + Scope + Conditions -> PolicyDecision -> WorkItem/Operation -> ExecutorAdapter -> Evidence + Audit.

- AgentSession separa agentes lógicos da sessão de um modelo ou terminal; fornece ACP, MCP e A2A como transportes/adaptadores.
- Machine/ExecutionWorkspace descrevem um ambiente local, remoto, Docker ou Daytona, mas nenhum adaptador controla ACL nem autorização por conta própria.
- O Control Plane SENTRA decide alocação, permissões, custos, approvals e efeitos colaterais. Não permitir que a UI ou callbacks de IA se tornem autoridade.
- Estado compartilhado de Canvas via CRDT é somente apresentação. Nunca usar CRDT para leads/locks, cobrança ou permissões.
- Em multiusuário, substituir compartilhamento de SQLite por backend transacional com migrações, locking e reconciliação aprovados.

## 8. Roadmap de integração (não implementado nesta etapa)

1. Publicar contratos de Machine/Executor/Capability; endurecer autorização e threat model.
2. Criar adapter ACP e A2A, E2E com duas identidades reais e prova de negativa de autorização.
3. Provar DaytonaAdapter em ambiente isolado, sem alterar SENTRA core: create/exec/snapshot/restore/delete e tolerância a falhas.
4. Incluir auditoria verificável e OTEL transversal, mantendo dados sensíveis redigidos.
5. Construir plataforma multiusuário Web (Postgres, streaming, CRDT para layout, MFA/SSO).
6. Adicionar catálogo de plugins e conectores enterprise com consentimento por tarefa.
7. Auditoria de licenças, supply chain, CVEs, releases e testes adversariais antes da primeira implantação comercial.

## 9. Critérios de evidência

- Este relatório é de inspeção estática. Nenhum build de projeto externo nem prova de sandbox remota executada.
- Atualizar fontes só com revisão explícita, novo manifesto SHA, aprovação de licença, SBOM, testes e controle de regressão.
- Não automatizar a promoção de nenhum projeto externo a dependência do instalador do SENTRA.

Artefatos: third_party/SENTRA_SOURCES_MANIFEST.json, third_party/SENTRA_STATIC_ANALYSIS.json e este relatório.

## 10. Inspeção de código adicional: componentes reutilizáveis concretos

A análise abaixo verifica arquivos e contratos específicos (não apenas README). Propostas são novas integrações, não capacidades declaradas como já concluídas no SENTRA.

### 10.1 Daytona como provedor de execução (prioridade mais alta)

**Código verificado:** third_party/daytona/libs/sdk-python/src/daytona/_sync/sandbox.py; third_party/daytona/libs/computer-use/pkg/computeruse/accessibility.go; mouse_validation.go; third_party/daytona/apps/runner; apps/snapshot-manager; apps/daytona-e2e.

O objeto Sandbox do SDK Python já agrega FileSystem, Git, Process, ComputerUse, CodeInterpreter, rótulos, volumes, snapshots e metadados do usuário/organização. Uma integração através de uma API adaptadora evitaria recriar sete famílias de operações remotas diferentes. A interface padronizada SENTRA deve projetar cada chamada como Operation idempotente com Run, WorkItem, approval, terminal status e Audit próprios.

**Computer Use:** o código accessibility.go utiliza D-Bus/AT-SPI para navegar elementos reais da interface com escopo focused/PID/all, atributos, ações, bounds e estados. É melhor como fonte estrutural de observação de aplicação Linux do que depender exclusivamente de screenshots e cliques por coordenada. Outros módulos oferecem mouse, keyboard, screenshot, processos e validação de argumentos. Não confundir isso com acessibilidade Windows (UI Automation), que precisaria de outro executor.

**Snapshots e recuperação:** reutilizar snapshot de ambiente apenas onde o provedor garante persistência e atomicidade; snapshots não ressuscitam processos locais Windows, nem substituem o registro de operações UNCERTAIN do SENTRA. Testar consistência de FS, idempotência, privilégios, redaction de segredos, rede restrita e descarte.

**Licenciamento fino:** a raiz Daytona é AGPL-3.0, assim como accessibility.go e mouse_validation.go (marcados SPDX AGPL-3.0). Contudo o arquivo libs/sdk-python/src/daytona/_sync/sandbox.py declara SPDX Apache-2.0. Verificar o pacote inteiro, transitivos e termos do servidor antes de copiar ou redistribuir código. Um cliente independente de API pode ser uma melhor fronteira do que incorporar o runtime AGPL.

### 10.2 OpenHands frontend + Agent Server (alto reaproveitamento de padrões)

**Código verificado:** third_party/openhands/docs/architecture.md; docs/ACP_AGENTS.md; third_party/openhands-agent-sdk/openhands-agent-server/openhands/agent_server/README.md.

No OpenHands a interface Canvas NÃO executa ações do agente. Ela trabalha por API com Agent Server, que gerencia subprocesso ACP via JSON-RPC stdio, converte eventos e expõe REST/WebSocket. O servidor suporta conversas/eventos, WebSocket e webhooks. É uma separação replicável no SENTRA: UI visual / Control Plane / ProviderAdapter / Executor, com cada domínio possuindo contrato explícito. O SDK/Agent Server foi clonado em terceiro repositório, além do frontend, para facilitar um protótipo real.

**Melhoria concreta:** quando um agente sai da UI, o SENTRA continua preservando Run/Agent/WorkItem; o backend mantém Process Session separada. Preferir streaming de eventos e eventos tipados às heurísticas de ler saída do terminal e identificar comandos de um modelo.

### 10.3 Yjs + @y/protocols e registro ACP

**Código verificado:** third_party/y-protocols/readme.md, que define sync, awareness e auth error. third_party/agent-client-protocol/schema/v2 e third_party/acp-registry, clonados para contratos de wire e catálogo.

Yjs pode sincronizar coordenadas, tamanho, agrupamentos, notas e cursores de colaboradores no SENTRA Web Canvas. O protocolo awareness trata estados efêmeros de usuário e cursores; não é uma base de permissões. Todo update CRDT deve passar por validação de workspace/tenant no servidor. Os estados WorkItem, Run, custos, política e leases continuam exclusivamente no servidor transacional.

O ACP Registry ajuda a descobrir adaptadores e capacidades de agentes. A lista externa deve passar por allowlist, pin de versão, assinatura/verificação de artefatos e autorização de instalação. Registro não prova confiabilidade do executor.

### 10.4 Controle de máquinas: Daytona + Guacamole

O Guacamole separa cliente HTML5 de proxy guacd; o Daytona descreve ambientes completamente gerenciados. São opções complementares: Daytona é apropriado para **criar e destruir computadores/sandboxes de agente**; Guacamole para **entrar em desktops existentes por protocolos remotos**. Para Windows host continuar com agentes locais limitados e provedores de sessão remota. Não conceder domínio amplo de teclado, rede ou FS sem autorização.

RustDesk utiliza AGPL-3.0 no arquivo LICENCE da revisão clonada. Para adoção comercial inicial, estudar Guacamole (Apache-2.0) como alternativa de menor risco jurídico; revisar suas licenças transitivas e segurança de sessão.

### 10.5 Observabilidade e compliance

A raiz do Langfuse usa MIT, mas exclui explicitamente componentes enterprise em ee/, web/src/ee e worker/src/ee. Activepieces também separa o núcleo MIT dos módulos enterprise em packages/ee e packages/server/api/src/app/ee. Não assumir que a interface inteira pode ser copiada.

immudb utiliza Business Source License com restrições para ofertas comerciais concorrentes, como consta no LICENSE. Usar como referência para algoritmo/trilha verificável, não como dependência obrigatória sem autorização jurídica.

OpenTelemetry Collector é apropriado para transportar traces estruturados, mas o ledger de auditoria verificável deve continuar na autoridade SENTRA. Métricas e tracing nunca devem habilitar leitura de credenciais, prompts sensíveis ou arquivos do cliente sem consentimento.

## 11. Complementos clonados após identificar dependências arquiteturais

Além dos 20 repositórios inicialmente selecionados, foram clonados:
- **openhands-agent-sdk**: OpenHands/software-agent-sdk — Agent Server, SDK, ferramentas e workspace.
- **y-protocols**: yjs/y-protocols — protocolo wire CRDT, awareness e erros de autorização.
- **acp-registry**: agentclientprotocol/registry — catálogo de agentes e seus metadados.

Os três estão registrados por commit no third_party/SENTRA_SOURCES_MANIFEST.json e não foram incorporados nem executados.

## 12. Decisões concretas para o SENTRA OS

| Decisão | Proposta | Razão |
|---|---|---|
| A1 | Manter Canvas próprio e introduzir sincronização por Yjs opcional | Evita descartar a UI e a física dos cabos existentes. |
| A2 | Criar ACPProviderAdapter e A2AIngress | Padroniza protocolos reais sem usar modelos como controladores de autorização. |
| A3 | Desenvolver DaytonaExecutor como componente externo opcional | Reaproveita sandbox/execução/snapshot sem substituir o core. |
| A4 | Expor Machine/Capability/Session/Operation como recursos endereçáveis | Torna cada ação disponível ao agente com política e auditoria uniformes. |
| A5 | Reforçar sandbox Windows e Linux antes de escalar | PTY em conta Windows de usuário não é isolamento suficiente. |
| A6 | WebSocket/SSE para telemetria em tempo real; CRDT apenas para UI | Evita polling constante e preserva fonte única de verdade. |
| A7 | Postgres transacional para modo hospedado/multiusuário | Escala sem compartilhar SQLite por rede ou perder fencing. |
| A8 | Guacamole como opção de desktop remoto, OTel como pipeline | Boa separação entre infraestrutura e regras do SENTRA. |
| A9 | Revisão jurídica de AGPL/BSL/enterprise antes de reutilização binária | Protege a possibilidade de comercialização do SENTRA. |

**Próximo passo de engenharia:** antes de copiar uma linha de Daytona, especificar o contrato ExecutorAdapter em termos de identidade de máquina, autenticação de sessão, capabilities, limites, operação idempotente, snapshot, cleanup, logs correlacionados e revogação. Em seguida implementar um protótipo externo com teste E2E isolado e aprovar licença e threat model.

## 13. Verificação final de clonagem

- 23 repositórios externos novos, todos com HEAD verificável e correspondência exata ao SHA do manifesto.
- 23/23 árvores de trabalho limpas; relatório gravado em third_party/SENTRA_CLONE_VERIFICATION.json, com 0 falhas.
- O clone Langfuse inicialmente perdeu 12 arquivos por limite de caminhos do Windows. A configuração local core.longpaths=true foi habilitada exclusivamente naquele clone e a restauração desses arquivos foi validada.
- Nenhuma dependência de projetos externos foi instalada nem suas aplicações executadas. Os 23 snapshots permanecem fora do versionamento principal por third_party/ estar excluído em .gitignore.
- O único novo arquivo de documentação no projeto principal é este relatório de auditoria. Os clones permanecem no computador, disponíveis para análise adicional e prototipagem explícita.
