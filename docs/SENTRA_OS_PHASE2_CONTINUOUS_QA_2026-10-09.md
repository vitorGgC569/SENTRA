# SENTRA OS — QA contínuo da Sprint 3×3 Fase 2 (09/10/2026)

Auditoria independente via Desktop Commander em OGrandeOxta, repositório `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Leitura do contrato de propriedade e relatório de Fase 2; nenhum arquivo de outra equipe editado, nenhum serviço externo instalado ou iniciado, nenhum git reset/clean/commit. HEAD observado: `68e3894`; módulos novos ainda untracked e árvore de trabalho compartilhada com muitas alterações preexistentes.

## Testes desta rodada — resultados com exit code

- **EXEC-001 Fase 2 isolada** (todos os `test_sentra_executors_*.py` exceto os novos `*_phase3.py`): **162 passed, 3 skipped**, exit 0, 4,42 s. Preserva evidência de Playwright browser controlado, remote-readonly loopback e Windows identity/fence fixtures. E2E real Playwright isolado, Guacamole/RustDesk, automação Windows pessoal não homologados.
- **CRIT-002 todos os arquivos interop atuais**: **120 passed**, exit 0, 18,37 s. ACP/A2A/MCP/Activepieces/OpenHands/LangGraph/Temporal são compatibilidades/fixtures locais, não serviço externo homologado.
- **CRIT-003 `npm test --prefix sentra_collab`**: **51 passed**, exit 0, 3,03 s Node. Inclui testes reais de WebSocket loopback, nonce, precommit, recovery, lifecycle, quotas e rejeições. Não prova Canvas nativo em produção, WSS entre dois dispositivos nem múltiplos escritores sincronizados.
- **Coordenador**: `test_sentra_runtime_contracts.py`, `test_sentra_runtime_durable_admission.py`, `test_sentra_runtime_otlp_sink.py`, `test_sentra_quality_grype_gate.py`: **62 passed**, exit 0, 4,48 s. A cópia separada `policy_request` é verificada contra fingerprint; `adapter_request` é snapshot separado no `ExecutorRegistry.submit`. Não equivale a reserva durável em `sentra_mcp`.
- Outros testes de inventory/collab/authority foram iniciados e seu resultado será anotado apenas após confirmação de exit code.

## Regressão observada na Fase 3 (não confundir com Fase 2)

Suíte **integral atual de EXEC-001**, que inclui arquivos novos `test_sentra_executors_gvisor_phase3.py` e `test_sentra_executors_hcs_phase3.py`: **176 passed, 3 skipped, 18 failed**, exit 1, 5,38 s. A Fase 2 isolada permanece verde.

17 falhas gVisor surgem antes do runner na construção de `RunscBinding` em `sentra_executors/gvisor_runsc.py:79`, pela comparação `type(self.bundle) is not Path` (e análogas): no Windows `Path(...)` é instância de `WindowsPath`, portanto o teste de tipo exato rejeita caminhos válidos. QA recomendado ao proprietário EXEC-001: validar `isinstance(..., Path)` sem relaxar checks de `resolve`, traversal, symlink, ownership e pinning; retestar os casos negativos para garantir que nenhum escape é liberado.

Uma falha WinHCS: `test_hcs_timeout_or_fault_does_not_replay_uncertain_kill` espera `FAILED` após timeout, mas recebeu `UNCERTAIN`. Como o efeito de `terminate` pode ter ocorrido, **UNCERTAIN é o estado semanticamente seguro**; revisar expectativa do teste e confirmar que operação com nova ID não repete efeito sem reconciliação. Não alterar o core nem converter timeout ambíguo em sucesso.

As novas implementações da Fase 3 estão em progresso, portanto essas falhas são status provisório e não prova de quebra da Fase 2. Nenhum arquivo EXEC-001 foi alterado pelo coordenador.

## Restrições e handoff

Prioridade P0 independente: `sentra_mcp/services/durable.py::create_operation` não compara fingerprint de intenção em replay de `run_id+idempotency_key`, e o fence do ControlStore não é atestado no instante do efeito. Não ligar dispatch remoto ao método legado, não criar banco paralelo, exigir revisão do proprietário de `sentra_mcp/`.

Manter a autoridade de `OperationRequest`/`PolicyDecision` e testes negativos de política ausente, replay, concorrência, revogação e precommit. Os 37 clones Git verificados não equivalem a 37 serviços incorporados. Não habilitar release ou serviços externos a partir de fixtures. Escopos: EXEC-001 somente executors e seus testes; CRIT-002 somente interop e testes; CRIT-003 somente collab, novo sentra-collab.js e testes; coordenador somente runtime, quality, testes próprios e docs/SENTRA_OS_*.

Os recibos de Fase 3 constam em `runs/SENTRA_SPRINT3_PHASE3_DISPATCH_20261009.json` para as **mesmas três conversas originais**, com status SENT. Não reenviar esses prompts. Nenhuma nova mensagem de QA foi enviada nesta rodada; este documento é handoff auditável para revisão pelo proprietário.

### Comunicação de QA

Uma tentativa ÚNICA de encaminhar o diagnóstico novo de 18 falhas à conversa EXEC-001 pelo Edge Browser Bridge foi bloqueada pelas verificações de segurança da ferramenta antes de haver recibo. **NÃO houve entrega confirmada**; não foi tentado canal alternativo nem reenvio. O handoff permanece neste documento para revisão legítima posterior. Não confundir com os prompts de Fase 3 já confirmados no arquivo de recibos.

### Teste cruzado ainda pendente

Foi iniciada uma execução adicional de `test_sentra_quality_source_inventory.py`, `test_sentra_collab_boundary.py` e `test_sentra_runtime_authority_bridge.py` sob PID de sessão 27780. O processo imprimiu apenas oito pontos e não apresentou resultado final/exit code até a última consulta; portanto **não conta como teste aprovado**. A tentativa de encerramento controlado da sessão foi bloqueada pelas verificações de segurança da ferramenta; nenhum mecanismo alternativo foi usado. Verificar se a sessão terminou e se deixou filhos antes de novos testes cruzados.
