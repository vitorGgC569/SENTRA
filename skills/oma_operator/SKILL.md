# Skill: oma_operator — Como orquestrar e usar o SENTRA

> Runbook do operador. Princípio: **LLMs propõem, software decide.**
> Caminho live: `main.py` (engine) → `BrowserExtensionProvider` → relay
> (`http://127.0.0.1:8765`) → `edge_extension/` → Edge real não-privado
> (`chatgpt.com`). Núcleo determinístico: estados, timeouts, quorum, gates.
> Fonte de verdade da especificação: `docs/OMA_Orquestrador_Multiagente.md`.
> Armadilhas já vencidas: `docs/traps.md` (leitura obrigatória).
> Baixou o projeto agora? Comece na seção 0 e siga na ordem.

---

## 0. Tutorial do zero (baixei o projeto agora)

### 0.1 O que é e o que você precisa

O OMA orquestra agentes de IA para **escrever código de verdade**: planeja um
DAG de tarefas, cada agente implementa sua fatia como patch, tudo roda em
testes reais, críticos avaliam (nota 0–10, barra 9.5) e o reparo tem limites.
Nada é aprovado por "parecer bom" — só por teste verde + quorum.

Precisa de: **Windows 10/11** (o lock de workspace usa `msvcrt`),
**Python 3.11+**, **Microsoft Edge** com você **logado no site de chat**
(operação real usa seu login, modo NÃO-privado), ~4GB livres. Docker Desktop
opcional (só p/ validar candidatos em container Linux). Avisos honestos:
automatizar UI de chat pode violar Termos do serviço (use com sites que
permitam); o provedor conta **chats criados** no rate limit — cada missão
consome conversas reais da sua conta.

### 0.2 Instalar

```powershell
cd <pasta-do-projeto>   # a que contém main.py, config.yaml, edge_extension/
python --version         # 3.11+
python -m pip install -r requirements.txt   # playwright, openai, pydantic, pyyaml, gitpython, pytest
```

Pastas que importam: `main.py` (CLI única), `config.yaml` (tudo configurável),
`orchestrator/` (engine), `edge_extension/` (ponte do Edge), `native_bridge/`
(relay), `dashboard/` (acompanhamento), `runs/` + `.oma/` (persistência),
`skills/oma_operator/` (este runbook), `docs/traps.md` (armadilhas).

### 0.3 Primeira execução: demo offline (sem Edge, sem custo)

```powershell
python -B main.py --demo
```

Cria `.oma/demo-*`, implementa um fatorial com **modelos roteirizados** e roda
testes reais. Prova que a máquina funciona (filesystem, gateway, testes).
Demo **não** prova inteligência nem Edge — é só fumaça local.

### 0.4 Subir o caminho live (relay + extensão)

```powershell
# Terminal 1 (deixe aberto): relay autenticado e persistente
python -B main.py --relay
# Anote o caminho do token de pareamento (ex.: .oma/relay-token)
```

No Edge, com sua conta logada no site de chat:
1. `edge://extensions` → modo desenvolvedor → **Carregar sem compactação** →
   pasta `edge_extension/`.
2. Detalhes da extensão → **Opções da extensão** → cole o conteúdo de
   `.oma/relay-token` no campo Token → marque **Ativar** → salve.
   (Token é segredo: nunca cole em chat nenhum.)
3. A extensão cria **duas tabs próprias** e começa o polling em
   `http://127.0.0.1:8765`. Ela **não** adota suas tabs pessoais.
4. Recarregue a extensão (`edge://extensions` → recarregar) sempre que
   atualizar os arquivos dela. Versão atual: `1.5.0` (paste de imagem + anti-morte-silenciosa)
   (`edge_extension/manifest.json`); doctor recusa se divergir.

```powershell
# Terminal 2: diagnóstico (não envia nada, não custa nada)
python -B main.py --doctor
# esperar ok=true, relay autenticado, workers_online com TAB-*
```

