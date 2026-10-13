# Forja — fechamento Selo (11/10/2026)

Fontes implementadas; composição e evidência operacional pendentes, sem
teste/build/install/lint/QA/benchmark. PID47408
preservado. Redistribuição e liberação explícita Nexo: authorization.py,
capabilities.py e guards Selo pertencem a Forja; sentra_runtime/core permanecem
Nexo. Canvas/service/HTTP/MCP/configurações raiz permanecem Codex.

## Contrato para composição cedo

Novo módulo de domínio `sentra_mcp.services.selo_composition`:
`build_client(*, host, control, owner, tenant_id, workspace_id, workspace_root, vault)` retorna
`SeloHostFacade`. Construção/configuração não inicia rede/processos/scanners.
`configuration(provider)`/`configure(provider, configuration,
expected_revision)` são server-only; CAS, referências vault, nenhuma senha/token
em DTO. `status()` é projeção local. `await dispatch(provider, action,
arguments, *, request_key)` exige contexto central já admitido para I/O e
preserva intenção/resultado incerto; não cria Grant. `await close()` encerra
clientes owned. O host deve passar owner/tenant/workspace autenticados; estes
campos não são argumentos do browser/agente.

Reserva Forja: novos `sentra_quality/protected_state.py`,
`provider_clients.py`, `audit_state.py`, `selo_composition.py` em services;
correções em authorization/policy_veto_chain/policy_identity_audit e demais
arquivos de qualidade/memory herdados. Estado configurado usa store central,
namespace provider_content, owner scope, codec DPAPI/keyring; PostgreSQL usa
schema/lock_key/db.raw e `%s`, sem ATTACH/SQLite fallback.

Providers opcionais continuam requisitos: OPA/OpenFGA/Keycloak/SPIRE,
Tessera/immudb, Langfuse/OTLP, Grype. Falta de configuração/binário/credencial
é indisponibilidade explícita, sem alegação operacional.

## Dependências externas e composição

Codex deve compor esta facade no center/shell/MCP mediante allowlist server-only
e autoridade central. Prisma/Pacto recebe candidate learning revisado com SHA,
manifesto/capabilities; ativação permanece central, com Grant preexistente.
Tessela/Vitra recebe pins/artefatos Grype e SDKs para pacote/SBOM/NOTICE. Helpers
Go e serviços/TLS/witnesses reais dependem de provisionamento futuro autorizado.

## Entrega final

### APIs disponíveis para Codex/Nexo/Prisma

```python
from sentra_mcp.services.selo_composition import build_client
selo = build_client(host=host, control=control, owner=owner,
                    tenant_id=tenant_id, workspace_id=project_id,
                    workspace_root=host_project_root, vault=vault)
selo.configure(provider, config, expected_revision=None)  # sync, host-only
selo.configuration(provider)                            # sync, host-only
selo.status()                                           # local; não faz health remoto
await selo.dispatch(provider, action, arguments, request_key=request_key)
selo.request_status(request_key)                        # nunca reenvia
await selo.close_provider(provider)                     # mantém fila/provas
await selo.close()
selo.policy(request, core_pdp=base_core_pdp, identity_binding=trusted_binding)
selo.enqueue(SafeTelemetryEvent(...), correlations=trusted_correlations)
selo.record_effect_boundary(context, phase="admitted" | "returned" | "uncertain")
selo.effect_coverage(run_id)
```

`workspace_id` é o ID lógico canônico do projeto. `workspace_root` é o PATH
absoluto derivado pelo host, conferido contra `Run.workspace`; ambos são
parâmetros server-only distintos. Cada WorkItem também precisa de
`metadata.workspace_id == workspace_id`. Não inferir ID do diretório ou aceitar
owner/tenant/principal/Grant/path do renderer. O dispatch é async
e deve rodar no loop do host dentro do `CentralEffectContext` existente, com
`context.authority.durable is control.durable`. Intenção exata:
`{provider, action, arguments, request_key}` em `OperationRequest.arguments` e
capability exata `selo.<provider>.<action>`. Não criar reserva paralela. Catálogo
gerado por `selo_capability_catalog()` em `capabilities.py`; as onze capabilities
`canvas.coordinator.dot_create/team_create/connect/delegate/handoff/pause/resume/
cancel/reassign/pause_dot/resume_dot` também foram adicionadas. Catálogo não é Grant.

