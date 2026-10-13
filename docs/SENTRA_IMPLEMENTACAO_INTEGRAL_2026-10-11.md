# SENTRA — implementação integral coordenada no Maestri

## Ordem mandatória do usuário

1. Estado inicial preservado na `main` e enviado a `origin/main`: `3639a2e296428db8e3bb0839fac87d9237ec8592`.
2. Implementar integralmente a nota conectada `todos-os-projetos-ja-estao-clo`, os estudos por ela referenciados e a migração visual para **CopilotKit/OpenDots**.
3. **Implementação integral primeiro; validação somente no final de todas as implementações.** Durante esta fase não executar testes, builds de verificação, lint, benchmarks, auditorias de homologação ou QA visual. É permitido ler código, levantar requisitos, implementar, criar testes para execução futura e registrar contratos/dependências.
4. Não usar skills nem MCP do SENTRA nesta tarefa. Usar shell, edição direta e comunicação Maestri.
5. Até cinco Codex implementadores, mais um Codex auxiliar de orquestração: todos gpt-6.1-sol com esforço high (alto), em papéis heterogêneos; seis OpenCode Muse Spark 1.3 gratuitos com esforço High. Não criar agentes adicionais sem o orquestrador principal.

## Fonte de requisitos (ler integralmente o material pertinente)

- Nota Maestri `todos-os-projetos-ja-estao-clo` (465 linhas).
- `C:/Users/vitor/OneDrive/Desktop/SENTRA_RESEARCH_OPENDOTS/SENTRA_OPEN_DOTS_RESEARCH.md`: 55 achados e matriz G01–G13/A01–A21.
- `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md`: 37 projetos.
- `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`: propostas adicionais por projeto.
- `docs/SENTRA_THIRD_PARTY_REUSE_2026-10-08.md`.
- `docs/SENTRA_ANALISE_INCORPORACAO_CHAT_ON_STEROIDS_2026-10-09.md`: 34 frentes/subfrentes.
- `docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md` e `docs/SENTRA_CHECKPOINT_IMPLEMENTACAO_E_PENDENCIAS_2026-10-09.md`.
- Clones locais: `third_party/*`, `SENTRA_RESEARCH_OPENDOTS/CopilotKit-OpenDots`, `SENTRA_RESEARCH_OPENDOTS/Anil-matcha-open-dots`. Usar o código atual como fonte, não alegações antigas de conclusão.

## Resultado integral requerido

Home, Dots especializados, conversas e Spaces são a experiência principal; Canvas existente passa a visualização interna. Dot Coordenador cria equipes/subagentes, delega tarefas, pausa e reorganiza trabalhos pela conversa. Chat, Canvas, CLI e Desktop consultam os mesmos agentes e o mesmo estado autoritativo. Projetos anteriores devem migrar de forma recuperável.

Incorporar todos os mecanismos aplicáveis dos estudos: documentos ricos/autosave/conflitos/versionamento/colaboração; continuidade e compactação; agendamentos; aprovações duráveis; outbox e recibos; execução Windows/browser/sandbox/remota; terminais persistentes; ACP/A2A/MCP; plugins MCPB/Skills; políticas e identidade; automações/conectores; histórico/anexos; observabilidade/diagnósticos; instalação/atualização/distribuição. Componentes opcionais podem permanecer opcionais, mas seus fluxos reais devem ser implementados; contratos vazios, stubs, placeholders e simulação não substituem integração.

Preservar ControlPlaneService/Run/WorkItem/Operation/Grant como autoridade única. Não executar backend OpenDots como segunda autoridade. Preservar proveniência/licenças de código reutilizado e falhar de forma explícita quando um serviço opcional não estiver configurado.

## Responsáveis e propriedade de arquivos

Todos trabalham na árvore compartilhada. Não editar arquivos de outro responsável; enviar contrato/solicitação ao dono e ao Codex principal. Não fazer commit/push/reset/stash nem remover mudanças alheias. Cada responsável pode criar arquivos novos no seu domínio e testes exclusivos, mas não executar validação ainda.

