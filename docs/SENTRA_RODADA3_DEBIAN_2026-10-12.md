# SENTRA — Relatório de Homologação P0-DEBIAN (Rodada 3 — 12/10/2026)

## 1. Escopo e Segurança

- **Frente:** P0-DEBIAN (Debian persistente no VDI exclusivo do Dot).
- **Checkout:** `C:\Users\vitor\OneDrive\Desktop\SENTRA` (Windows/PowerShell, dispositivo `OGrandeOxta`).
- **Fase executada:** **FASE 1 — Somente código, testes e leitura**.
- **Controles rígidos obedecidos:**
  - Nenhuma operação VBoxManage mutante (`controlvm`, `storageattach`, `modifyvm`, `startvm`, `unregistervm`) foi executada contra a VM física.
  - O runbook **NÃO** foi executado com `--execute` contra o ambiente físico.
  - Nenhum comando `git reset`, `checkout`, `clean`, `commit`, `push` ou `stash` foi executado.
  - Nenhuma VM, processo de relay, broker, Canvas ou aplicação foi reiniciada nesta rodada.
  - Nenhuma senha, token ou credencial foi impressa em logs, telas, recibos ou relatórios.
  - Arquivos editados limitaram-se estritamente ao escopo da frente: `sentra_executors/virtualbox_bootstrap.py`, `sentra_executors/virtualbox_installation.py`, `sentra_executors/virtualbox_vm.py`, `scripts/commander/debian_persistent_runbook.py`, `tests/unit/test_virtualbox_bootstrap.py` e este relatório.

---

## 2. Evidência Física Somente Leitura (Estado Observado)

Em 12/10/2026, inspeções somente leitura confirmaram:

1. **Estado da VM VirtualBox:**
   - VM: `SENTRA-Dot-fcd974cfccdc5636`
   - UUID: `fcd974cf-ccdc-5636-b7af-2f96024d5dde`
   - Marker: `SENTRA-DOT:fcd974cf-ccdc-5636-b7af-2f96024d5dde`
   - Hardware UUID SMBIOS: `fcd974cf-ccdc-5636-b7af-2f96024d5dde` (correspondência estrita com VM ID).
   - `VMState`: `running` (Debian Live).
   - Anexos SATA observados via `showvminfo --machinereadable`:
     - SATA 0-0: `C:\Users\vitor\OneDrive\Desktop\SENTRA\.sentra\durable\dot-vms\SENTRA-Dot-fcd974cfccdc5636\system.vdi`
     - SATA 1-0: `C:\Users\vitor\OneDrive\Desktop\SENTRA\Isos\debian-live-13.7.0-amd64-xfce.iso`
     - SATA 2-0: `C:\Users\vitor\OneDrive\Desktop\SENTRA\.sentra\durable\dot-vms\SENTRA-Dot-fcd974cfccdc5636\bootstrap\seed.iso` (tentativa antiga)
     - SATA 3-0: `C:\Program Files\Oracle\VirtualBox\VBoxGuestAdditions.iso`
   - `GuestAdditionsRunLevel`: 1 (canal autenticado guestcontrol ainda não operacional no Live).

2. **Inspeção física do VDI (`system.vdi`) em modo leitura:**
   - Caminho: `.sentra\durable\dot-vms\SENTRA-Dot-fcd974cfccdc5636\system.vdi`
   - `disk_uuid`: `9cf5e721-7cbd-48e9-9634-d2d709c9cb68`
   - `capacity_bytes`: `68719476736` (64 GiB)
   - `allocated_blocks`: `0`
   - `total_blocks`: `65536`
   - `file_bytes`: `2097152` (2 MiB, cabeçalho e tabela vazia)
   - `metadata_stable`: `True`
   - `empty_observed`: `True`
   - `partition_table_observed`: `False`
   - `metadata_sha256`: `e99b5ca9713b3ef555aff03feb07aca6ba562b7c9c3c5b196615027a2a44ba7a`
   - `installed_os_verified`: `False`

