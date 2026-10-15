# Keel — coordenação das frentes 8–9 e 11–18

Orquestrador: Keel. Maestro: Grok high. Checkout: `C:\Users\vitor\OneDrive\Desktop\SENTRA`.
Sessão: grok-4.7, effort high, contexto 500k, always-approve. Modelo não alterado.
Registro aberto em 2026-10-12 23:01. A leitura das 23:58 foi superada em 2026-10-13 pela decisão do Grok high. A ordem das 23:10 não foi reenviada. Keel não edita código de produto. Este arquivo é o único que Keel escreve.

Fontes lidas: notas `frentes-18-coord` e `sentra-diagnostico-de-maturi`; `docs/SENTRA_STATUS_VERIFICADO_2026-10-12.md`; `docs/SENTRA_RELATORIO_INTEGRADO_FRENTES_2026-10-12.md`. `maestri list` confirma Lumen, Nimbus, Quartz, Sable e Wren ligados a Keel, e Grok high ligado a Keel.

## Barra de fechamento

Ordem de 2026-10-12, depois do registro das 23:05: implementação integral primeiro. Testes e validações somente ao final da implementação integral. Pytest, teste de interface, `npm test` e `npm run build` não entram no meio do código.

Uma frente só entra como fechada neste dossiê quando as três linhas existem ao mesmo tempo, depois dessa implementação integral:

1. Código da frente está neste checkout, dentro dos arquivos exclusivos do par.
2. O teste automatizado da própria frente foi executado na validação final. A saída citada é a desta execução. Teste antigo, fixture, ACK, `ADMITTED` ou build anterior não homologam.
3. O dossiê `docs/frentes-18/<Nome>.md` separa prova física contemporânea de teste unitário. Efeito real só conta com Run, WorkItem, Operation, Grant e recibo. Operação `UNCERTAIN` não é reenviada.

Prova que apaga Dot, VM, VDI ou conversa, ou que exige conta externa, para na hora e sobe para Grok high. Não é declarada como feita.

## O que já está provado e não se repete

- Debian persistente do Dot Advanced verificado (VM `fcd974cf-ccdc-5636-b7af-2f96024d5dde`). A interface ainda não faz a instalação sozinha. Não reinstalar essa operação incerta.
- Cópia host→guest: a tentativa física anterior permanece `UNCERTAIN`. Não repetir. Não é escopo destes cinco pares.
- Imagem nativa: transporte e `/image` existem; `BINARY_UPLOAD_UNCONFIRMED` e `UNCERTAIN_NO_RESEND` não são entrega. `generated_asset_verified: true` é a única prova de binário. Não é escopo destes cinco pares.
- Smart UI declarativa teve ciclo real e `shell-interactive-ui.test.mjs` com 3 passed, mais `npm run build` do Vite. Isso não fecha a frente 8. Lumen amplia a interface e verifica o fluxo na UI.
- Atalho e build do desktop passaram em rodada anterior. Instância única e o botão Atualizar ficaram sem homologação final. Não tratar aquele build como fechamento da frente 9.
- Exclusão física de Dot, VM ou VDI continua sem aprovação. Nenhum destes pares a executa.
- Antigravity com janela aberta não é inferência. Fora do escopo destes cinco pares.

## Pares

| Par | Frentes | Decisão 2026-10-13 | Dossiê | Teste | Prova física |
| --- | --- | --- | --- | --- | --- |
| Lumen | 8 e 9 | Aceita na barra de corte. Terminal listado não reabre. | `Lumen.md` separa as seções | 19 pass / 0 fail; Electron 5 pass / 0 fail; instalador `SENTRA_DESKTOP_INSTALL_OK`; Vite `built in 2.67s` | harness headless. Sem shell ao vivo, Desktop real ou segunda instância |
| Nimbus | 11 e 12 | Aceita na barra de corte. Terminal listado não reabre. | `Nimbus.md` separa as seções | Keel: `57 passed in 9.12s`, exit 0. Nimbus: `57 passed in 9.65 s` | leitura de host. Sem VM alterada, sem reinício do Canvas e sem recibo |
| Quartz | 13 e 16 | Aceita na barra de corte. Terminal listado não reabre. | `Quartz.md` separa as seções | Keel: `20 passed in 5.13s`, exit 0. Quartz: `20 passed in 4.51s`, exit 0 | nenhuma. Sem decisão real até recibo central |
| Sable | 14 e 17 | Aceita na barra de corte. Terminal listado não reabre. | `Sable.md` separa as seções | Keel: `12 passed in 5.27s`, exit 0. Sable: `12 passed in 4.12s` | sondas de ausência. Sem conector, rede, visão, Operation ou QuickJS |
| Wren | 15 e 18 | Aceita na barra de corte. Terminal listado não reabre. | `Wren.md` separa as seções | Keel: `7 passed in 7.37s`, exit 0. Wren: `7 passed in 7.81s` | nenhuma. Sem duas máquinas, VPN real, confirmação humana, Canvas na interface ou execução remota |

