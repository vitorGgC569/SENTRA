import pytest
from sentra_mcp.services.control_store import SQLiteControlPlaneStore
from sentra_mcp.services.tool_exposure import ToolExposureRegistry


def test_disabled_provider_still_owns_name_after_restart(tmp_path):
    registry=ToolExposureRegistry(SQLiteControlPlaneStore(tmp_path))
    registry.reserve('provider-a',['send'],enabled=False)
    restored=ToolExposureRegistry(SQLiteControlPlaneStore(tmp_path))
    with pytest.raises(PermissionError):
        restored.reserve('provider-b',['Send'],enabled=True)
    restored.reserve('provider-a',['send'],enabled=True)
    assert restored.publication(['provider-a'])[0]['name']=='send'


def test_schema_and_aggregate_tool_budgets_are_enforced(tmp_path):
    registry=ToolExposureRegistry(SQLiteControlPlaneStore(tmp_path))
    with pytest.raises(ValueError,match='schema bytes'):
        registry.reserve('provider-a',[{'name':'large','inputSchema':{'description':'x'*250000}}])
    registry.reserve('provider-a',[f'a{i}' for i in range(200)],enabled=True)
    registry.reserve('provider-b',[f'b{i}' for i in range(100)],enabled=True)
    with pytest.raises(ValueError,match='256'):
        registry.publication(['provider-a','provider-b'])

def test_core_names_reserved_without_plugin_schema_budget(tmp_path):
    registry=ToolExposureRegistry(SQLiteControlPlaneStore(tmp_path))
    names=[f'core_method_{n}' for n in range(280)]
    result=registry.reserve_core_names(names)
    assert result["names"]==280 and not result["creates_grants"]
    with pytest.raises(PermissionError,match="reserved"):
        registry.reserve("untrusted-provider",["CORE_METHOD_279"],enabled=False)
    registry.reserve_core_names(names)
    with pytest.raises(ValueError,match="duplicate"):
        registry.reserve_core_names(["same","SAME"])
