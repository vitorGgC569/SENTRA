# SENTRA OS — Gate 8 / auditoria de coordenação

Data local de execução: 09/10/2026, aproximadamente 02:22 BRT. Revisão somente de módulos sob propriedade e leitura do ControlStore existente. **Nenhum serviço externo iniciado.**

## Evidência executada nesta rodada

- Testes focados com cinco arquivos: test_sentra_runtime_contracts.py, test_sentra_runtime_authority_bridge.py, test_sentra_executors_gate3.py, test_sentra_interop_gate5.py e test_sentra_collab_boundary.py: **71 passed**, exit code 0, 5,54 s.
- `npm test --prefix sentra_collab`: **26 passed**, 0 failed, exit code 0, 2,79 s. Casos incluem epoch revocation, WebSocket loopback, nonce e precommit.
- Leitura de `git status --short`: módulos sentra_runtime/, sentra_executors/, sentra_interop/ e sentra_collab/ permanecem **untracked**; existem muitas outras modificações prévias na árvore. Não usar reset/clean nem commits globais.
- Revisão de arquivos das três frentes: últimas alterações listadas datam de 09/10/2026 00:06 BRT ou antes; não se observou entrega posterior neste checkpoint.
- Baseline integral Gate 6 continua **1425 passed, 4 skipped, 1 warning**; não foi repetida integralmente nesta rodada.

## P0 confirmado no código, sem alteração do core alheio

`sentra_mcp/services/durable.py::create_operation` (perto da linha 1057) seleciona `operations` por `(run_id,idempotency_key)` e retorna `idempotent_replay=True` sem verificar `kind`, `operation_id` ou um fingerprint canônico. A tabela SQLite `operations` não tem coluna de intent hash. O mutex `self.lock` é do processo; o índice UNIQUE garante unicidade da chave, mas não garante equivalência de intenção. `_verify_fence_locked` em `update_operation` protege a atualização de estado, não prova que um efeito externo rejeita um lease revogado no instante do dispatch.

`sentra_runtime/executor.py` mantém fingerprint SHA-256 e cópia imutável por serialização JSON apenas no registro de memória. Não conectar o executor ao create_operation legado para efeitos externos. A migração de schema e admissão transacional exige revisão do proprietário de sentra_mcp/ e validação de duas instâncias reais, restart e crash.

## Próximas ações sem sobreposição

- EXEC-001 (somente sentra_executors/ e testes): testes negativos de reutilização PID/HWND, identidade de processo/janela e fencing no instante do efeito; UIA apenas em Tk lab opt-in e usuário/VM isolado. Daytona remoto permanece não comprovado.
- CRIT-002 (somente sentra_interop/ e testes): stress ACP e cleanup de subprocessos, pinning executable/cwd/argv, reattach e tool calls iniciadas pelo agente sempre negadas sem grant; A2A/MCP sem servidor externo ainda não são E2E.
- CRIT-003 (somente sentra_collab/ e testes): host CAS multi-sidecar com banco transacional real quando autorizado; revogação de epoch e commit ambíguo, zero leakage de CRDT/awareness; fixture não prova WSS em dois dispositivos.
- Coordenador (sentra_runtime/ e docs/SENTRA_OS_*): planejar integração com autoridade existente, fingerprint persistido, operação UNCERTAIN sem replay, autorização live e lease/fencing no executor. Não duplicar ControlStore.

## Limites de execução e comunicação

O Desktop Commander está online e permitiu leituras, git status e testes focados. Uma tentativa de executar comando composto de inspeção e outra de escrever teste negativo para o defeito de replay foram **bloqueadas pelas verificações de segurança da ferramenta**; não se contornou o bloqueio. Nenhum teste novo foi gravado. Gate 6/7/8 **não têm recibo de envio** às três conversas originais; não afirmar entrega, não reenviar uma entrega incerta e não criar chats substitutos.

Este documento é handoff interno. A matriz dos 37 projetos permanece em docs/SENTRA_OS_GATE5_ABSORCAO_2026-10-08.md.
