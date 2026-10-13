# SENTRA — homologação real da UI e do Canvas (12/10/2026)

## Escopo e salvaguardas
- Dispositivo autorizado: OGrandeOxta. Checkout compartilhado: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
- Baseline: 596 entradas modificadas/não rastreadas no `git status --short`; nenhuma delas foi sobrescrita, resetada, commitada ou limpa nesta execução.
- Canvas principal: broker `python3.12.exe` PID 6836, iniciado às 15:58, porta 50282; janela nativa SENTRA PID 16736, aberta pelo teste de interface às 15:59.
- Processo `sentra-canvas.exe` PID 37316 pertence a um checkpoint de QA de 09/10 e **não** foi tratado como a janela atual.
- Sem reiniciar relay, Canvas, VM ou aplicativos; somente sessões criadas pela própria homologação foram encerradas.

## Provas observadas diretamente na janela nativa (UI Automation)
1. Na Home de Oxta, clique real em **Canvas** do Dot **Sentra Aqrt** abriu o Canvas correspondente. A UI mostrou Conversation do Dot e abas **SENTRA CLI · GPT-6 High**, **OpenCode · Muse Spark High**, **Codex CLI**.
2. Clique real em **Conversar** criou e abriu **Conversa com Sentra Aqrt**, com editor e botão Enviar mensagem. Não houve repetição de pedido de criação.
3. Foi enviada **uma única vez**, pela UI, a solicitação não destrutiva com marcador `SENTRA_QA_UI_20261012_A1`, sem ferramentas. A resposta do Dot exibiu esse marcador e ambos os lados apresentaram recibos.
4. Conferência read-only na fila protegida ligou o marcador à `conversation-41cc33e9c72c9903551c57100d9b029c` e à Operation `op-31067ec8e153ae0e5e7c4f67b1414cbc`; `canvas_shell_queue.state=completed`. Não foi necessário retransmitir a mensagem.
5. A volta da conversa ao Canvas através do botão **Canvas do Dot** funcionou.
6. As três abas de terminais foram acionadas individualmente, com **Abrir sessão**. Em cada uma, a UI passou a mostrar `running` e **Encerrar sessão**. Foram solicitados os três encerramentos pela UI, sem handoff/prompt aos CLIs. Após atualização, a aba selecionada mostrou `closed`.
7. Atualização de dados na interface ocorreu sem novo aviso de consulta ao runtime local no Canvas selecionado.

## Relay Web e modelo
- O health reportou inicialmente último resultado do catálogo HTTP 401; durante a homologação o Dot `sentra/chatgpt-web/gpt-6` respondeu à mensagem de prova.
- Nova consulta em 12/10/2026 às 20:13:23 UTC: último catálogo HTTP **200**, `accepting_turns=true`, `active_http_turns=0`, `active_browser_turns=0`. Sem alterar credenciais ou reiniciar.
- Esta prova visual do chat **não aferiu separadamente** o esforço High do turno. O modelo associado ao Dot foi exibido pela interface.

## Recibos reais anteriores, consultados nesta rodada
Arquivo `.tmp/live-root-dispatch-a75f9a8c8b/report.json`: `provider_mocked=false`, Operation raiz `SUCCEEDED`, GPT-6 Web High, 115,2 s; duas entregas **SENTRA CLI** e **OpenCode Muse Spark High**, cada uma com Operation `SUCCEEDED`, `model_result_verified=true` e WorkItem `IN_REVIEW`; resposta final com recibo confirmado.
Este relatório anterior prova inferência/despacho reais **no host e em Canvas isolado**, não na VM e não na interface nativa atual.

## Limites explícitos
- Abrir terminal em estado `running` não comprova inferência nem conclusão de WorkItem. Não foi emitido novo handoff dos CLIs nesta execução.
- Não foi comprovada execução das três CLIs **dentro da VM** nem a consolidação de um trio no mesmo Run pela interface.
- Um aviso transitório de consulta ao runtime local apareceu no chat; na atualização do Canvas ele não reapareceu. Causa raiz desse erro de rede não foi comprovada.
- Tentativa de captura por `PIL.ImageGrab` produziu imagem **toda preta**; portanto não há aprovação visual por pixels/screenshot. A validação de interação foi pela árvore de acessibilidade UIA.
- Não houve modificação do código-fonte nem publicação; este documento é o único novo arquivo durável registrado por esta rodada. A homologação completa do produto permanece parcial.

## Achado adicional de apresentação
- Na listagem **Conversas**, quatro itens com o título **Conversa com Sentra Aqrt** exibiram data **21/01/1970**. O arquivo `sentra_canvas/desktop_ui/src/shell-app.jsx`, em `conversationRow`, usa `new Date(row.updated_at)` diretamente; o valor de timestamp informado pelo backend parece estar em segundos. Essa apresentação exige correção e teste regressivo, mas não bloqueou a abertura da conversa. Nenhum arquivo de UI alheio a esta homologação foi alterado.
- O primeiro item da lista reabriu a conversa de QA com o marcador `SENTRA_QA_UI_20261012_A1` e a resposta preservada, comprovando navegação de volta ao histórico.
