from __future__ import annotations

import asyncio
import hashlib
from typing import Callable, Awaitable


class ResponseCapture:
    @staticmethod
    async def wait_for_stable_response(
        extract_text_fn: Callable[[], Awaitable[str]],
        is_finished_fn: Callable[[], Awaitable[bool]],
        timeout_seconds: int = 600,
        stable_samples: int = 3,
    ) -> str:
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        previous_hash = None
        stable_count = 0
        last_text = ""

        while asyncio.get_running_loop().time() < deadline:
            try:
                text = await extract_text_fn()
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
                finished = await is_finished_fn()
            except Exception:
                finished = False

            if finished and stable_count >= stable_samples:
                return text

            # If END_RESULT marker is present and stable sample count reached
            if "END_RESULT" in text and stable_count >= stable_samples:
                return text

            await asyncio.sleep(1.5)

        # Deadline exceeded without stable finished response: surface a real
        # timeout (RF-016) instead of silently returning a partial capture.
        # Callers that want a degraded fallback must catch this explicitly.
        raise TimeoutError(
            f"Timed out after {timeout_seconds}s waiting for stable chatgpt.com response "
            f"(last capture {len(last_text)} chars, stable_samples={stable_count}/{stable_samples})"
        )
