# Lume — fechamento Pulso e automações subordinadas

Autorização/ownership: ../REDISTRIBUICAO_CODEX.md. Você assume Pulso além de seu
interop/registry/canais entregue. Leia nota integral, tasks/Pulso.md, Pulso.md,
Cobalto-status/requirements/coverage/contracts e fontes. Não estreitar requisitos.

Ownership herdado: sentra_interop/workflow* e activepieces*, goal_loop,
conpty_sessions, operation_receipts, routine_scheduler/jobs. Nexo mantém
sentra_runtime/MachineHost; root mantém Canvas/http/server/graph/configs.

Fechar RuntimeProviderHost/factories SDK reais Temporal/LangGraph, worker/graph
provisionados com pins/restauração e mesma MachineHost; RuntimeProviderMachine
e TerminalWriteMachine completos, nomes/IDs configurados coerentes no restore,
policy/Grant/Run/WorkItem/budget/fence centrais, sem scheduler soberano. Corrigir
builders/facade para root admitir/executar workflow/runtime/terminal intents reais.
Ligar NATS/Activepieces agendamentos/externalwebhooks TLS/provenance/dedupe;
claim de canais Lume->workflow signal->SUCCEEDED no mesmo WorkItem->ack;
outbound provider ACK separado de recipient receipt; diário ConPTY existente
com register/cursor/closed, scoped live=False restart e sem replay de inputs.

Precisamos signatures configure_runtime_machine/configure_terminal_machine,
root workflow/runtime resolvers e payload schemas exatos. Root compõe
PulsoShellDispatch na bridge, deve devolver resultado executado/receipt e não
apenas intent builder. Não pedir Grant/owner/Run do renderer; ID de operação
é gerado servidor e seletores de observação são target_operation_id.

Sem teste/build/install/lint/QA/benchmark, SENTRA skill/MCP, commit/push/reset/
stash/recrutamento; PID47408 intocado. Relate docs/integral/Lume-fechamento.md
com contratos e pendências por arquivo, sem ask-back síncrono.
