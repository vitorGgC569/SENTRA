# OMA Browser Bridge (Edge MV3) — instalação e operação real

Atuador do OMA dentro do Edge que você realmente usa (cookies, login, perfil
e Recentes reais). A extensão NÃO decide nada: executa operações primitivas
(`NEW_CHAT`, `SEND_MESSAGE`, `WAIT_RESPONSE`, `READ_RESPONSE`,
`GET_CONVERSATION_ID/URL`, `STOP_GENERATION`, `GET_STATUS`) e reporta ao relay.

`SEND_MESSAGE` aceita `images` (data URLs PNG/JPEG, máx 2 por job): cola cada
uma no composer via clipboard real ANTES do texto e confirma quantas anexaram
(`images_attached` no resultado; 0 com imagens enviadas = paste falhou, job
FAILED honesto, nada enviado). Nunca executa "paste" sem antes escrever o
próprio conteúdo (jamais toca no clipboard do usuário). Após atualizar os
arquivos, RECARREGUE a extensão em `edge://extensions` (versão atual 1.6.24).

Anti-morte-silenciosa MV3: WAIT fatiado em 25s (cada fatia renova o lease),
job ativo persistido em storage (restart retoma sem reenviar), a tab pinga o
SW a cada ~10s (mensagem acorda SW suspenso) e o worker carrega telemetria
`hb/slices/cshb/rec`. Fases `ready/sending/sent/waiting/reading` via
`POST /jobs/progress` (best-effort; relay antigo ignora sem quebrar).

> Nota de conformidade: automatizar a UI do chatgpt.com pode violar os Termos
> do serviço. Para ChatGPT, o caminho suportado é a API. Esta arquitetura é
> agnóstica a provider — use-a com sites cujos termos permitam automação.

## Subir o caminho real

1. Na raiz do projeto, inicie `python -B main.py --relay`. Ele persiste os jobs em
   `.oma/relay.sqlite3` e informa o arquivo do token de pareamento. Não exponha o token.
2. Edge → `edge://extensions` → modo desenvolvedor → "Carregar sem compactação"
   → pasta `edge_extension/`.
3. Nas opções da extensão, cole o token de `.oma/relay-token`, marque Ativar e salve.
   A extensão usa exclusivamente o Edge/perfil em que foi instalada. Não abre outro
   navegador e não cria nem fecha tabs. Quando há trabalho no relay, adota temporariamente
   uma aba `chatgpt.com` já aberta e inativa como controller único, guarda sua URL
   original, alterna os chats por `conversation_id` e restaura essa URL quando libera o
   controller. A aba ativa do usuário nunca é sequestrada. Se não houver uma aba ChatGPT
   inativa no perfil principal, o SENTRA falha fechado.
4. OMA submete jobs via `BrowserExtensionProvider` (relay_base padrão
   `http://127.0.0.1:8765`) ou `scripts/run_extension_swarm.py`.
5. Confira `python -B main.py --doctor`. Para roundtrip real no PowerShell,
   defina `$env:OMA_LIVE_EXTENSION = '1'` e rode
   `python -B -m pytest tests/e2e/test_extension_live.py -s` com o relay já ativo.

Novas instalações começam desativadas. Tokens não vão para prompts; jobs possuem
lease, expiração e correlação por tarefa/worker. Resultados aguardam ACK e sobrevivem
ao restart do relay. Falhas de entrega incertas não são automaticamente reenviadas.
A versão 1.6.24 usa controller lazy único, `CHAT_START/CHAT_COLLECT` por
`conversation_id` e recovery limitado de avisos transitórios “additional checks”.

Controller: existe no máximo uma referência SENTRA a uma aba ChatGPT já aberta.
O paralelismo de research é lógico, não visual: `CHAT_START` envia em uma conversa
e retorna o `conversation_id`; a geração continua no servidor enquanto o controller
navega para outros chats; `CHAT_COLLECT` volta depois pelo ID. O SENTRA nunca cria
uma tab por subagente e nunca fecha a aba adotada.
