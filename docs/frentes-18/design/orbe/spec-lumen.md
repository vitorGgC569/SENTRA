# Bancada — especificação para Lumen

Revisão depois do render `.tmp/codex-orbe-review-20261013/`. Zero erro de JS e zero overflow. A composição funcional fica. O aspecto de wireframe não é a direção final e ainda não é PASS.

O que sai do produto:

- Grade de fundo na Home e no Computador.
- Fio claro em volta de cada card. A lista é uma folha só, `#17191e`, sem contorno `#8b9098`.
- Rótulos em caixa alta, faixa de vocabulário e três caixas vazias repetindo a mesma ausência.
- Qualquer frase de dossiê dentro do quadro: captura, PNG, composição, sem ação, não capturado, nenhum nesta captura.

O que fica:

- Foco tipográfico: Oxta a 40 px (32 px em 390), a frase do produto `O que vamos fazer hoje?`, ação `Abrir`.
- Uma linha só quando aprovação, entrega e falha estão vazias: `Nenhuma aprovação, entrega ou falha nesta consulta.` Essa linha não é a Home quando há dezenas de pendências. Pendência real agrupa por conversa ou Operation, com contagem e detalhe gradual. O histórico permanece. Nenhum item incerto vira sucesso.
- Seis Dots na ordem da captura, 52 px, nome à esquerda, **Ativo** à direita, chevron. `active` não vira Trabalhando.
- Trilho 256 px, ícones de 16 px no mesmo traço, navegação com a página atual em preenchimento `#22262e`.
- Cápsula sem pill de token. `Em andamento` é texto de 13 px, numa linha, cor `#9b9ba3`. É o rótulo do run, não uma tarefa.
- Anel de teclado: 3 px `#ffffff`, offset 2 px, só em `:focus-visible`.
- Movimento 200 ms, `cubic-bezier(0.22, 1, 0.36, 1)`, sem bounce. Reduced-motion zera.

Canvas e Computador seguem a captura `2026-10-13T04:20:38-0300` em `.tmp/codex-closure-20261013-canvas-computer/`. O Dot visível é Testando Advanced. A navegação foi de um Dot e de uma conversa existentes, com guarda só leitura e `blocked_mutations` vazio. A captura não homologa apertar as ações. O protótipo anterior, com Sentra Aqrt, “Não capturado” e Pausar/Desligar/Assumir, não substitui esse fluxo.

Semântica, inalterada: `active` é ciclo de vida e mostra Ativo. Trabalhando só com WorkItem ou Operation de execução atual validado. `running_terminals` 0 e `provider_ready` unverified. O run `RUNNING` não prova tarefa.

Direção para integrar no shell. Não está homologada. Não é o shell da porta 50282. Não rode `npm run build`. Não feche a porta 4188. Não edite `shell-mascot.jsx`, `src/dot-motion.js`, `src/assets/dot-motion/` nem `src/assets/opendots/*.png`.

Composição de referência: `docs/frentes-18/design/orbe/index.html`. Abra no navegador e use os controles 1440, 768, 390, Home, Canvas e Computador.

## Baseline que esta direção usa

Captura assentada `2026-10-13T03:53:24-0300`, pasta `.tmp/codex-closure-20261013-application/`.

- `desktop.js` sha256 `7a5d7cac530a9e5318c2b175cf665be5e451396197a6304c5ca5d2852f7f1b4d`, 2035034 bytes, `matches_checkout_asset: true`.
- Broker pid 6836, porta 50282, runtime `cd86d23b412f46be948bfbe0c12ec197`.
- `page_errors`, `http_errors` e `blocked_mutations` vazios. `scrollWidth` igual a `innerWidth` em 1440, 768 e 390.
- Home com dados nas três larguras. Seis Dots recentes, nesta ordem: Sentra Aqrt, testegpt6, Testando Advanced, SubAgenteGPT6, Teste, dasdas. Projeto e Space Oxta. O chip da barra diz `Em andamento`. O status cru de cada Dot na captura é `active`.
- Coluna medida: 338,7 px × 3 em 1440; 464 px em 768; 350 px em 390.
- O PNG de 390 das 03:45 (sha `5f695844…`, 2021555 bytes) é quadro transitório de carregamento. Não desenhe a Home vazia a partir dele.

Crítica de Vitra: `docs/frentes-18/design/vitra/BASELINE.md`. O visual servido foi reprovado: lajes altas, `active` cru, hero de 190 px acima do trabalho, chip `Em andamento` quebrado em duas linhas em 768 e 390, fio `#343434` sobre `#202020` em 1,31:1.

## O que a primeira tela passa a ser

A primeira leitura deixa de ser o poster com mascote e deixa de ser o wireframe do render `.tmp/codex-orbe-review-20261013/`. A ordem, de cima para baixo, dentro de `.shell-content`:

