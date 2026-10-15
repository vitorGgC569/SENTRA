# ASTRA — entrega da frente de streaming e retomada

Estado: avanço implementado e validado em ambiente temporário; P1 integral ainda não homologado. Não certifica instalação, vinte identidades de equipe, dez inferências reais, suspensão do Windows ou disponibilidade de provedores.

## Correções implementadas

- O journal de apresentação usa snapshot SQL para leitura sem segurar o lock da ingestão. Leitor lento não impede o produtor de persistir.
- `publish_many` persiste até 64 observações numa única transação protegida, mantendo eventos e heads atômicos. Falha intermediária reverte o lote inteiro. Nenhum evento em transação incompleta é publicado.
- A ingestão das prévias nativas agrupa as mudanças dos dez produtores por ciclo, retém os fragmentos em caso de falha de gravação e repete apenas a persistência. As prévias não possuem capacidade de reenviar prompt.
- Leituras SQLite do mesmo cursor são coalescidas por até 50 ms, com limite agregado de 2 MB/64 entradas e limite de 256 KB por entrada. Cada commit local invalida o cache. Cada hit revalida a seleção da autoridade SQLite. A devolução copia o resultado, evitando que um consumidor altere o estado de outro. PostgreSQL não usa esse cache e não foi homologado nesta frente.
- A prévia nativa conserva o handle criado com `mkstemp` durante a operação, evitando reabrir o arquivo por fragmento. Cada leitura verifica pathname, identidade de arquivo e tamanho; substituição, symlink ou truncamento inesperado declara a prévia indisponível. Encerrar a operação fecha o handle, inclusive após erro do callback. A coleta não relê cada arquivo duas vezes quando a conversa tem produtor nativo ativo.
- O cliente conserva a última projeção durável quando o snapshot falha. Fragmentos posteriores aguardam um snapshot válido. Uma consulta travada é abortada após 10 s; a recuperação tem retentativa de leitura com atraso exponencial limitado a 15 s e também pode ser acordada por heartbeat/evento. Falha de autenticação não inicia essa retentativa.
- `online`, `pageshow` e retorno à visibilidade acordam a observação e atualizam os heads visíveis. A retomada usa o cursor existente e não reenvia operações. Autenticação recusada continua exigindo o caminho confiável existente.
- No MV3, startup, atualização e reinstalação deixam de apagar trabalhos ativos e de navegar a aba enquanto há trabalho preservado. A identidade de navegador continua sendo revogada separadamente, e os trabalhos Web preservados ficam em observação somente. Falha ao ler storage não autoriza restauração/navegação.
- Gravações dos metadados ativos são serializadas por aba. Renovação atrasada não sobrescreve prova mais nova nem recria um trabalho que já foi removido/substituído.
- Flushes concorrentes de outbox compartilham a mesma entrega. Um ACK antigo remove apenas o valor efetivamente enviado, sem apagar um resultado novo gravado durante a requisição. O formato de outbox existente permanece compatível.
- A projeção longa passa a usar uma janela limitada em UTF-16 com referência imutável para o corpo protegido paginado. Blocos de prefixo são reutilizados por hash; manifesto protegido vincula escopo, tamanhos, digest e ordem dos blocos. Detalhes de contrato, quotas e retenção estão em [ASTRA_STREAM_CONTENT.md](ASTRA_STREAM_CONTENT.md). O coletor nativo/Web e a publicação final alimentam esse contrato antes de aplicar a janela; isso ainda não comprova apresentação integral na UI.

## Evidência executada

`node --test sentra_canvas/desktop_ui/test/shell-stream-transport.test.mjs edge_extension/durable-recovery.test.cjs edge_extension/native-image-guard-load.test.cjs edge_extension/native-image-bytes.test.cjs`

