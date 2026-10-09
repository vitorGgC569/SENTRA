# Gate 6 — revisão de 09/10/2026

Verificação focada: 238 passed, 1 skipped em 18 arquivos Python. Testes de colaboração: 26/26 Node PASS. Integridade de fontes: 37/37. A suíte completa de tests/unit foi iniciada e ainda não tinha resultado final na hora desta anotação.

Os três escopos permanecem exclusivos: EXEC-001 em sentra_executors, CRIT-002 em sentra_interop, CRIT-003 em sentra_collab; o coordenador mantém sentra_runtime e docs/SENTRA_OS_*. Nenhum E2E com agentes externos, sandbox Daytona, dois dispositivos reais ou WSS foi validado.

P0: o DurableRunService.create_operation retorna replays por (run_id, idempotency_key), mas não valida o fingerprint de OperationRequest. A integração deve comparar intenção persistida e falhar fechada após crash, antes de qualquer efeito; leases requerem fencing no executor.
