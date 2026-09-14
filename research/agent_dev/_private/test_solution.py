"""Testes PRIVADOS do harness (fora do root da sessão do agente)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "palindrome"))

from solution import is_palindrome_number


def test_basics():
    assert is_palindrome_number(121) is True
    assert is_palindrome_number(7) is True
    assert is_palindrome_number(0) is True


def test_negatives():
    assert is_palindrome_number(-121) is False
    assert is_palindrome_number(-1) is False


def test_trailing_zero():
    assert is_palindrome_number(10) is False
    assert is_palindrome_number(100) is False


def test_larger():
    assert is_palindrome_number(12321) is True
    assert is_palindrome_number(123454321) is True
    assert is_palindrome_number(1000021) is False
    assert is_palindrome_number(123) is False


def test_no_str_cheat():
    src = (Path(__file__).resolve().parent.parent / "palindrome" / "solution.py").read_text()
    assert "str(" not in src, "conversão para string proibida"
