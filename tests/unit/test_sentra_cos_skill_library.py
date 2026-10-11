"""Integration-level provenance checks of CoS-inspired immutable skills."""
import subprocess
import pytest
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService

SKILL = "---\nname: reviewed-workflow\ndescription: Read-only instructions for a task\n---\n# Workflow\nDo not grant permissions.\n"


def _library(tmp_path):
    durable=DurableRunService(tmp_path/"state")
    control=ControlPlaneService(durable,ContextBusService(tmp_path/"state"))
    return control.skill_library


def test_immutable_local_import_revision_replay_and_revoke(tmp_path):
    src=tmp_path/"workspace"/"skills"/"review"
    src.mkdir(parents=True)
    (src/"SKILL.md").write_text(SKILL,encoding="utf-8")
    library=_library(tmp_path)
    owner="local-operator"
    root=tmp_path/"workspace"
    first=library.import_local(owner,root,"skills/review")
    again=library.import_local(owner,root,"skills/review")
    assert first["package_id"]==again["package_id"]
    assert first["revoked"]==0
    assert library.list(owner,root)["creates_grants"] is False
    (src/"SKILL.md").write_text(SKILL+"second revision\n",encoding="utf-8")
    second=library.import_local(owner,root,"skills/review")
    assert second["package_id"]!=first["package_id"]
    assert len(library.list(owner,root)["items"])==2
    revoked=library.revoke(owner,root,first["package_id"],expected_revision=1)
    assert revoked["revoked"]==1 and revoked["revision"]==2
    with pytest.raises(ValueError,match="revision"):
        library.revoke(owner,root,first["package_id"],expected_revision=1)


def test_skills_refuse_outside_files_private_links_and_bad_sha(tmp_path):
    root=tmp_path/"workspace"
    src=root/"review"
    src.mkdir(parents=True)
    (src/"SKILL.md").write_text(SKILL,encoding="utf-8")
    library=_library(tmp_path)
    with pytest.raises(PermissionError):
        library.import_local("operator",root,tmp_path)
    with pytest.raises(ValueError,match="checksum"):
        library.import_local("operator",root,"review",expected_sha256="a"*64)
    (src/".env").write_text("SECRET",encoding="utf-8")
    with pytest.raises(ValueError,match="private"):
        library.import_local("operator",root,"review")
    (src/".env").unlink()
    linked=src/"shadow.txt"
    try: linked.symlink_to(src/"SKILL.md")
    except (OSError,NotImplementedError): pytest.skip("symlinks require privilege")
    with pytest.raises(PermissionError,match="links"):
        library.import_local("operator",root,"review")


def test_git_sha_pinned_skill_import(tmp_path):
    root=tmp_path/"workspace"
    repo=root/"skillrepo"
    repo.mkdir(parents=True)
    (repo/"SKILL.md").write_text(SKILL,encoding="utf-8")
    def git(*arguments):
        result=subprocess.run(["git","-C",str(repo),*arguments],capture_output=True,text=True)
        if result.returncode: pytest.skip("git not available on test host")
        return result.stdout.strip()
    git("init","-q")
    git("-c","user.email=fixture@example.test","-c","user.name=fixture","add","SKILL.md")
    git("-c","user.email=fixture@example.test","-c","user.name=fixture","commit","-m","pin")
    sha=git("rev-parse","HEAD")
    library=_library(tmp_path)
    result=library.import_git("operator",root,"skillrepo",sha)
    assert result["git_sha"]==sha
    (repo/"SKILL.md").write_text(SKILL+"not pinned",encoding="utf-8")
    again=library.import_git("operator",root,"skillrepo",sha)
    assert result["package_id"]==again["package_id"]
