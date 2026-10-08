# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_corpus.py
# Description : FSM Analysis v2 corpus gate on the real data checkout (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis v2 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT; AC-191 .. AC-196, AC-256).

KF-DQ-011.1 (Appendix C2): the expected output classification of the corpus
is asserted here from the persisted FSM and Structural Analysis documents,
independently of the analyzer's own classification rule.
"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from scripts.fsm import model as F
from scripts.fsm import validator as V
from scripts.structural import model as TM
from tests.data.corpus_kind import private_corpus_only

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


@pytest.fixture(scope="module")
def report():
    return V.check(DATA_ROOT)


def test_corpus_fsm_gate_passes(report):
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["documents"] == report["canonical_modules"] > 0          # zero-FSM modules included


def test_corpus_provenance_is_complete(report):
    pv = report["provenance"]
    assert pv["objects"] > 0 and pv["valid"] == pv["objects"]
    assert pv["missing"] == 0 and pv["invalid_references"] == 0 and pv["coverage"] == 1.0


def test_corpus_fsm_scale_is_sane(report):
    """AC-018: confirmed FSMs on the order of tens, not one per register."""
    t = report["totals"]
    assert 10 <= t["confirmed"] < 100
    assert t["fsms"] == t["confirmed"] + t["candidate"] + t["ambiguous"] + t["unsupported"]
    assert t["rejected"] > t["fsms"]                                       # most interesting registers are not FSMs
    for key in ("states", "transitions", "outputs", "quality_high", "rejected_arithmetic_feedback",
                "rejected_no_state_predicate", "reset_state_known"):
        assert t.get(key, 0) > 0, key


def test_corpus_leakage_integration(report):
    lk = report["leakage"]
    assert lk["status"] == "PASS" and lk["fsm_dependent_records"] == 0
    assert all(c["classification"] == "soft" for c in lk["cross_split_fingerprints"])
    assert lk["structural_findings"]["classification"] == "soft"


# ----------------------------------------------------------------------------- KF-DQ-011.1 (C2)
# Corpus baseline of KF-DQ-011 (data 9712407): only the output classification may change.
EXPECTED = {"fsms": 123, "states": 592, "transitions": 2102, "actions": 2715, "couplings": 48, "outputs": 445}
EXPECTED_KINDS = {"moore": 333, "mealy": 92, "ambiguous": 20}


@pytest.fixture(scope="module")
def outputs():
    root = Path(DATA_ROOT)
    rows, counts = [], Counter()
    for path in sorted((root / F.OUTPUT_DIR).rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        st = json.loads((root / TM.OUTPUT_DIR / path.parent.name / path.name).read_text(encoding="utf-8"))
        recs = {}
        for r in st["registers"]:
            recs.setdefault(r["signal"], []).append(r["boundary"])
        counts["couplings"] += len(doc["couplings"])
        for f in doc["fsms"]:
            counts["fsms"] += 1
            for k in ("states", "transitions", "actions", "outputs"):
                counts[k] += len(f[k])
            for o in f["outputs"]:
                b = recs.get(o["signal"], [])
                rows.append((o, bool(b) and all(x == "sequential" for x in b), o["signal"] == f["register"]["signal"]))
    return rows, counts


def test_corpus_v1_tree_is_gone():
    assert not (Path(DATA_ROOT) / "normalized" / "fsm" / "v1").exists()


@private_corpus_only
def test_corpus_fsm_counts_unchanged(outputs):
    _, counts = outputs
    assert dict(counts) == EXPECTED


@private_corpus_only
def test_corpus_output_classification(outputs):
    rows, _ = outputs
    assert Counter(o["kind"] for o, _, _ in rows) == EXPECTED_KINDS
    registered = [(o, state) for o, reg, state in rows if reg]
    assert len(registered) == 313 and sum(1 for _, s in registered if s) == 24
    assert all(o["registered"] is reg for o, reg, _ in rows)
    assert all(o["kind"] == "moore" and o["other_sources"] == [] for o, _ in registered)
    assert all(not o["registered"] and o["sampled_sources"] == [] for o, reg, _ in rows if not reg)
    comb = Counter(o["kind"] for o, reg, _ in rows if not reg)
    assert comb == {"mealy": 92, "moore": 20, "ambiguous": 20}
