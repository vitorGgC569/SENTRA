"""Context budgeting: validator prompts fit the provider cap (>20k-char patches
once meant validators were never called)."""
from orchestrator.agents.validators import _compact_patch


def test_compact_patch_preserves_small():
    short = "a\n" * 100
    assert _compact_patch(short) == short


def test_compact_patch_marks_large_excerpt():
    long = "".join(f"line {i:04d} body text here\n" for i in range(2000))
    assert len(long) > 6000
    out = _compact_patch(long)
    assert len(out) < len(long) and "OMITTED" in out
    assert out.startswith("line 0000")
    assert out.rstrip().endswith("line 1999 body text here")
