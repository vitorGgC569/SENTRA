# SENTRA OS · EXEC-001 · integração central real · 2026-10-09

## Status operacional e fronteira de propriedade

Implementação consumível por host: `sentra_executors/central_integration.py`
(`CentralExecutorFactory`, `CentralRegisteredMachine`) e exportação
em `sentra_executors/__init__.py`. **NÃO** se trata de mais um executor;
a factory registra e governa os executores previamente implementados.

**Executores testados:** `BrowserLabExecutor` read-only, URL numérica
loopback exata. UIA Tk somente após laboratório VM isolado; nenhum app
pessoal executado, Playwright/WinHCS/runsc não instalados.

O host do Canvas `sentra_canvas/service.py::Canvas` /
`task_runtime.py::TaskRuntime` e seus contratos foram LIDOS e testados
em SQLite temporário. A integração abaixo **não foi inserida diretamente
no dispatcher do Canvas** pois a pasta pertence ao coordenador. A
factory **não se auto-anexa** à UI nativa nem anuncia Machine ao Canvas
sem que o host central invoque a integração explicitamente.

## Fatia 1 — Registro Machine/Capability pelo centro [REAL SQLITE/REGISTRY]

A factory é criada com o `ControlPlaneService` REAL,
owner autenticado e principal agente já conhecido do control plane.
`BoundWorkItemPolicy` usa o **MESMO**
`ControlPlaneService.authorization` e `.governance`, que por
sua vez usam o SQLite protegido do ControlStore; `ExecutorRegistry`
é o registro real de `sentra_runtime.executor`.

`register_lab_browser(machine_id, BrowserReadBinding, backend)`
registra `Machine` (owner_principal_id do agente), Capability
e adapter existente. `register_inventory(MachineDeclaration)`
também registra **descoberta somente** de adapters reais existentes,
incluindo WindowsUIAExecutor e DaytonaExecutor, com a policy do
Registry substituída pela policy central (não aceita a policy anterior
do caller). `discover(machine_id)` delega ao protocolo ExecutorAdapter
real. O despacho pela factory é exclusivamente browser read-only;
UIA/Daytona inventariados não ganham dispatch.
Não realiza grant de privilégio, nem altera ControlStore, nem inicia
navegador. Backend confiável deve ser injetado explicitamente; sem
backend, fail-closed.

Testes `test_sentra_executors_central_integration.py` exercitam
`control.durable.create_run`, `control.ensure_agent`,
`control.create_work_item`, `transition_work_item`,
`start_work_item_execution`, `AuthorizationService.authorize`
via `BoundWorkItemPolicy` e `ExecutorRegistry` com bases SQLite
temporárias; sem grant o Registry nega. Também provam que
a factory sem autoridade durável não permite disparo mesmo com grant.

## Fatia 2 — Run/WorkItem/Grant/Operation -> executor read-only

Fluxo do laboratório **testado**:
1. Autoridade do ControlPlane cria Run e WorkItem, assina agent_id e
   `required_capabilities`; WorkItem torna-se RUNNING.
2. Somente **autoridade de servidor** chama
   `AuthorizationService.grant(owner,principal_type=agent,...)`;
   cliente não recebe API de alteração de grant.
3. A factory valida Run RUNNING, WorkItem RUNNING, mesmo run_id/owner,
   assignee e capability; valida o grant vivo por
   `BoundWorkItemPolicy`, sem inferir permissão de `request.arguments`.
4. `DurableOperationGate` reserva fingerprint SHA-256 integral e fencing
   **somente em autoridade injetada** compatível com o contrato do
   coordenador `sentra_runtime/durable_admission.py`;
   `ContextVar` de fingerprint arma o `ExecutorRegistry` SOMENTE
   durante `effect` admitido, bloqueando chamadas diretas normais
   `hub.registry.submit` (mesmo com grant ativo). Isso NÃO é
   isolamento contra código Python hostil no mesmo processo; o host
   deve manter a factory dentro de processo confiável.
5. Executor `BrowserLabExecutor` recebe apenas método
   `read_page`, URL allowlisted loopback `127.0.0.1`, via backend
   explicitamente injetado, devolvendo **SHA256 e tamanho**.
6. No teste, `SQLiteAdmissionTestOnly` reserva o full intent
   em SQLite temporário e projeta `DurableRunService.create_operation`
   com `work_item_id`, `capability_id` e `intent_sha256` no
   progress; depois publica status e resultado via
   `DurableRunService.update_operation`. Teste verifica `op_id`,
   `run_id`, WorkItem e SHA256. Chamada HTTP GET foi feita num
   **subprocesso Python real descartável**, bound em 127.0.0.1,
   criado exclusivamente pelo próprio teste.
7. Revoke via `ControlPlaneService.authorization.revoke` impede
   nova submissão ou replay; revogação durante efeito torna
   conclusão UNCERTAIN, não sucesso falso.

**Limite NÃO negociável**: a classe
`SQLiteAdmissionTestOnly` reside **exclusivamente nos testes**.
Ela NÃO é um ControlStore de produção; sua projeção entre SQLite
fixture e Legacy DurableRunService NÃO é atômica. Nunca vender como
reserva/fencing real do produto. Nenhuma classe SQLite de autoridade
nova foi adicionada ao pacote `sentra_executors`.

O `DurableRunService.create_operation` atual não grava fingerprint
integral junto da reserva, por isso **NÃO É** autoridade adequada a
`DurableOperationGate`. Sem uma
`DurableIntentAuthority(reserve_intent,fence_active,record_result)`
IMPLEMENTADA PELO COORDENADOR, `CentralExecutorFactory.submit`
recusa a execução com `DurableAdmissionUnavailable`; se não houver
grant, recusa antes com `AuthorizationRequired`.
Em produção, o adaptador também deve garantir fencing no exato
ponto do efeito (principalmente para efeitos remotos). O teste
loopback read-only demonstra protocolo, NÃO distribuição segura.

