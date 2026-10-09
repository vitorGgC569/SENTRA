# SENTRA OS — Avaliação final de incorporação e cobertura

Data: 8/10/2026. Diretório: C:\Users\vitor\OneDrive\Desktop\SENTRA.
Fonte: inspeção do checkout local do SENTRA, relatórios de 37 clones externos, arquivos de módulos e testes; não equivale a revisão manual de cada linha, auditoria de segurança formal nem E2E de produtos externos.

## 1. Estado comprovado

- third_party/SENTRA_SOURCES_MANIFEST.json registra 37 repositórios de estudo, mais o checkout codex-chatgpt-web anteriormente presente.
- third_party/SENTRA_CLONE_VERIFICATION.json registrou 37/37 clones com commit íntegro e 0 falhas.
- docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md descreve todos os 37 projetos e caminhos de código.
- O SENTRA possui Canvas físico próprio, orquestração, CLI, MCP, Remote Agent, papéis, leases, políticas, logs, Model Gateway e CI; há mudanças de desenvolvimento não consolidadas em múltiplas partes.
- O teste real do Edge confirmou três chats independentes via extensão 1.6.52, com esforço High exibido, mas a extensão não atestou automaticamente família GPT-6 em cada turno. Não confundir a autoapresentação do modelo nas respostas com atestação.
- Este arquivo representa lacunas para incorporação; não afirma que os 37 produtos já foram integrados.

## 2. Matriz de cobertura / lacuna residual

