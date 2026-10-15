# Marlin — frentes 2 e 3 — 2026-10-13

## Reconciliação observacional

A VM `fcd974cf-ccdc-5636-b7af-2f96024d5dde` não fica incerta só porque `bootstrap/launch-intent.json` existe. Esse intent é o da instalação que o recibo `runbook-receipts/07-verify-guest.json` concluiu em modo verify-only: `installed_guest_verified`, disco `/dev/sda1`, desktop confirmado, `disk_uuid` `9cf5e721-7cbd-48e9-9634-d2d709c9cb68`. A tentativa anterior, sem partição, está arquivada em `bootstrap-attempts/1791808577-6fbb84c5` e não foi reenviada.

Leitura `VBoxManage showvminfo` nesta sessão, sem alterar a VM: `VMState=running`, 4096 MB, 2 CPU, `GuestAdditionsVersion=7.2.20 r175154`, `GuestAdditionsRunLevel=2`, boot só por disco, SATA 0 no `system.vdi` com o mesmo UUID do recibo, portas SATA 1–3 vazias. Isso não é uma sonda nova de guestcontrol. `installation.advance` com `confirm_launch` devolve `installed_guest_observed`, `observation_only`, `contemporary_probe: false`, e não chama launch nem prepare.

O arquivo `imports/fcca0db011b44f4593381b0164c82c88.tar` permanece. Não foi copiado de novo nem apagado. Usar esse nome como `request_key` é recusado antes de qualquer comando no convidado.

## Causalidade do uncertain antes da admissão

As duas chaves continuam sem linha em `operations`. Entre 03:43 e 03:50 só apareceram `op-217d4e8ecd6044662f745da3b1a30b0f` (`shell.message_send`, UNCERTAIN) e `op-0061343d0f7d41cf92f2bd277bfc16e4` (`chatgpt-web-turn`, UNCERTAIN). Nenhuma é `sentra.machine`.

A ponte grava `uncertain` em `ShellHostRequests.invoke`, em `sentra_canvas/shell_requests.py`, no `except BaseException` depois do `callback`. O `INSERT` inicial é `claimed`. A reserva central só acontece depois, em `DurableOperationGate.submit` → `reserve_intent`. Como não há linha, a exceção saiu antes dessa reserva. O `except` não grava a classe nem a mensagem: `protected_result` fica nulo. O HTTP, em `CanvasHandler._handle`, responderia 400 com o texto cortado em 200 caracteres, ou 500 no formato `NomeDaClasse: operation failed`. Esse corpo não foi persistido.

Tempos do diário: a primeira chave ficou 96,981 s entre `claimed` e `uncertain` (03:43:47 → 03:45:24). O cliente HTTP desistiu aos 90 s; o waiter de `MachineHost._call` é 150 s, então não foi esse timeout. A segunda ficou 1,017 s (03:48:15 → 03:48:16), também antes da reserva.

O PID 6836 subiu em 2026-10-12 15:58:47. `shell_requests.py` é de 2026-10-11 e é o código carregado. `shell_dot_vm.py` (03:37 de 13/10), `vm_resources.py` (03:49) e `virtualbox_vm.py` (03:59) são posteriores à subida. O processo não carregou esse código novo. Não reiniciei o canvas.

Ponto de recuperação: preservar as duas linhas `uncertain` sem resultado. Não reenviar essas chaves. Ausência de Operation, lease e worker não é `SUCCEEDED`. A importação continua esperando um verify central contemporâneo com chave nova, num processo que já tenha o código atual. `resource.cap` está no `_execute` e devolve `apply_authorized_cap`; o recibo com rollback é escrito em `state_root/vm-cap-receipts/<operation_id>.json` antes de `controlvm`, e só se o intent reservado tiver `controlled_proof` e `workload_inspected`. Esta sessão não disparou `resource.cap` na VM registrada.

## Duas Operations de verify

Nenhuma chave nova foi enviada. O timeout HTTP não foi tratado como fim do efeito.

| request_key | operation_id | diário da ponte | estado central | lease / fence | erro gravado | worker |
| --- | --- | --- | --- | --- | --- | --- |
| `verify-marlin-20261013-7cfe83ca1f0a` | `op-shell-fc888e287357d491605c923b3d40d1b88d43a336` | `uncertain`, sem resultado | linha ausente | nenhum | nenhum | nenhum processo com essa chave |
| `verify-marlin-20261013b-d7f07c43634e` | `op-shell-0a0a71a4cbe77e20feaa0d16488f23ea65cac35e` | `uncertain`, sem resultado | linha ausente | nenhum | nenhum | nenhum processo com essa chave |

Não há `effect-lock` com esses ids. Não há `VBoxManage.exe` vivo. O processo `6836` é o canvas, não um worker dessas chaves. As duas tentativas estão terminais no diário e não serão repetidas. A importação continua esperando um `SUCCEEDED` contemporâneo. As frentes 2 e 3 não estão homologadas.

## resource.cap

