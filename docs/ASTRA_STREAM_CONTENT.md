# ASTRA — conteúdo longo da prévia durável

Estado: backend de referência paginada e leitor React implementados. O leitor passou QA isolado descrito em `ASTRA_STREAM_CONTENT_UI.md`; a interface instalada ainda precisa de homologação. Nenhum teste deste documento representa inferência real ou instalação homologada.

## Contrato

O head e cada evento continuam carregando somente uma janela, limitada a **131.072 unidades UTF-16**, sem cortar um par substituto. Isso mantém compatibilidade com o limite do reducer JavaScript e com frames SSE menores que 2 MB, inclusive para texto astral. A sequência, a retomada do feed e o caráter não autoritativo permanecem iguais.

Quando o corpo excede a janela, a projeção inclui `truncated:true`, `content_offset` e:

```json
{
  "content_ref": {
    "reference_id": "stream-<sha256>",
    "total_chars": 220000,
    "total_utf8_bytes": 250000,
    "sha256": "<sha256 do corpo UTF-8 completo>",
    "action": "stream_content",
    "page_max_chars": 65536,
    "page_max_utf8_bytes": 262144
  }
}
```

`content_offset`, `offset`, `limit` e `total_chars` contam **pontos de código Unicode**, como uma string Python; não são offsets UTF-8 nem `String.length` do JavaScript. O cliente deve seguir `next_offset`, sem recalcular o cursor por unidades UTF-16.

Leitura autenticada:

`GET /api/shell/stream/content?project_id=...&space_id=...&conversation_id=...&reference_id=...&offset=0&limit=65536`

Os quatro identificadores são obrigatórios e exatos; `offset` e `limit` são opcionais. Não se aceitam campos extras, duplicados/vazios ou números fora da gramática ASCII decimal. A página aceita de 1 a 65.536 pontos de código, com até **262.144 bytes de conteúdo UTF-8 bruto**. O envelope JSON tem overhead adicional; essa quota não é apresentada como um limite de 64 KiB.

Resposta: escopo original, `reference_id`, `content`, `offset`, `next_offset`, `total_chars`, `total_utf8_bytes`, `sha256` do corpo e `page_sha256` da página. `next_offset:null` encerra a referência imutável. Permanecem `persisted:true`, `partial:true`, `authoritative:false`, `automatic_retry:false` e `closes_trio:false`.

Cada requisição revalida proprietário, projeto, Space e conversa vivos. A seleção do Space/conversa e a leitura de manifesto/blocos usam um único snapshot SQL de leitura. O servidor também consulta o projeto/run pela fronteira existente. Referência, digest ou cursor não concedem permissão. Não há cache de autenticação, Grants ou permissões. O retorno usa `Cache-Control:no-store`.

Ausência, expiração e referência fora do escopo resultam em 404 uniforme; autenticação expirada resulta em 401 e conflito de Space em 403. Erro de integridade impede a devolução do conteúdo. A leitura não chama modelo, browser, executor, redispatch ou reconciliação de envio.

## Persistência e retenção

O journal usa o armazenamento protegido existente e quatro tabelas adicionais no namespace `shell`: manifestos, blocos imutáveis, páginas e vínculos de referência por sequência. Corpo, manifesto e mapa ordenado de hashes são protegidos por `_encode`/DPAPI ou keyring. O manifesto vincula proprietário, projeto, Space, conversa, operação, referência, tamanhos e hash completo. A leitura valida também a posição/hash de cada bloco e rejeita troca entre dois blocos protegidos válidos.

Os blocos têm até 65.536 pontos de código e são reutilizados pelo hash dentro do mesmo proprietário/projeto. A gravação de um corpo crescente não regrava todos os blocos de prefixo: uma prova com vinte revisões gravou dois blocos estáveis e vinte caudas pequenas, em vez de vinte cópias do corpo. Manifestos e mapas de páginas continuam por referência imutável; o seu custo não é declarado constante.

Blocos, manifesto, referência, evento e head entram na mesma transação, antes da publicação. Falha intermediária reverte tudo. A compactação retém as referências de todos os eventos ainda reproduzíveis e de todos os heads, inclusive conversas inativas cujo último evento já saiu da janela de 2.048 eventos. Só remove páginas, manifestos e blocos depois de não restar raiz de retenção. Uma referência expirada nunca passa a apontar para uma revisão mais recente.

O orçamento explícito de corpo recuperável é **8.000.000 bytes UTF-8 por observação**. Excedê-lo gera uma projeção `preview_unavailable`, `truncated:true` e `content_error:{code:'stream_content_budget_exceeded',limit_utf8_bytes,observed_utf8_bytes}`, com atividade visível. Não se emite referência que afirme recuperar um corpo não armazenado. Isso não transforma a prévia numa confirmação de conclusão, mesmo se a observação original indicava `committed`.