| Domínio operacional | SENTRA hoje (código / prova) | Terceiros adequados | Falta para considerar resolvido | Prioridade / responsável |
| --- | --- | --- | --- | --- |
| Agentes e sessões de modelo | CLI + Model Gateway + turn leases | ACP, OpenHands SDK, A2A | ACP negotiated session/cancel/progress, validação real de modelo+esforço, preservação de chat id e política | P0 / CRIT-002; verificação de modelo no core em fase separada |
| Operação Windows UI | ConPTY, remote job, Windows Job Objects | UFO, pywinauto | UIA semântica por app/janela/PID, escopo, consentimento, proteção de credenciais, confirmação do efeito | P0 / EXEC-001 |
| Sandbox de computador do agente | Docker para algumas operações | Daytona, gVisor, hcsshim | criação, limite, rede, snapshots, recuperação e descarte; executor Windows GUI realmente isolado permanece difícil | P0 / EXEC-001 |
| MCP executado com política | sentra_mcp e plugin host | ToolHive, MCP SDK | catálogo e tools dinâmicas submetidos à MESMA autoridade, deny by default por efeito lateral | P0 / CRIT-002 |
| Interoperabilidade interagente | Context Bus / Canvas Handoff próprio | A2A, ACP, Registry | autenticação de agentes externos, task/artifact mapping, cancelamento, dedupe e revogação | P0 / CRIT-002 |
| Colaboração Web real | Canvas local com server/token e polling | Yjs, y-protocols, Hocuspocus | presença, compartilhamento autorizado, merge offline, stream de saída de terminais e conflitos | P1 / CRIT-003 |
| Máquina remota visual | sentra_remote gateway e agente | Guacamole Client/Server, RustDesk | view autenticada RDP/VNC/SSH com encerramento, clipboard e controle de acesso | P1 / Exec-001 futura fase |
| Comandos distribuídos | leases e event ingress locais, testes de multi-node | NATS JetStream, Temporal (referência) | at-least-once, fencing entre computadores, replay/deduplicação, observação de conclusão de efeito | P1 / coordenação |
| Identidade de máquinas | pairing de dispositivo | SPIRE | máquina/daemon com credenciais efêmeras e atestação, renovação e revogação | P1 / coordenação |
| Autenticação de amigos | autenticação local do Canvas/Relay | Keycloak | convidar usuários, identidade por usuário e workspace; MFA/OIDC se usar acesso externo | P1 / coordenação |
| Permissões e consentimento | AuthorizationService/grants, policy | OPA, OpenFGA, ToolHive | aplicar policy em TODOS os side effects, UI, tools, files, comandos e remote workers; UX de aprovação/auditoria | P0 / coordenação |
| Logs auditáveis | sentra_mcp/audit e sentra_core/telemetry | Tessera, immudb | prova criptográfica, checkpoint, verificabilidade independente; logs devem cobrir efeito real e não só intenção | P0 / coordenação |
| Telemetria e avaliação | telemetry/outbox, usage, project runs | OTel Collector, Langfuse | traces ponta a ponta com ids, redaction, dashboards de erro/latência/custo; sem vazar conversas | P1 / coordenação |
| UI da física do Canvas | Native Canvas, rope, grid, nó/edge | xyflow, OpenHands | benchmark 100 nós/200 cabos, teclado, viewport, acessibilidade, CPU/GPU e regressões visuais | P2 / CRIT-003 futura fase |
| Navegador operado por agente | extension Edge relay e model gateway | Playwright MCP | executar browser isolado por contexto sem tocar cookies privados do Edge principal | P1 / Exec-001 futura fase |
| Conectores de apps e RPA | MCP plugins, routine scheduler | Activepieces, rpaframework | catálogo, secrets por plugin, webhooks assinados, ações irreversíveis com approval e dedupe | P2 / fase seguinte |
| Estados complexos de agente | WorkItem, goal, durable runs | LangGraph, Temporal, UFO Constellation | decidir se subgraphs LLM devem ser executados no run, sem duplicar scheduler e promotion authority | P2 / integração futura |
| Supply chain e benchmark | CI, testes de componentes | Grype, WindowsWorld, WindowsAgentArena, OSWorld V2 | scanner em release, CVE gating, E2E em VM descartável com metas objetivas, testes adversariais | P1 / coordenação |
| Armazenamento em rede | SQLite WAL local | nenhum dos 37 é um drop-in de Postgres | backend multiusuário de controle transacional com migrations/fencing, backup testado e disaster recovery | P1 / lacuna própria |
| Segredos e credenciais | tokens locais privados e credenciais por provider | SPIRE, Keycloak (parcial) | vault/escopo, rotação, egress guard, logs sem segredos e revogação distribuída; selecionar secret store | P0 / lacuna própria |
| Instalação e atualizações | installers / setup / CI em evolução | Grype + snippets upstream | instalação modular sem exigir 37 serviços, dependências isoladas, rollback e diagnóstico de saúde | P1 / lacuna própria |
| Integridade da execução | outputs + receipts + idempotency | Temporal/Tessera/benchmarks | provar semântica de exactly-once side effect (idempotência/reconciliação), sem promessas absolutas | P0 / lacuna própria |
| Operação desconectada | desktop local offline possível | Yjs, NATS | política de offline, conflitos, limite de privilégios e sync segura ao reconectar | P2 / lacuna própria |
| Política de recursos/custos | orçamento e limitações por run | OTel, provider usage | memória, CPU, IO, tráfego e gastos por executor/máquina, cancelamento de processo órfão | P1 / lacuna própria |
| Segurança de conteúdo | validações de inputs e tool gates | ToolHive, OPA | prompt injection, supply-chain de tools, conteúdo de arquivos externos, upload, browser & secrets | P0 / lacuna própria |
| Privacidade e consentimento | projeto local de amigos | Keycloak/OPA (parcial) | retenção/expurgo, consentimento de screen/clipboard, acesso e exportação em dados compartilhados | P1 / lacuna própria |

## 3. Anti-duplicação: decisão final