3. **Arquivos da tentativa anterior em `.sentra/durable/dot-vms/SENTRA-Dot-fcd974cfccdc5636/bootstrap/`:**
   - `admission.json`:
     - `vm_id`: `fcd974cf-ccdc-5636-b7af-2f96024d5dde`
     - `disk_uuid`: `9cf5e721-7cbd-48e9-9634-d2d709c9cb68`
     - `vdi_metadata_sha256`: `e99b5ca9713b3ef555aff03feb07aca6ba562b7c9c3c5b196615027a2a44ba7a` (100% idêntico ao VDI real atual)
     - `seed_sha256`: `6fbb84c59d80bc0e8d7b683f381b0e25e880b1beee9671c9c377ccee4d22094b`
     - `prepared_at`: `1791808430.6862545`
   - `launch-intent.json`:
     - `vm_id`: `fcd974cf-ccdc-5636-b7af-2f96024d5dde`
     - `started_at`: `1791808577.3227305`
   - `seed.iso`: contém script anterior que falhou com `SENTRA_INSTALL_FAILED line=6` antes do particionamento.

**Conclusão da leitura física:** O disco VDI está comprovadamente 100% vazio e intacto, exatamente igual à admissão original, sem dados de usuário ou partições perdidas. A pasta de bootstrap e os anexos SATA 2/3 bloqueiam uma nova chamada direta a `prepare()`, exigindo a reconciliação formal implementada.

---

## 3. Implementações Realizadas (Fase 1)

### 3.1. Reconciliação Auditável (`reconcile_failed_attempt` em `virtualbox_bootstrap.py`)
- **Assinatura:** `reconcile_failed_attempt(client, binding, cfg, *, evidence=None, detach_storage=False, request_key=None)`
- **Condições de Admissão Estritas:**
  - O VDI deve estar comprovadamente vazio (`allocated_blocks == 0`, `empty_observed is True`, `partition_table_observed is False`, `metadata_stable is True`).
  - O hash de metadados do VDI (`metadata_sha256`), o `disk_uuid` e o `vm_id` devem ser estritamente iguais aos gravados no `admission.json` da tentativa.
  - O hardware UUID SMBIOS deve ser igual ao UUID da VM (`_require_hardware_uuid`).
  - Qualquer divergência gera `ValueError` imediato (fail-closed) sem tocar em nenhum arquivo.
- **Desanexação Segura de Portas Não Hot-Pluggable (SATA 2 e 3):**
  - Como `showvminfo` reporta `SATA-hot-pluggable-2-0 = "off"` e `SATA-hot-pluggable-3-0 = "off"`, qualquer tentativa de `storageattach --medium none` com a VM em execução falha no VirtualBox.
  - Se `detach_storage=True` e a VM estiver `running`: o sistema aplica guarda de ISO Live configurada (`SATA-1-0`), envia `controlvm poweroff`, confirma o desligamento via `status()`, desanexa SATA 2 e 3 e valida via `status()` que as portas estão `none`.
  - Somente após essa confirmação o diretório `bootstrap` é movido para `bootstrap-attempts/<timestamp>-<hash>`.
- **Preservação de Dados (Nunca Apaga Nada):**
  - O diretório `bootstrap` é movido atomicamente para `bootstrap-attempts/<timestamp>-<seed_hash_short>` (ex.: `1791808577-6fbb84c5`).
  - `admission.json`, `seed.iso` e `launch-intent.json` permanecem intactos na pasta arquivada.
  - Grava `reconciliation.json` no diretório arquivado com evidências completas, motivo `install_failed_before_partition`, hashes, timestamp e intenção prévia.
- **Idempotência:**
  - Consultas subsequentes com o mesmo `request_key` retornam o recibo arquivado existente sem falhar ou duplicar diretórios.

