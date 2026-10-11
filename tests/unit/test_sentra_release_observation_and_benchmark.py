"""Release regressions: workflow reconciliation and pinned benchmark identity."""
from pathlib import Path

from sentra_runtime.contracts import OperationRequest
from sentra_runtime.observations import is_observation
from sentra_executors.benchmark_dataset import DatasetCatalog,DatasetSource


def request(capability):
    return OperationRequest("op","p","m",capability,"work","key",{"action":"execute"})


def test_only_reviewed_workflow_plans_or_observations_bypass_physical_lease():
    for capability in ("workflow:advance","workflow:resume","workflow:observe",
                       "workflow:output","piece:file_observe"):
        assert is_observation(request(capability),"workflow")
    for capability in ("workflow:create","workflow:cancel","workflow:signal",
                       "piece:file","workflow:memory","workflow:unknown"):
        assert not is_observation(request(capability),"workflow")


def test_manifest_id_remains_authority_when_payload_id_is_duplicated(tmp_path):
    root=tmp_path/"clone"
    base=root/"evaluation_examples"
    example=base/"examples"/"sample"
    example.mkdir(parents=True)
    (base/"test_all.json").write_text('{"sample":["one","two"]}')
    for name in ("one","two"):
        (example/(name+".json")).write_text('{"id":"same","instruction":"fixture"}')
    source=DatasetSource("osworld-v2",str(root.resolve()),"0"*40,"osworld-v1-json")
    catalog=DatasetCatalog((source,)).load()
    assert set(t.task_id for t in catalog.tasks.values())=={"one","two"}
    assert all("manifest_payload_id_mismatch" in t.indexing_issues for t in catalog.tasks.values())
    assert len({t.key for t in catalog.tasks.values()})==2


def test_absolute_source_identity_does_not_promote_an_unpinned_provider(tmp_path):
    root=tmp_path/"clone"
    folder=root/"evaluation_examples"/"examples"/"sample"
    folder.mkdir(parents=True)
    (folder/"one.json").write_text('{"id":"one","instruction":"fixture"}')
    source=DatasetSource("osworld-v2",str(root.resolve()),"0"*40,"osworld-v1-json")
    catalog=DatasetCatalog((source,)).load()
    assert len(catalog.tasks)==1
    assert next(iter(catalog.tasks.values())).view()["evaluated"] is False
