# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_multitask_corpus.py
# Description : KF-DQ-013 multi-task dataset on a real data checkout (gate + private corpus numbers)
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Multi-task dataset on ``KRITVA_FORGE_DATA_ROOT`` (KF-DQ-013 AC-056, AC-084)."""

import json
import os
from pathlib import Path

import pytest

from scripts.multitask import registry as G
from tests.data.corpus_kind import private_corpus_only

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
pytestmark = pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")


def _report():
    return json.loads((Path(DATA_ROOT) / G.REPORT_PATH).read_text())


def test_corpus_multitask_report_pass():
    rep = _report()
    assert rep["status"] == "PASS", rep["problems"][:5]
    assert rep["authorization"]["kf_dq_013_entry"] == "open"
    modules = len(list((Path(DATA_ROOT) / "normalized/semantic_ir/v2").rglob("*.json")))
    for t in G.TASKS:
        assert rep["tasks"][t["id"]]["records"] == (modules if t["status"] == G.POPULATED else 0)


@private_corpus_only
def test_corpus_multitask_counts():
    """AC-056: 6 tasks x 350 modules; module split inherited from 248 / 51 / 51."""
    rep = _report()
    assert rep["counts"]["records"] == 2100
    assert rep["counts"]["splits"] == {"train": 1488, "validation": 306, "test": 306}
    f = rep["fsm_extraction"]
    assert f["positive"] + f["negative"] == 350 and f["fsms"] == 119
