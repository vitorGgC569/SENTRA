# Rodada 5 — JetStream e auditoria externa verificável

Handoff de implementação, 09/10/2026. **Nenhuma bateria, teste, build, serviço, login ou contato externo foi executado nesta fase.** Não há evidência de broker/log/database operacional. Clientes SDK e persistência reais foram implementados; build, provisionamento e aceitação externa estão pendentes da validação conjunta final.

## Projetos e fontes conferidos

Na reavaliação37 atual: **18 = nats-server; 23 = OPA; 24 = Tessera; 25 = immudb**. OPA foi entregue na rodada 4. Esta rodada incorpora 18/24/25, além dos requisitos correspondentes das auditorias de 08/10 (PubAck não é efeito; cobertura de auditoria não é garantida por log; verificação/retorno/backup precisam de provas reais).

| Fonte / HEAD local | API realmente utilizada |
| --- | --- |
| nats-server `6af2d22525d55f08ea72812e799b0397e1cf06f1` | ConsumerConfig/StreamConfig, testes de JetStream e client: SDK `github.com/nats-io/nats.go v1.53.1` pinado pelo go.mod do clone; PublishMsg/PubAck, GetLastMsg, durable PullSubscribe/Fetch, AckSync, NakWithDelay, Term, InProgress, StreamInfo/ConsumerInfo e recursos nativos. |
| Tessera `0489e17418aa6f6a3acf692d45e03102eeb2b3e5` | client/fetcher.go/client.go, api/layout, cmd/conformance/posix/main.go e integration/log: `POST /add` bytes→índice decimal; checkpoints/tiles/entry bundles reais; ParseCheckpoint/note.Open; ProofBuilder, RFC6962 inclusion/consistency; verifiers oficiais ML-DSA/CosignatureV1 para witnesses. |
| immudb `bfdce03649f52d575be46f74425fd18eaf4fa69c` | pkg/client/session.go/client.go, schema.proto, state service, embedded/store/verification.go: OpenSession, VerifiableSet com precondition nativa, VerifiableGet, VerifyInclusion/VerifyDualProof, FillMissingLinearAdvanceProof, assinatura ImmutableState, VerifiedTxByID e ExportTx. |

O módulo Go faz `replace` de Tessera/immudb para os clones locais; `v0.0.0` nesses requires é a referência técnica de módulo local, **não um release externo alegado**. HEADs/API são os pins de fonte. go.sum e binário precisam ser produzidos/revisados no build final. Manifest: `sentra_runtime/audit_provider_sdk/source-manifest.json`.

## Arquivos e preservação

| Área | Arquivos novos |
| --- | --- |
| Projeção/outbox/bridge | `sentra_runtime/audit_delivery.py`, `audit_provider_bridge.py` |
| Providers | `sentra_runtime/nats_jetstream.py`, `tessera_provider.py`, `immudb_provider.py` |
| SDK cliente owned | `sentra_runtime/audit_provider_sdk/go.mod`, `main.go`, `nats.go`, `tessera.go`, `immudb.go`, `source-manifest.json` |
| Template de instalação | `sentra_runtime/audit_provider_sdk/nats-server.example.conf` |
| Testes preparados | `tests/unit/test_sentra_runtime_audit_delivery.py`, `test_sentra_runtime_nats_jetstream.py`, `test_sentra_runtime_audit_external_proofs.py` |
| Documentação | Este handoff |

`audit_chain.py`, `sqlite_audit.py`, aliases/caminhos anteriores e o ledger existente foram preservados. Nenhuma edição em central_authority, effect_boundary, machine_host, Canvas, servicesCore, quality, interop ou arquivos de outros agentes. A importação do helper owned existente apenas reutiliza cleanup de grupo POSIX/JobObject Windows; não altera seu código.

Não existem novas tabelas Run/WorkItem/Operation/grant/lease. Há somente outbox/inbox de entrega, proofs, referências nativas, divergências e trusted heads. Os IDs de Operation presentes no export são **referências existentes do source audit**, não criação de autoridade. Notificação não modifica uma Operation central nem transforma seu ACK em recibo de efeito.

