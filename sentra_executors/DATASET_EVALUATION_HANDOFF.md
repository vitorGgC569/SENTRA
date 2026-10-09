# Datasets locais e avaliação configurada — handoff

2026-10-09. Rodada 4 desktop/guest/bench foi fechada e reportada antes desta
frente. **Nenhum teste, VM, provider, downloader, setup, reset ou avaliação foi
executado nesta frente.** Indexadores/runners/verificadores e aceitações estão
preparados para execução posterior pelo coordenador. Clones/datasets originais,
host/Canvas/Core/quality/interop/UI não foram alterados.

## Arquivos novos

- `sentra_executors/benchmark_dataset.py`
- `sentra_executors/benchmark_dataset_metrics.py`
- `sentra_executors/benchmark_suite.py`
- `sentra_executors/benchmark_suite_reports.py`
- `sentra_executors/benchmark_dataset_deployment.py`
- `tests/unit/test_sentra_benchmark_datasets.py`
- `tests/datasets/sentra_osworld_v1_vscode_expected.json`
- Este handoff.

## Formatos realmente lidos nos clones

| Fonte | Formato/caminho | Pin declarado pelo catálogo atual |
|---|---|---|
| windows-agent-arena | `src/win-arena-container/client/evaluation_examples_windows/test_all.json`: categoria -> lista de IDs; `examples/<categoria>/<id>.json` | `6d39ed88c545a0d40a7a02e39b928e278df7332b` |
| OSWorld V1 dentro do clone V2 | `evaluation_examples/examples/<categoria>/<id>.json`; manifest V1 quando disponível, senão enumeração readonly de examples | `acdd3493808e716825975b0f0208194bb2faf3c3` |
| OSWorld V2 oficial | `evaluation_examples/test_v2.json`, `task_class/task_<id>.py` ou `<domain>/task_<id>.py` | mesma revisão, namespace diferente de V1 |
| WindowsWorld | `benchmark.json`: array de objetos `task_id`, `task_category`, `environment_setup`, `evaluation_metrics` | `fbccd464f94fec9e284e139f97bf96d0b192f580` |

Arena exemplos inspecionados: Calculator
`28b91a24-5d97-4c2a-891c-dccbd3820c62-WOS` (`Differences.txt`, substring textual),
VSCode `276cc624-87ea-4f08-ab93-f770e3790175-WOS` (`check_json_settings`),
Calc `0a2e43bf-b26c-4631-a966-af9dfa12c9e5-WOS` (dados **e gráfico**, assets cloud e
postconfig que salva com pyautogui), Writer
`4bcb1253-a636-4df4-8cb0-a35c04dfef31-WOS` (PDF esperado cloud).
O chart rule não é descartado para fazer sheet-only passar. URLs não são baixadas.

WindowsWorld `win_hr__l1_001` contém seed XLSX a gerar por prompt, critérios
intermediários textuais e final de ordenação por departamento. Seus outros exemplos
podem incluir e-mail/serviços externos: dataset não concede autorização para enviar
mensagens ou usar contas externas. Plano/capabilidades permanecem definidos pelo
host e admitidos pelo centro.

O README local de `OSWorld-V2/evaluation_examples/task_class` informa que classes
oficiais e assets completos são distribuídos em datasets Hugging Face gated. As
classes não estavam presentes na inspeção de fonte desta frente. IDs do manifest
ficam catalogados como `official_gated_task_not_local`; **não** são substituídos
por JSON V1, importados, baixados ou marcados evaluated. Quando instalados depois,
o loader extrai literais e hashes de métodos por AST, sem executar Python. Setup/
evaluate arbitrários ainda exigem tradução revisada pelo host e pins reais.

Revisão é declaração/pin do host, não atestação git inferida. Cada arquivo recebe
SHA256 dos bytes reais; cada payload normalizado recebe outro SHA256. WindowsWorld
também guarda JSON pointer do objeto no array. Manifests e arquivos são revalidados
antes de tentar/avaliar/retomar; alteração interrompe o uso do binding anterior.

## Catálogo e seleção

```python
from sentra_executors.benchmark_dataset import DatasetCatalog, local_clone_sources

catalog = DatasetCatalog(local_clone_sources(workspace_absolute_path)).load()
rows = catalog.catalog()                       # metadata; evaluated=False
tasks = catalog.select(dataset="windows-agent-arena", category="vs_code")
task = catalog.get(qualified_task_key)
catalog.revalidate(task)                       # source/manifest pins
```

