# SENTRA OS — Fase 3 · acompanhamento de integração central

Auditoria read-only no OGrandeOxta, 09/10/2026 ~10:25 BRT. Não é homologação de produção.

## Baseline anterior — NÃO reexecutada nesta auditoria

- Node sentra_collab: 54 passed, 0 failed.
- Python 49 arquivos test_sentra_*.py: 634 passed, 4 skipped.
- Sete suítes novas Fase 3: 79 passed, 1 skipped.
- 37/37 clones Git verificados. Esses números precedem as alterações recentes.

## Novas alterações observadas

- EXEC-001: sentra_executors/central_integration.py (10:24:16) e tests/unit/test_sentra_executors_central_integration.py (10:24:49). Factory consome ControlPlaneService, BoundWorkItemPolicy, ExecutorRegistry e DurableOperationGate. Sem autoridade durável injetada, nega despacho. Teste novo usa HTTP loopback e subprocesso Python de laboratório, não Playwright/WinHCS/runsc/Daytona reais.
- CRIT-002: sentra_interop/central.py (10:24:25) e tests/unit/test_sentra_interop_central_real.py (10:24:38). Usa grants/WorkItem/Run reais e registra bloqueio, não executa ACP/A2A/MCP externo.
- Coordenador: sentra_runtime/central_authority.py (10:20:21) e tests/unit/test_sentra_runtime_central_integration.py (10:22:17). O adapter usa método opt-in reserve_operation_intent do DurableRunService, observado no core; create_operation legado permanece distinto e sem equivalência de fingerprint/fence. Não houve edição de sentra_mcp nesta auditoria.
- CRIT-003: nenhuma alteração posterior ao baseline observada nesta janela; colaboração continua opt-in e não montada no Canvas.

## Bloqueio de validação sequencial

Dois processos pytest já estavam ativos em ambas as verificações: PID 19828 (início 08/10 22:36:53, 7 arquivos; CPU acumulado ~1,84 s) e PID 19212 (início 09/10 09:56:19, 3 arquivos; CPU ~1,19 s). Não há recibos de propriedade nem exit codes. Não foram encerrados, e não se iniciou nova suíte Node/Python para evitar concorrência. Os novos módulos centrais permanecem SEM teste independente nesta auditoria.

## Gates ainda abertos

1. DurableOperationGate verifica fence antes do callback effect, mas isso não prova fencing no exato limite físico de I/O; backend deve revalidar lease, grant e epoch antes do efeito, e timeout/revogação incertos não podem ser reenviados.
2. reserve_operation_intent exige revisão formal do proprietário do core, migração/restart, colisão de operation_id/idempotency_key, crash após commit, lease vencido e revogação. Não usar create_operation legado para despacho remoto.
3. CentralInteropAdapter continua fail-closed; manter até existir provider com pinning e fencing físico.
4. Quando os testes existentes encerrarem, executar SEQUENCIALMENTE npm test --prefix sentra_collab; depois pytest focado nos três arquivos novos; depois regressão Python test_sentra_*.py. Registrar exit codes reais. Não matar processos de outras conversas.
5. Nenhum E2E de produção runsc/WinHCS/Daytona, Keycloak/OPA/OpenFGA upstream, ACP externo, Temporal, Canvas remoto, WSS entre dispositivos ou Guacamole/RustDesk foi comprovado.

Sem alterações em arquivos das outras equipes, sem novos prompts aos chats (ordens Fase 3 já confirmadas), sem git reset/clean, commit global ou infraestrutura externa.