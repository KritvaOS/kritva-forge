# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_semantic_ir_corpus.py
# Description : KF-DQ-008 Semantic IR v2 gate and representative coverage on the canonical corpus
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT).

Criteria section 16 prefers the canonical IP corpus over synthetic RTL: every
representative construct must occur in the published Semantic IR of the
canonical modules, and the corpus gate must pass.
"""

import json
import os
from pathlib import Path

import pytest

from scripts.semantic_ir import model as M
from scripts.semantic_ir import validator as V

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


def coverage(root) -> dict:
    """Section 16 construct -> number of occurrences in the canonical Semantic IR corpus."""
    hits = dict.fromkeys(("simple combinational logic", "sequential logic", "parameterized modules", "vectors",
                          "signed/unsigned signals", "continuous assignments", "blocking assignments",
                          "nonblocking assignments", "conditional logic", "case logic", "module instances",
                          "concatenation", "indexing", "part-selects"), 0)
    for path in sorted((Path(root) / M.OUTPUT_DIR).rglob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        kinds = [a["kind"] for a in d["assignments"]]
        hits["continuous assignments"] += kinds.count("continuous")
        hits["blocking assignments"] += kinds.count("blocking")
        hits["nonblocking assignments"] += kinds.count("nonblocking")
        hits["sequential logic"] += sum(1 for p in d["processes"]
                                        if p["kind"] == "always_ff" or any(e["edge"] in ("posedge", "negedge")
                                                                           for e in p["events"]))
        hits["simple combinational logic"] += sum(1 for p in d["processes"]
                                                  if p["kind"] == "always_comb" or p["sensitivity"] == "implicit")
        hits["parameterized modules"] += bool(d["parameters"])
        hits["vectors"] += sum(1 for s in d["ports"] + d["signals"] if (s.get("width") or 1) > 1)
        hits["signed/unsigned signals"] += sum(1 for s in d["ports"] + d["signals"] if s.get("signed"))
        hits["conditional logic"] += len(d["conditions"])
        hits["case logic"] += len(d["cases"])
        hits["module instances"] += len(d["instances"])
        stack = [d["assignments"]]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                op = x.get("op")
                hits["concatenation"] += op in ("concat", "replicate")
                hits["indexing"] += op == "index"
                hits["part-selects"] += op == "part_select"
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return hits


def test_corpus_semantic_gate_passes():
    report = V.check(DATA_ROOT)
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["documents"] == report["canonical_modules"] > 0
    assert report["totals"].get("unresolved_references", 0) == 0


def test_representative_constructs_occur_in_corpus():
    hits = coverage(DATA_ROOT)
    missing = sorted(k for k, v in hits.items() if not v)
    assert not missing, missing