Os limites anteriores do produtor permanecem: o escritor nativo envia no máximo 500.000 caracteres, o arquivo temporário continua limitado a 8 MB e os armazenamentos Web mantêm seus próprios orçamentos. O novo contrato não promete recuperar bytes que o adaptador nunca emitiu ou que foram perdidos antes do commit.

## Integração dos produtores e compatibilidade

O produtor nativo conserva o corpo observado da rodada para o journal; somente a view de compatibilidade aplica a janela. O coletor Web solicita o corpo completo já validado/protegido antes de gerar a janela. A conclusão de runtime deixa de cortar o conteúdo em 200.000 caracteres antes de passá-lo ao journal. O histórico canônico e seu `message_content` continuam separados e autoritativos.

O feed e os endpoints antigos permanecem disponíveis. As tabelas são aditivas; rollback da apresentação não apaga os conteúdos protegidos. Prévia antiga já truncada sem referência não ganha retroativamente os bytes que não foram preservados. Sua recuperação deve usar o histórico canônico quando existente, sem inventar completude.

Para a UI, a referência deve ficar vinculada à operação e sequência do head selecionado. Uma página atrasada não pode substituir uma operação nova. Conferir o hash completo ao reconstruir e preservar a janela durável durante falhas de leitura. Troca de conversa/operação, referência expirada e recusa de autenticação precisam de estados explícitos. A existência desta API não comprova que o produto já apresenta todo o corpo.

## Evidências

`tests/unit/test_shell_stream_content.py` cobre reconstrução Unicode em páginas atravessando blocos, reabertura, deduplicação, rollback, concorrência, retenção de head inativo, referência antiga/expirada, proprietário/escopo, manifesto adulterado, troca de blocos, orçamento e os caminhos nativo/Web/conclusão canônica. Há saídas abruptas de um processo real durante a gravação dos blocos e logo após o commit: a primeira não expõe referência/evento parcial; a segunda reabre o corpo completo e verifica seu hash. Os testes HTTP usam o `CanvasServer` real com estado temporário e provam gramática exata, bearer recusado/rotacionado, `no-store`, revogação da conversa e ausência de mutações no dump do journal. Os planos SQL também comprovam índices para as raízes de retenção, evitando buscar todos os mapas de páginas para cada bloco no GC.

Os demais testes da frente continuam em `test_shell_stream_journal.py`, `test_sentra_shell_live_preview.py`, `test_shell_runtime_turn_memory.py`, `test_shell_web_preview.py` e `test_canvas_web_peer_transport.py`. Resultados finais e latência após a integração ficam registrados em `ASTRA_FRENTE_STREAMING.md`.

Faltam a apresentação integral na UI instalada, falhas combinadas de todos os serviços, suspensão do Windows e homologação do PostgreSQL. A implementação SQL atual foi exercitada em SQLite/WAL com proteção real do sistema operacional.

## Retomada de referência após queda do broker

O ensaio real `tests/qa/astra_broker_restart.py` detectou e corrigiu a perda de `content_ref` ao republicar uma head interrompida depois de reiniciar o broker. O caminho interno de retenção só aceita `interrupted`/`preview_unavailable` com operação, revisão, janela, offset e referência idênticos à head protegida existente. Na mesma transação, exige o vínculo de sequência/raiz de retenção, o Space/operação do manifesto e a validação do conteúdo protegido. Não aceita referência arbitrária vinda do produtor, outra operação, outra janela, offset alterado, raiz ausente ou estado de conclusão.

A nova sequência retém a mesma referência imutável; não duplica o corpo nem refaz a tarefa. O harness mata seu próprio broker, reinicia na mesma porta com nova sessão e reconstrói **336.017 pontos de código** por páginas, conferindo o hash completo. Dez fluxos e vinte leitores recuperam cursores; a sessão anterior é recusada e as operações seguem `UNCERTAIN`. O relatório final está em `.tmp/astra-broker-restart/report.json`; o relatório que encontrou a falha permanece em `report-before-reference-fix.json`.

As provas negativas de `test_shell_stream_content.py` impedem carry de referência arbitrária, operação/Space/offset/janela divergentes, referência sem raiz e tentativa de declarar conclusão. A leitura GET permanece sem efeitos. A autenticação nova neste ensaio chega por um pipe privado de QA; esse caminho não certifica a renovação da sessão no produto instalado.

O filtro compartilhado `sentra_core/model_prose.py` preserva marcadores de prosa legítimos como `[[wiki]]` e `[[ação]]` antes da geração da janela/hash. Cabeçalhos da gramática formal de diretivas e seus argumentos incompletos permanecem ocultos. Os testes reconstruem corpos longos com esses marcadores, Unicode e repetições; o fallback de rascunho também informa explicitamente `truncated`/`content_offset`. A integração CLI e a remoção do reparse da UI foram feitas pelo agente principal. A prova desta frente continua sendo de backend/transporte, não de exibição completa instalada.
