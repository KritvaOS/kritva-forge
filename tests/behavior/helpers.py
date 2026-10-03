# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : helpers.py
# Description : Shared helpers for Behavioral Semantics v1 tests (KF-DQ-009)
#
# Component   : Kritva Forge
# Module      : tests/behavior
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Inline RTL -> Semantic IR v2 (real writer path) -> Behavioral Semantics v1."""

import hashlib
import json
from pathlib import Path

from scripts.behavior.analyzer import analyze, semantic_rel
from scripts.behavior.validator import validate_module
from tests.semantic_ir.helpers import extract


def behave_all(src: str, base: Path, ip: str = "fx", extra: dict | None = None) -> dict:
    """{module: (behavioral doc, semantic doc)}; every behavioral doc must validate."""
    sems = extract(src, base, ip=ip, extra=extra)
    root = Path(base) / "kritva-forge-data"
    out = {}
    for name, sem in sems.items():
        rel = semantic_rel(ip, name)
        raw = (root / rel).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        doc = analyze(json.loads(raw), rel, sha)
        problems = validate_module(doc, sem, sha)
        assert problems == [], (name, problems[:5])
        out[name] = (doc, sem)
    return out


def behave(src: str, base: Path, module: str = "fx") -> tuple:
    return behave_all(src, base)[module]


def proc(doc, kind=None, n=0):
    ps = [p for p in doc["processes"] if kind is None or p["kind"] == kind]
    return ps[n]


def reg(doc, name):
    return next(r for r in doc["registers"] if r["name"] == name)


def comb(doc, name):
    return next(c for c in doc["combinational"] if c["name"] == name)


def by_id(doc, section, oid):
    return next(x for x in doc[section] if x["id"] == oid)


def codes(rec):
    return {e["code"] for e in rec["evidence"]}
