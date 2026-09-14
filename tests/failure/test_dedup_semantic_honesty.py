"""Dedup honesty — proves what 'semantic' really means here.

The guard is LEXICAL (exact hash + Jaccard overlap), not embedding-based.
- Near-duplicates with high lexical overlap ARE caught.
- True paraphrases with low overlap are NOT caught (documented limitation).
- Functionally distinct tasks are NOT flagged (no false positives).
"""
from orchestrator.anti_explosion import AntiExplosionConfig, AntiExplosionError, AntiExplosionGuard
from orchestrator.models import Task


def _guard():
    return AntiExplosionGuard(AntiExplosionConfig(similarity_threshold=0.85))


def test_exact_duplicate_rejected():
    g = _guard()
    g.register_task(Task(id="T-1", run_id="r", objective="Implement binary search"))
    with __import__("pytest").raises(AntiExplosionError):
        g.register_task(Task(id="T-2", run_id="r", objective="implement binary search  "))


def test_near_duplicate_high_overlap_rejected():
    g = _guard()
    g.register_task(Task(id="T-1", run_id="r", objective="implement binary search in sorted array"))
    with __import__("pytest").raises(AntiExplosionError):
        g.register_task(Task(id="T-2", run_id="r", objective="implement binary search in sorted array fast"))


def test_true_paraphrase_low_overlap_not_detected_documents_limitation():
    """'implemente busca binaria' vs long paraphrase: semantically equal, lexically distant.

    A lexical guard CANNOT catch this — this test documents the limitation so the
    matrix honestly calls it near-duplicate detection, not semantic understanding.
    An embedding-based upgrade would be needed for true semantic dedup.
    """
    g = _guard()
    g.register_task(Task(id="T-1", run_id="r", objective="implemente busca binaria"))
    paraphrase = ("crie um algoritmo que encontre um elemento em vetor ordenado "
                  "dividindo o espaco de busca ao meio")
    sim = g.find_most_similar(paraphrase)
    assert sim < 0.85  # limitation proven numerically
    # And registration succeeds (not flagged)
    g.register_task(Task(id="T-2", run_id="r", objective=paraphrase))


def test_distinct_tasks_no_false_positive():
    g = _guard()
    g.register_task(Task(id="T-1", run_id="r", objective="implement binary search"))
    g.register_task(Task(id="T-2", run_id="r", objective="write quarterly financial report summary"))
    assert g.total_tasks_created == 2
