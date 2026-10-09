# Modelos Web no SENTRA

O checkout `third_party/codex-chatgpt-web` permanece upstream puro, fixado em
`a13cd09950969f43e3b7e25c71fa43efaf5446c5` (v6.1.1). A interface Electron,
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
pelo último catálogo Web autenticado observado pelo Gateway. O endpoint nativo
`/v1/models` exige o Bearer real do Codex e não deve ser sondado diretamente
pela UI com uma credencial local fictícia. Em cada consulta autenticada do
Codex, o Gateway preserva o catálogo completo para o cliente e grava somente
metadados redigidos dos modelos Web em `/sentra/model-catalog`, protegido pelo
token administrativo local. **Usar seleção** persiste o modelo no state
directory privado do usuário; não altera `config.yaml` e não modifica o
checkout upstream.

Para novas instâncias do OMA, a resolução do modelo `codex_web` segue esta
ordem:

1. `codex_web.model_name` explícito em configuração;
2. `SENTRA_CODEX_WEB_MODEL` no ambiente;
3. modelo salvo pela UI do SENTRA.

O valor persistido precisa usar `sentra/chatgpt-web/*` ou, quando Gemini Web
estiver habilitado, `sentra/gemini-web/*`. A escolha do usuário no picker
nativo do Codex continua independente e pode selecionar qualquer item do
catálogo que o Gateway anunciou; o padrão do SENTRA define o modelo usado pelo
OMA quando não existe override explícito.

### Gemini Web

O mesmo runtime pode publicar, de forma **opt-in**, três rotas Gemini Web
suportadas pela integração: `gemini-web/flash-lite`, `gemini-web/flash` e
`gemini-web/pro`. Elas usam o relay durável do SENTRA e a mesma extensão do
Edge principal; não iniciam outro navegador, não usam Playwright como fallback
e não substituem o provider ChatGPT padrão.

**Catálogo suportado não é garantia de disponibilidade na conta.** A interface
do Gemini pode expor apenas um subconjunto dessas opções conforme conta, plano
ou rollout. Antes de um envio, a extensão confirma o modelo no seletor real da
aba adotada. Se a opção pedida não existir, o turno falha com
`MODEL_SELECTION_FAILED` **antes de SEND_MESSAGE**, portanto é seguro escolher
outro modelo e tentar novamente. O SENTRA não troca silenciosamente um modelo
explicitamente escolhido pelo usuário. Para automação e swarm, `flash` é o
default compatível; use `flash-lite` somente quando ele aparecer na sessão
Gemini atual.

Para o provider direto do orquestrador, habilite `gemini_web.enabled: true` e
escolha `gemini_web.model` em `config.yaml`. No runtime Codex/Web Models, as
rotas Gemini só entram no catálogo quando o Gateway encontra o token privado do
relay no state directory e injeta a configuração no processo filho. O token é
referenciado por caminho de arquivo; ele não deve ser copiado para
`config.yaml`, documentação, logs ou Git.

A continuidade é vinculada à URL exata da conversa Gemini. Tool calls são
aceitas somente pelo envelope SENTRA validado contra as tools realmente
oferecidas pelo Codex; nomes inventados, argumentos inválidos, chamadas
paralelas proibidas ou mistura de resposta final com tool call falham fechado.

## Desenvolvimento e build

No checkout de desenvolvimento são necessários Python e Bun 1.4.0. Se Bun não
estiver no PATH, pode ficar somente em `.sentra/toolchain`.

```powershell
./scripts/integrations/Bootstrap-CodexChatGPTWeb.ps1
./scripts/integrations/Build-CodexChatGPTWebRuntime.ps1
$env:SENTRA_STATE_DIR = (Resolve-Path ".\.sentra").Path
python -m sentra_model_gateway.gateway --launch-upstream
```

No fluxo de desenvolvimento acima, `SENTRA_STATE_DIR` deve apontar para o
mesmo state directory usado pelo relay local; assim Gateway e relay compartilham
a mesma autoridade privada sem copiar tokens. No produto instalado, o Desktop
já passa seu `state_dir` explicitamente aos serviços.

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


## Native Codex subagents vs SENTRA Research

