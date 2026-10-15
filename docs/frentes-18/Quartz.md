# Quartz — frentes 13 e 16

Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou clean. Nenhum recurso de usuário foi apagado. Grants, leases e a proteção de UNCERTAIN não foram enfraquecidos.

## Frente 13 — auditoria da decisão ao recibo

Código novo em `sentra_quality/decision_receipt_audit.py`. O ledger registra, em cadeia com hash, a decisão do modelo, a ferramenta, a autorização observada, a execução (lease e fence), o resultado, o recibo e a revisão humana. `authorizes_effect` permanece falso. O ledger não emite Grant, não adquire lease e não despacha efeito.

`orchestrator/quality_gate.py` ganhou `gate_decision_observation`. O quorum, a nota mínima 9.5 e o `evaluate` existente não mudaram. A observação do gate não carrega Grant.

`orchestrator/observability.py` ganhou `AuditSpanRecorder`. O `MetricsCollector` anterior permanece.

Testes adversariais em `tests/unit/frentes/quartz/`:

- Isolamento: outro owner ou outro Dot não lê a cadeia nem anexa principal alheio.
- Idempotência: o mesmo corpo sela de novo; corpo diferente conflita; fence diferente conflita.
- Injeção: texto não confiável não abre cadeia, não vira instrução e não é gravado em claro. Argumento de ferramenta e motivo de autorização com injeção são recusados.
- UNCERTAIN não é reenviado. Reconciliação com `resend=true` é recusada. Reconciliação observando um estado posterior mantém `uncertain` e `resend_allowed=false`.
- Alterar o SQLite quebra a cadeia de hash.
- `AuthorizationService` foi importado nos testes e não foi editado. Sem Grant, a capacidade continua negada. Grant de `vm.import` não libera `vm.delete` nem outro Dot. Revogação volta a negar. Atalho `local_owner` continua só para o usuário dono no SQLite. O ledger não cria linha de Grant.

## Frente 16 — licença, uso e suporte

Política em `sentra_quality/local_use_policy.py` e comandos `python -B -m sentra_quality local-use` e `support-bundle`. Paywall, cobrança e bloqueio do uso local são recusados. A licença presa é MIT. Homologação comercial fica falsa.

Documentos em `docs/frentes-18/comercial/`: `README.md`, `LICENCA.md`, `USUARIO.md`, `SUPORTE.md`. CLI, desktop, Canvas local, REPL e MCP em loopback permanecem abertos, sem conta e sem pagamento. Superfície hospedada opcional ausente não desliga o uso local. O pacote de suporte não coleta token, `auth.json` nem prompt.

## Validação desta sessão

Comando, na raiz do checkout:

```text
python -B -m pytest -q tests/unit/frentes/quartz --tb=short
```

Saída:

```text
....................                                                     [100%]
20 passed in 4.51s
```

Exit code: 0.

Isso é teste unitário executado agora, neste checkout. Não é prova física.

## Prova física

Não há prova física contemporânea nesta frente. Nenhuma decisão de modelo real foi acompanhada até um recibo central de Run, WorkItem, Operation e Grant nesta sessão. Nenhum efeito foi despachado pelo ledger. Nenhuma operação UNCERTAIN já registrada (cópia para a VM, upload binário `BINARY_UPLOAD_UNCONFIRMED`) foi repetida.

## Lapidação — recibo central

`DecisionReceiptLedger.bind_central_receipt` lê o Run, o WorkItem, o recibo central da Operation (`receipt_for_operation`) e o Grant já existente. Não reserva intenção, não emite Grant, não renova lease e não despacha efeito. Grant revogado ou identificador ausente não sela a cadeia. Operação central `UNCERTAIN` permanece sem reenvio.

Comando desta correção, na raiz do checkout:

```text
python -B -m pytest -q tests/unit/frentes/quartz --tb=short
```

Saída:

```text
.......................                                                  [100%]
23 passed in 8.55s
```

Exit code: 0. Continua sendo teste unitário num Control Plane temporário. Não é prova física e não homologa o produto.

## Auditoria independente — 2026-10-13

