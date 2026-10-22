"""Read-only prerequisites for optional physical MCPB Docker assertions.

Effect commands never use this helper: their timeouts must still fail the test.
"""
import subprocess

from sentra_mcp.services.mcpb_sandbox import _trusted_docker


def trusted_docker():
    try:
        return _trusted_docker()
    except PermissionError:
        return None


def probe(docker, kind):
    arguments = {
        'image': ['image', 'inspect', 'oma-sandbox:local', '--format', '{{.Id}}'],
        'daemon': ['info', '--format', '{{.OSType}}'],
    }[kind]
    command = [docker, *arguments]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError) as error:
        return subprocess.CompletedProcess(command, 125, '', type(error).__name__)
