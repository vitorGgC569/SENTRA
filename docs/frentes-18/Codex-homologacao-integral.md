# Homologação integral — coordenação Codex — 2026-10-13

Objetivo do usuário: entregar todas as frentes corretamente implementadas, corrigidas, validadas, testadas e homologadas. O corte anterior não reduz esse objetivo. Estado inicial: **nenhuma das 18 frentes integralmente homologada**. Os dossiês registram testes e provas parciais; não são prova de fechamento.

## Autoridade e fluxo

Codex coordena e audita o fechamento final. Grok high revisa Flint, Marlin, Iris, Pylon, Pebble, Latch e Brook. Keel coordena Lumen, Nimbus, Quartz, Sable e Wren. Ambos reportam a Codex com requisito, diff, teste, evidência real e lacuna. Terminar a edição atual sem interrupção; depois continuar na lacuna integral. Não encerrar por aceite de corte ou por um conserto unitário isolado.

Preservar recursos e checkout compartilhado. Sem reset/clean/checkout/rebase/commit/push. Não sobrescrever arquivos em edição. Não repetir efeitos UNCERTAIN. Antes de tocar processo ativo, conferir identidade, operações, recibos e posse. Exclusão de dados reais do usuário exige confirmação específica; preparar o resultado concreto primeiro. Fixture pode validar integração, mas não homologar execução real no produto.

Cada frente fecha com: implementação conectada ao caminho de produção; teste relevante do comportamento final; prova pela superfície instalada com identidade da versão, ambiente, horários, logs e recibos; ausência de pendências do requisito. Indisponibilidade deve ser honesta e visível, mas não substitui uma capacidade exigida. Efeito exige Run, WorkItem, Operation, Grant e recibo; IDs declarados sem validação não autorizam. Uma execução no host não comprova execução no guest.

## Matriz dos 18 requisitos

| Nº | Responsável | Requisito de fechamento | Evidência inicial e lacuna | Estado |
| --- | --- | --- | --- | --- |
| 1 | Flint; Marlin e Brook integram | GPT-6 High coordena SENTRA CLI, OpenCode e Codex: três inferências, recibos, WorkItems reconciliados, revisão e resposta consolidada; processos e artefatos no guest | Testes de portão com runner injetado; prova antiga de dois filhos no host. Faltam trio real, guest e fechamento conectado ao coordenador | ABERTA |
| 2 | Marlin; Lumen liga interface | Criar Dot pela UI, reservar recursos, instalar Debian, usuário e desktop; Windows utilizável com licença declarada corretamente | installation.advance exposto na ponte; testes com cliente falso; Debian anterior parcial. Faltam botão, fluxo limpo e Windows real | ABERTA |
| 3 | Marlin; Lumen liga seletor | Selecionar pasta Windows, cópia filtrada, hash, extração e leitura no guest, recibo SUCCEEDED | Dispatch falso e snapshot local. Falta importação nova autorizada no guest; preservar operação incerta antiga | ABERTA |
| 4 | Iris; Marlin integra guest | Captura, localização, mouse, teclado, leitura pós-ação em tarefa gráfica na VM; posse única do input e isolamento familiar | Janela Win32 própria não é VM. Worker convidado ainda em correção; precisa caminho de produção e execução real no guest | ABERTA |
| 5 | Pylon; Lumen liga UI | Pausar, retomar, arquivar, restaurar e retirar família, conversas remotas e recursos sem órfãos, com recibos e confirmação | Ponte temporária pausa/retoma; pedido bloqueia exclusão. Arquivamento remoto ausente e retirada física não homologada | ABERTA |
| 6 | Iris; Lumen verifica Canvas | ChatGPT Web → extensão → relay → bytes armazenados → imagem no Canvas, MIME, tamanho e SHA-256 | Guard separado do worker; fixtures passam. Faltam ligação no coletor instalado e binário real. UNCERTAIN_NO_RESEND preservado | ABERTA |
| 7 | Pylon; Quartz audita | Crash, fechamento, queda do relay e reboot preservam conversas, leases e permissões; consulta/reconciliação sem segundo efeito, pela UI instalada | Plano observacional e testes temporários. Falta ligar recuperação na ponte e exercer incidentes reais em ambiente controlado | ABERTA |
| 8 | Lumen; Pebble animações | Home, navegação, sete estados, computador, recibos, falhas, Smart UI e acessibilidade úteis no shell real e responsivo | Harness fixture; overflow a 390 px observado. Faltam shell com broker/Dot/VM e evidência de ações e retorno da Smart UI | ABERTA |
| 9 | Lumen; Latch installer | Instalação limpa, dependências, ícone/atalho/taskbar, instância única, janela, atualização de versão com preservação/rollback; pacote instalável | Instalador temporário com executável fictício; stage de ícone. Faltam runtime completo instalado, segundo lançamento, atualização real e máquina limpa | ABERTA |
| 10 | Flint | Admissão comum de provedores/CLIs, autenticação, modelos/esforço, disponibilidade e fallback explícito; Antigravity só com contrato verificado | Catálogo/portão; Antigravity gráfico não é inferência. Faltam auth/cotas reais e conexão de todos os caminhos relevantes | ABERTA |
| 11 | Nimbus; Flint conecta sessões | Memória, planos e contexto por owner/Dot/projeto sobrevivem a reinício do processo do produto, não vazam entre Dots e suportam handoff | Segundo objeto Python reabre SQLite. Falta conexão às sessões vivas, restart de processo e isolamento pelo produto | ABERTA |
| 12 | Nimbus; Marlin executor | Medir Canvas/terminais/VMs; admissão/limites de CPU/RAM/disco/VMs efetivos e autorizados; reserva e suspensão/retomada sem travar host | Amostra host: CPU nula, Canvas/terminal zero; apply_plan sempre recusa. Faltam medição atribuída, aplicação central e VM real | ABERTA |
| 13 | Quartz; todos fornecem recibos | Auditoria decisão → autorização → execução → resultado/revisão, logs sanitizados, testes adversariais de isolamento/injeção/idempotência | Testes de ledger e recibo temporário. Falta decisão real até recibo e auditoria do caminho completo | ABERTA |
| 14 | Sable | Conector, skill, plugin e automação opcionais com execução autorizada, recibo e falha explícita; sem self-Grant; conteúdo externo é dado | Sondas de ausência e deny-only. Faltam invocação útil de pacote real, automação e integração na superfície | ABERTA |
| 15 | Wren; Lumen liga UI | Contas/equipes e sincronização com escopo de projeto, convite, revogação e privacidade sob Control Plane único local | APIs e testes temporários. Falta integração visível e uso real com escopos distintos | ABERTA |
| 16 | Quartz | Licença, documentação de instalação/uso, diagnóstico sanitizado, suporte e critérios de distribuição; uso local permanece livre | Documentação/política existentes; falta demonstrar percurso instalado e consistência do pacote/licenças/suporte | ABERTA |
| 17 | Sable | Marketplace opt-in com pacote fixado/verificado, catálogo útil e modelo visual local com pesos e saída real; ausência explícita | Pacotes/runtime ausentes; inference_homologated false. Falta execução opt-in útil e recibos | ABERTA |
| 18 | Wren; Latch pacote; Lumen UI | Dois SENTRAs identificados/pareados, mTLS, conversa com recibo/revogação, Canvas compartilhado, delegação realmente executada e reconciliação sem duplicar | Loopback em testes, execução remota false, PENDING/WAITING_EXTERNAL. Faltam executor remoto, UI e prova em duas máquinas/VPN | ABERTA |