1. Barra cápsula, 48 px, raio 999 px, fundo `#1a1c22`, sem fio. Sombra `0 8px 24px rgba(0,0,0,.28)`.
2. Busca, 40 px, raio 999 px, ícone à esquerda, sem rótulo visível. O `aria-label` continua `Buscar no trabalho`.
3. Foco tipográfico, sem placa e sem sobrancelha. Título `Oxta` a 40 px, peso 640, tracking −0,035 em. Em 390, 32 px. Apoio `O que vamos fazer hoje?` a 16 px, cor `#9b9ba3`. Ação `Abrir`, que chama o `onOpenSpace` já existente.
4. Uma linha, cor `#6f7480`, quando os três registros estão vazios: `Nenhuma aprovação, entrega ou falha nesta consulta.`
5. Título `Dots recentes` em sentença, 15 px, peso 620. Não use caixa alta.
6. Uma folha `#17191e`, raio 16 px, com as seis linhas. Sem grelha de fundo. O hero de 190 px sai da Home. Não renderize `DotMascot` `size="hero"` em `.shell-home-hero`.

Em 1440 a coluna útil cabe no palco com trilho de 256 px e padding horizontal de 28 px. Em 768 o trilho fica em 256 px e a coluna continua nos 464 px medidos (768 − 256 − 48). Em 390 o trilho fica fechado, o padding horizontal continua 20 px e a coluna continua 350 px. `scrollWidth` do quadro igual a `innerWidth`.

## Linha de Dot

Substitua o botão-laje de `shell-home-board.jsx`. O botão continua sendo o mesmo controle, com `onOpenDot`.

Estrutura:

- altura 52 px, máximo 56 px
- grelha `28px minmax(0,1fr) auto 16px`
- nome à esquerda, 15 px, peso 620, cor `#f3f3f5`, uma linha, reticências
- mascote com `DotMascot` `size="nav"` (30 px no componente; na folha cabe a 28 px). Importe o componente; não edite o arquivo dele. Não desenhe outro halo em CSS.
- segundo fato: a palavra do fato confirmado, 13 px, peso 600, à direita
- a linha não tem fio próprio. O separador entre linhas é `inset 0 1px 0 #2c3038`. Hover troca só o fundo para `#22262e`.
- chevron de 16 px, cor `#6f7480`

A lista é uma coluna. Não parta os seis Dots em grelha de cards.

`active` é estado de ciclo de vida do Dot. Não é prova de trabalho em execução. Não mapeie `active` para Trabalhando nem para Disponível.

| Fato confirmado | Palavra | Cor |
| --- | --- | --- |
| `dot.status` `active` | Ativo | `#c5c8ce` |
| `dot.status` `available` ou `ready` | Disponível | `#9aa0a8` |
| `dot.status` `idle` | Ocioso | `#9aa0a8` |
| WorkItem ou Operation atual já validado na fase `executing` de `shell-canvas-state.js` | Trabalhando | `#8eb6ff` |
| espera de pessoa (`waiting_approval`, `waiting_chatgpt_user_approval`, `needs_input`) | Espera | `#e2b15a` |
| `completed`, `succeeded` | Concluído | `#7dcea8` |
| `failed`, `cancelled`, `canceled`, `interrupted`, `blocked` | Falha | `#f0a0ae` |
| `uncertain`, `unconfirmed` | Incerta | `#e0b56a` |

Trabalhando só entra na linha se esse WorkItem ou Operation de execução atual estiver validado. `dot.status` não basta. `home.run.state === 'RUNNING'` não basta. `inProgress` calculado com o run do projeto não promove o Space nem o Dot a Trabalhando.

Nesta captura os seis estão `active`. Os seis dizem Ativo. `workspaces_summary` tem `terminals: 12` e `running_terminals: 0`. `provider_ready` é `unverified`. Não há WorkItem nem Operation de execução validados, então Trabalhando não aparece em nenhum dos seis. Não invente hora, conversa nem recibo.

Não desenhe faixa de vocabulário no produto. A tabela acima fica neste dossiê. `dotPhase` em `shell-home-board.js` hoje devolve Disponível para `active`. Corrija esse retorno para Ativo antes de integrar. Não deixe o default de `dotPhase` engolir o ciclo de vida.

`SubAgenteGPT6` não apareceu no trilho visível. Use o mascote que o registro do Dot já tiver. Não atribua cor nova.

## Registros

Quando aprovação, entrega e falha estão vazias, as três frases não viram três caixas. Uma linha só: `Nenhuma aprovação, entrega ou falha nesta consulta.`

Se o payload trouxer item, esse grupo aparece como linhas na mesma folha, com o título que o payload já traz. Não crie título. Cópias de item que já existem:

- Aprovação que não é conversa: `Consulte a mesma intenção. Ela não será reenviada daqui.`
- Falha de item: o estado e `Consulte o estado. Não repita o envio.`

## Chip Em andamento

O texto da barra repete `Status` de `home.run.state`. Na captura é `Em andamento`. É o rótulo do run. Não é pill, não tem fundo, não tem ponto e não usa `#8eb6ff`. Cor `#9b9ba3`, 13 px, `white-space: nowrap`. Em 390, 12 px. A migalha mostra só a página atual. Proibido largura que quebre `Em` e `andamento`.

## Contraste e foco

- O fio `#8b9098` não contorna card, cápsula, fase nem aba. O fio antigo `#343434` também não volta.
- Nome `#f3f3f5` sobre a folha `#17191e` fica acima de 4,5:1.
- Foco: `outline: 3px solid #ffffff; outline-offset: 2px`, só em `:focus-visible`. Tab percorre cada botão da lista. O segundo Dot da ordem capturada é testegpt6.

## Leitura que ainda não assentou

Enquanto `home` não voltou `ok: true`, a Home mostra só `Consultando seu trabalho…`. Não mostra a frase de projeto sem Dots. Não mostra as seis lajes vazias.

