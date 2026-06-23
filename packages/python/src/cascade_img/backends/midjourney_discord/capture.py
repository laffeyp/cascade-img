"""Raw-message capture hook (observation-only; env-gated; OFF by default).

Extracted from bridge.py (sprint 023.7).

When ``CASCADE_CAPTURE_RAW`` points at a path, ingest appends one JSON line per
MJ-bot message in the watched channel — structure only, NO interpretation — so
derived results (vary / zoom / pan / animate / favorite) that the bridge cannot
route to a tracked job are still recorded verbatim for the receive-side matchers.
Wrapped so a capture failure never breaks the live path.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("cascade_img.bridge.capture")


def _capture_raw_message(message, event: str) -> None:
    """Append a structure-only JSON line describing ``message`` to the path in
    CASCADE_CAPTURE_RAW. No-op when the env var is unset. Best-effort: any
    failure is logged and swallowed so it can never disturb live ingestion.
    """
    capture_path = os.environ.get("CASCADE_CAPTURE_RAW")
    if not capture_path:
        return
    try:
        import json as _json

        # Timestamps: record whichever discord.py-self exposes and tag which.
        created_at = getattr(message, "created_at", None)
        edited_at = getattr(message, "edited_at", None)
        ref = getattr(message, "reference", None)
        ref_id = getattr(ref, "message_id", None) if ref is not None else None

        attachments = []
        for a in getattr(message, "attachments", None) or []:
            attachments.append(
                {
                    "filename": getattr(a, "filename", None),
                    "url": getattr(a, "url", None),
                    "content_type": getattr(a, "content_type", None),
                    "size": getattr(a, "size", None),
                    "width": getattr(a, "width", None),
                    "height": getattr(a, "height", None),
                    "duration": getattr(a, "duration", None),
                }
            )

        components = []
        for row in getattr(message, "components", None) or []:
            for child in getattr(row, "children", None) or []:
                style = getattr(child, "style", None)
                components.append(
                    {
                        "type": getattr(getattr(child, "type", None), "value", None)
                        or str(getattr(child, "type", None)),
                        "custom_id": getattr(child, "custom_id", None),
                        "label": getattr(child, "label", None),
                        "style": getattr(style, "value", None) or str(style)
                        if style is not None
                        else None,
                    }
                )

        record = {
            "event": event,
            "id": getattr(message, "id", None),
            "channel_id": getattr(getattr(message, "channel", None), "id", None),
            "author_id": getattr(getattr(message, "author", None), "id", None),
            "created_at": created_at.isoformat() if created_at is not None else None,
            "edited_at": edited_at.isoformat() if edited_at is not None else None,
            "content": message.content or "",
            "message_reference": ref_id,
            "attachments": attachments,
            "components": components,
        }
        line = _json.dumps(record, default=str)
        with open(capture_path, "a") as f:
            f.write(line + "\n")
    except Exception as e:  # capture is observation-only; never break live path
        log.warning(f"raw-capture failed: {type(e).__name__}: {e}")