### 3.2. Verificação de Readback do DMI e Pós-Instalação (`install_script` e `virtualbox_installation.py`)
- **Readback DMI no Guest:**
  - Adicionado `test -r /sys/class/dmi/id/product_uuid`.
  - Leitura convertida para minúsculas: `dmi_uuid=$(cat /sys/class/dmi/id/product_uuid | tr '[:upper:]' '[:lower:]')`.
  - Log explícito: `echo "READBACK_DMI_UUID=$dmi_uuid"`.
  - Validação estrita contra as duas serializações RFC 4122 válidas da VM (`@@ID@@` e `@@LEGACY_DMI@@`); se houver divergência, emite `DMI_UUID_MISMATCH` e encerra com código 33 **antes de qualquer execução do `sfdisk`**.
- **Autologin XFCE e LightDM:**
  - Correção essencial: inclusão explícita do grupo `autologin` (`groupadd -r autologin || true` e `usermod -aG autologin,sudo,audio,video sentra`). No Debian, o PAM do LightDM rejeita autologin se o usuário não pertencer a esse grupo.
  - Configurado `/etc/lightdm/lightdm.conf.d/60-sentra-dot.conf` com `autologin-user=sentra`, `autologin-user-timeout=0`, `user-session=xfce`.
  - Ativação do serviço: `systemctl enable lightdm` e `systemctl set-default graphical.target`.
  - Atualizado também em `debian_postinstall_template`.
- **Instalação das Guest Additions Locais:**
  - Detecção dinâmica do dispositivo de DVD contendo as adições (`blkid` com tag `VBOX` ou fallback `/dev/sr2`).
  - Execução de `VBoxLinuxAdditions.run --nox11`.
  - Habilitação explícita dos serviços `vboxadd` e `vboxadd-service` para assegurar que o canal `guestcontrol` suba no primeiro boot.
- **Ejeção Limpa no Boot pelo Disco (`configure_disk_boot`):**
  - Além de `--boot1 disk --boot2 none` e ejetar a ISO Live em SATA 1, agora ejeta explicitamente SATA 2 (seed) e SATA 3 (GA) se ocupadas, garantindo que o guest inicialize exclusivamente a partir do VDI sem mídias residuais.

### 3.3. Integração com o Executor Central (`virtualbox_vm.py`)
- Adicionada a ação `'installation.reconcile'` a `VM_ACTIONS['vm:manage']`.
- Validação em `_validate` aceita apenas os campos autorizados `{'detach_storage', 'request_key'}`.
- Despacho em `_execute` encaminha para `reconcile_failed_attempt`.

### 3.4. Sequenciador Auditável e Resoluções dos 5 Apontamentos (`scripts/commander/debian_persistent_runbook.py`)
- Implementado orquestrador de 7 passos com suporte completo a `--dry-run` (padrão) e `--execute`:
  1. `reconcile`: reconciliação e arquivamento auditável da tentativa anterior com safe poweroff.
  2. `prepare`: geração do novo seed com o script corrigido e anexo de mídias SATA 2/3.
  3. `launch`: espera de prontidão observável no Debian Live, atraso de assentamento, registro de `launch-intent.json` e injeção de scancodes.
  4. `observe_installation`: observação contínua da VM até `poweroff` limpo. **Sem retry automático**: se houver timeout ou perda de observação, o status é registrado como `UNCERTAIN` e a execução para.
  5. `configure_disk_boot`: configuração de boot prioritário pelo disco e ejeção das mídias SATA 1, 2 e 3.
  6. `boot`: inicialização headless a partir do VDI persistente instalado e confirmação de estado `running`.
  7. `verify_guest`: probe autenticado via `guestcontrol` atestando `installed_os_verified`, `desktop_ready_verified` e `guest_channel_ready`.

