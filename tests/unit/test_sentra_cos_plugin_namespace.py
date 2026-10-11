"""Real SENTRA plugin-worker handshake enforces CoS-style surface safety."""
import pytest
from sentra_mcp.services.plugin_host import PluginWorkerHost,PluginProtocolError


def test_plugin_worker_rejects_casefold_aliases_and_duplicate_names():
    with pytest.raises(PluginProtocolError,match="ambiguous"):
        PluginWorkerHost._method_descriptors([
            {"name":"Filesystem_Read","capability":"filesystem.read"},
            {"name":"filesystem_read","capability":"filesystem.read"},
        ])


def test_plugin_worker_bounds_exposed_tool_count():
    too_many=[{"name":f"get_{i}","capability":"read"} for i in range(257)]
    with pytest.raises(PluginProtocolError,match="256"):
        PluginWorkerHost._method_descriptors(too_many)


def test_plugin_worker_retains_distinct_capability_on_valid_methods():
    methods,caps=PluginWorkerHost._method_descriptors([
        {"name":"safe_read","capability":"filesystem.read"},
        {"name":"safe_list","capability":"filesystem.list"},
    ])
    assert methods==["safe_read","safe_list"]
    assert caps=={"safe_read":"filesystem.read","safe_list":"filesystem.list"}
