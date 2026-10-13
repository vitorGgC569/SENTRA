# Cobalto — cliente Edge / frames do relay

11/10/2026. Fonte implementada; ZERO homologados. Nenhum teste/build/lint/
install/QA/runtime executado. Preview PID47408 e arquivos root preservados.

## Composição concreta para Codex

`browser/relay_observers.py::EdgeRelayObservers(control)` recebe o CP existente,
sem fábrica SQLite, outro Run ou Grant. Métodos concretos:

```python
observers = EdgeRelayObservers(canvas.control)
canvas.attach_shell_relay_observers(
    account_attestor=observers.account_attestor,
    assistant_observer=observers.assistant_observer,
)
observers.availability(owner=owner, project_id=project_id)
```

O root mantém a composição Canvas e deve combinar a disponibilidade por projeto
com seu slot. Callable presente não prova perfil enrolled, dependência presente
ou entrega. Antes da composição dos dois observers, `model_delivery_available`
permanece false; storage/chunks podem estar available independentemente.
`proves_model_delivery=False` sempre nesta disponibilidade: só receipt/final
reais do turno permitem a projeção posterior. Não execute o exemplo agora.

Enrollment SOMENTE host/operador (não endpoint renderer/model):

```python
observers.enroll(
    owner=owner, project_id=project_id,
    browser_ws="ws://127.0.0.1:<port>/devtools/browser/<id>",
    target_id=reviewed_existing_page_target, worker="TAB-<actual_chrome_tab_id>",
    extension_id=reviewed_extension_id,
    extension_source_sha256=reviewed_extension_build_source,
    browser_principal=enrolled_browser_principal, workspace=original_workspace,
    user_data_dir=reviewed_existing_edge_directory,
    profile_directory=reviewed_profile_name,
    executable=reviewed_msedge_executable,
    reviewed_executable_sha256=reviewed_executable_digest,
    reviewed_collector_sha256=reviewed_relay_host_reader_js_digest,
    expected_account_fingerprint=reviewed_account_user_fingerprint,
    expected_profile_epoch=reviewed_extension_profile_generation,
    model_bindings={canonical_server_model: observed_physical_model_slug},
    expected_revision=0, operator_approved=True,
)
observers.revoke(owner=owner, project_id=project_id,
                 expected_revision=current_revision, operator_approved=True)
```

Fingerprint de conta = SHA256 do JSON compacto/sorted de `[account_id,user_id]`
observados no committed account menu; IDs não saem nos retornos/erros.
Configuração, fingerprint e processo/generation ficam no envelope OS-protected
de `provider_content.edge_relay_profiles`, CAS owner/project/revision. Review
inicial de identidade e bytes é ação do operador; não aprovar automaticamente
a primeira conta vista. Enrollment central da extensão continua necessário e
independente. Mudança de PID/creation time/executável/contexto/perfil/conta/source
exige re-enrollment explícito; não há rebind por URL ou fallback Electron.

O resolver não cria, reinicia ou navega browser: exige endpoint CDP loopback
do Edge existente, listener PID Windows igual a SystemInfo browser PID,
QueryFullProcessImageNameW `msedge.exe`/SHA revisados, process creation time,
`Browser.getBrowserCommandLine` user-data/profile exatos, page target revisado
ChatGPT e browserContext estável. Lê o service-worker físico enrolled no mesmo
contexto, profile_epoch revisado e URL da aba `TAB-n` escolhida; ambiguidade ou
worker suspenso mantém unavailable. Account de outro Electron/Edge não serve.
Endpoint precisa permitir getBrowserCommandLine (Edge com `--enable-automation`)
e CDP opt-in já configurado pelo host; não alterei launchers, processo ou preview.

`browser/relay_host_reader.js` é fonte fixa revisada e lida pelo servidor.
Runtime.evaluate só recebe essa fonte e IDs seletores serializados: nunca código
ou corpo esperados vindos do renderer. Lê committed React account/user e model/
effort, mensagens lógicas user/assistant, parent_id, metadata.request_id,
full body e status provider. Schema ausente/ambíguo/virtualizado = unknown;
não há labels inventados, aproximação por índice, cookies/session API ou clique
em aprovação. Document ID da extensão é apenas correlação; loader CDP, processo,
target/profile e epoch central precisam concordar. A revisão host é persistida
separadamente em `edge_relay_observations`; não copia contador do frame renderer.

`account_attestor(control,owner,project_id,message,dot,job)` valida original
Run/WorkItem/Operation/assignee/workspace e seleção pinned, lê conta física e
revalida autoridade após I/O. `RelayState.leased_payload` acrescenta somente no
servidor `leased_worker`, derivado do lease validado. O callback exige esse worker
igual ao perfil revisado: um job sem target_worker não atesta outra aba por engano.
Root já o invoca imediatamente antes do sending ACK. Retorno contém
`account_verified=True,requested_model,requested_effort,worker,account_fingerprint`.

