# SENTRA OS — Gate 5 · Auditoria de absorção e coordenação de 37 projetos

Estado local: 2026-10-08, revisão no projeto C:\Users\vitor\OneDrive\Desktop\SENTRA. Não implica prontidão comercial nem release. Fonte: checkout local, docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md, testes de cada frente e snapshots Git.

## Critério de status

- **Código efetivo**: existe módulo SENTRA consumível ou extensão opt-in, com teste concreto.
- **Fronteira implementada**: há contrato/adaptador ou mock com teste, porém sem dependência externa real em execução.
- **Referência clonada**: código estudado e indexado, mas sem uso no runtime do aplicativo.
- **Infraestrutura planejada**: depende de serviços externos/configuração, deve ser opcional no modo local.
- **Benchmark**: ferramenta para validação, não componente de runtime.

## Governança por equipe

EXEC-001 → sentra_executors/ e tests/unit/test_sentra_executors_*.py: máquinas, Windows UIA, Daytona e executores de browser/remoto, nunca Control Plane.
CRIT-002 → sentra_interop/ e tests/unit/test_sentra_interop_*.py: agentes ACP/A2A/MCP, catálogo, ToolHive/OpenHands adapters.
CRIT-003 → sentra_collab/, sentra_canvas/static/sentra-collab.js e tests/unit/test_sentra_collab_*.py: colaboração e somente estado de apresentação.
COORDENADOR → sentra_runtime/, sentra_quality/, docs/SENTRA_OS_* e testes próprios: autoridade durável, hash/audit, integridade de fontes, plano de absorção e validação cruzada.

## Matriz dos 37 projetos

| Projeto | Dói onde no SENTRA | Absorção mínima | Estado verificado | Frente |
|---|---|---|---|---|
| UFO³ | Windows computer use, Galaxy DAG | estudar padrões/ações UIA/Win32 por app e mapear Machine/Operation | Referência clonada; sem operação UFO real | EXEC-001 |
| OpenHands | interface agêntica | padrões isolados de UX de agentes, conversas e aprovação | Referência clonada; Canvas SENTRA preservado | CRIT-003 |
| OpenHands Agent SDK | agentes externos | typed AgentSession/Event stream adapter | Fronteira implementada em sentra_interop/openhands.py, sem servidor real | CRIT-002 |
| Agent Client Protocol (ACP) | CLIs interoperáveis | session/new, prompt, updates, cancel e stdio seguro | Código efetivo local: fixture stdio JSON-RPC, não agentes externos | CRIT-002 |
| ACP Registry | catálogo | descriptors + versão fixada sem execução automática | Fronteira em sentra_interop/registry.py | CRIT-002 |
| A2A | comunicação agent-agent | envelopes task/artifact/ack + identidade confiável | Fronteira em sentra_interop/a2a.py, sem HTTP real | CRIT-002 |
| MCP TypeScript SDK | interoperar ferramentas TS | client/contract tool/resources seguro | SDK referência; boundaries MCP Python testados | CRIT-002 |
| Daytona | sandboxes isoladas | executor privado opt-in por SDK para sandbox previamente criado | sentra_executors/daytona.py com testes via doubles; sandbox real não validada | EXEC-001 |
| pywinauto | ações Windows UIA | janela/PID/seletor limitado, sem shell arbitrário | sentra_executors/windows_uia.py; teste UIA real skip por dependência/opt-in | EXEC-001 |
| hcsshim | Windows container | provider opcional headless, se host suportar | Referência clonada, sem runtime integrado | EXEC-001 |
| gVisor | sandbox Linux reforçada | perfil runsc opcional para workloads compatíveis | Referência clonada; não dá isolamento host Windows | EXEC-001 |
| Playwright MCP | browser agent | navegador em perfil/contexto isolado sem cookies do Edge principal | Referência clonada; não integrado ao executor | EXEC-001 |
| Guacamole Client | visualizar desktop | viewer de Machine remota com aprovação | Referência clonada; não integrado | EXEC-001 |
| Guacamole Server | RDP/VNC/SSH | guacd remoto governado por SENTRA | Infraestrutura planejada; serviço não instalado | EXEC-001 |
| RustDesk | acesso remoto máquinas | provider opcional alternativo ao Guacamole | Referência clonada; não integrado | EXEC-001 |
| LangGraph | subgrafos LLM | adapter por WorkItem, sem outro scheduler global | Referência clonada; integração opcional somente se necessário | CRIT-002 |
| Temporal | retries duráveis | padrões/worker adapter subordinado ao Run | Referência clonada; SENTRA mantém lease/runs | COORDENADOR |
| NATS JetStream | eventos dispositivos | barramento de envelopes idempotentes no gateway | Infraestrutura planejada; não instalada | COORDENADOR |
| ToolHive | MCP ToolHost | policy por tool, server registry e isolação | Boundary em sentra_interop/mcp.py com doubles; daemon não iniciado | CRIT-002 |
| SPIRE | identidade de dispositivo | SPIFFE SVID para relays/daemons remotos | Infraestrutura planejada; não instalada | COORDENADOR |
| Keycloak | login amigos | provider OIDC opcional | Referência clonada; não instalado | COORDENADOR |
| OpenFGA | autorização ReBAC | backend de decisão consultado, sem grants duplicados | Referência clonada; não integrado | COORDENADOR |
| OPA | política contextual | PDP versionado Rego opcional, deny-by-default | Referência clonada; sem PDP externo | COORDENADOR |
| Tessera | log transparência | witness/checkpoint externo para heads audit | Referência clonada; sentra_runtime/audit_chain.py só protótipo local | COORDENADOR |
| immudb | storage verificável | alternativa audit store com provas | Referência clonada; sem serviço | COORDENADOR |
| OTel Collector | traces distribuídos | exporter OTLP redigido | Referência clonada; não conectado | COORDENADOR |
| Langfuse | tracing LLM/custos | sink opt-in sem conteúdo sensível | Referência clonada; não instalado | COORDENADOR |
| Grype | CVEs SBOM | scanner de release e dependências de terceiros | Referência clonada; sentra_quality já verifica origem, NÃO CVEs | COORDENADOR |
| xyflow | nodes/edges | ergonomia/benchmark para Canvas sem substituir física | Referência clonada; não integrado | CRIT-003 |
| Yjs | edição simultânea | documentos CRDT somente layout/nós/notas | Código efetivo opt-in sentra_collab com WebSocket de teste | CRIT-003 |
| y-protocols | awareness/sync | presença sanitizada autorizada | Código efetivo no sidecar; produção não habilitada | CRIT-003 |
| Hocuspocus | servidor Yjs | WebSocket hooks auth/precommit/fencing | Código efetivo opt-in sidecar; fixture host, não conectado ao Canvas | CRIT-003 |
| Activepieces | automação SaaS | conector por WorkItem com OAuth isolado | Referência clonada; não integrado | CRIT-002 |
| RPA Framework | apps/documentos | biblioteca pontual em ExecutorRPA opcional | Referência clonada; não integrado | EXEC-001 |
| Windows Agent Arena | benchmark Windows | suíte VM de tarefas de Computer Use | Benchmark clonado, não executado | EXEC-001 |
| OSWorld V2 | benchmark geral | comparar efetividade dos executores em VM | Benchmark clonado, não executado | EXEC-001 |
| WindowsWorld | benchmark cross-app Windows | validação de etapas e efeitos | Benchmark clonado, não executado | EXEC-001 |

