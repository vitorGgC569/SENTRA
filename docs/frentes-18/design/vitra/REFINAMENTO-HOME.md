# Refinamento da Home — Vitra — 2026-10-13 05:58

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-055848/`. A captura `20261013-053624` permanece no lugar. `published`, `broker_restarted` e `homologated` falsos. Broker PID 6836. `page_errors`, `http_errors`, `blocked_requests` e `candidate_changed_during_review` vazios.

Bytes: `desktop.js` sha256 `9b012ef1b1531dfc9c878b34448b9b489f8a523a9c6bb83eb5e1df6c38d6033a`, 2055404 bytes. `desktop.css` sha256 `08270e81d6d036ea82d38ab9bbbafaccfc541662c63ef8579236f87de06f7320`, 123537 bytes. `desktop.html` sha256 `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`, 1062 bytes. `manifest.json` sha256 `a5393ae8c4987d6f7f16b8bda3a52ac3a0f730b6c1ae10dd2f6f2d1fb8cda2d7`, 13934 bytes.

Os doze PNG foram lidos. A regressão da leva 05:36 continua de pé nestes bytes: um cartão de envios, seis Dots visíveis, menu absoluto com três rótulos, Home termina em x 371 e Em andamento começa em x 391, vista reduced com `runningAnimations` 0. O relatório marca Esc e Enter. Isso não fecha o redesign.

## O que esta etapa moveu

A busca ocupa a largura da coluna, nas três medidas. O antigo botão “Abrir” virou o texto “Abrir o Space”, na mesma linha da pergunta. O grupo de 45 registros ganhou chevron e, aberto, continua uma linha: “Conversa com Sentra Aqrt”.

## O que o pixel ainda mostra

A primeira leitura continua sendo busca, título “Oxta” e a pergunta. O trabalho vem depois do cartão de falha. Em 1440 “Abrir o Space” fica na margem direita, sem corpo de botão, longe do título. Em 390, com o menu Atualizar aberto, o painel cobre a pergunta e corta “Abrir o Space”.

As seis linhas dizem só Ativo, com o estado na borda direita e o meio vazio. As conversas visíveis repetem “Conversa com Sentra Aqrt”; a data é o único segundo fato. Nenhum PNG mostra anel de foco na busca, no CTA ou numa linha. O teclado fotografado é o do menu e o do grupo.

## Veredito da etapa

O redesign substancial não está concluído. Não homologa. Não promove.

## Foco nos mesmos bytes — 2026-10-13 06:07

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-060755/`. `20261013-055848` e `20261013-053624` permanecem no lugar. O `desktop.js` continua `9b012ef1b1531dfc9c878b34448b9b489f8a523a9c6bb83eb5e1df6c38d6033a`. CSS e HTML iguais aos da etapa 05:58. `published` falso. Broker PID 6836. `page_errors` e `blocked_requests` vazios.

Tab chega à busca, a “Abrir o Space” e à linha do Dot. A busca por “Sentra Aqrt” deixa um Dot visível e, limpa, restaura seis. Nenhum Space nem Dot foi acionado.

O anel da linha está cortado nas quatro vistas: `candidate-focus-dot-1440.png`, `candidate-focus-dot-768.png`, `candidate-focus-dot-390.png` e `candidate-focus-dot-390-reduced.png`. O que aparece é uma linha branca na base de “Sentra Aqrt”. O computed style é `outline: 3px solid rgb(255, 255, 255)` com `outline-offset: 2px`. `.shell-home-sheet` tem `overflow: hidden` em `shell-integrate.css`. O offset de 2 px sai da folha e some. O critério da linha é o anel de 3 px visível nos quatro lados.

A busca e “Abrir o Space” mostram anel de 3 px, visível, na cor `rgb(176, 176, 176)`, não branco. A regra escura de `desktop.css` pinta `outline-color: #b0b0b0` em `:focus-visible`.

Os déficits de hierarquia da etapa 05:58 continuam nestes bytes: título antes dos Dots, CTA na margem, Ativo repetido na borda, conversas repetidas. O foco da linha não passa. Não homologa. Não promove.