`VM_ACTIONS['vm:manage']` admite `resource.cap`. `_execute` devolve `apply_authorized_cap` com `ResourceCeiling`. Sem autoridade central a resposta é recusa, `executed` falso, e o cliente VirtualBox não é chamado. Não alterei CPU, RAM nem cap da VM real. Não chamei `VBoxManage` no host. O contrato não está homologado.

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/frentes/marlin/test_fronts_2_3.py::test_resource_cap_call_site_refuses_without_central_authority_and_does_not_touch_vbox
1 passed in 6.71s
```

## installation.verify — 2026-10-13

Autoridade lida sem abrir a credencial. Projeto `1dccb4d7e53946f9b6f5743733a37433`. Dot `dot-04df85d21b0c095adc14a9fd39dbdc96` (Testando Advanced), espaço `space-e43df8551e95d3056a932d24b09db197`, agente `07869c683ca64485b88efff200be0711`, conversa `conversation-de5e0c18c973a5ef9c43c8dc3a298b54`, WorkItem `vm-c589c5dc499050e99ca58c57fb235640`. Grant `grant-d48a1e2f57e24d6281bc1b1cee41b8c6`, efeito allow, capacidade `vm:guest`, não revogado. A credencial está no registro e não foi impressa nem enviada no argumento. Posse humana do teclado não estava viva. `GuestAdditionsRunLevel` 2.

Duas chamadas novas de `dot_vm_execute` / `installation.verify` ficaram `uncertain` no diário da ponte, sem resultado gravado. Chaves `verify-marlin-20261013-7cfe83ca1f0a` e `verify-marlin-20261013b-d7f07c43634e`. A primeira esgotou a espera do cliente; a segunda voltou erro HTTP. Nenhuma das duas será reenviada. O log da VM não mostra sessão Guest Control depois do uptime `04:31:18`, com o log já em `14:27:52`. Não houve cópia, launch, prepare, reenvio de `launch-intent` nem exclusão do tar, da VM, do VDI ou do Dot.

A importação real continua dependente de um `installation.verify` central com recibo `SUCCEEDED` contemporâneo e de uma `request_key` nova, diferente dessas duas e de `fcca0db011b44f4593381b0164c82c88`.

## Próximo passo autorizado

Quem desenha o botão é a Lumen. A ponte já admite, sem desenhar botão e sem emitir credencial:

`dot_vm_execute` com `{ "action": "installation.verify" }`, capacidade `vm:guest`.

Dependência exata: grant `vm:guest` no WorkItem deste Dot, convidado em execução, canal das Guest Additions, e a credencial já gravada no registro da VM. Este passo não recebe senha no argumento. Não pode chamar `installation.launch`, `installation.prepare`, reenviar `launch-intent.json`, copiar ou apagar o tar sem recibo, nem apagar VM, VDI ou Dot.

Só depois de um `installation.verify` central desta operação, com `installed_os_verified` contemporâneo, a importação real é `project.import` com `host_folder` absoluto dentro do projeto e uma `request_key` nova, diferente de `fcca0db011b44f4593381b0164c82c88`.

Esta sessão não executou `installation.verify` nem `project.import` no convidado real. As frentes 2 e 3 não estão homologadas.

## Teste

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/frentes/marlin/test_fronts_2_3.py tests/unit/test_virtualbox_bootstrap.py
32 passed in 10.78s
```

O `SUCCEEDED` dos testes continua com cliente falso ou leitura de recibo. Não reinstalei Debian e não copiei pasta ao convidado.

# Marlin — frentes 2 e 3 — 2026-10-12

