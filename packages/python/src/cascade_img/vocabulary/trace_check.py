"""Offline trace checker for the cascade-img signal vocabulary.

Executes the catalog's declared sequence and timing rules
(``state_transitions.rules`` and ``temporal_invariants.invariants``) against a
recorded event trace — a list of ``Signal.to_dict()`` shapes, as produced by
``snapshot()`` or read back from the ``CASCADE_EVENT_LOG`` JSONL sink (012). The
rules became mechanically checkable in sprint 013, which added the structured
fields this module reads (``payload_match``, ``to_tags``, ``applies_when``,
``severity``, ``forbidden_tags_after``, ``exempt_tags``, ``or_exit_via``);
nothing here interprets a prose ``note``.

The checker is a *consumer* of the stream, never a speaker: it emits no signals
(that would be a feedback loop), imports nothing from the package beyond loading
the catalog JSON, does no env reads, and :func:`check_trace` is pure and
deterministic. stdlib only — it imports without discord / flask / mcp installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any


@dataclass
class Violation:
    """One rule breach found in a trace.

    ``severity`` is ``"error"`` (an ordering / terminal / pairing breach) or
    ``"warning"`` (a timing-window overrun — a slow run, not a broken contract;
    warnings never fail a gate). ``event`` is the offending record; ``prior`` is
    the related earlier record (the unresolved open, the violated terminal, the
    window start) when one applies. ``slice_key`` is the correlation key of the
    slice the breach was found in — a ``job_id``, ``job_id:slot``, ``tool``, or
    ``None`` for a globally-scoped rule.
    """

    rule: str
    severity: str
    message: str
    event: dict[str, Any] | None = None
    prior: dict[str, Any] | None = None
    slice_key: str | None = None


def load_catalog() -> dict[str, Any]:
    """Load the packaged vocabulary catalog as a raw dict (for ``main`` and
    tests). :func:`check_trace` itself takes the dict as an argument and does no
    I/O. Mirrors ``_runtime.Vocabulary.from_package_data`` so this stays the only
    I/O surface and the module import remains side-effect-free."""
    ref = files("cascade_img.vocabulary.versions") / "0.1.json"
    with ref.open("r", encoding="utf-8") as f:
        return json.load(f)


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") or {}


def _corr_key(payload_match: str | None, event: dict[str, Any]) -> str | None:
    """The slice key for ``event`` under a rule's ``payload_match``. A falsy
    ``payload_match`` means the rule is globally scoped (one slice, key None)."""
    if not payload_match:
        return None
    p = _payload(event)
    if payload_match == "job_id+slot":
        return f"{p.get('job_id')}:{p.get('slot')}"
    val = p.get(payload_match)
    return None if val is None else str(val)


def _upscale_mode(event: dict[str, Any]) -> str:
    """Map an IMAGINE_FIRED's ``upscale`` payload to a window ``applies_when``
    mode: null / absent / "none" -> none, "all" -> all, "1"-"4" -> single."""
    up = _payload(event).get("upscale")
    if up in (None, "", "none"):
        return "none"
    if up == "all":
        return "all"
    return "single"


def _ts(event: dict[str, Any]) -> float:
    return float(event.get("ts") or 0.0)


def _check_pairing_ordering(events: list[dict[str, Any]], rule: dict[str, Any]) -> list[Violation]:
    """A ``to_tags_allowed`` tag with no prior ``from_tag`` in its slice = error."""
    from_tag = rule["from_tag"]
    to_tags = set(rule.get("to_tags_allowed") or [])
    pm = rule.get("payload_match")
    out: list[Violation] = []
    seen_from: dict[str | None, bool] = {}
    for ev in events:
        tag = ev.get("tag")
        key = _corr_key(pm, ev)
        if tag == from_tag:
            seen_from[key] = True
        elif tag in to_tags and not seen_from.get(key):
            out.append(
                Violation(
                    rule="pairing_ordering",
                    severity="error",
                    message=f"{tag} occurred with no prior {from_tag} in its slice",
                    event=ev,
                    slice_key=key,
                )
            )
    return out


def _check_forced_next(events: list[dict[str, Any]], rule: dict[str, Any]) -> list[Violation]:
    """After ``from_tag``, one of ``to_tags_allowed`` or ``or_exit_via`` must
    eventually appear in the same slice, else error."""
    from_tag = rule["from_tag"]
    resolves = set(rule.get("to_tags_allowed") or []) | set(rule.get("or_exit_via") or [])
    pm = rule.get("payload_match")
    out: list[Violation] = []
    for i, ev in enumerate(events):
        if ev.get("tag") != from_tag:
            continue
        key = _corr_key(pm, ev)
        if not any(
            _corr_key(pm, nxt) == key and nxt.get("tag") in resolves for nxt in events[i + 1 :]
        ):
            out.append(
                Violation(
                    rule="forced_next",
                    severity="error",
                    message=f"{from_tag} not followed by any of {sorted(resolves)} in its slice",
                    event=ev,
                    slice_key=key,
                )
            )
    return out


def _check_terminal(events: list[dict[str, Any]], rule: dict[str, Any]) -> list[Violation]:
    """After a terminal tag in a slice, any ``forbidden_tags_after`` tag = error.
    ``exempt_tags`` (and any tag not listed as forbidden) pass — they are the
    post-terminal action / derived / eviction / collision events that legitimately
    carry a completed job's id."""
    terminals = set(rule.get("tags") or [])
    forbidden = set(rule.get("forbidden_tags_after") or [])
    pm = rule.get("payload_match")
    out: list[Violation] = []
    terminated_at: dict[str | None, dict[str, Any]] = {}
    for ev in events:
        key = _corr_key(pm, ev)
        tag = ev.get("tag")
        if key in terminated_at and tag in forbidden:
            prior = terminated_at[key]
            out.append(
                Violation(
                    rule="terminal",
                    severity="error",
                    message=f"{tag} carries {pm} after terminal {prior.get('tag')} in the same slice",
                    event=ev,
                    prior=prior,
                    slice_key=key,
                )
            )
        if tag in terminals:
            terminated_at[key] = ev
    return out


