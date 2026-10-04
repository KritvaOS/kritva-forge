# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_corpus.py
# Description : FSM Analysis v1 corpus gate on the real data checkout (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis v1 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT; AC-191 .. AC-196, AC-256)."""

import os

import pytest

from scripts.fsm import validator as V

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