- É viável incorporar pywinauto, Yjs, y-protocols e clientes MCP diretamente, mantendo os avisos legais.
- Daytona, guacd, ToolHive, NATS, SPIRE e Hocuspocus devem ser serviços/adaptadores opcionais, ativáveis apenas quando necessários.
- UFO/Constellation, LangGraph e Temporal fornecem padrões ou subfluxos; não devem substituir os próprios goals/runs, scheduler, quotas, policy ou audit do SENTRA.
- OPA/OpenFGA devem apenas executar decisões delegadas a partir da autoridade de identidade/credenciais do SENTRA; sem duplicação ou bypass.
- Tessera prova integridade de eventos registrados; não prova completude nem captura ações feitas fora do gateway.
- Os benchmarks WindowsWorld, WindowsAgentArena e OSWorld V2 ficam fora do runtime; servem apenas para validar entrega.

## 4. Contrato mínimo e pontos de integração

Machine identifica a máquina real/sandbox e proprietário. Capability descreve capacidade tipada com risco e versão. AgentSession identifica provedor/CLI/modelo/conta sem expor credencial. OperationRequest aponta a WorkItem + Run/Operation durável e idempotency_key. PolicyDecision dá allow/deny, escopo e condições. ExecutorAdapter implementa discover/start/observe/cancel/reconcile/cleanup e snapshot opcional. AuditEnvelope vincula decisão, comando, resultado e prova criptográfica.

- Um único ponto obrigatório de autorização ANTES de qualquer efeito.
- Uma única identidade de Operação registrada antes do envio, com lease/fencing.
- Repetição de evento com ID existente exige reconcile, nunca re-send automático.
- UI/CRDT não muda status autoritativo ou grants.
- NATS/ACP/A2A/MCP são transporte e semântica externa, não bancos de autorização.
- Testes de falha de rede, queda de navegador, perda de resposta, cancelamento e revogação fazem parte de cada entrega.

## 5. Escopo distribuído nas quatro conversas

Projeto e protocolo de propriedade: docs/SENTRA_OS_SPRINT_CONTRACT_V1.md.

- EXEC-001: sentra_executors/ + tests/unit/test_sentra_executors_*.py — Machine Runtime Windows/Daytona, provas de segurança.
- CRIT-002: sentra_interop/ + tests/unit/test_sentra_interop_*.py — ACP, A2A, ToolHive/MCP.
- CRIT-003: sentra_collab/ + sentra_canvas/static/sentra-collab.js NOVO + tests/unit/test_sentra_collab_*.py — Yjs/Hocuspocus e isolamento entre usuários.
- Coordenador: sentra_runtime/ + tests/unit/test_sentra_runtime_*.py e docs/SENTRA_OS_*.md — contratos globais, política fail-closed, auditoria, gates e integração futura.
- Nenhuma equipe modifica módulos compartilhados do SENTRA nesta fase sem validação. O fato de enviar uma instrução não prova que outro chat a tenha executado; inspecionar respostas, filesystem e testes.

## 6. Critérios para declarar SENTRA OS concluído

1. Pelo menos dois executores locais/remotos reais heterogêneos com efeito e evidência verificados.
2. ACP e A2A com duas conversas reais e delegação reproduzível.
3. Ações guiadas por policy e aprovação por usuário; teste negativo real em todo executor.
4. Sandbox/confinamento comprovado no Windows e Linux onde aplicável.
5. Dois amigos autenticados editando Canvas simultaneamente com separação de dados.
6. Uma sessão de desktop remoto consentida e revogável.
7. Falha e retomada distribuída com idempotência e prova de não duplicar ações irreversíveis.
8. Trilhas assinadas verificáveis de decisão, execução e artefatos.
9. Benchmark em VMs com pontuação objetiva por tarefa, latência e custo.
10. Build, installer e CI com checks de segurança, rastreabilidade e rollback.

### Conclusão

O inventário cobre quase todas as *categorias* do OS agêntico. Repositórios clonados NÃO preenchem lacunas automaticamente: o maior esforço restante é a integração robusta das abstrações de máquina, permissões, execução e observabilidade. Backup/migrations, segredo/consentimento, políticas offline, integração do installer, validação de modelo Web e E2E multinó continuam como trabalho próprio.
