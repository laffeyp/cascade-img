"""Reduce an image to a fixed palette for the limited-palette look.

Wraps PIL's quantizers. Transparency is preserved: PIL quantizes RGB only, so
the alpha channel is split off, the RGB is quantized, and alpha is reattached.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from cascade_img.vocabulary import emit

_METHODS = {
    "median_cut": Image.Quantize.MEDIANCUT,
    "maximum_coverage": Image.Quantize.MAXCOVERAGE,
    "octree": Image.Quantize.FASTOCTREE,
}


def palette_quantize(
    src: str | Path,
    dest: str | Path,
    *,
    n_colors: int = 16,
    method: str = "median_cut",
) -> Path:
    """Quantize ``src`` to ``n_colors`` and write the result to ``dest``.

    Args:
        src: Path to the image.
        dest: Output path.
        n_colors: Palette size (2-256).
        method: ``"median_cut"``, ``"maximum_coverage"``, or ``"octree"``.

    Returns:
        The resolved ``dest`` path.
    """
    if method not in _METHODS:
        raise ValueError(
            f"palette_quantize: unknown method {method!r}; expected one of {sorted(_METHODS)}."
        )
    if not 2 <= n_colors <= 256:
        raise ValueError(f"palette_quantize: n_colors must be 2-256; got {n_colors!r}.")

    src_p, dest_p = Path(src), Path(dest)
    with Image.open(src_p) as im:
        img = im.convert("RGBA")

    alpha = img.getchannel("A")
    quantized = img.convert("RGB").quantize(colors=n_colors, method=_METHODS[method])
    out = quantized.convert("RGBA")
    out.putalpha(alpha)

    dest_p.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest_p)
    emit(
        "PALETTE_QUANTIZED",
        src=str(src_p),
        dest=str(dest_p),
        n_colors=n_colors,
        method=method,
    )
    return dest_p
