# Modelos Web no SENTRA

O checkout `third_party/codex-chatgpt-web` permanece upstream puro, fixado em
`757942251222ee0f71953c35636679c6d92dd636` (v6.0.0). A interface Electron,
login, Browser Host, Responses, SSE, compaction e Turn Broker continuam
upstream-owned. A adaptação SENTRA fica em
`integrations/codex_chatgpt_web/sentra-upstream.patch` e é aplicada somente a
um worktree derivado durante o build.

O Model Gateway do SENTRA fica, por padrão, em `127.0.0.1:17842` e é a
fronteira consumida pelo Codex e pelo OMA. Ele expõe `/v1/models`,
`/v1/responses` e `/v1/responses/compact`. Modelos Web aparecem com o
prefixo `sentra/chatgpt-web/`; modelos nativos continuam sendo encaminhados.
SSE e cabeçalhos de turno são preservados de ponta a ponta.

## Fluxo de produto

```text
Codex / OMA
    |
    v
SENTRA Model Gateway :17842
    |  Run / Operation / TurnCapability / leases / fencing
    v
codex-chatgpt-web daemon :17841
    |
    +-- Responses + SSE + compaction
    +-- Turn Broker
    +-- Electron Browser Host
            |
            v
        ChatGPT Web
```

O Codex não deve ser configurado diretamente para o daemon `:17841`. O botão
**Conectar Codex** da aba **Web Models** usa a transação/journal do próprio
upstream, mas grava como destino o Gateway SENTRA em `/v1`. **Desconectar
Codex** restaura a configuração anterior pelo mesmo journal. Alterações de rota
exigem reiniciar o Codex para recarregar o catálogo.

A interface Electron upstream é reutilizada, não reimplementada. No SENTRA
Desktop, **Abrir interface Web** inicia o Gateway e o launcher; **Refresh**
apenas observa estado e não altera a configuração do Codex silenciosamente.

## Seleção de modelo

A aba **Web Models** do SENTRA Desktop possui um seletor explícito preenchido
pelo catálogo vivo de `/v1/models`. **Usar seleção** persiste o modelo no
state directory privado do usuário; não altera `config.yaml` e não modifica o
checkout upstream.

Para novas instâncias do OMA, a resolução do modelo `codex_web` segue esta
ordem:

1. `codex_web.model_name` explícito em configuração;
2. `SENTRA_CODEX_WEB_MODEL` no ambiente;
3. modelo salvo pela UI do SENTRA.

O valor persistido precisa usar o namespace `sentra/chatgpt-web/*`. A escolha
do usuário no picker nativo do Codex continua independente e pode selecionar
qualquer item do catálogo que o Gateway anunciou; o padrão do SENTRA define o
modelo usado pelo OMA quando não existe override explícito.

## Desenvolvimento e build

No checkout de desenvolvimento são necessários Python e Bun 1.4.0. Se Bun não
estiver no PATH, pode ficar somente em `.sentra/toolchain`.

```powershell
./scripts/integrations/Bootstrap-CodexChatGPTWeb.ps1
./scripts/integrations/Build-CodexChatGPTWebRuntime.ps1
python -m sentra_model_gateway.gateway --launch-upstream
```

O bootstrap valida remoto, commit, pacote e licença e mantém o checkout upstream
limpo. O build:

1. usa o commit fixado;
2. aplica o patch SENTRA em worktree separado;
3. valida `git diff --check`;
4. exige que o diff toque exatamente os arquivos declarados em
   `upstream.json.patch_files`;
5. registra SHA-256 do patch aprovado e do diff efetivamente aplicado;
6. executa typecheck/build do runtime;
7. gera `dist/web-models/win-unpacked/Codex Web GPT.exe` com runtime embutido.

Se um worktree anterior já estiver presente, o script reconhece o patch
anterior salvo e o substitui pelo patch aprovado atual. O checkout
`third_party/codex-chatgpt-web` não é modificado.