## Caminho de aceitação integrado

Instalar e abrir pelo ícone → criar Dot coordenador com Debian → selecionar/importar projeto → solicitar mudança com plano/código/testes → observar três CLIs executarem no guest → conferir recibos e falhas → consolidar artefatos/alterações para revisão → interromper/reabrir sem perda/duplicação → arquivar/restaurar/retirar recursos QA com confirmação específica. Repetir na instalação Windows limpa e com falhas controladas. Gates independentes: imagens nativas, Computer Use, Windows guest, memória/recursos, skills/marketplace/visão e federação.

## Evidência e próxima ação

Fontes: notas sentra-diagnostico-de-maturi (596 linhas) e frentes-18-coord (65 linhas), ambas integralmente lidas; docs/SENTRA_STATUS_VERIFICADO_2026-10-12.md; docs/SENTRA_RELATORIO_INTEGRADO_FRENTES_2026-10-12.md; todos os dossiês em docs/frentes-18. Estado dos terminais consultado em 13/10/2026: agentes ativos com consertos parciais; nenhuma tarefa foi reiniciada.

Relato contemporâneo de Grok confirma as lacunas. Não parar toda a implementação por testes físicos ainda dependentes de conta/segunda máquina/aprovação: concluir e testar a integração que independe disso, levantar recursos atuais sem efeito e preparar a prova concreta. Conta externa, VPN e segunda máquina são dependências a verificar, não indisponibilidades presumidas.

Próxima ação: cada par terminar o conserto ativo, mapear suas lacunas ao caminho de produção e implementar até os requisitos acima; coordenadores arbitram arquivos compartilhados. Codex verifica evidência e versão antes de liberar fechamento.

## Reforço visual solicitado pelo usuário

Em 13/10/2026 o usuário pediu melhoria visual pesada, interação e animações; autorizou mais três terminais Grok. Criados e conectados: Orbe (direção visual e composições concretas), Vitra (crítica visual independente e QA do produto), Cadencia (componentes de interação e movimento). Preset Grok high confirmado pelo CLI. Os três estão conectados a Lumen, Pebble, entre si e às notas. Lumen integra nos arquivos existentes e mantém build exclusivo; Pebble conserva propriedade de mascot/dot-motion/SVG e PNG originais. Orbe possui docs/frentes-18/design/orbe/, Vitra docs/frentes-18/design/vitra/, Cadencia novos src/experience/cadencia/ e test/experience-cadencia/. Critério: transformação visual substancial integrada ao shell real, com captura antes/depois, responsividade, foco/teclado e reduced-motion; relatório ou fixture isolado não fecha.

## Evidência independente de produção — 13/10/2026 03:45 BRT

Script somente observacional: .tmp/codex_production_baseline_20261013.py. Relatório .tmp/codex-closure-20261013/baseline.json; screenshots production-home-1440.png, production-home-768.png, production-home-390.png. Abriu um contexto Edge headless isolado por viewport, sem enviar mensagens, reiniciar broker/Edge existente ou mutar dados. Guard permitiu somente bridge de leitura; a captura final teve zero mutações bloqueadas, zero erros JS e zero respostas HTTP de erro.

