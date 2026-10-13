# Cobalto — Brisa/Rastro, contratos de fechamento em andamento

11/10/2026. Ownership vigente em `REDISTRIBUICAO_CODEX.md`.
ZERO homologados; nenhum teste/build/lint/install/QA/runtime executado.
Não toquei preview PID47408, assets, lock ou arquivos centrais root/Nexo.
Handoff de única edição Pacto anterior: `Cobalto-handoff.md` (Prisma).

## Contrato imediato root / Tessela: multimodal binário

`native_bridge.shell_multimodal.dispatch_shell_turn(control,jobs,drafts,web,*,
owner,run_id,work_item_id,operation_id,principal_id,grant_id,workspace,
project_id=None,space_id=None,conversation_id,conversation_url=None,
request_identity,prompt,attachments,operator_approved=False,timeout_s=180)`.
Kwargs opcionais adicionados a pedido root: `requested_model=None`,
`requested_effort=None`. Repassados sem alteração para `web.admit`; só
valores pinned server-side, nunca inferidos do filename/renderer.

`attachments` continua lista Brisa resolvida server-side:
`{attachment_id,kind,name,mime,bytes,sha256,data:bytes}`. Validar todas as refs
com `AttachmentStore.validate_attachments(owner,refs,project_id,space_id,
conversation_id)` e então `read_bytes(owner,id)`. Nunca confiar em owner/IDs
Run/WorkItem/Grant ou caminhos do renderer/CLI. Preservar a Operation original.

Mudança concreta: helper agora envia **arquivos inteiros** (PNG/JPEG até 8MiB,
PDF/texto até 20MiB, máximo 4) pela extensão ChatGPT/relay. Não exporta/trunca
PDF para texto, não expande o prompt com arquivos, não divide conjunto, não
repete prompt. Staging por key determinística, ciphertext em chunks 64KiB;
job/outbox apenas refs. Descritor transportado usa filename gerado seguro.

`WebSendAuthority.admit(...,attachments=[{asset_id,name,mime,bytes,sha256}],
dispatch_mode='relay')` faz UM admit/intent/fence. `RelayState.attachment_chunk`
e `POST /jobs/attachment-chunk` exigem bearer/origin/build + worker/lease
exatos, grant `web:attach` e scope original. A extensão verifica SHA de cada
chunk e SHA/tamanho total e faz UM gesto upload + UM Send.

Receipt binário é schema legado `{conversation_id,message_id,prompt_sha256,
images_attached}` mais `{attachments:[descritores exatos],attachment_names:
[nomes observados na nova mensagem user]}`. Local storage/READY_LOCAL não
provam upload. `AttachmentUploads.upload_status` exige também atestação
central request→message/document/epoch antes de `web_uploaded=True`.
Receipt comprova observação de mensagem/chips e source digest local, não
um hash recomputado pelo provider nem conclusão do WorkItem.

Composição ainda do root: `CanvasShellRuntime.dispatch_message` hoje recusa
refs antes de enfileirar; ligar o helper ao executor real de modelo e
acompanhar receipt/answer sem reenviar uncertain. A extensão precisa de
RelayState **com authenticated_control**; JobStore puro não fornece o
endpoint de chunks. Turno externo/upstream atual não aceita refs binárias:
indisponibilidade explícita, sem downgrade ou export textual silencioso.
Tessela: CLI pode transmitir refs `att-*` pelo único ShellBridge ou usar
ambiente/cápsula host-trusted Nexo; não criar CLI sender paralelo.

## Voz real / transcript servidor

`browser/voice.py`: multipart POST `/realtime/calls` com API key somente
servidor; call ref `rtc_*` extraída de `Location`; hangup por POST
`/realtime/calls/{id}/hangup`; removida mint beta/GET/DELETE supostos.
Checkpoint da autoridade antes de cada HTTP, redirect recusado, erros sem
conteúdo provider/segredos. SDP, resultados e transcript persistem protegidos.