Resultado: **20 passaram**. Inclui UTF-8/SSE fragmentado, confirmação, cursor/deduplicação, lacunas, erro transitório, consulta travada, retomada de leitura sem aguardar outro heartbeat, revogação de autenticação, concorrência de metadados/outbox e recriação de contexto JavaScript. Os testes MV3 executam as funções reais extraídas do worker num contexto Node com storage simulado; não equivalem a terminar um service worker real do Chrome.

`python -B -m pytest tests/unit/test_shell_stream_journal.py tests/unit/test_sentra_shell_live_preview.py tests/unit/test_shell_runtime_turn_memory.py tests/unit/test_canvas_web_peer_transport.py -q --tb=short --disable-warnings -p no:cacheprovider`

A execução final passou: **29 testes em 66,26 s**. A suíte cobre SQL/DPAPI reais, rollback, lote atômico, proteção de autoridade, ingestão sem renderer, vinte leitores HTTP e recuperação de conteúdo. O teste de saída abrupta usa um processo Python separado e `os._exit(37)` imediatamente depois do commit; ao reabrir o armazenamento, os dez eventos persistidos continuam íntegros.

`python -B tests/qa/astra_stream_resilience.py`

Rodada anterior preservada em `.tmp/astra-stream-resilience/report-prior465.json` (a série mais recente aparece abaixo):

| Medida | Resultado observado |
| --- | --- |
| Produtores nativos sintéticos | 10 |
| Leitores HTTP/SSE autenticados simultâneos | 20, sob um único proprietário |
| Observadores DOM multiplexados | 20 numa conexão do ProjectFeed |
| Emissões distintas / amostras de pintura | 60 / 120 |
| Todos os leitores HTTP receberam todos os 60 fragmentos | Sim |
| Emissão LivePreviewWriter → duas chamadas de requestAnimationFrame | p50 317,25 ms; p95 465,62 ms; máximo 501,58 ms |
| Emissão → commit observado | p95 312,20 ms |
| Commit → pintura | p95 153,42 ms |
| Reconexão após abortar o socket de observação e restaurar online | 125 ms |
| Heads preservados enquanto observador estava offline | 10 de 10 |
| Nova janela recupera conteúdo interrompido | Sim |
| Novo despacho de operações ao reconectar | Zero no ensaio sintético |

O relatório inclui hashes SHA-256 das fontes e amostras reais dos processos `cargo.exe`/`rustc.exe` no começo e no final. Na rodada final, nenhum desses processos foi encontrado nesses dois instantes, após o agente principal informar que o build RustDesk havia terminado. Isso não comprova host ocioso durante todo o intervalo e não transforma o ensaio em benchmark isolado de release. As primeiras rodadas ocorreram com o build informado como concorrente. P95 por etapa não deve ser somado como se fossem amostras pareadas.

A primeira medição deste trabalho observou p95 de 1.546 ms. As rodadas intermediárias, usadas para identificar os gargalos, observaram aproximadamente 798 ms, 639 ms e 413 ms. Foram ensaios individuais, com o host compartilhado; não são comparação estatística controlada nem prova da meta de 300 ms.

## Latência por etapa e correção de reabertura nativa

O harness passou a registrar amostras pareadas de emissão, ingestão, commit, `onPreview` e dupla RAF, além de durações das chamadas de arquivo, DPAPI e conexão SQL. A carga foi preservada: dez `LivePreviewWriter`, vinte leitores HTTP/SSE e vinte observadores DOM, sessenta fragmentos distintos e 120 amostras de pintura por rodada. Esses observadores usam o transporte fonte real; não representam vinte usuários ou a renderização Markdown completa do aplicativo instalado.

O baseline instrumentado identificou **70 reaberturas** de arquivo durante geração/recuperação, somando **503,48 ms** no coletor. A abertura custava p50 7,05 ms/p95 9,28 ms; DPAPI p95 0,45 ms por encode. A correção preserva o handle criado pela própria operação e valida a identidade `(st_dev, st_ino)` antes de cada leitura, mantendo os gates de nonce, tamanho, symlink e escopo. Nada foi alterado nos recibos, autenticação, durabilidade FULL ou metas de carga.

