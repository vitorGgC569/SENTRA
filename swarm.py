#!/usr/bin/env python3
"""
Drives a persistent swarm of named ChatGPT Web sessions via CDP for a target
project. Each role keeps a single long-lived conversation tab (identified by
its chatgpt.com/c/<id> URL) so follow-up prompts land in the same thread and
keep context, instead of starting a fresh chat every dispatch.

State (role -> {url, title}) is stored in runs/swarm_state.json so separate
invocations of this script can find the right tab again.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

STATE_FILE = Path(__file__).parent / "runs" / "swarm_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


async def find_page(context: BrowserContext, url: str) -> Optional[Page]:
    for page in context.pages:
        if page.url == url:
            return page
    return None


async def send_prompt(page: Page, prompt: str) -> None:
    input_box = page.get_by_role("textbox")
    if not await input_box.count():
        input_box = page.locator("#prompt-textarea, textarea, [contenteditable='true']")
    await input_box.first.fill(prompt)
    await asyncio.sleep(0.5)

    send_btn = page.locator("button[data-testid='send-button'], button:has-text('Send')")
    if await send_btn.count() and await send_btn.first.is_visible():
        await send_btn.first.click()
    else:
        await input_box.first.press("Enter")


async def is_finished(page: Page) -> bool:
    stop_btn = page.locator(
        "button[data-testid='stop-button'], button:has-text('Stop generating'), "
        "button[aria-label='Stop generating']"
    )
    if await stop_btn.count() and await stop_btn.first.is_visible():
        return False
    return True


async def extract_last_response(page: Page) -> str:
    messages = page.locator("[data-message-author-role='assistant'], .markdown, .agent-turn")
    count = await messages.count()
    if count == 0:
        return ""
    return await messages.nth(count - 1).inner_text()


async def wait_for_stable_response(page: Page, timeout_seconds: int, stable_samples: int = 3) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    previous_hash = None
    stable_count = 0
    last_text = ""

    while asyncio.get_running_loop().time() < deadline:
        try:
            text = await extract_last_response(page)
        except Exception:
            text = ""

        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_hash == previous_hash and text:
            stable_count += 1
        else:
            stable_count = 0
            previous_hash = text_hash
        last_text = text

        try:
            finished = await is_finished(page)
        except Exception:
            finished = False

        if finished and stable_count >= stable_samples:
            return text

        await asyncio.sleep(1.5)

    return last_text + "\n\n[WARNING: timed out waiting for a stable response]"


async def get_or_create_page(context: BrowserContext, state: dict, role: str, force_new: bool) -> Page:
    if role in state and not force_new:
        page = await find_page(context, state[role]["url"])
        if page:
            return page
        print(f"[{role}] Stored tab not found (closed?) - opening a new one.")

    page = await context.new_page()
    await page.goto("https://chatgpt.com", wait_until="domcontentloaded")
    await asyncio.sleep(1.5)
    return page


async def dispatch_one(context: BrowserContext, state: dict, role: str, prompt: str, timeout: int, force_new: bool) -> dict:
    page = await get_or_create_page(context, state, role, force_new)
    await send_prompt(page, prompt)
    await asyncio.sleep(1.0)
    response = await wait_for_stable_response(page, timeout_seconds=timeout)
    title = await page.title()
    state[role] = {"url": page.url, "title": title}
    return {"role": role, "title": title, "url": page.url, "response": response}


async def cmd_send(args) -> None:
    state = load_state()
    prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0]
        result = await dispatch_one(context, state, args.role, prompt, args.timeout, args.new)
        save_state(state)
        # Do NOT call browser.close() here: this is the user's real, already
        # running browser (attached via CDP) - closing it would kill their
        # window. Just let the CDP connection drop when the script exits.

    print(f"=== ROLE: {result['role']} ===")
    print(f"=== TITLE: {result['title']} ===")
    print(f"=== URL: {result['url']} ===")
    print(result["response"])


async def cmd_send_batch(args) -> None:
    state = load_state()
    batch = json.loads(Path(args.config).read_text(encoding="utf-8"))

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0]

        tasks = [
            dispatch_one(context, state, role, prompt, args.timeout, args.new)
            for role, prompt in batch.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        save_state(state)

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).parent / "runs" / "swarm_responses"
    out_dir.mkdir(parents=True, exist_ok=True)

    for role, result in zip(batch.keys(), results):
        if isinstance(result, Exception):
            print(f"=== ROLE: {role} === ERROR: {result}")
            continue
        out_file = out_dir / f"{role}.txt"
        out_file.write_text(result["response"], encoding="utf-8")
        print(f"=== ROLE: {result['role']} | TITLE: {result['title']} ===")
        print(f"Saved to {out_file} ({len(result['response'])} chars)")


def cmd_list(args) -> None:
    state = load_state()
    if not state:
        print("No sessions tracked yet.")
        return
    for role, info in state.items():
        print(f"{role} | {info.get('title')} | {info.get('url')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent ChatGPT Web swarm driver")
    sub = parser.add_subparsers(dest="cmd", required=True)

    send_p = sub.add_parser("send", help="Send a prompt to a single named session")
    send_p.add_argument("--role", required=True)
    send_p.add_argument("--prompt")
    send_p.add_argument("--prompt-file")
    send_p.add_argument("--cdp-url", default="http://localhost:9222")
    send_p.add_argument("--timeout", type=int, default=600)
    send_p.add_argument("--new", action="store_true", help="Force a fresh conversation for this role")

    batch_p = sub.add_parser("send-batch", help="Send different prompts to multiple sessions concurrently")
    batch_p.add_argument("--config", required=True, help="JSON file: {role: prompt, ...}")
    batch_p.add_argument("--cdp-url", default="http://localhost:9222")
    batch_p.add_argument("--timeout", type=int, default=600)
    batch_p.add_argument("--new", action="store_true")
    batch_p.add_argument("--out-dir")

    list_p = sub.add_parser("list", help="List tracked sessions")

    args = parser.parse_args()

    if args.cmd == "send":
        if not args.prompt and not args.prompt_file:
            parser.error("send requires --prompt or --prompt-file")
        asyncio.run(cmd_send(args))
    elif args.cmd == "send-batch":
        asyncio.run(cmd_send_batch(args))
    elif args.cmd == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