def _check_windows(events: list[dict[str, Any]], windows: list[dict[str, Any]]) -> list[Violation]:
    """For each ``from_tag``, select the window whose ``applies_when.upscale``
    matches the from-event's mode, pair it to the ``to_tag`` for the same job_id,
    and flag an over-budget delta at the window's ``severity`` (warning)."""
    by_mode = {(w.get("applies_when") or {}).get("upscale"): w for w in windows}
    from_tag = windows[0].get("from_tag")
    to_tag = windows[0].get("to_tag")
    out: list[Violation] = []
    for i, ev in enumerate(events):
        if ev.get("tag") != from_tag:
            continue
        w = by_mode.get(_upscale_mode(ev))
        if w is None:
            continue
        job_id = _payload(ev).get("job_id")
        to_ev = next(
            (
                nxt
                for nxt in events[i + 1 :]
                if nxt.get("tag") == to_tag and _payload(nxt).get("job_id") == job_id
            ),
            None,
        )
        if to_ev is None:
            continue  # no completion to time against — not a window concern
        budget = w.get("duration_seconds")
        delta = _ts(to_ev) - _ts(ev)
        if budget is not None and delta > budget:
            mode = (w.get("applies_when") or {}).get("upscale")
            out.append(
                Violation(
                    rule="window",
                    severity=w.get("severity", "warning"),
                    message=f"{from_tag}->{to_tag} took {delta:.1f}s, over the {budget}s '{mode}' band",
                    event=to_ev,
                    prior=ev,
                    slice_key=str(job_id) if job_id is not None else None,
                )
            )
    return out


def _check_pairing(events: list[dict[str, Any]], inv: dict[str, Any]) -> list[Violation]:
    """Every ``from_tag`` must resolve to one of ``to_tags`` in its slice before
    the stream ends, else error (an unresolved open)."""
    from_tag = inv["from_tag"]
    to_tags = set(inv.get("to_tags") or [])
    pm = inv.get("payload_match")
    out: list[Violation] = []
    pending: dict[str | None, list[dict[str, Any]]] = {}
    for ev in events:
        tag = ev.get("tag")
        key = _corr_key(pm, ev)
        if tag == from_tag:
            pending.setdefault(key, []).append(ev)
        elif tag in to_tags:
            q = pending.get(key)
            if q:
                q.pop(0)
    for key, q in pending.items():
        for ev in q:
            out.append(
                Violation(
                    rule="pairing",
                    severity="error",
                    message=f"{from_tag} never resolved to one of {sorted(to_tags)} in its slice",
                    event=ev,
                    slice_key=key,
                )
            )
    return out


def _check_forbidden_after(events: list[dict[str, Any]], inv: dict[str, Any]) -> list[Violation]:
    """After ``from_tag`` in a slice, any ``to_tags`` tag = error."""
    from_tag = inv["from_tag"]
    to_tags = set(inv.get("to_tags") or [])
    pm = inv.get("payload_match")
    out: list[Violation] = []
    seen_from: dict[str | None, dict[str, Any]] = {}
    for ev in events:
        key = _corr_key(pm, ev)
        tag = ev.get("tag")
        if key in seen_from and tag in to_tags:
            out.append(
                Violation(
                    rule="forbidden_after",
                    severity="error",
                    message=f"{tag} occurred after {from_tag} for the same {pm}",
                    event=ev,
                    prior=seen_from[key],
                    slice_key=key,
                )
            )
        if tag == from_tag:
            seen_from[key] = ev
    return out


def check_trace(events: list[dict[str, Any]], vocab: dict[str, Any]) -> list[Violation]:
    """Return every sequence/timing rule breach in ``events``, driven entirely by
    the catalog's structured fields. ``events`` are ``Signal.to_dict()`` shapes;
    ``vocab`` is the catalog dict (see :func:`load_catalog`). Pure: no I/O, no env
    reads, deterministic. Errors are real breaches; window warnings are slow runs
    that must not fail a gate.
    """
    out: list[Violation] = []
    for rule in (vocab.get("state_transitions") or {}).get("rules") or []:
        kind = rule.get("kind")
        if kind == "pairing_ordering":
            out += _check_pairing_ordering(events, rule)
        elif kind == "forced_next":
            out += _check_forced_next(events, rule)
        elif kind == "terminal":
            out += _check_terminal(events, rule)
    invariants = (vocab.get("temporal_invariants") or {}).get("invariants") or []
    windows = [i for i in invariants if i.get("kind") == "window"]
    if windows:
        out += _check_windows(events, windows)
    for inv in invariants:
        kind = inv.get("kind")
        if kind == "pairing":
            out += _check_pairing(events, inv)
        elif kind == "forbidden_after":
            out += _check_forbidden_after(events, inv)
    return out