Broker efetivo confirmado: PID 6836, porta 50282, runtime cd86d23b412f46be948bfbe0c12ec197. Três workspaces; 12 terminais, nenhum com status running, 15 agentes. Isso não comprova ausência de operações em voo; qualquer intervenção precisa ainda consultar Operations/relay/leases.

Assets efetivamente servidos coincidem com o checkout: desktop.js 2021555 bytes SHA-256 5f6958442d2f8f0da3ef0b8a10178c695f85b0acb2d7173f6a18688b83789bed; desktop.css 112039 bytes SHA-256 2adabddc5ccade371c957318e94fed2984371c9e36dee77410a5473282eb1b7d. A Home real tem scrollWidth igual a innerWidth em 1440/768/390. Colunas mediram 338.656/338.672/338.656 px em 1440, 464 px em 768, 350 px em 390. No mobile com boot fresco o sidebar inicia fechado. Captura anterior com resize preservou drawer aberto e guard bloqueou code_discovery, gerando aviso artificial; foi substituída por esta captura corrigida. Não tratar aquele aviso como defeito do produto.

Limite: comprova renderização da Home real nessa versão; não comprova Computer Use/VM, ações de ciclo de vida, instalação, transformação visual final nem toda a frente 8.

## Dependências verificadas

Codex login status: Logged in using ChatGPT. OpenCode auth list: No authenticated integrations; falta confirmar se o modelo free selecionado necessita autenticação antes de declarar bloqueio de inferência. VBoxManage showvminfo da VM fcd974cf-ccdc-5636-b7af-2f96024d5dde: running, RAM 4096MB, 2CPU, cap100, Guest Additions 7.2.20. Recibo 07-verify-guest.json: installed_guest_verified, installed_disk, /dev/sda1, desktop_ready_verified true. Marlin confirmou UUID do system.vdi 9cf5e721-7cbd-48e9-9634-d2d709c9cb68, ISO ejetada. Próxima prova é installation.verify contemporâneo via vm:guest e credencial já protegida; não reinstalar nem reenviar intento antigo.

Wren verificou somente leitura: Radmin VPN Up no host 26.168.99.36, vizinho 26.52.38.19 unreachable e 26.0.0.1 stale. Prova de duas máquinas ainda não executada; nenhuma conexão remota foi feita. Código de integração passou a executar federation.digest em Control Plane temporário com hash de resultado e reconciliar sem segundo efeito. Isso é progresso de integração, não delegação de agente remota integral nem homologação de VPN.

## Correções de integração em andamento

Flint conectou retenção/revisão de resposta a shell_runtime._publish_answer e shell_actor.compose; dados artificiais coordinator_text são not_inference. Ainda sem trio real/guest/Antigravity. Nimbus criou sessão persistente entre processos e preparação de mudança autorizada, mas sem call site produtivo nem aplicação; Nimbus/Flint/Marlin foram conectados para fechar esses dois caminhos. Quartz identificou ledger só de testes e pacote sem LICENSE/comercial/sentra_quality; criou production_audit.record_fleet_admission e contrato, com integração ao Flint/Latch pendente. Sable executou pacote local no teste, runtime visual/pesos/catálogo ainda ausentes e caminho de produto pendente. Latch provou HTTP de cópia independente do checkout, mas Python/pywebview/WebView2 e dependências continuam do host; pedido de pacote instalável independente reforçado. Brook ligou entradas main/repl/slash/Maestri; prova real e integração visual ainda pendentes.

Todas as frentes continuam ABERTAS. Estes marcos não reduzem a barra final.

## Incidentes e descobertas posteriores

Marlin encontrou identidade/Grant vm:guest do Dot Testando Advanced no projeto 1dccb4d7e53946f9b6f5743733a37433. Duas tentativas novas de installation.verify via ponte foram observadas como incertas pelo cliente, chaves verify-marlin-20261013-7cfe83ca1f0a e verify-marlin-20261013b-d7f07c43634e. Codex pediu consulta exclusiva das Operations/handles originais e diagnóstico sanitizado; nenhuma terceira chave/reenvio. Timeout HTTP não prova término. Importação continua aguardando verificação contemporânea SUCCEEDED.

Iris capturou framebuffer real da VM Debian 1280x800 com greeter e sessão ainda bloqueada; isso não é tarefa gráfica executada. Coletor de imagem instalado online e hash preservado, sem workers_online e sem ativos finalizados; job anterior may_have_sent=1 continua sem reenvio. Próxima prova de imagem exige lease próprio de aba apta, admissão e bytes, sem afetar a operação incerta.

Codex revisou production_audit.py: observação de admissão determinística não comprova decisão de modelo; IDs de lease derivados artificialmente do fence não comprovam lease real. Quartz recebeu correção de contrato para usar observações/identidades reais. Wren recebeu pedido para completar delegação de tarefa/Dot/artefato além do digest de teste e ligar network_surface à UI. Brook/Flint/Lumen/Cadencia e Sable/Flint foram conectados para fechar call sites.

## Segunda captura: confirmação dos envelopes de aplicação

