# SENTRA — checkpoint de implementação e retomada

Data: 09/10/2026. Snapshot solicitado pelo proprietário para preservar e enviar ao GitHub o trabalho antes do limite de uso. Base anterior: `68e3894`. Este documento descreve implementação, integrações e lacunas; não declara uma release aprovada.

## Estado real da entrega

Há uma base de código muito mais extensa: execução central durável, adaptadores reais, workflows, colaboração de documentos, agentes com contexto e uma nova superfície desktop. Há testes preparados e handoffs por frente. Ainda não temos a incorporação integral aceita dos37 projetos.

Nenhum requisito dos37 foi marcado concluído apenas pela existência de módulos. A regra continua sendo: implementação concreta + ligação ao produto + evidência de execução correspondente ao critério de aceitação. Configuração, registro de máquina, catálogo, ACK de transporte e retorno de processo não comprovam por si só uma tarefa verificada.

O snapshot reúne as alterações de projeto presentes no checkout, incluindo trabalho anterior ao coordenador desta rodada. Não atribuir todas as mudanças deste commit a um único agente ou somente à solicitação mais recente. Estado local, credenciais, caches, node_modules e clones independentes de third_party não fazem parte da entrega versionada.

## O que avançou no núcleo

1. **Autoridade central e persistência:** admissão pelo Control Plane existente, vínculo entre principal/Run/WorkItem/máquina/capability, intent imutável, fencing e recuperação por recibos duráveis.
2. **Efeitos físicos:** locks de recursos e máquina, leases/checkpoints e posse de workers. Cancelamento do chamador não libera antecipadamente um efeito físico ainda em andamento. Operação incerta bloqueia repetição até reconciliação.
3. **Evidências:** captura de Artifact dentro da fronteira física, hashes, resultados protegidos e referências no ledger. Retorno tardio serve como evidência diagnóstica; não promove sozinho uma operação incerta a sucesso.
4. **Host de máquinas:** event loop próprio, configuração persistida, restauração com verificação de workspace/agente, inventário, seleção por capability e despacho ligado ao WorkItem correto.
5. **Governança e limites:** integração com tarefas, orçamento/consumo, quota e estados centrais. Consumo não informado não é tratado como custo zero conhecido.
6. **Produto:** rotas Canvas/CLI para configuração, preparação de tarefa, execução, observação, experiências, planos e diagnóstico. Central com paginação de Runs, WorkItems e Operations, máquinas e limites.

Principais arquivos: `sentra_runtime/central_authority.py`, `effect_boundary.py`, `machine_host.py`, `provider_content.py`, `machine_budget.py`, `sentra_mcp/services/durable.py`, `sentra_executors/central_integration.py`, `sentra_canvas/service.py` e `sentra_cli/canvas.py`.

## Canvas desktop e qualidade visual

- Nova superfície em `sentra_canvas/desktop_ui/`; entrada `sentra_canvas/static/desktop.html`; bundle local em `static/desktop-assets/`.
- Componentes efetivamente incorporados: React Flow/XYFlow 12.12.0, React 19.3.0, Radix, Lucide e xterm 6.0.0. Pins transitivos no package-lock e manifesto do bundle.
- Direção visual da imagem Maestri: sidebar grafite, grid fino, barra de ícones flutuante, nós de terminal compactos, conexões curvas tracejadas e controles de zoom/mapa.
- Launcher pywebview/WebView2 abre uma janela Windows. O frontend usa HTML/React local dentro dessa aplicação; esse caminho não depende de abrir um navegador comum.
- Uma janela de avaliação foi aberta com três PowerShell/ConPTY reais. A instância antiga e seus terminais foram preservados.
- O frontend mantém views xterm por identidade de PTY, com filas de input/resize e sem recriar processos por pan/zoom/expansão.
- Dialogs para recursos/agentes/equipes, objetivo do agente, contexto e Rede. Integração visual com painéis de máquinas, workflows, Central e colaboração.
- Corrigida a colisão do import Lucide `Map` com o construtor JavaScript `Map`, responsável pela tela preta.

