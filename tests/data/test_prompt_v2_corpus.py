# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_corpus.py
# Description : Prompt v2 corpus gate on the real data checkout (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 on the real data checkout (runs with KRITVA_FORGE_DATA_ROOT; AC-801 .. AC-844).

Every canonical module has exactly one default prompt and one sidecar; the
gate, the persisted corpus report, the compatibility contract and the
cross-split classification all pass and agree with a recomputation.
"""

import json
import os
from pathlib import Path

import pytest

from scripts.core import compat as C
from scripts.prompt_v2 import classify as PC
from scripts.prompt_v2 import model as P
from scripts.prompt_v2 import render as R
from scripts.prompt_v2 import validator as V

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


@pytest.fixture(scope="module")
def report():
    return V.check(DATA_ROOT, with_classification=True)


def test_corpus_prompt_v2_gate_passes(report):
    """AC-801 .. AC-814."""
    assert report["status"] == "PASS", report["problems"][:10]
    n = len(R.canonical_modules(Path(DATA_ROOT)))
    assert report["canonical_modules"] == report["prompts"] == report["sidecars"] == n > 0
    assert report["provenance"]["valid"] == n and report["provenance"]["coverage"] == 1.0
    assert report["leakage"]["failures"] == 0 and report["leakage"]["records"] == n


def test_corpus_size_and_leakage_within_frozen_limits(report):
    """AC-813, AC-815, AC-816, AC-819."""
    s, lk = report["sizes"], report["leakage"]
    assert s["p100"] <= P.BUDGET_BYTES and s["truncated"] < report["canonical_modules"] * 0.05
    assert lk["overlap"]["p100"] <= lk["thresholds"]["overlap_max"]
    assert lk["longest_run"]["p100"] <= lk["thresholds"]["longest_run_max"]


def test_persisted_reports_agree_with_recomputation(report):
    """AC-843, AC-844, AC-820: corpus and classification reports are current."""
    root = Path(DATA_ROOT)
    saved = json.loads((root / P.REPORT_PATH).read_text(encoding="utf-8"))
    assert saved["status"] == "PASS" and saved["corpus_sha256"] == report["corpus_sha256"]
    cls = json.loads((root / P.CLASSIFICATION_REPORT_PATH).read_text(encoding="utf-8"))
    assert cls == PC.build(root) and PC.validate(cls) == [] and cls["splits_changed"] is False
    assert V.reports_check(root) == []


def test_corpus_compatibility(report):
    """AC-811, AC-823."""
    rep = C.check(DATA_ROOT)
    assert rep["status"] == "PASS", rep["problems"][:10]
    assert rep["sidecars_checked"] == report["sidecars"]


def test_corpus_has_no_unmanaged_prompt_files():
    """AC-805, AC-822, AC-826."""
    base = Path(DATA_ROOT) / P.OUTPUT_DIR
    canon = sorted(R.canonical_modules(Path(DATA_ROOT)))
    files = sorted(p.relative_to(Path(DATA_ROOT)).as_posix() for p in base.rglob("*") if p.is_file())
    assert files == sorted([P.prompt_rel(i, m) for i, m in canon] + [P.sidecar_rel(i, m) for i, m in canon])
