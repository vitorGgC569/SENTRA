# Selo — entrega integral (política, identidade, auditoria, telemetria, memória, Grype)

Data: 2026-10-11. Fase: implementação integral; validação NÃO executada (ordem do usuário/Codex).

## Expansão 11/10/2026 — tasks/Selo.md (Meridiano, autorizado pelo usuário)

Ordem: learning revisado CF17/FF10; Langfuse real (traces, prompts version/labels/config,
datasets/run-items/scores/correções humanas ligado ao QualityGate e custo central, não só OTLP);
OTel queues/batch/retention/loss/redaction; Tessera/immudb verifier trusted state+witness e
cobertura de efeitos; Grype real pin/SBOM/freshness/diff. Contratos de revisão para Pacto e
telemetry/eval para Codex. Nada homologado; sem guests/runners/providers faltantes declarados
como presentes.

### Arquivos criados na expansão (domínio Selo)

- `sentra_quality/learning_review.py` — ReviewedLearningStore: propose (origem operation/work_item/run/
  intent_sha + escopo + resultado SUCCEEDED/FAILED + transcript original preservada redatada e
  limitada), review APPROVED/REJECTED com revisor + CAS, withdraw, get/list. `to_skill_files()` e
  `review_bundle()` geram candidato SkillPack SOMENTE de sugestão APPROVED, no formato de
  `SkillLibrary.review` (package SHA, inventário por arquivo, frontmatter, capability manifest,
  pré-condições de ativação). Nunca ativa Skill, nunca cria grant.
- `sentra_quality/langfuse_eval.py` — LangfuseEvalStore: prompts version/labels/config + ativação;
  datasets com ambiente/provider/modelo/tools/verifier; items com input/expected; runs fixando
  versões dataset+prompt, referência de QualityGate (registrada, nunca recalculada) e de custos;
  run items com trace_id/observation_id, output, latência e custo; scores tipados
  NUMERIC/CATEGORICAL/BOOLEAN/CORRECTION/TEXT + correções humanas (author + correction_of);
  `compare_runs()` sobre a mesma versão de dataset: sucesso objetivo, custo, latência, regressões
  e correções por tarefa. Scores são consultivos; QualityGate e orçamento seguem autoritativos.
- `sentra_mcp/services/learning_eval.py` — LearningEvalService (suggest/review/skill_candidate/
  skill_review_bundle + prompt/dataset/run/item/score/compare).

### Arquivos estendidos na expansão (domínio Selo, compatível)

- `sentra_quality/otel_langfuse.py` — OTelPipeline + OTelPipelineConfig (send_batch_size/
  send_batch_max_size/timeout, cardinality_limit, memory_limit_bytes, max_pending, retention_s,
  max_attempts): configure/config, enqueue com cardinality + memory-limiter + retenção, batch_plan
  (size/time), prune_expired, mark_flushed, stats com loss explícita por motivo, redact_diagnostic.
  SeloTelemetryExporter e comandos OTLP/Langfuse existentes preservados.
- `sentra_quality/audit_anchor.py` — trust state do verificador (save_trust_state/trust_state),
  verify_against_trust (monotonicidade + veredito SDK injetado; divergência e trust mantido em
  dúvida), witness_set/witness_check (chaves distintas, quorum ≥ 1; quorum 0 nunca testemunha),
  set_effect_coverage/coverage_report (fronteira instrumentada declarada; efeitos fora dela são
  explicitamente descobertos; inclusão prova registro, não completude).
- `sentra_quality/release_gate.py` — check_database_freshness (ausente/inválida/futura/obsoleta
  nega), fix_advice (corrigível com fixed_versions vs sem correção, estados Fix), diff_scan_receipts
  (introduced/resolved/changed), verify_release com `database_built`, `max_database_age_hours`,
  `sbom_producer` e `previous_receipt` opcionais + bloco freshness/fix/diff no resultado.
- `sentra_mcp/services/policy_identity_audit.py` — trust_save/trust_get/trust_verify,
  witness_set/witness_check, coverage_set/coverage_report.
- `sentra_mcp/services/diagnostics.py` — pipeline_configure/pipeline_stats/pipeline_prune.
- `sentra_mcp/services/grype_release.py` — decide com freshness/diff/producer; freshness() e diff().
- `sentra_mcp/services/capabilities.py` — flags learning_review, langfuse_eval, otel_pipeline,
  audit_trust_witness, grype_freshness_diff.
- `sentra_quality/diagnostics.py` — seções learning (contagens por status) e otel_pipeline.
- `sentra_quality/__init__.py`, `sentra_quality/__main__.py` — exports +
  `selo-learning-propose/review/skill`, `selo-eval-compare`, `selo-pipeline-stats`,
  `selo-release-verify --database-built/--max-db-age-hours/--previous-receipt`.