| Rodada | Emissão → pintura p95 | Emissão → ingestão p95 | Todos os leitores receberam 60 fragmentos |
| --- | --- | --- | --- |
| `syscall-before` | 320,42 ms | 147,49 ms | Sim |
| `pinned-after-1` | 239,98 ms | 27,79 ms | Sim |
| `pinned-after-2` | 252,65 ms | 54,92 ms | Sim |
| `pinned-after-3` | 251,76 ms | 49,52 ms | Sim |

Comando: `python -B tests/qa/astra_stream_resilience.py --label pinned-after-3`. Os relatórios por rótulo estão em `.tmp/astra-stream-resilience/report-<rótulo>.json`. O harness tem o mesmo SHA-256 nas quatro rodadas: `ee1b1775aee97641da8c9b530de242f6541291f68a9534fb6535dc8cdafcda17`. Apenas `shell_live.py` mudou entre baseline e série posterior (hash final `5db55357cbd847fe9e9ffadc4ebc8e3da444c83b963a4c71499246550ca8ce5c`). Na segunda rodada posterior, `live_update` p95 caiu de 9,53 ms no baseline para 0,55 ms e não houve reabertura no coletor. Nas três rodadas posteriores, a retomada de leitura levou 125 ms e houve zero redispatch sintético.

As três rodadas passaram a meta de 300 ms **neste ensaio**. O host continuou compartilhado: `pinned-after-2` encontrou dois processos Cargo na amostra inicial e nenhum na final; as demais amostras dessas quatro rodadas não encontraram Cargo/rustc. Isso não prova isolamento nem causalidade estatística de toda a diferença. Os valores p95 por etapa não devem ser somados. Aceite do aplicativo instalado e dos provedores permanece pendente.

Após a correção, a regressão Python do comando acima passou novamente: **33 testes em 64,79 s**. Foram acrescentadas provas de escrita por um processo filho real enquanto o leitor permanece aberto, recusa de identidade diferente/truncamento, ausência de reaberturas e liberação do handle mesmo quando o callback de persistência falha. O processo filho escreve somente texto sintético; não executa inferência nem acessa provedores.

A revisão acrescentou descarte do handle substituído quando uma nova operação assume a mesma conversa e `close_all` no encerramento do runtime. Um `finally` tardio da operação anterior não publica interrupção na nova nem fecha seu handle. Falha em `fdopen` depois de tomar posse do descritor conserva o erro original e limpa o arquivo temporário. Os casos correspondentes são executados em `test_sentra_shell_live_preview.py`.

Com referências e descarte integrados, uma rodada posterior observou p95 **243,61 ms**, máximo **269,16 ms** e retomada **109 ms**, com a mesma carga e os mesmos probes. Está em `report-content-integrated.json`; continua sendo estado temporário/DOM de teste, sem inferência nem certificação do aplicativo instalado.

Após o tratamento de falha de `fdopen` e os índices de GC, a rodada `content-final` observou p95 **282,16 ms**, máximo **286,16 ms** e retomada **109 ms**, mantendo 10 produtores, 20 leitores HTTP, 20 observadores DOM e 120 pinturas. Todos os leitores receberam os 60 fragmentos; houve zero redispatch sintético. Os hashes registrados nessa rodada são `shell_stream.py=5b4a23bda5d7ad593ff9b2e2e3a297b0c9958172a9ba62f9e80d8cd954142924`, `shell_live.py=23c65763081d17a2f5a7d5a88d0a0f1339efdf225bce95073df4f2f4d22938e7` e `shell_runtime.py=7fb39762a8505aac599a639f2491b475d80627936e7179b7a4634e9573134204`. As amostras inicial/final não encontraram Cargo/rustc; o host compartilhado continua sem certificação de isolamento. O corpo dos marcadores é pequeno: esta medição não prova a meta de latência para dez respostas longas simultâneas.

