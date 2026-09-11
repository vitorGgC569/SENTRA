from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List


class CommandRunner:
    def __init__(self, cwd: Path):
        self.cwd = Path(cwd)

    async def run_command(self, cmd: str, timeout: int = 120) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.cwd),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            exit_code = process.returncode or 0

            return {
                "command": cmd,
                "passed": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            return {
                "command": cmd,
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds.",
            }
        except Exception as e:
            return {
                "command": cmd,
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution error: {e}",
            }

    async def run_all(self, commands: List[str], timeout: int = 120) -> Dict[str, Any]:
        if not commands:
            return {
                "all_passed": True,
                "passed_commands": [],
                "failed_commands": [],
                "results": [],
            }

        results = []
        all_passed = True
        passed_cmds = []
        failed_cmds = []

        for cmd in commands:
            res = await self.run_command(cmd, timeout=timeout)
            results.append(res)
            if res["passed"]:
                passed_cmds.append(cmd)
            else:
                failed_cmds.append(cmd)
                all_passed = False

        return {
            "all_passed": all_passed,
            "passed_commands": passed_cmds,
            "failed_commands": failed_cmds,
            "results": results,
        }