Se a consulta falha antes de assentar, um único aviso usa o ramo de rede de `explainFailure`: título `A consulta não chegou ao Canvas`, próxima ação `Consulte de novo. Uma consulta não reenvia uma operação já iniciada.` Não use `A operação não foi confirmada` para falha de leitura. Não repita o mesmo texto em `Solicitações de aprovação`. O vazio do projeto só aparece depois de `home` com `ok: true` e listas vazias.

Operação de fato incerta continua no `FailureNotice` atual, uma vez, sem botão de reenvio.

## Canvas

A captura mostra sete cartões, cada um com o número 0 e o parágrafo inteiro, ocupando cerca de 300 px antes do grafo. Em 390 o grafo só aparece depois dessa parede. Isso sai.

- Cabeçalho do Dot aberto: Testando Advanced, mascote que o registro já tem, ações já existentes `Computador` e `Novo terminal de agente`.
- As sete fases ficam numa faixa de uma linha: número e nome. Na captura os sete números são 0. Uma frase só, da fase escolhida, com `meaning` e `safeNext`. As outras seis ficam fechadas. Fase incerta não ganha reenvio.
- O grafo começa na primeira vista. O nó visível é Testando Advanced. Ferramentas visíveis: Conversa do Dot, SENTRA CLI · GPT-6 High, OpenCode · Muse Spark High, Codex CLI. O estado visível é `interrupted`, palavra Interrompido, não Trabalhando e não o token cru.
- O terminal mostra o que a captura mostra: SENTRA, “Seu ambiente de criação e colaboração”.
- A tarefa visível permanece: “Tarefa SENTRA (aceitar ≠ concluir)”, o papel “Dot não é trabalhador de uma equipe”, `Trabalho para este Dot` e `Aceitar tarefa`. A nota visível permanece: conclusão só após consolidação do coordenador; Antigravity é aplicativo externo, sem API de agente validada.
- Não invente aresta, recibo nem contagem diferente de zero. Não escreva dentro do quadro que o Canvas não foi capturado.
- Em 390 a faixa das fases rola dentro dela. O documento continua com `scrollWidth` igual a `innerWidth`.

## Computador

A captura abre o computador ao lado da conversa de Testando Advanced. Em 768 e 390 a exclusão aparece antes do estado. As frases `Ainda não criada` e `VirtualBox indisponível` nesse PNG são defeito da superfície antiga. Não provam máquina inexistente nem hypervisor ausente. A VM `fcd974cf` foi verificada instalada e em execução. `VBoxManage` existe fora do `PATH`.

- Em 1440 e 768 o painel fica ao lado do chat. Em 390 o chat fica acima e o computador abaixo, na coluna de 350 px.
- A conversa visível permanece: “Conversa com Testando Advanced”, “sentra/chatgpt-web/gpt-6”, a mensagem das 14:42 “Você possui uma maquina linux no computador, por gentileza tente controlar”, “Resultado ainda não confirmado”, “O provedor não confirmou uma resposta.” e `Consultar diagnóstico sem reenviar`. Não há botão de reenviar.
- Sem consulta confirmada e sem vínculo contemporâneo, o primeiro bloco do painel diz `Estado ainda não consultado` ou `Estado ainda não confirmado`. Não diz que a máquina não existe e não torna a configuração obrigatória. Não induz reinstalação nem importação. O aviso incerto da conversa permanece visível.
- Abaixo do estado vêm as abas Desktop, Terminal, Arquivos e Navegador. Os campos visíveis na captura ficam na configuração, como formulário, não como máquina ligada: Linux com interface gráfica, 2 processadores, 4096 MiB, 64 GiB. A frase visível permanece: o limite recomendado não altera CPU, RAM nem a VM registrada.
- Pausar família, Retomar família e Pedir exclusão descem para um disclosure fechado. A cópia visível permanece: pausar e retomar não excluem o Dot; pedir exclusão só registra o bloqueio; nenhum Dot, VM ou conversa é apagado.
- `Ocultar computador` continua no painel. Não crie ação de bridge. Esta captura não homologa o clique.

## Movimento

Um só tempo, 200 ms, dentro de 180–240 ms. Curva `cubic-bezier(0.22, 1, 0.36, 1)`. Sem bounce, sem `translateY`, sem a subida `sentra-rise` de 8 px em `.shell-home-board`.

Hover da linha troca só o fundo. Abertura de aba e de fase troca opacidade.

`prefers-reduced-motion: reduce` zera transição e animação dessas superfícies. As linhas nascem na posição final. O estado continua legível. Não fotografe bob do mascote como se fosse movimento da Home; o mascote não é desta edição.

## Tokens

Acrescente no bloco `/* Frente 8 design tokens` de `desktop.css`, sem apagar os quinze nomes atuais de `shell-design-tokens.js`:

- `--sentra-rail: 256px`
- `--sentra-sheet: #17191e`
- `--sentra-dur: 200ms`
- `--sentra-ease: cubic-bezier(0.22, 1, 0.36, 1)`

Inclua os nomes novos no array `DESIGN_TOKENS` para o teste `shell-design-tokens.test.mjs` continuar verdadeiro. Não rode o teste como substituto de build, e não rode `npm run build`.

## Arquivos que podem mudar

