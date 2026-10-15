# QA isolado — abrir conversa e enviar turno

Ensaio em `tests/qa/astra_chat_turn_browser.py`, fixture `sentra_canvas/desktop_ui/qa/chat-turn.html` / `.jsx`. Usa **OpenDotsShell, ShellConversation, shellBridge e api de produção**, com transporte fetch encaminhado para um **servidor HTTP real em loopback e porta temporária**. O servidor simula recibos e mensagens; nenhuma conta, modelo, runtime instalado ou dado real é tocado. A simulação não prova autorização nem execução produtiva.

Recibo completo: `.tmp/astra-chat-turn-qa/report.json`. Capturas por cenário no mesmo diretório. Após as correções descritas abaixo, **os 12 cenários passaram, exit 0**. Os defeitos da seção histórica foram efetivamente reproduzidos antes da correção.

## Percursos aprovados

- `immediate`: cria uma conversa, recebe identidade canônica, abre o chat, habilita envio após digitar, envia exatamente um POST `message_send` e recebe uma resposta sintética.
- `lost_creation`: o HTTP fecha sem resposta **depois** de persistir a criação. A consulta `conversation_request_status` usa a chave original, limpa a pendência e abre a conversa. Não há segunda criação. Em seguida, um turno novo funciona.
- `restored_draft`: um `pending` sintético restaurado é consultado via **message_request_status** com a chave antiga. Só o recibo confirmado libera o composer; nenhum `message_send` com aquela chave é enviado. Um turno novo usa nova chave.
- `selected_in_home`: com mais de 50 conversas e primeira página sem a conversa recém-criada, **se o home contém a conversa selecionada**, refresh/eventos mantêm o chat e o envio funciona.
- `pending_missing`, `pending_uncertain`, `pending_rejected`: consultar envio chama apenas `message_request_status`, sem conteúdo nem anexos. Pending/chave originais e composer bloqueado são preservados; zero `message_send`.

## Falhas reproduzidas na fonte atual

1. **Warm cache não é realmente inert.** `inert={warmVisual ? '' : undefined}` gera aviso do React 19: string vazia em atributo booleano é tratada como false. Antes de home autoritativo, `main.inert === false`, atributo ausente e textarea não desabilitada. Após home, o composer também funciona. Isso é falha de contenção da visualização em cache, **não uma reprodução do bloqueio atual do usuário**. Correção proposta: usar booleano `inert={warmVisual}`. Não alterei esta linha sem a revisão do coordenador.
2. **Conversa selecionada pode desaparecer com paginação.** `paginated_create`: com 60 conversas, criação canônica abre inicialmente; se home e conversation_list depois mostram apenas as 50 mais antigas, o refresh de eventos substitui a coleção e remove a conversa selecionada. A textarea deixa de existir. `outside_first_page`: navegação restaurada para conversa canônica fora da primeira página nunca resolve o chat.

As duas falhas de paginação **não explicam por si sós a última criação real** que o coordenador confirmou presente tanto no home quanto na primeira página. O caso equivalente `selected_in_home` passou. Não há base para declarar que a causa real foi encontrada sem observar o estado efetivamente carregado.

Correção proposta para paginação: resolver a conversa selecionada por leitura canônica pontual e escopada (`conversation_get` com projeto/Space/conversation), independente de páginas de catálogo. Preservar a identidade canônica confirmada enquanto essa consulta é feita; exclusão/fora de escopo deve produzir estado explícito, nunca criação/reenvio automático. Apenas reter eternamente uma linha antiga de catálogo esconderia revogações/exclusões.

## Wiring de consulta segura implementado

`shell-conversation.jsx` agora usa os helpers `inspectMessageRequest` e `confirmedMessageRequest` fornecidos pela frente de streaming. O botão “Consultar envio” e o caminho de compatibilidade `send(true)` consultam somente `message_request_status`. Um rascunho restaurado encontrado no histórico dispara uma consulta somente de leitura e só é liberado após confirmação do recibo. Ausência, incerteza, rejeição e falha de leitura preservam a pendência. A lista não transforma sozinha um resultado incerto em confirmação.

O backend e a allowlist do bridge pertencem à frente de streaming; não os alterei. Não regenerei bundle nem reiniciei serviços. Os 21 testes selecionados de bridge/chat-state/update/deadline/manutenção passaram nesta etapa.

## Correções candidatas verificadas

- `shell-app.jsx` agora usa `inert={warmVisual}`. QA mede `main.inert === true` no cache e `false` depois do home canônico, com o atributo removido.
- A conversa selecionada é resolvida por `conversation_get` em estado independente das páginas de catálogo, conferindo projeto, Space e conversa exatos. A consulta é revalidada após Home/eventos; exclusão/fora de escopo produz estado explícito e consulta somente de leitura. Falha transitória mantém entidade canônica já conhecida. Há apenas um estado de abertura enquanto ainda não resolvida, em vez de mostrar simultaneamente “carregando” e “indisponível”.
- Trocar de projeto libera o mutex visual da criação antiga. O finally da resposta antiga só libera o mutex se ainda possuir a mesma request_key. Uma resposta tardia não navega nem bloqueia o novo projeto. A criação antiga permanece consultável no journal original.
- `shell-pending-presentation.js` é somente projeção: pendências antigas aparecem imediatamente; novos avisos globais aguardam 700 ms, e uma criação com transporte ativo usa apenas “Abrindo conversa…”. Remoção confirmada é imediata. `pendingShellMutations` e as verificações de admissão de update não foram alteradas.
- QA adicional `native_bridge`: window.pywebview e controles nativos sintéticos presentes, criação/envio aprovados sem renovação/restart. Isso verifica o ramo React, **não equivale a homologação do WebView nativo real**. O drag region limita-se ao topbar; não identifiquei dependência de pywebview no botão Conversar.
- QA `project_switch`: retarda a entrega do ACK HTTP da primeira criação, troca o projeto e depois libera o ACK. O novo projeto mantém contexto, botão habilitado e nenhuma navegação/aviso de pendência do projeto anterior.
- QA verifica que POST reconhecido rapidamente não pisca o shelf global de pendências, e que o composer permanece dentro do viewport no shell com o mesmo root estrutural do desktop.

Suíte JavaScript completa: **123/123 passaram**, `.tmp/astra-experience-node.log`. Build Vite **isolado** passou, `.tmp/astra-experience-build.log`; nenhum static global foi escrito. Bundle instalado e caso nativo do usuário continuam sob validação do coordenador; não declaro a causa exata daquele episódio resolvida.

Observação UX registrada, sem mudança silenciosa: “Conversar” no cartão cria uma conversa nova; o botão da sidebar reutiliza uma existente. A discrepância continua candidata a decisão explícita de produto.
