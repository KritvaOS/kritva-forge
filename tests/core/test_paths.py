# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_paths.py
# Description : Tests for the canonical private data repository paths
#
# Component   : Kritva Forge
# Module      : tests/core
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from pathlib import Path

from scripts.core.paths import ForgeDataPaths


def test_data_repository_layout(tmp_path):
    data = ForgeDataPaths.from_root(tmp_path)

    assert data.raw_rtl == Path(tmp_path) / "raw" / "rtl"
    assert data.normalized_ir == Path(tmp_path) / "normalized" / "ir"
    assert data.reports == Path(tmp_path) / "analysis" / "reports"
    assert data.prompts == Path(tmp_path) / "generated" / "prompts"
    assert data.pipeline_datasets == Path(tmp_path) / "datasets" / "pipeline"


def test_ensure_outputs(tmp_path):
    data = ForgeDataPaths.from_root(tmp_path)
    data.ensure_outputs()

    for path in (
        data.normalized_ir,
        data.reports,
        data.prompts,
        data.metadata,
        data.statistics,
        data.pipeline_datasets,
    ):
        assert path.is_dir()
