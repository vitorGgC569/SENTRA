# EXEC-001 / GATE-3 — handoff para Canvas e ControlStore

Escopo deste arquivo: orientacao e evidencias; **nenhuma integracao em
producao foi ativada**. O modulo sentra_executors continua opt-in.
Contrato central observado em 2026-10-08, sem edicao do core por EXEC-001.

## Fluxo recomendado (marco posterior, sob propriedade do coordenador)

1. Uma task aprovada no Canvas identifica workspace, WorkItem, Run,
   operation_id, idempotency_key e Machine/capability. O usuario seleciona
   um recurso pre-registrado (PID/HWND e selector de laboratorio ou
   sandbox_id Daytona); **o navegador nunca envia permissoes soberanas**.
2. O ControlStore grava *antes do efeito* uma Operation duravel:
   sentra_mcp/services/durable.py oferece create_operation(run_id, owner,
   kind, idempotency_key, operation_id, cleanup_policy, initial_state).
   Reservar a identidade e checar estado anterior sob uma transacao; nao
   fabricar um novo idempotency_key em retry de resposta incerta.
3. O checker de autorizacao deve envolver o servico
   sentra_mcp/services/authorization.py: AuthorizationService.authorize
   retorna um dict, nao um PolicyDecision. Um wrapper de confianca,
   definido pelo coordenador, deve construir uma instancia verdadeira
   sentra_runtime.contracts.PolicyDecision e checar principal/scope,
   machine ownership, workspace, grant em vigor e revogacao. Nunca usar
   source='local_owner' implicitamente em operacoes de maquina externas.
   Cada operacao necessita da verificacao no registro E no executor.
4. sentra_runtime.executor.ExecutorRegistry.register(Machine, adapter),
   depois submit(OperationRequest). O mesmo PolicyChecker confiavel
   deve entrar no registry e em WindowsUIAExecutor/DaytonaExecutor.
   A acao nao pode ser disparada diretamente pelo Canvas/JavaScript.
   O ExecutorRegistry v1 recusa PolicyDecision.constraints nao-vazios:
   ampliar isso so em marco core coordenado, nunca contornar registry.
5. Mapear o OperationResult oficial para a Operation persistida pelo
   ControlStore (RUNNING, SUCCEEDED, FAILED, UNCERTAIN, CANCELLED)
   com update_operation(...). Um lease/resource_key e fencing_token
   validos devem ser verificados em todas as transicoes pertinentes;
   o adapter atual **nao** propaga/atesta fencing no momento do efeito.
   O projetor do Canvas deve mostrar UNCERTAIN como estado ambiguo
   com reconciliacao manual, nao como FAILED seguro de repetir.
6. sentra_canvas/task_runtime.py ja possui project() e fluxos de
   operacao canvas.agent_task. A integracao posterior criara operacoes
   de maquina com tipo dedicado, sem se apropriar da logica de chat.
   Exibir capabilities concedidas, estado da Machine, evidencia
   resumida, revogacao e motivo de negacao — nunca output bruto ou
   chaves de Daytona. Eventos retornam pelo ControlStore, nao via UIA
   ou SDK diretamente ao Canvas.

## Evidencia de autorizacao e ambiguidade

- Os testes em tests/unit/test_sentra_executors_registry.py usam o
  ExecutorRegistry REAL com PolicyDecision, OperationRequest e
  OperationResult REAIS. Apenas os efeitos externos sao fakes.
- tests/unit/test_sentra_executors_gate3.py cobre WindowsUIA **e**
  Daytona, atraves do Registry REAL: policy backend indisponivel,
  adapter sem policy, objetos que imitam PolicyDecision, revogacao
  entre avaliacoes, revogacao durante chamada, concorrencia no
  Registry e timeout. Side effects nao sao reenviados apos
  UNCERTAIN nem em duplicatas durante corrida.
- O backend pode continuar depois de timeout/cancelamento:
  UNCERTAIN e apenas relato conservador; nao cancela COM thread,
  processo remoto ou comando enviado para uma sandbox.
- A identidade/assinatura de repeticao e mantida na memoria por
  sentra_executors/_base.py. Leases e dedupe entre processos
  exigem integracao duravel. O registry core serializa submit()
  enquanto aguarda todo o efeito; revisar bloqueio entre maquinas.

