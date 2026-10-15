# Pacote que o Latch deve incluir

O instalador Next copia a lista abaixo, com `product_version` `1.0.0`. Isso não cria paywall, não bloqueia o uso local e não fecha a frente 16. Não é o pacote inteiro de `sentra_quality`: `production_audit` importa `decision_receipt_audit`, e esse módulo entra na lista. O `__init__.py` do pacote e os demais módulos de qualidade não entram.

O Latch empacota, sem paywall e sem bloquear o uso local:

- `LICENSE`
- `docs/frentes-18/comercial/README.md`
- `docs/frentes-18/comercial/LICENCA.md`
- `docs/frentes-18/comercial/USUARIO.md`
- `docs/frentes-18/comercial/SUPORTE.md`
- `docs/frentes-18/comercial/PACOTE_LATCH.md`
- `sentra_quality/local_use_policy.py`
- `sentra_quality/production_audit.py`
- `sentra_quality/distribution_diagnosis.py`
- `sentra_quality/decision_receipt_audit.py`

O diagnóstico lê o script e a árvore. Ele não cria Grant, não cobra e não declara a frente 16 fechada.

Contrato versão 2. `record_fleet_admission` não sela cadeia: a admissão é `deterministic_fallback` e `counts_as_model_decision` fica falso. O selo de decisão fica em `record_runner_final_answer`, depois do runner, com hash da instrução, `stdout_sha256`, ferramenta, modelo e a linha real de `leases` (`resource_key` e `fencing_token`). Não há rótulo `lease-`/`fence-` fabricado. Operação UNCERTAIN não é reenviada. O retorno não autoriza efeito e não homologa.
