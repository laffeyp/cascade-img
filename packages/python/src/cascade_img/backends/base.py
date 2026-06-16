"""Backend interface for image-generation providers.

v0.1 ships :class:`cascade_img.backends.midjourney_discord.MidjourneyDiscordBackend`
only. The surface is deliberately small — a synchronous
``imagine`` / ``wait`` / ``status`` / ``health`` plus a capabilities
declaration — and grows when a second backend lands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import NotRequired, TypedDict


@dataclass
class BackendCapabilities:
    """What a backend declares about itself.

    Records the supported composable prompt parts (moodboard, sref, oref, ow,
    style_raw, stylize, hd, sd, …), the aspect ratios, the selectable model
    ``versions``, and the ``default_version``. Some prompt parts are
    version-gated (the composer raises on a mismatch); ``versions`` /
    ``default_version`` tell a caller which model the parts apply to."""

    prompt_parts: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    default_version: str = ""


class ImagineResult(TypedDict):
    """What :meth:`ImageGenerationBackend.imagine` returns on acceptance."""

    job_id: str
    asset_id: str
    status: str
    upscale: str | None
    # Present when the submission round-trip timed out but the job may still be
    # processed upstream (HTTP 202 SUBMITTED_UNCONFIRMED from the bridge).
    note: NotRequired[str]
    # Present (True) when an idempotency_key matched a live job and the backend
    # replayed it instead of submitting again.
    idempotent_replay: NotRequired[bool]


class JobState(TypedDict, total=False):
    """A job's current state, as returned by :meth:`wait` and :meth:`status`.

    ``job_id`` / ``asset_id`` / ``status`` are always present; the rest fill in
    as the job progresses. ``total=False`` because the dict is a snapshot of the
    backend's job record and backends may carry extra provider-specific fields
    (the Midjourney bridge returns the full job row).
    """

    job_id: str
    asset_id: str
    status: str  # "queued" | "submitted" | "progress" | "upscaling" | "done" | "failed" | ...
    prompt: str
    upscale: str | None  # None | "1".."4" | "all"
    progress: str
    image_path: str | None
    image_url: str | None
    grid_path: str | None
    grid_url: str | None
    upscale_paths: dict[int, str]
    upscale_pending: list[int]
    upscale_press_failures: dict[int, str]
    upscale_download_failures: dict[int, str]
    derived: list[dict]
    error: str | None
    error_code: str | None
    idempotency_key: str | None
    created_at: float
    updated_at: float
    # Set (True) by :meth:`wait` when the wait window expired before the job
    # went terminal. The job may still be rendering — do NOT resubmit.
    timed_out: bool


class HealthReport(TypedDict, total=False):
    """Backend liveness, as returned by :meth:`health`.

    ``total=False``: beyond the generally useful counters listed here, each
    backend reports its own upstream specifics (the Midjourney bridge adds
    ``discord_ready``, ``pending_grid``, ``upscaling``, ``output_dir``).
    """

    total_jobs: int
    discord_ready: bool
    pending_grid: int
    upscaling: int
    output_dir: str


class ImageGenerationBackend(ABC):
    """Minimal v0.1 surface: submit a job, await its result, read status, report health.

    Methods are **synchronous**. Callers needing asyncio responsiveness invoke
    via ``asyncio.to_thread(backend.imagine, ...)`` rather than wrapping blocking
    ``requests`` calls in ``async def``."""

    capabilities: BackendCapabilities

    @abstractmethod
    def imagine(
        self,
        prompt: str,
        asset_id: str,
        upscale: str | None = None,
        idempotency_key: str | None = None,
    ) -> ImagineResult:
        """Submit a generation.

        ``upscale`` is ``None`` (grid only), ``"1"``-``"4"`` (one slot) or
        ``"all"``. ``idempotency_key``, when supplied, makes a retry safe: a key
        already attached to a live job replays that job instead of submitting
        again. Returns an :class:`ImagineResult` whose ``job_id`` is passed to
        :meth:`wait`."""

    @abstractmethod
    def wait(self, job_id: str, timeout: int = 180) -> JobState:
        """Block until the job hits ``done`` or ``failed`` or the timeout fires.

        A timeout is NOT an error: the returned state carries
        ``timed_out=True`` and the job may still complete — callers must branch
        on ``status`` and ``timed_out``, never resubmit on timeout."""

    @abstractmethod
    def status(self, job_id: str) -> JobState:
        """Non-blocking read of the job's current state (the ``status`` MCP tool)."""

    @abstractmethod
    def health(self) -> HealthReport:
        """Report backend liveness — daemon up, upstream connected (``bridge_health``)."""
