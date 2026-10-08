# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_behavior_corpus.py
# Description : KF-DQ-009 Behavioral Semantics gate and behavioral coverage on the canonical corpus
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT)."""

import os

import pytest

from scripts.behavior import validator as V
from tests.data.corpus_kind import private_corpus_only

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


def test_corpus_behavior_gate_passes():
    report = V.check(DATA_ROOT)
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["documents"] == report["canonical_modules"] > 0


@private_corpus_only
def test_corpus_behavioral_coverage():
    t = V.check(DATA_ROOT)["totals"]
    for key in ("role_sequential", "role_combinational", "clocks_confirmed", "resets_async", "resets_sync",
                "registers", "next_values", "enables", "holds_implicit", "combinational_complete",
                "state_candidates"):
        assert t.get(key, 0) > 0, key
    assert t["processes"] == sum(t.get(f"role_{r}", 0) for r in
                                 ("sequential", "combinational", "latch", "initialization", "generic", "unknown",
                                  "ambiguous"))
