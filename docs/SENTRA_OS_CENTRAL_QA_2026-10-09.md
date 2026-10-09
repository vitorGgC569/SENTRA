# SENTRA OS — QA da integração central (09/10/2026, ~10:36 BRT)

## Escopo e fonte
Coordenação em OGrandeOxta, repositório `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Consultados `docs/SENTRA_OS_CENTRAL_INTEGRATION_2026-10-09.md` e `docs/SENTRA_OS_SPRINT_3X3_PHASE3_2026-10-09.md`; leitura independente de `sentra_mcp/services/durable.py`, `sentra_runtime/central_authority.py`, `sentra_runtime/durable_admission.py`, `sentra_executors/central_integration.py` e `sentra_interop/central.py`.

## Evidência nova, observada nesta rodada
- A sessão de testes do Desktop Commander PID 30276 concluiu com **exit code 0: 1718 passed, 7 skipped, 1 warning in 404.66s**. A saída tinha barra de progresso até 100% e linha de resumo. Este resultado substitui a afirmação anterior de suíte completa ainda em andamento. Não houve nova execução concorrente iniciada por esta coordenação.
- Regressão focal SEQUENCIAL dos quatro arquivos centrais (`test_sentra_runtime_central_integration.py`, `test_sentra_runtime_canvas_center_http.py`, `test_sentra_executors_central_integration.py`, `test_sentra_interop_central_real.py`): **31 passed in 14.94s, exit code 0**, PID de teste 32188 concluído. Não prova fencing no driver físico nem broker instalado atualizado.
- `git status --short` confirmou os novos módulos `sentra_runtime/`, `sentra_executors/`, `sentra_interop/`, `sentra_collab/` e documentos `SENTRA_OS_*` ainda untracked, com alterações preexistentes extensas. Nenhum reset/clean/commit executado.
- `runs/SENTRA_CENTRAL_INTEGRATION_20261009_DISPATCH.json` registra ordem central inicial **SENT** para EXEC-001 e CRIT-002; CRIT-003 **NOT_SENT, retry_safe=true**. Handoffs técnicos posteriores da nova API constam NOT_SENT na fonte de verdade. Não houve reenvio nem recibo novo nesta rodada.

## Revisão de fronteira de autorização e execução
- `DurableRunService.reserve_operation_intent` implementa `BEGIN IMMEDIATE` para vincular fingerprint SHA256, operação, chave idempotente e lease/fence no mesmo SQLite/WAL. Replay `EXISTING` exige reconciliação, nunca novo efeito. A API legada `create_operation` não é admissão de efeito.
- `CentralDurableIntentAuthority` adapta o mesmo DurableRunService; não há segundo ledger.
- **Bloqueio ainda material para efeitos externos:** `DurableOperationGate.submit` chama `authority.fence_active(receipt)` ANTES de `effect(request)`, mas a assinatura do callback de efeito não recebe `receipt`/fencing token. Sem mecanismo de vinculação adicional e verificação no driver físico no instante do efeito, há janela TOCTOU. O contrato avisa isso explicitamente. Não habilitar dispatch remoto, browser externo ou UIA com base apenas na suíte verde.
- EXEC-001 `central_integration.py` já aceita autoridade injetada e constrói máquina de admissão owner-scoped; sua máquina registrada é agent-scoped. Ainda exige prova E2E de identidade e fence no backend antes de produção.
- CRIT-002 `central.py` ainda inicializa gate com `control.durable` legado, cai em blocked-only e nunca chama provedor externo. Deve receber integração revisada do agente dono, sem edição cruzada.
- A API Canvas central está testada em CanvasServer de laboratório, mas o processo broker previamente documentado era antigo e retornava 404. Nesta rodada não houve reinício/encerramento do Canvas nem comprovação da nova rota no broker ativo.

## Próximos gates
1. EXEC-001: teste read-only no ControlPlane REAL com `CentralDurableIntentAuthority`, grant vivo/revogado, identidade owner/agent, colisão, cancelamento, lease expirado e verificação do fence **dentro** do driver, não só no gate.
2. CRIT-002: injetar autoridade central real e vincular Run/WorkItem/Operation a ACP/MCP readonly/SSE; manter blocked-only para qualquer provedor sem fence físico.
3. CRIT-003: ordem central ainda não entregue; só enviar ao chat original quando Edge Bridge estiver comprovadamente operacional, com recibo. Não abrir chat substituto.
4. Coordenador: desenhar contrato de callback de efeito com receipt/fence e revalidação de grant no instante do efeito, incluindo testes negativos multi-conexão/crash/replay; revisar operação de Canvas sem matar sessões ConPTY.

Nenhum E2E de produção com Daytona, Windows, OpenHands, Guacamole, Activepieces, Temporal, Canvas remoto ou WSS foi observado. Não foi instalado serviço nem exposto segredo.

## Revisão independente posterior — boundary + suíte integral (09/10/2026, tarde BRT)

- OGrandeOxta online. `sentra_runtime/effect_boundary.py` tinha 319 linhas, com `_end_owned`, `run_blocking`, worker borrow/deferred release; o teste correspondente tinha 226 linhas. Alterações posteriores ao teste da rodada anterior foram retestadas nesta rodada.
- Regressão focada SEQUENCIAL: `python -B -m pytest -q -p no:cacheprovider tests/unit/test_sentra_runtime_effect_boundary.py --disable-warnings` -> **6 passed**, exit 0, 3.58s, PID 9284.
- Cinco arquivos centrais executados juntos após a rodada focada, sem concorrência: `test_sentra_runtime_central_integration.py`, `test_sentra_runtime_canvas_center_http.py`, `test_sentra_executors_central_integration.py`, `test_sentra_interop_central_real.py`, `test_sentra_runtime_effect_boundary.py` -> **37 passed**, exit 0, 15.56s, PID 32232.
- Suíte Python `tests/unit` INTEGRAL executada depois, isoladamente, PID 16800: **1847 passed, 50 failed, 34 skipped, 1 error, 1 warning, 14 subtests passed; exit 1, 477.64s**. A baseline anterior 1718/7 é histórica e NÃO descreve a árvore atual. Não anunciar release nem suíte verde.
- Grupos de falha: 11 testes Canvas/experiência/orçamento/documentos/workflow (nomes com espaços rejeitados pelo `validated_name`; `create_operation` exige `idempotency_key`); 8 benchmark/datasets (inclui arquivos SQLite temporários bloqueados no Windows e identidade duplicada); 1 workspace selector MCP; 1 migração Canvas Graph (`collaboration_projection` já existe); 4 collab boundary (Canvas agora carrega referências `sentra-collab.js`/`SentraCollab` contra testes de opt-in); 19 executors Daytona/remote sessions/RustDesk (inclui bloqueio WinError 32 em SQLite temporário e `rustdesk_native_patch_source_drift`); 5 interop Activepieces/ACP/workflow (KeyError payload, timeout e DuplicateOperation); 1 runtime Keycloak/OPA/OpenFGA (teste esperava 1 chamada a cada PDP, observou 2 chamadas OPA e 1 OpenFGA). Houve 1 erro adicional de teardown por `sessions.sqlite` em uso.
- Essas falhas não foram corrigidas automaticamente: várias pertencem a outros agentes e há alterações concorrentes não revisadas. Não modificar escopos alheios, não relaxar segurança apenas para satisfazer expectativas antigas, não usar reset/clean. Primeiro reconciliar contratos e recursos temporários; retestar por grupo, depois suíte integral.
- `run_blocking`/deferred release melhora a proteção de trabalhadores que o utilizam, mas não prova segurança de providers que usam `asyncio.to_thread` diretamente quando o event loop encerra, nem fencing independente no driver físico, crash ou produção E2E. Não habilitar dispatch externo. Broker Canvas com sessões ConPTY não foi reiniciado nesta rodada; Node não foi reexecutado.

### Correção de expectativa de teste no escopo do coordenador

- Revisão de `OpenFGADenyVeto`: sua composição chama a política base **antes e depois** do Check remoto. Quando a política base é `OPADenyVeto`, são **2** consultas OPA e **1** OpenFGA, intencionalmente, para revalidar a autorização após o Check. O teste antigo exigia uma consulta OPA e falhava apesar do veto adicional correto.
- Atualizado SOMENTE `tests/unit/test_sentra_runtime_external_authority_phase3.py` para exigir explicitamente 2 OPA + 1 FGA e zero chamadas extras após revogação. Não foi relaxada nenhuma validação de autorização.
- Reteste focado completo do arquivo: **26 passed**, exit 0, 10.60s, PID 38036. Isso resolve apenas a falha do teste do coordenador; os demais grupos de falhas da suíte integral continuam pendentes. Não foi iniciada outra suíte integral nesta rodada.
