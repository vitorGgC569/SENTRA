from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Candidate,
    Evidence,
    Finding,
    Severity,
    Task,
    ValidationReport,
    ValidatorRole,
    TokenUsage,
)
from ..providers.base import AgentRequest
from .router import ModelRouter


VALIDATOR_PROMPTS = {
    ValidatorRole.LOGIC: """You are the OMA Logic Validator.
Your job is to scrutinize the candidate solution for:
- Logical inconsistencies, contradictions, and algorithmic bugs.
- Flawed reasoning, off-by-one errors, or incorrect assumptions.
- State corruption or circular dependencies.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "LOGIC",
      "description": "Specific issue",
      "suggested_fix": "Fix recommendation"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.REQUIREMENTS: """You are the OMA Requirements Validator.
Your job is to verify that the proposed solution faithfully and completely satisfies the assigned objective and acceptance criteria.
Check for:
- Missing requirements or partial implementations.
- Divergence from the requested specification.
- Unwanted modifications outside the task scope.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "REQUIREMENTS",
      "description": "Requirement not satisfied",
      "suggested_fix": "How to satisfy it"
    }
  ],
  "requirements_checked": ["list of criteria satisfied"]
}
""",
    ValidatorRole.ADVERSARIAL: """You are the OMA Adversarial Validator.
Your goal is to actively try to BREAK the candidate solution.
Look for:
- Fragile logic, unhandled unexpected inputs, and easy bypasses.
- Silent error suppression or swallowing of exceptions.
- Malformed inputs that cause crashes or data corruption.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "ADVERSARIAL",
      "description": "Vulnerability or breakage found",
      "suggested_fix": "Hardening guidance"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.EDGE_CASES: """You are the OMA Edge Cases Validator.
Examine the solution for boundary conditions:
- Empty lists, null / None values, zero / negative numbers.
- Extremely large inputs, unicode / special characters.
- Concurrent access or race conditions.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "EDGE_CASE",
      "description": "Unhandled edge condition",
      "suggested_fix": "Defensive handling"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.SECURITY: """You are the OMA Security Validator.
Audit the solution for security risks:
- Command injection, SQL injection, path traversal, untrusted input execution.
- Credential leaks in logs or code.
- Principle of least privilege violations.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "SECURITY",
      "description": "Security risk identified",
      "suggested_fix": "Sanitization or security measure"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.PERFORMANCE: """You are the OMA Performance Validator.
Analyze the solution for:
- Algorithmic complexity (e.g. O(N^2) loops where O(N) is feasible).
- Unbounded memory consumption or leaks.
- Excessive I/O, redundant network calls, or blocking operations.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "PERFORMANCE",
      "description": "Performance concern",
      "suggested_fix": "Optimization approach"
    }
  ],
  "requirements_checked": []
}
""",
}


def _compact_patch(patch: str, limit: int = 6000) -> str:
    """Context budgeting for validator prompts: web-size diffs would otherwise
    exceed the provider's per-message cap and the validator would never run.
    Keeps head+tail with explicit omission markers and line stats, so the
    validator knows it sees an excerpt — strictly better than no validation.
    Pure function (input untouched)."""
    if len(patch or "") <= limit:
        return patch or ""
    lines = (patch or "").splitlines()
    head, tail = lines[:60], lines[-40:]
    omitted = len(lines) - len(head) - len(tail)
    return ("\n".join(head)
            + f"\n[... OMITTED {omitted} lines / {len(patch) - limit} chars "
              f"for context budget: {len(lines)} total lines ...]\n"
            + "\n".join(tail))


