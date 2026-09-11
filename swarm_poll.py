#!/usr/bin/env python3
"""Quick, non-blocking poll of tracked swarm sessions: reports whether each
is still generating, and saves the response once it's done. Safe to call
repeatedly (each call is fast) instead of relying on one long-lived
background process, which this environment seems to kill after a while."""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

STATE_FILE = Path(__file__).parent / "runs" / "swarm_state.json"


async def poll(roles, cdp_url, out_dir):
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]

        for role in roles:
            if role not in state:
                print(f"{role}: NOT TRACKED")
                continue
            url = state[role]["url"]
            page = None
            for p_ in context.pages:
                if p_.url == url:
                    page = p_
                    break
            if page is None:
                print(f"{role}: TAB NOT FOUND ({url})")
                continue

            stop_btn = page.locator(
                "button[data-testid='stop-button'], button:has-text('Stop generating'), "
                "button[aria-label='Stop generating']"
            )
            generating = bool(await stop_btn.count() and await stop_btn.first.is_visible())

            messages = page.locator("[data-message-author-role='assistant'], .markdown, .agent-turn")
            count = await messages.count()
            text = await messages.nth(count - 1).inner_text() if count else ""

            status = "GENERATING" if generating else "DONE"
            print(f"{role}: {status} ({len(text)} chars)")

            if not generating and text:
                out_file = out_dir / f"{role}.txt"
                out_file.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", required=True, help="Comma-separated role names")
    ap.add_argument("--cdp-url", default="http://localhost:9222")
    ap.add_argument("--out-dir", default="runs/swarm_responses_fix1")
    args = ap.parse_args()
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    asyncio.run(poll(roles, args.cdp_url, args.out_dir))


if __name__ == "__main__":
    main()