## CORRIGIDO PELO COORDENADOR NO CORE (GATE-5) — replay de request mutavel

O contrato OperationRequest aceita arguments com dict mutavel. O
ExecutorRegistry atualizado cria **fingerprint SHA-256 de payload JSON
canonico e copia independente** na admissao, verificando mudancas de
arguments antes do efeito e em replays. Quando o mesmo caller altera o
dict apos um resultado SUCCEEDED, o registry rejeita com
DuplicateOperation sem novo efeito e sem retornar resultado antigo.

A prova tests/unit/test_sentra_executors_gate3.py::
test_gate3_registry_should_reject_mutation_of_submitted_arguments
permanece ativa e agora **passa sem xfail**. A mudanca de seguranca
foi implementada pelo coordenador em sentra_runtime/executor.py;
EXEC-001 nao editou o core. Re-autorizacao de submit repetido segue
obrigatoria; grants revogados geram AuthorizationRequired.

**Ainda nao resolvido:** fencing no efeito, deduplicacao e historico
duravel compartilhado entre processos/maquinas, reconciliacao apos
restart e isolamento real da UIA Windows.

## Windows UIA — evidencia e seguranca

- Windows UIA por PID, HWND, titulo e automacao ID **nao isola
  o sistema operacional**, nao equivale a AppContainer, VM,
  usuario reduzido ou grant Windows. Reuso de PID/HWND, UIA de
  outro provedor e TOCTOU entre checagem/efeito exigem defesa.
- Nao executar tarefas nao confiaveis como usuario pessoal.
  Exigir usuario baixo privilegio ou VM descartavel antes de
  promover para automacao real, com allowlist de processos e
  aprovacao de efeito por WorkItem.
- Prova real read-only definida em
  tests/unit/test_sentra_executors_uia_lab.py; o teste cria
  apenas seu proprio Tk, valida PID/HWND, le o titulo e encerra
  o processo. Requer opt-in SENTRA_UIA_LAB_RUN=1.
- Verificacao nesta maquina: Windows session 1, tkinter
  disponivel, mas pywinauto AUSENTE; com opt-in o teste
  ficou SKIPPED [1]: optional pywinauto absent.
  Nenhuma janela pessoal foi inspecionada.

## Daytona — evidencia e ausencia de E2E

- O SDK e opcional e nao foi instalado neste gate.
- Verificacao local nao-invasiva: zero processos/servicos
  Daytona, CLI nao encontrado, pacote SDK nao importavel;
  docker ps --filter name=daytona retornou zero nomes,
  com exit_code=0. Isso **nao prova** inexistencia de um
  servico remoto; nenhum sandbox remoto foi consultado.
- Fakes validam forma de chamadas SDK, checks de
  sandbox privado/rede bloqueada e comportamento de
  autorizar/revogar/reconciliar. Nao comprovam networking,
  isolamento real, atestacao, snapshot, API autenticada ou
  teardown. Sem identificador de sandbox autorizado e
  infraestrutura de teste, E2E Daytona permanece BLOQUEADO.
- Nunca instalar daemon, ligar porta publica ou acessar
  sandbox de terceiros sem autorizacao explicita.

## Gates para o proximo responsavel

- [x] Corrigido pelo coordenador: fingerprint + snapshot canonico no registry (GATE-5).
- [ ] Conectar politica duravel a um checker tipado unico.
- [ ] Admitir operacoes Machine no ControlStore, com fencing.
- [ ] Definir reconciliacao por operacao/sandbox apos restart
      (sem repetir side effect).
- [ ] Isolar Windows UIA por VM/usuario restrito.
- [ ] Executar Tk lab UIA real quando pywinauto estiver
      instalado *no ambiente de laboratorio*.
- [ ] Validar Daytona real somente em sandbox autorizada.
- [ ] Integrar projeccao Canvas/WorkItem com event log,
      estados UNCERTAIN e evidencia sem segredos.

Execucao local e status sao registrados pelos resultados do
pytest; nenhuma alteracao foi feita fora da propriedade EXEC-001.
