# QA SENTRA: Dot GPT-6, Debian Live, imagem gerada e regressões (2026-10-11)

## Escopo e segurança

Testes no workspace Oxta, com solicitações persistidas e **sem reenvio de operações UNCERTAIN**. A VM COM de QA foi identificada por UUID/marker próprio, teve rede e clipboard desativados e foi excluída após verificação. Não houve commit, push, reset ou execução autônoma confirmada do Dot dentro da VM.

## Dot GPT-6: tentativa real

- Conversa original autorizada (`conversation-f1cbcab025460bcfed5f2fd9fa315c29`): requisição `op-d40682e4ff8421f6ebd12c423ed3509f` terminou UNCERTAIN; o journal já tinha outra operação incerta.
- Outra conversa autorizada, antes com journal `completed` (`conversation-b7c076c7e837c7e4177554b6a68c3d7d`): `op-27d23b44d50566f5712ee74bcf389c2c`, o Dot apresentou plano e consultas `[[CANVAS|vm_status]]`/`[[CANVAS|machine_list]]` como texto Markdown. Não há recibo de `vm_create` nem uso de `vm:input` por esse Dot; seu journal terminou incerto com `gateway: transport error: response stream ended before completion`.
- Estas duas tentativas **não provam controle da VM pelo GPT Web** e não foram reenviadas.

## Provisionamento via Control Plane

- Ação real autorizada `dot_vm_configure` na conversa QA criou configuração `1f5d0f3b-02e9-5e17-b5a5-adfb1336a819`, WorkItem `vm-10b89cb8650a56cfae0dc4f6f2f4efd5`, reserva de **2 vCPUs/4096 MiB** sob orçamento 6 vCPUs/15926 MiB.
- Operação de provisionamento `op-shell-37507c56bea5e532f5b0adf00b044e63836ac17e` encerrou `UNCERTAIN / physical_effect_error_requires_reconciliation`. O inventário físico subsequente mostrou **nenhuma VM VirtualBox registrada**. Não ocorreu retry dessa Operation e a reserva permanece até reconciliação autoritativa.
- Defeito identificado e corrigido em `sentra_executors/virtualbox_vm.py`: `VBoxManage createvm` aceita `--ostype`, não `--os-type`. Para a ISO Debian `amd64`, o tipo de convidado passou a `Debian_64`. Teste com client simulado protege a linha de comando.
- `shell_dot_vm.py` agora marca futuras tentativas que retornem UNCERTAIN como `uncertain_requires_reconciliation`, e `shell-dot-vm.jsx` exibe aviso e bloqueia novas criações enquanto houver essa marcação. A tentativa já incerta desta rodada precedeu a atualização do código e **não foi apagada, repetida ou marcada como sucesso**.

## Teste físico independente, sem atribuir execução ao Dot

Script de QA descartável `.tmp/sentra_debian_com_input_qa_20261011.py`:
1. VirtualBox 7.2.20, VM única com 2 vCPUs/4096 MiB, 32 GiB, rede desconectada.
2. `VirtualBoxClient.frame` capturou o menu do Debian.
3. `VirtualBoxClient.input` enviou Enter (`0x1c,0x9c`) e iniciou o Debian 13.7 XFCE Live.
4. O framebuffer apresentou área de trabalho XFCE em 1280×800, com ícones Home, File System, Trash e Install Debian.
5. `VirtualBoxClient.input` enviou Ctrl+Alt+T: screenshot final confirma terminal gráfico `user@debian:~$` e desktop XFCE em 1280×800.
6. VM identificada, desligada e removida por `unregistervm --delete`.
 
Evidências: `.tmp/sentra-debian-gui-validation-20261011/after_enter_60s.png`, `after_ctrl_alt_t.png`, `qa.json`. Teste físico **não é** prova de que o modelo tenha visto essas imagens nem interagido sozinho.

## Imagem gerada: causa de não entrega

O fluxo `native_bridge/shell_multimodal.py`/`web_history_assets.py` aceita arquivos que o **usuário envia ao GPT**; as imagens recebidas desse lado têm 8 MiB de limite. Em contraste, `sentra_canvas/shell_web.py::observe()` retorna somente `content: str`, e `ShellRuntime._publish_answer` registra apenas texto e recibos. Não há, nessa implementação, um transporte binário autenticado/confirmado para **imagens geradas pelo GPT Web e devolvidas ao Canvas**.

**Estado:** problema reproduzido conceitualmente no contrato/código, mas não foi possível produzir prova de download/envio ponta a ponta via conta ChatGPT Web. Não confundir geração remota com anexo local entregue. Uma correção completa requer coleta autenticada da mídia, metadados e bytes validados, armazenamento isolado, recibo e renderização de anexo. Não tentar inferir arquivo de uma URL não autorizada.

## Outras validações

- Testes direcionados de VM, screenshots multimodais, caixa de aprovações, anexos/histórico protegido e diagnóstico de entrega: **32 passed** após atualizar limites esperados de testes antigos ao contrato atual (PDF até 20 MiB, imagem até 8 MiB, histórico até 800000 bytes). Foi adicionada cobertura que mantém UNCERTAIN no provisionamento, sem liberar reservas ou alegar VM pronta.
- Screenshots via COM real demonstram caminho gráfico funcionando fora do modelo. Model tool calls e entrega multimodal do GPT Web **não homologados**.
- Pendente: reconciliação explícita do provisionamento UNCERTAIN e reserva VM, instalação persistente Debian, grants e ownership na execução do Dot, retorno real de imagens produzidas pelo GPT, e validação com conta Web funcional.
