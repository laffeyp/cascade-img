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
from cascade_img.vocabulary import emit

MIDJOURNEY_DISCORD_CAPABILITIES = BackendCapabilities(
    prompt_parts=["moodboard", "sref", "oref", "ow", "style_raw", "stylize"],
    aspect_ratios=["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2"],
)


class BridgeActionError(Exception):
    """A ``POST /action`` call returned a structured failure. Carries the bridge's
    stable ``code`` (NO_UPSCALED_IMAGE, BUTTON_NOT_FOUND, DISCORD_NOT_READY,
    UNKNOWN_JOB, UNKNOWN_ACTION, HTTP_<status>) and ``remediation`` so the MCP
    ``_run_tool`` envelope surfaces them as ``error.code`` / ``error.remediation``
    — the same shape every other tool failure takes."""

    def __init__(self, code: str, message: str, remediation: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if remediation:
            self.remediation = remediation


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
            emit(
                "BACKEND_HTTP_CALLED", method="GET", path=f"/status/{job_id}", status=r.status_code
            )
            r.raise_for_status()
            return r.json()

    def health(self) -> dict:
        with requests.get(f"{self.base_url}/health", timeout=5) as r:
            emit("BACKEND_HTTP_CALLED", method="GET", path="/health", status=r.status_code)
            r.raise_for_status()
            return r.json()

    def action(self, job_id: str, action: str) -> dict:
        """Press a response-message button on a completed job's upscaled image
        (vary / zoom / pan / upscale-variant / animate / favorite).

        The bridge's ``/action`` endpoint already speaks the ``{ok, result |
        error}`` envelope. This **unwraps** it: on success it returns the bare
        ``result`` dict (so the MCP ``_run_tool`` layer wraps it exactly once,
        single-level like every other tool); on failure it raises
        :class:`BridgeActionError` carrying the stable ``code`` (so the failure
        flows through ``_run_tool``'s ``{ok: false, error}`` path with the right
        top-level ``ok``, instead of a confusing ``{ok: true, result: {ok: false,
        ...}}`` double-envelope)."""
        with requests.post(
            f"{self.base_url}/action/{job_id}", json={"action": action}, timeout=40
        ) as r:
            emit(
                "BACKEND_HTTP_CALLED", method="POST", path=f"/action/{job_id}", status=r.status_code
            )
            body = r.json()
        if not isinstance(body, dict) or not body.get("ok", False):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise BridgeActionError(
                err.get("code") or f"HTTP_{r.status_code}",
                err.get("message") or "action failed",
                err.get("remediation"),
            )
        return body.get("result", {})
