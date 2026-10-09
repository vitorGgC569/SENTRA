# Rodada 4 — identidade, ReBAC, bundles e SPIRE

Implementação de 09/10/2026, baseada nas seções 20–23 da reavaliação37. **Nenhum teste, build, validação de política, login, contato externo ou serviço foi executado/iniciado nesta rodada.** Os testes e comandos abaixo são handoff para a validação conjunta final. O objetivo integral37 permanece em andamento.

## Fontes locais consultadas

| Projeto / HEAD | Contrato derivado |
| --- | --- |
| SPIRE `9dbd864e89239e1228246be486874eea69d3c81f` | `pkg/agent/endpoints/workload/handler.go`: FetchX509SVID/FetchJWTBundles subscriptions, FetchJWTSVID e ValidateJWTSVID, atestação no contexto de peer; `cmd/spire-agent/cli/api/watch.go` e `fetch_x509.go`: SDK WatchX509Context e x509svid.Verify; `pkg/common/util/addr_windows.go`, `addr_posix.go`, `cmd/spire-agent/cli/api/common.go`: named pipe/Unix socket, gRPC oficial e metadata `workload.spiffe.io=true`. |
| Keycloak `c7de391ae4d8a83ad62b8386cab85d37fbb6324c` | OIDCWellKnownProvider, TokenRevocationEndpoint, LogoutEndpoint, StandardTokenExchangeProvider, docs de token exchange e realm de teste V2: discovery, autenticação de client, PKCE, revogação, logout e exchange access→access para audience. |
| OpenFGA `526995eb202464e2cace266fb5be56c212af9ecf` | commands/list_objects.go, read_changes.go, assertions.go e testes Check/ListObjects: modelo fixado, consistência explícita, páginas de changes, assertions isoladas. |
| OPA `4dcda5da919a9cb6174b4998c6304f37783d8f21` | cmd/check.go/eval.go, v1/bundle/store.go, plugins/bundle/plugin.go, plugins/logs/plugin.go e docs locais: validação CLI oficial, ativação transacional, data.system.bundles[name].manifest.revision, status POST e máscara dos logs. |

## Limite de autoridade e arquivos

CorePDP continua a fonte de autorização. Identidade autenticada não cria grants, roles de JWT não viram capabilities, ListObjects não autoriza efeitos e OPA/OpenFGA só restringem uma decisão CorePDP já permitida. Os vetos novos preservam **constraints do CorePDP**, para o host aplicar sua validação física existente, e não substituem lease/fence/authority. Não foram editados central_authority, effect_boundary, authority_bridge, machine_host, Canvas, quality, executores ou workflows nesta rodada.

Arquivos alterados/criados:

| Área | Arquivos |
| --- | --- |
| Transporte e clientes existentes | `sentra_runtime/_policy_http.py`, `keycloak_identity.py`, `openfga_rebac.py`, `opa_pdp.py` |
| Lifecycle/persistência | `sentra_runtime/identity_state.py`, `keycloak_provider.py`, `policy_bundle.py`, `spire_identity.py` |
| Cliente SDK SPIFFE | `sentra_runtime/identity_spire_sdk/go.mod`, `main.go`, `transport_windows.go`, `transport_posix.go` |
| Templates concretos | `sentra_runtime/policy_identity_examples/keycloak-realm.json`, `opa-config.yaml`, `spire-agent-windows.conf`, `opa_bundle/.manifest`, `opa_bundle/sentra.rego` |
| Testes preparados | `tests/unit/test_sentra_runtime_identity_lifecycle.py`, `test_sentra_runtime_policy_lifecycle.py`, `test_sentra_runtime_spire_identity.py` |
| Handoff | Este documento |

`ProtectedIdentityStore(database, workspace=..., namespace=...)` usa a proteção DPAPI/keyring já existente, digest e CAS. Guarda somente projeções de sessão/política/cursor. Não contém Run, WorkItem, Operation, grant, reserva, lock ou lease. Nenhum fallback plaintext foi introduzido. O host deve proteger cookie/session IDs e endpoints de gerenciamento; não derivar o session_id de arguments do agente.

## Keycloak OIDC efetivo