Configuração exige `enabled: bool`, CAS obrigatório e somente `credential_ref`:

| Provider | Configuração real | Valor vault (só servidor) |
|---|---|---|
| OPA | endpoint, bundle_name, active_revision; opcionais bundle_root, validator (OPAOfflineValidator kwargs) | bearer string |
| OpenFGA | endpoint, store_id, authorization_model_id, subject_type | bearer string |
| Keycloak | oidc (KeycloakOIDCConfig kwargs), pinned_jwks | client secret string |
| SPIRE | workload (SpireWorkloadConfig kwargs; helper absoluto/SHA) | sem secret no config |
| Tessera/immudb | configuration (dataclass provider kwargs, sem owner/workspace), executable, executable_sha256 | dict SDK provider credenciais |
| Langfuse | endpoint, api_profile=langfuse-v3-dataset-runs, export_content explícito | `{public_key,secret_key}` |
| OTLP | endpoint, path=/v1/traces; batch_size/max_pending/retention_seconds/max_attempts/batch_delay_seconds | bearer string opcional |
| Grype | scan (GrypeScanConfig kwargs), sbom, expected_sbom_sha256, third_party_root, trusted_pins, fail_at | sem secret |
| Learning/Memory | enabled | sem secret |

TLS obrigatório fora de loopback literal; HTTP loopback exige `allow_loopback`
explícito. Nenhum proxy/redirect/retry implícito. `configure` não resolve vault,
não conecta daemon, não inicia helper, não executa scanner. Fechar provider antes
de trocar revisão. Configuração incompleta/desabilitada, vault/binary/callback
ausente e respostas inválidas têm indisponibilidade explícita.

Consumidores host obrigatórios, com implementação root/Nexo (não browser):

- `selo_identity_binding(owner=..., workspace_id=..., principal_id=...) ->
  {principal_id,kind[,session_id,browser_binding,spiffe_id]}`; kind é cadastro
  trusted. Browser/session binding é servidor, não parâmetro de ação.
- `selo_identity_authenticated(owner=...,workspace_id=...,session_id=...,principal=...)`
  vincula login autenticado; não cria grants. Session ID não volta no DTO.
- `selo_identity_invalidated(principal_id,session_id,reason)` fecha/retira
  conexões/admissões; notificação falha permanece no store Keycloak para retry.
- `selo_workload_identity_changed(event)` aplica queda/expiração/rotação SPIRE
  às conexões existentes; `selo_relationships_changed(owner=...,workspace_id=...,
  changes=...)` invalida projeções antes de persistir cursor FGA.
- `selo_audience_credential(credential)` consome credencial de exchange apenas
  na conexão da audience; o DTO devolve somente public_metadata.
- `selo_opa_instance_authorized(labels) -> bool` deve fechar sobre a autenticação
  HTTP/mTLS real do daemon; labels não provam identidade.

### Fluxos implementados

- OPA decisão revisionada consulta revision real no daemon antes/depois e
  reconsulta CorePDP; OpenFGA Check HIGHER_CONSISTENCY, descoberta WorkItem
  filtrada por workspace e grants atuais, changes/cursor CAS/invalidation e
  assertions reais. Keycloak usa PKCE/discovery/JWT pinado/introspection/refresh/
  logout/revoke/backchannel/exchange do cliente existente. SPIRE usa cliente
  oficial owned com subscriptions, SVID e bundles. Todos são veto após allow;
  constraints preservadas, sem roles JWT virando grants.
- Tessera/immudb usam SDKs oficiais existentes; store novo suporta PostgreSQL/
  SQLite configurado, outbox immutable, claim único, trusted head + receipt CAS
  atômicos, bytes de proof/export recuperáveis, quotas e divergências conservadas.
  `connect/initialize_trust/enqueue_operation/publish/observe/verify/export_transaction`
  onde pertinente. Seeds vêm de Artifact owner/Run/SHA aprovado, com identidade
  humana e capability exata. `proof_read` pagina bytes protegidos, não paths.
