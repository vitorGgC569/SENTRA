# Composição Orbe — Vitra — arquivo revisado

Lido em 2026-10-13: `docs/frentes-18/design/orbe/index.html` e `spec-lumen.md`. O PNG `.tmp/codex-orbe-review-20261013/` é o quadro anterior. Esta leitura é do arquivo. Não é PASS. Não homologa. Não é o shell `http://127.0.0.1:50282/desktop.html`.

## O que o arquivo já tirou

Dentro de `.frame` não há grelha de 8 px, não há `#8b9098`, não há `Trabalhando`, e não há as frases de dossiê (a nota sobre Dots abaixo da primeira leitura, o texto que começa por Composição, os “não capturado”). As seis linhas dizem Ativo em `#c5c8ce`. O palco do Canvas (`#spatial`) está vazio. O Computador é um bezel vazio com Pausar VM, Desligar, Assumir controle e Atualizar estado desabilitados.

A spec na linha 185 ainda diz que Canvas e Computador seguem sem PNG de produção. Essa frase ficou para trás. A baseline está em `.tmp/codex-closure-20261013-canvas-computer/`, captura `2026-10-13T04:20:38-0300`. O `desktop.js` servido nessa leva é sha256 `e9d3f16230f5ad4d71571a617cbf1dd15752e54da7f2d942cb14f36e4b867f65`, 2043655 bytes. O hash `7a5d7cac…` da spec é a Home das 03:53.

## O que o arquivo ainda é

Uma folha quieta com um buraco no lugar do trabalho. Tirar o fio e a grelha baixou o ruído. O Canvas e o Computador ficaram um retângulo `#0c0d11` e um retângulo `#07080b`. Os dois ainda levam um fio, agora `box-shadow: inset 0 0 0 1px rgba(255,255,255,.04)` no palco e `.05` no bezel.

A Home em 1440 usa padding horizontal de 36 px, trilho de 256 px, coluna de 1112 px. A grelha da linha é `28px minmax(0,1fr) auto 16px`, então Ativo senta na borda direita. O meio da folha é vazio. O estado senta ao lado do nome. A largura que sobra é a região do próximo trabalho, com medida própria, não uma folha esticada.

Planejamento carrega com `aria-pressed="true"` e `showPhase('planning')`. A frase “O trabalho foi admitido e ainda não está em execução.” aparece sem payload. Nenhuma fase fica escolhida até o payload trazer a fase. A sétima etiqueta em `shell-canvas-state.js` é “Operação incerta”. O arquivo escreve “Incerta”.

SubAgenteGPT6 é um disco com a letra S. Os outros cinco são PNG. O disco é uma marca nova.

O anel de 3 px branco está só em `.dot:focus-visible`. Busca, Abrir, fases, abas e trilho ficam no anel do navegador. O botão do trilho chamado Canvas não troca `data-screen`. Com a vista Canvas, o trilho continua `aria-current="page"` em Home. A navegação que funciona está nos controles fora do quadro.

O estado Consultando acrescenta “A lista aparece quando a consulta assentar.” A cópia da leitura que ainda não voltou é uma linha: “Consultando seu trabalho…”.

Os seis Ativo iguais são o ciclo de vida `active` sem execução validada. A linha continua com um fato só. Sem hora inventada. O segundo fato, quando o registro do Dot tiver conversa, é o título dessa conversa.

## O que a próxima bancada usa da captura real

Critério por pixel em `CANVAS-COMPUTADOR.md`. Resumo para a bancada:

- Canvas de Testando Advanced, um nó, abas da conversa visíveis por inteiro em 1440, 768 e 390. As sete legendas com contagem 0 e o parágrafo inteiro saem da primeira dobra. Uma fase, a que o payload marcou. Contagem 0 não vira sete lajes.
- Computador: até `dot_vm_status` voltar `ok: true`, a linha é “Consultando a máquina…”. Com o envelope e `vm` nulo, “Nenhuma VM registrada nesta consulta”. “VirtualBox indisponível” só quando esse envelope traz `hypervisor_available: false`. Os números 2, 4096 e 64 do formulário não entram como especificação da máquina. “Ainda não criada” não aparece enquanto o pedido está pendente ou o estado veio indefinido.
- Home do arquivo mantém Ativo. O PNG de 390 desta leva pinta Disponível e “Oxta Em execução”. Essas duas palavras ficam fora da bancada.

Sem `npm run build`. Sem fechar a porta 4188. Sem editar mascote, `dot-motion` nem PNG. Sem declarar a direção homologada.