## Store, outbox, retenção e origem

```python
delivery = AuditDeliveryStore(
    database, workspace_root=workspace_root,
    owner=authenticated_owner, workspace_id=canonical_workspace_id,
    max_pending=10000, max_stored_bytes=64_000_000,
    retention_seconds=604800,
)
```

Todas as projeções ficam dentro do workspace, com DPAPI/keyring real, digest e transações/CAS. Payloads não têm fallback plaintext. Proof/export bytes grandes são guardados em chunks protegidos, com digest por chunk e do artifact completo, não como `verified:true` local.

- `enqueue(provider, profile_sha256, event_id, body) -> key`: vínculo imutável de owner/workspace/provider/profile/event/body; duplicate diferente é recusado.
- `claim(key, provider, profile_sha256)`: QUEUED→IN_FLIGHT antes do request. Restart não libera automaticamente a mesma identidade para envio. Result perdido exige observer real.
- `row`, `pending`, `status`: diagnóstico sem autoridade. CONFIRMED significa entrega/verify específica do provider; não execução de máquina.
- `head`, `initialize_head`: estado confiável por scope/provider/profile. Head só avança por CAS junto do receipt confirmado. Conflito exige reconciliação com o head atual.
- `proof_blob`, `read_blob`: bytes reais/protegidos e verificação de integridade local do armazenamento. **Hash local do blob não é prova criptográfica do conteúdo externo.**
- `inbox`, `notifications`: persistência/dedupe de notificações, sem executor callback; devolvem requires_central_reconciliation=True e authorizes_effects=False.
- `divergence`: preserva falha de assinatura/quorum/fork/inclusão sem substituir o último trusted head.
- `prune(confirmed_before=...)`: só depois da retenção configurada; preserva pending/uncertain, heads, divergências e tombstones imutáveis de event ID. Dados/proofs expirados são marcados indisponíveis, não verificados ficticiamente. Blobs sem referência só expiram após sua própria idade de retenção. Tombstones impedem export recomeçar depois de apagar payload; continuam consumindo quota. Arquivar referências/proofs antes se a política exige conservação maior.

Enqueue de source real:

```python
key = provider.enqueue_entry(existing_sqlite_audit_ledger,
    source_id=trusted_source_identity, sequence=existing_event_sequence)
head_key = provider.enqueue_head(existing_sqlite_audit_ledger,
    source_id=trusted_source_identity)
```

O adapter verifica em streaming a cadeia/canonicalização existente (memória bounded) antes de capturar entry/head. Entry export contém source sequence/digest/previous, SHA do evento canônico e Operation ID já existente; dados sensíveis do evento não são exportados. Head export contém o compromisso do source head. Prova externa desses compromissos não comprova captura de ações fora da instrumentação: o coordenador precisa ligar o source às evidências reais no boundary central. Para verificar o evento original, comparar seu hash canônico com source_event_sha256 e depois verificar a prova externa do wrapper comprometido.

## SDK bridge, credenciais e rede

`OwnedAuditSDKBridge(executable, executable_sha256, provider, configuration, credential_provider, enabled=True, timeout=15)` é **cliente owned**, não servidor compatível. Constructor é inerte. `start()` é explícito e só será chamado após bootstrap/validação autorizados. SHA do binário é verificado; stdin privado entrega perfil/credentials; env e argv não carregam credenciais. stderr de SDK é descartado para evitar vazamento; erros públicos são códigos sanitizados.

`credential_provider(provider, profile_sha256) -> dict` pode ser sync/async. Values de SDK são strings. `_expires_at` opcional é deadline interno do host, removido antes de enviar ao SDK; quando vencido, fecha client e exige reautenticação explícita. Credenciais mudadas/revogadas exigem close/connect pelo host, sem reenviar exports incertos.