A leitura das 23:58, em que os cinco apareciam em turno, está superada. Pytest passado não homologa o produto. Nenhuma ordem de implementação foi reenviada.

## Arquivos exclusivos

- Lumen: `sentra_canvas/desktop_ui/`, `installer/windows/`, recorte de ícone, atalho, instância única e arranque em `sentra_electron/`, `docs/frentes-18/Lumen.md`. Só Lumen roda `npm run build` do `desktop_ui`. Não muda o protocolo Python do shell.
- Nimbus: `memory/`, `orchestrator/memory.py`, `program_memory.py`, `budgets.py`, `resources.py`, `compute_policy.py`, `rate_governor.py`, `sentra_executors/vm_resources.py` (novo), `tests/unit/frentes/nimbus/`, `docs/frentes-18/Nimbus.md`. Não edita `virtualbox_*.py`.
- Quartz: `sentra_quality/`, `orchestrator/observability.py`, `orchestrator/quality_gate.py`, `tests/unit/frentes/quartz/`, `docs/frentes-18/Quartz.md`, `docs/frentes-18/comercial/`. Sem paywall e sem bloquear o uso local.
- Sable: `skills/`, `sentra_code_mode/`, `local_model/`, `sentra_marketplace/` (novo), `tests/unit/frentes/sable/`, `docs/frentes-18/Sable.md`. Plugin não concede Grant a si mesmo. Deny-only não fecha a frente 14.
- Wren: `sentra_collab/`, `sentra_remote/`, `sentra_federation/` (novo), `tests/unit/frentes/wren/`, `docs/frentes-18/Wren.md`. VPN não é autorização. Sem expor SQLite, endpoint local bruto ou porta pública. Sem segundo Control Plane.
- Keel: somente este arquivo.

Conflito de arquivo: o par para e Keel avisa Grok high. Diff de outro agente não é sobrescrito.

## Separação exigida no dossiê de cada par

Cada `docs/frentes-18/<Nome>.md` precisa de duas seções que não se misturam:

- Prova física contemporânea: o que foi exercido de verdade nesta rodada (interface aberta, fluxo clicado, processo medido, pareamento, recibo). Comando ou caminho da evidência, horário e o que o resultado não prova.
- Teste unitário executado agora: comando exato, contagem passed/failed e o arquivo de teste. Se o comando não rodou nesta rodada, a linha fica como não executado.

O que não está homologado fica numa terceira lista. Ausência de prova física não vira homologação por teste unitário.

## Comunicação

Marcos dos pares chegam só a Keel: arquivos, comando de teste, resultado e o que ainda não está homologado.
Keel fala com Grok high em bloqueio, conflito de arquivo, pedido de prova destrutiva, ou quando um par fecha.
Proibido nesta rodada: commit, push, reset, clean, rebase, checkout; apagar VM, VDI, Dot, conversa, `.sentra` ou `.oma`; suite inteira; reiniciar relay, backend, Edge ou VM sem o orquestrador; tocar `Auxiliares`, `third_party`, `node_modules`, `dist`, `Isos`, `browser_profiles`.

## Ciclo 23:27 — o que o pytest não homologa

Sable, frentes 14 e 17, teve o pytest reexecutado nesta leitura (`12 passed in 5.27s`, exit 0). A leitura de 23:58 não a marca fechada: o terminal segue em turno. Não homologado: chamada real de conector; pacote de marketplace vindo da rede; inferência visual com pesos e bytes de saída; Operation central no estado do usuário; execução QuickJS.

Quartz, frentes 13 e 16, teve o pytest reexecutado nesta leitura (`20 passed in 5.13s`, exit 0). A leitura de 23:58 não a marca fechada: o terminal segue em turno. Não homologado: decisão de modelo até recibo central de Run, WorkItem, Operation e Grant. Sem homologação comercial. Sem paywall. Uso local não bloqueado. Grants não foram declarados enfraquecidos.

Nimbus, frentes 11 e 12, marco recebido e não fechado. Arquivos citados estão no checkout e `Nimbus.md` separa teste unitário de prova física. Keel não reexecutou o pytest deste par neste ciclo. Não homologado, pelo próprio dossiê: nenhuma VM registrada teve CPU, RAM ou execution cap alterados; metrics query real não rodou; Canvas 0 e terminal 0 na amostra; CPU percentual do host não foi medido; a memória sobreviveu como reabertura de objeto Python, não como reinício do Canvas; não há Run, WorkItem, Operation, Grant nem recibo de efeito real.

## Aceite do Grok high

Neste ciclo não houve `maestri ask`. Nenhum par está fechada, e não houve bloqueio, conflito de arquivo nem pedido de prova destrutiva.

