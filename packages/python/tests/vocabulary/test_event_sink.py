"""Contract for the env-gated persistent event sink (CASCADE_EVENT_LOG).

When ``CASCADE_EVENT_LOG`` names a path, every :meth:`Emitter.emit` appends one
JSON line (``Signal.to_dict()`` shape) to that file, so a durable signal trace
survives the process. The sink is best-effort, mirroring ``bridge._persist``: a
write failure logs one warning and never raises into the emit path. The env var
is read per-emit (not at construction) because the module-level ``_EMITTER`` is
built at import time, before tests or the e2e harness can set the path.
"""

from __future__ import annotations

import json
import logging

from cascade_img.vocabulary import Emitter, vocabulary


def test_each_emit_appends_one_jsonl_line(tmp_path, monkeypatch):
    """One emit -> one parseable JSON line carrying tag, ts, payload."""
    log_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CASCADE_EVENT_LOG", str(log_path))
    e = Emitter(vocabulary())

    e.emit("CASCADE_INIT", package_version="0.1.0", backend="midjourney_discord")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    # Round-trips with the Signal.to_dict() keys the trace checker reads.
    assert "tag" in rec and "ts" in rec and "payload" in rec
    assert rec["tag"] == "CASCADE_INIT"
    assert rec["payload"]["backend"] == "midjourney_discord"


def test_sink_appends_across_emits(tmp_path, monkeypatch):
    """The sink is append-mode: successive emits accumulate, in order."""
    log_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CASCADE_EVENT_LOG", str(log_path))
    e = Emitter(vocabulary())

    e.emit("CASCADE_INIT", package_version="0.1.0", backend="midjourney_discord")
    e.emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp", has_guild_id=False)
    e.emit("DISCORD_CONNECTED", user_id=123)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    tags = [json.loads(line)["tag"] for line in lines]
    assert tags == ["CASCADE_INIT", "CONFIG_VALIDATED", "DISCORD_CONNECTED"]


def test_env_read_per_emit(tmp_path, monkeypatch):
    """Activation is per-emit, not at construction. An Emitter built before the
    env is set still picks the sink up on the next emit once the env appears, and
    an emit fired while the env is unset writes nothing."""
    log_path = tmp_path / "trace.jsonl"
    e = Emitter(vocabulary())

    # No env yet: this emit must not write a file...
    monkeypatch.delenv("CASCADE_EVENT_LOG", raising=False)
    e.emit("CASCADE_INIT", package_version="0.1.0", backend="midjourney_discord")
    assert not log_path.exists()

    # ...but setting the env after construction activates the sink for the next
    # emit (proves env is read per-emit, not cached at Emitter() time).
    monkeypatch.setenv("CASCADE_EVENT_LOG", str(log_path))
    e.emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp", has_guild_id=False)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["tag"] == "CONFIG_VALIDATED"


def test_sink_failure_does_not_raise(tmp_path, monkeypatch, caplog):
    """A sink write failure (here: parent directory absent) is swallowed with one
    warning. Emission still succeeds and the in-process buffer still records the
    signal — the durable sink can never break the live emit path."""
    bad_path = tmp_path / "no-such-dir" / "trace.jsonl"
    monkeypatch.setenv("CASCADE_EVENT_LOG", str(bad_path))
    e = Emitter(vocabulary())

    with caplog.at_level(logging.WARNING, logger="cascade_img.vocabulary"):
        sig = e.emit(
            "CASCADE_INIT", package_version="0.1.0", backend="midjourney_discord"
        )

    assert sig.tag == "CASCADE_INIT"  # emit returned normally
    assert any(s.tag == "CASCADE_INIT" for s in e.snapshot())  # buffer intact
    assert not bad_path.exists()
    assert any("event-sink write failed" in r.message for r in caplog.records)


def test_sink_line_is_full_signal_shape(tmp_path, monkeypatch):
    """The persisted line carries the complete Signal.to_dict() surface the
    trace checker (sprint 014) consumes — not a reduced projection."""
    log_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CASCADE_EVENT_LOG", str(log_path))
    e = Emitter(vocabulary())

    e.emit("IMAGINE_FIRED", asset_id="mountain-icon", job_id="abc", prompt_chars=42, upscale="all")

    rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert set(rec) >= {"tag", "category", "stratum", "t", "ts", "vocab_version", "payload"}
    assert rec["category"] == "job"
    assert rec["payload"]["upscale"] == "all"