`browser/realtime_sideband.py` (novo): conexão servidor autenticada
`/realtime?call_id=`, via opcional `websockets.sync`, bounded 64KiB/evento,
64 queue/256 eventos/drain e 2s. Recebe user transcription.completed e
assistant audio_transcript.done; nenhum comando/tool executado. Conexão
abre em voice_start; heartbeat existente drena ingress e registra eventos
com call/generation/owner rechecados depois da rede. Status permanece local.
Renderer transcript segue provisional; nunca confere `verified=True` ou
tool-role por recibo inventado. Provider event original fica protegido e
recuperável por call/generation/event_id. Sem sideband, disponibilidade
explícita de transcript; sinalização/mídia não são prova de entrega textual.

Rebind/stop/revoke têm reserva `voice_effect_requests` antes do HTTP, chave
e fingerprint imutáveis, resultado completo protegido; pending retorna
uncertain e nunca recria chamada. Rebind reserva generation e fecha chamada
anterior, close failure permanece explicitamente uncertain. Local revoke
precede hangup, sem transação SQL segurando rede. Nexo fornece o CP wrapper.

Fontes oficiais consultadas, sem executar API:
- https://developers.openai.com/api/reference/resources/realtime/subresources/calls/methods/create
- https://developers.openai.com/api/reference/resources/realtime/subresources/calls/methods/hangup
- https://developers.openai.com/api/docs/guides/voice-server-controls?voice-api=realtime

## Host snapshots / conta

`integrations/codex_chatgpt_web/sentra-upstream.patch`: fonte agora contém
`sentraApprovalSnapshot`/`sentraAccountCatalog` e rotas no control-server
autenticado existente. Lê committed React primitives, valida turn-owned
surface/doc/epoch/authrevision antes/depois. Nunca clica approval nem busca
cookies/session endpoints. Catálogo é somente opções observadas, complete
separado, unknown permanece explícito. **Patch não aplicado ao runtime.**

`sentra_model_gateway/account_attestation.py` (novo): `HostAccountAttestor`
com `enroll(owner,descriptor,tab,trace_id,browser_principal,
reviewed_host_sha256,reviewed_collector_sha256,expected_revision,
operator_approved)` e `revoke(owner,profile_key,expected_revision,
operator_approved)`. Enrollment server-only por operador, perfil/account
fingerprint e pins protegidos/CAS; zero grants. Callable `(cap,descriptor,
tab)` lê host vivo, compara conta/perfil/fontes/approval/authrevision/seleção
com request Responses original protegido. Collector/worker/surface precisam
também da enrollment existente `BrowserEvidenceService.configure_host`.
`host_boot.attach_attestors` agora injeta essa classe, sem promover cache
de AccountCatalog a prova física. `browser_host_identity.read_host_account_catalog`
exige callback account_verifier real; flag account_verified de página não basta.
Root/Tessela devem compor review/enrollment e embarcar patch/pins na etapa
futura; a existência desta fonte não prova instalação/conta/schema atuais.

## Proteção / PostgreSQL / continuidade

`browser/protected_assets.py` (novo): DPAPI/keyring + binding/digest/tamanho,
limite antes de leitura, caminhos sem symlink, temp exclusivo/fsync/replace,
checkpoint antes de efeito físico. `AttachmentStore` usa esse caminho em
blobs/chunks, begin dedupe real, scope preso à origem, JPEG reconhecido pelos
bytes, cleanup apenas após receipt commit. Legados plaintext exigem migração
explícita, sem alegar erasure/portabilidade de perfil.

`browser/streaming.py`: remove identity via positional rowid, exige exato
request/document/epoch; `read_content(principal,conversation,message,revision)`
recupera texto protegido/overflow com digest e limite 1.5MB. Frames não
autorizam efeito nem provam entrega. Índice DOM fica apenas descritivo.

Defaults `create_control_plane_store` nos consumidores browser_evidence,
session_checkpoint, web_history_store/usage, web_account_dispatch e voice/
attachments; `TurnAuthority(...,control=None)` usa `durable.store` da mesma
seleção, nunca um SQLite store paralelo. `web_send` migração do índice usa
pg_indexes + DROP INDEX qualified nativo somente no ramo PG sob namespace
lock; SQLite mantém seu caminho local. Corrigida leitura positional tuple
para colunas nomeadas em binding PG. Nexo confirmou ownership em
`Cobalto-Nexo-contract.md`; seus arquivos não foram editados.

## Restante separado