Prova de fogo (cria **1 conversa real**, gasta quota):
```powershell
$env:OMA_LIVE_EXTENSION = '1'
python -B -m pytest tests/e2e/test_extension_live.py -s
```

Um relay por porta: se `/health` já responde, **não** suba outro
(dual-bind = duas filas invisíveis uma à outra).

### 0.5 Ver tudo no dashboard

```powershell
Start-Process python -ArgumentList '-B','dashboard/server.py','--port','8899' `
  -WorkingDirectory '<pasta-do-projeto>'
# abrir http://127.0.0.1:8899/
```

Runs → chats (link "abrir ↗" p/ a conversa real) → prompts/respostas.
Somente leitura. Para incluir outros workspaces (ex.: pasta do seu jogo),
use `--roots <dir1>,<dir2>` e reinicie (matando só processos cuja
`CommandLine` contenha `dashboard/server.py` — o Python aqui chama-se
`python3.12` no gerenciador).

### 0.6 Primeira missão (pequena de propósito!)

```powershell
python -B main.py --job-id primeira-run --workspace '<pasta-vazia-ou-projeto>' `
  --provider extension --reviewer extension --workers 1 `
  --prompt 'Corrigir a função X preservando a API e adicionar testes de borda' `
  --trust-workspace
```

Comece com **1 tarefa pequena** (1 arquivo + 1 teste). Missões gigantes
falham por motivos mecânicos, não por falta de inteligência:
**teto de 20000 caracteres por mensagem** — cada tarefa deve entregar no
máximo ~250 linhas + teste (detalhes na seção 3.1). Acompanhe pelo dashboard;
`--status` e `--reconcile` mostram estado sem enviar nada (seção 4).

### 0.7 Entender o resultado

- `Tarefas: N/M` + `Contexto para a central` + `Patch` no final = resumo.
- `<workspace>/runs/<job-id>/handoff.md` — o que foi feito e pendências.
- `candidate.patch` — o diff real. **Leia antes de qualquer coisa.**
- Promover (aplicar de verdade) é explícito e separado:
  `python -B main.py --promote <job-id> --workspace <dir> [--sandbox docker]`
  (repete testes, confere hashes; `--allow-protected` só com motivo).
- Falhou? Seção 5 (tabela de recuperação) + `docs/traps.md`.

### 0.8 Alternativa sem Edge: modelo local

Aponte `local_model.base_url/model_name` no `config.yaml` p/ seu Ollama/vLLM
e use `--provider local --reviewer local`. Sem chats, sem quota — qualidade
depende do seu modelo. `--demo`/`--mock` nunca representam execução live.

### 0.9 Como a engine trabalha (o ciclo — sim, ela trabalha)

A engine é determinística: o software decide, os modelos só propõem. Todo
ciclo, para cada tarefa do DAG:

1. **Plan** — o master decompõe o `--prompt` em tarefas (ou carrega as
   persistidas no `--resume`). Vira `tasks.json` + assentos fixos.
2. **Dispatch** — a fila libera tarefas sem dependência pendente
   (`--workers` em paralelo, envios serializados nos 5 assentos).
3. **Propose** — o executor pede contexto via diretivas `[[R|…]]`/`[[T|…]]`,
   o gateway responde, e ele devolve **patch unificado** (nunca shell livre).
4. **Verify** — o patch aplica numa cópia isolada (`work-*`) e roda os
   testes de verdade (`[[TEST|all]]`, Docker ou host). Sem teste verde,
   não há aprovação possível.
5. **Quorum** — 3 validadores (lógica, requisitos, adversarial) dão nota
   0–10; libera com mínimo ≥ 9.5 e 2 aprovações. Crítica bloqueia.
6. **Repair** — abaixo da barra, o executor recebe a crítica e tenta de
   novo (até 15 rounds, anti-estagnação aos 5 idênticos). Teto de 20k
   caracteres por mensagem: fatias pequenas ou o repair morre.