Relatório .tmp/codex-closure-20261013-application/baseline.json, captura 03:53 BRT, mesmo broker 6836/50282, script codex_production_application_20261013.py. Além de HTTP/JS, conferiu ok:true nos envelopes bridge de home, dot_list, space_get, conversation_list, events, document_list, dot_preferences_get, coordinator_approval_list e code_discovery, no projeto 1dccb4d7e53946f9b6f5743733a37433. Todos sem error; mutações bloqueadas zero. Contextos próprios e fresh por viewport, sem inferência/efeito. Asset desktop.js SHA-256 7a5d7cac530a9e5318c2b175cf665be5e451396197a6304c5ca5d2852f7f1b4d, 2035034 bytes, igual ao checkout; CSS SHA-256 3065bda68ca82389a56128b3f76f358b4f0e51ca523da19b9a9a066831db8d4e, 112951 bytes. ScrollWidth=innerWidth em 1440/768/390. O payload home real ainda não oferece network nem optional_surfaces: essa integração backend continua faltando. Captura não prova as funcionalidades ausentes. Os screenshots da primeira captura de 390 mostraram mensagem transitória de envio não confirmado durante carregamento; a segunda captura registrou envelopes de aplicação para distinguir renderização de resposta confirmada. Vitra avalia essa transição.

## Arbitragem de integração backend e qualidade da UI

O usuário rejeitou o design servido como extremamente simples e malfeito. Codex exigiu recomposição substancial da Home/Canvas/Computador e remoção de textos internos de homologação/checkout/loopback/Grants da superfície de produto; os metadados permanecem no dossiê/diagnóstico. UI deve oferecer informações e ações úteis com dados honestos, sem fixtures promocionais.

Codex reserva sentra_canvas/service.py para registrar adapters e enriquecer home. Wren recebeu ownership ampliado do novo sentra_canvas/shell_federation.py: NETWORK_ACTIONS/NETWORK_READS, dispatch_network(canvas,project_id,action,params,request_key=None), home_network(canvas,project_id). Sable recebeu ownership ampliado do novo sentra_canvas/shell_capabilities.py: CAPABILITY_ACTIONS/CAPABILITY_READS, dispatch_capability(...), home_capabilities(...). Ambos devem usar o Control Plane único do runtime, owner/escopo derivados no host, leituras sem efeito e mutations com autoridade central, diário e recibos; nenhuma edição concorrente em service.py. Lumen renderiza e liga ações conforme os contratos. Assim a integração pendente tem responsáveis e call sites concretos, além de documentação.

Cadencia entregou os módulos novos e 8 testes; import no shell ainda pendente. Seu feedMotion agora consome snapshots acumulados, superando o defeito de dedup por sufixo da versão antiga. Vitra continua a crítica da captura com versão delimitada. Quartz corrigiu a regressão de sessão: admissão/fallback/injection não salvam como decisão de modelo; runner audit real precede persistência. Testes relatados posteriores passaram, prova física ainda pendente.

## Causalidade das duas verificações e preparação de atualização do processo

Marlin confirmou as duas chaves sem Operation/lease/fence/worker/effect-lock e sem VBoxManage vivo. O diário ShellHostRequests.invoke grava uncertain no except BaseException após claimed e antes da reserva central, sem persistir causa. A primeira falha demorou 96.981s e a segunda 1.017s. PID6836 iniciou em 12/10 15:58:47; módulos VM foram editados em13/10 e não estão carregados nesse processo. Nenhum restart foi realizado. As duas linhas incertas continuam preservadas, sem protected_result e sem replay; ausência de worker não é recibo de sucesso.

Pylon recebeu ownership ampliado de sentra_canvas/shell_requests.py para diagnósticos duráveis sanitizados e fase de admissão, sem exception/stdout/credenciais crus nem reexecução. Codex prepara auditoria read-only de filas/Operations/leases antes de atualizar o mesmo broker, depois de estabilizar os módulos em edição. O processo antigo não será usado para atribuir homologação ao código novo.

Os relatos posteriores Flint/Quartz afirmam que persistência de sessão exige evidence_source=native_process, live_model_verified e audit real selado, enquanto fallback/admissão/injection não selam. As regressões pertinentes relatadas passaram; nenhuma inferência física foi realizada nesta rodada. Todas18 permanecem abertas.

## Revisão de código dos adapters e protótipo

Root encontrou defects bloqueantes antes de reload: ShellHostRequests sem marcador de efeito não pode presumir falha anterior à admissão; callbacks legados podem ter feito efeito. Pylon recebeu requisito de unknown=>UNCERTAIN e fase/Operation persistidas. Sable adapter aceita identidade/package_dir do renderer (incompatível com shell_bridge e potencial import de caminho arbitrário); deve derivar identidade/WorkItem no host, registry pinado e tratar conta não observada como unverified. Wren adapter enable/invite ainda não mostrou intenção/Operation/fence central; deve completar esse ciclo, concorrência e restauração da instalação. APIs de mutation não estão aprovadas para prova real até correção.

Orbe entregou index.html e spec-lumen.md. Root renderizou três superfícies em 1440/390 em .tmp/codex-orbe-review-20261013/report.json, zero erro JS/overflow, protótipo somente. Direção ainda não aprovada: parece wireframe, ruído de grade/contornos e anotações de QA na superfície; pedido de aprofundamento substantivo. Tradução active=>Trabalhando foi recusada: ciclo de vida ativo não prova execução atual. Trabalhando exige evidência de tarefa/Operation, sem inferir de Run aberto.

