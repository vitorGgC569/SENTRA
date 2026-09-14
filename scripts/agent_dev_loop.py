#!/usr/bin/env python3
"""Dev loop multi-turn em UMA conversa: agente codifica via protocolo do gateway.

Turno 1 (new_chat): brief da tarefa + protocolo [[R|...]] + entrega em bloco python.
Turnos seguintes (mesma conversa): harness executa leituras pedidas e devolve o
conteúdo real; aplica o código; roda os testes PRIVADOS; devolve o resultado.
Valida: leitura sob demanda, código aplicado de verdade, teste real, repair.

Uso: OMA_LIVE_EXTENSION=1 python scripts/agent_dev_loop.py [--turns 6]
Sem OMA_LIVE_EXTENSION=1: RECUSA.
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TASK_DIR = Path(__file__).resolve().parent.parent / "research" / "agent_dev" / "palindrome"
PRIVATE_TESTS = Path(__file__).resolve().parent.parent / "research" / "agent_dev" / "_private"
CODE_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)

BRIEF = """[DEV-001] Você é um desenvolvedor num loop real com runtime local.
TAREFA: leia spec.md e stub.py neste diretório e implemente is_palindrome_number.

PROTOCOLO (único jeito de ler arquivos — NÃO invente conteúdo):
- Para ler: emita uma linha [[R|caminho|ini|fim]] (ex. [[R|spec.md|1|40]])
- O runtime executa e cola o conteúdo REAL na próxima mensagem. Aguarde-o.
- Para entregar: bloco ```python com o CONTEÚDO COMPLETO de solution.py

O runtime vai aplicar seu código e rodar testes de verdade, devolvendo o
resultado aqui mesmo. Comece pedindo as leituras que precisar."""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--run-id", default="RUN-AGENT-DEV-001")
    args = ap.parse_args()
    if os.environ.get("OMA_LIVE_EXTENSION") != "1":
        print("RECUSADO: caminho exclusivamente real (OMA_LIVE_EXTENSION=1).")
        sys.exit(2)

    from repository.gateway import CommandGateway
    from repository.parser import find_all
    from browser.tab_pool import TabPool
    from orchestrator.providers.base import AgentRequest
    from orchestrator.providers.extension_provider import BrowserExtensionProvider

    run_dir = Path("runs") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    transcript = []

    gw = CommandGateway(TASK_DIR)
    sess = gw.open_session()
    provider = BrowserExtensionProvider()
    pool = TabPool(min_tabs=1, max_tabs=1)
    conv_url = None
    solution = TASK_DIR / "solution.py"

    async def send(text: str, new_chat: bool):
        nonlocal conv_url
        result = {}

        async def h(worker, tid):
            nonlocal conv_url
            req = AgentRequest(system_prompt="Você está no loop dev OMA. Sem prosa fora do necessário.",
                               user_prompt=text, role="executor", timeout=240,
                               metadata={"task_id": tid, "new_chat": new_chat,
                                         **({"conversation_url": conv_url} if conv_url else {})})
            resp = await provider.execute(req)
            if not resp.success:
                raise RuntimeError(resp.error)
            conv_url = provider.conversations[tid]["conversation_url"]
            result["text"] = resp.content

        outcome = await pool.run_all(["T-DEV-001"], h, timeout_per_task=360)
        if outcome["failed"]:
            transcript.append({"out": text[:300], "in": "", "url": conv_url,
                               "error": list(outcome["failed"].values())[0][:300]})
            (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
            raise RuntimeError(f"turno falhou: {list(outcome['failed'].values())[0][:300]}")
        transcript.append({"out": text[:300], "in": result["text"][:2000], "url": conv_url})
        (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
        print(f"[dev-loop] resposta ({len(result['text'])} chars, url={conv_url})", flush=True)
        return result["text"]

    def run_tests() -> tuple:
        p = subprocess.run([sys.executable, "-m", "pytest", str(PRIVATE_TESTS), "-q"],
                           capture_output=True, text=True, timeout=120,
                           cwd=str(Path(__file__).resolve().parent.parent))
        return p.returncode == 0, (p.stdout + p.stderr)[-1500:]

    print(f"[dev-loop] turno 1 (new chat)...", flush=True)
    answer = await send(BRIEF, new_chat=True)
    for turn in range(2, args.turns + 1):
        reads = [d for d in find_all(answer) if d.operation == "R" and d.known]
        code = CODE_RE.search(answer or "")
        follow = []
        if reads:
            for d in reads[:3]:
                try:
                    out = await gw.execute(sess, d.raw, agent_id="dev-agent",
                                           task_id="T-DEV-001", role="executor")
                except Exception as e:
                    out = f"ERROR: {e}"
                follow.append(f"Resultado de {d.raw}:\n{out[:2000]}")
        if code and not reads:
            solution.write_text(code.group(1).strip() + "\n", encoding="utf-8")
            ok, out = run_tests()
            (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
            if ok:
                print(f"[dev-loop] TESTES PASSARAM no turno {turn}. Conversa: {conv_url}")
                await send("APROVADO: todos os testes passaram. Resuma a solução em 2 linhas.",
                           new_chat=False)
                print(f"[dev-loop] DONE em {turn} turnos. Transcrição: {run_dir / 'transcript.json'}")
                return
            follow.append(f"TESTES FALHARAM:\n{out}\nCorrija e reenvie o bloco ```python completo.")
        if not reads and not code:
            follow.append("Sem leitura [[R|...]] e sem bloco ```python. Peça leitura ou entregue o código.")
        print(f"[dev-loop] turno {turn + 1} (mesma conversa)...", flush=True)
        answer = await send("\n\n".join(follow), new_chat=False)
    (run_dir / "transcript.json").write_text(json.dumps(transcript, indent=1), encoding="utf-8")
    print(f"[dev-loop] turnos esgotados sem aprovação. Conversa: {conv_url}")


if __name__ == "__main__":
    asyncio.run(main())
