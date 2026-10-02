# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_canonical_layout.py
# Description : KF-DQ-001 invariants for the private data repository IR layout
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Canonical normalized-IR layout invariants (KF-DQ-001).

Runs only when ``KRITVA_FORGE_DATA_ROOT`` points at a ``kritva-forge-data``
checkout (``make test-data`` sets it).  Public CI has no private data and
skips this module.

Expected baseline counts can be overridden with
``KRITVA_FORGE_EXPECTED_IPS`` / ``KRITVA_FORGE_EXPECTED_MODULES`` when the
canonical IP membership is intentionally changed.
"""

import os
from pathlib import Path

import pytest
import yaml

from scripts.core.paths import (
    IP_METADATA_FILES,
    ForgeDataPaths,
    find_noncanonical_module_yamls,
    iter_ip_dirs,
    iter_module_yamls,
)

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")

pytestmark = pytest.mark.skipif(
    not DATA_ROOT,
    reason="KRITVA_FORGE_DATA_ROOT not set; private data repository unavailable",
)

EXPECTED_IPS = int(os.environ.get("KRITVA_FORGE_EXPECTED_IPS", "19"))
EXPECTED_MODULES = int(os.environ.get("KRITVA_FORGE_EXPECTED_MODULES", "350"))


@pytest.fixture(scope="module")
def ir():
    root = ForgeDataPaths.from_root(DATA_ROOT).normalized_ir
    assert root.is_dir(), f"normalized IR root missing: {root}"
    return root


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def test_canonical_ip_count(ir):
    ips = [p.name for p in iter_ip_dirs(ir)]
    assert len(ips) == EXPECTED_IPS, ips


def test_every_ip_directory_is_canonical(ir):
    non_ip = sorted(
        p.name
        for p in ir.iterdir()
        if p.is_dir() and not (p / "modules").is_dir()
    )
    assert non_ip == []


def test_canonical_module_count(ir):
    assert len(list(iter_module_yamls(ir))) == EXPECTED_MODULES


def test_no_noncanonical_module_yaml(ir):
    stale = [str(p.relative_to(ir)) for p in find_noncanonical_module_yamls(ir)]
    assert stale == [], f"{len(stale)} stale root-level YAML(s): {stale[:10]}"


def test_ip_metadata_present(ir):
    for ip_dir in iter_ip_dirs(ir):
        for name in IP_METADATA_FILES:
            assert (ip_dir / name).is_file(), f"{ip_dir.name}/{name} missing"


def test_module_yaml_names_match_module(ir):
    mismatched = []
    for path in iter_module_yamls(ir):
        module = _load(path).get("module")
        if module != path.stem:
            mismatched.append(f"{path.relative_to(ir)} -> {module!r}")
    assert mismatched == []


def test_summary_matches_modules_dir(ir):
    for ip_dir in iter_ip_dirs(ir):
        summary = _load(ip_dir / "summary.yaml")
        stems = sorted(p.stem for p in iter_module_yamls(ir, ip_dir.name))

        assert sorted(summary.get("modules", [])) == stems, ip_dir.name
        assert summary.get("num_yaml_files") == len(stems), ip_dir.name


def test_hierarchy_parents_are_canonical_modules(ir):
    unresolved = []
    for ip_dir in iter_ip_dirs(ir):
        hierarchy = _load(ip_dir / "hierarchy.yaml").get("hierarchy", {}) or {}
        stems = {p.stem for p in iter_module_yamls(ir, ip_dir.name)}
        unresolved.extend(f"{ip_dir.name}:{m}" for m in hierarchy if m not in stems)

    assert unresolved == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Known data gap recorded at KF-DQ-001 review: some instantiated "
        "library modules (e.g. gmac -> generic_register) have no module IR "
        "in their IP. Not a layout issue; tracked as follow-up."
    ),
)
def test_hierarchy_children_resolve_to_canonical_modules(ir):
    unresolved = []
    for ip_dir in iter_ip_dirs(ir):
        hierarchy = _load(ip_dir / "hierarchy.yaml").get("hierarchy", {}) or {}
        stems = {p.stem for p in iter_module_yamls(ir, ip_dir.name)}

        for parent, children in hierarchy.items():
            for child in children or []:
                if child.get("module") not in stems:
                    unresolved.append(f"{ip_dir.name}:{parent}->{child.get('module')}")

    assert unresolved == []


def test_no_module_yaml_outside_canonical_locations(ir):
    """Only <ip>/{hierarchy,summary}.yaml and <ip>/modules/*.yaml are allowed."""
    allowed = {Path(p) for p in iter_module_yamls(ir)}
    for ip_dir in iter_ip_dirs(ir):
        allowed.update(ip_dir / name for name in IP_METADATA_FILES)

    extra = sorted(str(p.relative_to(ir)) for p in ir.rglob("*.yaml") if p not in allowed)
    assert extra == []