- **Detalhamento das 5 correções pontuais integradas:**
  1. **Carregamento Real da Senha Dessilada (`load_dot_vm_config`):**
     - Conecta em `.sentra/durable/shell.sqlite3`, consulta a tabela `shell_dot_vms` por `vm_id`, dessela o campo `body` criptografado via DPAPI (`sentra_core.conversations._decode`) e obtém a credencial real da VM.
     - Falha fechada (`KeyError`) se a VM não for encontrada.
     - A senha é mantida exclusivamente em memória para injeção no template em base64 e **nunca é impressa em stdout, logs, relatórios ou recibos JSON**.
  2. **Desanexação Segura de Portas Não Hot-Pluggable:**
     - A reconciliação desliga e confirma a VM antes de qualquer `storageattach --medium none` em SATA 2/3, evitando a falha de anexos não dinâmicos observada no VirtualBox.
  3. **Espera de Prontidão Observável no Live (`GuestAdditionsRunLevel >= 1`):**
     - No Passo 3 (`launch`), antes de enviar scancodes, o sequenciador monitora `GuestAdditionsRunLevel` via `status()`.
     - Aguarda atingir nível $\ge 1$ com timeout configurável (`readiness_timeout=300s`).
     - Se o Live não subir a tempo, falha com `failed_not_started` **sem registrar `launch-intent.json`**, evitando deixar a VM em estado ambíguo.
     - Após atingir prontidão observável, aplica um atraso de assentamento (`settling_delay=35s`) antes de abrir o terminal virtual para evitar perda de keystrokes durante a transição do compositor XFCE.
  4. **Streaming de Hash da ISO:**
     - Implementado via `hashlib.file_digest(f, 'sha256')`, consumindo os 3 GB da imagem Debian Live em streaming via blocos de I/O em nível de kernel sem ler o arquivo todo em memória.
  5. **Confirmação de Running no Boot pelo Disco:**
     - No Passo 6 (`boot`), após emitir `startvm`, o orquestrador aguarda ativamente e valida que `VMState` atinge `running` antes de liberar o fluxo para o Passo 7 (`verify_guest`).

---

## 4. Testes e Contagem Real

1. **Suite Pytest da Frente P0-DEBIAN:**
   - Comando executado:
     ```powershell
     python -m pytest -q tests/unit/test_virtualbox_bootstrap.py tests/unit/test_virtualbox_installation.py tests/unit/test_virtualbox_diagnostics.py tests/unit/test_shell_dot_vm.py
     ```
   - **Resultado:** **56 passed in 53.34s**, exit code **0**.
   - **Evolução da contagem:** de 47 testes (baseline) para **56 testes** aprovados.
   - **Cobertura dos novos testes:**
     - `test_reconcile_accepts_only_empty_disk_with_matching_admission_and_preserves_files`: aceitação estrita em disco vazio, preservação integral de arquivos e emissão de `reconciliation.json`.
     - `test_reconcile_detach_storage_flag_executes_storageattach`: controle da flag `detach_storage` com poweroff seguro e verificação de desanexação SATA.
     - `test_reconcile_refuses_allocated_blocks_or_divergent_hash`: recusa fail-closed quando há blocos alocados (>0), partições, hash de admissão divergente ou foreign hardware UUID.
     - `test_reconcile_idempotence_by_request_key`: idempotência por chave de requisição em chamadas repetidas.
     - `test_install_script_contains_dmi_readback_and_autologin_group`: verificação de sintaxe de readback DMI, grupo `autologin` e ativação de serviços Guest Additions.
     - `test_runbook_dry_run_and_execute_simulation`: validação completa do runbook em modo dry-run e simulação de execução de todos os passos com emissão de recibos.
     - `test_launch_fails_without_recording_intent_when_live_readiness_times_out`: garantia de que timeout na prontidão observável do Live (`GuestAdditionsRunLevel < 1`) falha como `failed_not_started` e não grava `launch-intent.json`.
     - `test_load_dot_vm_config_unseals_credentials_and_fails_closed`: desselagem de credenciais da tabela `shell_dot_vms` via DPAPI e fail-closed com `KeyError` para VM inexistente.