**Inspeção efetivamente relatada pelo agente visual:** superfície do broker de avaliação em 1440×900 com três nós/três xterms e nenhum pageerror. Capturas em `desktop_ui/evidence/`. Isso não comprova aprovação visual do proprietário, todos os fluxos nem a execução em WebView2 após reload.

**Limitação da prévia aberta:** o broker carregou o backend antes da nova rota Rede e respondeu `route not found`; o diálogo apresentou esse erro, sem simular sucesso. O bundle corrigido exige reload da janela. A nova API exige um processo atualizado; preservar terminais existentes antes de trocar o broker.

**Ainda falta:** revisão visual pelo proprietário, DPI/teclado/acessibilidade, drag e controles da janela, reconexão e Unicode/PTY, todos os diálogos com dados reais, build do executável, atalho, instalador e teste de fechar/reabrir sem perder sessões.

Detalhes: `sentra_canvas/desktop_ui/README.md` e `docs/SENTRA_DESKTOP_AUTONOMIA_REDE_2026-10-09.md`.

## Contexto e autonomia dos agentes

- Contexto protegido por workspace/agente, digest e revisão CAS: objetivo, papel, tarefas próprias, conexões e notas dirigidas.
- A CLI consulta o contexto atual por sua capability de sessão, sem copiar indiscriminadamente conversas de outros agentes.
- Criação de filho aceita nome/modelo/papel/brief. O objetivo selecionado e a entrega inicial persistente permitem que o filho recupere contexto.
- Identidades de filhos são registradas antes do bootstrap. Resposta perdida não relança automaticamente o agente nem a entrega.
- Comandos de criação de equipe, conexão e colaboração são reutilizados. Contexto e notas não criam grants de execução.

**Ainda falta:** prova com modelos reais criando filho/equipe e respondendo, testes de concorrência/restart/bootstrap, integração completa da coordenação à admissão central e tratamento de falhas parciais entre criação, registro e contexto.

## Hamachi/Radmin e whitelist

- Configuração protegida com CAS: adaptador Hamachi/Radmin/manual, IPv4 local, whitelist, porta comum37037 e rótulo.
- Cadastro vazio com descoberta desativada é permitido. Interfaces locais são obtidas do Windows quando disponíveis; entrada manual continua válida.
- Diálogo Rede no desktop. Rotas owner `GET/POST /api/center/network` e pareamento explícito `POST /api/center/network/pairing`.
- Agente vivo pode consultar e configurar campos autorizados da rede via `network_settings`/`network_whitelist`, solicitando os IPs ao usuário. Não recebe nem altera a chave de pareamento.
- Presença UDP assinada com Ed25519 e autenticação do mesh, whitelist de fonte, porta, validade, limites e defesa contra replay. Unicast explícito permite descoberta em VPN sem multicast.
- Descoberta não concede autoridade de máquina. A UI mostra somente peers efetivamente retornados pelo serviço.

**Ainda falta implementar:** transporte autenticado de tarefas e resultados, outbox/receipts/reconexão, despacho remoto ligado à admissão local, seleção de contexto compartilhado e política de colaboração automática. A presença implementada não é colaboração distribuída completa.

**Ainda falta validar:** duas máquinas reais Hamachi/Radmin. O proprietário informou que ainda não há IPs disponíveis. Não inventar pares nem declarar esse fluxo funcionando antes dessa prova.

## Workflows, documentos e colaboração

- Workflows com definições do proprietário, checkpoints, sinais, subflows, retries classificados e retomada. Inputs protegidos e operação separada por atividade.
- Máquina de workflows de documentos ligada ao host, com editor de etapas/sinais no Canvas. Falha de verificador falha a atividade.
- CSV/XLSX/PDF e interfaces explícitas para OCR/recalcular, sem tratar arquivo produzido como resultado semanticamente correto.
- Yjs/Y.Text, posições relativas, UndoManager e presença y-protocols; sidecar Hocuspocus com grants centrais, tickets de uso único e snapshots CAS.
- Projeção de layout/notas separada da autoridade de execução. Recuperação após interrupção de commit.
- Experiências derivadas de recibos e revisão/undo de planos preservam proveniência de efeitos já iniciados.

