"""MidjourneyDiscordBackend — thin HTTP wrapper around the local bridge daemon.

The bridge (``bridge.py``) runs as a separate process started by
``cascade-mj-bridge``. This class is the client-side handle. It speaks HTTP
rather than importing daemon internals, so the daemon can restart, be
replaced, or move to another machine without touching the consumer side.

Each method emits a ``BACKEND_HTTP_CALLED`` signal so graders can see the
client-side traffic, not just the daemon-side state transitions.
"""

from __future__ import annotations

import requests

from cascade_img.backends.base import BackendCapabilities, ImageGenerationBackend
from cascade_img.instrumentation.runtime import emit


MIDJOURNEY_DISCORD_CAPABILITIES = BackendCapabilities(
    facets=["moodboard", "sref", "oref", "ow", "style_raw", "stylize"],
    aspect_ratios=["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2"],
)


class MidjourneyDiscordBackend(ImageGenerationBackend):
    capabilities = MIDJOURNEY_DISCORD_CAPABILITIES

    def __init__(self, base_url: str = "http://127.0.0.1:5000") -> None:
        self.base_url = base_url.rstrip("/")

    async def imagine(self, prompt: str, asset_id: str, upscale=None) -> dict:
        body: dict = {"prompt": prompt, "asset_id": asset_id}
        if upscale is not None:
            body["upscale"] = upscale
        r = requests.post(f"{self.base_url}/imagine", json=body, timeout=30)
        emit("BACKEND_HTTP_CALLED", method="POST", path="/imagine", status=r.status_code)
        r.raise_for_status()
        return r.json()

    async def wait(self, job_id: str, timeout: int = 180) -> dict:
        r = requests.get(
            f"{self.base_url}/wait/{job_id}",
            params={"timeout": timeout},
            timeout=timeout + 5,
        )
        emit("BACKEND_HTTP_CALLED", method="GET", path=f"/wait/{job_id}", status=r.status_code)
        if r.status_code == 504:
            data = r.json()
            data["timed_out"] = True
            return data
        r.raise_for_status()
        return r.json()

    async def status(self, job_id: str) -> dict:
        r = requests.get(f"{self.base_url}/status/{job_id}", timeout=10)
        emit("BACKEND_HTTP_CALLED", method="GET", path=f"/status/{job_id}", status=r.status_code)
        r.raise_for_status()
        return r.json()

    async def health(self) -> dict:
        r = requests.get(f"{self.base_url}/health", timeout=5)
        emit("BACKEND_HTTP_CALLED", method="GET", path="/health", status=r.status_code)
        r.raise_for_status()
        return r.json()
