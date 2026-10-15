import json
import os
from pathlib import Path

import pytest

from scripts.commander.flutter_plugin_links import prepare_flutter_plugin_links

pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows junctions")


def setup(tmp_path):
    project = tmp_path / "project"
    (project / "windows").mkdir(parents=True)
    cache = tmp_path / "cache"
    (cache / "example_plugin").mkdir(parents=True)
    marker = cache / "example_plugin/marker.txt"
    marker.write_text("original cache content")
    descriptor = project / ".flutter-plugins-dependencies"
    descriptor.write_text(json.dumps({"plugins": {"windows": [
        {"name": "example_plugin", "path": str(marker.parent)}]}}))
    return project, cache, descriptor


def test_real_junctions_work_without_symlink_privileges_and_are_repeatable(tmp_path):
    project, cache, _ = setup(tmp_path)
    first = prepare_flutter_plugin_links(project, cache)
    assert prepare_flutter_plugin_links(project, cache) == first
    link = project / "windows/flutter/ephemeral/.plugin_symlinks/example_plugin"
    try:
        assert link.is_junction()
        assert (link / "marker.txt").read_text() == "original cache content"
    finally:
        # Remove only the directory junction itself, never traverse the cache.
        link.rmdir()
    assert (cache / "example_plugin/marker.txt").read_text() == "original cache content"


@pytest.mark.parametrize("name", ["../escape", "A/B", "a\\b", "x:stream"])
def test_invalid_plugin_name_never_creates_links(tmp_path, name):
    project, cache, descriptor = setup(tmp_path)
    descriptor.write_text(json.dumps({"plugins": {"windows": [
        {"name": name, "path": str(cache / "example_plugin")}]}}))
    with pytest.raises(ValueError, match="invalid or duplicate"):
        prepare_flutter_plugin_links(project, cache)
    assert not (project / "windows/flutter").exists()


def test_external_plugin_source_fails_before_any_mutation(tmp_path):
    project, cache, descriptor = setup(tmp_path)
    descriptor.write_text(json.dumps({"plugins": {"windows": [
        {"name": "allowed", "path": str(cache / "example_plugin")},
        {"name": "foreign", "path": str(tmp_path)}]}}))
    with pytest.raises(ValueError, match="escaped the selected Pub cache"):
        prepare_flutter_plugin_links(project, cache)
    assert not (project / "windows/flutter").exists()


def test_existing_real_directory_is_never_replaced(tmp_path):
    project, cache, _ = setup(tmp_path)
    directory = project / "windows/flutter/ephemeral/.plugin_symlinks/example_plugin"
    directory.mkdir(parents=True)
    (directory / "preserve.txt").write_text("user content")
    with pytest.raises(FileExistsError, match="differs"):
        prepare_flutter_plugin_links(project, cache)
    assert (directory / "preserve.txt").read_text() == "user content"
