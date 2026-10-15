# Proposta — abertura rápida de conversas com custo limitado

Proposta para revisão do coordenador antes de implementação. Nenhuma mudança de backend adicional nem cache de conteúdo foi aplicada nesta etapa.

## Evidência e fronteira

O `shell-session-cache.js` atual mantém metadados visuais de Home em sessionStorage por 120 s, com allowlist e teto de 26 mil caracteres; exclui mensagens, conteúdo, operações e permissões. Essa fronteira deve permanecer intacta. Mensagens em disco já pertencem ao ConversationStore protegido: não introduzir IndexedDB/plaintext, arquivo paralelo, Redis ou serviço externo.

O coordenador mediu 9 leituras HTTP reais de 3 conversas curtas (7–10 mensagens), com aproximadamente 55–170 ms sob carga compartilhada; recibo `.tmp/astra-conversation-read-latency.json`. Isso mede leitura, não tempo completo até chat pintado, e indica que há custo de orquestração/requisições/renderização além do banco.

## Desenho exato proposto

1. Módulo privado por janela com LRU de **até 8 conversas, 4 MiB de bytes UTF-8 serializados e TTL de 5 minutos**. Chave estrita projeto/Space/conversa dentro da sessão autenticada daquela janela. Nova navegação nativa/renovação de owner descarta o módulo. Evicção por bytes e quantidade; entrada acima do orçamento não entra.
2. Guardar somente a última página de até 50 mensagens **canônicas já recebidas**: identidade de exibição, papel, conteúdo/preview, timestamp e referência de conteúdo protegido quando existente. O cache nunca recebe bearer, Grants, permissões, rascunhos pending, ações ou estado de operação/recibo como autoridade. Não truncar conteúdo silenciosamente para caber: conservar o preview declarado pelo servidor ou recusar a entrada.
3. Ao abrir, pintar essa página imediatamente em apresentação **explicitamente visual**, separada do array canônico usado por reconciliação. Os controles de execução e recibos dependem da leitura autenticada atual; a presença no cache não limpa pending, não confirma resultado, não envia nada nem contorna a resolução canônica de conversa.
4. Revalidar **em paralelo** a entidade via conversation_get e a página recente via o contrato `message_tail` que a frente de streaming está preparando. O tail substitui as duas leituras sequenciais offset0→total→última página para conversas longas. Seletores/cursor vêm do host; reabrir não inicia uma tarefa nem repete prompt.
5. Quando a página autenticada chegar, substituir a visual preservando âncora de leitura. Pendências continuam no fluxo `message_request_status`. Erro de leitura deixa “visualização anterior; reconectando”, sem promover cache a recibo. 401/403/404/fora de escopo descarta a visualização e a entrada. Eventos de exclusão/revogação invalidam a entrada; mudança de projeto só lê chave do projeto correspondente.
6. Medir sem texto/IDs sensíveis: clique→primeira pintura visual, clique→entidade canônica, clique→página autenticada, hit/miss/evicções/bytes e número de requisições. Comparar frio/quente, conversa curta/longa, troca rápida, rede lenta e owner/projeto diferentes. Limitar o claim de ganho ao escopo medido.

## Cuidados de integração

- Não colocar mensagens no Home cache existente; compartilhar apenas o padrão de allowlist/TTL em um módulo RAM separado.
- Corpo visual em cache não deve montar SentraInteractiveUi executável nem links de ação; usar renderer de leitura ou inert até revalidação. Deve ser possível ler a visualização sem ela alterar autorização.
- Um cache RAM expira ao fechar/recarregar: esse limite é deliberado. A retomada durável continua no armazenamento protegido e no journal/SSE existente.
- `message_tail` é a única extensão de backend em estudo nesta proposta; implementação e semântica de paginação reversa pertencem à frente de streaming. Se o contrato atrasar, o cache RAM pode acompanhar as leituras atuais, mas não alegar redução de requisições.