```python
config = KeycloakOIDCConfig(
    issuer=realm_issuer, client_id=client_id, audience="sentra-api",
    redirect_uri=host_callback_uri,
    scopes=("openid", "profile"), exchange_audiences=("connector-api",),
    revocation_strategy="introspection",
)
verifier = PinnedKeycloakJWTVerifier(
    issuer=config.issuer, audience=config.audience,
    pinned_jwks=owner_verified_jwks,
)
oidc = KeycloakOIDCProvider(
    config=config, verifier=verifier, store=identity_store, enabled=True,
    client_secret_provider=read_protected_client_secret,
    on_invalidate=close_host_connections_for_identity,
)
identity_veto = KeycloakSessionVeto(
    oidc, trusted_session_id=current_authenticated_host_session,
    core_pdp=core_pdp,
)
```

Constructors não fazem requests. Métodos públicos síncronos usam HTTP/TLS real e bounded quando explicitamente chamados pelo host. Endpoints descobertos são conferidos contra o realm origin e os caminhos Keycloak efetivos; não se seguem redirects, proxies de ambiente ou endpoints arbitrários enviados pelo discovery.

| Interface | Efeito/contrato |
| --- | --- |
| `discover()` | GET realm `/.well-known/openid-configuration`; issuer, endpoints e S256 precisam coincidir; client_secret_post precisa ser anunciado quando configurado. |
| `fetch_jwks_candidate()` | GET `/protocol/openid-connect/certs`; valida a estrutura criptográfica e retorna candidate/digest, **não troca automaticamente o verificador**. |
| `begin_login(browser_binding=..., prompt=None)` | Grava nonce/state/PKCE protegidos e retorna authorization_url; não abre browser nem faz login. prompt consent pode pedir consentimento real. |
| `complete_login(state=..., code=..., browser_binding=...)` | Consome state antes do POST token; verifica binding do browser, PKCE, ID token nonce, issuer, sub, azp, audience, sessão. Code com resposta perdida não é repetido. |
| `authenticate(session_id)` | Verifica JWT, perfil, subject, SID revogado, cutoff de subject, validade estrita e estratégia de revogação; retorna AuthenticatedPrincipal. |
| `refresh(session_id)` | Fase REFRESHING persistida antes do POST; credencial rotacionada não é replayed em resposta perdida; fase UNCERTAIN bloqueia novas admissões. CAS e SID markers impedem ressurreição após logout concorrente. |
| `token_exchange(session_id, audience=..., scopes=...)` | RFC8693 Keycloak V2 access→access, audience/scopes allowlisted, principal inalterado; retorna ExchangedAudienceCredential. Sem impersonação ou troca arbitrária de subject. |
| `logout(session_id)` | Invalida localmente antes do POST logout com refresh token; remote ACKNOWLEDGED/UNCERTAIN é separado do bloqueio local. |
| `revoke(session_id, token_kind="refresh"|"access")` | Invalida antes de chamar `/revoke`; ausência/falha de provider não restaura a sessão. |
| `backchannel_logout(logout_token)` | Valida assinatura/issuer/aud/client, evento oficial, ausência de nonce, iat recente e jti; aplica SID/subject cutoff e dedupe persistidos. |
| `recover_backchannel_logout(jti)` | Completa somente um evento já autenticado e persistido; não aceita claims/seletores não verificados. |
| `retry_invalidation_notifications()` | Reentrega ao host notificações REVOKED pendentes, sem repetir login/refresh/effects externos. |
| `session_status(session_id)` | Diagnóstico sem tokens; locally_active é elegibilidade local, não permissão de Operation. |

Principal estável: `principal_id(issuer, subject, kind="oidc")` produz `oidc-<sha256 do issuer/sub>`. O mesmo usuário mantém ID durante refresh/exchange; realm diferente com mesmo sub não se confunde. O host registra/vincula esse principal no seu cadastro e fornece grants normais através do CorePDP; roles/groups do token não são importados como grants. `KeycloakIdentityVeto` antigo permanece para o modo legado de raw token/sub; o lifecycle novo usa `KeycloakSessionVeto` e o ID com namespace de emissor.

Revogação:

- **introspection** é o padrão: cada authenticate consulta `/token/introspect` com client confidential. Falha, inactive ou incompatibilidade nega. Token local com assinatura válida não dispensa essa consulta.
- **local_session** é opção explícita quando o host integra backchannel/logout e aceita seus limites de entrega. Não promete revogação externa imediata se a notificação não chegou. O endpoint de backchannel do host deve chamar o verificador antes de aplicar qualquer evento.
- on_invalidate recebe `(principal_id, session_id, reason)` e deve retirar conexões/admissões abertas no host. Falha de entrega fica persistida para retry; não se declara que conexões já foram encerradas. O fence/lease do host deve reconsultar sua política normalmente.
- Tokens com holder proof `cnf`, actor/delegation `act`/`may_act`, algoritmos alternativos ou audience errada são recusados neste perfil RS256 bearer. Não se apresenta suporte DPoP/mTLS token-bound sem prova correspondente.