- `tests/unit/test_selo_learning_langfuse.py` — esqueleto para validação futura, não executado.

### Contratos publicados na expansão

Para **Pacto** (SkillPack, sem editar `skill_library.py` — dono Pacto):
`LearningEvalService.skill_review_bundle(owner, suggestion_id)` devolve
`{package_id, name, description, source: "selo-learning:<id>", git_sha: None, frontmatter,
files: [{path, sha256, bytes}], capability_manifest, executable: False, grants_created: False,
activation_requires: [operator_review, sha_pin, capability_manifest, preexisting_grant]}`.
Ativação SOMENTE via `SkillLibrary.activate/upgrade_activation` após review + SHA + manifesto +
grant preexistente, em WorkItem ativo. Nenhuma publicação automática de aprendizado.

Para **Codex** (composição central, sem editar `server.py`/`service.py` — dono Codex):
`LearningEvalService` (prompts/datasets/runs/scores/compare + gate/cost por referência),
`DiagnosticsService.pipeline_*` (filas/batch/retenção/perda), `PolicyIdentityAuditService.trust_* /
witness_* / coverage_*` (AuditHost/config/dispatch/delivery/proofs), `GrypeReleaseService`
(pin/SBOM/freshness/diff do pacote final).
```python
from sentra_mcp.services.learning_eval import LearningEvalService
eval = LearningEvalService(state_root)
bundle = eval.skill_review_bundle(owner, suggestion_id)   # -> Pacto SkillLibrary
run = eval.eval_run_create(owner, dataset_name=..., dataset_version=...,
                           prompt_name=..., prompt_version=...,
                           gate={"passed": ..., "reason": ...},  # referência central
                           cost={"record_ids": [...]})           # referência central
report = eval.eval_compare(owner, run_a=..., run_b=...)
```

## Escopo exclusivo implementado

OPA/OpenFGA/Keycloak/SPIRE (vetos deny-only), Tessera/immudb (âncoras verificáveis),
telemetria OpenTelemetry/Langfuse (somente eventos sanitizados), memória/custos/diagnósticos
(projeções com CAS) e Grype (release gate ligado a proveniência + SBOM).

## Arquivos criados (domínio Selo)

- `sentra_quality/policy_veto_chain.py` — PolicyVetoChain deny-only sobre allow prévio do CorePDP;
  preserva constraints; falha fechada em erro/tipo.
- `sentra_quality/identity_registry.py` — Principal estável OIDC/SPIFFE, sessões como projeção
  (sem persistir segredos), `creates_grants=False`, `authorizes_effects=False`.
- `sentra_quality/audit_anchor.py` — AuditAnchorStore: trust explícito, avanço por CAS com receipt
  confirmado, divergências (fork/quorum/assinatura/rollback) sem promover head.
- `sentra_quality/otel_langfuse.py` — SeloTelemetryExporter: allowlist SafeTelemetryEvent,
  fila bounded com dedupe, flush OTLP loopback e Langfuse HTTPS opt-in; nunca levanta no caminho central.
- `sentra_quality/diagnostics.py` — DiagnosticsReport redatado, bounded, `audit_complete=False`.
- `sentra_quality/release_gate.py` — verify_release: SourceGate.verify_all + SBOM digest +
  reavaliação do report Grype ligado por digest; sem binário não confiável.
- `memory/__init__.py`, `memory/store.py`, `memory/costs.py` — MemoryStore (CAS/digest/retenção,
  até 64 KiB) e CostLedger (contábil, `enforces_admission=False`).
- `sentra_mcp/services/policy_identity_audit.py` — PolicyIdentityAuditService(authorization + vetos
  injetados, identidades, âncoras).
- `sentra_mcp/services/memory_costs.py` — MemoryCostsService.
- `sentra_mcp/services/diagnostics.py` — DiagnosticsService (snapshot + export).
- `sentra_mcp/services/grype_release.py` — GrypeReleaseService.
- `sentra_executors/benchmark_selo.py` — BenchmarkSeloGate: aggregate somente avaliações
  independentes pontuadas + seal com provenance/policy_context.
- `tests/unit/test_selo_*.py` (4 arquivos) — esqueletos para validação futura, não executados.

## Arquivos editados (domínio Selo, compatível)

- `sentra_mcp/services/authorization.py` — adicionado `authorize_with_vetos()`; API existente preservada.
- `sentra_mcp/services/capabilities.py` — flags Selo em `server_capabilities()` (sem remover as existentes).
- `sentra_mcp/services/telemetry.py` — métodos `selo_enqueue/stats/flush_otlp/diagnostics` delegando
  aos módulos Selo; query/usage_stats preservados.