class SpecializedValidator:
    def __init__(self, role: ValidatorRole, router: ModelRouter, require_explicit_scores=False):
        self.role = role
        self.router = router
        self.require_explicit_scores = require_explicit_scores

    async def validate(
        self,
        task: Task,
        candidate: Candidate,
        test_results: Optional[Dict[str, Any]] = None,
    ) -> ValidationReport:
        system_prompt = VALIDATOR_PROMPTS.get(
            self.role, VALIDATOR_PROMPTS[ValidatorRole.LOGIC]
        ) + (
            "\nStance: assume a defect exists and hunt it; do not agree with other "
            "validators. Both unsupported approval and invented rejection are "
            "errors. Never infer evidence you did not see."
            '\nScore the candidate 0.0-10.0 in "score": 10 = shippable without '
            "reservations; 9.5 = release bar (minor polish only); 7-9 = needs "
            "repair (list exactly what); below 7 = fundamentally flawed. The score "
            "MUST match your findings: any open CRITICAL caps you at 4.0, any "
            "MAJOR at 7.0 (enforced deterministically). Grade inflation — high "
            "score alongside severe findings — invalidates your report."
        )
        patch_text = _compact_patch(candidate.patch)
        user_prompt = f"""TASK OBJECTIVE: {task.objective}
TASK DESCRIPTION: {task.description}
TASK ACCEPTANCE CRITERIA (copy exact strings into requirements_checked only if verified):
{json.dumps(task.metadata.get('acceptance_criteria', []))}

CANDIDATE SUMMARY: {candidate.summary}
PROPOSED PATCH:
```diff
{patch_text}
```

DETERMINISTIC TEST RESULTS:
{json.dumps(test_results or {}, indent=2)}
"""
        images = [p for p in (task.metadata.get("images") or [])
                  if isinstance(p, str) and p]
        if images:
            user_prompt += (
                "\nEVIDENCIA VISUAL ANEXADA "
                f"({len(images)} imagem(ns) renderizada(s) desta candidatura, em ordem): "
                "examine cada imagem e confirme ou refute visualmente os requisitos "
                "visuais; cite o que observou em cada uma. "
                "Nunca alegue ter visto o que nao esta nas imagens.\n"
            )
        req = AgentRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role=self.role.value,
            metadata={"task_id": task.id, "candidate_id": candidate.candidate_id,
                      "acceptance_criteria": task.metadata.get("acceptance_criteria", []),
                      **({"images": images} if images else {})},
        )

        resp = await self.router.execute(req)

        # Parse JSON output
        parsed: Dict[str, Any] = {}
        if resp.structured_data:
            parsed = resp.structured_data
        else:
            try:
                start = resp.content.find("{")
                end = resp.content.rfind("}")
                if start != -1 and end != -1:
                    parsed = json.loads(resp.content[start : end + 1])
            except Exception:
                pass

        import math
        if not isinstance(parsed, dict):
            parsed = {}
        status = str(parsed.get("status", "REJECTED")).upper()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0
        try:
            raw_score = float(parsed.get("score"))
            explicit_score = (raw_score if math.isfinite(raw_score)
                              and 0.0 <= raw_score <= 10.0 else None)
        except (ValueError, TypeError):
            explicit_score = None
        model_judgment_ok = (
            resp.success and status in {"APPROVED", "REJECTED", "DISPUTED"}
            and math.isfinite(confidence) and 0 <= confidence <= 1
            and isinstance(parsed.get("findings", []), list)
            and all(isinstance(f, dict) for f in parsed.get("findings", []))
            and isinstance(parsed.get("requirements_checked", []), list)
            and all(isinstance(item, str) for item in parsed.get("requirements_checked", []))
        )
        if self.require_explicit_scores and (
                type(parsed.get("score")) not in (int, float) or explicit_score is None):
            model_judgment_ok = False
        if explicit_score is not None:
            score = explicit_score if self.require_explicit_scores else round(explicit_score, 2)
        elif model_judgment_ok:
            # Fallback documentado: sem nota explícita, confiança x10.
            score = round(max(0.0, min(1.0, confidence)) * 10.0, 2)
        else:
            score = 0.0
        # Sem julgamento do modelo (transporte/budget/timeout, ou resposta
        # inválida), o relatório NÃO é evidência contra o candidato: ran=False
        # para o Quality Gate excluir do quorum em vez de votar REJECTED.
        ran = bool(model_judgment_ok)
        error = "" if ran else (resp.error or "invalid validator response")
        if not model_judgment_ok:
            status, confidence = "REJECTED", 0.0
            parsed = {"summary": resp.error or "invalid validator response"}
        summary = parsed.get("summary", resp.content[:150])

        findings = []
        for f_data in parsed.get("findings", []):
            sev_str = f_data.get("severity", "MINOR").upper()
            sev = Severity[sev_str] if sev_str in Severity.__members__ else Severity.MINOR
            findings.append(
                Finding(
                    finding_id=f"fnd_{uuid.uuid4().hex[:8]}",
                    severity=sev,
                    category=f_data.get("category", self.role.name),
                    description=f_data.get("description", ""),
                    suggested_fix=f_data.get("suggested_fix"),
                )
            )

        # If tests failed deterministically, always add a CRITICAL finding.
        # Só falhas de checagens que REALMENTE executaram contam: recusas de
        # política (refused) ou ausência de checagens não são evidência contra
        # o candidato. Tests executados SÃO evidência: mesmo sem julgamento do
        # modelo, o relatório conta (ran=True) — só o voto vazio é excluído.
        ran_results = [r for r in (test_results or {}).get("results", [])]
        if test_results and ran_results and not test_results.get("all_passed", True):
            status = "REJECTED"
            confidence = min(confidence, 0.4)
            ran = True
            findings.append(
                Finding(
                    finding_id=f"fnd_test_{uuid.uuid4().hex[:6]}",
                    severity=Severity.CRITICAL,
                    category="TEST_FAILURE",
                    description=f"Objective tests failed: {test_results.get('failed_commands', [])}",
                    suggested_fix="Fix code to satisfy automated tests.",
                )
            )

        # Version downgrade sem justificativa bloqueia: nenhuma validação de
        # lógica enxerga constante de versão como regressão, então o determinismo
        # injeta o achado (mesmo padrão do TEST_FAILURE). Upgrades viram INFO.
        for down in (test_results or {}).get("version_check", {}).get("downgrades", []):
            status = "REJECTED"
            ran = True
            findings.append(
                Finding(
                    finding_id=f"fnd_ver_{uuid.uuid4().hex[:6]}",
                    severity=Severity.CRITICAL,
                    category="VERSION_REGRESSION",
                    description=(f"Version downgrade without justification: {down.get('path')} "
                                 f"{down.get('old')} -> {down.get('new')}"),
                    suggested_fix="Keep version constants monotonic unless the task is a release.",
                )
            )
        for up in (test_results or {}).get("version_check", {}).get("upgrades", []):
            findings.append(
                Finding(
                    finding_id=f"fnd_ver_{uuid.uuid4().hex[:6]}",
                    severity=Severity.INFO,
                    category="VERSION_CHANGE",
                    description=(f"Version upgrade (non-blocking, visible): {up.get('path')} "
                                 f"{up.get('old')} -> {up.get('new')}"),
                )
            )

        # Anti-inflação determinística: nota inconsistente com os achados é
        # cortada (CRITICAL aberto capa em 4.0, MAJOR em 7.0). Nota alta com
        # defeito grave é evidência contra o avaliador, não a favor.
        if any(f.severity == Severity.CRITICAL for f in findings):
            score = min(score, 4.0)
        elif any(f.severity == Severity.MAJOR for f in findings):
            score = min(score, 7.0)
        score = max(0.0, min(10.0, score))
        if not self.require_explicit_scores:
            score = round(score, 2)

        # Create report
        report = ValidationReport(
            report_id=f"val_{uuid.uuid4().hex[:8]}",
            candidate_id=candidate.candidate_id,
            task_id=task.id,
            validator_id=self.role.value,
            validator_role=self.role.value,
            status=status,
            confidence=confidence,
            score=score,
            ran=ran,
            error=error,
            summary=summary,
            findings=findings,
            requirements_checked=parsed.get("requirements_checked", []),
            tests=test_results.get("results", []) if test_results else [],
            token_usage=resp.token_usage,
        )

        return report


