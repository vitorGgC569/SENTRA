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
arquivos, RECARREGUE a extensão em `edge://extensions` (versão atual 1.5.0).

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
   Abra o site alvo logado. O service worker cria duas tabs próprias e começa o polling
   autenticado em `http://127.0.0.1:8765`. Tabs pessoais não são adotadas.
4. OMA submete jobs via `BrowserExtensionProvider` (relay_base padrão
   `http://127.0.0.1:8765`) ou `scripts/run_extension_swarm.py`.
5. Confira `python -B main.py --doctor`. Para roundtrip real no PowerShell,
   defina `$env:OMA_LIVE_EXTENSION = '1'` e rode
   `python -B -m pytest tests/e2e/test_extension_live.py -s` com o relay já ativo.

Versão 1.2.0: recarregue a extensão no Edge após atualizar os arquivos. Novas instalações
começam desativadas. Tokens não vão para prompts; jobs possuem lease, expiração e
correlação por tarefa/worker. Resultados aguardam ACK e sobrevivem ao restart do relay.
Falhas de entrega incertas não são automaticamente reenviadas.

Pool: poucas tabs servem muitas conversas por reutilização
(50 tarefas → 3 workers; `browser/tab_pool.py` no Python espelha os estados
`IDLE/BUSY/WAITING_RESPONSE` como `BROWSER_WORKER_01..N`).