A release oficial executa esse build antes de montar Setup/MSI. O build grava
`web-models/integration-build.json` com o commit e o SHA-256 do patch aplicado;
a geração da release recusa um Electron construído com patch diferente do
patch atual. O instalador e o MSI também recusam payload sem Electron, runtime,
metadata de integração ou aviso de licença MIT. A instalação final não depende
do checkout nem de Bun separado.

## Rota do Codex

Com o Gateway ativo:

```powershell
bun run integrations/codex_chatgpt_web/codex_route.ts install
bun run integrations/codex_chatgpt_web/codex_route.ts status
```

O comando `status` verifica também a saúde do Gateway e retorna
`pointsToSentra`. O `install` só termina com sucesso se a transação do
upstream realmente deixar a rota em
`http://127.0.0.1:17842/v1`.

Para restaurar a rota anterior:

```powershell
bun run integrations/codex_chatgpt_web/codex_route.ts disconnect
```

No runtime empacotado, a própria CLI upstream recebe
`SENTRA_WEB_GATEWAY_URL` do supervisor e oferece `route sentra`; portanto o
mesmo mecanismo transacional funciona sem o checkout de desenvolvimento.

## Validação de conexão

**Verificar conexões** e o botão **Run doctor** da interface Electron usam o
Doctor unificado do SENTRA. O Gateway é a autoridade para MCP, relay/Edge,
tunnel, Durable Core e rota Codex; do upstream são reaproveitadas apenas as
checagens que realmente pertencem a ele, como Browser Host, login e Responses
proxy. O doctor upstream não é mais autoridade para o tunnel ou serviço local
do produto SENTRA.

O relatório do Gateway verifica, entre outros itens:

- SENTRA Model Gateway e Durable Core;
- SENTRA MCP e tunnel;
- Relay/Edge e, quando configurado, Remote Agent;
- Browser Host/login/Responses do sidecar;
- rota do Codex apontando para `127.0.0.1:17842/v1`;
- connector ChatGPT com identidade `SENTRA tunnel` por padrão (ou override `SENTRA_CONNECTOR_NAME`).

O endpoint `/sentra/doctor` exige Bearer administrativo ou o token interno de
Turn Authority. A interface Electron recebe esse token somente pelo ambiente
privado do launcher gerenciado. O Browser Worker também recebe
`SENTRA_CONNECTOR_NAME` e usa essa mesma identidade durante turnos com tools;
portanto não existe uma UI dizendo "SENTRA tunnel" enquanto o turno ainda procura o
connector legado `Codex Native2`.

No build integrado do SENTRA existe **um único owner de MCP/tunnel**. O sidecar
`codex-chatgpt-web` não cria, reconecta, adota, reinicia ou encerra um segundo
tunnel e não pede outro Tunnel ID/API key. Quando `SENTRA_WEB_GATEWAY_URL` está
presente, o runtime normaliza a identidade para `SENTRA tunnel`, força o modo
Automatic, habilita local tools pela autoridade do Gateway e trata
`Codex Native`/ `Codex Native2` apenas como identidades legadas.

Desktop e Gateway também validam o payload Web empacotado antes de iniciá-lo:
`integration-build.json`, SHA-256 do patch, conjunto de arquivos patchados e
commit upstream precisam corresponder à integração atual. Um `dist/web-models`
stale falha fechado com pedido explícito de rebuild, em vez de iniciar uma UI
antiga contra um runtime novo. O Browser Host publica o mesmo SHA-256 no seu
descriptor privado; o Gateway recusa adotar um launcher já vivo se essa identidade
não corresponder ao payload atual, evitando que um processo antigo sobreviva ao
rebuild como autoridade válida.

A disponibilidade do connector na conta ChatGPT é comprovada pelo próprio
Browser Host. O Doctor é observacional por padrão; quando o usuário aciona
**Verificar conexões** (ou o Doctor da interface Electron), o Gateway chama o
control endpoint privado com `verify-connector`, e o Browser Host verifica
`SENTRA tunnel` no catálogo do ChatGPT. O check só vira `ok` após essa
confirmação. O passo de conexão do launcher também executa o Doctor SENTRA antes
de avançar, sem criar processos de tunnel nem gravar novas credenciais.

