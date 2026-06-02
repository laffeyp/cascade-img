"""emit/snapshot/clear/flush contract."""

from __future__ import annotations

import json
from pathlib import Path

from cascade_img.vocabulary import (
    VOCAB_VERSION,
    Emitter,
    clear,
    emit,
    flush_to_file,
    snapshot,
    vocabulary,
)


def test_emitter_buffer_evicts_oldest_past_max():
    """The bounded deque drops the oldest signal once max_buffer is exceeded.
    A real silent behavior (drop-oldest) that deserves a witness."""
    e = Emitter(vocabulary(), max_buffer=3)
    for i in range(5):
        e.emit("CASCADE_INIT", package_version=str(i), backend="midjourney_discord")
    buf = e.snapshot()
    assert len(buf) == 3
    # 0 and 1 evicted; 2,3,4 remain in order.
    assert [s.payload["package_version"] for s in buf] == ["2", "3", "4"]


def test_emit_appends_record_with_stable_shape():
    clear()
    rec = emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    assert rec["tag"] == "CASCADE_INIT"
    assert rec["vocab_version"] == VOCAB_VERSION
    assert rec["payload"]["backend"] == "midjourney_discord"
    assert isinstance(rec["ts"], float)
    buf = snapshot()
    assert len(buf) == 1
    assert buf[0]["tag"] == "CASCADE_INIT"


def test_snapshot_is_a_copy():
    clear()
    emit("CASCADE_INIT", package_version="x", backend="x")
    buf1 = snapshot()
    buf1.append({"tag": "FAKE"})  # mutate the copy
    buf2 = snapshot()
    assert len(buf2) == 1  # original untouched


def test_clear_wipes_buffer():
    clear()
    emit("CASCADE_INIT", package_version="x", backend="x")
    emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp", has_guild_id=False)
    assert len(snapshot()) == 2
    clear()
    assert snapshot() == []


def test_flush_to_file_writes_jsonl(tmp_path: Path):
    clear()
    emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp/x", has_guild_id=False)
    out = tmp_path / "capture.jsonl"
    n = flush_to_file(out)
    assert n == 2
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["tag"] == "CASCADE_INIT"
    assert parsed[1]["tag"] == "CONFIG_VALIDATED"
