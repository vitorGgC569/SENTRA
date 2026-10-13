"""Selo learning + Langfuse eval acceptance (FUTURE validation only — do not execute yet).

Planned coverage:
- propose requires origin/scope/result/transcript; transcript stored redacted;
  suggestion never activates a skill and never creates grants.
- review APPROVED/REJECTED with reviewer + CAS; non-PROPOSED refuses review.
- to_skill_files/review_bundle only from APPROVED; bundle mirrors
  SkillLibrary.review shape (package SHA, per-file SHA, frontmatter,
  capability manifest, activation preconditions).
- Langfuse prompts version/labels/config; datasets + items with expected I/O;
  runs pin dataset+prompt versions; run items link trace/observation ids;
  typed scores NUMERIC/CATEGORICAL/BOOLEAN/CORRECTION/TEXT + human corrections.
- compare_runs over one dataset version reports success/cost/latency,
  regressions and fixes; scores stay advisory, QualityGate authoritative.
"""
from __future__ import annotations


def test_placeholder_for_future_validation():
    assert True
