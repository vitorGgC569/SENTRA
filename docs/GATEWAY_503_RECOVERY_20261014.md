# Recuperação do erro 503 do SENTRA — 14/10/2026

**Estado: reconstrução concluída, publicação BLOQUEADA por processos externos. A falha 503 NÃO está homologada como resolvida.**

## Sintoma
Codex recebe HTTP 503 "upstream connect error/disconnect/reset before headers" em http://127.0.0.1:17842/v1/responses, com CF-Ray de GRU. O cliente usa `openai_base_url=http://127.0.0.1:17842/v1` e `model=gpt-6.1-sol`.

## Provas do host
- Porta 17842: sentra_model_gateway.gateway, PID 12772, ativo desde 08h18.
- Porta 17841: produtor Codex Web GPT 6.1.1; GET /healthz 200, accepting_turns=true.
- Gateway GET /livez e /healthz 200; 32 GET locais simultâneos 200. Isto não comprova que uma inferência longa funcione.
- Canvas/MCP/túnel SENTRA e túnel Codex tiveram verificações de prontidão aprovadas.
- A auditoria `model.request.started` abrange rotas WEB gerenciadas; o tráfego nativo `gpt-6.1-sol` é passthrough sem esse evento. Portanto, ausência de eventos recentes NÃO prova que a requisição não chegou ao gateway.
- Doctor autenticado: `web-payload=error`, `browser-host=error`, `codex-route=error`; causa detalhada: "Web Models payload is stale; rebuild scripts/integrations/Build-CodexChatGPTWebRuntime.ps1".
- Hash do patch atual de integração NÃO corresponde ao metadata do pacote ativo; commit upstream coincide. Os erros de integração são concretos, embora a causalidade específica de cada CF-Ray ainda não esteja comprovada.

## Correção da ferramenta de build
- `scripts/integrations/Build-CodexChatGPTWebRuntime.ps1` executava `node --test launcher/tests/saved-conversations.test.cjs` antes de `bun install` em `launcher`; no worktree limpo falhava em MODULE_NOT_FOUND: electron.
- Ordem corrigida para instalar dependências Electron 1.4.0 antes de executar o conjunto de testes do launcher.
- Build da integração: 72 testes Bun PASS; 9 testes do launcher PASS; TypeScript e Vite PASS; bundle/runtime e Electron win-unpacked concluídos.
- O pacote novo foi preparado em `dist/web-models.staging-37512`, contendo exe, manifest e integração. Metadados validados: patch SHA256, patch_files e commit correspondem ao código atual.
- O executável staged `win-unpacked/Codex Web GPT.exe` tem 223.748.608 bytes.
- `git diff --check` do script corrigido passou; checkout upstream original limpo; fonte de build usa worktree isolado em %LOCALAPPDATA%/SENTRA/Build/qa-web-models-20261014/stage.

## BLOQUEIO DA PUBLICAÇÃO (proteção aplicada corretamente)
- O script detectou os processos antigos Codex Web GPT.exe executando a partir de `dist/web-models`, incluindo o processo raiz PID 6188 e outros filhos. Há também PID 320 independente.
- Resposta do desligamento: `headless-upstream-pid-stale` e `browser-host-not-owned`.
- O script recusou sobrescrever os executáveis vivos de processos que não pertencem ao SENTRA; não usou taskkill nem forcou encerramento.
- A última observação mostrou 0 turnos HTTP ativos e 0 turnos do navegador ativos, mas isto não equivale a comprovar que todas as abas e sessões tenham seu estado salvo.
- Runtime antigo e sessão do usuário foram preservados; a versão nova NÃO foi publicada nem reiniciada; erro 503 não deve ser considerado resolvido.

## Próxima ação segura
1. Obter consentimento explícito para encerrar o runtime Web Models externo, pois não há janela principal Win32 e os processos não são identificados como gerenciados pelo SENTRA.
2. Salvar/verificar conversas pendentes, confirmar novamente 0 turnos ativos; tentar encerramento gracioso pelo próprio aplicativo, não força sem autorização adicional.
3. Reconfirmar ausência de todos os processos que usam `dist/web-models`; publicar pacote staged em troca transacional com rollback e reativar runtime com identidade SENTRA.
4. Confirmar `/sentra/doctor` sem erros de payload/browser-host/rota, saúde upstream, autenticação e teste de inferência nova única (não reenviar operações incertas).
5. Se o 503 persistir mesmo com patch validado, investigar especificamente a resposta do provedor Cloudflare e os CF-Rays; não atribuir exclusivamente ao payload desatualizado.

## Preservação
Nenhum dado da VM Windows, VDI, WorkItem, Grant ou operação incerta foi alterado nesta frente. Nenhum serviço externo foi morto à força.