Auditoria readonly authority-pre-restart.json revelou 32 linhas shell_queue running, 167 Operations UNCERTAIN, duas QUEUED, uma RUNNING antiga process.start e duas leases. O cruzamento com handles/estado central ainda está pendente; esse relatório não autoriza restart nem alteração de estados.

## Rotas de produto integradas por Codex

sentra_canvas/service.py registra NETWORK_ACTIONS/NETWORK_READS via dispatch_network e CAPABILITY_ACTIONS/CAPABILITY_READS via dispatch_capability. Home confirmada agrega home_network e home_capabilities. Falha de consulta opcional preserva os dados confirmados e retorna query_failed/effect_uncertain:false com código sanitizado, sem mensagem crua de exceção. Teste tests/unit/frentes/codex/test_shell_surface_integration.py: 4 passed in5.11s, estado temporário real Canvas/ControlPlane, cobrindo reads sem habilitar/Grants novos, rejeição de identidade/caminho renderer, preservação/sanitização de Home e projeto fora do escopo. git diff --check do serviço sem erro. Isto conecta o código; o broker6836 antigo ainda não carregou as rotas e não é homologação física.

Pylon reportou correção do default: fase desconhecida continuaUNCERTAIN, before_admission só com marca explícita; fase eoperation persistidas. Sable reportou contrato v2 com identidade/WorkItem derivados host e pacote por registry aprovado, conta unverified. Wren reportou effects com WorkItem/Operation/lease/diário, disable/revoke e instalação persistente, 8 testes de integração loopback; prova remota continua pendente.

## Cruzamento da autoridade e baseline adicional

authority-cross-reconcile.json 04:20 BRT: todas32 linhas shell_queue running correspondem a Operations centraisUNCERTAIN. Duasleases já expiradas, preservadas. A única OperationRUNNING antiga process.start aponta PID24148, ausente no snapshot atual; duas QUEUED antigas são validation_probe/postrefresh.validation sem handles. Filho do broker6836 apenas conhost56168; VBoxManage vivo nenhum. Isso muda o plano de atualização, mas não apaga estado nem autoriza replay; restart aguarda estabilização e verificação final do mesmo processo/autoridade.

Baseline adicional .tmp/codex-closure-20261013-canvas-computer/baseline.json e PNGs Canvas/Computador: abriu Dot/conversa EXISTENTES com bridge guard de leituras, semnewConversation/efeito. Zero errosJS/HTTP e zero mutações bloqueadas; bundle na captura e9d3f16230f5ad4d71571a617cbf1dd15752e54da7f2d942cb14f36e4b867f65,2043655bytes. Cada PNG precisa inspeção de conteúdo; nomes home subsequentes podem refletir navegação preservada, não prova deHome. Canvas apresenta sete legendas extensas acima do grafo; Computador no quadro inicial mostra estado não confirmado como não criado/VirtualBox indisponível. Designers receberam estas capturas para tratar loading/semântica e composição. Nenhum botão de energia/input/exclusão foi pressionado.


## Regressão servida e candidato isolado

Os screenshots do usuário mostram despejo de eventos message.uncertain na Home e menu Atualizar no fluxo da cápsula. Publicação bloqueada até correção e revisão independente de docs/frentes-18/design/vitra/REGRESSAO-SERVIDA.md. Lumen mantém ownership da apresentação e do build staged em .tmp/desktop-candidate-home. Não executar npm run build/materialize, copiar para static nem reiniciar PID 6836 nesta etapa. As 32 intenções UNCERTAIN permanecem sem replay.

Codex preparou .tmp/codex_candidate_home_review_20261013.py: captura bytes imutáveis do candidato, confere hashes do manifest, substitui HTML/assets apenas num contexto privado de Playwright e permite somente leituras da API real existente. Registra dependências estáticas preservadas, contagem de eventos recebidos, PNGs Home/menu em 1440/768/390 e reduced-motion, erros e requests bloqueados. Nunca promove nem reinicia. Primeiro resultado CANDIDATE_MISSING, antes de qualquer consulta ao broker; isso não é PASS/FAIL visual. Vitra revisará os PNGs do mesmo conjunto depois da captura.

Integração de routes/home em service.py: conjunto Codex + Wren shell_federation + Sable shell_capabilities + Pylon shell_host_requests deu 10 passed in 17.19s. Resultado temporário; Python novo ainda não carregado pelo broker e nenhuma frente homologada.


## Captura isolada do segundo candidato: regressão ainda FAIL

Codex capturou candidato completo em .tmp/desktop-candidate-home contra API real do broker 6836, sem publicar/reiniciar/replay. Segunda captura limpa 05:17: JS c3491db59e0a40e7fb0945733ba678ecfc0b1e4017833ac1da97c5857bda63bf (2054866 bytes), CSS 838fbd77a665c9f6dcf9c7a292d880c66102aa942282fa566abb291e8125c2a5, HTML 1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3, manifest fc1a7738b8d9e537639fc53ace9c66aec48f23f7f156208aaddb8db2093bf6f9. Home real devolveu 45 eventos uncertain entre 50 itens de atividade, 6 Dots e 42 conversas. Isso não é a contagem de 32 Operations no journal.

Sem erro JS/HTTP/chamada bloqueada na segunda captura; Dots visíveis, menu absoluto sem deslocar topbar, Esc fecha, zero animações com reduced-motion. Codex e Vitra acharam colisão visual Home/Em andamento em768 que scrollWidth não detectava. Vitra declarou FAIL desta regressão; release continua bloqueado, Lumen prepara nova iteração staged. Nenhuma frente homologada.