## Fatia 3 — Reconexão, cancel, cleanup, UNCERTAIN e bypass

Tests exercem, com **as mesmas APIs centrais reais** e SQLite temporário:
- Segunda factory/ExecutorRegistry e novos `DurableRunService`,
  `ControlPlaneService` abertos no mesmo state_root; operação reservada
  aparece EXISTS -> UNCERTAIN, sem segundo HTTP GET.
- Cancel do ControlPlane antes do dispatch via
  `DurableRunService.request_cancel` muda operação para
  CANCEL_REQUESTED, `fence_active` recusa efeito, sem GET.
- Perda de fence da autoridade de teste bloqueia efeito.
  Acknowledgement perdido APÓS GET retorna UNCERTAIN;
  replay posterior não executa novo GET.
- Alterar URL/intent com mesmo operation_id colide no fingerprint
  persistido do teste e dispara DuplicateOperation (no re-exec).
- Chamada DIRETA a `ExecutorRegistry.submit` mesmo com grant
  ativo é recusada por ContextVar de dispatch. Não se concede
  autoridade por parâmetro `grant=True/allowed=True` no pedido.
- `cleanup` de read-only valida grant ativo e vínculo
  WorkItem/Operation antes de invocar noop de limpeza local;
  não é deleção remota nem encerra apps de usuário.
- Nenhum processo do usuário é lido; único processo lançado
  explicitamente pelo teste é servidor HTTP em `127.0.0.1`.

## Contrato de host / handoff para COORDENADOR (P0)

Somente a **frente coordenadora**, sem mudanças por EXEC-001, deve:
1. Instanciar `CentralExecutorFactory(control=ControlPlaneService
   real, owner=owner_autenticado, agent_id=agent_de_run,
   durable_intent_authority=ControlStoreBridgeReal)`.
2. Registrar uma Machine e seu backend de laboratório aprovado após
   definição de configuração e consentimento pelo host.
3. Invocar `factory.submit(run_id=...,
   request=factory.request(...))` no ponto de despacho autorizado do
   Canvas/TaskRuntime ou ControlPlane, não em JS não autenticado.
4. Implementar no **ControlStore central** a reserva atômica
   de fingerprint+lease/fence e recuperação após crash, com teste
   multi-processo; garantir fencing no ponto do efeito e
   comprovar comportamento diante de cancel/timeout.
5. Substituir a `SQLiteAdmissionTestOnly` dos testes pelo provider
   **autoritativo**. Até lá, nenhuma integração é promovida a release.
6. Resolver semanticamente que a Machine anunciada ao Registry tem
   `owner_principal_id=agent_id`, ao passo que a Gate durável do
   coordenador compara `machine.owner_principal_id=owner`.
   A factory constrói uma Machine *de escopo de admissão*
   com mesmo machine_id/capabilities, mas owner diferente;
   revisar contrato para não divergir identidades em produção.

Nao editar sentra_canvas, sentra_mcp, sentra_runtime, segredos
ou instalar runsc/HCS/Playwright nesta frente. Sem reset/clean.


## Aceite final executado com Desktop Commander (2026-10-09)

```powershell
Set-Location 'C:\Users\vitor\OneDrive\Desktop\SENTRA'
$env:PYTHONDONTWRITEBYTECODE='1'
$tests=@(Get-ChildItem tests/unit -Filter 'test_sentra_executors_*.py' -File |
    Sort-Object Name | ForEach-Object {$_.FullName})
python -B -m pytest -p no:cacheprovider -q -rs -rx $tests
python -B -m pytest -p no:cacheprovider -q -rs `
    tests/unit/test_sentra_runtime_authority_bridge.py `
    tests/unit/test_sentra_runtime_durable_admission.py `
    tests/unit/test_governance_control_plane.py
```

- **14 arquivos da frente executors**: `229 passed, 4 skipped
  in 12.16s`; `EXECUTOR_EXIT=0`.
- **Testes novos de central integration**:
  `15 passed in 6.02s`, `CENTRAL_FOCUSED_EXIT=0`.
  Esses 15 ja estao incluidos nos 229, NAO somar duas vezes.
- **Smoke central de tres arquivos ja existentes**:
  `28 passed in 3.56s`, `CENTRAL_SMOKE_EXIT=0`.
- **Quatro skips herdados de rounds anteriores**: UIA Tk real,
  Windows identity Tk real, Playwright real sem VM isolada, e
  symlink real de gVisor negado pelo Windows.
- **Subprocesso REAL** criado no teste: Python stdlib
  `http.server` com bind 127.0.0.1, porta efemera e rota
  `/read`. O servidor foi encerrado pelo teste.
- Sem aplicativo pessoal aberto, sem Daytona/gVisor/HCS remoto
  real, sem alterar grants de usuario: grants nos testes sao
  criados pelo **objeto ControlPlaneService** em temp SQLite.
- O smoke Canvas instancia `Canvas` e `TaskRuntime` reais
  em state_dir temporario. Ele demonstra que o host e seu
  DurableRunService funcionam, nao que o dispatcher do Canvas
  atual importou ou chamou a factory.
- Estado Git: novas entregas continuam **untracked**;
  sem commits, sem reset/clean. Nenhum diretorio de outras
  frentes foi editado por EXEC-001.

**VEREDITO: integração de biblioteca e caminho central com SQLite/
subprocesso comprovados em laboratório; ligação do dispatcher Canvas
e atomicidade/fencing de produção pendentes da frente coordenadora.**
