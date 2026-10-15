# Iris — frentes 4 e 6 — 2026-10-13

Corte seguinte, sem sonda física nova e sem editar `service-worker.js`.

`native-image-guard.js` continua fora do service worker. O manifest tem um único `service_worker` e o hash `edfda4428a90710337317e26b2eba622b8b9f065460964f7adcf0f846fe4bc5f` permanece. O relay lê esse hash. Gravar o worker derrubaria o coletor vivo.

O primeiro efeito de input passa por `SemanticUIAExecutor.start`. O pid que chega ao motor é o da binding (`4242` no teste), não um atributo do dublê. O valor `from-executor` é a resposta desse backend de teste. Sem pid no perfil do convidado, `run_authorized_guest_step` recusa antes de `UIAProbeEngine`. Efeito já `UNCERTAIN` não é chamado de novo.

Captura real do guest Debian `fcd974cf-ccdc-5636-b7af-2f96024d5dde`, framebuffer VirtualBox 1280×800, Guest Additions 7.2.20 runlevel 2. A tela é o greeter Debian 13, usuário `sentra`, senha vazia. Nenhum teclado e nenhum mouse foram enviados. Essa captura não é Computer Use concluído. Neste corte não houve `guest.run`. O job `websend_8a4ed7c1363ce9404fb38774cab0963060293dca1786c5739d41cb174b0d27a7` não foi reenviado. As frentes 4 e 6 não estão homologadas.

Coletor instalado, só leitura: extensão `jclddpgggpogcoeombcaedlfoihfdmlm` online, hash `edfda4428a90710337317e26b2eba622b8b9f065460964f7adcf0f846fe4bc5f`, `enabled=1`, `generated_assets_configured=true`. `workers_online` vazio. Nenhum ativo nativo finalizado. Um job `websend_8a4ed7c1363ce9404fb38774cab0963060293dca1786c5739d41cb174b0d27a7` está `sending` com `may_have_sent=1` e não foi reenviado. Sem bytes, a frente 6 continua `ADMITTED`. O próximo passo do binário é alugar uma aba ChatGPT já aberta nesse coletor e deixar o service worker atual enviar a imagem nativa já commitada; não gira hash e não dá reload. As sondas Unicode `UNCERTAIN` da janela própria não foram repetidas. `UNCERTAIN_NO_RESEND` não foi reenviado. Sem bytes reais, a frente 6 continua `ADMITTED`.

## Registro de 2026-10-12

Implementação no checkout `C:\Users\vitor\OneDrive\Desktop\SENTRA`. Sem commit, push, reset ou limpeza. Nenhuma VM, VDI, Dot, conversa, relay, backend ou Edge foi reiniciado. Nenhuma operação UNCERTAIN antiga foi reenviada.

## Frente 4 — Computer Use

Ciclo `GraphicalComputerUse`: captura, localização, um clique, uma digitação e leitura posterior. Cada passo é uma Operation no Run do WorkItem, com Grant e posse de input. Clique ou teclado UNCERTAIN fica em `machine_input_uncertain` e não é despachado de novo. O executor semântico também recusa o mesmo efeito antes de chamar o backend.

A busca do elemento usa a especificação da janela. Um wrapper UIA não tem `child_window`, e um controle sem nome não derruba mais a observação.

### Prova física contemporânea

Janela Win32 própria `SENTRA-Iris-Probe`, edit `automation_id=1001`. Não é Dot, VM nem conta externa.

Run `run-iris`, WorkItem `work-iris`, agente `agent-iris`, capacidade `desktop:computer-use`, tarefa `task-live`. Base temporária `C:\Users\vitor\AppData\Local\Temp\iris-front4-central-8`. Relato `C:\Users\vitor\AppData\Local\Temp\iris-front4-physical.json`.

