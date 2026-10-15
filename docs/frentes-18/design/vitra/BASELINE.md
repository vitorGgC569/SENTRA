# Baseline visual — Vitra — 2026-10-13

Crítica do shell de produção capturado por Codex. Não é homologação. Fixture, `lumen-flow.html` e as portas 4178 e 4188 ficam fora desta leitura.

## Identidade da captura

| Campo | Valor |
| --- | --- |
| Superfície | Shell de produção. `baseline.json` marca `fixture: false` e `status: CAPTURED_PRODUCTION_SHELL`. |
| URL viva declarada | `http://127.0.0.1:50282/desktop.html`. `shell-home.html` nessa porta responde 401 e não é a superfície lida. |
| Broker | PID 6836, porta 50282, runtime `cd86d23b412f46be948bfbe0c12ec197`. Bate com `baseline.json`. |
| Quando | `2026-10-13T03:45:13-0300`. |
| Versão | Lumen declara 0.1.0. O título medido na captura é `SENTRA Desktop`. A versão 0.1.0 não está desenhada nos PNG. |
| Assets da captura | `desktop.js` sha256 `5f6958442d2f8f0da3ef0b8a10178c695f85b0acb2d7173f6a18688b83789bed`, 2021555 bytes. `desktop.css` sha256 `2adabddc5ccade371c957318e94fed2984371c9e36dee77410a5473282eb1b7d`, 112039 bytes. Os dois batiam com o checkout no instante da captura. |
| Erros | `page_errors` vazio, `http_errors` vazio, `blocked_mutations` vazio. `scrollWidth` igual a `innerWidth` nos três viewports. |
| Provas | `.tmp/codex-closure-20261013/production-home-1440.png` (1440×920), `production-home-768.png` (768×1024), `production-home-390.png` (390×844), `baseline.json`. |

A captura das 03:45 (sha `5f695844…`, 2021555 bytes) fica como quadro de carregamento. O recorte seguinte substitui a conclusão sobre Dots ausentes.

`reducedMotion` medido: `false` nos três. As imagens são stills. Movimento e teclado não foram exercidos nesta leva.

## Captura 03:53 — prova atual da Home

| Campo | Valor |
| --- | --- |
| Quando | `2026-10-13T03:53:24-0300` |
| Pasta | `.tmp/codex-closure-20261013-application/` |
| `desktop.js` | sha256 `7a5d7cac530a9e5318c2b175cf665be5e451396197a6304c5ca5d2852f7f1b4d`, 2035034 bytes, `matches_checkout_asset: true` |
| `desktop.css` | sha256 `3065bda68ca82389a56128b3f76f358b4f0e51ca523da19b9a9a066831db8d4e`, 112951 bytes |
| Bridge | Todos os envelopes registrados com `ok: true` e `error` vazio, inclusive `home`, `dot_list`, `conversation_list`, `space_get`, `events`, `document_list`. |
| Erros | `page_errors`, `http_errors` e `blocked_mutations` vazios. `scrollWidth` igual a `innerWidth` em 1440, 768 e 390. |
| Dados | As três larguras listam os mesmos headings de Dots (Sentra Aqrt, dasdas, Teste, testegpt6, Testando Advanced) e 189 botões. `reducedMotion` continua `false`. |

O PNG de 390 desta leva mostra a Home com os seis Dots recentes. A sidebar está fechada. Não há faixa de operação não confirmada nesse quadro assentado. O vazio e o aviso da captura das 03:45, por volta de 2 s, foram um quadro transitório de carregamento. Não provam ausência de Dots.

### Transição carregando, erro, dados

`shell-app.jsx` começa com `loading` verdadeiro e, no `finally` de `refresh`, passa a falso mesmo quando `home` lança. O `catch` grava `setError`. Com `loading` falso, projeto definido e `home` ainda vazio, a Home pinta ao mesmo tempo o `FailureNotice` e o texto de projeto sem Dots. O aviso usa a cópia de envio não confirmado (`A operação não foi confirmada`, `Não repita o envio`) quando a mensagem cai no ramo incerto de `explainFailure`. Uma leitura que ainda não assentou fica com a cara de uma mutação que não pode ser repetida. Na captura das 03:45 esse aviso também reaparecia em `Solicitações de aprovação`.

Os envelopes das 03:53 estão `ok: true`. A falha desenhada aos 2 s não era o estado do projeto. Critério: enquanto `home` não assentou, a tela mostra só `Consultando seu trabalho…`. Um erro de leitura diz que a consulta não chegou e oferece consultar de novo. Não afirma que o projeto está vazio. Não usa a cópia de envio não confirmado. Não duplica o mesmo aviso noutro cartão. O vazio só aparece depois de um `home` com `ok: true` e listas vazias.

## P0 — Dots recentes

Visível em 1440 e em 768, projeto Oxta, Home. Seis botões em `Dots recentes`: Sentra Aqrt, testegpt6, Testando Advanced, SubAgenteGPT6, Teste, dasdas. Cada botão mostra o nome e a palavra `active`. Nada mais.

