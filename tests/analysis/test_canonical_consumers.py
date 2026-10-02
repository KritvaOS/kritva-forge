# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_canonical_consumers.py
# Description : Consumers read only canonical <ip>/modules/*.yaml IR
#
# Component   : Kritva Forge
# Module      : tests/analysis
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""KF-DQ-001 regression tests.

Every IR consumer must ignore stale root-level ``<ip>/<module>.yaml`` files
and IP metadata (``hierarchy.yaml`` / ``summary.yaml``).  Each fixture tree
contains one canonical FSM module and one root-level decoy that would be
counted if a consumer walked the whole tree.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

FSM_MODULE = {
    "module_name": "CANON_FSM",
    "signals": [{"name": "state_q"}],
    "summary": {
        "num_fsm_states": 0,
        "num_case_statements": 1,
        "num_always_ff": 1,
        "num_always_comb": 1,
    },
    "fsm": {
        "states": ["IDLE", "RUN", "WAIT", "DONE"],
        "transitions": [],
        "style": "two_process",
        "state_encoding": {"type": "localparam"},
        "quality": {"score": "low", "transition_coverage": 0.0},
    },
}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.fixture
def ir_tree(tmp_path):
    ir = tmp_path / "normalized" / "ir"
    _write(ir / "uart" / "modules" / "canon_fsm.yaml", FSM_MODULE)
    decoy = dict(FSM_MODULE, module_name="DECOY_ROOT")
    _write(ir / "uart" / "canon_fsm.yaml", decoy)
    _write(ir / "uart" / "hierarchy.yaml", {"top": "canon_fsm", "hierarchy": {}})
    _write(ir / "uart" / "summary.yaml", {"ip": "uart", "modules": ["canon_fsm"]})
    return ir


def _run(module, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run(
        [sys.executable, "-m", module, *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


@pytest.mark.parametrize(
    "module, expected",
    [
        ("scripts.analysis.fsm_style_report", "FSMs: 1"),
        ("scripts.analysis.encoding_type_report", "FSMs: 1"),
        ("scripts.analysis.fsm_histogram", "0 states : 1"),
        ("scripts.analysis.fsm_quality_report", "FSMs                 : 1"),
        ("scripts.analysis.fsm_transition_gap", "CANON_FSM"),
        ("scripts.fsm.fsm_gap_analysis", "MODULE: CANON_FSM"),
        ("scripts.debug.fsm_transition_debug", "MODULE: CANON_FSM"),
    ],
)
def test_report_scripts_read_only_canonical_modules(ir_tree, module, expected):
    out = _run(module, ir_tree)

    assert expected in out
    assert "DECOY_ROOT" not in out


def test_fsm_coverage_reads_only_canonical_modules(ir_tree):
    out = _run("scripts.fsm.fsm_coverage", ir_tree)

    assert "FSMs         : 1" in out


def test_fsm_report_collect_modules(ir_tree):
    from scripts.analysis.fsm_report import collect_modules

    modules = collect_modules(str(ir_tree))

    assert [data["module_name"] for _, data in modules] == ["CANON_FSM"]
    assert all("/modules/" in path for path, _ in modules)


def test_dataset_generator_discovers_canonical_ips(ir_tree):
    from scripts.dataset.dataset_generator import discover_ips

    (ir_tree / "common" / "modules").mkdir(parents=True)
    (ir_tree / "no_modules_ip").mkdir()

    ips = [os.path.basename(p) for p in discover_ips(str(ir_tree))]

    assert ips == ["uart"]
