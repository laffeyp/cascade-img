"""MidjourneyDiscordBackend — thin HTTP wrapper around the local bridge daemon.

The bridge (``bridge.py``) runs as a separate process started by
``cascade-mj-bridge``. This class is the client-side handle. It speaks HTTP
rather than importing daemon internals, so the daemon can restart, be
replaced, or move to another machine without touching the consumer side.

Methods are **synchronous** — wrapping blocking ``requests`` calls in
``async def`` would mark them as coroutines when they are not. Callers that need the
asyncio loop to remain responsive should invoke these via
``asyncio.to_thread(backend.imagine, ...)`` or the MCP server's
``_run_tool`` helper (which already wraps sync callables in to_thread).

Each method emits a ``BACKEND_HTTP_CALLED`` event recording the client-side
HTTP call, alongside the daemon-side state transitions the bridge emits.
"""

from __future__ import annotations

import requests

from cascade_img.backends.base import BackendCapabilities, ImageGenerationBackend
from cascade_img.vocabulary import emit

MIDJOURNEY_DISCORD_CAPABILITIES = BackendCapabilities(
    prompt_parts=["moodboard", "sref", "oref", "ow", "style_raw", "stylize"],
    aspect_ratios=["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2"],
)


class BridgeError(Exception):
    """A bridge HTTP call returned a structured failure. Carries the bridge's
    stable ``code`` (e.g. DISCORD_NOT_READY, NO_UPSCALED_IMAGE, BUTTON_NOT_FOUND,
    UNKNOWN_JOB, or HTTP_<status> when the body had none) and ``remediation`` so
    the MCP ``_run_tool`` envelope surfaces them as ``error.code`` /
    ``error.remediation`` — the same shape every tool failure takes. Without
    this, ``raise_for_status()`` would surface a bare ``HTTPError`` and the
    agent would lose every stable code the bridge took care to send."""

    def __init__(self, code: str, message: str, remediation: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if remediation:
            self.remediation = remediation


# Back-compat alias (the exception was action-only before it generalized).
BridgeActionError = BridgeError


def _raise_for_envelope(r: requests.Response) -> None:
    """Raise :class:`BridgeError` from a non-2xx bridge response, preserving the
    stable code/remediation whether the body is enveloped
    ``{ok: false, error: {code, message, remediation}}`` (e.g. /action) or flat
    ``{error, code, remediation}`` (e.g. /imagine, /status). Falls back to
    ``HTTP_<status>`` when the body carries no code."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        code, msg, rem = err.get("code"), err.get("message"), err.get("remediation")
    elif isinstance(body, dict):
        code = body.get("code")
        msg = (err if isinstance(err, str) else None) or body.get("message")
        rem = body.get("remediation")
    else:
        code = msg = rem = None
    raise BridgeError(code or f"HTTP_{r.status_code}", msg or "bridge request failed", rem)


class MidjourneyDiscordBackend(ImageGenerationBackend):
    capabilities = MIDJOURNEY_DISCORD_CAPABILITIES

    def __init__(self, base_url: str = "http://127.0.0.1:5000") -> None:
        self.base_url = base_url.rstrip("/")

    def imagine(self, prompt: str, asset_id: str, upscale=None) -> dict:
        body: dict = {"prompt": prompt, "asset_id": asset_id}
        if upscale is not None:
            body["upscale"] = upscale
        # Must exceed the bridge's 35 s submit budget, or a slow-but-successful
        # submission reads as a client-side Timeout (and a retry double-bills).
        with requests.post(f"{self.base_url}/imagine", json=body, timeout=40) as r:
            emit("BACKEND_HTTP_CALLED", method="POST", path="/imagine", status=r.status_code)
            # 202 (SUBMITTED_UNCONFIRMED) is a success the caller must see, not a
            # failure — only 4xx/5xx raise.
            if r.status_code >= 400:
                _raise_for_envelope(r)
            return r.json()

    def wait(self, job_id: str, timeout: int = 180) -> dict:
        """Long-poll until the job is terminal or the wait times out.

        A wait-timeout is deliberately NOT raised as an error: the bridge
        returns HTTP 504 with ``timed_out=True`` and the job may still be
        rendering. Re-rolling on a timeout would double-bill, so the timeout is
        a non-terminal signal, not a failure. Callers must branch on the
        returned ``status`` (``done`` / ``failed`` / something in-progress) and
        on ``timed_out`` — a successful HTTP response does NOT imply the job
        finished. Only genuine errors (unknown/evicted job, etc.) raise.
        """
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
            if r.status_code >= 400:
                # 404 unknown job / 410 evicted-during-wait keep their stable
                # code (or HTTP_<status>) instead of flattening to HTTPError.
                _raise_for_envelope(r)
            return r.json()

    def status(self, job_id: str) -> dict:
        with requests.get(f"{self.base_url}/status/{job_id}", timeout=10) as r:
            emit(
                "BACKEND_HTTP_CALLED", method="GET", path=f"/status/{job_id}", status=r.status_code
            )
            if r.status_code >= 400:
                _raise_for_envelope(r)
            return r.json()

    def health(self) -> dict:
        with requests.get(f"{self.base_url}/health", timeout=5) as r:
            emit("BACKEND_HTTP_CALLED", method="GET", path="/health", status=r.status_code)
            if r.status_code >= 400:
                _raise_for_envelope(r)
            return r.json()

    def action(self, job_id: str, action: str, slot: int | None = None) -> dict:
        """Press a response-message button on a completed job's upscaled image
        (vary / zoom / pan / upscale-variant / animate / favorite). ``slot``
        (1-4) targets a specific SOLO image under ``upscale="all"``; omit it for
        the canonical one.

        The bridge's ``/action`` endpoint already speaks the ``{ok, result |
        error}`` envelope. This **unwraps** it: on success it returns the bare
        ``result`` dict (so the MCP ``_run_tool`` layer wraps it exactly once,
        single-level like every other tool); on failure it raises
        :class:`BridgeError` carrying the stable ``code`` (so the failure flows
        through ``_run_tool``'s ``{ok: false, error}`` path with the right
        top-level ``ok``, instead of a confusing ``{ok: true, result: {ok: false,
        ...}}`` double-envelope)."""
        body: dict = {"action": action}
        if slot is not None:
            body["slot"] = slot
        with requests.post(f"{self.base_url}/action/{job_id}", json=body, timeout=40) as r:
            emit(
                "BACKEND_HTTP_CALLED", method="POST", path=f"/action/{job_id}", status=r.status_code
            )
            if r.status_code >= 400:
                _raise_for_envelope(r)
            payload = r.json()
        return payload.get("result", {}) if isinstance(payload, dict) else {}