`ExchangedAudienceCredential.access_token`, `JWTWorkloadCredential.token` e private key são secretos: repr é mascarado; use `public_metadata()` para evidence/log. Não serializar `asdict()` de credentials nem devolver tokens em payload de Operation. O host utiliza tokens apenas na conexão scoped destino correspondente.

Deployment necessário: Keycloak existente HTTPS, realm/client confidential com PKCE, redirect URI exata, secret em armazenamento protegido, audience mapper e endpoints do host. O template realm importa **somente configuração**, não usuários/grants/secrets; `.example.invalid` deve ser substituído pelo operador. Provisionar client secret após import, audiência/target client para connector-api e consent/client scopes reais. V2 exige switch `standard.token.exchange.enabled` no requester confidential conforme o clone. Nada foi importado ou iniciado.

## OpenFGA descoberta, mudanças e assertions

`OpenFGACheckClient(endpoint=..., bearer=..., store_id=..., authorization_model_id=..., timeout_s=1.5, allow_remote=False, consistency="HIGHER_CONSISTENCY", subject_type="agent", http=None)` fixa store/model/type. Legacy endpoint permanece literal HTTP loopback; HTTPS externo requer `allow_remote=True`, opt-in no host e TLS verificável. `http` é injeção de transporte trusted/test, não dado de request.

`allows(request=...)` sempre faz Check real com HIGHER_CONSISTENCY, `subject_type:principal_id`, relação can_execute e work_item:ID. Não envia `request.arguments.contextual_tuples`. Model ID não vem do agente. `OpenFGADenyVeto(core_pdp, client)` consulta somente após CorePDP allow e o reconfirma após a consulta, preservando suas constraints.

| Interface | API oficial |
| --- | --- |
| `list_objects(principal_id=..., object_type=..., relation=..., consistency=None)` | POST `/stores/{store}/list-objects`, user/type/relation/model/consistency. Retorna RelationshipDiscovery com authorizes_effects=False. |
| `read_changes(object_type=None, continuation_token="", page_size=100, start_time=None)` | GET `/stores/{store}/changes`; cursor opaco scoped e bounded, timestamp/type/página. StartTime somente na primeira página. |
| `read_assertions()` | GET `/stores/{store}/assertions/{pinned_model}`. |
| `evaluate_assertions()` | Executa Check das assertions configuradas nesse modelo; exige casos não vazios. Contextual tuples de **assertions do servidor** ficam somente nessas avaliações isoladas e não entram em live admission. |
| `write_assertions(assertions, trusted_admin_authorize=...)` | PUT da API oficial, somente quando callback de administração do host autoriza `(store, model, "write_assertions")`. Não escreve tuples, modelos ou grants. |

`OpenFGADiscoveryProjection(client, store=..., object_type=..., on_invalidate=None)`:

- `discover(principal_id=..., relation=..., core_authorize_resource=...)` filtra os candidates OpenFGA pela decisão CorePDP real de cada recurso. Callback `(principal_id, resource_id) -> PolicyDecision`; apenas allowed=True aparece. O catálogo pode ser truncado pelo limite ListObjects do servidor e não concede acesso.
- `poll_changes()` lê a próxima página, chama invalidação, depois persiste cursor/generation por CAS. Perda de callback/commit pode repetir **invalidação idempotente**, nunca emitir grants ou efeitos de máquina. Leases/operations continuam centrais.
- UI pode usar MINIMIZE_LATENCY via list_objects direto; admissão sensível não reaproveita esse snapshot/cache. HIGHER_CONSISTENCY evita os caches configuráveis do servidor; não se afirma consistência global além da semântica real do deployment/datastore.

Deployment pendente: OpenFGA real, datastore, autenticação HTTPS/service token, store/model pinados, tipos/relações compatíveis (agent/user/service e work_item). Por exemplo, principals OIDC humanos devem ter `subject_type="user"` e relações correspondentes; a identidade não gera essas relações automaticamente. Model assertions e relation mutation precisam de administração explícita, fora do cliente de discovery.