| Passo | Operation | Estado | Efeito |
| --- | --- | --- | --- |
| Captura | `op-task-live-capture` | SUCCEEDED | PNG da janela em `C:\Users\vitor\AppData\Local\Temp\iris-front4-capture.png` |
| Elemento | `op-task-live-locate` | SUCCEEDED | Edit 1001, retângulo `[104, 151, 394, 179]` |
| Mouse | `op-task-live-mouse` | SUCCEEDED | Um `SendInput` no centro do edit. `mouse_dispatched=1` |
| Relocalização | `op-task-live-relocate` | SUCCEEDED | Mesmo runtime id |
| Teclado | `op-task-live-keyboard` | SUCCEEDED | `WM_CHAR` só nesse hwnd, depois que o foco do thread era o edit. `keyboard_dispatched=1` |
| Verificação | `op-task-live-verify` | SUCCEEDED | `value` lido de volta: `iris-ok` |

Estado da tarefa: `SUCCEEDED`. A janela foi destruída ao fim.

Duas sondas anteriores, em bases temporárias separadas, enviaram teclado Unicode global. O valor não voltou `iris-ok`. Essas Operations ficaram `UNCERTAIN` e não foram repetidas. A prova acima é outra Run, com mensagem de teclado dirigida ao edit já focado.

### Teste automatizado executado agora

`python -m pytest -q tests/unit/frentes/iris/test_front4_computer_use.py tests/unit/frentes/iris/test_front6_native_image.py`

8 passed em 4,00 s, nesta rodada final.

O teste da frente 4 usa o Control Plane real e um dispatch duplo. Cobre Grant obrigatório, o ciclo completo, e que um mouse `UNCERTAIN` não é despachado outra vez. Não substitui a prova da janela.

### O que essa frente não homologa

Não houve tarefa gráfica dentro da VM do Dot, nem clique em aplicativo de terceiros. O teclado da prova final é `WM_CHAR` no controle localizado, não uma tecla global.

## Frente 6 — imagem nativa

`WebGeneratedAssets.verdict` só devolve `VERIFIED` com MIME, tamanho e SHA-256 dos bytes lidos de volta. Sem binário finalizado o estado é `ADMITTED`, `success=false`. `mark_uncertain` grava `UNCERTAIN_NO_RESEND`; `chunk` e `finalize` passam a recusar esse job e não buscam de novo. `project_native_image` não promove admissão nem incerteza a entrega. `dispatch_shell_turn` marca `generated_asset_verified=false` e `admission_status=ADMITTED`.

`edge_extension/native-image-guard.js` repete essa decisão para a extensão. O `service-worker.js` em execução não foi alterado: mudar o arquivo gira `sentra_source_hash`, e o relay lê esse hash a cada pedido. Isso derrubaria o coletor vivo sem um reload autorizado do Edge.

### Teste automatizado executado agora

Os mesmos 8 testes Python, mais:

`node --test tests/unit/frentes/iris/native-image-guard.test.cjs`

3 passed. O PNG do teste Python é fixture sintético, não captura do ChatGPT.

### Prova física

Não feita. Exige conta externa no ChatGPT Web. Não declarei imagem real, nem reenviei a operação `UNCERTAIN_NO_RESEND` já registrada. `ADMITTED` sem binário não conta como sucesso.

O Canvas continua a publicar só ativo finalizado por `for_job`. Esse módulo de Canvas está fora dos arquivos desta frente.

## Arquivos

- `sentra_executors/input_control.py`
- `sentra_executors/uia_semantic.py`
- `sentra_executors/ufo_actions.py`
- `native_bridge/web_generated_assets.py`
- `native_bridge/shell_multimodal.py`
- `edge_extension/native-image-guard.js`
- `tests/unit/frentes/iris/test_front4_computer_use.py`
- `tests/unit/frentes/iris/test_front6_native_image.py`
- `tests/unit/frentes/iris/native-image-guard.test.cjs`
- `docs/frentes-18/Iris.md`