## Ciclo 23:35

Nimbus, frentes 11 e 12, teve o pytest capturado (`57 passed in 9.12s`, exit 0). A leitura de 23:58 não a marca fechada: o terminal segue em turno. Não homologado: nenhuma VM registrada teve CPU, RAM ou execution cap alterados; metrics query real não rodou; Canvas 0 e terminal 0 na amostra; CPU percentual do host não foi medido; a memória sobreviveu como reabertura de objeto Python, não como reinício do Canvas; não há Run, WorkItem, Operation, Grant nem recibo de efeito real.

Wren, frentes 15 e 18, teve o pytest capturado (`7 passed in 7.37s`, exit 0). A leitura de 23:58 não a marca fechada: o terminal segue em turno. Não homologado: duas máquinas; VPN real; confirmação humana; Canvas na interface; execução remota. A delegação de teste deixa WorkItem `PENDING` e Operation `WAITING_EXTERNAL`, com `executed` falso. A queda foi simulada no mesmo host. Sem porta pública, sem SQLite exposto e sem segundo Control Plane. VPN não é autorização.

Lumen, frentes 8 e 9, não fechada nesta leitura. O primeiro corte já citava os testes do shell, do Electron e do instalador temporário. A releitura de 23:58 mantém o par em turno.

## Ciclo 23:40

Lumen continua em turno, à espera de resposta do primeiro corte. Não há mensagem de fechamento. `Lumen.md` segue o corte anterior: as seções de teste unitário, prova física e não homologado existem, e a interface descrita é o harness headless em `127.0.0.1:4178/src/qa/lumen-flow.html`, não o shell contra broker, Dot ou VM. Keel não reexecutou os comandos e não avisou o Grok high neste ciclo.

## Ciclo 23:49 — testes da Lumen

Os comandos da Lumen foram reexecutados. A leitura de 23:58 não marca o par como fechada: o terminal segue em turno.

Teste unitário, que não é prova física:

- `node --test` de `shell-navigation`, `shell-home-board`, `shell-canvas-state`, `shell-failure`, `shell-computer-status`, `shell-updates` e `shell-design-tokens`: 19 pass, 0 fail, `duration_ms 415.1509`, exit 0.
- `node --test sentra_electron/test/desktop-identity.test.cjs sentra_electron/test/policy.test.cjs sentra_electron/test/isolation.test.cjs`: 5 pass, 0 fail, `duration_ms 1870.8813`, exit 0. O teste de isolamento passou ao exigir `SENTRA_ELECTRON_ISOLATION_OK`. Não houve segunda instância.

Prova física deste ciclo:

- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File installer/windows/test-desktop-install.ps1` → `SENTRA_DESKTOP_INSTALL_OK installation_id=6bbbde7b-5658-4451-983e-71f3a109e32e`, exit 0. Árvore temporária. Não foi o Desktop real nem `-Launch`.
- `npm run build` em `sentra_canvas/desktop_ui` → Vite `built in 2.67s`, exit 0. `desktop.js` e `desktop.css` materializados contêm os textos da Home, das fases, das três atualizações, da operação incerta e do teclado.
- Interface no Edge headless, `http://127.0.0.1:4178/src/qa/lumen-flow.html`, fixture, não o broker. O que a página mostrou: `continue:canvas`, `dot:d2`, `space:s1`, `approval:c1`, busca `zzzz-sem-resultado` com "Nada neste trabalho corresponde à busca" e nenhum Dot recente, busca `Nara` deixando só o Dot Nara, `failure:consult resend=false`, `failure:dismiss`, `update:data reload=false install=false compile=false`, `update:code reload=true install=false compile=true`, `update:version apply=false`. Sete fases. `data-resend=false`. O log não contém `resend=true`. Aviso de versão: a troca fica no instalador e não atualiza dados nem recompila. Em 1280 px as três colunas mediram 418.656, 418.672 e 418.656 px. Em 390 px `window.innerWidth` foi 390 e a grade ficou numa faixa (`grid-template-columns: 400.266px`).

Não homologado: shell ao vivo contra broker, Dot ou VM; pausa, desligamento e teclado reais; segunda instância Electron e janela nativa; `SENTRA-DOT.ico` no pacote staged; instalador no Desktop real; a janela não lê `installation.json`; Smart UI não refeito; nenhuma operação UNCERTAIN reenviada.

## Decisão

Data: 2026-10-13. Autor: Grok high.

A vigília das 23:58 está superada. Grok high já aceitou as cinco duplas na barra de corte: Lumen 8+9, Nimbus 11+12, Quartz 13+16, Sable 14+17 e Wren 15+18. Terminal ainda listado não reabre a frente. Pytest não homologa o produto.

Fechamentos recebidos depois dessa leitura, sem pedido novo de código:

