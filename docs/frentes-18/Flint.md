# Flint — frentes 1 e 10

Implementador: Flint. Maestro: Grok high. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
Sessão: grok-4.7, effort high, contexto 500k, always-approve. O modelo não foi alterado.
Registro: 2026-10-12.

Fontes lidas antes de editar: notas `frentes-18-coord` e `sentra-diagnostico-de-maturi`; `docs/SENTRA_STATUS_VERIFICADO_2026-10-12.md`; `docs/SENTRA_RELATORIO_INTEGRADO_FRENTES_2026-10-12.md`.

As frentes não estão fechadas. O código e o teste desta rodada existem. A prova física que exige conta externa não foi executada.

Grok high aceitou o primeiro corte em 2026-10-12: código e 10 testes unitários, sem prova física. Em 2026-10-13 o corte foi reaberto porque o despacho vivo não chamava o portão. `sentra_runtime/dot_tool_dispatch.py` agora só liga o portão; o runner não foi reescrito. A operação `op-94baad8161fb6fd4b4423e6ac1aecdeb` continua sem reenvio.

## O que entrou neste checkout

Admissão única de provedores e CLIs, sem enviar prompt:

- `orchestrator/providers/fleet_admission.py`
- `orchestrator/providers/trio_orchestration.py`
- `orchestrator/providers/__init__.py`
- `orchestrator/dispatcher.py` (`central_effect_admission`, `reconcile_coordinator_trio`)
- `integrations/codex_chatgpt_web/lane.py` (pin do ChatGPT Web e do Gemini Web; o pin não é inferência)
- `orchestrator/turn_scheduler.py` (entrega `UNCERTAIN` não entra em START)
- `orchestrator/conversation_pool.py` (assento `UNCERTAIN` não é reenviado)
- `sentra_cli/model_fence.py` (Antigravity gráfico não passa do checkpoint)
- `sentra_cli/agent.py` (instrução do coordenador e catálogo local no prompt do shell)
- `sentra_cli/codex_native.py` (`effect_key` já incerto não relança o CLI)
- `sentra_model_gateway/gateway.py` (`/sentra/status` inclui o catálogo `fleet`)
- `tests/unit/frentes/flint/test_fronts_1_and_10.py`

O trio só aplica reconciliação com Run `RUNNING`, WorkItem filho `IN_REVIEW`, Operation `SUCCEEDED`, Grant `model:invoke` do próprio filho e Grant de dispatch do coordenador, mais recibo verificado. O estado aplicado é `READY_FOR_PROMOTION`. `COMPLETED` não é escrito aqui. Recibo `ADMITTED`, ACK, eco ou `UNCERTAIN` não fecha. Guest sem processo verificado é recusado. Antigravity com `Antigravity.exe` fica `unavailable`: abrir a janela não é inferência.

`sentra_runtime/dot_tool_dispatch.py` chama `refuse_blocked_dispatch` antes de qualquer shell e `bind_live_lane` antes de `execute_non_interactive_tool`. O runner em `sentra_canvas/dot_tool_runner.py` não foi reescrito. Antigravity, guest sem processo verificado e a operação congelada são recusados antes do processo.

Texto de host (`coordinator_text`) não é inferência e não fecha o trio. `CanvasShellRuntime._publish_answer` e `ShellActorService.compose` chamam `retain_coordinator_turn`. A retenção abre a etapa `coordinator-review` e deixa o WorkItem em `IN_REVIEW`. `finalize_reviewed_trio` só grava `COMPLETED` depois de uma decisão `approved` em `review_decisions`. `prepare_live_trio` lê autenticação e recusa guest sem processo verificado; não envia prompt e não chama VBoxManage.

## Prova física contemporânea

Não há prova física de inferência nesta rodada.

