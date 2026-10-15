# Abertura de conversas: cache simples e leitura econômica

## Diagnóstico limitado ao que foi medido

Antes desta integração, a tela pedia `message_list` com `offset:0, limit:50`. Quando havia mais de 50 mensagens, pedia em seguida a última página. Eram duas requisições sequenciais para obter a parte recente de um histórico grande, além de decodificar/reconciliar a primeira página. O código atual usa `tail:true`, com fallback exclusivamente de leitura para servidores antigos.

O agente principal mediu nove leituras HTTP reais em três conversas com 7–10 mensagens: 55,0–169,7 ms, conforme `.tmp/astra-conversation-read-latency.json`. Essas amostras não medem abertura da tela, renderização, p95 nem conversas grandes. Também não demonstram uma necessidade de Redis ou outro serviço de cache.

## Implementação mínima no backend

Foi acrescentado `tail:true` opcional à ação existente:

```js
bridge({
  action: 'message_list',
  project_id,
  space_id,
  conversation_id,
  limit: 50,
  tail: true,
});
```

O servidor busca as últimas N mensagens e devolve os itens em ordem cronológica ASC, incluindo o desempate por `message_id`. Não há cache novo no servidor. Sem `tail`, o contrato antigo de `offset/limit` continua igual. `tail:false` também segue o caminho antigo. O modo novo exige Space explícito, aceita `offset` apenas omitido ou zero e rejeita `tail` não booleano.

Exemplo para 123 mensagens:

```json
{
  "page": {
    "offset": 73,
    "limit": 50,
    "returned": 50,
    "total": 123,
    "next_offset": null,
    "tail": true,
    "previous_offset": 23
  }
}
```

A primeira abertura passa a precisar de uma única requisição ao backend atualizado. Para buscar as anteriores, usar a leitura antiga com `offset:23, limit:50`. Para o último trecho restante, usar `offset:0, limit:23`. O cliente pode calcular `limit = começoAtual - previous_offset`; isso evita repetir mensagens quando restam menos de 50. Os resultados devem ser combinados por `message_id`, preservando revisão, `request_key`, recibos e a ordenação.

Há uma única instrução SQL para obter conteúdo e total sob o mesmo snapshot. Uma subconsulta COUNT não correlacionada usa o índice escopado; a seleção recente usa a ordenação inversa e só entrega N corpos protegidos. O teste do plano SQLite confirma a subconsulta não correlacionada e o índice de cobertura para a contagem. Não foi usado COUNT com window sobre todos os corpos. A contagem ainda percorre o índice do histórico: não é prometido custo constante para históricos arbitrariamente grandes.

O modo `tail:true` não executa a migração de Spaces/Dots/equipes. Mantém a verificação atual de proprietário/projeto/Space e a reconciliação síncrona das mensagens retornadas. O cache visual não é usado para substituir pendências ou recibos por outro estado. Conteúdos grandes continuam com sua referência paginada `message_content`, sem truncar o original.

Uma intenção pendente pode estar fora das últimas 50 mensagens. Sua ausência na janela não prova que não foi enviada nem permite apagá-la: consultar `message_request_status` pela chave original, projeto, Space e conversa, independentemente da página. Essa consulta não reenvia o prompt.

## Cache visual integrado à interface

`shell-conversation-cache.js` implementa um LRU privado por janela: oito conversas, até 4 MiB de JSON em UTF-8 e validade de cinco minutos sem extensão por leitura. São guardadas somente as últimas 50 mensagens completas da projeção. Uma mensagem que exceda o orçamento não é truncada para caber. O limite dos bytes serializados não é um teto exato do heap JavaScript. Não usa disco, localStorage, IndexedDB, Redis ou serviço adicional.