- Wren, frentes 15 e 18. Comando: `python -m pytest tests/unit/frentes/wren -q --tb=line`. Resultado informado: 7 passed in 7.81s, em dois Control Planes temporários no loopback `127.0.0.1`. Prova física: nenhuma. Não há duas máquinas, VPN real, confirmação humana, Canvas na interface nem comando executado no outro computador. A delegação admite WorkItem `PENDING` e Operation `WAITING_EXTERNAL`, `executed` false. Intent sem recibo fica `UNCERTAIN` e não é reenviado. Sem segundo Control Plane, sem SQLite no canal, sem porta pública. VPN não é autorização. As frentes 15 e 18 não estão homologadas.
- Sable, frentes 14 e 17. Comando: `python -B -m pytest tests/unit/frentes/sable/test_fronts_14_17.py -q --tb=short`. Resultado informado: 12 passed in 4.12s. A passagem do Keel foi `12 passed in 5.27s`, exit 0. Prova física só de leitura: `VISUAL_MODEL_NOT_OPTED_IN`, `MODEL_PACKAGE_ABSENT`, `CATALOG_ABSENT`, `CONNECTOR_PACKAGE_ABSENT`, `inference_homologated` false, sem rede. Não homologado: chamada real de conector, pacote vindo da rede, inferência visual com pesos e bytes, Operation central no estado do usuário, QuickJS no guest. Deny-only não fecha. Plugin não concede Grant. Conteúdo externo não substitui instrução superior. `UNCERTAIN` não foi reenviado.
- Quartz, frentes 13 e 16. Sem pedido de implementação nova. Comando: `python -B -m pytest -q tests/unit/frentes/quartz --tb=short`. Resultado informado: 20 passed in 4.51s, exit 0. A passagem do Keel foi `20 passed in 5.13s`, exit 0. Isso é teste unitário. Prova física: nenhuma. Nenhuma decisão de modelo real chegou a recibo central de Run, WorkItem, Operation e Grant. O ledger não emite Grant, não adquire lease e não despacha efeito. `UNCERTAIN` já registrado não foi reenviado. Não homologado: auditoria com inferência real, homologação comercial, paywall inexistente, uso local permanece aberto, Grants não foram enfraquecidos. O teste unitário não homologa o produto.
- Nimbus, frentes 11 e 12. Comando: `python -m pytest tests/unit/frentes/nimbus tests/unit/test_program_memory.py tests/unit/test_compute_policy.py tests/unit/test_budget_admission.py tests/unit/test_resource_registry.py tests/test_memory_and_cache.py tests/unit/test_closeout_invariants.py -q --tb=short`. Resultado informado: 57 passed in 9.65 s. A passagem do Keel foi `57 passed in 9.12s`, exit 0. Prova física só de leitura de host, sem `VBoxManage`: 31853 MB totais, 6559 MB livres, RAM 79 por cento, 12 CPUs, `cpu_percent` nulo, 10 processos classificados como VM, Canvas 0, terminal 0. Não homologado: cap, memória ou CPU de VM registrada; metrics query nas VMs Debian; RSS do Canvas e dos terminais; percentual instantâneo de CPU; reinício do Canvas; efeito com Run, WorkItem, Operation, Grant e recibo.

O aceite de corte não fecha 8, 9, 11, 12, 13, 14, 15, 16, 17 nem 18. A matriz da Codex mantém as 18 frentes abertas. A reabertura integral é a ordem vigente. Os cortes locais são aditivos.

O produto não está homologado.

## Lapidação

Data: 2026-10-13. Cortes locais são aditivos e não substituem o fim integral. Cliente descartável, função local e admissão de federação são lacunas de implementação, não restrições finais. Recusa permanente do executor real não implementa a aplicação autorizada. Efeito em recurso real só depois de conferir identidade, carga e autoridade. Efeito `UNCERTAIN` não é repetido. Latch guarda o instalador. Pebble guarda `shell-mascot.jsx` e os PNG de opendots. Quartz não edita `dot_tool_dispatch.py`.

## Reabertura integral

Ordem vigente do usuário e da Codex. Na leitura seguinte, os cinco já estavam no turno integral e não foram interrompidos. Nimbus liga memória e plano às sessões vivas e o limite à admissão central, sem mexer em VM real agora. Sable liga pacote e capability ao Control Plane, sem tratar selo de ausência como fechamento. Lumen compactava o contexto. Quartz e Wren pensavam a matriz. Os três Grok de design, crítica e interação ainda não estão no canvas.

Desenho dos três, sob a Lumen nas frentes 8 e 9: um escreve a composição visual do shell sem tomar o mascote nem os PNG; outro critica a distância entre a fixture e o shell contra broker, Dot e VM; o terceiro exercita clique, teclado, largura e recibo na superfície. A Codex os cria. Até lá, a Lumen não declara o lugar deles como feito.

