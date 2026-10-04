# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : helpers.py
# Description : Inline RTL to Structural Analysis v1 test helpers (KF-DQ-010)
#
# Component   : Kritva Forge
# Module      : tests/structural
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Inline RTL -> Semantic IR v2 -> Behavioral Semantics v1 -> Structural Analysis v1 (real code paths)."""

import json
from pathlib import Path

from scripts.behavior import analyzer as BA
from scripts.behavior import model as BM
from scripts.structural import analyzer as A
from scripts.structural.validator import validate_module
from tests.semantic_ir.helpers import extract


def structure_all(src: str, base: Path, ip: str = "fx", extra: dict | None = None, canonical=None) -> dict:
    """{module: (structural doc, semantic doc, behavioral doc)}; every structural doc must validate.

    ``canonical`` lists the modules that get canonical IR (default: all), so a
    child without canonical IR can be modelled.
    """
    sems = extract(src, base, ip=ip, extra=extra)
    root = Path(base) / "kritva-forge-data"
    for name in sems if canonical is None else canonical:
        p = root / "normalized" / "ir" / ip / "modules" / f"{name}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"name: {name}\n", encoding="utf-8")
    for name in sems:
        out = root / BA.behavior_rel(ip, name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(BM.dumps(BA.build(root, ip, name)), encoding="utf-8")
    inv = A.inventory(root)
    res = {}
    for name in sems:
        sem, srel, ssha, beh, brel, bsha = A.load_inputs(root, ip, name)
        doc = A.analyze(sem, srel, ssha, beh, brel, bsha, inv)
        problems = validate_module(doc, sem, beh, ssha, bsha)
        assert problems == [], (name, problems[:5])
        res[name] = (doc, sem, beh)
    return res


def structure(src: str, base: Path, module: str = "fx", **kw) -> dict:
    return structure_all(src, base, **kw)[module][0]


def sid(doc, name):
    return next(s["signal"] for s in doc["signals"] if s["name"] == name)


def signal(doc, name):
    return next(s for s in doc["signals"] if s["name"] == name)


def names(doc, ids):
    by = {s["signal"]: s["name"] for s in doc["signals"]}
    return sorted(by[i] for i in ids)


def edges(doc, src=None, dst=None, kind=None, context=None):
    """[(source name, target name, kind, context)] of the dependencies matching the filters."""
    by = {s["signal"]: s["name"] for s in doc["signals"]}
    out = []
    for d in doc["dependencies"]:
        e = (by[d["source"]], by[d["target"]], d["kind"], d["context"])
        if (src is None or e[0] == src) and (dst is None or e[1] == dst) and (kind is None or e[2] == kind) \
                and (context is None or e[3] == context):
            out.append(e)
    return sorted(out)


def dep(doc, src, dst, kind):
    by = {s["signal"]: s["name"] for s in doc["signals"]}
    return [d for d in doc["dependencies"] if by[d["source"]] == src and by[d["target"]] == dst and d["kind"] == kind]


def classes(doc, name):
    return {c["class"]: c["status"] for c in signal(doc, name)["classes"]}


def register(doc, name):
    return next(r for r in doc["registers"] if r["name"] == name)


def predicate(doc, kind=None, n=0):
    return [p for p in doc["predicates"] if kind is None or p["kind"] == kind][n]


def drivers(doc, name):
    s = sid(doc, name)
    return [d for d in doc["drivers"] if d["signal"] == s]


def loads(doc, name):
    s = sid(doc, name)
    return [x for x in doc["loads"] if x["signal"] == s]


def stage(src: str, base: Path, ip: str = "fx"):
    """Write a scratch data repository with Semantic IR, behavior and structural documents; return its root."""
    structure_all(src, base, ip=ip)
    root = Path(base) / "kritva-forge-data"
    A.write_all(root)
    return root


def load(root, ip, module):
    return json.loads((Path(root) / A.structural_rel(ip, module)).read_text(encoding="utf-8"))