Em modo SENTRA, o `DoctorSummary` do Electron mostra **todos** os checks do
relatório unificado; ele não reduz mais um estado saudável aos últimos seis
itens. Assim MCP, tunnel, relay/Edge, Durable Core, Browser/login, Gateway e
rota Codex permanecem visíveis na mesma validação.

## Autoridade de turno

Cada requisição a um modelo `sentra/chatgpt-web/*` recebe uma TurnCapability
opaca e um Run/Operation durável. O hash da capacidade e a identidade lógica
são persistidos no snapshot do Run, permitindo reidratação depois de restart
do Gateway sem persistir a capacidade em texto puro.

O canal interno Gateway <-> Broker/Browser Host possui um segundo Bearer privado
persistente, separado da TurnCapability. Assim, conhecer uma capacidade não é
suficiente para chamar os endpoints internos de autoridade.

O Browser Host publica no descritor privado a aba física, surface, trace,
conversation key e heartbeat. A autoridade mantém leases com fencing para:

- a aba física `browser-tab:<pid>:<tab>`;
- o assento lógico `conversation-uri:<hash>` quando o OMA fornece
  `conversation://...`;
- a conversa retida upstream `conversation:<hash>`, quando disponível.

No OMA, o `conversation://...` do assento é também projetado para o metadata
canônico do Codex: um `thread_id` determinístico identifica o assento e um
`turn_id` determinístico identifica a chamada. O upstream usa esse contrato
nativo para reutilização de contexto/chat; o SENTRA continua usando
`conversation://...` como identidade de autoridade e lease. O adapter permanece
`persistent_conversations=False` apenas porque essa flag antiga significa
"provider precisa devolver uma URL de chat", não porque o transporte Web seja
stateless.

Retries com o mesmo `thread_id` + `turn_id` não são reenviados silenciosamente.
O Gateway deriva uma chave idempotente no Durable Core e responde
`409 duplicate_turn` se a mesma identidade reaparecer, exigindo reconciliação em
vez de arriscar duas execuções do mesmo turno.

O heartbeat do Browser Host renova também esses leases no Durable Core. Em
compaction/rebrowser, a fase anterior precisa estar `SUCCEEDED`, seus leases
são liberados e uma nova Operation recebe novos fences.

Em turnos com ferramentas, o Turn Broker consulta a autoridade no registro,
antes de cada tool call, no prepare e no commit da conclusão. No registro ele
fixa a allowlist exata das tools expostas naquele turno (`namespace__tool` para
nomes namespaced); a TurnCapability persiste essa lista e recusa chamadas fora
dela, inclusive após recovery do Gateway. O commit só vence se a revisão do
Broker não mudou e os leases físicos/lógicos ainda forem válidos. Turnos sem
ferramenta usam `browser-start`, `browser-heartbeat` e `browser-complete`.

Se o modelo concluir mas a entrega HTTP/SSE ao cliente falhar, a Operation pode
preservar a conclusão observada, porém o Run fica `BLOCKED` e registra
`delivery_state=UNCERTAIN`. O SENTRA não transforma fim de processamento em
entrega confirmada.

## Tokens locais de controle

Os endpoints administrativos `/sentra/*` exigem Bearer. Se
`SENTRA_GATEWAY_ADMIN_TOKEN` não for fornecido, o Gateway cria e reutiliza um
token privado no state directory. O canal Broker/Browser usa outro token,
`turn-authority.token`, também privado e gerado pelo Gateway.

Drain/resume/interrupt não exigem mais que o SENTRA conheça o `controlToken`
do daemon. O Gateway usa o `control.endpoint` + token privado já publicado no
descritor do Browser Host; o Browser Control Server delega a operação ao
`RuntimeSupervisor`, que é quem conhece a credencial do daemon. O endpoint só é
instalado quando o launcher está sob autoridade SENTRA. `SENTRA_WEB_CONTROL_TOKEN`
permanece aceito apenas como fallback de compatibilidade. A aba **Web Models**
usa o token administrativo efetivo do próprio Gateway, sem duplicar segredos.