## Recuperação autorizada e testes físicos — atualização final

- Usuário autorizou encerrar à força os processos Web Models antigos para publicar o runtime novo.
- Confirmada ausência de turnos ativos antes do desligamento. O encerramento da árvore raiz PID 6188 também removeu os subprocessos correspondentes. O script recusou repetir um encerramento quando o segundo PID já havia desaparecido. A verificação posterior confirmou que nenhum processo antigo do executável persistiu.
- Publicação transacional **real** concluída: `dist/web-models.staging-37512` foi movido para `dist/web-models`; o pacote antigo foi preservado em `dist/web-models.rollback-before-20261014-503-repair`. Hash do patch atual, commit, arquivos de patch e payload foram validados pelo `LauncherSupervisor.validate_payload()`. Arquivo `.sentra/integrations/codex-chatgpt-web/runtime-build.json` atualizado com metadata do build publicado.
- Browser Host novo iniciou PID 36460 com descriptor `sentraManaged:true`. Upstream da nova distribuição iniciou PID 37920. Ambas as portas 17841 e 17842 responderam HTTP 200; `ModelClient._browser_host_ready()` e `._upstream_ready()` retornaram True, e a rota Codex informou `installed=True, active=True, points_to_sentra=True`.
- Testes de build: 72 Bun e 9 Node/launcher aprovados; script PowerShell corrigido para instalar dependências Electron **antes** dos testes de persistência.
- Inferência nova, única e inofensiva com `codex exec --ephemeral --sandbox read-only -m gpt-6.1-sol` e `model_reasoning_effort=low`: exit 0, marcador exato `SENTRA-PROBE-1726` presente, **17,89 s**, sem 503 nem reset de upstream nesta amostra. Esse teste não reproduziu tarefas antigas incertas. Uma tentativa de benchmark anterior, bloqueada por stdin de um terminal interativo, foi terminada isoladamente, sem reenvio.
- Após atualização, 24 GETs HTTP locais no gateway `/livez`: 24/24 HTTP 200, mediana 103,35 ms, p95 149,8 ms. No upstream `/healthz`: 24/24 HTTP 200, mediana 89,35 ms, p95 108,6 ms. Não são métricas de tempo de inferência; não atribuir ganho causal somente a esses números.
- Ajuste de baixa latência implementado em `sentra_model_gateway/gateway.py`: `GatewayHandler.disable_nagle_algorithm=True` para enviar frames SSE pequenos imediatamente no socket cliente. Teste TCP real `tests/unit/test_gateway_sse_tcp_nodelay.py` e regressão de entrega do gateway: **24 testes aprovados** e git diff --check sem erro. **O gateway ativo ainda não carregou esse ajuste.**
- Tentativa de reinício do gateway 17842 para ativar a melhoria foi corretamente BLOQUEADA antes de qualquer mutação porque o upstream reportou `active_http_turns=1`. Gateway PID 12772 permaneceu ativo e respondeu HTTP 200. Não reiniciar nem repetir turnos incertos enquanto houver trabalho ativo.
- Diagnóstico do launcher sob o novo pacote: `config=ok`, `browser-host=ok` e navegador autenticado; `proxy=error` porque `launcher-supervisor.json` conserva o `ownerPid=6188` e `daemonPid=14436` da instalação antiga, ao passo que o novo upstream foi iniciado pelo SENTRA como processo separado PID37920. **O indicador de propriedade ainda precisa ser reconciliado pelo fluxo real do supervisor, não por edição manual/espoofing de PID.** Não confundir essa pendência com indisponibilidade do listener 17841.
- O erro Cloudflare 503 pode ter causas fora do host; um teste real sem 503 comprova restauração naquele momento, não ausência futura de falhas intermitentes. Latência de ~18 s em um prompt mínimo mostra espaço para melhorar o caminho de inferência/modelo; ~0,1 s de loopback indica que o trânsito entre as portas não é responsável pela maior parte da espera.
- Nenhuma modificação foi realizada na VM Windows, VDI, WorkItems/Grants e operações de VM. Não houve push, commit nem reinício indevido do gateway.

**Próximos gates:** permitir que a(s) Operation(s) HTTP pendente(s) sejam confirmadas ou reconciliadas, regularizar posse nativa do supervisor sem forjar o marcador, ativar a otimização TCP em reinício seguro do gateway, e executar monitoramento longitudinal de inferências para separar intermitência Cloudflare de latência do provedor.

## Investigação da hipótese de instalação duplicada — 14/10/2026

