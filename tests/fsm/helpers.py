# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : helpers.py
# Description : Inline RTL to FSM Analysis v2 test helpers (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/fsm
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Inline RTL -> Semantic IR v2 -> Behavioral Semantics v1 -> Structural Analysis v1 -> FSM Analysis v2."""

from pathlib import Path

from scripts.fsm import analyzer as FA
from scripts.fsm import model as F
from scripts.fsm.validator import validate_module
from scripts.structural import analyzer as SA
from scripts.structural import model as SM
from tests.structural.helpers import structure_all


def fsm_all(src: str, base: Path, ip: str = "fx", extra: dict | None = None, validate: bool = True) -> dict:
    """{module: (fsm doc, inputs tuple)}; every FSM document must validate."""
    res = structure_all(src, base, ip=ip, extra=extra)
    root = Path(base) / "kritva-forge-data"
    for name, (doc, _, _) in res.items():
        out = root / SA.structural_rel(ip, name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(SM.dumps(doc), encoding="utf-8")
    out = {}
    for name in res:
        inputs = FA.load_inputs(root, ip, name)
        doc = FA.analyze(*inputs)
        if validate:
            problems = validate_module(doc, *inputs)
            assert problems == [], (name, problems[:5])
        out[name] = (doc, inputs)
    return out


def stage(src: str, base: Path, ip: str = "fx") -> Path:
    """Scratch data repository with Semantic IR, behavior, structural and FSM documents; return its root."""
    fsm_all(src, base, ip=ip)
    root = Path(base) / "kritva-forge-data"
    FA.write_all(root)
    return root


def fsm(src: str, base: Path, module: str = "fx", **kw) -> dict:
    return fsm_all(src, base, **kw)[module][0]


def only(doc):
    assert len(doc["fsms"]) == 1, [f["register"]["name"] for f in doc["fsms"]]
    return doc["fsms"][0]


def by_reg(doc, name):
    return next(f for f in doc["fsms"] if f["register"]["name"] == name)


def state_names(f):
    return sorted((s["value"], s["name"]) for s in f["states"])


def edges(f, kinds=None):
    """Sorted (source value|pseudo, target value|pseudo, kind) of the transitions."""
    val = {s["id"]: s["value"] for s in f["states"]}
    out = []
    for t in f["transitions"]:
        if kinds is None or t["kind"] in kinds:
            out.append((str(val.get(t["source"], t["source"])), str(val.get(t["target"], t["target"])), t["kind"]))
    return sorted(out)


def rejected(doc):
    return sorted((r["name"], r["reason"]) for r in doc["rejected"])


__all__ = ["fsm_all", "stage", "fsm", "only", "by_reg", "state_names", "edges", "rejected", "F"]