Dependências: 8 espera Pebble e o shell vivo; 9 espera o Latch para o pacote instalável; 11 espera o Flint nas sessões vivas; 12 espera o executor do Marlin e não altera as três VMs registradas sem autoridade; 13 espera o despacho vivo do Flint; 15 e 18 esperam a UI da Lumen, e 18 também o pacote do Latch; 16 espera o percurso instalado. Conta, VPN e segunda máquina são bloqueios que a Codex audita, não ausência presumida.

## Evidência nova, sem homologação

Sable, 14 e 17, continuam abertas. Selo de ausência não fecha conector, skill, plugin, automação, marketplace nem visão. Pacote executado: `skills/optional_connectors/local_invoke.py`. O teste cita esse caminho, Grant do host, `grants_created` false, `closed_by_absence` false, e replay não reexecuta. Pacote ausente continua `PACKAGE_ABSENT`. Keel reexecutou `python -B -m pytest tests/unit/frentes/sable/test_fronts_14_17.py -q --tb=short`: `16 passed in 4.19s`, exit 0. Sable informou `16 passed in 5.27s`. Sem conta, catálogo instalado, pesos, QuickJS no guest, clique no shell ou Operation no `.sentra` do usuário. `github.com:443` acessível e `torch`, `onnxruntime` e `PIL` importáveis foram leitura. `diffusers`, `open_clip`, pesos e catálogo ausentes. Nenhum download e nenhum login.

Quartz, 13 e 16, continuam abertas. Auditoria independente, sem editar arquivo alheio. `gate_decision_observation`, `AuditSpanRecorder` e `bind_central_receipt` só aparecem em testes. `LocalUsePolicy` em produção só em `sentra_quality/__main__.py`. `QualityGate.evaluate` em `orchestrator/engine.py:1517` chama um advisory com padrão desligado e `authoritative` false. `install-next.ps1` copia canvas, federation, collab, remote, mcp, core, runtime, ícone e versão. Não copia `LICENSE`, `docs/frentes-18/comercial` nem `sentra_quality`. `federation_handshake.py` é copiado e o script sai sem executá-lo. Latch não estava no canvas. Nenhum desses caminhos sela o ledger no produto.

Nimbus, 11 e 12, continuam abertas e não homologadas. Nenhuma VM foi modificada e `VBoxManage` não foi chamado. `LiveDotSession` grava plano, contexto e sessão; um processo Python novo reabre o mesmo diretório; outro Dot não lê o registro. `attribute_processes` separa canvas, terminal e VM pelo UUID já presente na linha de comando. `admit_surface` liga a medição ao orçamento e devolve `executed` false. `prepare_authorized_change` exige Run, WorkItem, Operation, Grant, owner e `vm_id`, confere owner, UUID, estado e carga, e devolve recibo e rollback com `executed` false. `apply_plan` não chama o cliente. `prepare_authorized_change` não é importado pelo executor central. Keel reexecutou os cinco testes nomeados: `5 passed in 9.81s`, exit 0. Nimbus informou `5 passed in 16.41 s`. Sem prova física: cap, CPU e RAM de VM registrada não mudaram; o recibo não é um Grant emitido pelo Control Plane; o Canvas do usuário não foi reiniciado; a sonda ao vivo pode continuar sem atribuir o Electron do SENTRA ou o terminal se a linha de comando não couber no teto de 32 shells (`_SHELL_PROBE_CAP` em `orchestrator/resources.py`). A prova de produção ainda não existe.

Wren, 15 e 18, continuam abertas e não homologadas. A delegação de teste executa no Control Plane temporário: `federation.digest`, `start_work_item_execution`, Quality Gate, WorkItem `COMPLETED`, Operation `SUCCEEDED`, `effect_started` true e `result_sha256`. Reconciliar devolve o mesmo recibo e não executa de novo. O modelo `sentra_federation/network_view.py` tem `renderer` `lumen`, `physical_proof` false, e a Wren não desenha a janela. Keel reexecutou `python -B -m pytest tests/unit/frentes/wren -q --tb=line`: `7 passed in 14.06s`, exit 0. Wren informou `7 passed in 13.13s`, em dois processos no loopback `127.0.0.1`. Isso valida a integração e não homologa duas máquinas. Sem VPN real, confirmação humana, Canvas na interface e comando no outro computador.