- Não houve três inferências reais, três recibos de modelo, nem resposta de coordenador em conta externa.
- Não houve processo verificado dentro de VM. Nenhuma chamada a VBoxManage, guestcontrol ou CLI de modelo.
- `probe_antigravity()` rodou dentro do teste, sem observação e sem lançar o aplicativo. O teste exigiu `inference_verified is False` e `gui_launch_counts_as_inference is False`. Isso observa a ausência de contrato, não uma inferência não interativa.
- A operação antiga `op-94baad8161fb6fd4b4423e6ac1aecdeb` não foi repetida. Ela não entra nesta homologação.
- Nenhuma operação `UNCERTAIN` anterior foi reenviada. Nenhum Dot, VM, VDI, conversa, `.sentra` ou `.oma` de usuário foi apagado.

## Teste unitário executado agora

Comando, na raiz do checkout, em 2026-10-13:

`python -m pytest tests/unit/frentes/flint/test_live_dispatch_gate.py tests/unit/frentes/flint/test_fronts_1_and_10.py tests/unit/test_dot_tool_dispatch.py -q --tb=line`

Resultado desta execução: **19 passed in 69.39s**.

`test_live_dispatch_admits_the_lane_and_reconciles_three_receipts` chama `execute_dot_tool_dispatch` antes dos recibos e de novo depois dos três. A primeira resposta não executa a ferramenta e não devolve texto. A segunda devolve o texto do coordenador e deixa os filhos em `READY_FOR_PROMOTION`. O runner injetado não corre na resposta. Isso não é conta externa, guest verificado nem Antigravity não interativo.

O teste do trio usa um estado temporário do pytest. Cria Run, WorkItems, Operations e Grants reais nesse diretório, exige o recibo e move os três filhos de `IN_REVIEW` para `READY_FOR_PROMOTION`. Sem os serviços centrais, `closed` fica falso e o WorkItem não muda. Isso não é inferência de GPT-6, OpenCode, Codex ou Antigravity. A observação bem formada de Antigravity no teste deixa `physical_inference` falso de propósito.

## Estado de autenticação lido em 2026-10-13

Sem prompt e sem repetir `op-94baad8161fb6fd4b4423e6ac1aecdeb`.

- Codex: `C:\Users\vitor\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe`. `codex login status` saiu 0 e escreveu `Logged in using ChatGPT`. Isso é sessão de login, não recibo de inferência.
- OpenCode: `C:\Users\vitor\AppData\Roaming\npm\node_modules\@opencode\cli\bin\opencode.exe`. `opencode auth list --standalone` saiu 0 e escreveu `No authenticated integrations`. A sessão não está pronta. A dependência é uma integração autenticada. Não há recibo.

Grok high confirmou este limite: as frentes 1 e 10 ficam abertas até existir integração autenticada do OpenCode. Sem ela o trio real não se prova. Não houve prompt, inferência, uso de VBoxManage, nem repetição de `op-94baad8161fb6fd4b4423e6ac1aecdeb`.

Contrato v2 da auditoria: `record_fleet_admission` é fallback e não sela. A memória do Dot só é gravada quando o runner do produto observou `native_process` com `live_model_verified` e o selo de `record_runner_final_answer` leu o lease da Operation. Flag sintética e runner injetado não gravam sessão e não fecham a frente.

## O que não está homologado

1. Frente 1. Três inferências reais, três recibos de modelo, WorkItems conciliados num Canvas de verdade e resposta do coordenador. Exige conta externa. Parado e escalado. Não declarado como feito.
2. Frente 1 dentro da VM. Só vale com processo verificado no guest. Não houve esse processo.
3. Frente 10. Antigravity com inferência não interativa verificada. O contrato continua ausente; indisponível fica explícito. Janela aberta não conta.
4. Autenticação e cota de SENTRA CLI, OpenCode e Codex. Presença de executável no catálogo não autentica.
5. Ligação do dispatch ao vivo do Canvas ao novo fechamento. Fora dos arquivos exclusivos. O loop antigo de browser em `dispatcher.py` não passou a exigir esta admissão, para não mudar o comportamento já testado daquele loop.
6. Promoção `READY_FOR_PROMOTION` → `COMPLETED`. Continua explícita e não foi feita.
