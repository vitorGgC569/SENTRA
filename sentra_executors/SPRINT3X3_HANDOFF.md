# EXEC-001 / SPRINT 3x3 — entrega e evidencias locais

Revisao: 2026-10-09. Propriedade exclusiva: `sentra_executors/`,
`tests/unit/test_sentra_executors_*.py`. NENHUMA alteracao no
ControlStore, sentra_runtime, sentra_interop, Canvas, apps do usuario
ou terceiros; nenhuma instalacao de infra nem binario desconhecido.

## 1. Windows UIA — lab read-only [E2E FIXTURE] / [REAL BLOQUEADO]

Implementado:
- `lab_discovery.discover_owned_tk_lab(pid, title)`: consulta
  FindWindowW com titulo exato SENTRA-UIA-LAB-*, GetWindowThreadProcessId,
  compara PID fornecido; sem enumerar desktop ou abrir app.
- `plan_read_only_tk_lab` e `MachineDeclaration.register`:
  cap `lab.read_window_title` e OperationRequest tipado, passando por
  ExecutorRegistry REAL + PolicyDecision REAL.
- `PywinautoUIABackend.run`: connect(process=PID), janela por handle,
  verifica pid/handle/titulo; evidencia contem SHA256 do titulo, nunca
  texto bruto. Novo teste usa backend real e simula apenas UIA/COM.
- `test_sentra_executors_sprint3x3.py`: discovery positiva,
  PID errado, HWND invalido, titulo fora do lab, registry policy,
  idempotencia, revogacao, janela alterada e fake pywinauto.
- `test_sentra_executors_uia_lab.py`: teste E2E real, cria e
  remove proprio processo Tk, sem aplicacoes pessoais; apenas quando
  SENTRA_UIA_LAB_RUN=1 E SENTRA_UIA_LAB_VM_CONFIRMED=1 e pywinauto
  importavel, Windows interativo de lab. Confirmacao do operador NAO
  substitui auditoria independente de isolamento. Sem isso, SKIP.

Lacuna P0: VM/usuario Windows de privilegio minimo verificado,
reuso de PID/HWND e limites COM/UIA; o backend acessa o desktop com
os privilegios do processo. Nao declarar sandbox Windows.

## 2. Daytona [E2E FIXTURE] / [REAL BLOQUEADO]

Implementado:
- `daytona_lifecycle.DaytonaSandboxLifecycle`: somente IDs
  explicitamente cadastrados; `discover_existing(id)`, `status(id)`,
  `provision(SandboxCreateSpec, operation_id, approval_ref)`,
  `cleanup(id)`. Todas as chamadas exigem PolicyDecision real,
  escopo imutavel e policy revalidada ao concluir IO. Manager e
  sincronico; callback de policy deve ser sincronico.
- Provisionamento **opt-in disabled by default**, exige tanto
  `allow_provision=True` da configuracao confiavel QUANTO
  `approve_provision(spec, approval_ref) is True` da autoridade.
  Apenas snapshot confiavel preexistente; cria parametros oficiais
  `CreateSandboxFromSnapshotParams(name, snapshot, public=False,
  network_block_all=True, network_allow_list=None, env_vars={},
  ephemeral=True)`. Nao cria imagem nem executa no host.
- Reusa `DaytonaSDKBackend`: `Daytona.get(sandbox_id)`,
  `sandbox.process.exec(command,timeout)` sob allowlist exata via
  `DaytonaExecutor` e ExecutorRegistry real; somente SHA256/tamanho
  de output/exit code nos resultados.
- Cleanup: apenas IDs criados por ESTE manager em vida de processo;
  `Daytona.delete(sandbox)` uma vez sob grant, repeticões retornam
  `DELETED`. Na falha/revogacao durante criacao ou delecao, estado
  **UNCERTAIN** e sem replay automatico (exige reconciliacao manual).
- `test_sentra_executors_sprint3x3.py` utiliza API fixture fiel
  `get/create(params)/delete(sandbox)/process.exec` integrada ao
  registry real. Testes negativos de politica, falta de aprovacao,
  sandbox nao gerenciada, politica revogada durante request, timeout,
  idempotencia e alteracao de spec.

Lacunas P0: gerenciar identificacao de sandbox remoto autorizada,
policy+approval persistentes no ControlStore, journal/fencing duravel,
atestar network/snapshot/tenant, verificar SDK/servico real com
credenciais e sandbox dedicada (nenhum disponivel neste ambiente).
Sem snapshot aprovado nao provisionar; sem plano de reconciliacao
nao ativar em producao. Logs/snapshot/raw credentials nunca expostos.