**Ainda falta:** pieces e providers completamente ligados ao produto, provas de crash/revoke/concorrência, runtime externo Activepieces, funcionalidades adicionais LangGraph/Temporal e verificação de workflows reais ponta a ponta.

## Desktop, serviços externos e isolamento

- Browser Playwright real com sessão/perfil, captura e verificadores; documentos/RPA com paths autorizados.
- UIA semântico e workflows de ações, identidade de sessão Windows e bindings de guest.
- Daytona com lifecycle/PTY/comandos/streaming; Guacamole com protocolo guacd, TLS/pins, cursores/gravação e contratos de viewer/tunnel.
- RustDesk com launcher/patch nativo próprio, pin da identidade do peer e watchdog; bundle privado copiado/verificado por hashes. Runtime, manifest e outputs têm autoridades de path separadas.
- Helpers de guest Windows/Hyper-V, bridge HCS e worker runsc/gVisor preparados.

**Ainda falta:** builds nativos/Go, providers/guests reais e seus prerequisitos, login/frame/input/revoke/cleanup, montagem final do viewer Guacamole e comprovação de isolamento. Posse de subprocesso/JobObject não equivale a sandbox de sistema operacional.

## Identidade, auditoria e observabilidade

- Keycloak OIDC, ciclo de vida OpenFGA, políticas OPA/bundles e cliente SPIRE com SDK/Workload API oficial implementados em módulos.
- NATS JetStream via SDK Go: PubAck, dedupe/reconciliação, pull e ACK/NAK/TERM/InProgress.
- Tessera: append, checkpoints/tiles, inclusão/consistência e quorum de witnesses.
- immudb: operações verificáveis, estado assinado, proofs e export de transação audit.
- Outbox/inbox protegidos, dedupe, retenção, tombstones, anchors e divergências. Recebimento de evento não executa comando nem cria grant.
- Pipeline OTLP com fila persistente, batching, limites, retenção, retries e contadores de perda.
- Grype: execução por binário pinado, SBOM, freshness, diagnósticos e diff de scans.

**Ainda falta:** AuditHost/configuração CAS/rotas owner, ligar ledger real aos providers, script de build SDK, go.sum/binários, TLS/ACL/credenciais, serviços e anchors/witnesses reais. Integração definitiva de identidade/políticas ao produto, deployment Collector e ligação de avaliação Langfuse. Scanner/DB/SBOM reais e revisão de TOCTOU. Nenhuma prova externa desta rodada foi executada.

## Benchmarks e avaliação independente

- Catálogo e formatos reais locais de Windows Agent Arena, OSWorld e WindowsWorld; pins/source drift e assets declarados.
- APIs `select`, `attempt`, `evaluate`, `resume` e `report`; tentativa separada de avaliação.
- Intents/IDs persistidos por passo e callbacks de host para bind/dispatch/recover/checkpoint/fixture/verifier; retomada consulta estado, sem reset/replay de efeito incerto.
- Métricas e relatórios separam resultado do agente e juiz independente. Assets/providers/formatos gated ausentes ficam unsupported.

**Ainda falta:** ligar callbacks a Core/guests reais, preparar snapshots/fixtures/goldens/collectors, assets autorizados e executar tarefas. Nenhuma tarefa foi declarada evaluated nesta implementação. OSWorld V2 gated e casos sem providers permanecem indisponíveis.

Detalhes: `sentra_executors/DATASET_EVALUATION_HANDOFF.md`.

## Matriz dos37 projetos para retomada

Todas as linhas permanecem com aceitação integral pendente. A coluna de avanço indica código/contratos entregues, não validação de runtime externo.

