# Degradacao honesta do caminho Edge/extension

Status: implementado como matriz pura + relogio de budget + roteador de
fallback testado com fakes. Sem modelo local vivo neste ambiente, portanto
sem rota live ativada. Nenhuma chamada ao ChatGPT/Edge foi feita.

## 1. O que existe de verdade no ambiente

- Ollama `http://127.0.0.1:11434/api/version` e `/v1/models`: conexao
  recusada (WinError 10061). Verificado via GET stdlib com timeout de 3s,
  sem prompts, sem downloads.
- vLLM `http://127.0.0.1:8000/v1/models`: conexao recusada, mesmo metodo.
- Conclusao honesta: nao ha backend local alcancavel. A entrega 1 (fallback
  live para modelo local) e INVIAVEL aqui. Nao foi ativada nenhuma rota que
  finja capacidade. O codigo novo prova o mecanismo apenas com providers
  falsos injetando falha.

## 2. O que foi implementado

- `orchestrator/providers/degradation.py` (novo):
  decisao pura `decide(error, metadata)` -> retry/reconcile/abort/degrade_once,
  `is_dead_path(error)`, `DeadPathBudget` (teto 1..10, padrao 3),
  `mark_degraded(response, original_error)` e `VALIDATOR_RULE`.
- `orchestrator/providers/fallback_router.py` (novo):
  `DegradedFallbackRouter(primary, fallback, budget, allow_degrade)`.
  Tenta o primario uma vez; em erro de caminho-morto tenta o fallback UMA
  vez por chamada e marca `metadata {degraded: True, original_error}`.
  Nunca engole `CancelledError`. Teto de budget aborta rapido com
  `[DEAD_PATH_BUDGET]`.
- `orchestrator/providers/local_provider.py` (estendido com seguranca,
  comportamento de `execute` inalterado):
  `probe_local_endpoint()` (GET somente-leitura de `/api/version` e
  `/v1/models`, loopback apenas, sem prompts) +
  `LocalModelProvider.probe()` + `mark_as_degraded()`.
- `tests/unit/test_degradation.py` e `tests/unit/test_fallback_router.py`
  (novos): matriz, budget, marcacao honesta, sonda, roteador uma-vez,
  nunca-degradar, teto, cancelamento. Somente fakes; rede apenas para
  stub loopback em-processo e porta recusada.

## 3. Matriz de decisao (funcao pura)

| Erro (substring exata) | Acao | Motivo |
|---|---|---|
| `no extension connected` | `degrade_once` | Pre-submit em `browser/extension_transport.py`; nada foi enviado. Override explicito mesmo com metadata UNCERTAIN (classificacao generica enganosa). |
| `LEASE_LOST`, `LEASE_EXPIRED`, `TAB_STALE`, `TAB_ERROR` com metadata limpa | `degrade_once` | Caminho morto (tabs/lease). Uma tentativa local honesta no maximo. |
| Mesmo grupo acima com `delivery_state` UNCERTAIN/BLOCKED ou `retry_safe: False` | `reconcile` | Envio pode ja ter ocorrido; operador descarta via `orchestrator/reconcile.py`. Nunca replay, nunca degradar calado. |
| `DELIVERY_UNCERTAIN`, `SUBMISSION_UNCERTAIN`, `DELIVERY_EXPIRED` | `reconcile` | Incerteza externa; reconciliar, nao repetir. |
| `ACCOUNT_LIMIT`, `RATE_LIMIT`, `QUOTA_EXCEEDED`, `CONVERSATION_BLOCKED`, `PAIRING_REQUIRED`, `relay pairing required`, `RELAY_HTTP_401/403`, `forbidden origin`, `invalid host` | `abort` | Diagnostico/operador; retry ou degradar queimaria budget para falhar igual. |
| `TIMEOUT`, `TIMED OUT`, `IN_FLIGHT`, `SUBMIT_FAILED`, `STALE_CONVERSATION` (metadata limpa) | `retry` | Caminho transitorio do engine com backoff; nao e prova de caminho morto. |
| Conteudo/qualidade (`CONVERSATION_MISMATCH`, `PROMPT_MISMATCH`, `FILL_FAILED`, `CLEAR_FAILED`, `STALE_DRAFT`, `IMAGE_ERROR`, `IMAGE_VERSION`, `CONTEXT_BUDGET`, `DEPENDENCY_ERROR`, `MODEL_*`, `PATCH_SYNTAX`, `BUDGET_EXCEEDED`, `POLICY_ERROR`, vereditos de qualidade) e qualquer erro desconhecido | `abort` | Falha normal: vai para repair/validadores. Rotular fraco como forte e proibido. |

Lista exata de caminho-morto: `DEAD_PATH_MARKERS = ("no extension connected", "LEASE_LOST", "LEASE_EXPIRED", "TAB_STALE", "TAB_ERROR")`. NUNCA em erro de conteudo/qualidade.

## 4. Relogio de budget

`DeadPathBudget(max_consecutive_dead_path=3)`: incrementa a cada sinal bruto
de caminho-morto (`is_dead_path`), inclusive em sucesso degradado (o caminho
Edge continua morto); zera apenas em sucesso do primario. Em
`consecutive >= max`, o roteador retorna `[DEAD_PATH_BUDGET]` sem tentar o
fallback. Impede queima infinita em caminho morto.

## 5. Regra sugerida para validadores (spec, nao implementada aqui)

`VALIDATOR_RULE`: tratar `metadata.degraded is True` como evidencia fraca:
confianca maxima 0.5, score maximo 6.0, nunca satisfazer `minimum_approvals`
sozinho, exigir ao menos um teste objetivo passando e registrar
`original_error` no relatorio. Outra frente implementa nos validadores.

## 6. Chaves propostas (somente spec; `orchestrator/configuration.py` nao editado)

- `routing.degraded_fallback`: `null | "local"` (padrao `null`: preserva
  `fallback: null`, sem troca inesperada de provider/custo).
- `degradation.max_consecutive_dead_path`: int 1..10 (padrao 3).
- `degradation.allow_degraded_validators`: bool (padrao false ate a frente
  de validadores implementar a regra fraca).
- `local_model.enabled`: bool + `local_model.require_reachable`: bool
  (falhar visivel quando o operador optar por degradar sem backend vivo).

## 7. Resultado dos testes e o que ficou como spec

- `tests/unit -q`: 208 passed antes; apos a mudanca, ver saida do run.
- Ficou como spec (sem live): ativacao do fallback em `configuration.py`,
  tratamento de `degraded` nos validadores/engine e qualquer afinacao do
  teto por run live. O mecanismo esta pronto e testado com fakes; a rota
  live continua desligada ate existir Ollama/vLLM de verdade.
