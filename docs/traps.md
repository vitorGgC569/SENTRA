# TRAPS — Erros, dificuldades e limitações já vencidas

> Leitura obrigatória antes de orquestrar agentes neste repositório.
> Cada item: **sintoma → causa-raiz → correção → regra**.
> Referências `arquivo:linha` são aproximadas; use-as como ponto de partida.

---

## 1. Extensão Edge live (caminho real: provider → relay → tabs reais)

### 1.1 NEW_CHAT via content-script mata o canal de mensagem
- **Sintoma:** `TAB_ERROR: ... message channel closed before a response was received`.
- **Causa:** o content-script navegava (`window.location.href=...`); a navegação
  destrói o contexto JS antes do `sendResponse`.
- **Correção:** navegação pertence ao service worker (`chrome.tabs.update`) —
  `edge_extension/service-worker.js` (`omaProcessJob`); no content-script, `NEW_CHAT`
  responde de forma síncrona ANTES de navegar (fallback).
- **Regra:** content-script só faz operações **in-page**. Navegação/ciclo de vida de
  tab é do worker.

### 1.2 Race: página antiga responde antes do unload terminar
- **Sintoma:** mesmo `TAB_ERROR` acima, em ~2–3s, mesmo após 1.1.
- **Causa:** `GET_STATUS` era respondido pelo contexto da página ANTIGA; o
  `SEND_MESSAGE` chegava durante o unload e o canal morria.
- **Correção:** `omaWaitTabComplete` — esperar `tab.status === 'complete'` via API
  **antes** de qualquer `sendMessage` (`edge_extension/service-worker.js`).
- **Regra:** após navegar, sincronize por **estado via API**, nunca por sleep fixo.

### 1.3 Submit preenchia mas não enviava
- **Sintoma:** texto visível no composer, nada enviado (screenshot prova).
- **Causa dupla:** seletor do botão (`data-testid='send-button'`) desatualizado +
  Enter sintético (`KeyboardEvent`) é evento **não-confiável** e o editor ignora.
- **Correção:** cadeia botão (4 seletores) → `form.requestSubmit()` → Enter, cada
  etapa verificada por **aceite via estado** (composer esvaziou OU stop apareceu) —
  `omaSubmitAccepted` em `edge_extension/content-script.js`.
- **Regra:** todo DOM de terceiros muda; use N seletores + verificação de efeito.
  Enter sintético é sempre último recurso.

### 1.4 Worker antigo invisível disputava os jobs
- **Sintoma:** erro idêntico repetido após reload; correção "não pegava".
- **Causa:** cópia duplicada da extensão instalada (ou worker pré-reload) consumia
  o job primeiro e falhava com código velho.
- **Correção:** telemetria `sw=`/`cs=` em todo resultado/erro + versão do
  `manifest.json` acompanhando o código (o card mostra o manifest, não constantes).
  Erro sem tag `[sw=]` = código velho rodando.
- **Regra:** toda mensagem de erro do bridge carrega versão. Uma única cópia
  instalada. Na dúvida, remover todas e carregar uma vez.

### 1.5 Content-script obsoleto em tabs abertas
- **Sintoma:** reload da extensão não atualiza scripts de tabs já abertas.
- **Causa:** injeção nova só ocorre em navegação/carregamento.
- **Correção:** nosso fluxo sempre navega (`new_chat=true`) antes de operar, logo
  recebe injeção fresca; `GET_STATUS` reporta `cs_version` para detectar desvio.
- **Regra:** nunca opere tab "herdada" sem navegar primeiro (ou sem checar versão).

### 1.6 Pool adotava a tab ativa do usuário
- **Sintoma (quase-incidente):** worker poderia navegar a conversa atual do usuário.
- **Correção:** `oma_owned_tabs` em `chrome.storage.local`; pool cria tabs próprias
  em 2º plano e **nunca** adota tabs existentes (`edge_extension/service-worker.js`).
- **Regra:** atuador jamais toca estado do usuário; opera só no que criou.

