"""Notice evidence integrity, not a legal opinion or native acceptance test."""
import hashlib
import json

import pytest

from scripts.commander import review_rustdesk_legal as review


@pytest.mark.parametrize("url", ["http://api.github.com/example", "https://evil.invalid/license",
                                 "https://user:pass@raw.githubusercontent.com/a/b/LICENSE"])
def test_notice_origins_are_allowlisted_before_network(url, tmp_path):
    with pytest.raises(ValueError, match="origin"):
        review.fetch(url, tmp_path / "cache")
    assert not (tmp_path / "cache").exists()


def test_cached_notice_must_match_both_origin_and_actual_bytes(tmp_path):
    url = "https://raw.githubusercontent.com/owner/repo/" + "a" * 40 + "/LICENSE"
    key = hashlib.sha256(url.encode()).hexdigest()
    body = tmp_path / (key + ".body"); body.write_bytes(b"notice fixture")
    meta = tmp_path / (key + ".json")
    value = {"url": url, "status": 200, "cache_file": str(body), "sha256": hashlib.sha256(body.read_bytes()).hexdigest()}
    review.materializer.write_json(meta, value)
    assert review.fetch(url, tmp_path) == value
    body.write_bytes(b"changed")
    with pytest.raises(ValueError, match="cache changed"):
        review.fetch(url, tmp_path)


def test_cached_notice_cannot_substitute_an_arbitrary_local_file(tmp_path):
    url = "https://raw.githubusercontent.com/owner/repo/" + "a" * 40 + "/LICENSE"
    key = hashlib.sha256(url.encode()).hexdigest()
    body = tmp_path / (key + ".body"); body.write_bytes(b"fixture")
    other = tmp_path / "private.txt"; other.write_bytes(b"fixture")
    review.materializer.write_json(tmp_path / (key + ".json"), {"url": url, "status": 200,
        "cache_file": str(other), "sha256": hashlib.sha256(body.read_bytes()).hexdigest()})
    with pytest.raises(ValueError, match="cache changed"):
        review.fetch(url, tmp_path)


def test_root_license_fetch_keeps_exact_commit_and_ignores_foreign_download_url(tmp_path, monkeypatch):
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps([{"type": "file", "name": "LICENSE", "path": "LICENSE",
                                   "download_url": "https://evil.invalid/latest"}]))
    calls = []
    def fake_fetch(url, cache):
        calls.append(url)
        return {"status": 200, "cache_file": str(listing)}
    monkeypatch.setattr(review, "fetch", fake_fetch)
    revision = "a" * 40
    review.pinned_root_notices("owner/repo", revision, tmp_path)
    assert calls == ["https://api.github.com/repos/owner/repo/contents?ref=" + revision,
                     "https://raw.githubusercontent.com/owner/repo/" + revision + "/LICENSE"]
    with pytest.raises(ValueError, match="exact"):
        review.pinned_root_notices("owner/repo", "main", tmp_path)


def test_frozen_manifest_pin_and_unlisted_file_are_rejected(tmp_path):
    artifact = tmp_path / "artifact"; artifact.mkdir()
    payload = artifact / "notice.txt"; payload.write_bytes(b"fixture")
    manifest = artifact / "manifest.json"
    review.materializer.write_json(manifest, {"files": [{"path": payload.name,
        "sha256": review.materializer.build.sha(payload)}]})
    pin = review.materializer.build.sha(manifest)
    review.verify_component(artifact, pin)
    with pytest.raises(ValueError, match="pin changed"):
        review.verify_component(artifact, "0" * 64)
    (artifact / "extra.txt").write_text("unlisted")
    with pytest.raises(ValueError, match="file set changed"):
        review.verify_component(artifact, pin)
