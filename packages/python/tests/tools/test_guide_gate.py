"""The read-first gate + cascade_guide tool (Sprint 027).

Verifies the activation mechanism: gated tools refuse with GUIDE_UNREAD (without
touching the backend) until cascade_guide is read this session; exempt tools stay
open; and cascade_guide returns the full corpus.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cascade_img.guide import load_guide
from cascade_img.interfaces.mcp import _envelope
from cascade_img.interfaces.mcp.tools import bridge_health, cascade_guide, imagine

# NB: the shared conftest autouse-opens the gate (_guide_read = True) for every
# test. These tests exercise the gate, so each sets _guide_read = False in-body
# (which runs after all setup fixtures — order-independent). The conftest fixture
# restores the flag after each test.


async def test_gated_tool_blocked_before_guide(monkeypatch):
    _envelope._guide_read = False
    backend_call = MagicMock(return_value={"job_id": "unexpected"})
    monkeypatch.setattr(_envelope._backend, "imagine", backend_call)

    out = await imagine(prompt="a cat", asset_id="cat_01")

    assert out["ok"] is False
    assert out["error"]["code"] == "GUIDE_UNREAD"
    assert "cascade_guide" in out["error"]["remediation"]
    backend_call.assert_not_called()  # the gate ran before the backend


async def test_gate_opens_after_guide(monkeypatch):
    _envelope._guide_read = False
    monkeypatch.setattr(_envelope._backend, "imagine", lambda **kw: {"job_id": "j1"})

    # unread -> blocked
    blocked = await imagine(prompt="x", asset_id="a")
    assert blocked["error"]["code"] == "GUIDE_UNREAD"

    # read the manual
    g = await cascade_guide()
    assert g["ok"] is True

    # now the same call proceeds to the backend
    out = await imagine(prompt="x", asset_id="a")
    assert out["ok"] is True
    assert out["result"] == {"job_id": "j1"}


async def test_exempt_tool_works_guide_unread(monkeypatch):
    _envelope._guide_read = False
    monkeypatch.setattr(_envelope._backend, "health", lambda: {"up": True})
    out = await bridge_health()  # not in the gated set
    assert out["ok"] is True
    assert out["result"] == {"up": True}


async def test_cascade_guide_returns_full_corpus():
    _envelope._guide_read = False
    out = await cascade_guide()
    assert out["ok"] is True
    assert out["result"]["guide"] == load_guide()  # full, not summarized