## Ensaio MV3 em navegador real

`python -B tests/qa/astra_mv3_lifecycle.py`

Passou em Chromium **151.0.7922.34**, usando extensão temporária e perfil próprio. O relatório está em `.tmp/astra-mv3-lifecycle/report.json`, com hashes da fonte, da cópia de teste e os caminhos efetivamente recebidos pelo relay sintético. A cópia usa somente um relay efêmero em loopback, substitui as duas constantes de URL e acrescenta listeners diagnósticos de ciclo de vida. Nenhum bootstrap, credencial real, conta, página de provedor ou perfil produtivo foi copiado.

Foram comprovados: retenção da outbox após HTTP 503; parada forçada do worker pelo CDP, com transição `stopped → running` e desaparecimento de uma marca exclusiva do contexto JavaScript anterior; identidade local, cursor/revisão, job e outbox íntegros; encerramento e abertura do navegador com o mesmo perfil; recuperação Web em observação somente; entrega de um resultado sintético armazenado exatamente uma vez após o relay voltar e remoção da outbox somente após ACK. Não houve chamadas de submissão, poll, progress, receipt ou bootstrap.

O ensaio encontrou uma lacuna real no callback: o relaunch da extensão unpacked recebeu `onInstalled(reason: install)` novamente, sem `onStartup`. Antes da correção, os metadados persistiam, mas `observe_only:false` permanecia após o relaunch. `onInstalled` agora também chama `omaStartupCleanup`, depois de invalidar identidade e antes da injeção nas abas existentes. O teste real passou após essa mudança. O callback `onStartup` é validado em unidade; este ensaio real não prova que esse evento específico foi disparado.

Regressão adicional: **22 JavaScript passaram** no comando de transport/guard/durable-recovery acima, incluindo **8** casos de durabilidade e execução dos dois callbacks reais em VM Node. O hash fonte da extensão nesse ensaio é `051a2767f4a03fa7a1ef5dbb0f74c1b67e09745287a0bbbc19ff1b3c3301ab63`. O agente principal confirmou o stamp do manifest e 22 testes adicionais de versões, sem reload/bootstrap produtivo. Nenhum helper runtime foi acrescentado.

Limites da primeira rodada: resultado sintético de uma outbox não Web; nenhuma inferência, entrega atestada de provedor, suspensão do Windows ou validação da extensão instalada. O encerramento integral dessa rodada foi gracioso; o crash completo passou posteriormente, conforme a prova abaixo. A recuperação de um corpo Web não foi simulada por armazená-lo em texto simples na extensão.

### Crash completo do navegador isolado

`python -u -B tests/qa/astra_mv3_lifecycle.py --browser-restart crash` passou. O harness obtém o PID pelo CDP do seu próprio navegador, mantém um handle Windows para impedir ambiguidade por reutilização de PID, chama `TerminateProcess` e confirma a saída real por `WaitForSingleObject`/`GetExitCodeProcess` antes de reabrir o perfil. Não enumera nem mata navegadores do usuário. A saída não graciosa foi confirmada com código 57005. A primeira tentativa com o comando CDP `Browser.crash` terminou o navegador, mas deixou a resposta presa no driver do teste; esse limite de instrumentação foi registrado em `report-crash-cdp-command-blocked.json` e corrigido no harness, sem mudanças no produto.

Na reabertura, a outbox, o job, o cursor/revisão, o digest e as identidades persistidas permaneceram iguais; o job Web passou de `observe_only:false` para `true`. O relay inicialmente em 503 recebeu o resultado sintético exatamente uma vez quando voltou, e a outbox foi removida somente após ACK. Nenhum caminho de submissão/poll/progress/receipt/bootstrap foi chamado. O hash fonte da extensão permaneceu `051a2767f4a03fa7a1ef5dbb0f74c1b67e09745287a0bbbc19ff1b3c3301ab63`.

