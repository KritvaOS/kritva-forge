# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_structural_corpus.py
# Description : KF-DQ-010 Structural Analysis gate, provenance and coverage on the canonical corpus
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural Analysis v1 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT; AC-058)."""

import os

import pytest

from scripts.structural import validator as V

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


@pytest.fixture(scope="module")
def report():
    return V.check(DATA_ROOT)


def test_corpus_structural_gate_passes(report):
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["documents"] == report["canonical_modules"] > 0


def test_corpus_provenance_is_complete(report):
    pv = report["provenance"]
    assert pv["objects"] > 0 and pv["valid"] == pv["objects"]
    assert pv["missing"] == 0 and pv["invalid_references"] == 0 and pv["coverage"] == 1.0


def test_corpus_structural_coverage(report):
    t = report["totals"]
    for key in ("ips", "modules", "processes", "signals", "dependencies", "drivers", "loads", "instances",
                "dependencies_data", "dependencies_control", "dependencies_reset", "dependencies_enable",
                "dependencies_hold", "dependencies_clock", "sequential_boundaries", "registers", "predicates",
                "connections", "cones"):
        assert t.get(key, 0) > 0, key
    assert t["dependencies"] == sum(t[f"dependencies_{k}"] for k in
                                    ("data", "control", "reset", "enable", "hold", "clock"))
    for key in ("cycles", "unresolved_instances", "multiple_drivers", "signals_undriven", "signals_unknown"):
        assert key in t                                            # reported even when zero


def test_corpus_leakage_integration(report):
    assert report["leakage"]["status"] == "PASS" and report["leakage"]["structural_dependent_records"] == 0
