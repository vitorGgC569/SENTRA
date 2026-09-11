from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from .command_runner import CommandRunner
from .git_manager import GitManager


class Validator:
    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.cmd_runner = CommandRunner(self.workspace_path)
        self.git_manager = GitManager(self.workspace_path)

    async def validate_workspace(self, validation_commands: List[str]) -> Dict[str, Any]:
        return await self.cmd_runner.run_all(validation_commands)