- `sentra_canvas/desktop_ui/src/desktop.css`
- `sentra_canvas/desktop_ui/src/shell-home-board.jsx`
- `sentra_canvas/desktop_ui/src/shell-design-tokens.js`
- `sentra_canvas/desktop_ui/src/shell-dot-canvas.jsx`
- `sentra_canvas/desktop_ui/src/shell-computer-status.jsx`
- `sentra_canvas/desktop_ui/src/shell-dot-computer.jsx`
- `sentra_canvas/desktop_ui/src/shell-dot-vm.jsx` só na apresentação
- o trecho de carregamento de `shell-app.jsx` que hoje pinta `FailureNotice` e o vazio juntos quando `home` ainda não assentou

## Proibido

- `shell-mascot.jsx`, `dot-motion.js`, SVG de `dot-motion`, PNG de `opendots`
- `npm run build`
- fechar ou reiniciar a porta 4188, o broker 50282 ou o vite 5173
- ação nova de bridge, reenvio de operação incerta, estatística de VM
- declarar esta direção homologada

## Pendências numerosas

Os prints do usuário mostram a Home já integrada, fora da baseline vazia:

- `C:\Users\vitor\AppData\Local\Temp\Maestri-drops\c887fef8-6776-4d75-ad56-7fc98198e6f7.png`: dezenas de linhas iguais, `message.uncertain` colado em `uncertain. Consulte o estado. Não repita o envio.`
- `C:\Users\vitor\AppData\Local\Temp\Maestri-drops\97fbb455-ba49-45a0-999c-d587b357c6bc.png`: o menu Atualizar sai da cápsula. `Atualizar dados`, `Atualizar código local` e `Versão instalada` ficam soltos.

A causa da linha é `shell-home-board.js` mais `shell-home-board.jsx`. Sem `payload.summary`, o título vira o `kind` cru `message.uncertain`. O `small` imprime de novo o status `uncertain`. A folha pinta um botão por evento e empurra os Dots para fora da primeira tela. `recordsQuiet` só cabe quando as três listas estão vazias. Não use essa frase para esconder eventos.

A causa do menu é `desktop.css`: `.shell-update-menu[open] { display: grid }`. O `details` deixa de ser um item da cápsula e os três botões caem no fluxo.

Regra de agrupamento, sobre o array real de `failures`, sem descartar item:

1. Chave, nesta ordem: `conversation_id`, `operation_id`, `dot_id`, `kind`.
2. Título visível: nome da conversa já presente em `home.conversations`, senão nome do Dot já presente, senão `Operação` mais o `operation_id`, senão o rótulo humano do kind. `message.uncertain` no plural é `Mensagens não confirmadas`. Proibido o token cru e proibido repetir `uncertain` ao lado dele.
3. A contagem do grupo é o tamanho do grupo. A linha de cima é a soma: `N resultados ainda não confirmados. Nenhum virou sucesso.`
4. A frase `Consulte o estado. Não repita o envio.` aparece uma vez no grupo, não uma vez por evento.
5. O grupo abre no lugar. A primeira página mostra 6 registros. `Mostrar os outros N` revela o restante na mesma folha. Registro sem conversa e sem operação diz `Registro` mais `event_id` ou `seq`. Não apague o evento do modelo.
6. `Consultar este grupo` usa a consulta já existente. Não reenvia a operação incerta.
7. Com o grupo fechado, `Dots recentes` continua na primeira tela. A Home não vira um log.
8. `Continuar em Conversa` permanece quando `board.surface` existe. É um botão de texto, acima do foco, não uma laje.

Menu Atualizar:

- O `details` continua no flex da cápsula. Não use `display: grid` nele ao abrir.
- Os três botões ficam num painel `position: absolute; top: calc(100% + 8px); right: 0; z-index: 6; width: 220px`, fundo `#1a1c22`, raio 14 px.
- Em 390 o painel não aumenta `scrollWidth`.

A composição `index.html` tem o controle Pendências. Os 32 eventos de exemplo não têm conversa nem operação, porque o print também não tem. 32 não é a contagem do broker. No produto a contagem sai do array real.

Leitura do primeiro candidato, ainda sem servir: o painel fechado pode dizer `Envios não confirmados` e `N registros`. A frase fica uma vez no painel. O grupo sem nome, quando o kind é `message.uncertain`, diz `Mensagens não confirmadas`. Falha confirmada fica no painel `Falhas`. A frase `Nenhum virou sucesso` não é obrigatória. O painel não pinta sucesso.

## Cronologia das capturas

Os oito PNG com nome repetido em `.tmp/codex-candidate-home-review-20261013/` são a segunda iteração. O relato que os descreve é `report.json`, `2026-10-13T05:17:23-0300`. O `desktop.js` citado é `c3491db59e0a40e7fb0945733ba678ecfc0b1e4017833ac1da97c5857bda63bf`. O `desktop.css` é `838fbd77a665c9f6dcf9c7a292d880c66102aa942282fa566abb291e8125c2a5`.

`report-guard-incomplete.json` documenta a primeira iteração. Os PNG que ele nomeia foram sobrescritos pela captura limpa. Não use esse relato para ler os pixels atuais.

Cada captura nova fica numa subpasta imutável com o timestamp, e o relato aponta os caminhos. Um quadro só se lê com o relato da mesma pasta.