## 3. UFO + RPA Framework — subset seleto [E2E FIXTURE]

Implementado:
- `uia_workflow.ReadOnlyUIAWorkflow` recebe a
  MachineDeclaration declarativa e ExecutorRegistry real.
  `capabilities()` anuncia so bindings Windows com leitura permitida.
  `run(workflow_id, work_item_id, steps)` pre-valida todos os
  `ReadStep` (maximo 16; read_window_title/read_text somente) ANTES de
  qualquer efeito; nao permite invoke, shell, coordenadas ou selector
  nao allowlisted.
- Cada etapa gera OperationRequest com operation_id/idempotency_key
  estaveis `<workflow_id>:read:<index>` e submete AO REGISTRY real.
  PolicyDecision viva no registry e no adapter em toda etapa e retry.
  Revogacao DENIED, backend ambíguo UNCERTAIN, nunca inicia etapas
  posteriores quando nao SUCCEEDED.
- `StepReceipt` e `WorkflowReceipt`: estado, operation_id, digest
  SHA256 da evidencia (sem texto de UIA). Repetir mesmo plano nao
  repete side effect. Nao confundir com journal ControlStore duravel.
- Testes de sucesso 2 etapas, mesmo workflow reexecutado,
  grant revogado entre steps, revogado no backend, timeout UNCERTAIN,
  pre-validacao negativa, nao invoke/shell.

Codigo upstream lido (SO REFERÊNCIA; nenhuma linha copiada):
- UFO `third_party/ufo/ufo/automator/action_execution.py`,
  `ufo/automator/ui_control/controller.py` e `inspector.py`.
  Adotados SOMENTE conceitos de escopo de app, `is_enabled/is_visible`,
  selector e orquestracao, **NAO** dispatch dinâmico, `pyautogui` ou
  chamadas por coordenadas.
- RPA Framework `third_party/rpaframework/packages/main/src/RPA/Tasks.py`:
  conceito de grafo de tarefas/resultado auditavel; nao importar
  Graph do Robot, Graphviz ou scheduler. No SENTRA e implementacao
  propria de sequencia curta idempotente e grants por step.

Upstream licencas inspecionadas:
- UFO `third_party/ufo/LICENSE`: Microsoft MIT;
- RPA Framework `third_party/rpaframework/LICENSE`: Apache 2.0;
- Daytona `third_party/daytona/libs/sdk-python`: header Apache 2.0;
- pywinauto `third_party/pywinauto`: aviso copyright no fonte.
Nao houve vendoring nem traducao literal de codigo; atribuir
upstream ao redistribuir dependencias sob as licencas respectivas.

## Comando e matricula de aceite

Do raiz do repositorio, PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$suite = Get-ChildItem tests/unit -Filter 'test_sentra_executors_*.py' |
    ForEach-Object { $_.FullName }
python -B -m pytest -p no:cacheprovider -q -rs $suite
```

**Nunca** usar wildcard nao-expandido diretamente no pytest PowerShell.
Relatar numeros exatos somente da ultima execucao. E2E fixture = todo
caminho SENTRA registry+adapter+double externo, nao SDK remoto real.

Proximo gate externo: VM Windows isolada e pywinauto E2E de propria janela
Tk; SDK Daytona autenticado em sandbox disposable aprovada; gateway duravel
do ControlStore mantido estritamente sob propriedade do coordenador.


### Resultado observado nesta sessao (2026-10-09, Desktop Commander)

- Sete arquivos tests/unit/test_sentra_executors_*.py:
  `112 passed, 1 skipped in 1.31s`, exit code 0.
  O skip foi o Tk UIA real, por gate opt-in/VM nao confirmado.
- Smoke adicional com tests/unit/test_sentra_runtime_contracts.py e
  tests/unit/test_sentra_runtime_audit_chain.py:
  `21 passed in 0.22s`, exit code 0. Somente LEITURA do core.
- O novo tests/unit/test_sentra_executors_sprint3x3.py:
  `28 passed in 0.26s` (subconjunto incluido nos 112).
- Rodada UIA explicita: sem VM flag, 1 skip; com ambas flags de
  teste, 1 skip por `optional pywinauto absent`. Nenhum Tk criado.
- Python da maquina: `pywinauto=False`, `daytona=False`;
  nao houve chamadas Daytona remotas, provisionamento externo real,
  instalacao de pacotes/daemons, shells externos ou apps pessoais.
- Falta E2E externo real para os slices 1 e 2; slice 3 E2E fixture
  via registry real (dependencias externas substituidas por doubles).
- Arquivos proprios seguem untracked no git; nao foi efetuado commit,
  reset nem clean por EXEC-001.
