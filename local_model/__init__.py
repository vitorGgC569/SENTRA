"""
Local LLM Integration (Qwen) for SENTRA.
"""
from .qwen_client import QwenLocalClient
from .prompts import PromptBuilder

__all__ = ["QwenLocalClient", "PromptBuilder"]
