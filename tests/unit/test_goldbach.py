"""Backbone Goldbach: peneira, testemunha, divisão sem perda/dup, faixa."""
from research.goldbach.verifier import (
    sieve, goldbach_witness, check_witness, split_ranges, verify_range)


def test_sieve_primes():
    ip = sieve(30)
    assert [i for i in range(31) if ip[i]] == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]


def test_witness_valid():
    ip = sieve(100)
    assert goldbach_witness(4, ip) == (2, 2)
    assert goldbach_witness(28, ip) == (5, 23)
    p, q = goldbach_witness(100, ip)
    assert p + q == 100 and ip[p] and ip[q]


def test_check_witness_rejects_lies():
    ip = sieve(100)
    assert check_witness(28, 5, 23, ip) is True
    assert check_witness(28, 5, 24, ip) is False   # soma errada
    assert check_witness(28, 4, 24, ip) is False   # 4 e 24 não primos
    assert check_witness(28, 11, 17, ip) is True


def test_split_ranges_no_loss_no_dup():
    ranges = split_ranges(4, 100002, 100)
    assert len(ranges) == 100
    covered = []
    for a, b in ranges:
        assert a % 2 == 0 and b % 2 == 0 and a <= b
        covered += list(range(a, b + 1, 2))
    assert covered == list(range(4, 100003, 2))  # 50.000 pares exatos


def test_verify_range_holds_small():
    ip = sieve(1000)
    r = verify_range(4, 1000, ip)
    assert r["holds"] is True and r["tested"] == 499 and r["counterexamples"] == []