Nessa captura das 05:17, Escape fecha o menu (`escape_closes_menu` true). O poll oculto não chama `/api/terminal/output`. Não há toast. A nota tem o recuo de 14 px. `blocked_requests` está vazio. Não está publicada. `approved_for_publication` é false. Não homologa.

Vitra leu essa segunda iteração e deu FAIL. O achado que bloqueia é `breadcrumb_overlaps_run_status` em 768, no quadro `candidate-home-768.png`. Na cápsula, `Home` atravessa `Em andamento`. O trilho mede 256 px e a barra mede 488 px de largura. 1440 e 390 não estão nesse achado.

## Terceira iteração, captura 05:36

A evidência é só `.tmp/codex-candidate-home-review-20261013/20261013-053624/`. O relato é o `report.json` dessa subpasta, `2026-10-13T05:36:24-0300`. São 12 PNG. `desktop.js` `63ff43258e4edfd959ab6c32610b9616a4ef0a37b0a0f67b1302536f46b17e01`. API real do broker 6836, porta 50282. Não é fixture. Não está publicada. `homologated` false. Sem restart.

Os PNG na raiz de `.tmp/codex-candidate-home-review-20261013/` continuam a segunda iteração. O `report.json` da raiz foi atualizado como índice da terceira e não representa mais a segunda. Daqui em diante o índice é `latest-report.json`. Não se lê a terceira por aquele `report.json` da raiz.

Em 768, `candidate-home-768.png`: `Home` termina em x 371 e `Em andamento` começa em x 391. A folga é 20 px. Os dois textos estão inteiros. `scrollWidth` é 768. `topbar_labels_do_not_overlap` é true. `page_errors`, `http_errors` e `blocked_requests` estão vazios. Escape fecha o menu. Enter abre e recolhe o conjunto. No reduced, as animações param.

A colisão de 768 fecha nesta subpasta. Isso não aprova o design e não homologa.

## Refinamento, leitura sem quadro

O candidato está em `.tmp/desktop-candidate-home-refinement`. Não está servido. `desktop.js` `9b012ef1b1531dfc9c878b34448b9b489f8a523a9c6bb83eb5e1df6c38d6033a`. `desktop.css` `08270e81d6d036ea82d38ab9bbbafaccfc541662c63ef8579236f87de06f7320`. O documento de entrada permanece `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`. O manifest é `a5393ae8c4987d6f7f16b8bda3a52ac3a0f730b6c1ae10dd2f6f2d1fb8cda2d7`. Os hashes servidos e os da subpasta `20261013-053624` não mudaram.

No CSS minificado: a busca tem largura 100%, `max-width: none`, 40 px e raio 999 px. `Oxta` tem 40 px e 32 px até 700 px. A linha do conjunto tem 52 px, a contagem `#e2b15a` e o chevron 16 px. `Consultar` tem 32 px, margem `0 14px 8px` e fundo transparente. O chevron vai de `rotate(0deg)` a `rotate(90deg)` em 200 ms, `cubic-bezier(0.22, 1, 0.36, 1)`. No reduced, a transição do `.cadence-set-chevron` zera e o `rotate` final permanece. Essa regra não usa `translateY`. O bundle contém `Abrir o Space`. O container de 560 px e o painel de 220 px continuam.

A distância do foco até a folha é a margem `0 0 8px` mais o gap de 16 px da grelha. A soma é 24 px. Não troque a margem para 24 px por cima desse gap.

## Captura do refinamento, 05:58

A evidência é só `.tmp/codex-candidate-home-review-20261013/20261013-055848/`. O relato é o `report.json` dessa subpasta, `2026-10-13T05:58:48-0300`. São 12 PNG. `desktop.js` `9b012ef1b1531dfc9c878b34448b9b489f8a523a9c6bb83eb5e1df6c38d6033a`. `desktop.css` `08270e81d6d036ea82d38ab9bbbafaccfc541662c63ef8579236f87de06f7320`. API real do broker 6836. Não é fixture. Não está publicada. `homologated` false. A subpasta `20261013-053624` não foi escrita. O índice é `latest-report.json`.

O que esse quadro fecha: a busca ocupa a coluna, `Abrir o Space` está na linha da pergunta, o conjunto tem chevron, `45 registros` continuam numa folha, Escape, Enter e reduced seguem, e em 768 os rótulos não se sobrepõem. `page_errors`, `http_errors` e `blocked_requests` estão vazios. Isso não é PASS.

O que ainda falta, com os dados desta consulta:

- A pergunta `O que vamos fazer hoje?` não nomeia o trabalho. Os 45 da consulta são registros de `activity`, não 45 envios distintos e não 45 Operations. A linha de apoio e o subtítulo do Dot dizem `45 registros de envio não confirmado`. `N envios` só entra depois de deduplicar por `message_id` ou `request_key` presente no registro. Registros sem uma dessas chaves continuam na contagem de registros. `Abrir o Space` continua à direita e não vira a tarefa.
- Os seis Dots estão `active`. `Ativo` permanece. A segunda frase usa a mesma regra de contagem, nos registros já ligados ao `dot_id`. Sem esses registros e com conversas, a frase é `N conversas` mais a data mais recente de `updated_at`. Sem conversa e sem registro, a linha fica só `Ativo`. Não usar Trabalhando. Não converter o contador de logs em número de mensagens.
- Há 42 conversas. As três primeiras visíveis têm o mesmo título, `Conversa com Sentra Aqrt`, e o mesmo Dot. As datas são 13/10/2026, 12/10/2026 e 12/10/2026. `formatConversationDate` em `shell-dates.js` imprime só o dia UTC, então as duas de 12/10 ficam iguais. Na Home, agrupar por título e `dot_id`. O grupo fechado mostra o título, a contagem e a data mais recente. Aberto, cada conversa mostra dia e hora de `updated_at`. `Ver todas` continua levando às 42. Não apagar conversa.
- Não reabrir agrupamento dos envios, Escape, poll nem a colisão de 768. Sem servir. A família do computador continua fora.

