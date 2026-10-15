# Canvas e Computador — Vitra — 2026-10-13 04:20

Shell de produção. Pasta `.tmp/codex-closure-20261013-canvas-computer/`. `fixture: false`. `product_mutations: false`. `page_errors`, `http_errors` e `blocked_mutations` vazios. Broker PID 6836, porta 50282, runtime `cd86d23b412f46be948bfbe0c12ec197`. `desktop.js` sha256 `e9d3f16230f5ad4d71571a617cbf1dd15752e54da7f2d942cb14f36e4b867f65`, 2043655 bytes. `desktop.css` sha256 `a7a95e688423a312e23693ec122fb298adb7c1d999456e95e90717bcd754068c`, 117252 bytes. Os dois batiam com o checkout no instante da captura.

`dot_canvas_get` e `dot_vm_images` estão `ok: true`. A navegação usou o Dot e a conversa que já existiam (Testando Advanced). Não houve conversa nova.

Não homologa. Foco e reduced-motion não foram fotografados (`reducedMotion` segue falso nos stills da Home).

## O nome do arquivo e o quadro

| Arquivo | O que o pixel mostra |
| --- | --- |
| `production-home-1440.png` | Leitura da Home que não assentou. Cartão: “A consulta não chegou.”, “A leitura da Home não assentou.”, “Consulte de novo. Esta falha não esvazia o projeto.”, botão “Consultar de novo”. Trilho: “Nenhum Space neste projeto.” |
| `production-home-768.png` | O mesmo cartão, mais o aviso “Não foi possível consultar o runtime local.” |
| `production-home-390.png` | Home assentada. Hero, “O que vamos fazer hoje?”, seis Dots com Disponível, “Projetos em andamento” com “Oxta Em execução”. A migalha corta “Hon” contra “Em andamento”. |
| `production-canvas-1440.png` | Canvas de Testando Advanced. Sete cartões, cada um com contagem 0 e o parágrafo de `meaning` + `safeNext`. Abaixo, um nó. |
| `production-canvas-390.png` | Os mesmos sete cartões ocupam a vista. O nó aparece cortado no fundo. As abas do nó saem pela direita. |
| `production-canvas-768.png` | Outro quadro. “A operação não foi confirmada”, “Envio não confirmado…”, “Não repita o envio.”, e em seguida “Carregando o Canvas deste Dot…”. Trilho sem Spaces. |
| `production-computer-1440.png` | Conversa existente à esquerda, “Resultado ainda não confirmado”. Painel à direita com a faixa da VM. |
| `production-computer-768.png` | O mesmo par, com as frases do painel cortadas na borda. A migalha corta “Con” contra “Em andamento”. |
| `production-computer-390.png` | A conversa e o painel empilhados. A migalha corta do mesmo jeito. O formulário de exclusão entra antes da máquina. |

Os headings “Seu trabalho”, “Detalhes”, “Solicitações de entrada” e “Atividade e recibos” medidos em 1440 e 768 pertencem ao painel contextual no DOM. O pixel desses dois arquivos de Home é o cartão de leitura, não esse painel e não a conversa.

## Três estados, três desenhos

Carregando. A frase é uma só: “Consultando seu trabalho…”, “Carregando o Canvas deste Dot…” ou “Consultando a máquina…”. Nesse quadro não há zero, não há “Nenhum Space neste projeto.”, não há “Ainda não criada” e não há “VirtualBox indisponível”.

Erro de leitura fechado. Um aviso. Título no ramo de leitura: a consulta não chegou. A próxima ação consulta de novo e não reenvia uma operação. O trilho conserva o Space e os Dots que a leitura anterior já tinha assentado. A cópia do cartão em 1440 e 768 diz que a falha não esvazia o projeto; o trilho, no mesmo quadro, diz que não há Space. As duas frases juntas são o defeito.