TLS: CA file+SHA, ServerName, SPKI SHA256; client cert/key opcionais também pinados por SHA. TLS normal valida cadeia/hostname e expiry, além do SPKI. No NATS é tls://; nos outros, HTTPS/TLS gRPC com porta explícita. Sem downgrade, redirects, proxy de ambiente ou cluster URLs descobertas não aprovadas. Service permissions/account/database devem corresponder ao owner/workspace; a string owner em payload não é autenticação.

IPC owned interno aceita somente métodos enumerados por provider, não comandos CLI/remotos. Requests/responses, proof sizes e deadlines são bounded. Falha/mismatch de request ID fecha/tainta o bridge. Reconectar é ação explícita; outbox claim continua impedindo repetir write. Cleanup fecha grupo/job owned em erro/timeout/close. Usar apenas o binário construído das fontes aprovadas; não registrar uma fixture como provider real.

Quando o coordenador chama o bridge dentro de um CentralEffectContext já existente, spawn e dispatch IPC fazem checkpoint desse contexto antes/depois. Não há reserve/lock/ack de Operation adicional. Fora desse contexto, export relay continua sendo transporte auxiliar owner-scoped, e não execução de máquina autorizada pelo payload recebido.

## NATS JetStream

```python
bus = NATSJetStreamProvider(
    config=NATSJetStreamConfig(
        server="tls://nats-owner.example:4222",
        stream="SENTRA_EVENTS", consumer="SENTRA_HOST",
        owner=owner, workspace_id=workspace_id, tls=approved_tls_pins,
        max_messages=10000, max_bytes=16_000_000, max_consumers=16,
        max_age_seconds=86400, duplicate_window_seconds=120,
        max_ack_pending=32, max_deliver=5, backoff_seconds=(1,5,30),
        batch=16, replicas=1,
    ),
    store=delivery, executable=sdk_binary,
    executable_sha256=sdk_binary_sha, credential_provider=host_credentials,
    enabled=True,
)
await bus.connect()  # futuro bootstrap; não executado nesta rodada
```

Credenciais NATS aceitas: token; username/password; UserCredentials file+digest (NKey/JWT oficial); ou client certificate do perfil TLS. Callbacks não são obtidos de arguments/notificações. SDK pinned: nats.go v1.53.1 referenciado pelo clone.

Native resource lifecycle:

- `await configure(trusted_admin_authorize=...)`: callback host confirma `(owner,workspace,profile_sha)`; cria somente recursos faltantes com API real, **não sobrescreve configuração existente**. Uma role publisher normal não deve ter os privilégios de criação.
- FileStorage/replicas; LimitsPolicy; DiscardNew; máximo de bytes/messages/consumers/msg size/age; duplicate window; MaxMsgsPerSubject=1. Declaração/config existente precisa coincidir, caso contrário nega.
- Pull durable: explicit ack, MaxAckPending/MaxWaiting/MaxRequestBatch/MaxRequestExpires/MaxRequestMaxBytes, backoff/MaxDeliver, replay por posição OU tempo (RFC3339) e policy fixa. Server antigo que não aplica os campos retorna mismatch, não sucesso aparente.
- Topic scope é hash de owner/workspace + channel; tipo/event ID tem subject exato. Canal `audit` usa stream separado quando necessário; não transportar terminal/comandos com a retenção das notificações.

`enqueue(event_id, kind, references) -> key`: só operation_status, work_item_projection, audit_head, provider_health, com conjunto exato de references. Não aceita command/arguments/action. event ID nunca fica disponível para outra publicação depois de retenção/tombstone.

`await publish(key)` utiliza PublishMsg real, Nats-Msg-Id, Nats-Expected-Stream e Nats-Expected-Last-Subject-Sequence=0 em subject individual do evento. PubAck (stream/sequence/duplicate/domain) só é persistido como confirmado após response real. FileStorage dá o contrato de persistência JetStream; sua durabilidade operacional ainda depende do deployment. **PubAck não comprova Operation/efeito SENTRA.**