## OPA bundles e decisões auditáveis

```python
validator = OPAOfflineValidator(
    executable=absolute_opa_binary, executable_sha256=approved_binary_digest,
    capabilities_file=offline_capabilities_json,
    capabilities_sha256=approved_capabilities_digest,
)
bundles = OPABundleManager(
    root=bundle_root, workspace=workspace, store=policy_store,
    validator=validator, bundle_name="sentra", roots=("sentra",),
)
opa = OPAClient(
    endpoint=opa_endpoint, bearer=opa_service_secret,
    decision_path="/v1/data/sentra/decision",
    active_revision=bundles.active_revision,
    audit_sink=masked_host_event_sink,
)
veto = OPADenyVeto(core_pdp, opa, trusted_workspace_id=workspace_id)
```

`OPAClient.decide(request=..., workspace_id=...) -> OPADecision(allowed, revision, decision_id, creates_grants=False)` exige result `{allow: bool, revision: str}`; reason_code opcional nunca é exportado cru. Result indefinido, erro ou revision diferente da confirmada antes/depois da chamada nega. OPA decision_id é retornado somente quando veio do daemon; não é inventado. `/v1/data/sentra/allow` legado boolean permanece compatível, mas não tem a evidência de revision do perfil novo.

Audit sink recebe apenas provider/allowed/revision/decision_id/Operation/capability e digests de principal/machine/WorkItem. Não recebe arguments, input cru, bearer ou resposta arbitrária. O exemplo Rego também configura máscara oficial `/sentra/log_mask` para apagar input/result/request_context/nd_builtin_cache nos logs nativos, preservando metadados de bundle/decision ID. O host ainda deve autenticar a ingestão dos logs e registrar somente campos permitidos em sua telemetria; logs não viram ledger de autorização.

Bundle lifecycle:

1. `stage(archive, expected_sha256=..., expected_revision=...) -> OPABundleCandidate`: archive absoluto bounded; sha exato; snapshot manifest revision/roots/rego_version; sem traversal, symlinks, hardlinks, delta/foreign roots ou duplicações. Não extrai arquivos arbitrários.
2. `await activate(candidate, acceptance_cases=..., trusted_admin_authorize=...)`: callback CorePDP/deployment confirma `(bundle_name, revision, sha256)`; **quando for chamado na validação final**, executa binário OPA pinado `check --bundle --strict` e `eval --bundle --stdin-input --format=json` para casos positivos/negativos. Cleanup owned e checkpoint físico quando dentro do contexto do host.
3. Só depois de check/casos reais passa a publicar archive validado por ponteiro CAS. Candidate inválido/dependência ausente preserva a última válida. A mesma revision não pode ser reutilizada para bytes distintos. Uma publicação pendente não é sobrescrita por outra.
4. `resource()` devolve body/content_type/ETag/revision para **route autenticada existente do host**. OPA bundle plugin a busca conforme seu contrato nativo, não se inventa endpoint de upload/activation.
5. `accept_status(status, trusted_instance_authorize=...)` consome POST status oficial autenticado. **Labels de status não são prova de identidade**; callback precisa ser fechado sobre authn/mTLS/bearer estabelecido no host. Só active_revision correspondente sem erro confirma a ativação. Se o daemon rejeitar candidate e informar a anterior ainda ativa, restaura publicação anterior.
6. `active_revision()` retorna somente a revision **confirmada no daemon**; `published_revision()` informa o candidate publicado. Enquanto a revisão anterior ainda está ativa, ela continua utilizável. Janela de troca sem status confirmado nega a nova revision.

As capabilities offline do OPA devem ser um arquivo oficial gerado para o binário e filtrado pelo operador, excluindo http.send, net.lookup_ip_addr, time.now_ns, uuid.rfc4122, rand.intn. Isso impede aceitação offline de política que faça rede ou invente valores não determinísticos nesses builtins. O digest do archive é um pin aprovado no host; não se afirma verificação JWS OPA de bundle assinado se não foi configurada a cadeia de assinatura. Para deployments que exigem assinatura, adicionar signing/verification do plugin oficial ao provisionamento; não tratar SHA como assinatura de publisher externo.