7. **Integrate** — tarefas prontas viram `candidate.patch` + testes finais;
   sai `handoff.md`/`handoff.json` para a central. **Promoção é manual**
   (`--promote`), nunca automática.

Prova de que trabalha (registrado, não prometido): código real com testes
verdes e quorum 9.7 em runs live; gate barrando 7.0 com críticas corretas;
falhas mecânicas abortando alto em vez de fingir sucesso (`docs/traps.md`).

---

## 1. Pre-flight (antes de qualquer missão live)

```powershell
# 1a. Relay saudável + workers reais?
Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 15
# esperar: ok=true, workers_online com 1-2 TAB-*, queued=0, leased=0

# 1b. Sonda de quota (custo zero). UNKNOWN = inconclusivo, não é luz verde nem vermelha.
python -B scripts/cap_watch.py --once

# 1c. Doctor (conexão, sem chamar modelos)
python -B main.py --doctor
```

Não suba segundo relay na mesma porta (dual-bind: cada um tem sua fila;
sonde `/health` antes). Processo Python aqui chama-se **`python3.12`**
(não `python.exe`) — filtre por `CommandLine`, nunca mate o
`main.py --relay` nem o `http.server` de preview de terceiros.

---

## 2. Dashboard de acompanhamento

```powershell
Start-Process python -ArgumentList '-B','dashboard/server.py','--port','8899','--roots',(
  '<pasta-do-SENTRA>\runs,' +
  '<pasta-do-SENTRA>\.oma'
) -WorkingDirectory '<pasta-do-SENTRA>'
# Acrescente outros workspaces separados por vírgula se a missão usar outro diretório.
```

- Abrir `http://127.0.0.1:8899/` — console estilo admin (sidebar + topbar),
  somente leitura, sem envios. Visões:
  - **Visão geral** — cards (runs, projetos, failed, chats quebrados) + tabela
    por projeto com botão de resumo.
  - **Runs** — tabela com status/tarefas + detalhe de chats (link "abrir ↗").
  - **Conversas** — todos os chats com filtro por estado.
  - **Falhas** — assentos quebrados (NOT_SENT/UNCERTAIN/BLOCKED), entregas
    FAILED com erro, tarefas FAILED. Diagnóstico local; reconciliar é no
    `main.py --reconcile` (seção 5).
  - **Resumos** — documento de contexto em markdown **gerado localmente**
    dos registros (objetivo, tarefas, chats+URLs, validações, falhas,
    eventos), por projeto ou por run, com copiar/baixar `.md`. Nada é
    enviado aos chats; é contexto do operador.
- APIs: `/api/overview`, `/api/conversations?state=`, `/api/failures`,
  `/api/summary?run_id=|project=`, `/api/responses`, `/api/relay/jobs`.
- **Um único dashboard por porta.** Se reiniciar, mate SOMENTE os processos
  cuja `CommandLine` contenha `dashboard/server.py` e confira que restou um
  (processos antigos grudados na porta servem versão velha em silêncio).
- Raízes novas (`--roots`) exigem reinício; o diretório precisa existir.
- Evidência de QA visual do operador: `<workspace>/runs/<RUN>/evidence/`
  (screenshots + `visual-qa.md` com achados em texto).

## 3. Lançar uma missão (engine, sem alterar fonte)

```powershell
$prompt = '...objetivo + direta...'
$qprompt = '"' + $prompt + '"'   # Start-Process NÃO cita espaços sozinho
Start-Process python -ArgumentList '-B','main.py','--job-id','RUN-X-001',
  '--prompt',$qprompt,'--workspace','<dir-do-projeto>','--provider','extension',
  '--reviewer','extension','--workers','3','--max-rounds','40','--trust-workspace' `
  -WorkingDirectory '<pasta-do-SENTRA>' `
  -RedirectStandardOutput '<dir-do-projeto>\launch-RUN-X-001.log' `
  -RedirectStandardError '<dir-do-projeto>\launch-RUN-X-001.err.log'
