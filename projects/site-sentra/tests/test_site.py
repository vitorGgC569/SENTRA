"""Testes do site SENTRA."""
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def test_workspace_ready():
    """Valida que o diretório do projeto está configurado."""
    assert WORKSPACE.is_dir()