Os modos `--browser-restart graceful` e `--browser-restart crash` passaram novamente com o mesmo harness SHA-256 `cf51d33c68f9125030b00a924acf2e6c6b33d83c88743d8b176efecbbd4b1bf2`. Relatórios separados: `.tmp/astra-mv3-lifecycle/report-graceful.json` e `report-crash.json`; `report.json` aponta para a última execução. O perfil, relay e credencial de teste são temporários, a identidade de distribuição é restampada apenas nessa cópia e a comparação final confirma fontes produtivas intactas. Continua faltando suspensão do Windows, extensão instalada e entrega atestada por um provedor real. O relaunch unpacked ainda dispara `onInstalled`; não foi alegado disparo real de `onStartup`.

## Integração e rollback

Nenhum bundle estático foi reconstruído por esta frente e nenhum runtime instalado foi reiniciado/substituído. O agente principal deve revisar as fontes, reconstruir o bundle e gerar seu snapshot de proveniência.

A extensão recebeu alterações somente em `service-worker.js`; não há novo helper runtime importado. O teste `durable-recovery.test.cjs` é arquivo de teste. O agente principal deve recalcular/stampar o `sentra_source_hash` do manifest após revisar o worker. Durante a integração, ele acrescentou o módulo preexistente `native-image-guard.js` e `options.js`/`options.html` à lista `EXTENSION_IDENTITY_FILES`.

A flag de compatibilidade existente continua válida: `localStorage.setItem('sentra_shell_stream', 'off')` e reabrir a janela força o caminho legado. Remover a chave restaura o feed. O rollback de apresentação não apaga o journal protegido nem altera comandos/recibos.

## Pendências explícitas do P1

1. Demonstrar p95 ≤ 300 ms em host isolado, com série estatística e no aplicativo instalado. O ensaio temporário com mesma carga passou em três rodadas após a correção do handle (239,98/252,65/251,76 ms), mas isso ainda não certifica o produto instalado ou um host isolado.
2. Executar dez inferências reais respeitando contas/provedores e vinte identidades de equipe, com isolamento, revogação e expiração. O ensaio atual é sintético e usa um proprietário.
3. Validar suspensão do Windows e extensão instalada com relay real. A parada/retomada de um worker MV3 real, o reinício gracioso e o crash completo do navegador com perfil isolado já passaram nos ensaios descritos acima; não equivalem a entrega atestada de uma resposta Web nem ao disparo real de `onStartup`.
4. Validar falhas combinadas de gateway, relay e produtor junto ao broker. A queda abrupta do broker em processo próprio, retomada de cursores e rotação de autenticação já passaram no ensaio abaixo; isso não cobre toda a cadeia de inferência.
5. Integrar e validar a recuperação paginada na UI instalada. O backend já preserva o corpo completo dentro do orçamento declarado e publica referência imutável, em vez de cortar antes do journal. A janela agora respeita unidades UTF-16; páginas usam pontos de código Unicode e explicitam a quota de bytes. Permanecem pendentes a apresentação integral, a experiência de falha/expiração e a prova do percurso instalado.
6. Formalizar/medir perda de bytes ainda não persistidos na queda abrupta do produtor; o requisito de zero perda comprovado aqui se restringe aos eventos cujo commit terminou.
7. Homologar o adaptador PostgreSQL nos mesmos fluxos. O cache coalescido local não se aplica a ele.

O objetivo global do ASTRA permanece ativo. Esta entrega não deve ser tratada como conclusão do plano integral.

## Fechamento da revisão: broker, referências e prosa