Namespaces incluem dataset, layout, categoria e ID; V1/V2 não colidem. Payloads
ficam em JSON imutável e são entregues como dados, não instruções privilegiadas.
Catálogo registra snapshot, apps, config/setup, evaluator, postconfig, sourcepaths,
source hashes, categorias, memberships e referências de inputs/expected. Assets
remotos/generated sem bytes locais mantêm SHA ausente, sem sucesso presumido.

`DatasetSource(..., manifest=...)` seleciona manifest explícito; se ausente, erro.
Limites de tamanho/contagem protegem carregamento. Não escreve índices no clone.

`DatasetEvaluationSuite.catalog_tasks(...)` acrescenta blockers; `select(...)`
devolve somente IDs com bindings/pins/métricas/fixture/provider/verificador
efetivamente configurados e callback de readiness válido. Sem registrations,
nenhuma tarefa é avaliada por causa de existir no clone.

## Expected, métricas e cobertura

`compile_source_metrics(task, reviewed=...)` traduz somente algoritmos conhecidos:

- `check_json_settings` + `vm_file` + rule.expected dict: JSON subset conforme
  `metrics/vscode.py`, sem permitir remover as chaves esperadas.
- `exact_match` + `is_file_saved_desktop` + expected "true": verifica conteúdo
  textual required no arquivo capturado, conforme getter/metric do clone.
- `compare_csv` + vm_file/expected file: compara linhas, strict/ignore_case,
  conforme `metrics/table.py`; não troca silenciosamente por comparação de tabela.

Artefatos textuais desses adapters usam UTF-8. `official_metric_equivalence` é
**not_certified**; a origem native_subset identifica o algoritmo traduzido da
fonte, não uma execução da suíte upstream completa.

Outros funcs/regras exigem `DatasetMetricContract(origin='host_reviewed')` com
hash do spec original completo. Cobertura deve incluir todos os funcs/options e
todos os critérios WindowsWorld; critérios não configurados tornam unsupported.
Adapters revisados podem usar bytes/json/table/excel/pdf dos verificadores de
documentos existentes ou `table_sorted` (ordem Unicode lexicográfica explícita,
colunas configuradas, preservação das linhas vs seed esperado). Isso não presume
locale do Excel, regra de chart, resultados de OCR/LLM ou recálculo de fórmulas.

WindowsWorld separa final `semantic_final` de `semantic_intermediate`: score final
não é substituído pela média dos checkpoints. `intermediate_score` é reportado
separadamente. Capturar testemunhos intermediários em Operations/Artifacts reais
nos respectivos checkpoints, não inventá-los a partir do arquivo final.

`DatasetAssetPin(ref, path, sha256, purpose)` identifica seed/golden local real.
URLs/ref generated/inline são aliases de proveniência, não novos transports.
Inputs e expected devem ficar em warehouse protegido/readonly do host, separado
de write roots do agente. Hash é conferido na seleção e no judge. Expected ausente
retorna UNSUPPORTED, `evaluated=False`, score null. Actual ausente com expected
válido é falha de tarefa, não pass. Assets/source alterados ou provider/parser
indisponível têm diagnóstico de evaluator, sem score fabricado.

`inline_expected_assets(task, contracts)` retorna bytes da regra original.
`provision_inline_expected(...)` é ação **explícita** de commissioning fora do
clone, com atomic_output e captura Artifact se contexto central existir. Não foi
invocada. A fixture JSON adicionada em tests/datasets tem somente a chave esperada
do exemplo real de VSCode; não é execução real de VSCode.

## Verificador registrado

```python
binding = configured_dataset_verifier_binding(
    capability_id="dataset.verify", catalog=catalog, registrations=registrations,
    actual_paths=authorized_captured_inputs,
    expected_paths=readonly_seed_and_golden_paths,
    output_paths=workspace_report_paths,
)
declaration = declare_dataset_verifier_machine(
    machine_id=verifier_machine_id, owner_principal_id=factory.agent_id,
    bindings=(binding,), policy=None,
)
factory.register_execution(declaration)
```

Imports das duas funções vêm respectivamente de `benchmark_dataset_deployment`
e `benchmark_dataset_metrics`. Action é:

```python
{"action": "verify", "task_key": key,
 "actuals": {metric_actual_key: {
     "path": captured_readonly_path, "sha256": captured_sha256,
     "artifact_id": artifact_id, "resource_uri": resource_uri}},
 "output": optional_workspace_report_path}
```

