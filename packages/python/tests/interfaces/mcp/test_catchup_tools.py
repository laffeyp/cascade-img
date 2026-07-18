"""Behavior contract for the catch-up MCP tools (channel_recent /
adopt_message): envelopes, gating, and the human-origin prompt-log record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cascade_img.interfaces.mcp import _envelope
from cascade_img.interfaces.mcp.tool_server import adopt_message, channel_recent
from cascade_img.prompt.prompt_log import PromptLog
from cascade_img.vocabulary import clear, snapshot


class _FakeBackend:
    def channel_recent(self, n: int = 10) -> dict:
        return {
            "messages": [
                {"message_id": "500", "kind": "grid", "tracked_job_id": "j1"},
                {"message_id": "501", "kind": "solo", "tracked_job_id": None},
            ],
            "source": "buffer",
        }

    def adopt(self, message_id: str, asset_id: str) -> dict:
        return {
            "job_id": "adopted-1",
            "asset_id": asset_id,
            "kind": "solo",
            "image_path": f"/tmp/{asset_id}.png",
            "buttons": ["vary_strong"],
            "origin": "adopted",
        }


def _tags() -> list[str]:
    return [r["tag"] for r in snapshot()]


@pytest.mark.asyncio
async def test_channel_recent_envelope(monkeypatch):
    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await channel_recent(n=2)
    assert r["ok"] is True
    msgs = r["result"]["messages"]
    assert msgs[1]["tracked_job_id"] is None  # the catch-up candidate
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_channel_recent_is_exempt_from_guide_gate(monkeypatch):
    _envelope._guide_read = False
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await channel_recent()
    assert r["ok"] is True  # orientation tool: open before the manual is read


@pytest.mark.asyncio
async def test_adopt_message_is_gated(monkeypatch):
    _envelope._guide_read = False
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await adopt_message(message_id="501", asset_id="x")
    assert r["ok"] is False
    assert r["error"]["code"] == "GUIDE_UNREAD"


@pytest.mark.asyncio
async def test_adopt_message_appends_human_origin_log_record(monkeypatch, tmp_path: Path):
    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    log_path = tmp_path / "log.jsonl"
    monkeypatch.setattr(_envelope, "_log", PromptLog(log_path))

    r = await adopt_message(message_id="501", asset_id="manual-u4")
    assert r["ok"] is True
    assert r["result"]["job_id"] == "adopted-1"

    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(records) == 1
    rec = records[0]
    assert rec["origin"] == "human_in_discord"
    assert rec["asset_id"] == "manual-u4"
    assert rec["job_id"] == "adopted-1"
    assert rec["agent_decision"] is None


def test_prompt_log_origin_roundtrip(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(asset_id="a", prompt="p", backend="b")  # default: agent's own loop
    log.append(asset_id="a", prompt="p2", backend="b", origin="human_in_discord")
    recs = log.read()
    assert recs[0]["origin"] is None
    assert recs[1]["origin"] == "human_in_discord"
