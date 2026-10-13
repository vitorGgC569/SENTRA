# Funções dos seis terminais OpenCode existentes

Solicitação vigente: usar os terminais que o usuário abriu no mesmo workspace SENTRA. Não recrutar duplicatas. Modelo: `opencode/muse-spark-1.3-contributor-free`, esforço `high`. Os seis Codex permanecem exclusivamente `gpt-6.1-sol`, esforço `high`; o usuário autorizou reiniciá-los para carregar a nova conta padrão autenticada.

Diretório de trabalho: `C:/Users/vitor/OneDrive/Desktop/SENTRA`.

Regra mandatória: **implementação integral primeiro, validação somente depois de todas as implementações**. Não executar testes, build de verificação, lint, benchmark ou QA nesta fase. Não usar skills/MCP SENTRA. Não fazer commit/push/reset/stash nem modificar arquivos pertencentes a outro responsável. Preservar o checkpoint `3639a2e` já enviado à main.

Ler `docs/SENTRA_IMPLEMENTACAO_INTEGRAL_2026-10-11.md`, `docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md`, a nota `todos-os-projetos-ja-estao-clo` e os estudos completos do domínio. Documentar o resultado em `docs/integral/<papel>.md`; documentação não substitui implementação. Compartilhar dependências e contratos com Codex/Meridiano; se o Maestri recusar comunicação, registrar o impedimento no relatório local. Não criar novos agentes nem usar modelo pago como alternativa.

| Terminal existente | Papel | Escopo exclusivo |
|---|---|---|
| OpenCode | Rastro — continuidade e entrega | Continuidade A→B, Compact & Resume, outbox cifrada, recibos e recuperação. `native_bridge/*`, `sentra_model_gateway/*` exceto `browser_host_identity.py`; `session_checkpoint.py`, `web_account_dispatch.py`, `web_history_*` em services. Usar despacho real e manter estados incertos sem duplicar efeitos. |
| OpenCode #2 | Brisa — navegador e identidade | Extensão Edge, identidade/provas de conversa, streaming/anexos, espera de aprovação e modelos/esforços observados na conta. `edge_extension/*`, `browser/*`, `browser_host_identity.py`, `browser_evidence.py`, `integrations/codex_chatgpt_web/*`. Contratos com Rastro para join de IDs e recibos. |
| OpenCode #3 | Pacto — plugins e capacidades | Lifecycle MCPB stdio/HTTP/OAuth/supervisão/sandbox/uninstall, Skills Git-pinned/versionadas, tool surfaces/Code Mode, consentimento por chat. `mcpb_*`, `plugin_*`, `skill_library.py`, `tool_exposure.py`, `chat_access.py`, `action_consent_gate.py`, `sentra_mcp/tool_policy.py`, `sentra_code_mode/*` e componentes existentes de plugins/skills/chat-access. |
| OpenCode #4 | Pulso — execução persistente e automações | Scheduling durável, Goal/Loop, integração NATS/Temporal/LangGraph, Activepieces, workflows, terminal persistente e recibos humanos. `sentra_interop/workflow*`, `activepieces*`, `sentra_executors/goal_loop.py`, `conpty_sessions.py`, `operation_receipts.py`, services `routine_scheduler.py`/`jobs.py`. |
| OpenCode #5 | Selo — políticas, confiança e observabilidade | OPA/OpenFGA/Keycloak/SPIRE, Tessera/immudb, OpenTelemetry/Langfuse, memória/custos, Grype. `sentra_quality/*`, `memory/*`, services `authorization.py`, `capabilities.py`, `telemetry.py`, novos módulos próprios de política/identidade/auditoria e `sentra_executors/benchmark*`. Diagnósticos de instalação permanecem com Vitra. |
| OpenCode #6 | Vitra — desktop e distribuição | Setup/Doctor/reparo, staged update/migração/rollback, Windows/Electron/CLI e release. `sentra_remote/*`, `scripts/commander/*`, `.github/workflows/*`, `sentra_electron/*`, `sentra_canvas/electron_host.py`, `native_app.py`, `__main__.py`, `sentra_cli/*`. Coordenar a rota `/api/shell/bridge` com Codex antes de editar seu handler: composição dessa rota é responsabilidade do principal. |

O Control Plane SENTRA continua sendo a autoridade única de Run/WorkItem/Operation/Grant. A interface usa CopilotKit/OpenDots como referência visual, com Canvas interno e os mesmos agentes/estado da conversa. Todas as frentes devem integrar seus recursos ao produto; não substituir fluxos por fixtures, simulação ou contratos vazios.

## Estado observado nesta retomada

Os seis terminais OpenCode constam no arquivo do workspace e há processos CLI ativos. Isso comprova a abertura dos terminais, não que receberam estas tarefas, selecionaram o modelo ou iniciaram a implementação.

A API Maestri recusou a tentativa de restart da equipe pela conta Default: 403, avaliação expirada/workspace bloqueado. Reinício e entrega de ordens só podem ser declarados concluídos após o comando ser aceito e o terminal confirmar o resultado. Nenhum controle de licença foi alterado.