`python -B tests/qa/astra_broker_restart.py` passou com um `CanvasServer` em processo próprio, produtor sintético separado, dez conversas e vinte leitores HTTP/SSE mais vinte observadores DOM. O harness mata somente seu broker temporário, mantém o produtor vivo e reinicia o servidor na mesma porta/armazenamento com outra sessão. O bearer antigo recebe 401; a nova sessão, entregue pelo canal privado de teste, retoma a leitura sem novo envio. As dez operações em andamento permanecem honestamente `UNCERTAIN`. O corpo longo de **336.017 pontos de código**, incluindo Unicode e `[[wiki]]`, foi reconstruído pela API paginada e conferido por SHA-256. O contador de despacho permaneceu igual. Evidência: `.tmp/astra-broker-restart/report.json`.

A primeira execução real encontrou uma falha: o coletor republicava a janela após o restart, mas descartava sua referência completa. O relatório anterior foi preservado em `report-before-reference-fix.json`. A correção permite carregar uma referência existente apenas pelo caminho interno de interrupção, comparando a head protegida, operação, revisão, janela, offset, Space, raiz de retenção e manifesto na mesma transação. Referências arbitrárias de upstream, outra operação ou janela alterada são recusadas. Não regrava o corpo, não executa efeitos e não transforma `UNCERTAIN` em conclusão.

O helper `sentra_core/model_prose.py` substitui o corte genérico em `[[` nos caminhos desta frente. Preserva `[[wiki]]`, `[[ação]]`, texto repetido e combinações legítimas; retém somente prefixos ambíguos ou cabeçalhos da gramática formal de diretivas, evitando mostrar argumentos internos incompletos. O agente principal integrou o helper no CLI e fez a UI consumir a projeção sem reparsá-la, preservando janela e hash. Esses arquivos do CLI/apresentação foram integrados por ele, não por esta frente.

A regressão final conjunta passou com **71 Python em 89,73 s**, usando `test_model_prose.py`, `test_shell_stream_journal.py`, `test_shell_stream_content.py`, `test_sentra_shell_live_preview.py`, `test_shell_runtime_turn_memory.py`, `test_shell_web_preview.py` e `test_canvas_web_peer_transport.py`, com `-W error::pytest.PytestUnhandledThreadExceptionWarning`. Os dois casos adicionais de `test_shell_draft_prose.py` passaram em **7,63 s**. A regressão de transporte e extensão passou com **23 JavaScript**; inclui referência longa, janela astral e identidade de cursor. São conjuntos separados, sem contabilizar testes de outras frentes.

## Medição final das fontes entregues

`python -B tests/qa/astra_stream_resilience.py --label broker-prose-final` passou: **10 produtores sintéticos, 20 leitores HTTP/SSE, 20 observadores DOM multiplexados, 60 fragmentos e 120 pinturas**. Todos os leitores receberam os sessenta fragmentos. Emissão nativa → dupla RAF: p50 **187,65 ms**, p95 **248,85 ms**, máximo **251,97 ms**. A retomada após online levou **109 ms**, preservando dez heads; nenhum prompt foi repetido. Emissão → commit teve p95 143,92 ms, ingestão → commit 117,03 ms e commit → pintura 118,76 ms; esses percentis não são somáveis.

Relatório: `.tmp/astra-stream-resilience/report-broker-prose-final.json`. O harness conservou carga, probes e critério; somente ampliou a lista de arquivos de proveniência, passando ao hash `7f1f830c9270673248a1fe0ade6128dd9e00302607db8d5206d2b055e29cce5c`. Fontes registradas: `shell_stream.py=6d1af3432f3264ec3b6a0ff173e9cdcaebe91e29a4d93949710c4524eb3a7b96`, `shell_live.py=182315489b731f0c66febaa2f5643f7b75c6eef4c9fa6c89d660790eddb22798`, `shell_runtime.py=94445d2a06e7a86ce0e4a685bcfb3ed0a6768bc49bdd28bbe8000827a6e224a3`, `model_prose.py=a6d755d61f16ecd42ea7240fd969f0e509ca59023e17de9618ab9a67c4ca93a8`. O JSON inclui os demais hashes.