## Captura 06:26 — FAIL no 390

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-062616/`. `desktop.js` sha256 `0c6c31c1ad33fca091626035ebf544422d244247daa5eea03e7ce055b58261d6`, 2058994 bytes. `desktop.css` sha256 `00a5aab5aa6896b650e9d08991d4d3b559f3813c607f78ffd3e168cc688326af`, 125829 bytes. HTML continua `1c959e72…`. `published` e `broker_restarted` falsos. Broker PID 6836. `page_errors` e `blocked_requests` vazios.

O anel da linha passou a `outline-offset: -4px` e aparece nos quatro lados em `candidate-focus-dot-1440.png`. A busca e “Abrir o Space” usam anel branco de 3 px, visível. Em 1440 e em 768 o contexto cabe entre o nome e Ativo: “12 conversas · 12/10/2026” não invade o nome. As conversas recentes agrupam por título, com a contagem ao lado.

FAIL em 390. A leitura que vale é só `candidate-home-390.png` desta pasta, com o `report.json` ao lado. As pastas `20261013-053624`, `20261013-055848` e `20261013-060755` não entram. As linhas medem cerca de 52 px. “Testando Advanced” cobre a frase. A frase cobre “Ativo”. O anel de foco desta captura não é o defeito.

A correção que a próxima captura tem de mostrar: nome e frase empilhados numa coluna flexível, a linha até 56 px, Ativo e o chevron fora dessa coluna. A frase real permanece (“12 conversas · 12/10/2026”, “1 envio não confirmado”). Não vira “ocupado” nem “Trabalhando”. Cada uma das duas linhas é uma só, com reticências se não couber. “Ativo” fica inteiro. `scrollWidth` não substitui essa leitura.

O mascote `active` ainda desenhado como execução neste bundle fica fora desta correção. O contrato de execução validada é do Pebble e a ligação é da Lumen, depois. Não homologa. Não promove.

## Captura 06:40 — a colisão de 390 fecha

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-064043/`. As pastas anteriores permanecem. `desktop.js` sha256 `8e4c5ca214fa9d58e248019c2bbd0b8e5c641ee8165f04db3d2c96c349bc6cb9`, 2059629 bytes. `desktop.css` sha256 `b9999b1d7f07ddb8e52cf229f0eb81125900ef23b6db6c3fb88000f07aecc81e`, 126832 bytes. `published` e `broker_restarted` falsos. Broker PID 6836. `page_errors` e `blocked_requests` vazios.

Em `candidate-home-390.png` e no reduced, o nome e a frase estão em linhas próprias. “Testando Advanced” termina em x 204 e a frase “12 conversas · 12/10/2026” começa na linha de baixo, em x 72. “Ativo” começa em x 302. O passo da linha é 52 px. O chevron fica depois de Ativo. As frases reais permanecem. Os seis `mascotState` estão `idle`.

Em 1440 e em 768 a linha continua única: nome, frase e Ativo em faixas que não se cruzam. O anel do Dot contorna a linha. A busca e “Abrir o Space” mostram anel. O menu aberto tem os três rótulos inteiros.

Isto fecha a colisão de 390. Não fecha o redesign. O título ainda precede os Dots, “Abrir o Space” continua texto na margem, as seis linhas dizem só Ativo, e em 390 a conversa agrupada corta o título em “Conversa com Se…”. O menu aberto cobre a busca. Não homologa. Não promove.

## Fechamento estrito

A pilha de 390, o anel de foco e o `mascotState` `idle` dos seis Dots `active` ficam aceitos só em `desktop.js` `8e4c5ca214fa9d58e248019c2bbd0b8e5c641ee8165f04db3d2c96c349bc6cb9` e `desktop.css` `b9999b1d7f07ddb8e52cf229f0eb81125900ef23b6db6c3fb88000f07aecc81e`, da pasta `20261013-064043`. Sem publicação e sem restart. Os snapshots não se reescrevem. Não há nova captura desta regressão.

A etapa seguinte é a composição da Home: título antes dos Dots, “Abrir o Space” na margem, seis linhas só com Ativo, título de conversa cortado em 390 e menu aberto sobre a busca. Canvas e Computador continuam fora. Não promove.

## Composição 07:07 — aceite parcial

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-070729/`. A captura `20261013-070554` não entra. `desktop.js` sha256 `c4a159ee6fe7ff9af840b666157653cff8d2f70faf338002daef9b59842a265f`, 2060336 bytes. `desktop.css` sha256 `adcb93b90df5303fbba894b380c72dc0e6a4575a6acf226b836ec23f4c64a11f`, 127169 bytes. HTML `1c959e72…`. Manifest `58d9e4917a688d6e1a8256c012f9ffd56075adb9f16ed44ea8487893f109f2e4`. Broker PID 6836. `published` e `broker_restarted` falsos. `page_errors`, `blocked_requests` e `candidate_changed_during_review` vazios.

No quadro fechado, “Abrir o Space” fica na mesma linha do apoio em 1440 e em 768. Em 390 o CTA quebra à esquerda, debaixo de “1 envio não confirmado, em 45 registros”. A busca fica abaixo do cartão e acima dos seis Dots. A pilha de 390 permanece: nome, frase, Ativo e chevron sem se cruzar. O anel aparece na busca, no CTA e na linha. O primeiro grupo abre e fecha pelo teclado. Os sete itens mostram data, hora e o Dot, de `13/10/2026, 06:54` a `11/10/2026, 12:46`, todos Sentra Aqrt. A conversa não abre.

Em 390, com Atualizar aberto, o painel cobre o apoio e “Abrir o Space”. Os três rótulos do menu ficam inteiros. Em 1440 o CTA continua visível ao lado do apoio.

Isto aceita essa composição parcial. Não aceita o redesign: o título ainda lidera, as seis linhas dizem só Ativo e o cartão de envios continua acima dos Dots. Não homologa. Não promove.