O template `opa-config.yaml` configura bundles/status/logs reais para o serviço do host. Servir body gzip em `/policy/bundles/sentra`, receber POST `/policy/status` e `/policy/decision-logs`, com autenticação real e secret protegido. O daemon `/v1/data` também precisa de autenticação/authorization do operador. Nenhuma dessas routes/serviço foi iniciada aqui; o coordenador liga ao host existente.

## SPIRE Workload API real e renovação

O clone pinou `go-spiffe/v2 v2.8.2`; helper Go usa essa dependência oficial, gRPC v1.84.0 e go-winio v0.6.2. O helper não é SPIRE server/agent e não cria sua própria Workload API. É um cliente owned com stdin/stdout privado entre host e helper. Construção e dependências ainda não foram compiladas/baixadas nesta rodada; go.sum deverá ser produzido e revisado no provisionamento final, sem fingir que módulos ausentes estavam disponíveis.

**SPIRE real versus contratos:** há implementação de transporte/cliente oficial concreta, com chamadas gRPC ao Workload API, verificação x509svid.Verify e subscriptions; não é só uma interface ou callback placeholder. Entretanto, nenhum helper foi compilado/conectado a um agente real e nenhuma atestação/renovação externa foi comprovada nesta fase. Os testes de decoder são contratos explícitos; prova operacional depende do build pinado, agente/server/registrations reais e aceitação final.

**O processo atestado é o helper SDK**, identificado pelo peer PID/SID/path/hash no agente; não se afirma que o PID Python que o iniciou recebeu a mesma atestação. O host assume esse cliente trusted como seu provedor de identidade. Registrar o helper real no SPIRE com os seletores observados pelo agente; não enviar seletores alegados no login/Operation/IPC. Go decoder recusa campos desconhecidos e só recebe endpoint, expected IDs, audiences e TTL do perfil host.

```python
config = SpireWorkloadConfig(
    executable=owned_sdk_helper_binary,
    executable_sha256=owner_verified_helper_digest,
    endpoint="\\spire-agent\\public\\api",  # Windows pipe NAME
    expected_spiffe_ids=("spiffe://sentra.example/host",),
    trust_domains=("sentra.example",), audiences=("sentra-api",),
    max_ttl_seconds=300,
)
client = SpireWorkloadIdentityClient(
    config, enabled=True, on_identity_change=host_identity_rotation_callback,
)
# Somente na etapa de bootstrap autorizada APÓS validação final:
await client.start(timeout=10)
identity = client.authenticate(config.expected_spiffe_ids[0])
veto = SpireIdentityVeto(
    client, trusted_spiffe_id=config.expected_spiffe_ids[0], core_pdp=core_pdp,
)
```

No POSIX, endpoint é path absoluto Unix socket. No Windows, é nome do named pipe local; não aceita pipe SMB remoto/TCP. O SDK usa WatchX509Context oficialmente, verifica SVID/chain pelo x509svid.Verify, exporta PKCS8 privado somente pelo IPC owned e subscription continua a renovar cert/bundles. Python confere URI exata, key↔cert, TTL, intervalos e trusted domains e troca snapshot atomicamente. Identidade é estável `spiffe-<sha256 do trust-domain/ID>`, independentemente de key/cert renovados.

Métodos reais:

- `await start(timeout=...)`: verifica hash do binário, inicia apenas helper cliente owned e aguarda credencial real; dependência/atestação ausente falha, sem SVID placeholder.
- `credential(spiffe_id) -> X509WorkloadCredential`: host usa cert/private key para sua conexão mTLS; expiração de leaf e caminho de confiança bloqueia novos usos. repr/public_metadata não revelam key.
- `authenticate(spiffe_id) -> AuthenticatedPrincipal`: consulta snapshot válido; não concede capability.
- `await jwt_svid(spiffe_id=..., audience=...) -> JWTWorkloadCredential`: FetchJWTSVID e ValidateJWTSVID **oficiais no agente**, scope/audience/TTL configurados, sem JWT autoassinado. Não aceita token/selector/PID do caller como atestação.
- `trust_bundles()`: X509/JWT bundles obtidos do Workload API, incluindo somente domínios/federação explicitamente configurados; JSON devolvido por cópia, sem mutação do cache.
- `await close()`: cancela subscriptions/pending calls e limpa grupo/job owned; erro de watch/disconnect remove identidade utilizável, não preserva cache como autorização indefinida.

