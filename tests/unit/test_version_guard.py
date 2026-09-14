"""Version-regression guard: downgrades block, upgrades inform, clean passes."""
from orchestrator.version_guard import (
    check_patch, compare_versions, extract_versions)


def test_compare_versions():
    assert compare_versions("1.3.9", "1.3.17") == 1
    assert compare_versions("1.3.17", "1.3.9") == -1   # o caso real do piloto
    assert compare_versions("1.3.17", "1.3.17") == 0
    assert compare_versions("1.0", "1.0.0") == 0
    assert compare_versions("1.0", "1.0.1") == 1
    assert compare_versions("2.0", "1.9.9") == -1
    assert compare_versions("1.0-rc1", "1.0") == 1
    assert compare_versions("1.0", "1.0-rc1") == -1
    assert compare_versions("", "1.0") is None
    assert compare_versions("abc", "def") in (-1, 0, 1)  # nunca explode


def test_extract_versions():
    files = {
        "edge_extension/content-script.js": 'const OMA_CS_VERSION = "1.3.17";',
        "edge_extension/manifest.json": '{"version": "1.3.17"}',
        "pkg/__init__.py": '__version__ = "0.2.0"',
        "src/app.py": "x = 1\n",
    }
    found = extract_versions(files)
    assert found["edge_extension/content-script.js"] == "1.3.17"
    assert found["edge_extension/manifest.json"] == "1.3.17"
    assert found["pkg/__init__.py"] == "0.2.0"
    assert "src/app.py" not in found


def _patch(old_line, new_line, path="edge_extension/content-script.js"):
    return (f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,2 +1,2 @@\n const X = 1;\n-{old_line}\n+{new_line}\n")


def test_check_patch_detects_downgrade():
    base = {"edge_extension/content-script.js":
            'const X = 1;\nconst OMA_CS_VERSION = "1.3.17";\n'}
    res = check_patch(base, _patch('const OMA_CS_VERSION = "1.3.17";',
                                   'const OMA_CS_VERSION = "1.3.9";'))
    assert len(res["downgrades"]) == 1
    assert res["downgrades"][0]["old"] == "1.3.17"
    assert res["downgrades"][0]["new"] == "1.3.9"
    assert res["upgrades"] == []


def test_check_patch_allows_upgrade_and_clean():
    base = {"edge_extension/content-script.js":
            'const X = 1;\nconst OMA_CS_VERSION = "1.3.9";\n'}
    res = check_patch(base, _patch('const OMA_CS_VERSION = "1.3.9";',
                                   'const OMA_CS_VERSION = "1.3.10";'))
    assert res["downgrades"] == []
    assert len(res["upgrades"]) == 1
    res2 = check_patch({"a/b.py": "x = 1\n"},
                       "--- a/a/b.py\n+++ b/a/b.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n")
    assert res2["downgrades"] == [] and res2["changed"] == []


def test_check_patch_never_raises_on_garbage():
    res = check_patch({}, "this is not a diff")
    assert res["downgrades"] == [] and "error" in res