## Captura contextual, 06:26, colisão em 390

A evidência é só `.tmp/codex-candidate-home-review-20261013/20261013-062616/`. `desktop.js` `0c6c31c1ad33fca091626035ebf544422d244247daa5eea03e7ce055b58261d6`. São 24 PNG. API real. Não está publicada. `homologated` false. As subpastas `20261013-053624`, `20261013-055848` e `20261013-060755` não se escrevem. O anel de foco desta captura permanece corrigido. Não reabri-lo.

Em 1440 e 768 o contexto cabe na mesma linha: nome, frase, `Ativo` e chevron. Em `candidate-home-390.png` a frase atravessa `Ativo` e, em `Testando Advanced`, o nome atravessa a frase. `scrollWidth` é 390. As frases reais são `1 envio não confirmado`, `12 conversas · 12/10/2026`, `2 conversas · 11/10/2026`, `1 conversa · 11/10/2026` e `8 conversas · 11/10/2026`. O painel continua `45 registros`. Não troque essas frases para caber. Não invente ocupado nem pinte `Trabalhando`.

No 390, a linha do Dot é uma grelha `28px minmax(0, 1fr) auto 16px`, altura no máximo 56 px. Hoje as linhas medem cerca de 52 px. A coluna flexível empilha o nome e a frase. Cada um é uma só linha, com reticências se não couber. `Ativo` fica inteiro, fora dessa coluna, sem encolher e sem quebrar. O chevron de 16 px fica na última coluna. As seis linhas continuam na primeira tela. Em 1440 e 768 a linha única permanece. A conversa agrupada pode cortar o título; a contagem e a data não atravessam o chevron.

Vitra leu `candidate-home-390.png` desta subpasta. Não é PASS. O aceite da próxima captura não é `scrollWidth` igual a 390. Esse número já fecha nesta captura e os textos ainda se atravessam. O aceite é o nome inteiro ou com reticências, a frase inteira ou com reticências, e `Ativo` inteiro, sem um pintar por cima do outro.

## Captura 06:40, aceite da pilha

A evidência é só `.tmp/codex-candidate-home-review-20261013/20261013-064043/`. `2026-10-13T06:40:43-0300`. `desktop.js` `8e4c5ca214fa9d58e248019c2bbd0b8e5c641ee8165f04db3d2c96c349bc6cb9`. `desktop.css` `b9999b1d7f07ddb8e52cf229f0eb81125900ef23b6db6c3fb88000f07aecc81e`. API real do PID 6836. Não publicada. `homologated` false. As pastas anteriores não entram nesta leitura.

No 390, nome e frase compartilham o x e a frase começa abaixo do nome. `Ativo` começa em x 302,5, à direita do fim da frase. A linha tem 52 px. Em 1440 e 768 a linha continua única. Os seis Dots estão `active` e o mascote está `idle`. Esse aceite fecha. Não é PASS.

O aceite estrito da pilha, do foco e do mascote `idle` fecha só neste par: `desktop.js` `8e4c5ca2…` e `desktop.css` `b9999b1d…`. A frase única sob `Oxta` é válida e entra na etapa abaixo. Sozinha, não responde à Home.

## Etapa única da Home

Uma etapa, em `shell-home-board.jsx` e no CSS da Home. Não reabre a pilha de 390, o anel de foco, o menu Atualizar nem o reduced. Não desenha Canvas nem Computador. Sem servir.

A coluna, de cima para baixo:

1. `Oxta` continua 40 px, e 32 px em 390. A linha de apoio fica a 8 px abaixo e diz `1 envio não confirmado, em 45 registros`. `Abrir o Space` fica 16 px depois dessa frase, no mesmo agrupamento à esquerda. Se os dois não couberem em 390, o botão quebra para a linha seguinte, alinhado à esquerda. Não fica na borda oposta da coluna.
2. A folha `Envios não confirmados` / `45 registros` vem 16 px abaixo. A frase `Consulte o estado. Não repita o envio.` e `Consultar` permanecem. A busca sai de cima do título e fica entre esta folha e `Dots recentes`, com 40 px, largura da coluna e raio 999 px.
3. Os seis Dots permanecem `Ativo`, mascote `idle`, com as frases já medidas. Em 390 a pilha aceita não muda. Em 1440 e 768 a linha única não muda.
4. Cada conversa agrupada tem duas linhas, altura até 56 px. A primeira é o título, com reticências se não couber. A segunda é o nome do Dot, a contagem e a data, quando o título não é o próprio Dot. Em `testegpt6` a segunda linha é `2 conversas · 12/10/2026`. Em `Conversa com Sentra Aqrt` a segunda linha é `Sentra Aqrt · 7 conversas · 13/10/2026`. Em 390, `Sentra Aqrt` aparece inteiro nessa segunda linha, mesmo se o título virar `Conversa com Se...`.