Perda de PubAck deixa UNCERTAIN. `await reconcile(key)` usa GetLastMsg do subject exato e compara message ID e body digest. Ausência pode ser retenção, request não integrado ou estado ainda incerto: não confirma ausência nem reenfileira com nova identidade. Janela finita de broker dedupe não substitui claim/inbox/idempotência central.

`await pull(batch=...)`: fetch real bounded. Antes de ACK, valida schema/scope/subject/idade/tamanho e persiste inbox; duplicate id/body já persistido gera ACK sem outro processamento. Mensagem fora do perfil é quarantinada e TERM; armazenamento cheio gera NAK delayed. Métodos `ack(handle)`, `nak(handle,delay=...)`, `term(handle)`, `progress(handle)` só operam handles pertencentes ao SDK. AckSync confirma ACK pelo broker; NAK/TERM/progress são envio do protocolo e **não recebem rótulo de durable ACK confirmado** quando API não o garante.

`notifications()` não executa efeitos. O host precisa consultar/reconciliar a autoridade central pelo ID transportado, com sessão/grant atual. Não submeter machine_execute automaticamente e não trocar identidade de uma Operation UNCERTAIN.

`status()` retorna StreamInfo/ConsumerInfo nativos, backlog/pending e projeção local. `close()`/`invalidate_credentials()` encerram transporte; redelivery posterior reencontra o inbox ou é recusado pela idade máxima. Retenção de inbox precisa cobrir MaxAge do stream. Após o broker atingir MaxDeliver, dead-letter/reconciliação é decisão da aplicação; quarantine local existe, mas não é servidor DLQ fabricado.

Deployment necessário: broker NATS real com JetStream habilitado, volume persistente, TLS/certificados e account permissions scoped (publish subject, APIs readonly/pull e ACK do consumer). O template .conf é configuração nativa para revisão, não um broker criado pela implementação. Substituir SCOPE pelo prefixo calculado e fornecer role administrativa separada. Domínios/contas podem mudar ACK/API subjects; conferir ACL nativa do deployment final.

## Tessera: compromisso, proof e witness quorum

`TesseraAuditProvider(config=TesseraConfig(...), store=..., executable=..., executable_sha256=..., credential_provider=..., enabled=True)` usa o cliente oficial local. Perfil HTTP deliberadamente específico: **tessera-conformance-add-tiles-v1**, derivado do cmd/conformance do clone. Tessera é também biblioteca; não existe /add universal em todo deployment. MTC /add-tbs não é aceito como log genérico de eventos.

Config: owner/workspace; read_url/write_url HTTPS no mesmo origin; checkpoint origin; log verifier key; witnesses `{key,url}`; witness_quorum **≥1**; TLS pins; leaf bound ≤65535 (EntryBundle framing). Pubkeys de witnesses precisam ser distintos entre si e do log, incluindo mesmo material com nome diferente. Verificação usa parsers oficiais de ML-DSA/CosignatureV1, não contador de strings de assinatura.

- `connect()`: inicia helper client; não inicia log/witness/server.
- `initialize_trust(checkpoint=bytes)`: SDK valida checkpoint assinado, origin e quorum antes de persistir anchor. Seed vem do operador/verificador; não há root de JSON automaticamente confiada.
- `publish(key)`: persiste a tentativa e previous checkpoint/scan start antes de `POST /add` do leaf real. Índice decimal confirmado vira PENDING_INCLUSION; não afirma inclusão/quorum ainda.
- `observe(key,max_scan=256)`: usa índice persistido ou busca **bounded** em entry bundles a partir do checkpoint anterior, quando índice se perdeu. Nunca repete add. Falta na janela observada não comprova ausência definitiva.
- Client lê checkpoint/tiles/entry bundles com fallback partial→full, conforme tlog-tiles e SDK oficial; compara leaf bytes; constrói e valida RFC6962 inclusion/consistency; confirma assinatura do log e quorum dos witnesses sobre o mesmo checkpoint.
- Rollback, mesmo tamanho com root divergente, invalid inclusion, entry mismatch ou quorum incompleto persiste divergence e mantém head anterior. Não assume que LogStateTracker silenciosamente retornando a anterior provou consistência de um rollback.
- Receipt confirmado contém índice/tree size/root/proof artifact/source digest e quorum. Prova JSON é somente **envelope dos bytes/nodes/checkpoints**; o SDK realiza a verificação criptográfica.
- `verify(key)` reabre bytes retidos e executa verify_offline no helper oficial, sem requests ao log. Reconfere body binding, notas, witnesses e Merkle proofs. status() lê checkpoint nativo; close() fecha transporte.

