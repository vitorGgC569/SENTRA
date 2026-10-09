# Rodada 4 — desktop semântico, guest real, HCS/runsc e aceitação independente

2026-10-09. Código e testes preparados; **nenhuma validação, compilação, execução
de fixture, acesso ao Hyper-V/HCS/runsc ou boot de VM foi executado nesta rodada**.
Não alterar host central/Canvas/runtime/interop para consumir estas APIs sem o
registro e a autorização existentes. Os documentos anteriores permanecem intactos.

## Evidência de fonte

Lidas as seções 01, 09–11 e 35–37 da reavaliação37. Revisões do catálogo existente:

| Fonte | Revisão registrada | Padrão/API usado |
|---|---|---|
| pywinauto | `18d2a95cebed2f0061ab4e4c80c3a76ece5dd4f3` | `windows/uia_element_info.py`: runtime_id e cache; `controls/uiawrapper.py`: Value/Invoke/SelectionItem; `timings.py`: espera de estado |
| UFO | `a795552d976c4c019d7c2f778a0effb5cef7de6b` | `ufo/automator/ui_control/controller.py`: receiver por controle; catálogo de capacidades e sequência de passos. Não importar seu dispatcher arbitrário ou seu fallback pyautogui |
| hcsshim | `ab8249e8a1110ff5f052d3710fe57f29c45503d3` | `interface.go`, `container.go`: Create/Open/GetContainers, Start, CreateProcess, Stdio, WaitTimeout, Shutdown/Terminate; schema1 público por aliases |
| gVisor | `25e4d4778b06a66f268e13c2b8b0abc433096693` | `runsc/config/config.go`; `cmd/create.go`, `start.go`, `wait.go`, `checkpoint.go`, `restore.go`, `kill.go`, `delete.go` |
| Windows-agent-arena | `6d39ed88c545a0d40a7a02e39b928e278df7332b` | `controllers/vm.py`: sessão de VM/reset/captura; Navi: observação a11y/imagem. O novo caminho Windows usa Hyper-V configurado, não executa QMP incompleto do clone |
| OSWorld-v2 | `acdd3493808e716825975b0f0208194bb2faf3c3` | `generated_task_utils.py`: conjunção/short-circuit e checkpoints; separação de resultado e avaliador. Sem postconfig oculto ou julgamento LLM |
| WindowsWorld | `fbccd464f94fec9e284e139f97bf96d0b192f580` | `metrics/table.py`: comparar artefato final; `desktop_env.py`: fixture/avaliação. Sem replay pyautogui do clone |