- `sentra_quality/__init__.py`, `sentra_quality/__main__.py` — exports + subcomandos
  `selo-diagnostics`, `selo-telemetry-stats`, `selo-release-verify`.

## Não alterado (outros donos)

`sentra_runtime/*`, `sentra_core/*`, `sentra_canvas/*`, `sentra_mcp/server.py`,
`sentra_executors/*` (exceto novo `benchmark_selo.py`), demais services. Integração com
providers OPA/OpenFGA/Keycloak/SPIRE/Tessera/immudb é por callables injetados pelo host/Codex;
nenhum cliente de rede foi duplicado aqui.

## Contrato de integração (para Codex compor)

```python
from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.policy_identity_audit import PolicyIdentityAuditService
from sentra_mcp.services.memory_costs import MemoryCostsService
from sentra_mcp.services.diagnostics import DiagnosticsService
from sentra_mcp.services.grype_release import GrypeReleaseService

authz = AuthorizationService(state_root)  # autoridade única (Nexo/Codex)
svc = PolicyIdentityAuditService(state_root, authorization=authz, vetos=[
    ("opa", lambda req: opa_veto(req)),          # host liga sentra_runtime.opa_pdp
    ("openfga", lambda req: fga_veto(req)),      # host liga openfga_rebac
    ("keycloak", lambda req: kc_veto(req)),      # host liga keycloak_provider
    ("spire", lambda req: spire_veto(req)),      # host liga spire_identity
])
decision = svc.authorize(owner, principal_type="agent", principal_id=pid,
                         capability="...", scope_type="...", scope_id="...",
                         context={...})
mem = MemoryCostsService(state_root)
diag = DiagnosticsService(state_root)
grype = GrypeReleaseService().decide(third_party_root=..., trusted_pins=...,
                                     sbom=..., expected_sbom_sha256=...,
                                     scan_receipt=..., fail_at="high")
```

- Shell bridge: sem rota nova Selo; `home` pode exibir capabilities Selo concedidas.
- Vetos: somente após allow do CorePDP; ListObjects/descoberta nunca autoriza efeito.
- Telemetria: somente `SafeTelemetryEvent` (digest de operation_id); falha de sink não muda resultado.
- Memória/custos: projeção; budgets reais continuam em BudgetPolicyService/autoridade.
- Auditoria: Tessera quorum ≥1 + verificação SDK; immudb dual proof no provider; aqui só
  estrutura + head CAS + divergência.
- Grype: release exige sources verificados + SBOM + report ligado por digest + sem ignored.

## Pendências reais (não declaradas como concluídas)

1. Provisionamento externo: OPA daemon/bundles, OpenFGA store/modelo, Keycloak realm/client,
   SPIRE server/agent/registrations, broker NATS, log Tessera + witnesses, immudb TLS/seed,
   collector OTLP loopback, conta Langfuse — nada iniciado nesta fase.
2. Build pinado dos helpers Go (spire/audit SDK) + go.sum revisado — pendente de toolchain/rede liberada.
3. Aceitação externa (introspecção/backchannel, quorum/fork, dual proof, PubAck incerto,
   renovação SVID, revogação) — testes criados como esqueleto, execução na etapa final.
4. Ligação no host central (endpoints login/backchannel, serviço de bundles/status/logs,
   callbacks on_invalidate, retenção/arquivamento) — dono Codex.
5. Expansão tasks/Selo.md: composição HTTP/Canvas/CLI/Desktop dos novos serviços e ações de shell
   (`learning_*`, `eval_*`, `pipeline_*`, `trust_*/witness_*/coverage_*`) — dono Codex registrar;
   importação SkillPack de candidatos Selo — dono Pacto; comparação prompt/provider com
   QualityGate/custo centrais em dados reais — validação futura após liberação do principal.
   Artefatos ausentes (guests, runners, providers, contas) NÃO são declarados como presentes.

## Plano de validação futura (NÃO executado)

- `python -m pytest tests/unit/test_selo_* -q` + suites de lifecycle de política/identidade/spire/audit.
- `python -m sentra_quality selo-diagnostics --state-root <dir> --owner <o>`.
- `python -m sentra_quality selo-release-verify --sbom <f> --sbom-sha256 <h> --receipt <r>`.
- Opt-ins com perfis reais: OPA binary/capabilities, SPIRE profile, NATS/immudb/audit-proof,
  Langfuse bearer — skips explícitos sem perfil.
- Concorrência/recovery/permissões e fidelidade visual na etapa final do Codex.