Implementação ainda em andamento: coerência de scopes/replays de voz e
legados protegidos, catálogo host upstream para todas as formas observadas,
fechamento dos consumidores de histórico/recovery e documentação completa.
Composição root/CLI: ligar helper e receipt/answer reais, Host profile review,
factory/backend único e attestors do worker sem criar autoridade paralela.
Ambiente/release: pacote websocket/provider autorizado, extensão re-stamp
1.7 pelo pipeline Tessela, patch host/guest/manifests/binários e contas reais.
Validação futura: exclusão/revogação/crash/quotas/PG/conta/mídia/composer/receipt
somente após liberação geral; nenhuma evidência runtime alegada aqui.

## Delta root: assistant attestation / Relay frames (fonte implementada)

`assistant_attestor_from_streaming(control,streaming,*,host_observer=None)`
agora NÃO autentica pelo ledger renderer. Sem callback independente retorna
`authenticated=False`. Verifica receipt central + send intent original:
owner/Run/job/WorkItem/Operation/assignee/workspace/worker/send_fence;
conversation/parent_user_message/epoch EXATOS ao receipt. Revalida request
→ user message/doc/epoch/collector no BrowserEvidence/ChatAccess existente.
Lê frame protegido COMPLETO (`StreamingLedger.read_content`), compara SHA
total com body_sha256, e só então chama o observer físico independente.
Latest revision ou prefix digest isolados nunca são prova.

Callback SERVER-SELECTED (nunca registrado por endpoint/renderer):

```python
host_observer(**selectors) -> {
    **selectors, "authenticated": True,
    "host_observation": {
        "revision": host_revision, "body_sha256": full_body_sha256,
        "state": "partial" | "complete", "collector_id": reviewed_collector,
        "source_sha256": reviewed_collector_sha256,
        "document_id": exact_document, "identity_epoch": exact_epoch,
    },
}
```

Selectors exatos: `owner,run_id,job_id,worker,conversation_id,message_id,
parent_user_message_id,revision,body_sha256,identity_epoch,role='assistant',
state,browser_principal,request_id,document_id,work_item_id,operation_id,
workspace`. A leitura física deve observar role/parent/corpo INDEPENDENTEMENTE
desses seletores (usar como seleção/desafio, nunca copiar como prova).
`revision` de frame e `host_observation.revision` são clocks diferentes.
Factory confere todos os bindings e o host digest/state/doc/epoch/source
antes de retornar autenticado; WebHistory preserva monotonicidade host.
Callback existente `DurableWebTransport._host_observation` é baseado em
read_host_message/challenge do Electron; não atribuir a ele outro Edge/profile.
Host real não configurado → indisponível explícito, sem substituição por DOM
renderer/StreamingLedger. A source do guest/extensão não autentica sozinha
uma observação independente do próprio mesmo ledger.

`RelayState(...,authenticated_control=shared_control,
assistant_observer=host_observer)` ou
`state.attach_assistant_observer(host_observer)` liga o store compartilhado e
o attestor. `RelayServer` aceita o mesmo kwarg. Root é dono da resolução do
observer de browser configurado/autorizado; Cobalto não cria outro host.

`state.response_frame(...)` e **POST `/jobs/response-frame`**:
schema EXATO `{job_id,worker,lease_token,request_id,source_sha256,document_id,
identity_epoch,conversation_id,message_id,parent_user_message_id,revision,
body,complete}`. Origin/bearer/build verificados na mesma rota relay.
`extension_id` vem do Origin; owner/Run/WI/op vêm do send intent. Token é o
lease ORIGINAL, não há renew/claim/requeue: uma prova tardia exata pode
reparar UNCERTAIN. Receipt original deve estar sent+attested; frame não pode
substituir parent por outro user. Complete literal bool, corpo máximo 200000
chars, digest computado servidor. Guarda frame protegido como dado e chama
`WebSend.answer`, que só chega a ANSWERED após callback independente.
Caller pode enviar a mesma revision/corpo após perda de ACK; mudança no
conteúdo com mesma revision é conflito. Replay nunca reenvia prompt.