| Agente | CLI/modelo | Responsabilidade e arquivos exclusivos |
|---|---|---|
| Meridiano | Codex gpt-6.1-sol high | Auxiliar de orquestração. Extrair a matriz completa de requisitos dos três estudos, dependências, lacunas de implementação e distribuição sem reduzir escopo. Dono de `docs/integral/requirements.md`, `docs/integral/coverage.json`, `docs/integral/contracts.md`. Sem editar código de outros. |
| Prisma | Codex gpt-6.1-sol high | Migração visual integral OpenDots, Home/Dots/Spaces/conversas, Canvas interno e painéis contextuais. Dono de `sentra_canvas/desktop_ui/src/main.jsx`, `desktop.css`, novos componentes de shell/conversa e package.json da UI. Acompanhar integração real com os endpoints do Codex principal. |
| Nexo | Codex gpt-6.1-sol high | Autoridade central, Run/WorkItem/Grant/Operation, coordenação conversacional e persistência de Dots/Spaces/equipes. Dono de `sentra_core/*`, `sentra_runtime/*`, `sentra_mcp/services/control_plane.py`, `control_store.py`, `durable.py`, `context*.py`, `task_ledger.py`, `budget_policy.py`, `governance.py`, `conversation_memory.py`, `workspaces.py`. Criar módulo próprio de serviço coordenador/Spaces se necessário. |
| Forja | Codex gpt-6.1-sol high | Execução Windows/UFO/UIA, Daytona/HCS/gVisor, Playwright, remoto/Guacamole/RustDesk e RPA. Dono de `sentra_executors/*` EXCETO `goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py` e benchmarks. Implementar provedores reais e memória/recovery, não apenas contratos. |
| Lume | Codex gpt-6.1-sol high | ACP/A2A/OpenHands/MCP SDK, registry, lifecycle, descoberta, streams/artefatos/delegação. Dono de `sentra_interop/*` EXCETO `workflow*` e `activepieces*`. |
| Tessela | Codex gpt-6.1-sol high | Documentos ricos, autosave/CAS/conflitos/versionamento, Yjs/y-protocols/Hocuspocus, presença/undo, PDFs/código/diff. Dono de `sentra_collab/*`, `sentra_canvas/project_review.py`, `sentra_canvas/project_documents.py` e componentes novos `document-*`/`collaboration-*` na UI. Coordenar inserção no shell com Prisma. |
| Rastro | OpenCode Muse Spark 1.3 Free high | Continuidade A→B, Compact & Resume, outbox cifrada/recibos/recuperação, gateway modelos/contas/esforços. Dono de `native_bridge/*`, `sentra_model_gateway/*` EXCETO `browser_host_identity.py`, e `sentra_mcp/services/session_checkpoint.py`, `web_account_dispatch.py`, `web_history_*`. |
| Brisa | OpenCode Muse Spark 1.3 Free high | Extensão Edge/browser, identidade/provas de conversa, streaming/anexos/aprovação observada e catálogo de conta autenticada. Dono de `edge_extension/*`, `browser/*`, `sentra_model_gateway/browser_host_identity.py`, `sentra_mcp/services/browser_evidence.py`, `integrations/codex_chatgpt_web/*`. Contratos com Rastro. |
| Pacto | OpenCode Muse Spark 1.3 Free high | MCPB stdio/HTTP/OAuth/supervisão/sandbox/uninstall, Skills versionadas, superfícies mínimas/Code Mode e consentimento por chat. Dono de `sentra_mcp/services/mcpb_*`, `plugin_*`, `skill_library.py`, `tool_exposure.py`, `chat_access.py`, `action_consent_gate.py`, `sentra_mcp/tool_policy.py`, `sentra_code_mode/*`, componentes existentes de plugins/skills/chat-access. |
| Pulso | OpenCode Muse Spark 1.3 Free high | Scheduling persistente, Goal/Loop, NATS/Temporal/LangGraph, Activepieces, workflows empresariais, terminal persistente e recibos humanos. Dono de `sentra_interop/workflow*`, `activepieces*`, `sentra_executors/goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py`, `sentra_mcp/services/routine_scheduler.py`, `jobs.py`. |
| Selo | OpenCode Muse Spark 1.3 Free high | OPA/OpenFGA/Keycloak/SPIRE, Tessera/immudb, telemetria OpenTelemetry/Langfuse, memória/custos/diagnósticos e Grype. Dono de `sentra_quality/*`, `memory/*`, `sentra_mcp/services/authorization.py`, `capabilities.py`, `telemetry.py`, módulos novos de política/identidade/auditoria e benchmarks de `sentra_executors/benchmark*`. |
| Vitra | OpenCode Muse Spark 1.3 Free high | Setup/Doctor/reparo, staged update/migração/rollback, Windows/Electron/CLI, instalação/distribuição e proveniência. Dono de `sentra_remote/*`, `scripts/commander/*`, `.github/workflows/*`, `sentra_electron/*`, `sentra_canvas/electron_host.py`, `native_app.py`, `__main__.py`, `sentra_cli/*`, manifests de release. Preparar QA final sem executar. |
| Codex | Orquestrador principal | Dono dos pontos centrais de composição: `sentra_canvas/service.py`, `graph.py`, `sentra_mcp/server.py`, configuração raiz/pyproject e integração entre todos os módulos. Libera etapa de validação somente após TODAS as frentes implementadas e integradas. |

## Comunicação e entrega

Executar `maestri list` antes de contatar colegas. Cada agente lê a nota ou este documento e o estudo de seu domínio, implementa integralmente sua parte e registra `docs/integral/<Nome>.md`: requisitos, arquivos alterados, contrato de integração, pendências reais, plano de validação futura. A documentação não substitui implementação.

Relatar progresso e dependências ao principal com `maestri ask "Codex" "..."`; no término da implementação, usar esse comando para retornar o resultado completo. Não declarar homologado nem completo por leitura de arquivos. Meridiano consolida a matriz e solicita expansão das tarefas faltantes ao principal. Não recrutar mais agentes. Todos preservam mudanças existentes e a regra de validação ao final.

## Etapa final (ainda não liberada)

Depois da implementação integral e integração de todas as frentes, executar testes apropriados, builds, verificação visual/fidelidade ao CopilotKit/OpenDots, concorrência/recovery/permissões, provedores autorizados e instalação/release. Confrontar requisito por requisito com evidência atual. Não declarar sucesso integral enquanto faltarem implementação, integração ou evidências.