Primeira captura tinha guard excessivo para machine_list/output de terminais ocultos e toast artificial, preservada apenas em report-guard-incomplete.json; seus PNGs de nomes iguais foram sobrescritos pela captura limpa. Não usar o report antigo para afirmar os pixels atuais. Output de terminal continua proibido no teste readonly: seu handler pode reconciliar receipts; candidato novo suspende polling na Home. Uma tentativa intermediária teve ECONNREFUSED transitório, com PID/listener verificados vivos depois; nenhum restart.

O harness agora grava cada nova captura em subpasta por timestamp e mantém report.json como índice da última, para evitar confusão entre versões. Acrescenta colisão dos rótulos e abertura/recolhimento de grupos por teclado com paginação, além dos PNGs e hashes. Refinamento visual geral, Canvas/Computador e homologação integral seguem pendentes.


## PASS estrito da regressão, sem publicação

Terceira captura imutável: .tmp/codex-candidate-home-review-20261013/20261013-053624/report.json e 12 PNG. JS 63ff43258e4edfd959ab6c32610b9616a4ef0a37b0a0f67b1302536f46b17e01; CSS a56c83143c5a37c0ce902a80c9bf9b9696bf821daae7b4828be4a883980f66ee; HTML 1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3; manifest f4251b3829b1c2bd55c0634726344a1590192efbaf6c19c909841c95d2afa13f. API real, mesmos bytes durante leitura, zero erros JS/HTTP/requests bloqueados. Em768 e390 há20px entre Home e Em andamento, rótulos inteiros; menu absoluto, Esc fecha; grupos recolhidos, Enter abre/recolhe, reduced sem animações. Vitra leu esses12PNG e deu PASS somente desta regressão.

Snapshot exato preservado em .tmp/desktop-candidate-home-reviewed-20261013-053624, com review-receipt.json. Nada copiado para static, nenhum broker/VM/Edge do usuário reiniciado, nenhum UNCERTAIN reenviado. Ordem atual continua não publicar. Não é design pronto nem homologação; todas18frentes ABERTAS. O refinamento de hierarquia, busca, ação Abrir, affordance dos grupos, estados/conversas repetidos, Canvas/Computador permanece pendente.

Pylon confirmou contrato atual: fase sem marcador é null no banco, status uncertain/effect_uncertain true, sem retry/replay. before_admission exige nota/prova explícita; after_possible_effect e operation_id são persistidos. O relato anterior que inferia ausência de efeito foi revogado. Nenhuma correção em massa nem reload ocorreu.


## Refinamento incremental e falha de foco

Captura readonly do refinamento: .tmp/codex-candidate-home-review-20261013/20261013-055848/report.json e12PNG, JS9b012ef1b1531dfc9c878b34448b9b489f8a523a9c6bb83eb5e1df6c38d6033a, CSS08270e81d6d036ea82d38ab9bbbafaccfc541662c63ef8579236f87de06f7320, HTML1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3, manifesta5393ae8c4987d6f7f16b8bda3a52ac3a0f730b6c1ae10dd2f6f2d1fb8cda2d7. APIreal6836, zeroerros/bloqueios/alteração debytes. Busca larga, Abrir o Space e chevron melhoraram; Orbe/Vitra consideram incremental e não fecham redesign. DossiêVitra REFINAMENTO-HOME.md.

Probe adicional por preocupação de foco não exercido: .tmp/codex-candidate-home-review-20261013/20261013-060755/report.json e24PNG dos mesmosbytes9b012ef1. Tab chega a busca,CTA,Dot; buscaSentraAqrt filtraum e limparrestauraseis. Nenhum Space/Dot acionado. Zero JS/HTTP/requests bloqueados. Codex eVitra confirmaram defeito: outline3px branco offset2 na linhaDot é clipado por overflowhidden dafolha; só base aparece nas quatrovistas. Busca/CTA têm outline3px cinza176 visível. Não é PASS dofoco nemdesign.

Lumen recebeu etapa de composição com contexto real porDot, agrupamento de conversas por título+dot_id com data/hora e preservação dos42IDs, CTA junto aotítulo, correção defoco e regressões preservadas. Contagem45 édeEVENTOS/REGISTROS, não45mensagens/Operations. Orbe corrigiu spec. Codex apontou que dedup misturando message_id e request_key também pode supercontar; exige domínio consistente compartilhado por TODOS osregistros ou mantém rótulo de registros.

Bytes9b012ef1 preservados fora das capturas intocáveis em .tmp/desktop-candidate-home-refinement-evidence-9b012ef1/evidence-receipt.json, approvedfalse. O harness futuro salva osbytes exatos em candidate-files na NOVA subpasta de captura, além de checks/PNG.053624,055848 e060755 não foram reescritas; índice só latest-report.json. Nenhuma publicação/restart/replay/homologação. Matriz18ABERTA.


## Contexto dos Dots, correção mobile e semântica do mascote

A captura .tmp/codex-candidate-home-review-20261013/20261013-062616/report.json preserva JS 0c6c31c1ad33fca091626035ebf544422d244247daa5eea03e7ce055b58261d6 e CSS 00a5aab5aa6896b650e9d08991d4d3b559f3813c607f78ffd3e168cc688326af. O foco passou a aparecer nos quatro lados, com offset interno. Contexto real por Dot e agrupamento de conversas foram integrados, mas Vitra e Orbe encontraram colisão entre nome, contexto e Ativo em 390/reduced: FAIL dessa etapa. A ausência de overflow horizontal não era suficiente. Nenhuma publicação/reinício.

