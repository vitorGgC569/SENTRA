# SENTRA: recuperação real do boot Debian do Dot

## Resultado físico

A VM existente do Dot **Testando Advanced**, UUID `fcd974cf-ccdc-5636-b7af-2f96024d5dde`, chegou à área de trabalho Debian XFCE em 1280×800. Todas as entradas e o reinício passaram pelos endpoints autenticados do SENTRA e pelo executor central. O disco, o UUID e a outra VM do Dot testegpt6 foram preservados.

Evidência: `.tmp/owned-vm-kernel-parameters-boot-later.png` mostra Applications, Home, File System, Trash e Install Debian. É **Debian Live**. Isso não confirma instalação persistente no VDI, Guest Additions, login sentra, execução por guestcontrol nem controle autônomo pelo GPT Web.

## Diagnóstico e execução

- Controle humano temporário, Ctrl+Alt+F2 enviado uma vez e controle devolvido: recibo físico `op-shell-ac054dbc9939bdea610495a62f639522c54f78a2`, SUCCEEDED. Console mostrou RCU stalls e ausência de wakeup de timer. O VBox.log confirmou fallback AMD-V → NEM com Hyper-V/WHv presente. O aviso vmwgfx sozinho não foi usado para afirmar causa fatal.
- Reinício controlado da VM existente: `op-shell-ee3981644885328e9978f958bc4e34bde2a6502e`, SUCCEEDED. Pré-condição verificou zero operações ativas do owner canônico `canvas:vitor`. Uma operação de outro owner mcp-direct/e2e permaneceu intacta.
- Menu Debian selecionado observado no framebuffer. Tab abriu a linha de boot real, depois foram acrescentados `tsc=unstable clocksource=acpi_pm nohz=off maxcpus=1` em lotes de no máximo 32 scancodes, todos com recibos SUCCEEDED. A imagem confirmou a linha antes de um único Enter. Controle devolvido ao Dot, epoch 13.
- Aos 20 segundos ainda havia tela de kernel; captura posterior confirmou o desktop XFCE. Os quatro parâmetros foram testados juntos: a evidência não identifica qual deles resolveu isoladamente o travamento.

Journals: `.tmp/owned-vm-tty-diagnosis.json`, `.tmp/owned-vm-controlled-restart.json`, `.tmp/owned-vm-kernel-boot-edit.json`. Nenhuma intenção incerta anterior foi repetida. O diagnóstico inicial esperou incorretamente um campo state no retorno de handoff; a posse foi reconciliada por consulta do recibo autenticado persistido, sem repetir o handoff.

## Código

- `virtualbox_vm.py`: `vm:manage restart` só reseta uma VM running com UUID e marker verificados. `vm:observe diagnostics` apresenta flags de backend, Guest Additions e estado de instalação desconhecido, lendo somente o log dentro da pasta dessa VM.
- Bootstrap Debian 13 Live em Hyper-V/NEM: confirma menu selecionado, envia Tab uma vez, aguarda o editor Syslinux reconhecido, acrescenta os parâmetros fixos e envia Enter uma vez. Repaint é observado sem repetir entradas. Sem editor confirmado ou após falha ambígua, não envia novas teclas automaticamente. Outros sistemas/hosts mantêm o fluxo anterior.
- A projeção `existing_vm` após vincular uma nova conversa não desativa mais a seleção visual do menu no próximo start.
- `VmStore`: atualizações do mapa de WorkItems por conversa são transacionais e preservam vínculos concorrentes. Conversas do mesmo Dot reutilizam a VM, mas possuem WorkItems e acesso efetivo separados.

As reservas continuam em 2 vCPUs por VM, 4 vCPUs/8192 MiB agregados. `maxcpus=1` limita o kernel neste boot a uma CPU ativa e não muda a reserva configurada. O limite agregado de 50% é de configuração, não garantia da utilização real do host.

## Validação e limites

- 23 testes combinados de VM/diagnóstico passaram; após a última alteração, os 7 testes de diagnóstico/restart/bootstrap passaram novamente. Dois testes específicos de reutilização por conversa e atualização transacional também passaram.
- Os classificadores reconheceram o editor de boot real e rejeitaram a captura real do desktop. Compilação Python passou.
- O caminho automático de bootstrap foi testado com clientes controlados; o boot físico desta rodada foi executado em passos autenticados com revisão de frames. Não foi feito outro reboot só para repetir a prova.
- A instalação persistente Debian e a homologação Windows continuam pendentes. Nenhum disco foi formatado, nenhuma VM foi recriada, e Hyper-V do host não foi alterado.

Referências: [parâmetros oficiais do kernel Linux](https://cdn.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html), [relato upstream de stalls RCU no VirtualBox](https://github.com/VirtualBox/virtualbox/issues/861). São referências de diagnóstico; não substituem os recibos e frames deste host.