Executor das frentes 2 (provisionamento do Dot e da VM) e 3 (importação de projeto). Checkout `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Nenhum commit, push, reset, clean ou rebase. Nenhuma VM, VDI, Dot, conversa, `.sentra` ou `.oma` foi apagada. A instalação Debian incerta e a cópia anterior não foram reenviadas.

## Código neste checkout

- `sentra_executors/virtualbox_bootstrap.py`: ação `advance` (`installation.advance`). Exige CPU, RAM e disco já reservados nos limites da interface. Recusa `launch-intent.json` já gravado, mesmo com `confirm_launch`. Em disco Linux vazio e desligado, sem bootstrap, prepara o seed com usuário `sentra` e desktop XFCE. Desktop já verificado não é reinstalado. Lançamento só com admissão distinta.
- `sentra_executors/virtualbox_installation.py`: postura de licença Windows. Canais admitidos: `owner_supplied_iso`, `evaluation_unactivated`, `owner_attested_license`. Chave de produto é recusada e não é gravada. `windows_usable` sai só da sonda do convidado: `Licensed`, ou `Notification` quando o canal é avaliação. `activation_claimed` permanece falso.
- `sentra_executors/virtualbox_vm.py`: `installation.advance` em `vm:manage`. `provision` de Windows não marca o desktop como usável. `guest.run` não repete o executável depois de `--`. `project.import` aceita `host_folder` e `request_key`.
- `sentra_executors/virtualbox_project.py`: a pasta do Windows tem de ser absoluta e ficar dentro do projeto vinculado. Raiz do disco, atalho, junction e pasta sensível são recusados. O tar é copiado para um diretório, o SHA-256 confere o nome exato e a extração exige `SENTRA_IMPORT_COMPLETE`. Intenção aberta ou payload diferente da mesma chave não gera outra cópia. O recibo `SUCCEEDED` só é escrito depois da confirmação do convidado.
- `tests/unit/frentes/marlin/test_fronts_2_3.py`: testes novos desta rodada.

Não houve mudança em `virtualbox_seed.py`, `windows_guest.py`, `windows_guest_deployment.py` nem `guest_process.py`. O convidado Hyper-V desses módulos continua sendo fixture descartável, não um Windows licenciado do Dot.

`sentra_canvas/desktop_ui` não foi editado. O botão continua com a Lumen.

## Lapidação de 2026-10-13

O `SUCCEEDED` do corte anterior permanece recibo de executor simulado. Esta lapidação não o promove a prova física.

`installation.advance` fica chamável pela ponte `dot_vm_execute`, capacidade `vm:manage`, argumento opcional `confirm_launch`. O estado do Dot publica esse contrato em `bridge.actions`, com `screen_button: false`. A ponte grava a observação em `installation_advance` e não troca `installation_launch_sent` nem `uncertain_requires_reconciliation`. `project.import` no mesmo contrato declara `replays_duplicate_operation: false`. Uma intenção aberta ou a mesma chave com outra pasta não gera outra cópia.

Não houve reinstalação Debian, reenvio de `launch-intent`, cópia ao convidado nem exclusão de VM, VDI ou Dot.

## Dispatch pela ponte — 2026-10-13

`test_bridge_publishes_advance_and_keeps_a_recorded_attempt` agora chama `DotVmServices.dispatch` com `dot_vm_execute`. O cliente de VirtualBox é falso e recusa `guestcontrol`, `controlvm`, `startvm`, `storageattach`, `unattended` e criação de disco. `installation.advance` com `confirm_launch: true` devolve `prior_attempt_not_replayed` e não altera o `launch-intent`. `project.import` com a chave antiga devolve o recibo gravado, `replayed: true`, sem cópia. A mesma chave com outra pasta não gera outro `copyto`.

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/frentes/marlin/test_fronts_2_3.py
12 passed in 9.79s
```

O canvas desse teste fica em diretório temporário. Nenhuma VM, VDI ou Dot real foi apagado. O `SUCCEEDED` continua sendo executor com cliente falso, não prova física.

## Teste da lapidação — 2026-10-13

Unidade. Não é prova física e não homologa as frentes.

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/frentes/marlin/test_fronts_2_3.py tests/unit/test_virtualbox_bootstrap.py
30 passed in 2.64s
```

No mesmo corte, antes do ajuste do carimbo `interface_action`, `tests/unit/test_shell_dot_vm.py` e `tests/unit/test_virtualbox_project.py` já tinham passado junto com o restante: 51 passed, 1 failed, 1 skipped. A falha era só o carimbo e foi corrigida no comando acima. O skip segue sendo o teste antigo de symlink.

## Teste do corte anterior

Unidade, com convidado falso. Não é prova física.

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/frentes/marlin/test_fronts_2_3.py tests/unit/test_virtualbox_project.py tests/unit/test_virtualbox_installation.py tests/unit/test_shell_dot_vm.py::test_executor_uses_real_argv_stdin_credentials_and_detected_os tests/unit/test_shell_dot_vm.py::test_virtualbox_72_partial_detect_boots_iso_without_false_unattended_claim
30 passed, 1 skipped in 2.11s
```

O skip é o teste antigo de symlink em `tests/unit/test_virtualbox_project.py`, quando o token Windows não cria o link.

```text
python -B -m pytest -q -p no:cacheprovider tests/unit/test_virtualbox_bootstrap.py
18 passed in 1.92s
```

O recibo `SUCCEEDED` desse corte é o `OperationResult` do `GuardedExecutor` sobre um `guestcontrol` simulado. O mesmo `operation_id` não reenvia. A mesma `request_key` devolve o recibo gravado sem `copyto`.

## Prova física contemporânea

Nenhuma nesta sessão. Não houve `guestcontrol` real, preparação de seed na VM existente, lançamento de instalação, boot de disco nem cópia de pasta para o convidado.

Não reaproveito como prova desta rodada o registro anterior da VM `fcd974cf-ccdc-5636-b7af-2f96024d5dde` nem a operação `op-shell-7326a0030be23e64e8ec85fbc7879f62e7c7c6d4`. Também não repito o `launch-intent` já gravado nem a cópia que ficou incerta.

## O que não está homologado

1. Criar o Dot, reservar recurso, instalar Debian, usuário e desktop pelo botão que o usuário vê. A ponte já aceita `installation.advance`. A tela, que é da Lumen, ainda não desenha esse botão.
2. Windows usável. Não houve ISO Windows, sonda real de licença nem desktop Windows observado. `provision` continua podendo iniciar a instalação autônoma do VirtualBox para uma ISO já configurada, e mesmo assim devolve `windows_usable: false`.
3. Pasta real do Windows copiada ao convidado com hash, extração e recibo central `SUCCEEDED` de uma operação nova. A tentativa física anterior permanece sem reenvio.
4. Exclusão de Dot, VM ou VDI. Não foi pedida aprovação e não foi feita.