Callback on_identity_change recebe só disponibilidade, IDs/expiração e fingerprints públicos; fechar/reatar conexões é integração do host. O cliente não cria grants ou outra autoridade de Operation. Remoção de registro deve ser recebida pela subscription; credencial vencida jamais autoriza novo request mesmo se não houve evento de rede.

Deployment: SPIRE server/agent realmente provisionados, CA/bootstrap trust, NodeAttestor adequado e WorkloadAttestor Windows com discover_workload_path para path/sha selectors. O template Windows foi derivado do clone; SID/hash/path devem ser reais do helper configurado. Perfil com seletor só de user permite outros processos desse user; para isolar, operador usa SID **e** binary hash/path conforme o atestador oficial. Essas entradas são administração SPIRE, não claims enviados pelo cliente.

## Comandos e critérios para validação futura

**Não executados nesta rodada.** Rodar somente no fim da implementação integral coordenada.

```powershell
python -m pytest tests/unit/test_sentra_runtime_identity_lifecycle.py tests/unit/test_sentra_runtime_policy_lifecycle.py tests/unit/test_sentra_runtime_spire_identity.py -q
python -m pytest tests/unit/test_sentra_runtime_external_authority_phase3.py -q
```

Fixtures novas são explicitamente protocol fixtures. JWTs são assinados por chave RSA local de teste; decoder SPIRE usa cert local **sem comprovar atestação**; essas evidências nunca equivalem a IdP/OPA/FGA/SPIRE externo funcionando. DPAPI/keyring de verdade é pré-requisito da persistência; não há mock que simule criptografia/autoridade.

Build do cliente oficial, para provisionamento posterior (requires Go toolchain 1.27.1 da árvore atual e módulos disponíveis/aprovados):

```powershell
$env:GOTOOLCHAIN = 'local'
Set-Location C:/Users/vitor/OneDrive/Desktop/SENTRA/sentra_runtime/identity_spire_sdk
go mod tidy
go build -trimpath -o C:/SENTRA/bin/sentra-spire-identity.exe .
```

go mod tidy pode resolver dependências externamente; **não foi chamado agora**. Revisar/pinar go.sum e hash do binário antes de configurar o provider. Registrar o hash real do helper, usuário/SID e path no SPIRE. Bootstrap/agentes/server/realm e trust federation são tarefas do operador, não automação acionada pelo catálogo.

Opt-ins dos testes reais:

- `SENTRA_ACCEPTANCE_OPA_BINARY` + `SENTRA_ACCEPTANCE_OPA_CAPABILITIES`: executa CLI oficial real no teste de bundle. Sem esses paths, skip explícito. Não inicia daemon e não substitui o validator por mock que retorna sucesso.
- `SENTRA_ACCEPTANCE_SPIRE_PROFILE`: JSON com todos os campos de SpireWorkloadConfig, helper real e registro atestado. Usa Workload API real e fetch/validate JWT/bundle. Sem perfil, skip. `SENTRA_ACCEPTANCE_SPIRE_RENEW_WAIT_SECONDS=1..120` permite comprovar rotação real de cert/mesmo Principal com TTL curto; sem essa opção não afirmar que o teste observou renovação.

Aceitação externa pendente:

1. Keycloak: login real PKCE/nonce; consentimento; principal estável; audiência errada recusada; refresh concorrente com logout não reativa; introspecção inactive e backchannel cancelam novas admissões e acionam host; exchange audience específica sem mudança de principal.
2. OpenFGA: modelo real/assertions; alteração/delete de relação seguida de ReadChanges invalida UX; ação seguinte consulta HIGHER_CONSISTENCY e CorePDP; contextual tuple de agente nunca muda seu privilégio.
3. OPA: candidate inválido mantém publicação/ativação anterior; candidate válido passa casos e status oficial confirma revision; decision ID/revision auditáveis com dados mascarados; versão trocada durante operação provoca nova consulta/fail-closed pelo host.
4. SPIRE: processos de outro SID/hash não recebem ID esperado; X509/JWT curtos e renovação real sem principal instável; trust/federação fora do perfil recusada; expirado/removido/stream perdido nega nova operação; cleanup do helper em cancel/erro.

Integrações do coordenador: registrar Principal coerente e compor os vetos com CorePDP; callbacks de retirada de sessões/conexões; endpoints de login/backchannel e serviço de bundles/status/logs autenticados; operar/provisionar as dependências; validar fim a fim junto do fence/admission central. Nada deste handoff declara esses serviços ativos ou external acceptance concluída.