2. **Compilação de Bytecode:**
   - Comando executado:
     ```powershell
     python -m compileall -q sentra_executors/virtualbox_bootstrap.py sentra_executors/virtualbox_installation.py sentra_executors/virtualbox_vm.py sentra_canvas/shell_dot_vm.py scripts/commander/debian_persistent_runbook.py tests/unit/test_virtualbox_bootstrap.py
     ```
   - **Resultado:** Exit code **0** (sem erros de sintaxe).

3. **Homologação Real do Runbook em Modo Dry-Run:**
   - Comando executado sobre o ambiente real:
     ```powershell
     python scripts/commander/debian_persistent_runbook.py --dry-run
     ```
   - **Resultado:** Exit code **0**.
   - **Recibo emitido:** `.sentra/durable/dot-vms/SENTRA-Dot-fcd974cfccdc5636/runbook-receipts/runbook-summary.json`
   - **Status reportado:** `DRY_RUN_PLAN_COMPLETE` em 0.44s.
   - **Preflight verificado no ambiente real:**
     - `vm_state: running`
     - `hardwareuuid_matches: true`
     - `disk_empty: true`
     - `allocated_blocks: 0`
     - `partition_table_observed: false`
     - `admission_disk_uuid_matches: true`
     - `admission_vdi_sha256_matches: true`
     - `bootstrap_exists: true`

---

## 5. Sequência Exata de Comandos da Fase 2 (Exigirá Autorização Humana)

A execução física da Fase 2 **NÃO foi iniciada** e só poderá ocorrer após autorização explícita do usuário. A sequência de passos e comandos operacionais que serão realizados pelo runbook (ou via executor central) é a seguinte:

### O que acontece com a VM Live em execução atual:
1. A VM atualmente em execução (`VMState=running`) está no ambiente Debian Live, com o script antigo falhado em memória e SATA 2/3 ocupados pelo seed anterior e GA.
2. Na etapa 1 (Reconcile), a VM Live é desligada de forma limpa (`controlvm poweroff`), as portas SATA 2/3 não hot-pluggable são desanexadas (`storageattach --medium none`), e a pasta `bootstrap` é movida para `bootstrap-attempts/1791808577-6fbb84c5/`.
3. Na etapa 2 (Prepare), confirmada em poweroff, a nova pasta `bootstrap` é criada com o novo `seed.iso` e mídias SATA 2/3 são anexadas.
4. Na etapa 3 (Launch), a VM é ligada via `startvm --type headless`, aguarda `GuestAdditionsRunLevel >= 1` mais o tempo de assentamento, registra `launch-intent.json` e envia scancodes para montar o novo seed e disparar a instalação.

### Sequência exata de execução na Fase 2:

```powershell
# Execução autorizada do runbook sequenciador:
python scripts/commander/debian_persistent_runbook.py --execute `
    --vm-id fcd974cf-ccdc-5636-b7af-2f96024d5dde `
    --vm-name SENTRA-Dot-fcd974cfccdc5636 `
    --marker "SENTRA-DOT:fcd974cf-ccdc-5636-b7af-2f96024d5dde" `
    --iso-path "Isos/debian-live-13.7.0-amd64-xfce.iso" `
    --base-folder ".sentra/durable/dot-vms" `
    --observe-timeout 1800 `
    --verify-timeout 180