Nova captura imutável .tmp/codex-candidate-home-review-20261013/20261013-064043/report.json, 24 PNG e candidate-files com bytes exatos. JS 8e4c5ca214fa9d58e248019c2bbd0b8e5c641ee8165f04db3d2c96c349bc6cb9 (2059629 bytes); CSS b9999b1d7f07ddb8e52cf229f0eb81125900ef23b6db6c3fb88000f07aecc81e (126832 bytes); HTML 1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3; manifest b9711108b28c21d5509825ae518bcd0926c5138d5e9e595aea573a546067249d. API real do broker 6836/50282. Todas as verificações passaram em 1440, 768, 390 e 390 reduced, sem erros JS/HTTP/requests bloqueados ou alteração dos bytes durante captura. A medição agora inclui interseção dos textos visíveis de nome/contexto/estado, respeitando clipping/reticências, além de foco/teclado/busca/menu. Em 390, linhas de 52 px empilham nome e contexto; Ativo e chevron ficam separados. Em desktop/tablet, linha única preservada. Revisão independente solicitada a Vitra e Orbe; resultado desta captura ainda não é PASS visual nem homologação.

Pebble corrigiu o contrato do mascote: active/running/working sem execução validada do host passam a idle. Working exige validated true e WorkItem/Operation em execução conforme canvasPhase, não apenas tarefa ou ciclo de vida ativo. Lumen ligou os call sites; nesta captura os seis Dots active têm mascotState idle. Não é prova de animação durante execução física. PNGs originais preservados. Contagem distingue 45 registros de atividade de uma mensagem deduplicada por chave real: o contexto diz 1 envio não confirmado, enquanto o cartão mantém 45 registros.

053624, 055848, 060755 e 062616 permanecem intocadas. O índice atual é latest-report.json, nunca report.json da raiz. Publicação e restart continuam proibidos; nenhuma operação UNCERTAIN reenviada. Refinamento integral de hierarquia, Canvas/Computador, funcionalidades físicas e todas as 18 frentes seguem ABERTAS.


## Revisão independente da captura 064043

Vitra e Orbe leram somente a pasta 20261013-064043 e fecharam o aceite estrito da colisão mobile nos bytes JS 8e4c5ca2 / CSS b9999b1d. Em 390 e reduced, nome/contexto ocupam linhas próprias, estado inteiro e chevron fora da coluna; passo 52 px. Desktop/tablet mantêm linha única. Foco visível, menu com três rótulos inteiros, seis mascotes idle. Isto não é PASS do redesign nem homologação ou autorização de publicação.

Limites de Vitra: título precede o trabalho, CTA distante na margem, Ativo repetido, título de conversa agrupada truncado em 390 e menu sobrepondo busca; Canvas/Computador fora desta captura. Codex pediu a Orbe uma etapa coerente de composição da Home, com trabalho/pendências prioritários, CTA próximo do contexto e conversas identificáveis, preservando os aceites. Lumen aguarda direção concreta antes de outro candidato. Não se reduziu o pedido original de qualidade visual a ajuste de frase isolada. Publicação/restart continuam bloqueados e todas as 18 frentes continuam ABERTAS.


## Próxima composição e preparação de outras superfícies

Orbe entregou a seção Etapa única da Home em spec-lumen.md: apoio/CTA agrupados à esquerda, busca próxima aos Dots abaixo das pendências, conversas agrupadas em duas linhas com Dot identificável. Codex encaminhou a Lumen para implementação exclusivamente staged, com contagens derivadas e preservação dos seis Dots visíveis, foco/menu/reduced/mascote. Ainda não há novo candidato congelado. O harness seguinte tem opções composition/conversations para medir posição do CTA/busca, visibilidade das linhas e abertura/recolhimento dos grupos com data/hora/Dot, sem abrir conversa ou acionar Space/Dot. Nenhuma nova captura dos bytes já aceitos foi feita.

Orbe preparou Canvas/Computador somente em seu spec, com base nos PNG reais 04:20. Canvas deve priorizar grafo/nó e compactar legendas vazias. Computador deve priorizar identidade/estado observado e recolher a seção da família. Codex corrigiu semântica do spec: Ainda não criada/VirtualBox indisponível nos PNG antigos são defeitos da superfície, não prova física. A VM Debian fcd974cf foi verificada instalada/em execução e VBoxManage existe fora do PATH. Sem vínculo/consulta contemporâneos, mostrar estado ainda não consultado ou não confirmado, não induzir reinstalação/importação. Nenhuma cópia confirmada significa falta de recibo, não prova de ausência física de arquivos. Valores 2/4096/64 são de formulário, não medição. Orbe confirmou a correção somente no spec. Nada integrado ou homologado nestas duas superfícies; release/restart continuam bloqueados.


## Captura da Etapa única da Home