O judge revalida source, copia snapshots bounded dos bytes autorizados, confere
hash de captura e expected, executa métricas independentemente e publica score/
critério/evidência. Não usa claimed success do agente. Role de expected não recebe
write grant e output não pode ser dentro de nenhum clone.

## Intents, execução, avaliação e retomada

`DatasetTaskRegistration` fixa payload/setup/evaluator hashes, fixture/snapshot,
provider IDs, environment_version, contracts/assets, plan_factory **do host** e
machine/capability do verificador independente. Setup só pode ser estado de
fixture preparado ou passos centrais explícitos. Postconfig precisa ser traduzido
em passos explícitos do agente ou incluído no snapshot; nunca roda durante judge.
Não importar as funções setup/getters/evaluate do clone.

`DatasetSuiteState(path, paths, source_roots=...)` vai em durable/provider-state,
fora de clones/outputs do agente. O SQLite registra tentativa, plano/hash, epoch,
intents/Operation IDs por passo, estados e receipts. Não é uma grant authority.
Reserva de intent ocorre antes do despacho, com claim CAS; mesmo passo não ganha
um segundo despacho concorrente por race local.

Callbacks obrigatórios em `HostDatasetCallbacks`:

| Callback | Assinatura / contrato |
|---|---|
| bind_request | `(context, intent) -> OperationRequest` real via `factory.dispatch_request`; vincula principal/Run/WorkItem/args/IDs |
| dispatch | `(context, request) -> OperationResult` real via `factory.submit`; admission/fencing/ContextVar ficam no centro existente |
| recover | `(context, request) -> OperationResult` por **consulta durável autorizada**; não chamar adapter.start/registry.submit nem reenviar o efeito |
| checkpoint | `(context, phase, request_or_none) -> PolicyDecision` fresca de Run/WorkItem/grant; também é chamado effect_checkpoint quando ContextVar existe |
| fixture_readiness | `(task, registration) -> FixtureReadiness` de guest/provider real, snapshot/epoch/providers/evidence |
| verifier_contract | `(task, registration) -> registration_contract_sha256(registration)` somente após conferir o binding realmente registrado |
| after_step opcional | atualização confiável de binding/epoch depois da Operation; não interpretar configs do clone como código ou esconder setup físico |

Context contém run_id/work_item_id/attempt_id/task_key. Intent contém machine/cap,
Operation/idempotency IDs estáveis e argumentos já resolvidos de receipts.
Requests e results devem ser tipos Core reais; callback que retorna dict arbitrário
de sucesso é rejeitado. Isso não torna mocks uma prova de runtime: somente o host
pode fornecer os callbacks reais e custodiar Artifact/guest/fixture.

```python
suite = DatasetEvaluationSuite(
    catalog=catalog, registrations=registrations,
    state=durable_dataset_state, callbacks=trusted_host_callbacks,
    asset_paths=readonly_assets,
)
supported = await suite.select(dataset="windows-agent-arena", category="vs_code")
agent_receipt = await suite.attempt(
    key, run_id=run_id, work_item_id=work_item_id, attempt_id=fresh_attempt_id)
verdict = await suite.evaluate(fresh_attempt_id)
resumed = await suite.resume(existing_attempt_id, evaluate=True)
report = suite.report(existing_attempt_id)
```

plan_factory retorna `AcceptanceCasePlan`/`AcceptanceStep` existentes, com reset
como primeiro passo, snapshot/environment corretos e verificador registrado.
`ReceiptField` resolve evidência de passos anteriores. Plano fica persistido;
não é recriado ao retomar. Não há mutação depois da fase verify. Campo output
é recusado se aponta para clone. Cada tentativa **nova explicitamente solicitada**
reseta fixture; tentativa ativa/uncerta bloqueia nova tentativa no mesmo WorkItem.

`attempt()` para em READY_TO_EVALUATE, `evaluated=False`. `evaluate()` executa
verify separadamente. SUCCEEDED do agente não é score. `resume()` não reseta e
não redispara ACCEPTED/RUNNING/UNCERTAIN/DISPATCHING: consulta a Operation durável
com os mesmos IDs e intent. Somente passos realmente não despachados podem seguir
após revalidação. Source/assets/registration/epoch alterados interrompem retomada.
Após reset **próprio confirmado**, readiness é consultado de novo e seu epoch é
persistido. Hooks cujo resultado ficou incerto exigem reconciliação explícita do
host; não são repetidos automaticamente. Não existe force-success/auto-retry.