```

Flags: `--workers 1..8` (concorrência de tarefas, não nº de agentes);
`--max-rounds` = teto de tentativas (10 tarefas + reparos → ~40);
`--trust-workspace` exigido p/ testes no host (backend `host` no `config.yaml`).
`--job-id` deve casar `[A-Za-z0-9][A-Za-z0-9_-]{0,79}`.

### 3.1 Escrever o --prompt (o que decide o sucesso)

- Peça **EXATAMENTE N tarefas** ("Decomponha em EXATAMENTE 10 tarefas"),
  cada uma **fatia completa com seu próprio teste executável**, em DAG
  (fundação primeiro, smoke final por último).
- **Restrição dura — teto de 20000 caracteres por mensagem** (hardcoded em
  `orchestrator/providers/extension_provider.py` e `native_bridge/protocol.py`,
  sem knob de config): cada tarefa entrega **NO MÁXIMO 1 arquivo de ~250
  linhas + seu teste**, senão o repair estoura o teto e a run morre (caso
  real em run live de build).
- Trave decisões de design/críticas anteriores no prompt ("seguir sem reabrir
  debate") — é assim que feedback textual do operador entra nos agentes.
- Master planeja em 1 chat; confira `tasks.json` (N tarefas, DAG coerente).

### 3.2 Comandos curtos (o shell derruba chamadas longas)

O harness mata chamadas de terminal longas (`Unknown: ChildProcess.kill`),
sem erro aproveitável — e o processo destacado pode ou não ter nascido.
Defensivo, sempre:
- `--prompt` longo NUNCA inline: grave em `<workspace>/mission-<RUN>.txt`
  (ferramenta de escrita) e lance lendo do arquivo:
  `python -B -c "import subprocess; p=open('<arq>').read(); …;
  subprocess.Popen(['python','-B','main.py','--job-id','<RUN>','--prompt',p,…],
  cwd='<repo>',stdout=l,stderr=e)"` (argv em lista = sem problema de quoting).
- Uma chamada = um passo: lançar / esperar (`Start-Sleep` curto, só poll) /
  verificar (log, processo, run dir) em chamadas separadas.
- Após qualquer queda: verificar o estado real antes de relançar
  (nunca presumir que nasceu nem que morreu).

## 4. Acompanhar e forense

- `…/runs/<RUN>/tasks.json` — status por tarefa (`RUNNING`, `repairs=`).
- `…/conversations.json` — assentos fixos (master, executor, 3 validadores):
  `CONFIRMED` (ok), `IN_FLIGHT`, `NOT_SENT`, `UNCERTAIN` (intenção incerta),
  `BLOCKED`.
- `…/validations.json` — scores 0-10 por validador; release bar 9.5
  (`min_release_score`, `config.yaml`). Gate abaixo da barra = rejeição
  correta, não bug.
- `…/events.jsonl` — verdade final (`QUALITY_GATE_FAILED`,
  `REPAIR_REQUESTED`, `TASK_FAILED`, `RUN_FAILED` + motivo).
- `…/handoff.json` + `handoff.md` — contexto p/ a central; `candidate.patch`.
- `python -B main.py --status --job-id <RUN> --workspace <dir>`
- `python -B main.py --reconcile --job-id <RUN> --workspace <dir>` lista
  assentos travados **sem enviar nada**; `--drop-seat '<RUN>:<papel>'`
  descarta intenção incerta (o próximo envio abre chat novo, **sem replay**).

## 5. Recuperação (protocolo)

