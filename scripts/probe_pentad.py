#!/usr/bin/env python3
"""Sonda live de 2 turnos no MESMO seat: valida FixedConversationRouter de
ponta a ponta (novo chat + continuação) e o estado da quota de uma vez."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    from orchestrator.agents.router import ModelRouter
    from orchestrator.conversation_pool import FixedConversationRouter
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider

    store = Path(tempfile.mkdtemp())
    inner = BrowserExtensionProvider()
    router = ModelRouter(providers={"primary": inner},
                         primary_provider_name="primary", fallback_provider_name=None)
    pool = FixedConversationRouter(router, run_id="RUN-PROBE5", store_dir=store,
                                   inter_call_delay_s=30)
    prompts = ["Responda exatamente: PENTAD_OK_1",
               "Responda exatamente: PENTAD_OK_2 (mesmo chat)"]
    for turn, text in enumerate(prompts, 1):
        req = AgentRequest(system_prompt="Eco exato.", user_prompt=text,
                           role="executor", timeout=180,
                           metadata={"task_id": f"T-{turn}"})
        r = await pool.execute(req)
        print(f"turno {turn}: success={r.success} err={str(r.error or '')[:160]}",
              flush=True)
        assert r.success, r.error
        assert ("PENTAD_OK_1" if turn == 1 else "PENTAD_OK_2") in (r.content or "")
    print("seats:", pool.seats(), flush=True)
    print("PENTAD PROBE OK: mesmo chat continuado", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