Candidato de Lumen congelado e capturado contra API real em .tmp/codex-candidate-home-review-20261013/20261013-070729/report.json, 28 PNG e candidate-files. JS c4a159ee6fe7ff9af840b666157653cff8d2f70faf338002daef9b59842a265f (2060336 bytes), CSS adcb93b90df5303fbba894b380c72dc0e6a4575a6acf226b836ec23f4c64a11f (127169 bytes), HTML 1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3, manifest 58d9e4917a688d6e1a8256c012f9ffd56075adb9f16ed44ea8487893f109f2e4. Verificações verdadeiras em 1440/768/390/390 reduced; zero erro JS/HTTP, requests bloqueados e alteração dos bytes. CTA fica a 16 px do apoio em desktop/tablet e quebra alinhado à esquerda em 390; busca segue pendências; seis Dots continuam visíveis. Foco, menu, reduced e mascotes idle preservados.

Probe de grupos de conversas: Enter abre e recolhe, sete itens reais do primeiro grupo identificados por conversation_id, dia/hora e Dot. Nenhuma conversa/Space/Dot foi acionado. Captura preliminar 20261013-070554 preservada, mas o enquadramento dos itens abertos ficava fora da tela; o harness foi corrigido apenas para enquadrar o grupo aberto e a nova pasta 070729 é a enviada aos revisores. Nada sobrescrito. Abertura local do grupo não reenvia Operation nem mensagem.

Vitra e Orbe receberam exclusivamente essa pasta para revisão independente. Candidato ainda sem aceite visual desta etapa, não homologado/não publicado; nenhum restart/build/materialize de Codex. Todas as 18 frentes continuam abertas. A composição é melhoria parcial, não fechamento do redesign.


## Aceite parcial de composição, sem promoção

Vitra confirmou a leitura exclusiva de 20261013-070729, JS c4a159ee6fe7ff9af840b666157653cff8d2f70faf338002daef9b59842a265f e CSS adcb93b90df5303fbba894b380c72dc0e6a4575a6acf226b836ec23f4c64a11f. Aceitou esta composição parcial: CTA próximo do apoio, busca próxima aos Dots, linhas sem colisão/foco preservado e sete conversas reais distinguíveis por data/hora/Dot, abertas/recolhidas somente como grupo. Não é redesign integral, homologação ou promoção. Limite: menu sobrepõe apoio/CTA em 390 quando aberto; título e cartão ainda precedem os Dots. Orbe ainda conclui sua leitura.

Lumen recebeu a próxima etapa de apresentação de Canvas/Computador com diretório staged separado .tmp/desktop-candidate-canvas-computer, usando somente a spec corrigida e baselines existentes. Grafo/nó antes de legendas vazias; identidade/estado observado antes de formulário/família; falta de consulta/recibo não vira ausência física. Preservar controles/callbacks e Home aceita, sem API/VM/terminal/input/instalação/importação/PNG. A leitura readonly destas superfícies precisa preparação antes de captura: não reusar o harness antigo que permite todo GET nem executar handler de output que reconcilia recibos. Nenhum candidato destas superfícies foi produzido ou aprovado nesta etapa. Ninguém autorizado a publicar ou reiniciar.


## Preparação readonly de Canvas e Computador

Candidato separado .tmp/desktop-candidate-canvas-computer conferido offline: JS 665237fb9f76b254981b311f4cbb9ac9cbc4bfd187f15677705feb061192023c, CSS 8416f0652b8ed5bcc95043f477baf58f4669cd6549b09327d31d939113e10362, HTML 1c959e724a618c3eacb8d6e4537d29ff0d96ca8d561917ab99ded01106e410d3, manifest 0f39a88ea4b8852e51ca178fdc10996ec43d384c3b0ebbce3c1fc04a77865a19. 129 arquivos e 128 entradas de manifest, sem hashes ausentes/divergentes. Os PNG staged desktop/desktop2/desktop3/desktop4 correspondem byte a byte aos originais blue/mint/orange/purple. Diretórios congelados da Home intocados.

Artefatos próprios: .tmp/codex_canvas_computer_readonly_preflight_20261013.py e .tmp/codex-canvas-computer-readonly-preflight-20261013/20261013-073505/preflight.json. Política negativa validada em 21 casos, sem browser, captura ou chamada API. Estado PREFLIGHT_COMPLETE_CAPTURE_BLOCKED, capture_ready false. Não é rejeição automática de aprovação; é resultado concreto da auditoria de callbacks e da exigência readonly.

Bloqueios encontrados na fonte: service.terminal_output pode chamar _uncertain_receipts_for_terminal; dot_canvas_get chama deliveries(), que pode mudar WAITING_EXTERNAL para UNCERTAIN quando não há PTY vivo; dot_vm_status pode re-registrar o provedor e persistir sua configuração; dot_vm_frame cria Operation e despacha vm:observe. Inicialização dos serviços de máquinas e nested reads também não foi certificada sem efeito. Esses handlers ficam bloqueados antes do broker. O nome READ ou o método GET não prova ausência de mutação. Fonte atual não comprova código Python já carregado no PID 6836; a guarda é conservadora diante dessa diferença.

Lumen recebeu maestri ask com a preparação, os hashes, os bloqueios e a orientação de manter candidato/callbacks/APIs congelados. Não foram fabricadas respostas de VM ou fixtures para fazer uma captura parecer limpa. Uma captura que aborte os autoreads seria parcial e teria artefatos da guarda, não PASS de produto. O próximo caminho precisa separar projeções observacionais de reconciliação/admissão; nenhum reload ou efeito autorizado por essa constatação. Nenhuma frente homologada, publicação/restart bloqueados.
