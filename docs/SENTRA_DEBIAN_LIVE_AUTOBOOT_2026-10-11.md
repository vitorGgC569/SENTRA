# QA SENTRA Debian Live — 2026-10-11

Diagnóstico: o Dot Testando Advanced tem a VM fcd974cf-ccdc-5636-b7af-2f96024d5dde, que estava em running no menu Debian Live system (amd64). Outra VM (1f5d0f3b-02e9-5e17-b5a5-adfb1336a819) pertence ao Dot testegpt6. As duas VMs são diferentes; não foi comprovada duplicação física de uma mesma VM.

Correção no executor sentra_executors/virtualbox_vm.py: reconhecer visualmente o menu Debian Live em imagem real do framebuffer e enviar somente um Enter, com efeito centralmente autorizado, no provisionamento e no próximo start. Sem reconhecimento positivo não enviar entrada; não inferir instalação concluída.

Correção sentra_canvas/shell_dot_vm.py: VmStore.policy não bloqueia o controle humano de vm:input; InputBoundPolicy verifica a posse humana/agente e epoch. Falha real 403 de entrada humana identificada e protegida por teste.

Correção sentra_canvas/shell_actor.py: vm_create sobre VM física registrada e vinculada retorna existing_vm, sem novo provisionamento; próximo passo é vm_frame/vm_input. Rebind de conversa pode cadastrar seu WorkItem sem provisionar uma VM que já existe.

Validação: 36 testes aprovados em VM/CLI/actor, quatro testes finais críticos aprovados, compileall e git diff --check aprovados. Frame real observado em .tmp/sentra-live-debian-menu-observed-20261011.png. Classificador reconheceu menu real e rejeitou captura do desktop XFCE.

Execução física do Enter desta sessão: um handoff para controle humano foi realizado, mas o Enter recebeu 403 antes da admissão física e não criou operação Durable; o menu permaneceu intacto. Não foi repetido. O host journal desse pedido permanece marcado uncertain por seu tratamento conservador.

Deploy: NÃO efetuado. Primeira tentativa de reinício foi recusada por operação ativa. Uma segunda tentativa foi bloqueada pelas configurações de segurança da ferramenta; não se tentou contorná-las. As duas VMs permaneceram em execução, e o processo já aberto requer um reinício autorizado, quando o usuário puder fazê-lo sem trabalho ativo, para carregar o novo código.

Distinção: Debian Live sem instalação persistente não garante retenção de mudanças no disco. Para persistência é preciso uma VM instalada/preparada, não apenas autoescolher Live no menu.

Nenhum commit, push, reset, exclusão de VM ou reenvio de operação UNCERTAIN.