As amostras inicial/final não encontraram Cargo/rustc, mas o host é compartilhado e não há certificação de isolamento. Este ensaio mede marcadores curtos, transporte fonte e DOM de teste, sem Markdown completo, inferência real, vinte identidades de equipe ou aplicativo instalado. A prova de reinício usa executor sintético e renovação da sessão pelo canal de controle de QA; não homologa o fluxo de credenciais da instalação. Não se promete recuperar bytes produzidos sem commit durante a indisponibilidade. UI instalada, contas reais, suspensão do Windows, falhas combinadas e PostgreSQL continuam pendentes; o goal P1 permanece ativo.

## Consulta de envio sem redispatch

Na revisão conjunta foi identificado que o botão antigo `send(true)` usava `message_send` novamente. Se a intenção original nunca chegasse ao servidor, essa consulta poderia iniciar um efeito novo. Isso é independente do bloqueio de navegação anterior à tela de chat informado pelo usuário.

Foi acrescentado `message_request_status` ao Canvas e `inspect_message_request` ao coordenador. O contrato exige exatamente projeto, Space, conversa e chave original. Não recebe conteúdo/anexos, não chama dispatch nem reconciliação de runtime e não insere requests, mensagens, eventos, Operations ou recibos. Ausência resulta em `unverified`, nunca em autorização para reenviar.

Resposta: `{status, request_key, found, confirmed, automatic_retry:false, resent:false, message?}`. `confirmed:true` exige que a mensagem canônica e o ACK armazenado coincidam na chave/conversa e estejam num estado de aceitação conhecido; `confirmation_kind:'stored_message'` não afirma conclusão da inferência. Um ACK divergente, claim incompleto ou mensagem incerta conserva `confirmed:false`.

`src/shell-message-request-status.js` oferece `inspectMessageRequest(bridge, originalPending, scope)` e `confirmedMessageRequest(value, originalPending, scope)`. O helper constrói somente o seletor de leitura, inclusive quando `scope` contém campos extras. A frente de experiência recebeu o contrato para substituir o ramo `send(true)`; `shell-conversation.jsx` não foi editado por esta frente.

Validação adicional: **7 Python passaram em 26,56 s** (`test_shell_message_request_status.py` e `test_shell_conversation_receipt_read.py`); **5 JavaScript passaram** (`shell-message-request-status.test.mjs`). Os testes comparam as tabelas do journal antes/depois e impedem dispatch/reconcile, além de executar o bridge real para verificar a classificação `readOnly:true` mesmo usando POST como transporte. Esse conjunto é adicional aos 29 Python e 20 JavaScript acima.

## Restauração independente da página de conversas

Foi acrescentado `conversation_get` ao conjunto de leituras do coordenador e do bridge. Contrato: `bridge({action:'conversation_get', project_id, space_id, conversation_id})`; `envelope.value` é a conversa canônica diretamente, com seus IDs, título, Dot, revisão e datas. Não retorna `items`, não gera chave de mutação e não cria outra conversa.

Essa ação não chama a listagem nem a migração de Spaces/Dots/equipes. A resolução mantém os gates atuais do projeto/proprietário, valida o Space e confere os IDs também no corpo protegido. Cada leitura consulta a entidade atual: revisão alterada aparece imediatamente e uma entidade removida deixa de ser encontrada. Nenhum cache visual, conversa de outro proprietário ou primeira página concede autoridade.

Validação: **6 testes Python passaram em 17,53 s**, incluindo uma conversa real fora de Home e da primeira página com 56 entidades protegidas (55 registros de paginação semeados na fixture), inexistência, outro Space/projeto/proprietário, payload extra, revisão, remoção, bearer revogado e identidade inconsistente no armazenamento. O teste verifica que o journal permanece idêntico e bloqueia qualquer tentativa de chamar `_list` ou `_migrate` durante o lookup. **2 testes JavaScript passaram** usando o bridge real para provar leitura sem chave de mutação e recusa sem operação pendente. A frente de experiência integra o estado selecionado e a navegação restaurada.