Critério visual, na captura nova, sem escrever nas pastas antigas:

- 1440 e 768: o botão está a 16 px da frase, não no fim da coluna. A busca está abaixo da folha. A segunda linha da conversa mostra `Sentra Aqrt` inteiro.
- 390: `scrollWidth` igual a 390 não basta. Nome, frase e `Ativo` continuam sem se cruzar. A segunda linha da conversa mostra `Sentra Aqrt` inteiro. A linha do Dot e a da conversa ficam até 56 px.

A leitura desta etapa está na seção seguinte. Ela não reescreve estes critérios.

## Captura da etapa única, 07:07

A evidência é só `.tmp/codex-candidate-home-review-20261013/20261013-070729/`. `2026-10-13T07:07:29-0300`. 28 PNG. `candidate-files` permanece imutável nesta leitura. `desktop.js` `c4a159ee6fe7ff9af840b666157653cff8d2f70faf338002daef9b59842a265f`, 2060336 bytes. `desktop.css` `adcb93b90df5303fbba894b380c72dc0e6a4575a6acf226b836ec23f4c64a11f`, 127169 bytes. `desktop.html` `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`. `manifest.json` `58d9e4917a688d6e1a8256c012f9ffd56075adb9f16ed44ea8487893f109f2e4`. API real do PID 6836, porta 50282, runtime `cd86d23b412f46be948bfbe0c12ec197`. `published` false. `broker_restarted` false. `homologated` false. `product_mutations` false. `fixture` false. `candidate_changed_during_review` vazio. `page_errors`, `http_errors`, `blocked_requests` e `blocked_websockets` vazios. Os cheques passaram em 1440, 768, 390 e 390 com reduced. `runningAnimations` 0 nos quatro quadros. As pastas anteriores não entram nesta leitura.

Critério medido nestes pixels:

- 1440: o apoio termina em x 612,8. `Abrir o Space` começa em x 628,8, 16 px depois, e termina em x 711,7. A coluna vai até x 1368.
- 768: o apoio termina em x 564,8. O botão começa em x 580,8 e termina em x 663,7. A coluna vai até x 744.
- 390: o botão quebra para x 20, y 153,6, na mesma esquerda do apoio, e termina em x 102,8. A coluna vai até x 370.
- A busca fica abaixo da folha. Em 390 ela começa em y 325,1, tem 40 px de altura e 350 px de largura, 16 px depois do fim da folha.
- As seis linhas de Dot têm 52 px, `phase` active e mascote `idle`. Em 390 o nome e a frase compartilham x 72. `Ativo` começa em x 302,5. Os três não se cruzam.
- A caixa medida de `Oxta` tem 42 px em 1440 e 768 e 33,6 px em 390. É a caixa da linha do título de 40/32.
- Frases derivadas: apoio `1 envio não confirmado, em 45 registros`. Folha `Envios não confirmados`, `45 registros`, `Consulte o estado. Não repita o envio.` e `Consultar`. Dots: Sentra Aqrt `1 envio não confirmado`; testegpt6 e Testando Advanced `12 conversas · 12/10/2026`; SubAgenteGPT6 `2 conversas · 11/10/2026`; Teste `1 conversa · 11/10/2026`; dasdas `8 conversas · 11/10/2026`. Todos `Ativo`.
- Grupo fechado: `Conversa com Sentra Aqrt` / `Sentra Aqrt · 7 conversas · 13/10/2026`. `testegpt6` / `2 conversas · 12/10/2026`. Em 390, `Sentra Aqrt` aparece inteiro na segunda linha.
- Enter abre e fecha o grupo. O primeiro grupo aberto mostra sete itens e não abre a conversa: `13/10/2026, 06:54`; `12/10/2026, 23:22`; `12/10/2026, 21:24`; `12/10/2026, 21:22`; `12/10/2026, 18:43`; `12/10/2026, 12:49`; `11/10/2026, 12:46`. O Dot dos sete é Sentra Aqrt. Os ids estão no `conversation_probe`.
- A ação `home` desta captura traz `uncertain_event_count` 45 e `activity_count` 50. A frase visível usa 45. Não trocar 45 por 50.
- Busca e `Abrir o Space` têm anel de 3 px branco com offset 2 px. A linha do Dot tem o anel visível e o probe mede offset -4 px. Isso não reabre o anel.

Este encontro fecha a etapa única só nestes bytes. Não é PASS. Não é redesign fechado. A Home continua uma coluna de linhas de 52 px, com o mesmo peso entre a folha, os Dots e as conversas. Canvas e Computador não estão nestes 28 PNG e continuam fora deste aceite. Estes hashes não são o shell da porta 50282. Sem publicar, sem promover e sem reiniciar.

## Aceite visual, ainda sem homologação