O markup que produz essa linha é o botão de `shell-home-board.jsx`: `strong` com o nome e `small` com `row.status`. `statusOf` devolve o estado cru, em minúsculas. A tela repete `active` seis vezes.

### Altura e repetição

Os seis botões ocupam o resto da primeira tela de 920 px, debaixo do hero. Aprovações, Entregas e Falhas existem no DOM (`homeColumns` 338,7 px × 3 em 1440) e ficam abaixo dessa pilha. Cada linha é um retângulo largo com o texto no meio e o lado esquerdo vazio: sem mascote, sem hora, sem última conversa, sem ação. A sidebar já lista os mesmos Dots. A linha não acrescenta um fato.

Em 768 a coluna medida é 464 px e a pilha é a mesma. O chip `Em andamento` na barra de cima quebra em duas linhas (`Em` / `andamento`).

### Contraste

Tema escuro do checkout: painel `#202020`, fio `#343434`, texto `#ededed`, meta `#aaaaaa`. O nome em `#ededed` sobre `#202020` lê. O fio `#343434` sobre `#202020` fica em cerca de 1,3:1, abaixo de 3:1 para separação de controle. No PNG as linhas se fundem com a seção. O estado `active` usa a cor de meta, igual nas seis linhas, e não separa trabalhando, espera, conclusão e idle.

### 390 px

No quadro assentado das 03:53 a sidebar está fechada, a coluna mede 350 px e `scrollWidth` é 390. Os seis cards aparecem, com o mesmo nome centralizado e a mesma palavra `active`. O chip `Em andamento` também quebra em duas linhas nesta largura. A altura da pilha continua a empurrar Aprovações para baixo de 844 px.

### Foco

Nenhum PNG mostra linha focada. O DOM da Home tem 188 botões em 1440 e em 768. O anel do checkout é `outline: 3px solid` com offset 3 px (`#a7b7f0` no claro; no escuro a cor do anel passa a `#b0b0b0`). Isso não foi percorrido com Tab. Aceite exige o percurso, não a existência da regra.

### Reduced-motion

A captura declara `reducedMotion: false`. Com movimento permitido, `.shell-home-board > *` sobe 8 px em `sentra-rise`. A lista inteira é um filho só, então a seção sobe uma vez. O caminho `prefers-reduced-motion: reduce` zera animação em `.opendots-shell *` e não foi fotografado.

## Critério para a próxima captura

Home do mesmo broker, `desktop.html`, com a lista populada. Três PNG novos: 1440, 768 e 390 com sidebar fechada de propósito. Mais um still com foco no segundo Dot recente e um still com `prefers-reduced-motion: reduce`.

1. Cada linha de Dot recente tem no máximo 56 px de altura, nome alinhado à esquerda e um segundo fato visível (hora, conversa ou estado traduzido). Seis linhas cabem sem empurrar Aprovações para fora de 1440×920.
2. Os estados visíveis diferem na palavra e na cor. `active` cru não permanece. Idle, trabalhando, espera e conclusão são distinguíveis a 390 px.
3. O fio da linha contra o painel mede pelo menos 3:1. Nome contra o fundo da linha mede pelo menos 4,5:1.
4. A 390 px, com sidebar fechada e lista populada, `scrollWidth` continua igual a `innerWidth`. A linha não estoura. O aviso de operação não confirmada aparece uma vez.
5. Tab chega a cada botão da lista. O anel de 3 px fica inteiro, visível contra `#202020` e contra o fio da seção, sem depender de hover.
6. Com `prefers-reduced-motion: reduce`, as linhas aparecem na posição final. Sem subida, sem bob, estado ainda legível.

Fora deste critério: PNG do mascote, hash de SVG, porta 4188, `lumen-flow.html`.

## Home, além dos cards

O hero (`O que vamos fazer hoje?` mais o mascote com halo tracejado) é a primeira leitura. O trabalho operacional fica abaixo dos seis cards. O halo tracejado está desenhado no hero nos três PNG; o still não prova o ciclo de animação.

A 768 a sidebar permanece aberta e a coluna útil mede 464 px. O hero e o mascote dividem essa coluna.

## Canvas e Computador

Esta leva não tem PNG de produção dessas duas superfícies. Não há aceite nem recusa por pixel. A próxima leva precisa de 1440, 768 e 390, com foco e reduced-motion, no mesmo `desktop.html`.

## Orbe e Cadencia

No momento desta leitura não havia arquivos em `docs/frentes-18/design/orbe/` nem em `src/experience/cadencia/`. Os dois terminais ainda compunham. Não há versão integrada para criticar. Proposta escrita sem captura no shell 50282 não substitui os PNG.

## Preview do mascote

Medição em `http://127.0.0.1:5173/desktop-assets/pebble-preview.html` e `?reduced=1`, vite PID 18136. É preview, não o shell 50282. Resultado: PASS para o recorte medido (halo idle em opacity 0, working no mesmo nó com opacity 1 e `translate(0 0)`, reduced-motion parado com pose still diferente do idle, seletor em `img`). Não homologa o mascote na Home. O hero da captura 03:53 continua com o halo tracejado sempre visível.

