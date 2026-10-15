# Pylon — frentes 5 e 7 (2026-10-12)

Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou limpeza. Nenhuma VM, VDI, Dot, conversa, `.sentra` ou `.oma` de uso real foi apagada. Nenhuma operação UNCERTAIN foi reenviada.

## Prova física contemporânea

Não houve prova física nesta rodada.

- Exclusão real de Dot, família, conversa ChatGPT, VM ou VDI não foi executada. O pedido `EXCLUIR DOT` grava recibo e para em `deletion_blocked_pending_user_approval`.
- Não houve crash, fechamento do Canvas instalado, queda do relay em execução nem reboot da máquina do usuário.
- Em 13/10/2026 a ponte passou a despachar `dot_pause_family`, `dot_resume_family` e `dot_delete_request` para as funções já existentes. O teste HTTP do Canvas temporário exige o recibo. `shell_pause_wired` ficou `true`.
- Isso continua sendo um Canvas temporário, não o aplicativo instalado. Não arquiva conversa no provedor e não apaga disco.
- O script `scripts/frentes/pylon_e2e.py` usa o mesmo `shell_bridge` em processo, num diretório temporário, e terminou `ok: true`. Também não é homologação da GUI.

## Frente 5 — ciclo de vida da família

Em `sentra_canvas/shell_dot_retirement.py`:

- `pause_family` / `resume_family`: a raiz e os membros do canvas mudam `desired_state` para `WAITING` e de volta ao estado anterior. Cada passo é reivindicado antes do efeito. A mesma `request_key` devolve o mesmo recibo e não chama de novo. Grants, WorkItems, conversas, VM e VDI permanecem.
- ACK perdido: o passo fica `uncertain`, a repetição da mesma chave não reexecuta, e `reconcile_family` só confirma o que já observa. Passo ainda `pending` não é executado.
- `dot_archive_local` / `dot_restore_local`: o recibo local cobre todos os `dot_id` da família. Um filho não permanece ativo quando a raiz é arquivada.
- `request_deletion`: recibo `dot-delete-request-…`, `physical_effect_performed: false`, `orphans_created: []`, lista `would_orphan_if_root_removed_alone`. Nada é removido.

`sentra_canvas/shell_dot_authority_retirement.py` não foi alterado. O fecho de autoridade que já existia continua claim-before-effect, sem retry automático e sem apagar VM.

## Frente 7 — reconciliação sem segundo efeito

- `sentra_runtime/uncertain_recovery.py`: incidentes `crash`, `canvas_closed`, `relay_down`, `reboot`. Plano só de leitura. `effects_executed: 0`, `may_resend: false`, `promoted_work_items: 0`. `UNCERTAIN` e `IN_REVIEW` ficam em observação. Conversa ou job de relay em voo fica bloqueado, sem replay.
- `HumanReceiptViews.recovery_projection`: a mesma projeção sanitizada, sem stdout, segredo ou caminho.
- `orchestrator/state_machine.py`: `FAILED -> RETRYING` é recusado quando `effect_state` é `UNCERTAIN`, `RUNNING`, `IN_FLIGHT`, `IN_REVIEW` ou `may_have_started`. Sem esse marcador, o retry antigo continua válido.
- `DurableResourceLeaseManager.admit_after_incident`: não adquire nem libera lease. `QUEUED` depois do incidente não conta como não iniciado.
- `classify_seat`: não grava `conversations.json` e não chama `drop_seat`. Payload selado do relay (`dpapi:` / `keyring:`) passa a ser lido; antes um job existente parecia ausente.

## Teste executado agora

Unidade e regressão dos módulos tocados, sem a suíte inteira do repositório:

```text
python -m pytest tests/unit/frentes/pylon tests/unit/test_reconcile.py tests/unit/test_shell_dot_lifecycle.py tests/unit/test_durable_resource_leases.py tests/test_state_machine.py tests/unit/test_sentra_executors_cos_operation_receipts.py -q --tb=line
```

Resultado: **36 passed in 61.43s**.

A primeira execução só de `tests/unit/frentes/pylon` teve 6 passed e 1 failed: `classify_seat` lia o payload selado como JSON e tratava o job como ausente. A leitura do lacre foi corrigida e `tests/unit/test_reconcile.py` mais esse teste passaram (5 passed). A rodada de 36 é posterior a essa correção.

Script, Canvas temporário, exit 0:

```text
python scripts/frentes/pylon_e2e.py
```

```json
{"ok": true, "pause_receipt": "dot-family-e165c29fd34c5f6fc947281e62796121", "resume_receipt": "dot-family-f0308ff5e27b424d9eac594a69138074", "archive_receipt": "dot-local-4805ff3fc0484bdcbbe9293a51b36459", "restore_receipt": "dot-local-f1a1f699d95d85b2431918acf9c7a3aa", "deletion_receipt": "dot-delete-request-e34b8e0493da196bfb1d82d3c341c1f3", "deletion_status": "deletion_blocked_pending_user_approval", "recovery_incident": "canvas_closed", "recovery_effects_executed": 0, "uncertain_operation_state": "UNCERTAIN", "shell_pause_wired": false, "physical_deletion_executed": false, "vm_or_vdi_touched": false, "conversation_deleted": false}
```