- Langfuse: prompts create/get/labels com versão real; datasets versionados por
  nome scoped + manifesto ambiente/provider/model/tools/verifier; inputs/outputs
  esperados pinados; `eval_run`, `eval_item` com Artifact da Operation real e
  QualityGate central ligado por evidence ID, custo central/model/provider,
  traces OTLP reais, dataset-run-items, scores tipados/correções humanas e
  `eval_compare` por sucesso objetivo/custo/latência/regressões. Conteúdo só sai
  com export_content explícito; telemetria de produto continua SafeTelemetryEvent.
- Fila persistente protegida: batch count/delay, limites, retenção, perda/counters,
  targets independentes OTLP/Langfuse. ACK não altera Operation. Após timeout fica
  UNCERTAIN; retry de trace é explícito e pode duplicar sinal, nunca efeito do
  agente. Dedupe tombstones conservados. Sem thread exportadora auto-start.
  O exporter local histórico Langfuse também foi corrigido para Basic public/
  secret key e OTLP real, com contexto central owner-scoped e sem redirects;
  o batch antigo com bearer/shape incorreto deixou de ser enviado.
- Learning: `propose` recebe operation_id/transcript_artifact_id/objective/ttl_s;
  origem/estado/fence vêm da autoridade. Texto original exato protegido, SHA e
  redigido separado. Review humano/CAS, validade/withdraw e candidato Skill com
  inventário SHA/manifesto/capabilities/revisão, sem ativação/grants. Ler origem de
  outro WorkItem exige Grant real scoped também na origem. Prisma/Pacto integra
  candidate em import/review/pin/activate normal; memória/review/custo não concedem.
- Memory: namespace/key e corpo protegido/CAS/TTL por workspace + WorkItem, com
  origem central. `cost_summary` consulta contabilização central, sem ledger de
  admissão/budget paralelo.
- Grype: scan real pinned, checkpoints periódicos/cancel/owned cleanup, inputs
  do operador, SBOM frozen, report blob e receipt protected. Release gate real
  source pins + SPDX/CycloneDX + SBOM/report digest + database freshness + threshold
  + ignoredMatches, fix recommendations/diff. Não executado nesta fase.
- BenchmarkSeloGate.acceptance_from_artifacts consome manifesto pinado e report
  AcceptanceRunner; confere reset/mode/environment, receipts/bytes da autoridade,
  capability do verificador independente, score e custo central. Não lança
  benchmark nem avalia fixture; apenas API preparada para fase final.

`reconcile/cancel/close` são ações exatas em todos os providers. Reconciliação
Tessera/immudb observa a identidade já tentada; Keycloak consulta login consumido;
Langfuse consulta objetos/scores existentes; Grype consulta receipt local. Sem
observador conclusivo, permanece UNCERTAIN e nunca resubmete. `request_status`
omite argumentos de recuperação (OAuth code etc.) e não executa efeito.

### Arquivos e guardas

Novos: `sentra_quality/{protected_state,provider_clients,audit_state,authority_guard,
learning_runtime,telemetry_state,eval_runtime,grype_runtime,effect_coverage}.py`,
`memory/protected_store.py`, `sentra_mcp/services/selo_composition.py`.

Alterados no ownership: authorization.py (ancestry via configured store, guard PG
único com locks sorted e rows FOR UPDATE, sem SQLite path; eventos INSERT sem NULL
identity; constraints; recheck após vetos), capabilities.py (catálogos exatos),
policy_identity_audit.py (mesmo authorize_with_vetos), policy_veto_chain.py
(boolean/provider estritos e erros sanitizados), learning_review.py (redactor
fail-closed/validade), langfuse_eval.py (boolean estrito), grype_scan.py
(checkpoint durante processo), source_gate.py (checkpoint por Git subprocess),
benchmark_selo.py (gate de receipts reais).

`policy_identity_audit`, `learning_eval`, `memory_costs`, `diagnostics` e
`grype_release` reexportam `build_client(**trusted_host_configuration)` para a
mesma implementação concreta. `TelemetryService(..., selo_client=selo)` ou
`compose_selo(selo)` aceita a facade real (não callable); enqueue/stats/diagnostics
usam fila/estado configurados e `await selo_dispatch(...)` exige intenção central.
Flush sync legado é recusado quando o client configurado está composto. Os
demais métodos históricos locais não se tornam hosted por importarem a facade.