## Integração

Orbe e Cadencia não têm composição aplicada nesta Home. `docs/frentes-18/design/` só contém este dossiê. O PNG das 03:53 repete densidade, hierarquia, `active` cru e o chip quebrado em 768. Hash do próximo recorte: `7a5d7cac530a9e5318c2b175cf665be5e451396197a6304c5ca5d2852f7f1b4d`, 2035034 bytes. Nenhum build a mais entra nesta crítica.

## Preview Cadencia — 5173, não é o shell

URL confirmada: `http://127.0.0.1:5173/desktop-assets/cadence-preview.html`, vite PID 18136, portal 1440×904. O próprio preview diz que não é o shell 50282. Não houve `npm run build`. O `desktop.js` servido continua o da captura 03:53.

No preview, antes de assentar, a árvore mostra só `Consultando seu trabalho…`. O quadro de leitura falha mostra `A consulta não chegou.` e `Consultar de novo`, sem a lista. Isso cumpre a cópia no preview.

A Home assentada do preview falha: as seis linhas medem 33 px e a palavra visível é `Trabalhando` nas seis. O nome do Dot não aparece como texto claro na linha. Não há estados diferentes. Não é a Home de produção.

No fonte, `shell-app.jsx` só mostra o quadro depois de `homeSettled`. Uma falha da primeira leitura não pinta o vazio. Uma leitura que falha depois da primeira ainda deixa `homeSettled` verdadeiro, então o quadro antigo permanece. `FailureNotice` continua na página para os outros erros. `cadence.css` limita a altura da linha e não troca `active`, não corrige o chip de 768 nem o fio `#343434`.

## Captura 04:20 — Canvas, Computador e o que cada arquivo mostra

| Campo | Valor |
| --- | --- |
| Quando | `2026-10-13T04:20:38-0300` |
| Pasta | `.tmp/codex-closure-20261013-canvas-computer/` |
| Superfície | `fixture: false`, `status: CAPTURED_PRODUCTION_SHELL`, `product_mutations: false` |
| Broker | PID 6836, porta 50282, runtime `cd86d23b412f46be948bfbe0c12ec197` |
| `desktop.js` | sha256 `e9d3f16230f5ad4d71571a617cbf1dd15752e54da7f2d942cb14f36e4b867f65`, 2043655 bytes, `matches_checkout_asset: true` neste instante |
| `desktop.css` | sha256 `a7a95e688423a312e23693ec122fb298adb7c1d999456e95e90717bcd754068c`, 117252 bytes, `matches_checkout_asset: true` |
| Bridge | `dot_canvas_get` e `dot_vm_images` com `ok: true`. `page_errors`, `http_errors` e `blocked_mutations` vazios |
| Conversa | Dot e conversa já existentes de Testando Advanced. Sem `newConversation` |

O nome do arquivo não é a superfície. Leitura por pixel:

- `production-home-1440.png` e `production-home-768.png` são a leitura da Home que não assentou: “A consulta não chegou.”, “A leitura da Home não assentou.”, “Consulte de novo. Esta falha não esvazia o projeto.” O trilho diz “Nenhum Space neste projeto.” Em 768 há um segundo aviso, “Não foi possível consultar o runtime local.” Não são a Home dos seis Dots e não são a conversa. Os headings “Seu trabalho”, “Detalhes”, “Solicitações de entrada” e “Atividade e recibos” estão no DOM do painel contextual; o pixel desses dois quadros é o cartão de leitura.
- `production-home-390.png` é a Home assentada. Hero com halo tracejado, seis linhas com a palavra Disponível, migalha cortada em “Hon” contra “Em andamento”, e o projeto “Oxta” com “Em execução”.
- `production-canvas-1440.png` e `production-canvas-390.png` são o Canvas de Testando Advanced: sete legendas com contagem 0 e o parágrafo inteiro, mais um nó. Em 390 as legendas ocupam a vista e o nó fica cortado.
- `production-canvas-768.png` é outro quadro: “A operação não foi confirmada” junto de “Carregando o Canvas deste Dot…”. `dot_canvas_get` desta leva está `ok: true`. Este arquivo não prova Canvas vazio em 768.
- `production-computer-1440.png`, `production-computer-768.png` e `production-computer-390.png` são a conversa existente com o painel do computador aberto. A faixa pinta “Ainda não criada” e “VirtualBox indisponível” no mesmo quadro em que o desempenho “ainda não foi consultado”. Em 768 as frases cortam. Em 390 a migalha corta “Con” contra “Em andamento”.

Detalhe e redesenho: `docs/frentes-18/design/vitra/CANVAS-COMPUTADOR.md` e `ORBE-COMPOSICAO.md`.

## Estado

Não homologado. O asset servido nesta última captura é `e9d3f162…`, 2043655 bytes. A Home assentada com dados nas três larguras continua sendo a das 03:53; nesta leva de 04:20 a Home assentada só aparece no arquivo de 390, e pinta Disponível. Foco e reduced-motion seguem sem still no shell 50282.
