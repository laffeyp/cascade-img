"""MidjourneyDiscordBackend — thin HTTP wrapper around the local bridge daemon.

The bridge (``bridge.py``) runs as a separate process started by
``cascade-mj-bridge``. This class is the client-side handle. It speaks HTTP
rather than importing daemon internals, so the daemon can restart, be
replaced, or move to another machine without touching the consumer side.

Methods are **synchronous** — wrapping blocking ``requests`` calls in
``async def`` would lie about the coroutine contract. Callers that need the
asyncio loop to remain responsive should invoke these via
``asyncio.to_thread(backend.imagine, ...)`` or the MCP server's
``_run_tool`` helper (which already wraps sync callables in to_thread).

Each method emits a ``BACKEND_HTTP_CALLED`` signal so graders see the
client-side traffic, not just the daemon-side state transitions.
"""

from __future__ import annotations

import requests

from cascade_img.backends.base import BackendCapabilities, ImageGenerationBackend
from cascade_img.instrumentation.sdd import emit


MIDJOURNEY_DISCORD_CAPABILITIES = BackendCapabilities(
    facets=["moodboard", "sref", "oref", "ow", "style_raw", "stylize"],
    aspect_ratios=["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2"],
)


class MidjourneyDiscordBackend(ImageGenerationBackend):
    capabilities = MIDJOURNEY_DISCORD_CAPABILITIES

    def __init__(self, base_url: str = "http://127.0.0.1:5000") -> None:
        self.base_url = base_url.rstrip("/")

    def imagine(self, prompt: str, asset_id: str, upscale=None) -> dict:
        body: dict = {"prompt": prompt, "asset_id": asset_id}
        if upscale is not None:
            body["upscale"] = upscale
        with requests.post(f"{self.base_url}/imagine", json=body, timeout=30) as r:
            emit("BACKEND_HTTP_CALLED", method="POST", path="/imagine", status=r.status_code)
            r.raise_for_status()
            return r.json()

    def wait(self, job_id: str, timeout: int = 180) -> dict:
        with requests.get(
            f"{self.base_url}/wait/{job_id}",
            params={"timeout": timeout},
            timeout=timeout + 5,
        ) as r:
            emit("BACKEND_HTTP_CALLED", method="GET", path=f"/wait/{job_id}", status=r.status_code)
            if r.status_code == 504:
                data = r.json()
                data["timed_out"] = True
                return data
            r.raise_for_status()
            return r.json()

    def status(self, job_id: str) -> dict:
        with requests.get(f"{self.base_url}/status/{job_id}", timeout=10) as r:
            emit("BACKEND_HTTP_CALLED", method="GET", path=f"/status/{job_id}", status=r.status_code)
            r.raise_for_status()
            return r.json()

    def health(self) -> dict:
        with requests.get(f"{self.base_url}/health", timeout=5) as r:
            emit("BACKEND_HTTP_CALLED", method="GET", path="/health", status=r.status_code)
            r.raise_for_status()
            return r.json()