Deployment pendente: log Tessera real com profile Add/tiles, armazenamento persistente, assinatura de checkpoint, witnesses/mirrors independentes e publication policy que obtenha cosignatures. Clone conformance é base real de API, mas exige operador colocar HTTPS/autenticação e política de witnesses adequada. URLs de witnesses configuradas não provam que estão online; somente suas assinaturas verificadas satisfazem quorum. Source entry inclusion não comprova cobertura total de efeitos reais.

## immudb: transações verificadas e estado durável

`ImmudbAuditProvider(config=ImmudbAuditConfig(...), store=..., executable=..., executable_sha256=..., credential_provider=..., enabled=True)` usa o SDK/schema nativos do clone. Config owner/workspace, HTTPS gRPC endpoint com porta, database, server UUID, ECDSA signing pubkey path+SHA e TLS pins; credenciais username/password via callback.

- `initialize_trust(immutable_state_protobuf=bytes)`: seed nativa aprovada pelo operador; não constrói ImmutableState de JSON e não adota CurrentState automaticamente. Bytes/DB/hash/signature são conferidos antes da primeira escrita. Para genesis, operador precisa confirmar DB vazio e fornecer protobuf válido TxId=0/hash de 32 bytes; primeiro novo state ainda exige assinatura do signing key pinado.
- `publish(key)`: OpenSession nativa; verifica UUID do server em metadata oficial Health; VerifiableSet com KeyMustNotExist atômico e ProveSinceTx do anchor. Mesmo event key não é sobrescrito. Perda de resposta conserva UNKNOWN; não chama Set outra vez.
- VerifiableGet liga entry/key/value/AtTx, inclusion proof, target/source header IDs, dual proof, linear advance completo e assinatura do novo ImmutableState. SDK FillMissingLinearAdvanceProof obtém partes necessárias e a prova completa é serializada para conservação/offline. Não implementar a checagem vulnerável que aceita só linear terms sem o restante do dual proof.
- `observe(key)` consulta o key existente e verifica a prova contra o head persistido atual. Não cria outra transação. NotFound/indisponível não é licença para repetir write.
- Proof protobuf bytes, previous signed state, native tx/database/UUID e new signed state são guardados; trusted head+receipt avançam numa transação CAS. Divergência/backpressure/crash não promovem JSON boolean a proof.
- `verify(key)` faz revalidação offline pelo helper com inclusão/dual/linear-advance/signatura reais, usando artifact protobuf e source anchor. Não precisa de sessão remota.
- `export_transaction(key)` chama VerifiedTxByID + ExportTx com allowPreCommitted=false, skipIntegrityCheck=false. Export restrito a **transação audit de uma entry**; decoder nativo compara header/ALH, encoded key, metadata, SHA/value e flag de truncation contra a transação verificada. Persiste referência do export artifact no receipt. Não chama ReplicateTx ou afirma restauração de todos os artefatos SENTRA.
- `status()` lê estado assinado do DB real sem inicializar trust automaticamente; close encerra helper. Sessões RPC usam deadlines e CloseSession bounded.

Deployment pendente: immudb real com TLS, database/account dedicado ao scope, signing key configurado, UUID pinado e seed confiável do operador. TLS sozinho ou CurrentState JSON não dá evolução verificada. Migrar signing key/UUID/profile exige nova decisão explícita de trust e provas, não apagar estado anterior. Backup/restauração do SENTRA inteiro continua trabalho coordenado do núcleo; este cliente fornece committed exports audit e referências verificáveis.

