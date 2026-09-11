import asyncio
import inspect
import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    # Register custom marker to avoid PytestUnknownMarkWarning
    config.addinivalue_line("markers", "asyncio: mark test to run in asyncio event loop")


def pytest_pyfunc_call(pyfuncitem):
    """
    Hook to automatically execute async def test functions using asyncio.run
    without requiring external pytest-asyncio plugin.
    """
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {arg: pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
    return None


@pytest.fixture
def tmp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    import git
    git.Repo.init(workspace)
    return workspace
