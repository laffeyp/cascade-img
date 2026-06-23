"""Promote a curated asset from staging into the consumer's asset tree.

Thin wrapper: read bytes, write bytes, emit a signal. Creates parent
directories as needed; overwrites the destination if present (curation
regenerations are expected to replace prior promotions).
"""

from __future__ import annotations

from pathlib import Path

from cascade_img.vocabulary import emit


def promote(src: str | Path, dest: str | Path) -> Path:
    """Copy a curated asset to its destination path.

    Args:
        src: Path to the staging asset (e.g. a cropped + alpha-keyed PNG).
        dest: Destination path inside the consumer's asset tree.

    Returns:
        The resolved destination path.

    Raises:
        FileNotFoundError: src does not exist.
    """
    src_p = Path(src)
    dest_p = Path(dest)
    if not src_p.exists():
        raise FileNotFoundError(f"source asset not found: {src_p}")
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    data = src_p.read_bytes()
    dest_p.write_bytes(data)
    emit(
        "ASSET_PROMOTED",
        src=str(src_p),
        dest=str(dest_p),
        bytes=len(data),
    )
    return dest_p
