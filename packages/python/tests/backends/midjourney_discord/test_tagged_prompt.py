"""Behavior contract: the per-job routing token merges into a user --no clause.

When the composer emits a user negative-prompt clause, the bridge must fold its
collision-routing needle into that single --no clause rather than appending a
second --no (which would break Midjourney's parsing and the match path).
"""

from __future__ import annotations

from cascade_img.backends.midjourney_discord.bridge import (
    Job,
    _merge_no_clause,
    _token_needle,
)


def test_appends_fresh_no_clause_when_none_present():
    out = _merge_no_clause("a mountain --ar 1:1 --v 7", "abc123")
    assert out == "a mountain --ar 1:1 --v 7 --no cscidnocollideabc123"
    assert out.count("--no") == 1
    assert _token_needle("abc123") in out


def test_merges_into_existing_no_clause():
    out = _merge_no_clause("a mountain --ar 1:1 --v 7 --no text, watermark", "abc123")
    assert out == "a mountain --ar 1:1 --v 7 --no text, watermark, cscidnocollideabc123"
    assert out.count("--no") == 1
    assert _token_needle("abc123") in out


def test_merges_into_mid_prompt_no_clause_preserving_trailing_flags():
    # A hand-crafted raw prompt with --no mid-string: the needle folds into the
    # --no list and the trailing render flags (--ar, --s) are preserved, not
    # swallowed into the negative-prompt words (which would default MJ's aspect
    # ratio / stylize).
    out = _merge_no_clause("a cat --no text, watermark --ar 16:9 --s 750", "abc123")
    assert out == "a cat --no text, watermark, cscidnocollideabc123 --ar 16:9 --s 750"
    assert out.count("--no") == 1
    assert _token_needle("abc123") in out


def test_job_tagged_prompt_uses_merge():
    job = Job(job_id="j1", asset_id="a", prompt="a mountain --v 7 --no text", request_token="tok")
    tagged = job.tagged_prompt()
    assert tagged == "a mountain --v 7 --no text, cscidnocollidetok"
    assert tagged.count("--no") == 1
    assert _token_needle("tok") in tagged