`assistant_observer(**selectors)` aceita APENAS os 18 selectors publicados em
`Cobalto-fechamento.md`. Resolve owner/project via ORIGINAL
`shell.canvas_shell_web_turns(operation_id,job_id)`, verifica perfil físico,
extension doc/epoch/profile lineage e a prova request→user do CP. Compara SHA
do corpo COMPLETO lido fisicamente, role real, parent real e status provider.
Retorna selectors intactos + authenticated + os EXATOS sete campos de
host_observation. Nada obtém autenticação só do ledger renderer ou cache.

Dependência opcional: `websockets.sync.client`; não instalada nesta fase.
Protocolo primário consultado apenas como documentação, sem executar browser:
[Browser](https://chromedevtools.github.io/devtools-protocol/tot/Browser/),
[SystemInfo](https://chromedevtools.github.io/devtools-protocol/tot/SystemInfo/),
[Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/),
[Runtime](https://chromedevtools.github.io/devtools-protocol/tot/Runtime/),
[Page](https://chromedevtools.github.io/devtools-protocol/tot/Page/).

## Produtor e recuperação por observação

`edge_extension/service-worker.js::omaPublishAssistantFrame` agora recupera
request_id do user ORIGINAL por nova observação committed, inclusive generating.
Não usa job_id/timestamp como request MCP. Depois junta o receipt JÁ armazenado
no relay pela nova rota POST `/jobs/receipt-observation`, antes do frame.

Schema exato da rota nova:
`{job_id,worker,lease_token,request_id,source_sha256,document_id,identity_epoch}`.
Origin/bearer/build/collector e token ORIGINAL são obrigatórios. Owner/Run/WI/op
vêm do send intent, original grant precisa continuar válido. A rota aceita ZERO
bytes de receipt ou prompt, não renova lease/claim/fence e não envia nada ao
modelo. Só reatesta receipt exato existente e pode reparar ACK perdido/expiry.
`reconcile_web_receipt` antigo permanece API host; não foi exposto genericamente.

O producer lê full assistantFrame como DADO não confiável e POSTa a rota
`/jobs/response-frame` exata já publicada. Tenta parciais entre fatias de espera;
final só é aceito após observer físico. Dedupe SHA+message+revision persiste apenas
metadados, nunca prompt/body/binary no Chrome storage. Perda de ACK pode repetir
observação/frame com mesma chave/conteúdo, jamais Send. ACK parcial não se torna
final por cache. `WebSend.answer` reserva IDs/revision, libera namespace lock,
observa/grava histórico protegido, revalida CP e CAS antes de publicar estado.
Não segura writer PG durante I/O/nested namespace initialization.

`send_reserved` é persistido antes de solicitar sending fence. Falha/expiry/crash
de job bound preserva metadados originais em `observe_only`; retomada faz somente
scan/receipt join/frame, sem STOP_GENERATION, Continue, WAIT_RESPONSE, renew,
claim, progress ou sender. Tab com observação pendente não recebe novo job.
Ausência de receipt/doc/conta/model/host continua uncertain e requer reparo do
operador; fechar a aba perde a oportunidade física, não prova not-run.
HTTP result COMPLETED do renderer não substitui ANSWERED independente.

## Pendências reais, separadas

- Root: compor objeto/callbacks + disponibilidade per-project + fluxo host-only
  de review/enrollment; conservar CP único, pinned seleção e recuperação sem resend.
- Tessela: source/restamp/distribuição da extensão 1.7 e dependência websocket;
  CLI binário usa o mesmo helper/turno. Nenhum build/restamp instalado agora.
- Ambiente: Edge autorizado com CDP existente e schema committed observado,
  extensão real enabled/enrolled, perfil/conta revisados; não alegados disponíveis.
- Validação futura: protocolo/Win32/CDP/schema/PG/worker/quotas/crash após liberação
  geral. Fonte implementada e assinatura não equivalem a homologação.


Adendo de nao reenvio fisico: `SENTRA_BOUND_OBSERVATION(job_id)` do content-script
quiesce o guard existente via cleanup e latch antes do sending fence. Guard
executando Stop/Continue no momento e recusado. Nenhuma source Tessela de guard
foi editada. WAIT_RESPONSE de turnos bound recebe `read_only=True`; additional
checks sao observacao/espera por operador, nunca segundo prompt Continue. Reload
ou navegacao invalida documento; nao recalibra identidade para reparar envio.
Parent user com anexos binarios exige role/request/message reais; a atestacao le
corpo textual FULL do child assistant, sem transformar objetos binarios do parent
em texto. Mais de um child committed para o parent e ambiguo.
