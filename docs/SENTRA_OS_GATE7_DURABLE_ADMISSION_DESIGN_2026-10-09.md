# SENTRA OS — Gate 7: decisão de segurança sobre reserva durável

Revisão de 09/10/2026 01:42 BRT. Esta nota é uma especificação e auditoria estática, não uma implementação nem prova E2E.

## Evidência lida

- sentra_runtime/executor.py guarda fingerprint SHA-256 de JSON canônico da intenção completa, mas somente em memória do processo. O replay in-process é reautorizado e alterações do payload são recusadas.
- sentra_mcp/services/durable.py::create_operation, próximo da linha 1057, usa SELECT por (run_id, idempotency_key). Se existe, retorna o registro com idempotent_replay=True, sem comparar kind, operation_id ou fingerprint de OperationRequest.
- O esquema SQLite operations, próximo da linha 230, possui UNIQUE(run_id,idempotency_key), mas não tem coluna para hash canônico da intenção nem epoch de autorização.
- _verify_fence_locked protege operações de atualização do registro quando um token é fornecido. Isso não comprova fencing no instante de um efeito externo executado por Windows UIA, Daytona ou agente ACP.
- Não houve execução de teste novo nesta rodada: chamadas de execução pelo Desktop Commander foram bloqueadas pelas verificações de segurança da ferramenta. Nenhum código ou arquivo de outra frente foi alterado.

## Contrato de integração obrigatório antes de habilitar dispatch remoto

1. O controlador confiável calcula o fingerprint sobre a representação canônica completa de OperationRequest (operation_id, principal_id, machine_id, capability_id, work_item_id, idempotency_key, arguments), com limite de tamanho, sem NaN, chaves duplicadas ou tipos inesperados. A política nunca recebe autoridade de request.arguments.
2. Uma transação no MESMO ControlStore persistente da operação liga atomicamente run_id, owner, operation_id, idempotency_key, intent_sha256, versão do esquema, estado e reserva. Não criar banco paralelo nem dois journals autoritativos. A mesma transação decide conflitos de operação e idempotência.
3. Em replay, comparar a intenção inteira e todas as identidades; divergência => conflito, nunca retorno de resultado anterior como autorização de um novo efeito. Um registro legado sem fingerprint => quarentena/fail-closed, com migração explícita; não inferir fingerprint retroativamente a partir de kind.
4. Após COMMIT da reserva e antes do efeito, revalidar WorkItem RUNNING, grant atual, owner, capability e lease. Uma falha/timeout do commit ou dúvida sobre a reserva => UNCERTAIN e reconciliação, sem dispatch.
5. O executor deve validar fencing token e identidade da máquina NO ponto do efeito. A verificação somente em update_operation é insuficiente. Não prometer exactly-once distribuído: um crash após commit e antes de side effect exige reconciliação e pode reduzir liveness.
6. Duplicata idêntica jamais é tratada como nova oportunidade de execução; devolver estado persistido sob nova autorização. Se estado persistido é UNCERTAIN, não reexecutar automaticamente.
7. A migração precisa preservar a API legada de operações já existentes sem transformá-las em autorizações para novas ações. Compatibilidade de leitura não significa autorização de dispatch.

## Testes de aceite necessários

- Duas instâncias concorrentes, mesma chave, intenções diferentes: exatamente uma reserva, outra conflito, nenhum segundo efeito.
- Mesma operação/mesmo fingerprint após restart: leitura autorizada do estado, sem novo efeito.
- Mesmo idempotency_key com operation_id, principal, machine, work item, capability ou argumentos alterados: conflito.
- Crash entre reserva e efeito; crash após efeito mas antes de confirmação: estado incerto e reconciliação explícita, jamais replay automático.
- Revogação e expiração de lease entre admissão e efeito: efeito negado pelo executor com fencing.
- Erro de banco, busy timeout, migração incompleta, registro legado sem fingerprint, policy indisponível: fail-closed.
- Testes com DurableRunService SQLite real e processos concorrentes, além de fixtures. Testes UIA/Daytona/ACP externos são marcos separados.

## Limite de propriedade

O coordenador pode editar sentra_runtime/ e testes test_sentra_runtime_*.py; sentra_mcp/services/durable.py não está incluído no contrato de sprint. A correção real do banco existente exige marco de integração com proprietário do módulo e revisão de migração. NÃO adaptar ExecutorRegistry ao create_operation legado para dispatch de efeitos antes disso.

## Equipes e bloqueio de comunicação

EXEC-001: testar PID/HWND reuse, identidade de janela, revogação e fencing no ponto do efeito em laboratório isolado; sem afirmar isolamento por PID.
CRIT-002: stress ACP stdio com pinning, cleanup e pedidos iniciados pelo agente; A2A/MCP sem grants implícitos.
CRIT-003: CAS multi-sidecar, epoch/nonce compartilhado, commits ambíguos, revogação e zero leakage; host fixture não é banco real.
As mensagens Gate 6 ainda não possuem recibo de entrega; não reenviar sem confirmar transporte autorizado e ausência de duplicidade.