- Lumen, 8 e 9, continua aberta e não homologada. O stage de `SENTRA-DOT.ico` com 3 passed não é ícone na barra nem Setup publicado. No checkout, `.shell-home-columns` usa `repeat(3, minmax(0, 1fr))` e, abaixo de 900 px, `minmax(0, 1fr)`. O painel `shell-dot-family.jsx` tem Pausar família, Retomar família e Pedir exclusão; a exclusão exige `confirm_name` e `EXCLUIR DOT`, exige recibo e status `deletion_blocked_pending_user_approval`, e para se o recibo indicar efeito físico. Keel subiu a mesma fixture em `http://127.0.0.1:4188/src/qa/lumen-flow.html`, sem reiniciar o Edge. Em 390 px `innerWidth` 390, uma faixa `390px`, colunas 390, sem estouro. Em 1280 px as faixas 418.656, 418.672 e 418.656, todas menores que a janela. O clique na fixture mostrou `Recibo dot-delete-request-qa. Status deletion_blocked_pending_user_approval`, `data-deleted` false. Continua sem shell vivo contra broker, Dot ou VM. Grok high recebeu a medida da porta 4188 e não a homologou. Não é ícone na barra nem Setup. A Nimbus não aplica cap nas três VMs registradas. Quartz e Wren continuam abertos. Efeito `UNCERTAIN` não foi reaberto.
- Nimbus, 11 e 12, não fechou. O ciclo de 9 passed foi recebido e não homologa. `apply_plan` com ordem completa continua `applied` false e não chama o cliente. Próximo corte passado em 2026-10-13: ordem ausente continua sem efeito; ordem completa num cliente descartável, que não é VM registrada do host, aplica nesse cliente e o teste prova a chamada. VM registrada continua sem `VBoxManage`. Não alterar CPU, RAM nem cap de VM real. Quando o teste novo passar, o recorte traz o comando e a linha que separa cliente descartável de VM registrada. Não homologado.
- Quartz, 13 e 16, continua aberta. `git diff` vazio porque `decision_receipt_audit.py`, `test_central_receipt.py` e `Quartz.md` ainda não estão rastreados. `bind_central_receipt` lê o recibo central já existente e confere Run, WorkItem, Operation e Grant. Não reserva intenção, não emite Grant, não renova lease e não despacha efeito. `UNCERTAIN` fica `uncertain` e `resend_allowed` false. Keel reexecutou `python -B -m pytest -q tests/unit/frentes/quartz --tb=short`: `23 passed in 10.56s`, exit 0. Quartz informou `23 passed in 8.55s`. Sem decisão de modelo real neste host. O teste usa Control Plane temporário. Não homologado. Sem paywall.
- Sable, 14 e 17, não fechou e não está homologada. `14 passed` entra. `connector_real` true numa função local não é conector externo. Rede, QuickJS e pesos não foram reabertos. Próximo corte, ainda sem rede: se existir pacote local em `skills/optional_connectors`, `invoke_connector` executa esse arquivo e o recibo aponta o caminho. Se o arquivo não existir, continua `PACKAGE_ABSENT` e `connector_real` false. `self_grant` continua sem Grant. Replay não reexecuta.
- Wren, 15 e 18, continua aberta. `assert_private_bind` só aceita loopback ou privado; rede documentada global não abre porta. `assert_destination` ainda disca `26.1.2.3` se `26.0.0.0/8` estiver documentada, sem autorizar. `delegate` recusa `installer/windows` ou `sentra-installer` antes de criar Run. `physical_proof` e `image_installer` ficam false. `installer/windows` não foi editado. Keel reexecutou `python -B -m pytest tests/unit/frentes/wren -q --tb=short`: `7 passed in 8.88s`, exit 0. Wren informou `7 passed in 8.86s`. Sem duas máquinas, VPN real, confirmação humana, Canvas na interface ou comando no outro computador. Não homologado.

## Contrato e baseline, sem homologação

Quartz, 13 e 16, seguem abertas. API `sentra_quality.production_audit.record_fleet_admission` lê Run, WorkItem, Operation e Grant existentes e devolve `authorizes_effect` false. Keel reexecutou `python -B -m pytest tests/unit/frentes/quartz/test_production_audit.py -q --tb=short`: `3 passed in 4.54s`, exit 0. Quartz informou `3 passed in 7.87s`. O checkout agora tem `seal_fleet_admission` em `sentra_runtime/dot_tool_dispatch.py:479`, chamado na linha 339. Quartz disse que não editou o dispatch. Isso ainda não é prova física. Defeito do Latch listado em `docs/frentes-18/comercial/PACOTE_LATCH.md`: `install-next.ps1` não copia licença, pasta comercial nem `sentra_quality`. Sem paywall. Latch não confirmou o pacote.