1. Cada Dot recente tem no máximo 56 px, nome à esquerda e a palavra Ativo nesta captura. Os seis cabem numa folha. A frase de ausência só aparece quando aprovação, entrega e falha estão vazias. Com eventos, a Home mostra grupos, contagem e Dots, não uma linha crua por evento.
2. `active` cru não aparece e não vira Trabalhando. Trabalhando só existe com WorkItem ou Operation de execução validado.
3. Nenhum card, fase ou aba usa o fio `#8b9098`. O nome sobre `#17191e` mede pelo menos 4,5:1.
4. A 390 px, trilho fechado, `scrollWidth` igual a `innerWidth` e a coluna em 350 px. `Em andamento` fica numa linha. Aviso de leitura, quando existir, aparece uma vez e não usa a cópia de envio não confirmado.
5. Tab chega a cada botão. O anel de 3 px branco aparece no foco, sem hover.
6. Com `prefers-reduced-motion: reduce`, as linhas aparecem no lugar, sem subida.
7. O quadro do produto não contém nota de QA, a palavra Composição, nem a frase de que algo não foi capturado.
8. Dezenas de `message.uncertain` viram um grupo com contagem. O token cru não aparece. O detalhe abre no lugar e o restante do histórico continua alcançável. Nenhum desses eventos é pintado como sucesso.
9. Atualizar aberto ancora o painel na cápsula, à direita do botão, sem soltar os três itens no fluxo.
10. Em 768, `Home` e `Em andamento` não se sobrepõem. O rótulo do run fica inteiro. A migalha cede com reticências. Há pelo menos 8 px entre os dois.

## Canvas e Computador, preparação visual

Esta seção não entra no aceite da Home. A evidência é só `.tmp/codex-closure-20261013-canvas-computer/`, `2026-10-13T04:20:38-0300`, `baseline.json`. `desktop.js` `e9d3f16230f5ad4d71571a617cbf1dd15752e54da7f2d942cb14f36e4b867f65`. A captura não homologa ações. Orbe não edita o fonte do Lumen nem os controles de família.

### Canvas

`production-canvas-1440.png` e `production-canvas-390.png` mostram o mesmo trabalho: sete cartões com `0` e um parágrafo cada, e só depois o nó. Em 390 o nó entra no fim da tela: `Testando Advanced`, `interrupted`, as ferramentas `Conversa do Dot`, `SENTRA CLI · GPT-6 High`, `OpenCode · Muse Spark High`, `Codex CLI`, e o começo de `SENTRA`. `production-canvas-768.png` é outro quadro: o aviso `A operação não foi confirmada`, `Carregando o Canvas deste Dot...` e `Nenhum Space neste projeto.` Não usar esse PNG como o grafo.

Hierarquia do quadro assentado:

1. O grafo é o trabalho. Os sete parágrafos saem de cima dele. A régua é uma linha: nome da fase e `0`. Sem contagem no payload, a frase da fase não aparece.
2. O nó é o objeto. Título `Testando Advanced`. O status cru `interrupted` aparece como `Interrompido`. As quatro ferramentas permanecem. O texto do terminal permanece `SENTRA` e `Seu ambiente de criação e colaboração`.
3. A tarefa fica no nó, não numa laje acima: `Tarefa SENTRA (aceitar ≠ concluir)`, o papel `Dot não é trabalhador de uma equipe`, `Trabalho para este Dot` e `Aceitar tarefa`. A nota de conclusão com o coordenador permanece. Aceitar não é concluir e não reenvia.
4. A conversa é o caminho `Conversa do Dot` no nó, não uma segunda página de parágrafos. `Computador` e `Novo terminal de agente` continuam no cabeçalho.
5. Em 390 a régua rola dentro da coluna. O título do nó e `Interrompido` entram na primeira tela. A página não rola na horizontal.

### Computador

Em `production-computer-1440.png` a conversa fica à esquerda e o painel à direita. O painel abre com `Pausar família`, `Retomar família`, `Pedir exclusão` e `EXCLUIR DOT`. A superfície antiga escreve depois `Ainda não criada` e `VirtualBox indisponível`. Essas duas frases são defeito dessa superfície. Não provam que a máquina não existe nem que o hypervisor está ausente. A VM `fcd974cf` foi verificada instalada e em execução. `VBoxManage` existe fora do `PATH`. Em `production-computer-390.png` a exclusão ocupa a tela. A conversa visível é `Conversa com Testando Advanced`, subtítulo `Testando Advanced · sentra/chatgpt-web/gpt-6`.

Hierarquia:

1. Identidade: `Testando Advanced` e o subtítulo acima. Em 1440 e 768 a conversa fica ao lado. Em 390 a conversa fica acima do painel.
2. Sem consulta confirmada e sem vínculo contemporâneo, o primeiro bloco diz `Estado ainda não consultado` ou `Estado ainda não confirmado`. Não diz máquina inexistente. Não torna `Configurar a máquina` obrigatório. Não pede reinstalação nem importação. O aviso incerto da conversa não é escondido.
3. `Desempenho da VM ainda não consultado` permanece consulta não feita. Não vira zero nem ausência de CPU. `Nenhuma cópia de projeto confirmada no guest` prova falta de recibo. Não prova que os arquivos não estão no guest. A frase visível é `Nenhum recibo de cópia confirmada`.
4. `2`, `4096` e `64` só aparecem dentro do formulário, como valores do formulário, nunca como medição. O formulário não abre sozinho. A frase do limite recomendado permanece.
5. `Pausar família`, `Retomar família`, `Pedir exclusão` e `EXCLUIR DOT` ficam abaixo, num bloco fechado. Não lideram o painel. Os controles de família não são editados aqui.

Não servir, não construir e não reiniciar. Esta preparação não altera o aceite da Home.