## Entregas atuais e evidência

- Testes de integração das frentes (pytest de 16 arquivos) em 2026-10-08 23:55–23:57: **196 passed, 1 skipped, 1 xfailed**. O xfail era defeito core conhecido de request.arguments mutável.
- Coordenador corrigiu no mesmo dia o problema core: ExecutorRegistry captura fingerprint e cópia canônica da requisição, rejeitando replay com alteração de intent; 33/33 testes runtime focados passaram; teste antigo de EXEC-001 tornou-se XPASS(strict), portanto aguardando remoção da marcação xfail pela equipe.
- GATE-4 anterior: colaboração chegou a 17/17 testes Node; cross Python 98/98. Essa rodada de pytest atual com test_sentra_collab_boundary passou, mas o runner Node separado deve ser validado após novas alterações.
- ACP stdio testado com fixture Python em subprocesso, incluindo casos de cancelamento, timeout e bloqueio de tool calls agent-initiated; histórico de falhas sob carga exige stress repetido. Não equivale a acesso a Codex/Antigravity real.
- Sentra_quality compara clones Git com approved_sources.json independente; 37/37 fontes foram verificadas na rodada anterior. Isso não é SBOM/CVE scan.
- Alterações desta sprint em módulos novos estão em arquivos **untracked**. Não promover a release sem revisão explícita de diffs, CI, package/build, security negative tests.

## Lacunas prioritárias para próxima integração

1. Gateway ControlStore/Run/Operation durável: autorização por grant e WorkItem e journal persistido, lease, fencing, reserva transacional ANTES de qualquer side effect; não duplicar autoridade.
2. Máquina real: executar WindowsUIA **somente em VM/usuário restrito**, distinguir limites de UIA por PID de isolamento OS. Daytona SDK em sandbox autorizado e privado somente após provisionamento manual revisado.
3. Agent real: ACP e A2A com agente terceiro autenticado, grantee/capability scoped, recuperação e reattach; evitar prompt-hacks. ToolHive só sob policy por ferramenta.
4. Canvas: host callbacks atômicos de commit/nonce/grant e sidecar opt-in, sem permitir CRDT alterar Run/Operation/Grant/Lease; 2 dispositivos autenticados E2E e TLS.
5. Fonte e auditoria: SBOM/Grype, testes de instalação, witness Tessera e OTel, segredo/redaction, backups/migrations; serviços opcionais para uso entre amigos.

## Política de absorção

Não substituir os componentes autoritativos do SENTRA por motores completos concorrentes. Incorporar bibliotecas pontuais, adaptar interfaces e habilitar servidores pesados apenas sob demanda. Preservar NOTICE/LICENSE aplicáveis ao compartilhamento, mesmo sem fins comerciais. As provas de E2E devem dizer precisamente qual processo/serviço/ambiente estava de fato em execução.
