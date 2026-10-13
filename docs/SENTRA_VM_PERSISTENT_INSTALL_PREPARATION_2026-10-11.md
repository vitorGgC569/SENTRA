# Preparação conservadora de OS persistente por Dot

## Evidência física somente leitura

No Dot Testando Advanced, o único disco rígido anexado é o VDI próprio `system.vdi`, SATA porta 0/dispositivo 0, UUID `9cf5e721-7cbd-48e9-9634-d2d709c9cb68`, usado pela VM `fcd974cf-ccdc-5636-b7af-2f96024d5dde`.

O VirtualBox mostra base dinâmica de 64 GiB e arquivo de 2 MiB. A leitura do header e do **mapa inteiro** VDI v1.1 confirmou identidade correspondente, ausência de parent/differencing disk, 65536 blocos, zero blocos alocados e metadados estáveis durante a leitura. Nenhuma tabela de partições foi observada. Registro: `.tmp/owned-vdi-installation-readonly.json`.

Isso comprova disco virtual observado vazio naquele momento; não autoriza uma futura formatação sem nova admissão e nova verificação. O Debian XFCE atualmente running continua **Live**, com GuestAdditionsRunLevel 0. Nesta rodada não houve entrada, instalação, formatação, desligamento, reinício ou alteração da VM/host.

## Implementação preparada

`sentra_executors/virtualbox_installation.py` acrescenta:

- `installation.plan`, capability `vm:observe`: valida UUID/marker da VM, sua pasta registrada, um único VDI próprio SATA0, UUID do medium/header, capacidade, base sem parent e mapa estável. Diferencia disco vazio, dados e partições. Nenhum desses estados é tratado como OS instalado.
- `installation.verify`, capability `vm:guest`: probe fixo pelo canal autenticado guestcontrol. Para Linux requer VDI particionado, root ext4 em `/dev/sdaN`, UUID de filesystem, ausência de Live/overlay e identidade `/etc/sentra-dot-vm-id` correspondente à VM. Só confirma desktop instalado se display manager e sessão XFCE do usuário sentra também estiverem ativos. Aceitar uma resposta de texto arbitrária do modelo não produz essa prova.
- `installation.boot_disk`, capability `vm:manage`: exige VM própria poweroff e VDI estável particionado. Define disco primeiro e remove a ISO da unidade virtual. Não formata, não cria VM, não inicia e não afirma que o OS já está instalado ou pronto.
- Templates de revisão para Debian Installer e pós-instalação: só preparados para preflight de Linux poweroff e disco vazio. Fixam o destino virtual, XFCE, identidade, autologin LightDM e parâmetros GRUB conhecidos. A senha é um placeholder de hash SHA512 a ser substituído privadamente pelo VirtualBox, que já oferece esse recurso localmente. Nenhum arquivo de respostas com senha foi escrito.

No `DotVmServices.dispatch`, a verificação de instalação usa `vm:guest`. As declarações permitem ainda o caminho genérico machine_execute com a capability correspondente. Os campos dos novos comandos são fixos: o renderer não seleciona outro UUID, caminho de disco ou script de verificação.

Correções verificadas no host: DeviceType HardDisk é 3, DVD é 2; chaves quoted de showvminfo, como SATA-ImageUUID-0-0, agora são normalizadas pelo parser.

## O que falta para instalar automaticamente

O prepare retorna `prepared_not_applied` e `automatic_installation_ready=False`. Falta admitir e implementar a entrega dos templates/Guest Additions a um instalador real e observar sua conclusão. A ISO Debian Live atual oferece Calamares/entrada Debian Installer, enquanto a detecção VirtualBox 7.2.20 retornou E_NOTIMPL. Iniciar Live ou detectar uma ISO não equivale a executar instalação desassistida.

O canal guestcontrol ainda não existe no Live atual. A interação gráfica COM funciona e não depende dele, mas não substitui uma prova de root persistente e de login instalado. É preciso instalar no disco virtual exclusivo, estabelecer usuário/canal convidado, desligar de forma confirmada, configurar boot no disco, iniciar e verificar novamente identidade/root/desktop. Essa sequência física não foi executada nesta preparação.

Linux: o boot Live recuperado foi testado com `tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1`; o template permite manter esses parâmetros no GRUB instalado. A verificação implementada cobre root ext4 direto em SATA, XFCE e sentra. Layouts LVM/Btrfs/criptografados exigem outro contrato de verificação e não são presumidos válidos.

Windows: a ISO local foi detectada como Windows10_64 versão 2004/pt-br na homologação anterior. O caminho de provisionamento/boot existe, mas instalação persistente e canal Windows **não** foram homologados. A verificação de instalação retorna explicitamente windows_verification_pending. O template Linux não é aplicado a Windows. O branch Windows 11 exige firmware/TPM2 e mínimos configurados, sem constituir prova de instalação física desse sistema.

## Testes

- Conjunto VM + diagnóstico + instalação: 37 passaram.
- Após os últimos ajustes: 13 testes de instalação passaram; compileall passou.
- Cobertura: VDI vazio e completo, identidade alterada, differencing image, múltiplos discos, caminho estrangeiro, preflight sem efeitos, boot apenas poweroff/particionado, rejeição Live/overlay/guest diferente, credentials via stdin, script fixo e preparação sem aplicação.
- A leitura real validou COM attachments e o mapa do VDI. Não houve teste de instalação/reboot persistente, pois nenhum disco foi formatado nesta rodada.

Referências primárias: [formatos VDI no código Oracle](https://raw.githubusercontent.com/VirtualBox/virtualbox/master/src/VBox/Storage/VDICore.h), [imagens Live oficiais Debian](https://www.debian.org/CD/live/index.html), [preseed Debian Installer](https://www.debian.org/releases/trixie/amd64/apbs04.en.html), [LightDM no Debian](https://wiki.debian.org/LightDM). Os templates instalados do próprio VirtualBox foram inspecionados localmente.