SENTRA deliberately keeps two delegation planes distinct.

- **Codex native multi-agent** is owned by the Codex harness and uses its native
  `spawn_agent`, `wait_agent` and follow-up lifecycle. SENTRA routes Web-model
  turns and preserves the Codex protocol; it does not replace those tools with
  `sentra_research_*`. When Codex supplies canonical thread-spawn lineage,
  SENTRA binds that child thread to a durable Agent/subgoal under the parent's
  Goal and reuses the binding on later turns/restart, including nested child
  threads. Codex still owns spawn/wait/follow-up/terminal semantics. When the
  native runtime injects a canonical `<subagent_notification>`, SENTRA projects
  the terminal outcome into the subgoal and publishes a `RESULT`/`FAILURE` to
  the Context Bus; it does not infer completion from a Web turn ending.
  Notification replay is deduplicated by the native turn identity. If Codex
  issues a follow-up after a completed wait, SENTRA keeps the same Agent identity
  but creates a successor subgoal under the same parent instead of reopening a
  terminal Goal.
- **SENTRA Research** is a Control-Plane workflow for independent ChatGPT Web
  conversations. Each branch has a durable Agent/Chat/subgoal identity and its
  RESULT or FAILURE is published to the Context Bus before synthesis.

A release validation must exercise both planes separately. Passing Research does
not prove native `spawn_agent`; passing native Codex multi-agent does not prove
the Edge Research collector.

### Research collection on one principal Edge controller

Research may launch several independent generations, but SENTRA still owns only
one adopted principal-Edge controller. Collection is therefore cooperative:
`CHAT_PEEK` performs only `GET_STATUS` + `READ_RESPONSE` and branches are
polled round-robin. A peek never sends a message and never invokes the
side-effecting response waiter. The content script's bounded
`additional_checks` recovery remains a separate UI recovery mechanism and its
attempt/active state is exposed as telemetry.

Queue time and execution time are separate budgets. A branch that waited for the
single controller receives its execution deadline when leased; queue delay does
not consume the generation budget.

If one branch fails or times out after the send may have occurred, SENTRA keeps
the failure/uncertainty durably and does not replay the send automatically.
Successful sibling results remain available for partial synthesis when the
strategy permits it.

## Rotas GPT-6 e seletor compacto (outubro de 2026)

A integração reconhece o editor ProseMirror e os controles de seleção atuais do ChatGPT, incluindo o rótulo localizado `Selecionar modelo do ChatGPT`. O catálogo anuncia `sentra/chatgpt-web/gpt-6-instant` (Instant) e `sentra/chatgpt-web/gpt-6` (Medium/High, com Extra High somente quando disponível), além de `sentra/chatgpt-web/gpt-6-pro` quando autorizado pela conta. A rota `gpt-6` utiliza High como esforço padrão. A família GPT-6 e o nível de esforço são verificados no navegador antes do envio; a seleção `/model` sozinha não comprova que o turno foi executado.

Contas que mostrem apenas `6 Instantânea` com o próximo nível bloqueado podem usar o perfil Instant, mas High deve falhar antes de enviar a mensagem, com `chatgpt_effort_unavailable` ou `chatgpt_effort_locked`. Nunca rebaixar silenciosamente High para Instant, nem relatar tal falta de acesso como sobrecarga. Para conferir, use `/model sentra/chatgpt-web/gpt-6`, consulte `/model` e realize uma inferência somente depois que o navegador confirmar High. As rotas legadas `sentra/chatgpt-web/high` não fixam a família GPT-6.

**Superficie Think-only em chat temporario:** Algumas contas ou sessoes do
ChatGPT expoem apenas Pensar/Think no composer, sem seletor de modelo ou
esforco. Nao ha prova da familia GPT-6 nessa superficie. O Browser Worker
reconhece a condicao e recusa o turno com HTTP 400
chatgpt_model_controls_unavailable antes do envio; nao aguarda 70 segundos
nem converte a falha em server_is_overloaded. A correcao do acesso depende
de a sessao autenticada do ChatGPT apresentar o modelo e o esforco pedidos.
Nao desabilitar chats temporarios ou alternar contas silenciosamente.