| Situação | Ação |
|---|---|
| `STALE_CONVERSATION` (id repetido após new_chat) | Guarda agiu certo (sem replay). **Operador no Edge:** abrir novo chat/recarregar a aba presa. Depois lançar **run nova** (novo `--job-id`), com o objetivo reaproveitado byte-idêntico do `run.json`. |
| Assento `UNCERTAIN`/`BLOCKED` | `--reconcile` (+ `--drop-seat` se `relay_jobs: []`). |
| `--resume` | Com `tasks.json` aproveitável, recupera; **vazio/ausente/sem tarefa útil → replaneja do objetivo** (veneno antigo corrigido). Objective deve ser idêntico ao persistido. Falha isola o galho: status `PARTIAL`, só dependente inalcançável cai (`DEPENDENCY_ERROR`). |
| Repair em loop / estagnação | `stagnation_limit=5` rejeições idênticas escala p/ STAGNANT. Intervenção do operador é **texto no próximo --prompt**, nunca injeção no chat. |
| Quota/rate-limit | Conta **chats criados**, não mensagens. `SUBMIT_FAILED`/`send_available=False` sem banner explícito = UNKNOWN, não prova de teto. Falha alto e visível; não force. |

## 6. Regras duras

- `MockProvider`/doubles: só injetam **falha** no código real; **nunca**
  provam integração. Prova live = URL de conversa + `versions.json` casando
  (`sw`/`cs`) + `workers_online`.
- Screenshots p/ agentes: **canal de imagem ativo** (v1.4.0+). A engine
  renderiza alvos `.html` do candidato (Edge headless) em
  `runs/<RUN>/evidence/` e anexa nas revisões dos validadores (máx 2/job,
  confirmação `images_attached` por job no `/api/relay/jobs`; 0 = paste
  falhou, visível). Validador cita o que viu nas imagens.
- **Após qualquer update da extensão, RECARREGUE em `edge://extensions`**
  e confira a versão. Pasta do projeto renomeada? Remova o registro velho
  e carregue o novo caminho (path morto = "File path cannot be resolved").
- QA visual do operador continua valendo p/ o que agente não cobre:
  capture, inspecione, registre `evidence/visual-qa.md`.
- Validação local quem decide é teste executado (`[[TEST|all]]`), não score
  de LLM. Quorum: 3 validadores, mínimo 2 aprovações, crítica bloqueia.
- Sem commit/push/entrega automática: handoff exige promoção explícita
  (`--promote` + `--allow-protected` p/ componentes protegidos).
- Não modificar fonte da engine sem autorização explícita do operador.
  Usar = CLI + config + dados da run. Ler fonte p/ forense é permitido.

## 7. Mapa rápido

- Engine/estados: `orchestrator/engine.py`, `state_machine.py`, `queue.py`
- Assentos fixos: `orchestrator/conversation_pool.py` (`max_seats: 5`)
- Provider live: `orchestrator/providers/extension_provider.py`,
  `browser/tab_pool.py`, `browser/extension_transport.py`
- Portas: relay `8765`, dashboard `8899` (um processo por porta; confira antes)
- Workspaces: `runs/` (runs da engine), `.oma/` (pilotos), `dashboard/` (observabilidade)

## 8. Programa (longa duração)

- **Supervisor:** `python -B main.py --supervise --workspace <dir>
  [--max-iterations N] [--idle-exit-secs 300]` mastiga a fila sozinho;
  `runs/SUPERVISOR.pause|.stop` controlam; estado em
  `runs/supervisor-status.json`.
- **Memória:** `<workspace>/memory/` (ADRs, lições com evidência, índice de
  candidatos) alimenta o planner sozinha; rotação de assento = chat novo com
  brief, nunca replay.
- **Marcos:** declare `provides/requires` em metadata das tarefas (violação
  aborta cedo); `evaluate_milestone` + `check_budgets` por marco; evidência
  visual = integridade, julgamento é seu.
- **CI:** push roda `tests/unit` + `tests/failure` + `tests/integration` no
  Windows; console tem a visão **Programa** (velocidade, taxonomia de falhas,
  flakiness).
