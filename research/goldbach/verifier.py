"""Backbone determinístico da pesquisa Goldbach (verdade do OMA).

Todo claim de agente (par testemunha p+q=n) é revalidado aqui.
Modelos propõem; este módulo decide.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def sieve(limit: int) -> bytearray:
    is_prime = bytearray(b"\x01") * (limit + 1)
    is_prime[0:2] = b"\x00\x00"
    p = 2
    while p * p <= limit:
        if is_prime[p]:
            step = p
            start = p * p
            is_prime[start:limit + 1:step] = b"\x00" * ((limit - start) // step + 1)
        p += 1
    return is_prime


def goldbach_witness(n: int, is_prime: bytearray) -> Optional[Tuple[int, int]]:
    """Menor par (p, q) primos com p+q=n. None se contraexemplo (n par >= 4)."""
    if n < 4 or n % 2:
        raise ValueError("n deve ser par >= 4")
    for p in range(2, n // 2 + 1):
        if is_prime[p] and is_prime[n - p]:
            return (p, n - p)
    return None


def check_witness(n: int, p: int, q: int, is_prime: bytearray) -> bool:
    return p + q == n and bool(is_prime[p]) and bool(is_prime[q])


def split_ranges(start: int, end: int, n_agents: int) -> List[Tuple[int, int]]:
    """Divide pares [start, end] em n_agents faixas contíguas (sem perda/dup)."""
    evens = list(range(start if start % 2 == 0 else start + 1, end + 1, 2))
    chunk, rem = divmod(len(evens), n_agents)
    out, idx = [], 0
    for i in range(n_agents):
        size = chunk + (1 if i < rem else 0)
        out.append((evens[idx], evens[idx + size - 1]))
        idx += size
    return out


def verify_range(a: int, b: int, is_prime: bytearray) -> Dict[str, object]:
    """Verificação completa de uma faixa. Retorna cobertura + contraexemplos."""
    missing, tested = [], 0
    n = a if a % 2 == 0 else a + 1
    while n <= b:
        tested += 1
        if goldbach_witness(n, is_prime) is None:
            missing.append(n)
        n += 2
    return {"range": [a, b], "tested": tested,
            "counterexamples": missing, "holds": not missing}