| # | Projeto | Avanço presente | Principal trabalho restante |
|---|---|---|---|
| 1 | UFO | Experiências protegidas e revisões de plano ligadas a recibos | Seleção de dispositivo/carga e prova de reutilização/obsolescência |
| 2 | OpenHands | Provider Agent Server, IDs/cursor/eventos e binding ao host | Runtime real, reconexão fora de ordem e recuperação completa |
| 3 | OpenHands Agent SDK | Condensação preservando instruções/contexto e leases/boundary | Sessão real, retomada e correspondência tool→Operation |
| 4 | ACP | Lifecycle negociado, config/usage e processos owned | Binding completo ao produto e CLI externo real |
| 5 | ACP Registry | Planos de instalação pinados binary/npx/uvx | Instalar/lançar distribuição selecionada e conferir integridade |
| 6 | A2A | Mapeamento/gates/transportes e estados duráveis | Recursos adicionais e servidor/peer real; loopback não prova VPN |
| 7 | MCP TypeScript SDK | Binding/transporte compatível com autoridade central | Contratos TS e execução real integrada |
| 8 | Daytona | SDK lifecycle, PTY, comandos e streaming ligados ao host | Serviço/credenciais/toolbox e aceitação real |
| 9 | pywinauto | UIA semântico, workflows e identidade Windows | Aplicações/guest reais, selectors/revoke/cleanup |
| 10 | hcsshim | Bridge Go/HCS e contratos de boundary | Build, host compatível e container real |
| 11 | gVisor | Worker OCI/runsc e verificação de workload | Linux/runsc real e prova de isolamento/cleanup |
| 12 | Playwright MCP | Backend real de browser e verificadores | Integração completa de contrato e aceitação final |
| 13 | Guacamole Client | Viewer/playback e contratos de tunnel | Bundle/montagem na UI e desktop real |
| 14 | Guacamole Server | Protocolo guacd/TLS/pins/cursor/gravação | Provisionar guacd/guest e testar login/input/revogação |
| 15 | RustDesk | Patch/launcher próprios, bundle privado, path separation | Build próprio, peer real, login/frame/control |
| 16 | LangGraph | Checkpoints/subflows/controle e workflows de documentos | Cobertura restante e runtime completo ponta a ponta |
| 17 | Temporal | Sinais/retries classificados/retomada no workflow | Cobertura restante e integração de runtime externo |
| 18 | NATS Server | SDK JetStream e outbox/inbox | AuditHost, broker/ACL/TLS e prova de entrega/reconciliação |
| 19 | ToolHive | Catálogo seletivo autorizado e invalidação de schemas | Catálogo no produto e prova de redução/correção |
| 20 | SPIRE | SDK oficial/Workload API e estado de identidade | Build, atestação, renovação/revogação real |
| 21 | Keycloak | Provider OIDC e lifecycle | Realm/serviço real e integração de login |
| 22 | OpenFGA | Lifecycle/modelo/relacionamentos/autorização | Serviço/modelo real e binding na política central |
| 23 | OPA | PDP, bundles e máscara de logs | Serviço/bundle real, decisões e revogação na aplicação |
| 24 | Tessera | Append/checkpoints/proofs/witnesses | AuditHost, log, anchors e quorum reais |
| 25 | immudb | VerifiableSet/Get, proofs/estado/export | AuditHost, DB/TLS/estado confiável e provas reais |
| 26 | OpenTelemetry Collector | Pipeline OTLP persistente e configuração | Deployment Collector e demonstração de export |
| 27 | Langfuse | Requisitos/fronteiras de observabilidade mapeados | Integração completa de traces/datasets/evals no produto |
| 28 | Grype | Scanner pinado e comparação/diagnóstico SBOM | Binário/DB reais, prova e revisão da captura de inputs |
| 29 | XYFlow | React Flow real no desktop, nodes/resize/pan/zoom/mapa | QA de sessões, escala, teclado, DPI e aprovação visual |
| 30 | Yjs | Y.Text, undo e posições relativas | Concorrência, persistência e revogação ponta a ponta |
| 31 | y-protocols | Awareness com propriedade/clock/TTL | Disconnect/revoke real e integração distribuída |
| 32 | Hocuspocus | Sidecar real, tickets/grants e snapshot CAS | Crash/recovery, revogação e runtime integrado |
| 33 | Activepieces | Provider HTTP e worker SDK piece | Pieces/providers no produto e runtime externo real |
| 34 | RPA Framework | CSV/XLSX/PDF, OCR/recalcular configuráveis | Providers opcionais e aceitação semântica real |
| 35 | Windows Agent Arena | Catalog/attempt/evaluate/report e métricas | Guest/fixtures/juiz reais e tarefas avaliadas |
| 36 | OSWorld V2 | Loader/contratos e unsupported explícito | Assets gated/snapshot/providers e avaliações reais |
| 37 | WindowsWorld | Loader/métricas/estado intermediário/report | Seeds/goldens/collectors e execução real |