Config/vault são reconsultados antes/depois dos efeitos; mudança/expiração exige
close e reautenticação explícitos. Fingerprints de credenciais ficam somente na
memória, fora de DTO/journal. Bridge SDK audit recebe o mesmo checkpoint real
antes de cada IPC, sem editar fontes de Nexo. Scope e resultados protégidos
usam receipts/artifacts do núcleo; não decodificam prova criptográfica por flag.

### Ajuste exato Codex-coordinator-contract — ID versus PATH

Aplicado ao `build_client`/constructor da facade e `CentralReferences`, que agora
recebem `workspace_root` host-only obrigatório. `_context`, policy veto,
descoberta e snapshot comparam `Run.workspace` ao root absoluto normalizado e
conferem o ID lógico em `WorkItem.metadata.workspace_id`. Coverage filtra também
as Operations pelo WorkItem com esse metadata, em vez de misturar projetos com
mesmo path. Learning/Memory/audit/evals/projeções e callbacks conservam
workspace_id como ID de projeto; não foi substituído por path. OPA bundle staging
fica contido no workspace_root host-derived. Root deve fornecer ambos e metadata
canônico também nos WIs de origem; ausência/incompatibilidade nega explicitamente.
Somente arquivos de ownership Forja foram editados; sem QA/preview/ask síncrono.

PG usa `schema(namespace)`, `lock_key(namespace)`, `db._begin`, `db.raw` com `%s`;
RLS owner/membership tenant/principal, reader sem write, codec antes da primeira
persistência. Namespaces existentes provider_content/durable/governance/
authorization; sem novo namespace Nexo, sem ATTACH/fallback. Backup configurado
inclui provider_content com heads/filas/proofs e referências keyring existentes.

### Pendências reais — não homologado

1. Codex compor facade/allowlist/callbacks acima em center/shell/MCP; Nexo ligar
   identidade/revogação à lista real de conexões e contexto físico já existente.
   HTTP/server/Canvas/runtime/core não foram editados por Forja.
2. Nexo: `policy_bundle.py` faz writes em stage/activation/resource e constructors
   auxiliares. A facade faz checkpoint antes/depois; guard por **cada** filesystem
   effect interno precisa ser incorporado pelo dono nesse helper. Não editei
   sentra_runtime para suprir isso sem acordo. Root não deve publicar rota de
   bundle/status sem auth daemon real e esse fechamento.
3. Root ligar `record_effect_boundary` também aos demais executores. A própria
   facade registra suas chamadas contra effect_started central; coverage confronta
   Operations reais e informa faltantes/incertas. Witness inclusão não demonstra
   cobertura de efeitos fora dessa instrumentação; audit_complete continua false.
4. Prisma/Pacto consumir candidate pela ativação central; callbacks/config root e
   serialização de operações/provas no bridge permanecem composição de seus donos.
5. Serviços externos, realms/models/bundles/TLS/vault/account, helpers SPIRE/audit
   Go com go.sum/toolchain/binário pinado, Grype/base/SBOM final/assinaturas e
   packaging/NOTICES com Tessela/Vitra não foram provisionados/executados. Manter
   requisitos opcionais completos, sem simular presença/health/prova.
6. Langfuse perfil de dataset runs v3 é declarado pelo clone; deployment deve
   suportá-lo. Migração v4/experiments demanda perfil próprio, sem alegar suporte
   por aceitar OTLP. A configuração rejeita perfil desconhecido explicitamente.
7. Stores/facades locais históricos permanecem para compatibilidade local; root
   deve usar a nova composição configurada em hosted. Nenhuma importação automática
   de estado legado/grants/identidades foi feita.

Progresso/assinatura/resultado publicados por arquivo para Codex/Meridiano e
Prisma/Nexo/Tessela; não foi usado ask-back síncrono conforme redistribuição.
Toda execução de testes/build/install/lint/QA/scanner/benchmark/providers,
concorrência/recovery/duas tenants/provas positivas e clean-install continua
dependendo da liberação final do root após todas as implementações integradas.