`StreamingLedger.record_frame` agora aceita replay exato por SHA total;
WebHistory cap alinhado a 800000 bytes (200000 chars UTF-8 de ChatResult).
Root pode ler body/receipt com status/projeções existentes e reparar o gap
history-final → outbox ACK por `WebSend.status`/`_finish_answer`, sem resend.
Fonte endpoint pronta; worker producer/injeção de observer físico e aceitação
externa permanecem composição/ambiente, não prova runtime nesta fase.


## Delta final desta rodada - cliente Edge e producer fisico

Contrato concreto em [Cobalto-relay-observers.md](Cobalto-relay-observers.md).
`browser/relay_observers.py` + `browser/relay_host_reader.js`: cliente CDP real
somente leitura, vinculando listener/PID/creation/exe SHA, user-data/profile,
context/target e extensao fisica/profile_epoch/worker ao CP compartilhado.
Conta real committed e selecao server pinned reatestadas antes sending;
assistant completo/role/parent/provider-state lidos independentemente do frame.
Enrollment/revoke host-only CAS/protegidos; nenhum browser/preview e iniciado.
Sem enrollment/endpoint/schema/dependencia, entrega fica indisponivel explicita.
Electron continua provando apenas seu proprio Host, sem fallback para outro Edge.
Root deve ligar callbacks, disponibilidade por projeto e review UI.

`native_bridge/relay.py`: `leased_payload` expoe leased_worker so ao host;
`receipt_observation` e POST `/jobs/receipt-observation` exigem original token /
worker/fence/grant e receipt ja persistido. Nao recebem prompt/receipt novos,
nao renovam lease ou Send. `response_frame` usa a mesma original worker proof.
`stream_ingest.py`: normaliza host_observation aos sete campos exatos esperados
pelo historico; ledger renderer e conteudo protegido, nunca autenticacao.

`edge_extension/service-worker.js`: producer descobre novamente request MCP do
user original, junta receipt existente, publica partial/final por revisao/SHA.
ACK parcial nao vira final em cache. `send_reserved` precede fence; crash/expiry/
falha preservam metadados observe_only, retomada nao usa renew/Stop/Continue/
WAIT_RESPONSE/progress/claim/Send. Tab pendente nao recebe outro job. SaveActive
failure aborta antes de efeito. `content-script.js` adiciona binding readonly do
turno e quiesce pela API de cleanup do guard ja existente; recusa guard ocupado
por outro efeito. `observer.js` WAIT read_only observa additional-checks e pede
operador, sem recovery automatico. Nenhum arquivo de guard Tessela foi editado.
`conversation-evidence.js`: parent request so de role user; body binario do user
nao e confundido com texto assistant. Child assistant exige corpo textual inteiro.

`native_bridge/web_send.py`: lease central por colunas nomeadas PG; reserva
answer ID/revision antes de host I/O, writer lock liberado enquanto observa,
CP/revision CAS rechecados antes de finalizar. Final so aceita replay da mesma
revision. `host_boot.py` remove attestor inseguro de catalogo/cache e corrige
usage_projection para eventos reportados na governance compartilhada com filtro
owner/workspace, sem importar ProviderUsageLedger inexistente ou abrir SQLite.

`browser/attachments.py`: completion key/fingerprint imutaveis (incluem WI/op),
conflito nao sobrescreve receipt de outro upload; replay exige chave original.
`browser/voice.py`: start status lookup por owner+project+key; replay de rebind
verifica original protegido antes de generation/terminal e nao faz HTTP novamente.
Provider events protegidos carregam owner/project/call/generation/conversation/
Run/WI/call-ref; overflow recovery recusa ciphertext transplantado. SDP/signal/
storage receipts nao provam conclusao remota ou tool-role. Tools de voz ainda
requerem admissao CP explicita do consumidor; transcript observado nao cria Grant.
`session_checkpoint.py`: branch PG evita path_for e secure_delete local; migracao
legada PG preserva marcador e exige retention purge administrativo, sem fallback.

Pendencias reais de ambiente/composicao: review/enrollment Canvas por projeto,
CDP/profile/conta reais autorizados, pacote websocket/provider, source/restamp/
release da extensao com Tessela e patch Host aplicado ao upstream. Schema
virtualizado/desconhecido nao usa aproximacao por DOM index. Fontes concretas/
configuraveis; nenhuma validacao/runtime foi executada e nada homologado.