O coordenador deve manter callback after_step sem mutação física implícita;
binding/epoch dependentes de recibo precisam de recuperação do próprio host se
esse hook falhar. A suíte não resolve automaticamente um hook incerto ou um guest
que mudou de epoch por operação externa.

## Relatórios no produto, sem modificar UI

`suite.report(attempt_id)` separa agent_result e verifier_result; inclui pins,
sourcepaths/revisions/pointer, environment/snapshot/epoch, Operation IDs, latência
por fase, Artifact evidence e hashes de registration/plano.

`aggregate_dataset_reports(reports)` agrega score/sucesso somente das avaliações
independentes efetivamente pontuadas, categorias/datasets, latency e unsupported.
Não usar catálogo inteiro como denominador de score nem transformar unsupported
em score zero/pass. Mostrar ambos total e evaluated para evidenciar cobertura.

`dataset_report_view_model(report)` fornece DTO pronto ao host/Canvas atual:
state/evaluated/score/intermediate_score, agent/verifier, source/pins e Artifacts.
`render_dataset_report_html(aggregate, artifact_href=...)` é HTML escaped sem
scripts/embeds remotos. O host resolve Artifact ID/URI autorizado para sua rota
existente; não há novo endpoint nem mudança no produto nesta frente.
`publish_dataset_report(...)` exporta JSON/HTML atomicamente fora dos clones e
captura Artifact dentro do lock quando contexto central existe.

## Aceitação preparada, não executada

```powershell
python -m pytest tests/unit/test_sentra_benchmark_datasets.py
```

Testes preparados: formatos reais locais, placeholders V2 gated, source drift,
expected ausente, JSON subset, separação attempt/evaluate, UNCERTAIN sem replay/
reset, intents persistidos, score denominador e escaping. Testes sintéticos de
callbacks não demonstram VM, identidade, grants ou controle operacional.

Aceitação real opt-in: `SENTRA_DATASET_REAL_ACCEPTANCE=1` e
`SENTRA_DATASET_HOST_FACTORY=<módulo_próprio_do_host>:<função>`. A factory retorna
`suite, task_key, run_id, work_item_id, attempt_id`, com Core/guest/fixture/judge
registrados e ativos. Sem flag: skip explícito. Flag com factory/prerequisitos
ausentes: falha. O teste exige payload real de third_party, readiness configurada,
reset/ator/judge reais e IDs/URIs de Artifact nos critérios PASS. Não importar
agents/bootstrap/downloaders dos clones como factory.

Primeiro alvo configurável concreto: Arena VSCode ID
`276cc624-87ea-4f08-ab93-f770e3790175-WOS`, fixture Windows VSCode preparado,
workflow UIA permitido e collector do settings.json real. Golden vem da regra
`editor.wordWrapColumn:50`, pinado fora do clone. OSWorld JSON V1 correspondente
usa path Linux e snapshot próprio: não redirecionar seu path para Windows sem
tradução/fixture revisada. WindowsWorld requer seeds/goldens/métricas de estado
intermediário explícitas. Calc com chart/PDF cloud e OSWorld V2 gated permanecem
unsupported até assets/adapters/provider completos serem comissionados.

Nenhuma tarefa do dataset foi marcada evaluated nesta implementação. Estar no
catálogo ou ter algoritmo de métrica implementado não prova provider configurado.
Download de assets gated/URLs, construção de fixtures e execução de suíte ficam
pendentes para a validação integral autorizada pelo usuário.

## Confirmação RustDesk — integração da rodada 3

Permanece a divisão já entregue, sem nova alteração nesta frente:

```python
RustDeskPeerBinding(
    # argumentos anteriores preservados
    paths=workspace_output_paths,
    host_runtime_paths=AuthorizedPaths((runtime_dir,), (runtime_dir,)),
    manifest_paths=AuthorizedPaths((manifest_dir, bundle_dir), ()),
)
```

Os dois campos adicionais são opcionais ao final da assinatura. `manifest_paths`
readonly lê manifest/bundle; `host_runtime_paths` controla runtime; `paths` só
exporta Workspace. Exportação bloqueia runtime/manifest protegidos mesmo se
aninhados no Workspace. A implementação fica em remote_rustdesk.py; testes de
regressão foram preparados anteriormente e não executados.