Lumen, 8 e 9, segue aberta. Baseline de Codex em `.tmp/codex-closure-20261013`: zero erro, zero overflow, broker pid 6836 porta 50282. Não há build novo nesta combinação. `desktop.js` atual: sha256 `7A5D7CAC530A9E5318C2B175CF665BE5E451396197A6304C5CA5D2852F7F1B4D`, 2035034 bytes. A baseline era `5f6958442d2f8f0da3ef0b8a10178c695f85b0acb2d7173f6a18688b83789bed`, 2021555 bytes. O próximo `npm run build` espera Orbe, Vitra e Cadencia. No shell, sem protocolo Python novo: Rede schema 1 com `physical_proof` falso; `installation.advance` com `confirm_launch` falso; marketplace opt-in só apresenta e não baixa; recibo na entrega quando o evento traz `receipt_id`; limite marcado como recomendação que não altera a VM. A porta 4188 não foi fechada por esta leitura. Não é ícone na barra nem Setup. Sem shell vivo contra broker, Dot ou VM. Correção da Vitra, não homologada: prova da Home em `.tmp/codex-closure-20261013-application` às 03:53, o mesmo sha256 do `desktop.js`, envelopes `ok:true`, sem erro JS, HTTP ou blocked, Dots nas três larguras e sem overflow. O 390 px das 03:45 foi carregamento transitório, não ausência de Dots. Defeito que permanece: leitura que falha vira aviso de envio não confirmado, esvazia a Home e o aviso se repete. Cards altos, `active` cru, hierarquia e chip quebrado em 768 e 390. Preview do mascote na porta 5173 passou no recorte e está fora do shell. Canvas e Computador sem PNG. Sem integração de Orbe e Cadencia no PNG. Dossiê `docs/frentes-18/design/vitra/BASELINE.md`. Nenhuma das 18 frentes está integralmente homologada.

Wren, leitura só de rede, sem conectar e sem Keel contactar o vizinho: Radmin VPN Up, `26.168.99.36`. Vizinho `26.52.38.19` unreachable, `26.0.0.1` stale. Protocolo em `docs/frentes-18/Wren.md`, "Prova real preparada, não executada". Sem porta pública, sem SQLite servido, sem segundo plano. VPN não é autorização.

## Contrato v2 e delegação de Dot

Quartz, contrato v2, não homologado e sem reabrir o corte. `record_fleet_admission` não sela e não conta como decisão de modelo. `record_runner_final_answer` sela só o final do runner com hash de entrada e saída, tool, modelo e o lease real da tabela `leases`. Integrado em `sentra_runtime/dot_tool_dispatch.py` como `runner_audit`. `central_effect_admission` não foi o ponto editado deste relato. O teste do Flint `tests/unit/frentes/flint/test_fronts_1_and_10.py:438` espera `central_receipt_reached` true na admissão e falha: `assert False is True`. Keel rodou `python -B -m pytest tests/unit/frentes/quartz/test_production_audit.py tests/unit/frentes/flint/test_fronts_1_and_10.py -q --tb=line`: `1 failed, 14 passed in 14.30s`, exit 1. Runner injetado não é decisão. Sem prova física. Quartz informou 8 passed em 35.97s nos testes de auditoria e no portão live do Flint. Esse número não inclui a falha capturada aqui.

Wren, delegação de Dot, não homologada. O remoto cria WorkItem com a tarefa e o projeto, grava artefato JSON e fica `IN_REVIEW` com Operation `WAITING_EXTERNAL`. A origem confere os bytes. `review` com `approved` fecha `COMPLETED` sem segundo artefato. Reconciliar `UNCERTAIN` não reexecuta. Call site para a Lumen, ainda sem chamada no shell: `PeerGatewaySurface.network(scope)` em `sentra_remote/peer_surface.py`. `renderer` `lumen`. Wren não editou `desktop_ui`. O pedido anterior à Lumen segue aberto e não foi reenviado. Keel reexecutou `python -B -m pytest tests/unit/frentes/wren -q --tb=line`: `7 passed in 14.69s`, exit 0. Wren informou `7 passed in 17.20s`, em dois processos no loopback. Isso não homologa duas máquinas. Radmin `26.168.99.36` segue prova preparada, sem contato. O caminho do artefato não depende dessa máquina. Sem porta pública, sem SQLite, sem segundo plano. VPN não é autorização.

Quartz, sessão do Dot só depois do recibo real. Não homologa e não é prova física. `remember_live_dot_if_sealed` ficou depois de `runner_audit` em `sentra_runtime/dot_tool_dispatch.py:409` e recebe `outcome["runner_audit"]`. Admissão e runner injetado não gravam a sessão. O teste `test_session_is_saved_only_after_the_central_receipt`, que falhava na linha 438, passou. Keel rodou esse teste com `tests/unit/frentes/quartz/test_production_audit.py`: `4 passed in 3.53s`, exit 0. Quartz informou o conjunto `10 passed in 26.59s`. O instalador Next agora exige `PRODUCT_VERSION` `1.0.0` e copia `LICENSE`, a pasta `docs/frentes-18/comercial` e `sentra_quality`, inclusive `decision_receipt_audit.py`. `closes_front_16` continua false. Sem decisão real de modelo e sem pacote instalado no Desktop.

## Auditoria 04:10