### 1.7 Envelope `{ok, result}` — ler campo no nível errado
- **Sintoma:** telemetria `cs=unknown` com tudo funcionando.
- **Causa:** content-script responde `{ok:true, result:{...}}`; código lia `ans.cs_version`.
- **Regra:** desembrulhar envelope em UM helper, nunca espalhar `ans.result.X`.

### 1.8 Diversos (bridge)
- `fetch` ao relay precisa de `host_permissions` p/ `http://127.0.0.1/*`.
- MV3: service worker dorme; polling + `chrome.storage` mínimo; **fila vive no OMA**.
- Teste live sobe o próprio relay (`tests/e2e/test_extension_live.py`); porta
  ocupada = falha espúria — checar `:8765` livre antes.
- Prompt duplicado quando system==user → dedupe no provider
  (`orchestrator/providers/extension_provider.py`).
- Conformidade: automatizar UI do ChatGPT pode violar os ToS; API é o caminho
  suportado. Arquitetura é agnóstica — trocar o site não toca OMA
  (`orchestrator/projects.py` desacopla `OmaProject ≠ ResearchRun ≠ RemoteConversation`).
- Swarms: começar pequeno (rate-limit). 50 conversas ≠ 50 tabs (pool reutiliza).

---

## 2. Engine / fila (núcleo determinístico)

### 2.1 DEADLOCK: dependente de tarefa terminal travava a run
- **Sintoma:** `run()` girando em `sleep(0.1)` para sempre; faulthandler mostra loop
  idle sem frames da engine (corrotina suspensa sem timeout).
- **Causa:** tarefa ESCALATED/FAILED/CANCELLED nunca liberava dependentes bloqueados.
- **Correção:** cascata `DEPENDENCY_ERROR` (`_fail_dependents_locked` em
  `orchestrator/queue.py`), `PENDING→FAILED` permitido
  (`orchestrator/state_machine.py`), `mark_escalated` via FAILED quando o estado
  direto é ilegal, guard `fail_unfulfillable_blocked` no loop (`engine.py`).
  Regressão: `tests/failure/test_dependency_failure.py`.
- **Regra:** todo estado terminal libera dependentes. Nenhum `await` sem timeout ou
  condição de saída no núcleo. `has_pending_work` + `running==0` + só-bloqueadas =
  finalizar, nunca girar.

### 2.2 Transições ilegais no escalonamento
- **Sintoma:** `InvalidStateTransitionError: RUNNING→ESCALATED`; antes:
  `QUALITY_GATE→ESCALATED` (adicionado).
- **Correção:** `mark_escalated` tenta direto; se ilegal, rota via FAILED (melhor
  trilha de auditoria que afrouxar a máquina).
- **Regra:** endurecer o chamador, não afrouxar a máquina de estados.

### 2.3 Repair infinito quando o patch nunca é aplicado
- **Sintoma:** 5 rounds de repair, sempre rejeitado, depois escala.
- **Causa:** validadores rejeitam por teste determinístico falho, mas o patch só é
  aplicado ao workspace **após** aprovação do Master — o teste falha igual todo round.
- **Correção (testes):** cenário E2E de sucesso usa comando de validação que passa
  deterministicamente; dinâmica de repair tem teste próprio (`test_repair_loop.py`).
- **Regra:** em E2E, premissa de sucesso exige validação verde; propagar a causa,
  não mascarar.

### 2.4 Ordem do ciclo de self-improvement
- **Sintoma:** `run_cycle` retornava REJECT com patch bom.
- **Causa:** testava o root real ANTES de promover (root ainda com o bug).
- **Correção:** sandbox → gate de PROTECTED → promove no root → testa root →
  rollback se falhar (`self_improvement/engine.py`).
- **Regra:** validar onde o código está, promover antes de testar o destino.

---

## 3. Timeouts (RF-016)

- **Buffers duplos:** router `+30s` × provider `+30s` = testes de 150s.
  Padrão: router `+5s`, browser `+10s` (comentário na linha explica a graça).
- **Fallback esquecido no timeout:** router retornava TIMEOUT sem tentar fallback.
  Timeout também dispara fallback (`orchestrator/agents/router.py`, `_try_fallback`).
- **Timeout default 120s vaza para testes:** `AgentRequest` sem timeout explícito +
  validador = teste de 150s. Para lógica, use double de falha-rápida; hang real só
  em 1–2 testes dedicados.
