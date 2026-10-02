# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_run_pipeline_layout.py
# Description : Tests for pipeline output-root defaults and canonical IR guard
#
# Component   : Kritva Forge
# Module      : tests/pipeline
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from pathlib import Path

import pytest

from scripts.pipeline import run_pipeline as rp


def test_default_output_roots_for_data_repository(tmp_path):
    normalized = tmp_path / "kritva-forge-data" / "normalized" / "ir"

    roots = rp.default_output_roots(normalized)

    data = tmp_path / "kritva-forge-data"
    assert roots == {
        "prompts": str(data / "generated" / "prompts"),
        "reports": str(data / "analysis" / "reports"),
        "datasets": str(data / "datasets" / "pipeline"),
    }


def test_default_output_roots_never_inside_normalized_root(tmp_path):
    normalized = tmp_path / "scratch_ir"

    roots = rp.default_output_roots(normalized)

    for path in roots.values():
        assert not Path(path).is_relative_to(normalized)
        assert Path(path).parent == tmp_path


def test_run_pipeline_rejects_outputs_inside_normalized_root(tmp_path):
    normalized = tmp_path / "ir"

    with pytest.raises(ValueError, match="prompt_root must not be inside"):
        rp.run_pipeline(
            tmp_path / "rtl",
            normalized,
            prompt_root=normalized / "prompts",
        )


def test_check_canonical_layout_accepts_clean_tree(tmp_path):
    (tmp_path / "uart" / "modules").mkdir(parents=True)
    (tmp_path / "uart" / "hierarchy.yaml").write_text("top: uart_top\n")
    (tmp_path / "uart" / "summary.yaml").write_text("ip: uart\n")
    (tmp_path / "uart" / "modules" / "uart_tx.yaml").write_text("module_name: uart_tx\n")

    rp.check_canonical_layout(tmp_path)


def test_check_canonical_layout_rejects_root_level_module_yaml(tmp_path):
    (tmp_path / "uart" / "modules").mkdir(parents=True)
    (tmp_path / "uart" / "modules" / "uart_tx.yaml").write_text("module_name: uart_tx\n")
    (tmp_path / "uart" / "uart_tx.yaml").write_text("module_name: uart_tx\n")

    with pytest.raises(RuntimeError, match="1 non-canonical module YAML"):
        rp.check_canonical_layout(tmp_path)
