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

from scripts.core.paths import (
    ForgeDataPaths,
    find_noncanonical_module_yamls,
    iter_ip_dirs,
    iter_module_yamls,
)


def _make_ir(root):
    """Build a tiny IR tree with canonical modules plus stale decoys."""
    ir = Path(root) / "normalized" / "ir"
    for ip, modules in (("uart", ("uart_tx", "uart_rx")), ("gpio", ("gpio_top",))):
        (ir / ip / "modules").mkdir(parents=True)
        (ir / ip / "hierarchy.yaml").write_text("top: x\n")
        (ir / ip / "summary.yaml").write_text("ip: x\n")
        for m in modules:
            (ir / ip / "modules" / f"{m}.yaml").write_text(f"module_name: {m}\n")
    # stale root-level duplicate (the pre-KF-DQ-001 layout)
    (ir / "uart" / "uart_tx.yaml").write_text("module_name: DECOY\n")
    # non-yaml file inside modules/ and a directory without modules/
    (ir / "uart" / "modules" / "notes.txt").write_text("x")
    (ir / "orphan").mkdir()
    (ir / "orphan" / "orphan.yaml").write_text("module_name: ORPHAN\n")
    return ir


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


def test_iter_module_yamls_returns_only_canonical(tmp_path):
    ir = _make_ir(tmp_path)

    found = [p.relative_to(ir).as_posix() for p in iter_module_yamls(ir)]

    assert found == [
        "gpio/modules/gpio_top.yaml",
        "uart/modules/uart_rx.yaml",
        "uart/modules/uart_tx.yaml",
    ]


def test_iter_module_yamls_single_ip(tmp_path):
    ir = _make_ir(tmp_path)

    found = [p.name for p in iter_module_yamls(ir, "uart")]

    assert found == ["uart_rx.yaml", "uart_tx.yaml"]
    assert list(iter_module_yamls(ir, "missing_ip")) == []


def test_iter_ip_dirs_requires_modules_dir(tmp_path):
    ir = _make_ir(tmp_path)

    assert [p.name for p in iter_ip_dirs(ir)] == ["gpio", "uart"]
    assert list(iter_ip_dirs(tmp_path / "does-not-exist")) == []


def test_find_noncanonical_module_yamls(tmp_path):
    ir = _make_ir(tmp_path)

    stale = [p.relative_to(ir).as_posix() for p in find_noncanonical_module_yamls(ir)]

    assert stale == ["orphan/orphan.yaml", "uart/uart_tx.yaml"]


def test_find_noncanonical_module_yamls_clean_tree(tmp_path):
    ir = _make_ir(tmp_path)
    (ir / "uart" / "uart_tx.yaml").unlink()
    (ir / "orphan" / "orphan.yaml").unlink()

    assert find_noncanonical_module_yamls(ir) == []


def test_forge_data_paths_module_helpers(tmp_path):
    _make_ir(tmp_path)
    data = ForgeDataPaths.from_root(tmp_path)

    assert data.module_dir("uart") == data.normalized_ir / "uart" / "modules"
    assert data.module_yaml("uart", "uart_tx") == (
        data.normalized_ir / "uart" / "modules" / "uart_tx.yaml"
    )
    assert [p.name for p in data.iter_module_yamls("gpio")] == ["gpio_top.yaml"]