## Lapidação de 13/10/2026 — despacho na ponte

`sentra_canvas/shell_dot_lifecycle.py` só ganhou três ações. Cada uma chama a função que já existia em `shell_dot_retirement.py`:

- `dot_pause_family` → `pause_family`
- `dot_resume_family` → `resume_family`
- `dot_delete_request` → `request_deletion`

Nenhuma dessas ações apaga Dot, VM, VDI ou conversa. A exclusão continua em `deletion_blocked_pending_user_approval`.

```text
python -m pytest tests/unit/frentes/pylon tests/unit/test_shell_dot_lifecycle.py -q --tb=short
```

Resultado: **22 passed in 77.03s**.

```text
python scripts/frentes/pylon_e2e.py
```

Exit 0. `shell_pause_wired: true`. `recovery_effects_executed: 0`. Recibo de pausa `dot-family-cb7a40f0bc5eed619ef482d5a10b5add`. Recibo de retomada `dot-family-140686babb54e9223f717d010fc80e3b`. Recibo do pedido de exclusão `dot-delete-request-96dadee01a2cffecfc153b983102895b`.

A ponte HTTP, no mesmo dispatch, agora também cobre estes recuos. `confirm_name` errado volta 403, sem `operation failed` e sem mudar `desired_state`. A mesma `request_key` devolve o mesmo `receipt_id` e não chama o agente de novo. Outra chave com a família já pausada volta 403. Família arquivada volta 403 antes de qualquer restauro. O pedido certo fica em `deletion_blocked_pending_user_approval`, com `effects_executed` 0 e id estável. VM sintética, conversa e Dots permanecem. A tela não lê esses recibos; isso fica com a Lumen.

```text
python -m pytest tests/unit/frentes/pylon/test_family_lifecycle.py -q --tb=short
```

Resultado: **4 passed in 23.08s**.

`dot_reconcile_family` entrou na ponte e só chama `reconcile_family`. Passo `pending` não chama `update_agent`. A mesma `request_key` da pausa incerta não reaplica o efeito. O recibo traz `effects_executed` 0. O passo já observado fica `confirmed`; o pendente permanece `pending`.

```text
python -m pytest tests/unit/frentes/pylon/test_family_lifecycle.py -q --tb=short
```

Resultado desta passagem: **4 passed in 19.02s**.

`dot_incident_reconcile` é só leitura. O incidente tem de ser `crash`, `canvas_closed`, `relay_down` ou `reboot`. A ação chama `UncertainRecovery.reconcile_durable` no run do Dot. A resposta traz `effects_executed` 0 e `may_resend` false. A segunda chamada devolve o mesmo digest. Operação `UNCERTAIN` fica `observe`. Não chama `update_agent` e não muda `updated_at`. Incidente fora da lista volta 400. O Canvas aberto não foi reiniciado e a tela não foi desenhada.

```text
python -m pytest tests/unit/frentes/pylon/test_family_lifecycle.py -q --tb=short
```

Resultado: **5 passed in 25.78s**.

O plano da ponte agora lê, no store que já existe, as conversas do dono na família do Dot e os Grants desse dono. Conversa `in_flight` fica `blocked`. Grant com evento `UNCERTAIN` fica `observe` e `may_resend` false. Operação `UNCERTAIN` continua `observe`. A segunda chamada repete o digest. `updated_at` da operação e do Grant não muda. Não chama `update_agent`.

```text
python -m pytest tests/unit/frentes/pylon/test_family_lifecycle.py -q --tb=short
```

Resultado: **6 passed in 35.51s**.

## Recibo de falha do host — 13/10/2026

`ShellHostRequests.invoke` não grava `phase=unknown` na admissão. Sem atestação explícita, a falha fica `uncertain`, `phase` nula, `query_failed` false e `effect_uncertain` true. `before_admission` só entra se `note_before_admission` gravou essa fase. `note_effect_possible` grava `after_possible_effect` e o `operation_id` na tabela. Não há correção em massa das operações, da fila ou dos leases já capturados. Replay não reexecuta.

```text
python -m pytest tests/unit/frentes/pylon/test_shell_host_requests.py -q --tb=short
```

Resultado: **2 passed in 2.65s**. Isso não homologa as frentes 5 e 7. `service.py` e a VM do Marlin não foram editados. A tela é da Lumen.

## O que não está homologado

1. Exclusão física de Dot, conversa remota, VM e VDI. Espera aprovação explícita do usuário. Não declarar como feita.
2. A ponte do Canvas temporário despacha pausa, retomada e o pedido de exclusão. O Canvas instalado que o usuário deixa aberto não foi reiniciado nem exercido.
3. Recuperação depois de crash, relay caído ou reboot não foi exercida nesse processo.
4. Arquivamento remoto no ChatGPT continua inexistente. O bloqueio `dot_delete_unavailable` do preflight permanece.
5. Estas provas não homologam as frentes 5 e 7.
