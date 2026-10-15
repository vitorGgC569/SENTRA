"""Archive evidence rejection tests; fixtures are not publisher attestations."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

SPEC = importlib.util.spec_from_file_location("mit_archive_qa", Path(__file__).parents[1] / "qa/astra_rustdesk_mit_archive_evidence.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


def crate(tmp_path, *, license="MIT", extra=None):
    path = tmp_path / "fixture.crate"
    manifest = ('[package]\nname="fixture"\nversion="0.1.0"\nlicense="' + license + '"\nauthors=["Original author metadata"]\n').encode()
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo("fixture-0.1.0/Cargo.toml"); entry.size = len(manifest)
        archive.addfile(entry, io.BytesIO(manifest))
        if extra:
            archive.addfile(extra)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_mit_metadata_is_preserved_without_added_copyright_claim(tmp_path):
    path, checksum = crate(tmp_path)
    result = qa.inspect_crate(path, "fixture", "0.1.0", checksum)
    assert result["authors_verbatim"] == ["Original author metadata"]
    assert result["standalone_notice_filenames"] == []
    assert result["copyright_holder_inferred"] is False
    assert result["copyright_year_inferred"] is False
    assert result["crate_sha256"] == checksum


def test_changed_archive_and_wrong_license_are_not_accepted(tmp_path):
    path, checksum = crate(tmp_path, license="Apache-2.0")
    with pytest.raises(ValueError, match="MIT declaration"):
        qa.inspect_crate(path, "fixture", "0.1.0", checksum)
    with pytest.raises(ValueError, match="checksum"):
        qa.inspect_crate(path, "fixture", "0.1.0", "0" * 64)


@pytest.mark.parametrize("linked", [True, False])
def test_published_archive_cannot_supply_links_or_parent_paths(tmp_path, linked):
    member = tarfile.TarInfo("fixture-0.1.0/link" if linked else "../outside")
    if linked:
        member.type, member.linkname = tarfile.SYMTYPE, "../../private"
    path, checksum = crate(tmp_path, extra=member)
    with pytest.raises(ValueError, match="linked|portable"):
        qa.inspect_crate(path, "fixture", "0.1.0", checksum)