- **Parcial silencioso esconde timeout:** `ResponseCapture` levantava nada e
  retornava último texto. Agora levanta `TimeoutError`
  (`browser/response_capture.py`).
- **Cancelamento:** `CancelledError` sempre propaga (nunca converter em resposta);
  testado com `pytest.raises(asyncio.CancelledError)`.

---

## 4. Testes e ferramental

- **Sem output ≠ travado (às vezes):** comandos longos não fazem streaming. Rode a
  suíte em **blocos curtos** (por arquivo/pasta), cada um com output visível.
- **Jobs em background morrem** neste ambiente (`Start-Job` some, `Start-Process`
  foi morto). Não confie neles; prefira blocos foreground curtos.
- **PowerShell:** sem `&&`, sem heredoc `<<`, `Select-Object -Last` só mostra no fim.
  Para hangs: `python -u` + `faulthandler.dump_traceback_later(N, exit=True)`.
- **Isolar hangs:** `--collect-only` (coleta ok?) → 1 teste por vez → faulthandler →
  script de debug replicando o teste com prints + `wait_for` global.
- **Paths no Windows:** `str(Path)` usa `\`; compare objetos `Path`, não strings.
- **`PersistenceStore(run_id, base_dir=tmp_path)`** existe — não faça monkeypatch
  de `__init__`.
- **Git em testes:** `index.commit` sem `user.name/email` falha (capturado, retorna
  False). Para asserir diff, faça commit baseline com GitPython no seed.
- **Budget global (200) derruba testes de carga:** declare `AntiExplosionConfig`
  explícito nos testes de load (rejeição silenciosa retorna `False` — cheque).
- **Status de teste:** cheque `exit code`, não substring (`ERROR` ≠ `FAIL`).
- **Cache de leitura:** chave = path+intervalo+hash; só-path quebra ranges diferentes.
- **Live tests:** `pytest.skip` sem env (`OMA_LIVE_EDGE`, `OMA_LIVE_EXTENSION`,
  `OMA_LIVE_LOCAL`). Sem env, sem browser, sem simulação.

---

## 5. Política e segurança

- **Default-deny morde:** papel novo (`critic`) sem entrada em `ROLE_PERMISSIONS`
  nega tudo em silêncio (achado via log `[OMA COMMAND] ... DENIED`).
  Todo papel novo exige permissões explícitas (`repository/policy.py`).
- **`PatchManager` escapava workspace:** `repo_root / rel` com `../../` ou absoluto
  sai do root. Sempre `resolve()` + `relative_to` (`workspace/patch_manager.py`).
- **Nunca `os.system(texto-do-modelo`):** regex só identifica intenção; handler
  registrado executa (`repository/registry.py` + `gateway.py`). Operação fora da
  allowlist = `UNKNOWN_OPERATION`.

## 6. Segunda leva (enxame de 50 sobre o bridge — melhorias reais aplicadas)

- **`assert` em caminho de produção** (`browser/tab_pool.py`): `assert` some com
  `python -O`. Invariantes críticas (não-perda/não-duplicação, limites do pool)
  viram `ValueError`/`RuntimeError` explícitos. Regra: `assert` só em testes.
- **Sem presença de worker, sem espera cega:** provider aguardava o timeout inteiro
  com extensão inexistente. Relay registra `last_poll` por worker; `/health`
  expõe `workers_online`/`workers_ever_seen`; transporte falha rápido e claro
  (`no extension connected`, graça ≤ timeout do job). Regra: observabilidade
  antes de espera.
- **Fill não verificado:** composer podia descartar o texto e o submit enviava
  vazio/antigo. `omaSendMessage` verifica retenção (2 métodos) ou `FILL_FAILED`.
  Regra: verificar escrita antes de agir sobre ela.
- **Catches invisíveis:** `catch(_){}` em loop quente esconde bug crônico.
  Contador persistente (`oma_error_counts`) + tag `err=N` nos resultados.
  Regra: todo catch silencioso conta; todo erro de job carrega versão+contagem.
- **Repair enxerga as notas ou corrige no escuro.** O prompt de repair carrega
  a tabela (papel, nota, veredito) + a barra vigente vinda da policy do gate
  (nunca hardcoded). Lacuna encontrada por inspeção, não por falha.
- **Release só com nota mínima (barra 9.5).** Críticos emitem `score` 0-10;
  fallback documentado `confidence×10`; normalização determinística
  (CRITICAL capa em 4, MAJOR em 7) contra inflação; gate exige MÍNIMO ≥ barra
  (maioria não basta); pacote carrega min/mean. Loop refina até a barra ou
  limites (stagnation/repair/budget). Travado em
  `tests/unit/test_release_threshold.py` (8 testes, incl. convergência 8→9→9.6).
- **Failover vs double-send se decide por metadados, nunca por string de erro.**
  Bloquear fallback em `[TIMEOUT]` puro quebra failover de modelo local (RF-019);
  liberar tudo permite double-send no browser. Regra: `retry_safe is False` ou
  `delivery_state ∈ {UNCERTAIN, BLOCKED}` bloqueia. `NOT_SENT` pode permitir
  failover no router geral, mas o modo de assentos fixos para após falha.
  Erro de UI/identidade sem fase explícita é incerto; timeout de router tem graça (+5s) para a
  classificação interna do provider vencer a corrida. Travado em
  `tests/failure/test_timeout.py` (3 testes).
- **Lapidação com teto, não loop infinito.** Reprovação volta ao repair com a
  crítica anexada; mesma rejeição 3x seguidas (assinatura: classe do motivo +
  comandos falhos + categorias dos findings) escala por STAGNANT sem queimar
  rounds. Humanos só veem CANDIDATE_READY ou esgotamento real com trilha.
  Piloto usa max_repair_rounds=4 (era 1: morria sem lapidar). Trava em
  `tests/failure/test_loop_limits.py`.
- **Primeiro ciclo real de 5 agentes: rejeição correta, não fracasso.** Executor
  gerou new-file sem `/dev/null` → dry-run barrou sem gastar validadores →
  repair instruído → validadores julgaram no mérito com achados específicos
  (overlap, hash inalterado, design). Sistema recusou lixo com precisão; reparar
  prompt do executor (regra new-file) + erro instrutivo > tentar de novo igual.
- **Piloto real: ler o artefato antes de teorizar.** Quatro rodadas, quatro causas
  distintas, todas nos artefatos (handoff/metrics/validations/budgets.json):
  diff malformado → budget travando validadores → confiança 0.42 no mérito →
  overlap de hunks. Nenhuma exigiu adivinhação; todas estavam nos JSONs.
- **Candidato pode vir com regressão embutida:** o primeiro CANDIDATE_READY trouxe
  downgrade de versão (1.3.17→1.3.9). Por isso promoção é explícita e externa
  (`requires_external_promotion`), nunca automática. Revise o diff do candidato
  como código hostil.
- **Contar papéis não basta para contar chats.** Planner/judge compartilham o
  assento master; repair compartilha executor. Cooldown e persistência envolvem
  cada envio do provider, inclusive resultados do gateway. Browser sem URL não
  degrada para chat novo: bloqueia. Falha de disco ou envio incerto nunca deve
  ser ignorada. Escopo ainda é por run, não conta inteira. Ver
  `docs/fixed-conversations.md` e `tests/integration/test_persistent_conversation_delivery.py`.
- **Assento travado: forense antes, `main.py --reconcile` para resolver.**
  `IN_FLIGHT` após kill = intenção incerta; a run trava por desenho. Caminho:
  `--reconcile` lista + cruza jobs do relay (só-leitura) → `--drop-seat`
  descarta explícito com journal (sem replay). Vindicado em run live: o candidato
  descartado aplicava limpo com testes verdes — o loop convergiu, a operação travou.
- **Bloqueio por assento, nunca global.** Um envio incerto trava só seu assento;
  travar a run inteira converte 1 tab ruim em stall total (visto em run live:
  1 seat incerto parou 5 saudáveis). A invariante que importa (nunca repetir
  envio incerto) é por assento. Travado nos testes de blockade reescritos.
- **Rate limit conta CHATS, não mensagens.** Delay entre mensagens não resolve;
  o controle é teto de criação (`oma.max_seats`, 5 = master+executor+3 validadores),
  recusado alto via `CONVERSATION_BLOCKED` sem acionar provider. NUNCA usar
  `compute_policy.max_agents` como teto de assentos (teto abstrato; era 500 =
  desligado). Escalada além do teto degrada visivelmente, não silenciosamente.
- **Compute policy começa em 5 e só escala com causa:** DISPUTED→standby,
  confiança baixa→standby, tarefa crítica→começa maior; teto `max_agents`;
  sem `compute_policy` no config, comportamento histórico intacto (pool default).
  Trava em `tests/unit/test_compute_policy.py`.
- **Recusa não é evidência (três lugares, mesma regra).** (a) Validador que não
  executou (budget/timeout/transporte) marca `ran=False` e sai do quorum com
  `INSUFFICIENT_VALIDATION` — nunca vota REJECTED (quebrava espiral de morte:
  8 tentativas → repair → escala sem nenhum julgamento). (b) Comando recusado
  pela política (`refused=True`) não entra em `failed_commands` nem gera
  CRITICAL fantasma; zero checagens executadas → gate insuficiente, não reprovado.
  (c) Reserva de budget em bytes contra limite em tokens super-reserva 4x:
  estimar input em tokens (`len//4`). Travado em
  `tests/failure/test_insufficient_validation.py` (9 testes).
- **Patch vazio é candidato legítimo** (tarefa só-verificação); só diff não-vazio
  malformado vai direto ao repair sem gastar round de validador (`PATCH_SYNTAX`).
  Descoberto quebrando o e2e legado — o e2e é o teste dessa distinção.
- **Dicts de auditoria sem teto vazam memória** (`provider.conversations`):
  cap FIFO de 1000 com teste. Regra: estrutura que cresce com runs tem limite.
- **Módulo alternativo avaliado e dispensado:** CDP/Playwright já existe como
  `PlaywrightProvider` (testes/E2E); extensão segue como caminho live.
  Regra: antes de criar módulo novo, prove que o existente não cobre.
- **Dual-bind no Windows (SO_REUSEADDR):** dois relays ligam na mesma porta e
  CADA UM tem sua fila — job submetido num e poluído no outro morre de inanição.
  Sondar `/health` antes de subir efêmero; nunca duplicar
  (`scripts/run_math_swarm.py`). Regra: probe-before-bind em recurso local único.
- **Tag `worker` do outbox:** resultado carrega `worker: TAB-<id>` (identidade do
  lease), não o formato de telemetria `BROWSER_WORKER_.. sw=..`. Não use a tag
  para inferir versão do worker — versão está no erro/payload.
  Regra: documente qual campo carrega qual semântica após merge de fluxos.
- **Botão ausente não prova teto de conta.** `no-buttons-found`, fill aceito e
  ausência de streaming também podem indicar UI incompleta ou seletor obsoleto.
  Sem banner/erro explícito de limite, classifique como UNKNOWN/UI, não quota.
  `STALE_CONVERSATION` pode aparecer APÓS envio; não prova `NOT_SENT` e não
  autoriza replay. Travas em `tests/unit/test_browser_outcomes.py`.
- **SPA ≠ reload: contaminação por conversa obsoleta** (achado no swarm Goldbach:
  agentes resolviam a faixa do vizinho, aritmética 100% válida!).
  `tab.status complete` não prova chat novo em SPA; prompt caía no chat anterior
  e o modelo "continuava a sequência". Guardas: `is_fresh_chat` (URL sem `/c/` +
  zero respostas) com reload forçado após 3 tentativas + ID da conversa
  obrigatoriamente novo por job (`STALE_CONVERSATION` aborta alto).
  Regra: verificar frescura E mudança de ID; nunca presumir navegação.

### Dashboard local estilo console (somente leitura)
- **Uso:** `python -B dashboard/server.py --port 8899 [--roots R1,R2]` →
  `http://127.0.0.1:8899/` (sidebar: visão geral, runs, conversas, falhas,
  resumos). Chats com URL da conversa; prompts/respostas do SQLite do relay.
- **Falhas:** agrega assentos quebrados + entregas FAILED + tarefas FAILED.
- **Resumos:** markdown de contexto gerado localmente por projeto/run
  (objetivo, tarefas, chats, validações, falhas, eventos), com copiar/baixar.
  Nada é enviado aos chats.
- **Raízes:** `runs/`, `.oma/` por padrão; externas via `--roots`.
- **Regras:** stdlib apenas; loopback apenas; só GET, nenhuma mutação; textos
  longos truncados; SQLite em `mode=ro`.
- **Armadilha real:** processos antigos grudados na porta servem a versão
  velha em silêncio (dual-bind vale p/ dashboard também). Após reiniciar,
  confira que resta UM `dashboard/server.py` e que `/api/failures` responde.
- (`dashboard/store.py`, `dashboard/server.py`, `dashboard/static/`,
  `tests/unit/test_dashboard.py`).

## 7. Operação do shell do operador

### 7.1 Shell derruba chamadas longas (`Unknown: ChildProcess.kill`)
- **Sintoma:** a chamada de terminal morre no meio (`Unknown: ChildProcess.kill`),
  sem saída e sem erro do comando — 3 ocorrências (relançamentos de run,
  restart do relay, lançamento com prompt longo). O processo destacado às vezes
  chegou a nascer antes da queda, às vezes não: estado incerto, conferir depois.
- **Causa:** gatilho exato desconhecido (kill do lado do harness, não do comando);
  correlação com comandos longos (`Start-Process` com `--prompt` gigante inline,
  redirects + sleeps na mesma chamada), mas houve caso curto — não há regra
  exata, só defensiva.
- **Correção (funciona sempre):** comandos curtos; conteúdo longo vai em ARQUIVO
  (ex.: `<workspace>/mission-<RUN>.txt` via ferramenta de escrita) e o lançamento lê
  do arquivo (`python -B -c` + `subprocess.Popen` com argv em lista, sem
  quoting de shell); separar lançar / esperar / verificar em chamadas distintas;
  sleeps de poll em chamadas próprias e curtas.
- **Regra:** nunca passe texto gigante como argumento inline no shell; arquivo
  para conteúdo, shell só para gatilhos curtos; após qualquer queda, verificar
  estado real (processo vivo? log? run dir?) antes de relançar.

## 8. Programa (isolamento, supervisor, memória, marcos, CI)
- **Planner silencioso virava 1 tarefa só.** Modelo devolve JSON estruturalmente
  completo mas com aspas internas sem escape (`"titulo "X", resto"`) → parse
  falhava → fallback determinístico criava T-01 com o objetivo cru, sem aviso,
  e a run queimava chats no escopo errado (visto 2x seguidas). Correção:
  prompt exige só-JSON + escape, parser prefere bloco ```json, retry limitado
  (3 tentativas) e **sem fallback: sem JSON, sem plano** (falha alta).
  Prova: `tests/unit/test_planner_retry.py` usa o padrão real observado.
  Regra: fallback silencioso que degrada escopo é bug, não resiliência.

- **Falha isola o galho, não a run.** Status `PARTIAL` = algumas tarefas
  prontas, resto falhou; só dependentes inalcançáveis caem em cascata
  (`DEPENDENCY_ERROR`). Irmãs `READY` nunca são tocadas.
- **Transitório retenta, permanente repara.** Marcadores: `STALE_CONVERSATION`,
  `DELIVERY_EXPIRED/UNCERTAIN`, `SUBMISSION_UNCERTAIN`, `TIMEOUT`, perda de
  lease (`oma.transient_max_retries=3`, backoff `base*2^n`, sem consumir repair).
  `UNCERTAIN` puro NÃO é marcador (reclassificava veredito de qualidade).
- **Resume replaneja quando não há o que recuperar** (`tasks.json` ausente ou
  vazio/sem tarefa aproveitável) em vez de FAILED silencioso.
- **Supervisor** (`main.py --supervise`): mastiga a fila, backoff após falhas,
  sai ocioso (`--idle-exit-secs`), sentinelas `runs/SUPERVISOR.pause|.stop`,
  watchdog por `events.jsonl` parado, snapshot `runs/supervisor-status.json`.
- **Memória de programa** (`<workspace>/memory/`): ADRs + lições (só com
  evidência run+arquivo) + índice de candidatos; `recall` alimenta o planner
  automaticamente (fail-open). Rotação de assento = chat NOVO com brief,
  nunca replay de incerto.
- **Marcos**: `provides/requires` em metadata → violação aborta cedo
  (`DEPENDENCY_ERROR`); `evaluate_milestone` + `check_budgets` por marco;
  evidência visual = integridade (sha256/PNG), julgamento é do operador.
- **CI** (`.github/workflows/ci.yml`, windows-latest): `tests/unit` +
  `tests/failure` + `tests/integration`. E2E/load fora (exigem Edge/Docker).

## 9. Evidência visual nos chats (pipeline de imagem)

- **Validador com 7.0 honesto exigiu render que o pipeline não entregava**
  (hero→status→rodapé visíveis em ordem): deadlock estrutural de toda tarefa
  UI. Correção ponta a ponta: captura headless do Edge
  (`orchestrator/visual_evidence.py`, só PNG válido e limitado, fail-closed) →
  `task.metadata["images"]` na revisão dos validadores (nota no prompt) →
  `ChatJob.images` (máx 2, data URLs, dentro do 1 MiB do relay) → paste via
  clipboard real no composer → `images_attached` confirmado por job (0 =
  falha visível). Limites: sem canal de imagem não há QA visual de UI.
- **Recarregar a extensão após update é obrigatório** (código novo não entra
  sozinho; `edge://extensions` → recarregar; confira 1.4.0). Pasta renomeada?
  Remova o registro antigo e carregue o novo caminho — path morto dá
  "File path cannot be resolved".
- **Headless Edge só escreve `--screenshot` em `.png`**: tmp de captura tem
  que terminar em `.png` (rc=0 sem arquivo, silencioso e traiçoeiro).
- Regra: evidência ausente é registrada (`visual_evidence.error`), nunca
  inventada; validador nunca alega ter visto o que não está nas imagens.

## 10. Morte silenciosa MV3 (lease vencia com a tab viva)

- **Sintoma:** jobs LEASED expiravam ~60s após pickup (lease 30s + sweep
  preguiçoso), deadline intacto, zero erros na extensão, resposta do modelo
  visível na tab mas nunca postada. 3x seguidas em tabs diferentes.
  **Janela elevada para 120s** (`LEASE_WINDOW_S`): suspensão MV3 cabe na
  folga sem expirar; morte real continua detectada via progresso vencido.
- **Causa:** Chrome suspende o service worker após ~30s sem eventos;
  `setInterval` de heartbeat morria junto; renovar+postar eram exclusivos do
  SW enquanto a espera longa rodava na tab. Alarme de 60s > lease de 30s não
  salvava. Prova forense: pickup rápido + 1 renew + silêncio; probe de 0.75s
  no mesmo worker; `lease_until-upd` negativo com `deadline-upd` positivo.
- **Correção:** WAIT fatiado 25s, job ativo em storage, pings tab→SW
  (acordam suspenso), resume sem reenvio com guarda anti-contaminação,
  fases via `/jobs/progress`, erros distintos `WORKER_LOST/DELIVERY_SLOW/
  QUEUE_TIMEOUT`, requeue 1x só de nunca-enviado (latch `sending`).
  Telemetria `hb/slices/cshb/rec` na string worker prova vida por job.
- **Regra:** contexto que renova lease não pode morar só em memória volátil;
  expiração precisa dizer morto vs lento; reenvio cego de incerto continua
  proibido (requeue só com prova de não-envio).

### Anti-simulação (regra dura, vale para todos os capítulos)

- Doubles de teste só injetam **falha real** (hang, atraso, erro) no código
    **real** de produção; jamais provam integração (`tests/support/fake_providers.py`).
  - `MockProvider` é o double aceito p/ lógica/orquestração — nunca como prova de
    modelo/browser real (matriz marca `BLOCKED_EXTERNAL` nesses casos).
  - Sem backend live: **falhar alto** (`BrowserSession.ask` levanta; provider live
    recus
...[truncated 911 chars]