## Validação: o que foi e o que não foi feito

- Existiram execuções de testes em etapas anteriores, documentadas nos respectivos relatórios. Não usar esses resultados históricos como prova do snapshot atual.
- Bundles de colaboração e desktop foram construídos para materializar a interface. A inspeção visual do agente confirmou renderização após a correção MapIcon; não substitui suite de funcionalidade nem aprovação visual.
- Por instrução do proprietário, implementação veio primeiro e bateria integral ficou para o final. Novos testes foram escritos/preparados, mas a bateria integral deste estado não foi executada.
- Não houve aceitação real nesta rodada dos serviços externos, builds nativos/Go, VMs ou colaboração Hamachi/Radmin. Ausência de prerequisite deve aparecer como pendência explícita, nunca sucesso simulado.
- O commit é checkpoint de trabalho em andamento. Fazer push não valida nem publica uma release operacional.
- Na preparação do commit, `git diff --cached --check` apontou whitespace em patch upstream, documentação e bundle gerado. Esses arquivos foram preservados; a conferência de whitespace não passou limpa. Não alterar linhas de contexto do patch ou bytes/manifest do bundle apenas para ocultar o aviso.

## Ordem prática para continuar

1. Restaurar o checkout deste checkpoint e consultar os handoffs, matriz e manifests. Clones third_party são independentes: recriar/verificar pelos HEADs/pins registrados quando não estiverem presentes.
2. Atualizar a prévia desktop de forma que preserve as sessões, recarregar o bundle e testar diálogo Rede em backend atualizado. Obter avaliação visual do proprietário.
3. Terminar viewer/gateway Guacamole e transporte peer de tarefas/resultados. Autenticação/discovery não substituem admissão de trabalho.
4. Terminar AuditHost e ligações de identidade/políticas/ACP/MCP/A2A/Activepieces/Langfuse ao produto, com configuração owner e secrets privados.
5. Ligar datasets ao host central e preparar ambientes/fixtures/providers reais. Completar lacunas por projeto, sem reduzir critérios ao código existente.
6. Compilar bridges/builds nativos e provisionar serviços necessários. Registrar prerequisites, versões e evidências reproduzíveis.
7. Executar validação integral Python/JS/frontend/integração/E2E e aceitação real por provider; corrigir falhas. Registrar pass/fail/skip e limitações.
8. Empacotar e aceitar executável/instalador Windows. Só então promover os requisitos correspondentes a concluídos e avaliar a conclusão integral dos37.

## Documentos de referência

- Auditoria original: `docs/SENTRA_AUDITORIA_INTEGRAL_ECOSSISTEMA_2026-10-08.md`.
- Reavaliação37: `docs/SENTRA_REAVALIACAO_REAPROVEITAMENTO_37_PROJETOS_2026-10-09.md`.
- Requisitos verificáveis: `sentra_quality/incorporation_requirements.json` e `desktop_agent_collaboration_requirements.json`.
- Núcleo/Canvas: `docs/SENTRA_INCORPORACAO_NUCLEO_CANVAS_2026-10-09.md`.
- Workflows: `docs/SENTRA_INCORPORACAO_WORKFLOWS_CANVAS_2026-10-09.md` e `SENTRA_INCORPORACAO_WORKFLOW_ACTIVEPIECES_2026-10-09.md`.
- Identidade: `docs/SENTRA_INCORPORACAO_IDENTIDADE_POLITICA_2026-10-09.md`.
- Auditoria externa: `docs/SENTRA_INCORPORACAO_NATS_TESSERA_IMMUDB_2026-10-09.md`.
- Desktop/guest: `sentra_executors/DESKTOP_GUEST_BENCHMARK_HANDOFF_ROUND4.md`.
- Dataset: `sentra_executors/DATASET_EVALUATION_HANDOFF.md`.
- Desktop visual: `sentra_canvas/desktop_ui/README.md` e capturas em `evidence/`.
