"""Video curation: make a temporal artifact inspectable in the curation loop.

An agent can't "read a video with vision" the way it reads a still, so these
project a video (animated webp) into vision-readable / numeric signals:

* :func:`~cascade_img.curation.video.filmstrip.video_filmstrip` — sample
  keyframes into one labeled contact sheet + emit a frame/duration signature
  (F32, the video analog of an audio waveform-with-time-markers).
* :func:`~cascade_img.curation.video.loop_seam.loop_seam_delta` — report how
  cleanly a looping video closes, as a number (F33).
"""

from cascade_img.curation.video.filmstrip import video_filmstrip
from cascade_img.curation.video.loop_seam import loop_seam_delta

__all__ = ["loop_seam_delta", "video_filmstrip"]