**Conclusão delimitada:** não há evidência de dois servidores locais concorrendo por 127.0.0.1:17841 ou 127.0.0.1:17842. Isso NÃO exclui uma rota/túnel antigo registrado remotamente; a listagem administrativa remota não pôde ser efetuada com as credenciais disponíveis.

### Inventário físico e identidade
- Listener 17841, TCP IPv4 loopback, produtor Bun gerenciado; único PID 37920 na inspeção.
- Listener 17842, TCP IPv4 loopback, gateway Python; PID 12772 antes da manutenção, PID 12060 após reinício autorizado e seguro. Apenas um listener em 17842 após o reinício. Nenhum concorrente IPv6 observado.
- Dois processos tunnel-client: Codex PID 25428 (health local 60283) e SENTRA PID 9492 (health local 57003), ambos do usuário host atual, ambos /healthz /readyz/control-plane poll OK. Os respectivos IDs de túnel foram comparados sem divulgar identificadores: **diferentes**, um perfil por serviço. O perfil SENTRA aponta para MCP 127.0.0.1:8000/mcp.
- Nenhuma tarefa agendada Codex/Grok adicional identificada; quatro tarefas SENTRA existentes pertencem ao usuário atual; nenhum serviço Windows duplicado para as portas. Não foram identificadas entradas de PortProxy redirecionando 17841/17842.
- Há outro perfil Windows, mas estava descarregado e não havia processos Codex/gateway/túnel ativos nesse perfil. Partes de AppData têm ACL restritiva; não houve bypass de permissões.
- Variáveis de ambiente HTTP_PROXY, HTTPS_PROXY, ALL_PROXY e NO_PROXY não estavam configuradas no processo de diagnóstico; não apareceu proxy explícito nesse shell.
- A listagem de aliases Codex retornou **um** alias local. A tentativa de enumerar os túneis remotos no escopo da organização foi recusada; cadastro remoto duplicado não foi descartado.

### Correção de observabilidade implementada e homologada
- `sentra_model_gateway/gateway.py` registra eventos sem prompts/tokens para POST /v1/responses: `model.gateway.received` com correlation_id local, e `model.gateway.forwarded` com status HTTP e elapsed_ms. Falhas de transporte geram `model.gateway.transport_error` com fase/exception_class/headers_recebidos, sempre `automatic_retry:false`. Falha de auditoria não altera a resposta ao cliente.
- Testes novos `tests/unit/test_gateway_native_route_trace.py`, `tests/unit/test_gateway_sse_tcp_nodelay.py`, regressão `test_sentra_cos_gateway_completion_gate.py`: **27 passed** em pytest; `git diff --check` passou.
- Ajuste de transmissão TCP_NODELAY pré-existente e nova auditoria foram ativados pelo reinício **somente do gateway**, após verificar zero turnos HTTP e browser ativos. Gateway PID antigo 12772 foi encerrado e gateway novo PID 12060 iniciado pelo cliente SENTRA; /healthz 200 e `ready:true`, exatamente um listener 17842. Upstream, túnel, navegador e VM não foram reiniciados.
- Uma única inferência NOVA e efêmera `gpt-6.1-sol`, sandbox somente-leitura, raciocínio low, concluiu com exit 0 e marcador esperado `SENTRA-NEW-ROUTE-PROBE-1738`, **10,64 s**, nenhum 503/CF-ray/reset no cliente. Não repetir solicitações antigas incertas.
- A auditoria nova confirmou o par recebido → encaminhado `/v1/responses`, status upstream 200, **4.515 ms** no gateway.
- Também apareceu um evento `ConnectionAbortedError` com cabeçalhos upstream já recebidos e fase `unknown` às 20:52:15 UTC. O evento ocorreu antes do par de POST concluído e pode decorrer de uma conexão que o cliente fechou (inclusive probe WebSocket GET). **Não comprova a origem do 503 do usuário** e não é justificativa para reenvio.

### Remanescente
- A origem do 503 intermitente com `cf-ray` não foi confirmada. Um resultado HTTP 200 local e uma única inferência bem-sucedida não provam ausência de falhas na rota remota.
- Necessário comparar o próximo erro novo (hora exata + CF-Ray) aos novos eventos `model.gateway.*`: ausência de `received` indica falha antes de POST chegar ao gateway; `forwarded.upstream_http_status=503` indica erro retornado por upstream; `transport_error` indica falha de socket e se chegou a receber cabeçalhos.
- Cadastro de túneis na organização requer autorização administrativa de listagem remota; não remover/migrar túneis de outro usuário por hipótese.
- WARP está ativo no host, porém não foi estabelecida relação causal; não mexer no serviço sem evidência.
- Nenhum VDI, VM, WorkItem, Grant, conversa ou credencial foi apagado; não houve commit/reset/push.