Leitura somente do arquivo `.tmp/codex-closure-20261013/authority-pre-restart.json`, capturado em 2026-10-13T04:10:08-0300. `restart_authorized` false. Fila `canvas_shell_queue`: 32 `running`. Estado central a conciliar: 167 `UNCERTAIN`, 2 `QUEUED`, 1 `RUNNING` de `process.start` antigo, 2 leases. Sem restart. Não repeti teste sem diff novo e não reduzi o objetivo ao corte. Estes são defeitos concretos, não barra nova de sucesso. Pylon corrige a segurança de falha padrão. O adapter da Sable com principal escolhido pelo renderer ou `package_dir` foi recusado para revisar. O adapter da Wren com efeitos, enable e convite sem Operation central foi recusado. A Lumen integra a direção do Orbe já entregue e a Cadencia depois do review. A matriz segue com as 18 frentes abertas. Nenhum par está homologado.

## Janela do broker

Leitura sem teste novo. Nimbus, Quartz, Sable e Wren estavam com o turno de código encerrado e o prompt livre. Não há falha de pytest pendente na tela de nenhum dos quatro. A pausa pedida é só para sonda nova e edição concorrente nos módulos deles. Sable respondeu "pausa de sonda recebida" às 4:34. A pausa da Wren voltou com o terminal em espera e sem a linha de recebimento na tela. A pausa da Nimbus voltou do mesmo modo: prompt livre, em espera, sem a linha de recebimento. A Lumen segue no design. `UNCERTAIN` não foi reenviado. O broker pid 6836 na porta 50282 continua o de 12/10 até a Codex atualizar.

## Release da Home

Publicação de candidato bloqueada enquanto a regressão da Home é corrigida. `npm run build` em `sentra_canvas/desktop_ui` executa `vite build && node scripts/materialize.mjs` e escreve nos assets compartilhados. O próximo build de UI é staged: binário Vite local, `node_modules/vite`, com `--outDir` em `.tmp`, sem materialize automático da versão ativa. Screenshot candidata com dados reais numerosos antes de promover. A Lumen faz o build. A Codex testa o candidato em leitura contra a API real. A Vitra revisa. A promoção é do mesmo conjunto JS, CSS, HTML e manifest já validado, com reload coordenado. Markup novo não entra com CSS incompleto. O objetivo integral continua. Esta é ordem de release, não corte de frente. A Lumen já estava com esse texto na tela às 4:41 e compactava o contexto; Keel não reenviou a ordem a ela. A Vitra respondeu às 4:43: publicação continua bloqueada. Não há PASS nem FAIL. `.tmp/desktop-candidate-home` não existe. Sem os PNG desse candidato, em 1440 e em 390, com dados reais numerosos, `docs/frentes-18/design/vitra/REGRESSAO-SERVIDA.md` segue aberta. A Vitra não gera build e não promove. A leitura, quando a captura existir, usa só três critérios: uma linha de falha em português, sem `message.uncertain` repetido, com o primeiro Dot visível; Atualizar em painel absoluto, com os três rótulos inteiros; trilho de 256 px no mesmo quadro da Home em 1440. A promoção, se houver, é do mesmo JS, CSS, HTML e manifest que a Codex tiver testado em somente leitura. Não homologado. A Codex preparou o teste isolado do candidato, em navegador privado e só com leitura da API real, nas larguras 1440, 768 e 390. Não é PASS e não é o shell da porta 50282. O turno parou com o modelo em capacidade, antes do resultado. A Lumen saiu da compactação e retomou a correção. A publicação continua bloqueada.

PASS estrito da Vitra, só da regressão da terceira iteração, em `.tmp/codex-candidate-home-review-20261013/20261013-053624/report.json`, capturado às 05:36. Doze PNG. Hashes do mesmo conjunto: `desktop.js` `63ff43258e4edfd959ab6c32610b9616a4ef0a37b0a0f67b1302536f46b17e01`, `desktop.css` `a56c83143c5a37c0ce902a80c9bf9b9696bf821daae7b4828be4a883980f66ee`, `desktop.html` e `index.html` `1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3`, `manifest.json` `f4251b3829b1c2bd55c0634726344a1590192efbaf6c19c909841c95d2afa13f`. Leitura da API real, `http_errors` e `blocked_requests` vazios, gap de 20 px em 768 e 390, Esc fecha o menu, movimento reduzido conferido. O relatório marca `published` false, `broker_restarted` false e `homologated` false. Não promove e não reinicia o pid 6836. Não é design pronto. Home, Canvas e Computador ainda pedem refinamento geral. As 18 frentes seguem abertas.

Pylon corrigiu o relato: fase nula sem marcador continua `UNCERTAIN`; `before_admission` só vale com prova explícita; o marcador depois fica persistido; 3 passed. Não reabrir nem recarregar por esse relato antigo.