Critério: `docs/frentes-18/Codex-homologacao-integral.md` linhas 9, 29 e 32. As frentes 13 e 16 seguem abertas. Teste com Control Plane temporário não fecha. Nenhum arquivo de outra frente foi editado. Latch não está conectado no canvas; a leitura do pacote abaixo não é confirmação do Latch.

Funções só alcançadas por teste ou CLI isolada:

- `gate_decision_observation` em `orchestrator/quality_gate.py:365`. O único call site é `tests/unit/frentes/quartz/test_decision_receipt_audit.py:132`.
- `AuditSpanRecorder` em `orchestrator/observability.py:147`. O único call site é `tests/unit/frentes/quartz/test_local_use_policy.py:111`.
- `bind_central_receipt` em `sentra_quality/decision_receipt_audit.py:612`. Os call sites são só `tests/unit/frentes/quartz/test_central_receipt.py`.
- `LocalUsePolicy` entra em produção apenas por `sentra_quality/__main__.py:93`. O instalador não chama essa CLI.

O portão que o produto usa não sela o ledger. `orchestrator/engine.py:1517` chama `QualityGate.evaluate`. `engine.py:1523` chama `_decision_quality_advisory` (`engine.py:805`), que só emite um score se `decision_quality_advisory_enabled` estiver ligado. O padrão é falso em `orchestrator/agents/router.py:106` e `orchestrator/configuration.py:36`. O escore marca `authoritative: False` em `engine.py:875` e não cria Run, WorkItem, Operation, Grant nem recibo. `sentra_mcp/services/workspace_ops.py:205` repete o mesmo portão e devolve `passed`/`reason`/`package`.

Pacote lido em `installer/windows/install-next.ps1:78-141`: copia canvas, federation, collab, remote, mcp, core, runtime, ícone e `sentra_version.py`. Não copia `LICENSE`, `docs/frentes-18/comercial/` nem `sentra_quality`. O marcador é `kind=next_install`, `product_version=0.1.0`. `federation_handshake.py` é copiado na linha 97 e não é executado. `sentra_remote/support_surface.py:15` só é chamado por `tests/unit/test_sentra_product_minimum_fronts.py`.

Caminhos alheios, só leitura: Flint chega a `central_effect_admission` por `sentra_runtime/dot_tool_dispatch.py:561` e `sentra_canvas/shell_actor.py:207`, sem o ledger. Pylon observa incidente em `sentra_canvas/shell_dot_lifecycle.py:191` e não grava auditoria. `apply_plan` e `invoke_connector` não têm caller fora dos testes de Nimbus e Sable.

## Contrato de produção

Contrato versão 2 em `sentra_quality/production_audit.py`. `record_fleet_admission` não sela: a admissão é fallback e não conta como decisão de modelo. `record_runner_final_answer` sela só resultado vivo do runner (`live_model_verified`, `evidence_source=native_process`), com hash da instrução, `stdout_sha256`, ferramenta e modelo reais. O lease copiado é `leases.resource_key` e `leases.fencing_token`, iguais à Operation. Runner injetado não sela.

A sessão do Dot só é gravada depois de `runner_audit` com `source=model` e `counts_as_model_decision`. A admissão e o runner injetado não gravam sessão. O teste `test_session_is_saved_only_after_the_central_receipt` cobre essa ordem. `central_effect_admission` não foi editado.

`tests/unit/frentes/quartz/test_production_audit.py`, `test_central_receipt.py` e `tests/unit/frentes/flint/test_live_dispatch_gate.py`: 8 passed em 35,97 s. Isso não fecha as frentes 13 e 16.

O defeito do pacote está confirmado: o instalador Next não copia `LICENSE`, `docs/frentes-18/comercial/` nem `sentra_quality`. A lista para o Latch está em `docs/frentes-18/comercial/PACOTE_LATCH.md`. O diagnóstico é `sentra_quality/distribution_diagnosis.py`. Não há paywall.

## Não homologado

- Auditoria ponta a ponta com inferência real e recibo central.
- Homologação comercial, auditoria de segurança independente, SBOM/CVE e licenças de terceiros.
- Instalador em máquina limpa, ciclo do Dot dentro da VM, imagem nativa entregue e importação física de projeto. Esses itens pertencem a outras frentes e continuam abertos no estado verificado de 12/10/2026.
- O teste unitário não homologa o produto.
