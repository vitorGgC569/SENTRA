# Auditoria e correções: VM por Dot, ISOs e aprovação de coordenação

Data: 2026-10-11. Checkout compartilhado: as mudanças foram feitas sem commit, push ou reset.

## Alterações

- `sentra_cli/agent.py`: montagem de screenshots multimodais não exige que instâncias mínimas de teste tenham inicializado `_vm_frame`.
- `sentra_executors/virtualbox_vm.py`: detecção real de ISO com os nomes de campos retornados pelo VirtualBox 7.2 e a falha parcial `E_NOTIMPL`. Na detecção parcial, o executor pode criar a VM e iniciar o instalador pela ISO local, sem afirmar que a instalação desassistida terminou; `os_ready_verified=False`.
- `sentra_canvas/shell_dot_vm.py`: escopo por Dot e conversa específica (inclusive filhos); reserva agregada de até 50% de vCPUs/RAM configuradas; listagem segura de ISOs existentes no subdiretório `Isos` do workspace; validação de Run ativo antes da reserva.
- `sentra_canvas/desktop_ui/src/shell-dot-vm.jsx`: escolha de ISOs identificadas no projeto, sem baixar imagens automaticamente.
- `sentra_runtime/coordinator_approvals.py`: inbox durável por projeto para `waiting_approval`, sem criar Grants no momento da solicitação.
- `sentra_runtime/coordinator_admission.py`: publica os bloqueios reais de coordenação nesse inbox, mantendo operação e conversa originais.
- `sentra_canvas/shell_approval_inbox.py`, `service.py`: endpoints do owner para consultar, aprovar ou rejeitar. Aprovação valida novamente Dot, conversa, Space, WorkItem, operação ativa e capability declarada; autoriza apenas o turno original, sem reexecução automática.
- `shell-approval-notifications.jsx`, `shell-app.jsx`, `shell-bridge.js`, `desktop.css`: aviso persistente sobreposto à interface, polling sem autoaprovação, respostas explícitas e descarte de pedidos expirados.

## Homologação de ISOs (VirtualBox 7.2.20)

Originais mantidas em `Isos`:
- `debian-live-13.7.0-amd64-xfce.iso`: detectado como Debian, versão 13.7.0 XFCE.
- `Windows.iso`: detectado como `Windows10_64` / versão 2004 / idioma pt-br.

O comando de detecção do VBoxManage neste host retorna `E_NOTIMPL` junto com `OSTypeId` e `IsInstallSupported=on`. O executor agora interpreta o resultado como detecção parcial e utiliza boot pela ISO para instalação manual, sem relatar falso sucesso da instalação desassistida.

O smoke test de boot usou **VMs descartáveis**, uma por vez, com **2 vCPUs/4096 MiB**, rede desconectada, clipboard e drag & drop desativados. Para cada ISO: cria/register VM, configura disco virtual, monta a ISO, inicia o monitor headless, verifica `VMState=running`, captura PNG real pela CLI **e pela API COM real do VirtualBox** (`virtualbox-com-framebuffer`), verifica ownership e executa `unregistervm --delete`. Os arquivos originais não são modificados.

O smoke adicional confirmou quadro COM de **640×480 no Debian** e **1024×768 no Windows**, e registrou o resumo em `.tmp/sentra-vm-iso-qa-20261011/report.json`.

**Limite da evidência:** boot/headless/PNG não é prova de sistema operacional instalado no disco, login do usuário, Guest Additions, rede convidada funcional, controle da interface pelo agente ou interpretação da tela pelo modelo. Validar isso requer um teste integral adicional, com ações de mouse/teclado e recibos reais.

## Segurança e pendências

- Uma solicitação `waiting_approval` anterior à instalação da nova lógica **não** possui ticket retroativo: não forjar nem autorizar o histórico automaticamente.
- Uma autorização de coordenação concedida **não** repete o comando original. Se a operação pai terminou, o pedido aparece como expirado e o usuário deverá fazer uma nova solicitação após revisão.
- O recurso de VM reserva quantidade de vCPU/RAM, não garantia de utilização real máxima do processador.
- Falta validar o ciclo inteiro de instalação dos dois convidados, boot no disco, registro no Dot, framebuffer COM pela interface, interação agente/humano e limpeza automática na exclusão de um Dot.
- Menu contextual completo de Dots com remoção, arquivamento do GPT e limpeza de VMs ainda não foi tratado neste conjunto de alterações. Não apagar Dots/VMs até que o fluxo faça reconciliação com confirmação real dos efeitos externos.

## Testes

- `pytest -q -p no:cacheprovider tests/unit/test_shell_coordinator_approval_inbox.py tests/unit/test_shell_dot_vm.py tests/unit/test_sentra_shell_live_preview.py`: 13 passaram.
- `pytest -q -p no:cacheprovider tests/unit/test_shell_coordinator_approval_inbox.py tests/unit/test_shell_dot_vm.py tests/unit/test_sentra_shell_live_preview.py tests/unit/test_shell_actor_children.py tests/unit/test_cli_vm_frame_multimodal.py tests/unit/test_shell_web_preview.py tests/unit/test_shell_dot_computer.py`: 39 passaram.
- `npm run build` do desktop UI: sucesso, com avisos preexistentes de scripts legados sem `type=module` e tamanho de bundle.

Sem teste de execução nova do GPT Web ou concessão real de permissão pelo owner durante esta rodada.
