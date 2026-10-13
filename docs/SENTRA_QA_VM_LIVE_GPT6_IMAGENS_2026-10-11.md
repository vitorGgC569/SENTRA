# SENTRA QA: GPT-6 + mídia gerada + computador ao vivo (2026-10-11)

## Veredito

- **Computador no Canvas:** painel real `Computador → Desktop` abre; VM configurada do Dot é exibida, e o viewer mostra `Ao vivo · VM do Dot` e quadros contínuos quando recebe frames. **Confirmado no renderer com resposta de API simulada e framebuffer PNG real da QA Debian.** A VM `testegpt6` física continua `not_created`; logo, não há homologação do streaming da própria VM desse Dot no momento.
- **Rebind após reinício:** `sentra_canvas/shell_dot_vm.py::status` re-registra o executor host da VM persistida com identidade/workitems existentes, sem start/retry físico; teste específico aprovado. `shell-dot-computer.jsx` usa o Dot selecionado, inclusive Dot filho. Interface atualizada com status de streaming.
- **GPT-6 agindo sozinho na VM:** **NÃO confirmado**. Duas tentativas recentes do `testegpt6` terminaram `UNCERTAIN` por entrega incompleta do gateway; não há recibo de vm_create, vm:observe ou vm:input emitido pelo modelo. Não executar efeitos baseando-se em diretivas textuais de respostas não confirmadas.
- **Imagem gerada pelo ChatGPT Web entregue ao Canvas:** **NÃO implementado**. `conversation-evidence.js` rejeita rich-media assistant parts, `shell_web.observe` publica texto com final attestado, `ConversationMarkdown` não tem suporte binário. Um caminho autenticado de upload de mídia dependeria de coletor de browser verificado, associação ao ID original da mensagem, armazenamento cifrado, recibo e viewer. O caminho de coleta não pôde ser concluído sob as restrições de segurança; nenhum endpoint parcial foi deixado ativo.

## Evidência técnica

- Teste físico de Debian do turno anterior: `.tmp/sentra-debian-gui-validation-20261011/after_ctrl_alt_t.png` e `qa.json`. Entradas COM enviadas para a VM isolada e terminal XFCE aberto.
- Teste de UI real sem mock: `.tmp/qa-dot-computer-headless.png`. Playwright/Edge abriu `/desktop.html`, entrou na conversa do `testegpt6` e clicou `Computador`. A VM apresentava `not_created`, sem vídeo.
- Teste de UI com API `dot_vm_status`/`dot_vm_frame` simulada e PNG real: `.tmp/qa-dot-computer-live-mocked.png`. Canvas montou imagem, indicador `Ao vivo` e consultou 2 frames. **Não alegar VM física ativa.**
- A reserva anterior do Dot `testegpt6` ainda estava em 2 vCPU/4096 MiB apesar de `not_created`; o provisionamento anterior permanece `UNCERTAIN`. Não houve reenvio automático, remoção de reserva nem criação física da VM nesta rodada.

## Alterações aplicadas nesta rodada

1. `sentra_canvas/shell_dot_vm.py`: rebind do executor persistido durante status no contexto autenticado do mesmo Dot.
2. `sentra_canvas/desktop_ui/src/shell-dot-computer.jsx`: Dot selecionado como identidade do painel.
3. `sentra_canvas/desktop_ui/src/shell-dot-vm.jsx`: indicador condicional `Ao vivo` só após frame real `status=live`.
4. `tests/unit/test_shell_dot_vm.py`: teste de rebind de VM após reinício lógico do executor.
5. Build do Canvas concluído. Após verificar zero operações ativas, a instância local foi reiniciada; broker disponível na porta 64621, `dot_vm_status` responde e indica `not_created` com reserva persistida de 2 vCPUs/4096 MiB. Nenhuma VM ficou registrada.

## Limites e segurança

- **Não** foi realizada alteração do conteúdo do computador do usuário via Dot nesta rodada.
- **Não** foram criados novos Grants nem reexecutadas operações incertas.
- Não transformar SSE truncado em `response.completed` sem prova final, não tentar download de URL de mídia não autorizada, não divulgar Base64.
- O browser real não consegue exibir tela de VM inexistente; o clique abre o viewer, não inicia automaticamente a VM (iniciar é efeito físico separado).
- Para homologação integral restante, são necessárias as duas provas físicas faltantes: resposta Web GPT-6 final autenticada contendo operações CANVAS com WorkItem válido; mídia gerada real, coletada e entregue ao renderer pelo relay com ID e bytes confirmados.

## Testes

- `pytest -q -p no:cacheprovider tests/unit/test_shell_dot_vm.py`: 10 passed.
- Primeira regressão combinada de 8 módulos: 41 passed, 1 failed por corrida `UNIQUE canvas_shell_provider_bindings.conversation_id` na fixture de `test_shell_actor_children`. O teste passou isoladamente (1 passed). **Segunda execução combinada: 42 passed em 63,07 s**, confirmando caráter intermitente da falha anterior.
- `npm run build`: concluído.