Hyper-V/Task Scheduler usam APIs públicas Microsoft:
[PowerShell Direct](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell-direct),
[Interactive task principal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal),
[Restore-VMSnapshot](https://learn.microsoft.com/en-us/powershell/module/hyper-v/restore-vmsnapshot).
Não foi criado protocolo proprietário de HCS, Hyper-V ou runsc. JSON/ACK dos
helpers é IPC próprio sobre stdio/spool protegido, com chamadas nativas reais.

## Arquivos exatos

Novos nesta rodada:

- `sentra_executors/guest_process.py`
- `sentra_executors/uia_semantic.py`
- `sentra_executors/uia_guest_worker.py`
- `sentra_executors/windows_guest.py`
- `sentra_executors/windows_guest_deployment.py`
- `sentra_executors/hcs_provider.py`
- `sentra_executors/hcs_bridge/main.go`
- `sentra_executors/hcs_bridge/go.mod`
- `sentra_executors/gvisor_workload.py`
- `sentra_executors/gvisor_worker.py`
- `sentra_executors/benchmark_acceptance.py`
- Este handoff.
- `tests/unit/test_sentra_executors_round4_desktop_benchmark.py`
- `tests/unit/test_sentra_executors_round4_hcs_gvisor.py`
- `tests/unit/test_sentra_executors_round4_guest_external.py`

Alterações pontuais permitidas: `windows_uia.py` (checkpoints),
`windows_identity.py` (CloseHandle 64-bit), `gvisor_runsc.py` (checkpoints do
caminho antigo). Adapters de laboratório permanecem disponíveis e distintos.

Exceção solicitada da rodada 3: `remote_rustdesk.py` separa runtime/manifest/
bundle de exportação; teste acrescentado a
`tests/unit/test_sentra_executors_rustdesk_sessions_round3.py`. Não houve outras
mudanças nos providers estabilizados da rodada 3.

## Registro e fronteira física

Todas as declarações retornam `MachineDeclaration` com adapter `GuardedExecutor`
via `SessionExecutor`. O host usa `factory.register_execution(declaration)`,
`factory.dispatch_request(...)`, depois `await factory.submit(...)`. `policy=None`
nega execução direta; o factory instala sua policy real. Não usar grants permissivos
de testes como configuração de produção.

O worker efetivo permanece no `current_effect_context.run_sync` do `_base`
existente. Helpers externos aguardam ACK de checkpoint do pai; cada ACK consulta
o ContextVar real. Revogação/timeout fecha somente o process tree próprio e não
afirma rollback de um efeito remoto. Process tree/Job é ownership de helper,
**não sandbox OS**. O runner não reenvia mutação incerta.

Journal em storage protegido `durable/provider-state`, sem write grant ao agente;
paths de outputs só Workspace. Todos os screenshots, arquivos coletados, exports
e reports publicados usam `atomic_output` existente: lock por caminho, publicação
exclusiva, verificação e captura central do Artifact antes de liberar o lock.
Standalone informa arquivo/hash local; não fabrica `artifact_id/resource_uri`.

## UIA sem coordenadas primeiro

APIs: `DesktopIdentity`, `UIASelector`, `SemanticUIABinding`,
`declare_semantic_windows_machine(machine_id, owner_principal_id, bindings,
policy=None, backend=None)`.

`SemanticUIABinding` exige `ProcessIdentity(pid, hwnd, creation_filetime,
executable_sha256)`, título exato, MachineGuid, SessionId interativo e seletores
exatos com AutomationId/ControlType/name opcional. Default foreground obrigatório
nas mutações; pode ser relaxado somente pelo host para patterns que dispensam
foco, sem fornecer keyboard/mouse fallback.

| Ação | Argumentos | Comportamento |
|---|---|---|
| `observe` | nenhum | controles do catálogo, propriedades/texto bounded e referências por revisão |
| `wait` | `selector_key, expected, wait_seconds?` | espera read-only de text/value/enabled/visible; não repete ação |
| `read` | `reference` | resolve novamente e compara runtime_id/processo/desktop |
| `set_value` | `reference, value` | UIA ValuePattern, sem digitação global; lê valor final |
| `invoke` | `reference` | UIA InvokePattern, sem click_input |
| `toggle/select` | `reference` | TogglePattern/SelectionItemPattern |
| `screenshot` | `output` `.png` | imagem da janela bound, publicada como Artifact |

Cada seletor tem `actions` próprias; habilitar ação no binding não a libera para
todos os controles. Referências incluem escopo machine/principal/capability/
work_item e fingerprint do perfil. Nova observação, troca de perfil ou mutação
invalida referências anteriores. Cache serve só à observação; execução reconsulta
o elemento. Processo recriado, HWND trocado, input desktop bloqueado, sessão 0,
título/foco alterado ou runtime_id diferente causam diagnóstico/negação.
Invoke não significa resultado final confirmado: usar wait e verificador final.

Dependency fonte estudada: pywinauto **0.6.9**, com comtypes e Pillow compatíveis
com Windows/Python usados. Não detectada versão instalada aqui. Provider COM que
trava é contido pelo worker próprio; isso não cancela um efeito já despachado.
App sem patterns requer integração de observação adicional; não há clique por
coordenadas escondido, OCR/modelo visual ou backend Win32 completo nesta rodada.

## Desktop isolado: VM configurada + tarefa interativa no guest

`HyperVGuestConfig` contém VM GUID canônico, nome, Notes exato
`SENTRA-DISPOSABLE:<inventory-tag>`, fingerprint de hardware, PowerShell
absoluto/hash, callback `(username,password)`, spool/task/guest Python/package
root e pins dos arquivos instalados no guest. `allowed_switch_ids=()` permite
somente adapters desconectados; Direct não requer rede. Autorizar switches
explicitamente se necessário. Fingerprint inclui CPU/memória/generation/config
location/disk slots/switch IDs; não prende os AVHD paths que mudam em checkpoint.

Prerequisitos reais: Windows host com Hyper-V e privilégios necessários,
Windows guest compatível com Direct, VM já provisionada, usuário **logado em
sessão interativa** e input desktop desbloqueado. Sem autologon/elevation/boot
automático. RDP disconnect/lock pode tornar desktop indisponível; não ignorar esse
erro. A sessão PS Direct não é a sessão GUI: a task `InteractiveToken` executa
UIA no desktop do usuário e o worker verifica o SessionId/input desktop nativos.
O clock UTC do guest precisa estar sincronizado ao host para deadline/TTL; skew
após restore é diagnosticado e não convertido em sucesso. Scripts do fixture
devem satisfazer a execution policy do guest; não há bypass automático.

Declarações:

```python
declare_hyperv_fixture_machine(
    machine_id=..., owner_principal_id=..., bindings=(HyperVFixtureBinding(...),),
    lease_reader=..., policy=None, runner=None)
declare_windows_guest_uia_machine(
    machine_id=..., owner_principal_id=..., bindings=(SemanticUIABinding(...),),
    guest_config=config, lease_reader=..., policy=None, runner=None)
declare_guest_artifact_machine(
    machine_id=..., owner_principal_id=..., bindings=(GuestArtifactBinding(...),),
    lease_reader=..., policy=None, runner=None)
```

`lease_reader(vm_id, scope_sha256) -> GuestLease(vm_id, scope_sha256, epoch,
expires_monotonic)` é callback **confiável do host**, derivado da autorização/
posse central da VM. Não aceitar lease/fingerprint declarado pelo agente. O scope
é o hash `SessionScope.from_request(request).key`. Caps fixture/UIA/collect podem
usar a mesma VM somente sob o mesmo WorkItem/handoff central explícito; callback
deve admitir esses scopes conforme o centro. Cada ACK também revalida o epoch.

Fixture actions: `status` default; opt-in `snapshot`, `reset`, `prepare`, `start`,
`stop`. Reset exige snapshot GUID fixado e selecionado somente dentro da VM bound.
Snapshot não sobrescreve nome existente. Start/stop só ocorrem como Operations
explicitamente solicitadas. Nenhum construtor liga ou cria VM. Reset reporta
restore solicitado; ainda requer verificação do fixture após restore.

Prepare exige `fixture_task_name`, `fixture_executable`, `fixture_arguments`,
`fixture_identity_path`, tasks/sources já instalados e pinados. Confere task
Interactive/Limited, não adota uma task já running, arquiva somente metadata antiga
configurada e espera arquivo de readiness novo (5s). Não afirma GUI pronta só por
Start-ScheduledTask; UIA/kernel e condição inicial verificam essa conclusão.

Collector action: `collect(artifact_key, output)`. `GuestArtifactBinding.inventory`
fixa key -> guest path; request não fornece um path remoto livre. Arquivo máximo
16MiB é copiado por Direct, hash conferido e publicado/capturado. Agent não pode
exportar manifest/runtime/credenciais do host por esse binding.

Guest UIA mantém referências no host e usa ACK files com job ID/sequence/TTL
curto no spool protegido. A task não recebe scripts/métodos arbitrários.
Sem ACK continua parada e expira; native watchdog limita o job. Host chama
`backend.shutdown()` para descartar referências no fim/reset do fixture.
Refs não são restauradas por snapshot nem adotadas após restart. O host deve
avançar epoch e reatestar binding após reset antes da próxima ação.

Commissionamento manual, preparado por `windows_guest_deployment.py`:

1. Usar VM descartável com disco/imagem/base e baseline conhecidos; o template
   não cria/instala VM no host. Impedir escrita de outros agentes nos assets.
2. Instalar package SENTRA dos helpers e dependências no guest. Python/WorkingDirectory
   e módulos instalados devem corresponder aos pins, incluindo dependências usadas
   pelos helpers; pin de um arquivo não atesta o bundle todo.
3. Provisionar ACLs: package/manifest readonly para task user; spool protegido do
   host/worker; outputs do fixture separados. Esses ACLs não são criados pela API.
4. Gerar/salvar Windows Forms fixture com `windows_forms_fixture_script(...)` e
   configurar task `-NoProfile -STA -File "<fixture.ps1>"` no executável guest pinado.
   `interactive_guest_task_setup(config, guest_user=...)` e
   `fixture_task_setup(...)` retornam scripts para executar **dentro do guest**.
   Nenhum deles foi executado aqui; não contêm autologon ou ExecutionPolicy bypass.
5. Capturar baseline com tasks registradas/ready e usuário logado; fixar snapshot
   GUID. `hyperv_hardware_inventory_script(vm_id)` retorna inspeção read-only para
   commissionamento, não executada automaticamente.

Não alegar isolamento por PID: o limite é a **VM Hyper-V configurada** observada
pela API. `isolation_attested=False` permanece explícito. Não foi feita atestação
remota/medida de hypervisor, nem comparação runtime com outra VM nesta rodada.

## HCS headless real

APIs: `HCSCommand`, `NativeHCSBinding`, `declare_native_hcs_machine(..., journal,
policy=None, runner=None)`. Pin de bridge e JSON preparado são obrigatórios;
`host_paths` lê config/assets; `paths` exporta somente Workspace.

Config aceita Windows Container com `HvPartition=True`, layers/HvRuntime já
preparados, memória/CPU limitadas, sem endpoints, host mapped dirs/pipes/devices
ou JSON extra herdado. `HCSSHIM_CREATECONTAINER_ADDITIONALJSON` é removido do env
do helper pois upstream o mescla ao CreateContainer. Sem download/unpack de
imagem, mount de scratch, habilitação de serviços ou escalada de privilégio.

`hcs_bridge` usa **exports públicos** de hcsshim; não importa `internal` em módulo
externo. O Go source usa schema1 legado por aliases públicos; host/build de imagem
precisa suportá-lo. Dependência do clone: toolchain Go **1.26.8** conforme go.mod.
O go.mod do helper aponta por replace ao clone separado. Comando preparado, **não
executado**:

```powershell
go -C sentra_executors/hcs_bridge build -o C:/SENTRA-provider-build/hcs-bridge.exe .
```

Fixar SHA256 do binário resultante e revisar fonte/revisão antes de registrar.
Prerequisitos: Windows Containers/HCS/vmcompute/Hyper-V disponíveis, privilégios
adequados, layers/scratch/uVM do build correspondente já provisionados pelo host.
Clone/binary fixture não prova disponibilidade, segurança ou isolamento real.

Ações opt-in: `create`, `start`, `status`, `run(command_key)`, `shutdown`,
`terminate`, `session.list`, `evidence.export`. Todas pós-create usam session ID
local, sem container ID/PID/comando livre em request. Owner nativo é bound ao
scope central; RuntimeID/SiloGUID são registrados e checados contra substituição
do compute system. Se indisponíveis, unsupported/falha explícita. Status permite
observar identity após create incerto; não confirma nem repete a Operation original.
Start/run requerem identity reconciliada. Process handle fica no helper real;
WaitTimeout/exit code/stdio bounded (64KiB cada) vêm da API. Pipes incompletos são
marcados. Shutdown/terminate só alegam wait completo se WaitTimeout terminou.

HCS não fornece GUI nesta implementação. Quotas são configurações/relatos do
provider, não atestação. Host deve integrar cleanup da posse durável de workload
ao fim/revogação do Run; não existe monitor automático de lifecycle no registro.

## gVisor útil além de /bin/true

APIs: `RunscWorkloadBinding`, `WorkloadLease`,
`declare_runsc_workload_machine(..., journal, lease_reader, policy=None, runner=None)`.
`lease_reader(container_id, scope_sha256)` devolve lease central viva; state root,
checkpoint root e bundle são storage protegido do host, separado dos outputs.

Binário runsc, spec OCI 1.0.2 e executável do rootfs pinados. Workload/argv vêm do
spec confiável, nunca de args do agente. Perfil inclui `--network=none`, plataforma
systrap/kvm explícita, file-access exclusive/shared, root readonly, usuário não
root, noNewPrivileges, sem capabilities, private namespaces, limites de pids/RAM.
Somente binds readonly aprovados, proc do sandbox e tmpfs /tmp limitado; hooks e
devices/namespace paths do host são rejeitados. Bibliotecas/rootfs completo e
fontes de mounts ainda exigem storage/manifest imutáveis do host.

Ações: `inspect`, `create`, `start`, `state`, `wait`, `terminate` (kill --all),
`delete`, `checkpoint(output)`, `restore`, `session.list`, `evidence.export`.
Linux real é obrigatório para invocar CLI; Windows não vira sandbox Linux. Sem
fallback shell/SSH/dummy runner. Stderr/nonzero oferecem diagnóstico bounded.
Create incerto requer lookup/reconciliação por session.list; nunca repetir create.

Checkpoint usa flags reais `--image-path`, `--leave-running=true`; produz diretório
próprio e tar verificado/capturado com manifest de compatibilidade/digests. Limite
default 448MiB de payload + overhead limitado. Restore exige **delete explícito**
do container antes, checkpoint próprio intacto e mesmos pins. Usa `restore
--bundle --image-path --detach`, sem auto-kill/delete ou retry. Epoch muda; não
afirma recuperar sockets/efeitos externos/FS montado nem estado semântico do app.
Experimental como upstream: workload longo, kernel/binário e checkpoint precisam
de teste externo específico. Não há restore transparente de Operation incerta.

## Verificadores e runner

APIs de `benchmark_acceptance.py`:

- `ExpectedArtifact(key, path, sha256)` só do host; fora de write roots do agente.
- `ArtifactCriterion(criterion_id, actual_key, expected_key, metric, options)`;
  metrics bytes/json/table/excel/pdf. Tabelas/Excel/PDF consomem verificadores
  determinísticos de `documents.py` já existentes, sem editar esse arquivo.
- `VerifierCase(case_id, criteria, conjunction='and', short_circuit=False)`.
- `BenchmarkVerifierBinding(capability_id, actual_paths, expected_paths,
  output_paths, expected, cases, ...)`.
- `declare_benchmark_verifier_machine(...)`; action
  `verify(case_id, actuals={key:{path,sha256,artifact_id?,resource_uri?}}, output?)`.

Judge copia bytes authorized para snapshots temporários bounded e confere pins
antes de comparar. Golden alterado, bytes alterados desde captura ou provider
ausente são `EVALUATOR_ERROR`, score null, com diagnóstico. Actual ausente tem
FAIL explícito; mismatch é falha da tarefa. Nenhum score provém de confiança do
agente, screenshot fictício ou SUCCEEDED do executor. Conjunção and/or e
short-circuit explicitam critérios NOT_EVALUATED. Fórmulas vs valores cached
mantêm comportamento explícito do verifier de documentos: sem recalcular via
openpyxl. Dependencies opcionais ausentes não simulam sucesso.

`AcceptanceRunner(dispatch, prepare_after_reset=None, after_step=None)` usa
`AcceptanceCasePlan/AcceptanceStep/ReceiptField`. O callback async de despacho
deve chamar `factory.dispatch_request` + `factory.submit` para cada passo,
preservando Run/WorkItem/machine/cap/Operation novos. Runner não cria grants nem
faz IO físico por conta própria. Stops em UNCERTAIN/erro, não reenvia ações.
Cleanup posterior é outra operação central autorizada; host deve reconciliar
incerteza antes de reset/destruição adicional.

Resultados: trajetória/latência por fase, ambiente versão, snapshot, método de
observação, estado executor separado do avaliador e taxa de sucesso objetiva.
Dispatch fictício de teste não se converte em atestação de provider. Estado PASS
exige contrato do verifier determinístico, não simplesmente `passed: true`.

`forms_acceptance_plan(...)` prepara receita concreta: reset -> prepare -> collect
identity -> wait Not saved -> observe -> ValuePattern -> observe -> Invoke Save ->
wait resultado semântico -> screenshot opcional -> collect CSV -> judge independente.
O host `after_step` de identity deve validar hash/receipt protegido e comissionar
binding com `binding_from_fixture_identity(...)`; no reset, avançar epoch e limpar
refs. A receita pressupõe catálogo na ordem InputValue/SaveResult/ResultStatus.
Híbrido exige imagem real além de UIA; ainda **não** é agente de visão/OCR treinado.
Comparar métodos usando mesmo golden/snapshot/versões, outputs e Operations novos.

Materializar Artifact registry em snapshot readonly via APIs centrais existentes
se Workspace tiver mudado; este verifier não implementa um novo transporte de
registry. Runtime integrations, ACLs, reset e source custody são pré-condições do
host, não inferências de mocks ou de metadata que o agente pode escrever.

## Aceitação posterior — preparada, não executada

```powershell
python -m pytest tests/unit/test_sentra_executors_round4_desktop_benchmark.py tests/unit/test_sentra_executors_round4_hcs_gvisor.py tests/unit/test_sentra_executors_round4_guest_external.py
```

Sem flags, os providers externos são skip explícito. Byte/observation fixtures
verificam apenas contrato/cache/perfil, nunca OS isolation, COM ou VM reais.

- `SENTRA_GUEST_R4_ACCEPTANCE=1`: CONFIG_JSON (HyperVGuestConfig sem credential),
  USERNAME/PASSWORD, IDENTITY_PATH, RESULT_CSV_PATH, MACHINE_GUID,
  FIXTURE_EXE_SHA256, EXPECTED_CSV/EXPECTED_CSV_SHA256 e INPUT_VALUE, todos com
  prefixo `SENTRA_GUEST_`. Exige baseline snapshot e ambas tasks reais. Mostra
  UIA->arquivo->verifier em VM; lease permissivo do lab **não** testa o centro.
- `SENTRA_HCS_R4_ACCEPTANCE=1`: BRIDGE, BRIDGE_SHA256, CONFIG, CONFIG_SHA256,
  CONTAINER_ID, COMMAND_JSON (HCSCommand) e EXPECTED_STDOUT, prefixo SENTRA_HCS_.
  Exige bridge compilado e config/layers reais; prova separada de GUI.
- `SENTRA_RUNSC_R4_ACCEPTANCE=1`: BINARY/BINARY_SHA256, BUNDLE/CONFIG_SHA256,
  PROGRAM_SHA256, STATE_ROOT, CHECKPOINT_ROOT e CONTAINER_ID, prefixo
  SENTRA_RUNSC_. Exige Linux e workload real com saída normal. Denial de FS/rede
  e restore de processo longo são aceitações adversariais externas adicionais.

Flag habilitada com setting ausente causa falha. Nenhuma flag, teste, build ou
probe de privilégio/provider foi executado nesta rodada. Main deve acrescentar
provas centrais de revogação durante I/O/timeout, ownership entre agentes,
hardware drift/reset, captura Artifact/restart, isolamento entre guests, quotas/
descendentes HCS e negação FS/rede/compatibilidade checkpoint runsc.

## Correção RustDesk solicitada durante esta rodada

Assinatura compatível: `RustDeskPeerBinding(..., paths: AuthorizedPaths, ...,
actions=..., host_runtime_paths: AuthorizedPaths | None = None,
manifest_paths: AuthorizedPaths | None = None)`.
`paths`/`artifact_paths` é **somente exportação**. `host_runtime_paths`/`runtime_paths`
autoriza runtime e nunca é consultado por `evidence.export.output`. `manifest_paths`
é readonly e alimenta `build_paths` para manifest/executável/bundle; write roots
nessa policy são rejeitados. Main deve passar:

```python
RustDeskPeerBinding(
    # ... demais argumentos obrigatórios preservados ...
    paths=workspace_output_paths,
    host_runtime_paths=AuthorizedPaths((runtime_dir,), (runtime_dir,)),
    manifest_paths=AuthorizedPaths((manifest_dir, bundle_dir), ()),
)
```

Se `manifest_paths` for omitido, build lookup usa a policy anterior
`host_runtime_paths`, ou os diretórios explícitos de manifest/executável caso
ambas sejam omitidas. Quando `host_runtime_paths` for omitido, runtime policy
deriva dos diretórios configurados pelo host. Nenhum fallback amplia a permissão
de output do Workspace. Todos os argumentos posicionais anteriores permanecem.
Export também rejeita runtime/write roots protegidos e manifest roots explícitos
mesmo quando forem subdiretórios de um Workspace com grant mais amplo; bloqueia
os arquivos exatos de manifest/executável. Não publicar outputs nos diretórios
readonly de assets. `resolve_artifact_output()` aplica essa exclusão tanto no
schema do executor quanto no backend.
Testes de export para manifest/lease e readonly manifest policy foram preparados,
não executados.