Bug. `production-canvas-768.png` põe o carregamento do Canvas debaixo de “A operação não foi confirmada” / “Não repita o envio.” `dot_canvas_get` desta leva está `ok: true`. O arquivo de 768 não é a prova de que o Canvas está vazio nessa largura. A prova do Canvas são os arquivos de 1440 e de 390.

`computerStatus` em `shell-computer-status.js` usa `vm?.vm_state || 'not_created'`. Com `status` ainda nulo, a faixa nasce “Ainda não criada”, “Teclado sem posse ativa” e “Nenhuma cópia de projeto confirmada no guest.” O cabeçalho em `shell-dot-vm.jsx` cai em “VirtualBox indisponível” quando `hypervisor_available` ainda não veio, porque o valor ausente é falso. O chip “Desempenho da VM ainda não consultado” é o único que diz que a consulta não voltou. Os outros cinco falam como fato. Os campos 2, 4096 e 64 são o `useState` inicial do formulário (`os_family: linux`, `cpus: 2`, `memory_mb: 4096`, `disk_gb: 64`), no mesmo quadro em que o desempenho não foi consultado.

“Resultado ainda não confirmado” está na mensagem da conversa. É o estado daquela resposta. Fica na conversa, uma vez. Não vira estado da VM e não usa o cartão de envio no Canvas.

## Canvas — uso

Sete cartões da mesma altura, com o mesmo zero e o mesmo tamanho de parágrafo, são a primeira leitura. O grafo, que é o Canvas, fica embaixo e menor. Em 390 a primeira dobra acaba antes do nó. O nó em 1440 é um cartão com a marca SENTRA, a frase “Seu ambiente de criação e colaboração”, um seletor de tarefa e as abas da conversa (Conversa do Dot, SENTRA CLI, OpenCode, Codex CLI, a aba `sentra/chatgpt-web/gpt-6` cortada). A palavra `interrupted` aparece cortada na borda de cima do nó.

A próxima composição: o nó ocupa o palco. As abas cabem inteiras em 390 e em 768, ou passam a uma lista vertical sem cortar o endereço. A legenda de fase é uma linha: a fase que `summarizePhases` marcou, com a contagem. As outras seis ficam num controle que abre, fechadas. Contagem 0 mostra a fase e o número, sem o parágrafo de duas frases repetido sete vezes. O zoom do React Flow permanece. Sem seis nós decorativos.

## Computador — uso

O painel abre por cima da conversa que já existe. Em 1440 os dois lados cabem. Em 768 o painel come a frase no meio (“Pausar e retomar não excluem o D”, “VirtualBo”). Em 390 a exclusão (nome exato, EXCLUIR DOT, Pausar família) vem antes do estado da máquina, e a cápsula corta a migalha.

A próxima composição: a cápsula guarda a página numa linha, “Em andamento” incluso, em 390. O painel da máquina começa pelo estado. Enquanto `dot_vm_status` não voltou, uma linha: “Consultando a máquina…”. Depois do `ok: true`, com `vm` nulo, “Nenhuma VM registrada nesta consulta”. “VirtualBox indisponível” entra só com `hypervisor_available: false` nesse envelope. Os campos de processador, RAM e disco aparecem como formulário de configuração, com rótulo de formulário, e só depois do envelope. Não como a medida da VM. As abas Desktop, Terminal, Arquivos e Navegador ficam. Pausar VM, Desligar e Assumir controle continuam fora até `vm_state` ser `running` ou `paused`.

## Home deste mesmo recorte

O arquivo de 390 é a Home que assentou nesta leva. As seis linhas dizem Disponível. O contrato da bancada é Ativo para `dot.status` `active`. “Oxta Em execução” promove o Space porque o run está `RUNNING`. O rótulo do run na cápsula já é “Em andamento”. O projeto não ganha uma segunda palavra de execução. O hero de 190 px com halo tracejado continua acima da lista. A migalha “Hon” é corte de “Home”.

A Home assentada nas três larguras, com os seis Dots e sem este cartão de leitura, continua a das 03:53. Esta leva não a substitui em 1440 e 768.
