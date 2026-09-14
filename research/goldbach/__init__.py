"""Pesquisa Goldbach — backbone determinístico + orquestração de 100 agentes."""
from .verifier import sieve, goldbach_witness, check_witness, split_ranges, verify_range

__all__ = ["sieve", "goldbach_witness", "check_witness", "split_ranges", "verify_range"]