```

Internamente, esta execução gerará a seguinte cadeia física estritamente auditada por recibos JSON:

1. **Passo 1 (Reconcile):**
   - Valida `inspect_vdi` (0 blocos alocados) e hashes de `admission.json`.
   - Executa `VBoxManage controlvm fcd974cf-ccdc-5636-b7af-2f96024d5dde poweroff` e confirma `VMState=poweroff`.
   - `VBoxManage storageattach fcd974cf-ccdc-5636-b7af-2f96024d5dde --storagectl SATA --port 2 --device 0 --type dvddrive --medium none`
   - `VBoxManage storageattach fcd974cf-ccdc-5636-b7af-2f96024d5dde --storagectl SATA --port 3 --device 0 --type dvddrive --medium none`
   - Confirma portas desanexadas.
   - Renomeia `.sentra/durable/dot-vms/SENTRA-Dot-fcd974cfccdc5636/bootstrap` para `bootstrap-attempts/1791808577-6fbb84c5`.
   - Emite: `01-reconcile.json`

2. **Passo 2 (Prepare):**
   - Reconfirma `inspect_vdi` e `VMState=poweroff`.
   - Cria nova pasta `bootstrap/` com `seed.iso` (script com readback DMI e autologin XFCE) e novo `admission.json`.
   - `VBoxManage storageattach fcd974cf-ccdc-5636-b7af-2f96024d5dde --storagectl SATA --port 2 --device 0 --type dvddrive --medium <novo-seed.iso>`
   - `VBoxManage storageattach fcd974cf-ccdc-5636-b7af-2f96024d5dde --storagectl SATA --port 3 --device 0 --type dvddrive --medium <VBoxGuestAdditions.iso>`
   - Emite: `02-prepare.json`

3. **Passo 3 (Launch):**
   - `VBoxManage startvm fcd974cf-ccdc-5636-b7af-2f96024d5dde --type headless`
   - Aguarda `GuestAdditionsRunLevel >= 1` com timeout de 300s + delay de assentamento de 35s.
   - Registra `launch-intent.json`.
   - Envia scancodes: Ctrl+Alt+F2 / login / montagem de `/dev/sr1` / execução de `sudo bash /mnt/sentra-seed/install.sh`.
   - Emite: `03-launch.json`

4. **Passo 4 (Observe Installation):**
   - Observa o status da VM até o shutdown automático programado (`systemctl poweroff` no final de `install.sh`).
   - Timeout de 1800s; em caso de encerramento prematuro ou timeout, marca `UNCERTAIN` e interrompe a sequência (sem retry).
   - Emite: `04-observe.json` (com `status=poweroff_confirmed`).

5. **Passo 5 (Configure Disk Boot):**
   - Comprova `VMState=poweroff` e VDI particionado (`inspect_vdi` com `partition_table_observed=True`).
   - `VBoxManage modifyvm fcd974cf-ccdc-5636-b7af-2f96024d5dde --boot1 disk --boot2 none --boot3 none --boot4 none`
   - `VBoxManage storageattach fcd974cf-ccdc-5636-b7af-2f96024d5dde --storagectl SATA --port 1 --device 0 --type dvddrive --medium none` (ejeção Live ISO)
   - Ejeção de SATA 2 (seed) e SATA 3 (GA).
   - Emite: `05-configure-disk-boot.json`

6. **Passo 6 (Boot):**
   - `VBoxManage startvm fcd974cf-ccdc-5636-b7af-2f96024d5dde --type headless` (boot a partir do disco persistente).
   - Confirma `VMState=running`.
   - Emite: `06-boot.json`

7. **Passo 7 (Verify Guest):**
   - Aguarda o guest inicializar, carregar o LightDM e o `VBoxService`.
   - Executa sonda fixa via canal autenticado `VBoxManage guestcontrol run`:
     - Validação de root `/dev/sda1` ext4 (não overlay).
     - Validação de `/etc/sentra-dot-vm-id == fcd974cf-ccdc-5636-b7af-2f96024d5dde`.
     - Validação de `display-manager` ativo e processo `xfce4-session` do usuário `sentra`.
   - Emite: `07-verify-guest.json` e `runbook-summary.json` com `status=SUCCEEDED`.

---

## 6. Estado de Homologação da Fase 1

- **Fase 1 (Código, Testes, Auditoria e Leitura):** **100% CONCLUÍDA E HOMOLOGADA** (56/56 testes aprovados).
- **Dry-run do Runbook:** Aprovado com `DRY_RUN_PLAN_COMPLETE`.

---

## 7. Execução Física da Fase 2 — Homologação Completa (12/10/2026)

Após autorização explícita do usuário, a sequência autorizada da Fase 2 (ordem **2 → 3 → 4 → 1**) foi executada fisicamente via `debian_persistent_runbook.py`.

### 7.1. Recibos Reais Emitidos em `.sentra/durable/dot-vms/SENTRA-Dot-fcd974cfccdc5636/runbook-receipts/`:

| Passo | Arquivo de Recibo | Status Observado | Evidência Chave |
|---|---|---|---|
| **1. Reconcile** | `01-reconcile.json` | `reconciled_failed_attempt` | VDI vazio (`allocated_blocks=0`), bootstrap anterior arquivado em `bootstrap-attempts/1791808577-6fbb84c5`, SATA 2/3 desanexadas com segurança |
| **2. Prepare** | `02-prepare.json` | `installation_seed_prepared` | Novo `seed.iso` gerado com script corrigido (readback DMI, autologin LightDM/XFCE4), anexado em SATA 2; GA em SATA 3 |
| **3. Launch** | `03-launch.json` | `installation_launch_sent` | VM iniciada headless, scancodes injetados após `GuestAdditionsRunLevel >= 1` e delay de assentamento |
| **4. Observe** | `04-observe.json` | `poweroff_confirmed` | `install.sh` particionou `/dev/sda1` (64 GiB), formatou ext4, instalou pacotes e GRUB no chroot, executando `systemctl poweroff` de desligamento limpo |
| **5. Configure Disk Boot** | `05-configure-disk-boot.json` | `disk_boot_configured` | Boot modificado para `boot1=disk boot2=none`, ISOs ejetadas de SATA 1, 2 e 3 |
| **6. Boot** | `06-boot.json` | `boot_running_confirmed` | VM ligada diretamente a partir do VDI persistente (`VMState=running`) |
| **7. Verify Guest** | `07-verify-guest.json` | `installed_guest_verified` | Sonda autenticada via `guestcontrol` com senha unsealed confirmou root `/dev/sda1` ext4, `SENTRA_LIVE=0`, `display-manager=active` e sessão `xfce4-session=running` |

### 7.2. Recibo de Verificação Final (`07-verify-guest.json`):
```json
{
  "boot_mode": "installed_disk",
  "desktop_ready_verified": true,
  "disk_uuid": "9cf5e721-7cbd-48e9-9634-d2d709c9cb68",
  "installed_os_verified": true,
  "mode": "verify-only",
  "name": "verify_guest",
  "root_source": "/dev/sda1",
  "root_uuid": "7a38b1c2-dbad-4e78-a53d-51fd75d3d89d",
  "started_at": 1791822295.7730281,
  "status": "installed_guest_verified",
  "vm_id": "fcd974cf-ccdc-5636-b7af-2f96024d5dde"
}
```

### 7.3. Resumo Consolidado do Runbook (`runbook-summary.json`):
- **Run ID:** `runbook-1791822295-d9d288`
- **VM ID:** `fcd974cf-ccdc-5636-b7af-2f96024d5dde`
- **Status Geral:** **`SUCCEEDED`**
- **VDI Final:** `system.vdi` expandido para ~10.083 MB (~9,84 GiB), particionado com `/dev/sda1` ext4 bootável.
- **Canal de Controle Convidado:** Operacional com `GuestAdditionsRunLevel=2` (VirtualBox Base Driver, System Service, Graphics Mode e Seamless Mode ativos).
- **Homologação P0-DEBIAN:** **100% HOMOLOGADA COM PROVA REAL PONTA A PONTA**.