## Build, testes e aceitação futura

**Comandos abaixo não executados.** Não usar a existência dos arquivos como sucesso operacional.

```powershell
$env:GOTOOLCHAIN = 'local'
Set-Location C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_runtime/audit_provider_sdk
go mod tidy
go build -trimpath -o C:/SENTRA/bin/sentra-audit-provider-sdk.exe .
```

Toolchain Go 1.27.1, módulos de nats.go/Tessera/immudb e transitive deps são pré-requisitos. go mod tidy pode acessar rede; aguardar validação final autorizada. Conferir source HEADs, revisar go.sum e pin do binário/manifest. Código do helper realiza requests **apenas quando explicitamente iniciado/chamado**, sem instalar serviços ou fabricar backend compatível.

```powershell
python -m pytest tests/unit/test_sentra_runtime_audit_delivery.py tests/unit/test_sentra_runtime_nats_jetstream.py tests/unit/test_sentra_runtime_audit_external_proofs.py -q
```

Testes de JSON/wire são protocol fixtures **explicitamente marcadas**, sem servidor falso nem sucesso criptográfico de mock. SQLite/proteção são reais. Positive proof só está nos opt-ins com binário SDK real e artifact/server reais:

- `SENTRA_ACCEPTANCE_NATS_PROFILE`: config NATSJetStreamConfig, executable/SHA, protected_credentials DPAPI/keyring. Opcional allow_resource_administration=true somente por perfil do operador. Requer broker/recursos/ACL reais; sem perfil, skip.
- `SENTRA_ACCEPTANCE_IMMUDB_PROFILE`: config ImmudbAuditConfig, executable/SHA, protected_credentials e trusted_state_protobuf_file nativo aprovado. Efetua transação/read/proof/export no DB audit selecionado; sem perfil, skip.
- `SENTRA_ACCEPTANCE_AUDIT_PROOF_PROFILE`: provider tessera ou immudb, configuração SDK concreta, executable/SHA, protected_credentials e verification_payload_file com prova autêntica retida. Verifica offline e depois adultera leaf/value para exigir rejeição. Sem artefatos reais, skip, sem validator mock retornando verified.

Aceitação externa ainda obrigatória: queda de rede antes/depois do PubAck; duplicate fora da janela do broker; crash entre inbox commit e AckSync; backpressure/MaxDeliver/retention/replay; revogação de credenciais e isolamento owner/workspace; Tessera inclusão/consistência/quorum/fork/índice perdido; immudb prova inválida, rollback, perda de commit response e re-observação; export/restauração de audit sob seed confiável. Verificar também cancelamento/cleanup e integração com a evidência central real. Estas provas **não foram executadas nesta rodada**.

## Integração solicitada ao coordenador

Fornecer owner/workspace/credentials derivados do host autenticado; instanciar providers/config/pins e store; conectar somente após provisionamento aprovado; chamar enqueue_entry/head no source já instrumentado; consumir references/public_metadata e registrar os receipts na evidência central existente. Barramento deve acionar observação/projeção autorizada, nunca executar notificações como comandos ou criar novos Run/WorkItem/Operation/grants. Ligar callbacks de revogação/close, endpoints/ACL, manutenção de retenção/arquivamento e observabilidade. Nenhuma edição do host central foi feita por esta frente.

Lacunas residuais explícitas: helper ainda não compilado; módulos/go.sum e serviços/tokens/TLS/witnesses não provisionados; provas operacionais não obtidas; Tessera write profile precisa corresponder ao deployment real; failover automático/cluster endpoints não pinados permanecem desabilitados; DLQ remota e restore/replicação completa não são implementados implicitamente; nova trust/key rotation exige procedimento do operador; instrumentação global e alias bindings do host continuam com o coordenador.
