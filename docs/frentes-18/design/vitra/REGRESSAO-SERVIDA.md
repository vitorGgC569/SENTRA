# Regressão da versão servida — Vitra — 2026-10-13

O usuário fotografou o shell servido. Três arquivos em `C:\Users\vitor\AppData\Local\Temp\Maestri-drops\`. Não é homologação. Não é aceite por teste unitário nem por `scrollWidth`.

Root trata isto como regressão de uma versão intermediária. A Home das 03:53 não tinha este despejo.

## Home — `c887fef8-6776-4d75-ad56-7fc98198e6f7.png`

1630×1004. Cápsula com Oxta, Home, Em andamento, Atualizar. Busca, “Continuar em Conversa”, título Oxta, “O que vamos fazer hoje?”, Abrir. Abaixo, a mesma linha dezenas de vezes, até o fim do quadro:

`message.uncertainuncertain. Consulte o estado. Não repita o envio.`

“Dots recentes” não aparece neste quadro. O trilho também não.

Origem no fonte atual: `homeBoard` em `shell-home-board.js` empurra cada evento de atividade cujo `kind` casa `/fail|uncertain|error/` para `failures`. O título cai em `event.kind` quando não há `payload.summary`. O status cai em `uncertain`. `shell-home-board.jsx` pinta `<strong>{title}</strong><small>{status}. Consulte o estado. Não repita o envio.</small>` na mesma linha. `message.uncertain` mais `uncertain` lê `message.uncertainuncertain`.

## Atualizar — `97fbb455-ba49-45a0-999c-d587b357c6bc.png`

673×208. O `details` aberto não abre um painel. “Atualizar dados”, “Atualizar código local” e “Versão instalada” entram na faixa da cápsula, por cima do botão Atualizar, cortados em cima. “Em andamento” fica atrás do painel.

Origem: `.shell-update-menu[open] { display: grid }` em `desktop.css` põe os três botões no fluxo da barra.

## Trilho — `dbe05a91-d387-4350-85dd-2a2b71cd25fc.png`

228×1017, só o trilho. Os rótulos cabem: Home, Conversas, Dots, Spaces, cinco Dots, Oxta, Documentos, Canvas, Rede, Ambientes e modelos, Skills e ferramentas. Não há palavra cortada neste recorte. O defeito é o quadro da Home, 1630 px, sem este trilho ao lado.

## Critério para o candidato, antes de servir

Um render com a mesma forma de dados (vários eventos `message.uncertain` na atividade), em 1440 e em 390. Sem `npm run build` no broker 50282 até esta leitura.

1. A Home mostra uma linha para essa falha, com título em português, sem o token `message.uncertain` e sem `uncertain` colado nele. “Não repita o envio” aparece uma vez. “Dots recentes” e o primeiro nome ficam visíveis em 1440×920.
2. Atualizar aberto é um painel absoluto, três linhas inteiras, sem deslocar a cápsula e sem cortar o rótulo. Fechado, a cápsula volta a uma linha.
3. Em 1440 o trilho de 256 px está no mesmo quadro que a Home.

Teste unitário e largura sem overflow não fecham estes três.

## Portão de release

A publicação do candidato fica bloqueada até esta regressão estar corrigida. O próximo artefato da Lumen entra em `.tmp/desktop-candidate-home`, sem `npm run build` e sem materialize da versão ativa. Não há markup novo com CSS incompleto na versão servida.

Em 2026-10-13 esta pasta não existe. Sem os PNG do candidato não há PASS nem FAIL.

Harness da Codex: `.tmp/codex_candidate_home_review_20261013.py`. Sai antes de `read_endpoint` quando faltam `desktop.js`, `desktop.css`, `manifest.json` e `desktop.html` ou `index.html`. Relatório `.tmp/codex-candidate-home-review-20261013/report.json` às 04:53: `status` `CANDIDATE_MISSING`, `screens` vazio, sem `broker_pid`. Não consultou o broker. `published`, `broker_restarted` e `homologated` estão falsos.

A primeira leva com arquivos está em `report-guard-incomplete.json`, status `CAPTURED_STAGED_CANDIDATE`, `2026-10-13T05:03:12-0300`. Não é a captura limpa. Não aprova.

Bytes dessa leva: `desktop.js` sha256 `3a46c9819401abc71463293d8477fbba6fac6bd7cc519bd1ef1825df406ad080`, 2053509 bytes. `desktop.css` sha256 `b27d10bdb81cba4e7d58d374daf6ac18be611e74ae802bbd0523200a22dec83e`, 120847 bytes. `desktop.html` e `index.html` sha256 `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`, 1062 bytes. `manifest.json` sha256 `7311644ef9f6e8a63d527a75bd79ab458575fc43bc605f67618b556a721bee74`, 14653 bytes.

Os oito PNG existem ao lado desse relatório. O harness marcou, nas quatro vistas, overflow horizontal ausente, primeiro Dot visível, menu absoluto com três ações, trilho junto da Home, e `escape_closes_menu: false`. O guard dessa leva bloqueou `machine_list` e `/api/terminal/output`. O aviso que isso desenhou no PNG não é defeito da Home. `machine_list` foi corrigido no guard. Output de terminal continua fora, porque o handler pode reconciliar recibos. A Lumen suspende o polling oculto por `canvasActive`, sem destruir sessões.

`report.json` às 05:05 é só `OBSERVATION_FAILED`, `exception_class` `Error`, com `published`, `broker_restarted` e `homologated` falsos. Não traz hash. A segunda tentativa foi `ECONNREFUSED` transitório, com o PID 6836 e o listener vivos. Sem restart.

PASS espera uma captura nova, limpa, com hash do conjunto JS/CSS/HTML/manifest, e os PNG Home e menu em 1440, 768, 390 e 390 reduced. Esc entra nessa leitura. Não homologa. Vitra não gera o build e não promove.

## Veredito da captura 05:17 — FAIL

`report.json` `CAPTURED_STAGED_CANDIDATE`, `2026-10-13T05:17:23-0300`. Broker PID 6836. `published`, `broker_restarted` e `homologated` falsos. `page_errors`, `http_errors` e `blocked_requests` vazios. Hashes do relatório batem com o anúncio: `desktop.js` `c3491db59e0a40e7fb0945733ba678ecfc0b1e4017833ac1da97c5857bda63bf`, 2054866 bytes. `desktop.css` `838fbd77a665c9f6dcf9c7a292d880c66102aa942282fa566abb291e8125c2a5`. `desktop.html` `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`. `manifest.json` `fc1a7738b8d9e537639fc53ace9c66aec48f23f7f156208aaddb8db2093bf6f9`.

Os oito PNG foram lidos. O despejo de `message.uncertain` fechou: um cartão, “Envios não confirmados”, “45 registros”, uma vez “Consulte o estado. Não repita o envio.”, botão Consultar com `data-resend="false"`. Os seis Dots estão visíveis, com Ativo. Em 1440 e em 768 o trilho mede 256 px no mesmo quadro. O menu aberto é absoluto, com “Atualizar dados”, “Atualizar código local” e “Versão instalada” inteiros, sem empurrar a cápsula. O harness marca `escape_closes_menu: true` nas quatro vistas. Em 390 e em 390 reduced, Home e Em andamento ficam lado a lado, legíveis. O quadro reduced está assentado.

FAIL por colisão em 768. Em `candidate-home-768.png` e `candidate-update-768.png` o breadcrumb Home e o chip Em andamento ocupam o mesmo sítio. O recorte da cápsula lê “HomEm andamento”. `scrollWidth` 768 e a âncora do botão Atualizar passam sem ver essa interseção. A publicação continua bloqueada. A próxima iteração staged mostra, em 768, os dois rótulos inteiros com folga entre as caixas. A verificação nova falha a captura se o retângulo do breadcrumb cruzar o do chip.

O refinamento de hierarquia, a repetição de Ativo e as conversas repetidas ficam fora desta correção. Não homologa. Não promove.

## Veredito da captura 05:36 — PASS da regressão

Pasta `.tmp/codex-candidate-home-review-20261013/20261013-053624/`. Os PNG da raiz anterior não entram. `report.json` `CAPTURED_STAGED_CANDIDATE`, `2026-10-13T05:36:24-0300`. Broker PID 6836. `published`, `broker_restarted` e `homologated` falsos. `page_errors`, `http_errors`, `blocked_requests` e `candidate_changed_during_review` vazios.

Bytes: `desktop.js` sha256 `63ff43258e4edfd959ab6c32610b9616a4ef0a37b0a0f67b1302536f46b17e01`, 2054866 bytes. `desktop.css` sha256 `a56c83143c5a37c0ce902a80c9bf9b9696bf821daae7b4828be4a883980f66ee`, 121562 bytes. `desktop.html` sha256 `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`, 1062 bytes. `manifest.json` sha256 `f4251b3829b1c2bd55c0634726344a1590192efbaf6c19c909841c95d2afa13f`, 13719 bytes.

Os doze PNG foram lidos. Em 768, Home termina em x 371 e Em andamento começa em x 391. O recorte da cápsula mostra as duas palavras inteiras, com folga. Em 390 e em 390 reduced, Home termina em x 105 e Em andamento começa em x 125, também 20 px, as duas inteiras. O menu aberto continua absoluto, com os três rótulos inteiros, sem empurrar a cápsula. O grupo aberto mostra uma linha, “Conversa com Sentra Aqrt”, e a contagem 45. O despejo de `message.uncertain` não voltou. Os seis Dots seguem visíveis. Em 1440 e em 768 o trilho mede 256 px no mesmo quadro. A vista reduced registra `runningAnimations` 0. O relatório marca Esc fechando o menu e o grupo abrindo e fechando pelo teclado.

PASS vale só para esta regressão e só para estes bytes. Não homologa a Home, o Canvas nem o Computador. Não promove. A hierarquia, os seis Ativo iguais e as conversas repetidas continuam pendentes, fora desta correção.
