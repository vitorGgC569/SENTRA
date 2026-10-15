from pathlib import Path

from sentra_remote.openai_auto_setup import edge_automation_profile


def test_automation_edge_is_not_the_signed_in_profile(tmp_path, monkeypatch):
    edge = tmp_path / "Microsoft" / "Edge" / "User Data"
    edge.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    profile = edge_automation_profile(tmp_path / "state")
    assert profile.name == "edge-automation"
    assert "User Data" not in profile.parts
    assert profile.is_dir()