O cache mantém apenas escopo, identidade da mensagem, papel, texto, data e indicação de prévia truncada. Exclui request_key, status, recibo, Operation, Grant, token, anexos e referência de conteúdo. A renderização antecipada usa texto simples, identificado como visualização anterior, sem botões, Markdown interativo ou recibos. Mensagens canônicas e pendências são mantidas em coleções separadas. Falha definitiva de autenticação limpa o cache e a projeção já renderizada, incluindo recibos/conteúdo completo; preserva a intenção pendente. Fechamento da página limpa o LRU; negação da conversa ou do histórico, inclusive durante paginação antiga, remove a entrada afetada. Uma troca de escopo recria o componente.

O cache pode antecipar a última visualização enquanto uma consulta autenticada atualiza os dados. Não deve armazenar decisões de autorização, permissões, Grants, credenciais nem intenções pendentes; não pode encerrar um envio incerto ou habilitar uma ação com base num recibo antigo. Sessão/projeto precisam estar no contexto atualmente autorizado. Respostas explícitas de 401/403/404 devem invalidar a entrada afetada; uma falha transitória pode manter a projeção como “última visualização”, com recuperação em andamento.

Ao voltar de outra conversa, o resultado fresco define a página recente e substitui a prévia. No acompanhamento aberto, páginas sobrepostas ou adjacentes podem ser combinadas. Se uma nova janela estiver separada por uma lacuna, o leitor no fim adota a janela recente; quem lê um trecho antigo mantém sua posição e recebe o botão “Há novas mensagens · Ir para o mais recente”. Essa ação troca a janela; as páginas anteriores continuam acessíveis. A paginação reversa é serializada com a atualização recente, sem avançar o limite do trecho por causa de um COUNT mais novo. Não se trata uma coleção parcial em RAM como histórico completo.

## Compatibilidade e implantação

Um backend antigo pode ignorar o campo desconhecido `tail` e devolver a primeira página normalmente. A interface deve verificar `result.page.tail === true`. Se a marca não vier e `total > limit`, deve usar o fallback já existente para ler a última página; isso é exclusivamente leitura e nunca repete prompt. Para rollback basta voltar às leituras antigas, sem migrar ou apagar dados.

A interface aberta antes desta integração ainda usava o bundle anterior. O wiring novo foi verificado em código React real e HTTP isolado; sua publicação no bundle é uma etapa separada e não comprova um novo Setup instalado. Não foi criado servidor externo de cache.

## Evidências e limites

### Continuação — leituras anteriores à perda de acesso

`ShellConversation` agora incrementa um epoch de leitura ao invalidar o acesso. Respostas iniciadas antes dessa invalidação são descartadas no histórico, paginação, prévia de compatibilidade, consulta de envio/recibo e leitor/exportação do original. A liberação de uma resposta antiga não reativa acesso nem repopula o cache. Só uma nova leitura canônica iniciada depois pode recuperar a apresentação. Os bytes do original também são recusados se a invalidação acontecer durante a espera da página ou do hash final.

O QA real de navegador reteve respostas HTTP 200 já recebidas de `message_list` (50 mensagens), live (52 caracteres) e `message_content` (10.200 caracteres), perdeu a autorização e só então liberou as respostas. Texto, cache e recibos não voltaram; novas leituras recuperaram os dados. A interface mostra acesso indisponível e não apresenta uma introdução de conversa vazia enquanto o histórico está invalidado. Nenhum prompt foi enviado. Evidência atualizada em `.tmp/astra-conversation-cache-qa/report.json`, com hash da fonte e captura `auth-late-history-discarded-1440.png`.

Após a integração, **145 testes JavaScript passaram** e os **12 cenários de `astra_chat_turn_browser.py` passaram**. O bundle foi reconstruído e `validate_desktop_bundle` conferiu **128 assets e 140 inputs de fonte**; relatório `.tmp/astra-current-ui-validation.json`. Esses números descrevem o checkout candidato, não comprovam atualização da janela já aberta ou um novo Setup instalado. A amostra de cache dessa execução foi 85,24 ms, sem inferência real e sem alegação de p95.

`python -B -m pytest tests/unit/test_shell_message_tail.py -q --tb=short --disable-warnings -p no:cacheprovider`

