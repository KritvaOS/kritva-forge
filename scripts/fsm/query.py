# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : query.py
# Description : FSM Analysis v1 query API (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Deterministic read-only queries over one FSM Analysis v1 document (AC-223 .. AC-234).

Every result is a fresh, canonically ordered structure derived only from the
document.  Reachability is graph reachability over the extracted transition
graph; predicate feasibility (SAT/SMT) is not analysed and is reported as
``"not_analyzed"`` (AC-045 .. AC-047, AC-233).
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from scripts.fsm import model as F

PREDICATE_FEASIBILITY = "not_analyzed"


def load(data_root, ip: str, module: str) -> dict:
    path = Path(os.path.abspath(data_root)) / F.OUTPUT_DIR / ip / f"{module}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fsms(doc: dict, status: str | None = None, quality: str | None = None) -> list:
    """FSMs of the module (identity order), optionally filtered by status / quality."""
    return [deepcopy(f) for f in sorted(doc["fsms"], key=lambda f: f["id"])
            if (status is None or f["status"] == status) and (quality is None or f["quality"] == quality)]


def fsm(doc: dict, key: str) -> dict:
    """One FSM by ``fsm1:`` identity, state-register signal identity or state-register name.

    Raises ``KeyError`` when nothing or more than one FSM matches.
    """
    hits = [f for f in doc["fsms"] if key in (f["id"], f["register"]["signal"], f["register"]["name"])]
    if len(hits) != 1:
        raise KeyError(f"{key!r} matches {len(hits)} FSMs")
    return deepcopy(hits[0])


def state_register(f: dict) -> dict:
    """The state register, the next-state signal (two-process FSMs) and the coding style."""
    return {"register": deepcopy(f["register"]), "next_signal": deepcopy(f["next_signal"]), "style": f["style"],
            "clock": deepcopy(f["clock"]), "reset": deepcopy(f["reset"]), "enable": deepcopy(f["enable"]),
            "hold": f["hold"]}


def states(f: dict, reachability: str | None = None) -> list:
    """States in encoded-value order, optionally filtered by graph reachability class."""
    return [deepcopy(s) for s in f["states"] if reachability is None or s["reachability"] == reachability]


def state(f: dict, key) -> dict:
    """A state by identity, name or encoded value."""
    hits = [s for s in f["states"] if key in (s["id"], s["name"]) or (isinstance(key, int) and s["value"] == key)]
    if len(hits) != 1:
        raise KeyError(f"{key!r} matches {len(hits)} states")
    return deepcopy(hits[0])


def _sid(f, key):
    if isinstance(key, str) and (key in F.PSEUDO_STATES or F.ID_RE.fullmatch(key)):
        return key
    return state(f, key)["id"]


def _order(t):
    return (t["priority"] is None, t["priority"] if t["priority"] is not None else 0, t["id"])


def transitions(f: dict, kind: str | None = None) -> list:
    """Transitions in priority order (unknown priority last), then identity."""
    return [deepcopy(t) for t in sorted(f["transitions"], key=_order) if kind is None or t["kind"] == kind]


def outgoing(f: dict, key) -> list:
    sid = _sid(f, key)
    return [t for t in transitions(f) if t["source"] == sid]


def incoming(f: dict, key) -> list:
    sid = _sid(f, key)
    return [t for t in transitions(f) if t["target"] == sid]


def guard(f: dict, transition_id: str) -> dict:
    """Structured guard path (outermost first) and the non-canonical rendering of one transition."""
    t = next((t for t in f["transitions"] if t["id"] == transition_id), None)
    if t is None:
        raise KeyError(transition_id)
    return {"transition": t["id"], "path": deepcopy(t["guard"]), "rendered": t["rendered"], "priority": t["priority"]}


def encoding(f: dict) -> dict:
    """Encoding classification with the state values and their constants (provenance)."""
    return {**deepcopy(f["encoding"]),
            "values": [{"state": s["id"], "value": s["value"], "name": s["name"], "constant": deepcopy(s["constant"])}
                       for s in f["states"]]}


def outputs(f: dict, kind: str | None = None) -> list:
    return [deepcopy(o) for o in f["outputs"] if kind is None or o["kind"] == kind]


def actions(f: dict, key=None) -> list:
    """Actions, optionally of one state (identity, name, value or ``*unknown``)."""
    sid = None if key is None else _sid(f, key)
    return [deepcopy(a) for a in f["actions"] if sid is None or a["state"] == sid]


def quality(f: dict) -> dict:
    return {"status": f["status"], "quality": f["quality"], "evidence": deepcopy(f["evidence"]),
            "unknowns": deepcopy(f["unknowns"])}


def reachability(f: dict) -> dict:
    """Graph reachability from the reset state; never a feasibility claim."""
    r = deepcopy(f["reachability"])
    r["predicate_feasibility"] = PREDICATE_FEASIBILITY
    return r


def couplings(doc: dict, fsm_id: str | None = None) -> list:
    return [deepcopy(c) for c in doc["couplings"] if fsm_id is None or fsm_id in (c["from_fsm"], c["to_fsm"])]


def rejected(doc: dict, reason: str | None = None) -> list:
    return [deepcopy(r) for r in doc["rejected"] if reason is None or r["reason"] == reason]
