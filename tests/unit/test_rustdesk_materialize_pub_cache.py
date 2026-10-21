import json
from pathlib import Path

import pytest

from scripts.commander.materialize_rustdesk import collect_pub


@pytest.mark.parametrize("explicit_cache", [True, False])
def test_pub_sources_use_the_selected_build_cache(tmp_path, monkeypatch, explicit_cache):
    source, tools, artifact = (tmp_path / name for name in ("source", "tools", "artifact"))
    for folder in (source, tools, artifact):
        folder.mkdir()
    (artifact / "provenance").mkdir()
    local = tmp_path / "local"
    cache = tmp_path / "selected-cache" if explicit_cache else local / "Pub/Cache"
    package = cache / "package-1.0.0"
    package.mkdir(parents=True)
    (package / "pubspec.yaml").write_text("name: package\nversion: 1.0.0\n")
    (package / "LICENSE").write_text("unit fixture license\n")
    config = source / "flutter/.dart_tool/package_config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"packages": [{"name": "package", "rootUri": package.as_uri()}]}))
    (source / "flutter/pubspec.lock").write_text("packages:\n  package:\n    version: 1.0.0\n")
    (source / "flutter/.flutter-plugins-dependencies").write_text('{}')
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    if explicit_cache:
        monkeypatch.setenv("PUB_CACHE", str(cache))
        assert not local.exists()
    else:
        monkeypatch.delenv("PUB_CACHE", raising=False)

    class Archive:
        def __init__(self):
            self.files = []

        def add(self, root, name, prefix):
            assert (root / name).is_file()
            self.files.append((root, name, prefix))

    archive, gaps = Archive(), []
    components = collect_pub(source, tools, artifact, archive, gaps)
    assert components[0]["name"] == "package" and components[0]["version"] == "1.0.0"
    assert components[0]["license_files"] and not gaps
    assert {name for _, name, _ in archive.files} == {"pubspec.yaml", "LICENSE"}
    # An explicit cache never authorizes packages from a different directory.
    outside = tmp_path / "foreign-package"
    outside.mkdir()
    config.write_text(json.dumps({"packages": [{"name": "package", "rootUri": outside.as_uri()}]}))
    with pytest.raises(ValueError, match="outside selected"):
        collect_pub(source, tools, artifact, Archive(), [])