**8 testes passaram em 18,19 s.** Cobrem últimas 50 em um histórico de 123 mensagens, recuperação de todo o histórico via páginas antigas, Unicode e timestamps empatados, chegada de novas mensagens/revisões, conversa vazia, referência de conteúdo longo, escopos e autenticação, reconciliação síncrona de pendência com recibo/chave, plano da consulta e um escritor que faz commit durante o SELECT. Nesse último caso, total e conteúdo correspondem ao mesmo snapshot e a consulta seguinte vê as cinco mensagens novas.

A tradução da instrução foi exercitada pelo adaptador SQL PostgreSQL; isso não é homologação com um servidor PostgreSQL real. O conjunto usa Canvas/SQLite/DPAPI reais em armazenamento temporário, com conteúdo e recibos de teste; não invoca modelo.

Regressão final: **28 testes passaram em 95,73 s**, reunindo `test_shell_message_tail.py`, `test_shell_conversation_get.py`, `test_shell_conversation_receipt_read.py`, `test_shell_message_request_status.py` e `test_canvas_web_peer_transport.py`. O caminho legado e as consultas seguras anteriores permaneceram aprovados.

## Verificação da interface integrada

`node --test test/*.test.mjs test/experience-cadencia/*.test.mjs` no diretório Desktop: **132 aprovados**, incluindo nove casos novos de cache/TTL/LRU/quota UTF-8, exclusão de autoridade, escopo, tail, fallback e lacunas.

`python -B tests/qa/astra_conversation_cache_browser.py`: componente React e transporte HTTP reais com dados sintéticos, sem modelo/conta produtiva. Relatório `.tmp/astra-conversation-cache-qa/report.json`: uma consulta para a página recente; histórico de 123 mensagens recuperado integralmente; lote novo de 100 mensagens só adotado explicitamente quando o leitor está no trecho antigo; prévia visível durante leitura deliberadamente bloqueada; nenhuma confirmação de envio pendente pelo cache; 403 e falha global de autenticação limpam a tela e o LRU; zero erros JavaScript. Quatro amostras da prévia quente ficaram entre **80,62 e 141,29 ms**; última execução: **80,62 ms**. Incluem automação do clique e espera do seletor, com revisões do harness entre execuções. Não são p95, comparação controlada de ganho ou medição de pintura do aplicativo instalado.

`python -B tests/qa/astra_chat_turn_browser.py`: **12 cenários aprovados** após a integração, incluindo perda de resposta de criação, conversa fora da primeira página, pendências não confirmadas, troca de projeto e bridge nativa sintética.

Após acrescentar a limpeza da projeção já renderizada na falha global de autenticação, a repetição completa aprovou 11 cenários; `warm_cache` não carregou o JavaScript do Vite (`net::ERR_NO_BUFFER_SPACE`, zero requisições ao backend e tela em branco). O caso foi repetido isoladamente com `--scenario warm_cache`, sem mudança no produto, e passou em 3,06 s. Relatórios separados: `.tmp/astra-chat-turn-qa/report.json` conserva essa falha de infraestrutura; `.tmp/astra-chat-turn-qa-warm_cache/report.json` conserva a repetição aprovada. O harness agora permite selecionar cenários sem substituir o resultado completo.

O bundle foi reconstruído e validado com 128 assets e 138 entradas de fonte. Navegação de leitura no broker real, usando esse bundle, abriu a conversa existente e a confirmação de criação simulada sem erros JavaScript; nenhuma criação/envio real foi efetuado nesse ensaio. A janela nativa já aberta não foi reiniciada por essa validação. Regressão backend selecionada: **21 aprovados em 46,86 s** (tail, conversation_get, status HTTP e consulta de envio).

Ainda faltam medições repetidas da primeira pintura e atualização canônica no aplicativo instalado, perfil de heap e histórico muito grande sob carga real. A redução de duas leituras para uma não autoriza anunciar ganho percentual sem medir esse percurso.