class ValidatorPool:
    """
    Manages a pool of specialized cognitive diversity validators.
    """

    def __init__(self, router: ModelRouter, require_explicit_scores=False):
        self.router = router
        self.validators = {
            role: SpecializedValidator(role, router, require_explicit_scores)
            for role in ValidatorRole
            if role != ValidatorRole.GENERAL
        }

    async def validate_candidate(
        self,
        task: Task,
        candidate: Candidate,
        roles: Optional[List[ValidatorRole]] = None,
        test_results: Optional[Dict[str, Any]] = None,
    ) -> List[ValidationReport]:
        selected_roles = roles or [
            ValidatorRole.LOGIC,
            ValidatorRole.REQUIREMENTS,
            ValidatorRole.EDGE_CASES,
            ValidatorRole.ADVERSARIAL,
        ]
        selected_roles = list(dict.fromkeys(selected_roles))
        if str(task.risk).upper() in {"HIGH", "CRITICAL"} or getattr(task.priority, "value", task.priority) == "CRITICAL":
            if ValidatorRole.SECURITY not in selected_roles:
                selected_roles.append(ValidatorRole.SECURITY)

        tasks = [
            self.validators[role].validate(task, candidate, test_results)
            for role in selected_roles
            if role in self.validators
        ]

        reports = await asyncio.gather(*tasks)
        return list(reports)
