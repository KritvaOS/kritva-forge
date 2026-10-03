# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_data_manifest.py
# Description : KF-DQ-007 tests for the canonical data manifest and publication gate
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Canonical data manifest (KF-DQ-007).

A tiny data repository is generated once with the real pipeline (which
writes and validates ``manifests/data_manifest.json``); each test corrupts a
copy and expects the validator to fail for the intended reason.
"""

import ast
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from scripts.core import data_manifest as M
from scripts.core import stale_artifacts as S
from scripts.core.paths import ForgeDataPaths

ROOT = Path(__file__).resolve().parents[2]

LIB = """\
module lib_buf (input a, output y); assign y = a; endmodule
module lib_inv (input a, output y); assign y = ~a; endmodule
"""


def _ip_rtl(name, n):
    mods = [f"module {name}_m{i} (input a, output y); assign y = a ^ 1'b{i % 2}; endmodule\n" for i in range(n)]
    return "".join(mods) + f"module {name}_top (input a, output y); lib_buf u0 (.a(a), .y(y)); endmodule\n"


def _make_data_root(base):
    root = base / "kritva-forge-data"
    original = root / "raw" / "rtl" / "original"
    (original / "common").mkdir(parents=True)
    (original / "common" / "lib.sv").write_text(LIB)
    for name, n in (("ipa", 5), ("ipb", 4), ("ipc", 3), ("ipd", 2)):
        (original / name).mkdir()
        (original / name / f"{name}.sv").write_text(_ip_rtl(name, n))
        (original / name / "files.f").write_text(f"{name}.sv\n../common/lib.sv\n")
    (original / "ipa" / "tb_ipa.sv").write_text("module tb_ipa; endmodule\n")       # unreferenced RTL
    (original / "ipa" / "README.md").write_text("docs\n")                           # documentation
    (root / "raw" / "rtl" / "curated" / "ipa").mkdir(parents=True)
    (root / "raw" / "rtl" / "curated" / "ipa" / "ipa.sv").write_text(_ip_rtl("ipa", 1))
    for keep in ("splits", "golden"):
        (root / keep).mkdir(parents=True, exist_ok=True)
        (root / keep / ".gitkeep").write_text("")
    (root / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "manifests" / "migration_manifest.json").write_text('{"moves": []}\n')     # historical
    return root


def _run(root):
    from scripts.pipeline.run_pipeline import run_pipeline

    data = ForgeDataPaths.from_root(root)
    run_pipeline(str(data.raw_rtl / "original"), str(data.normalized_ir), data_root=str(root),
                 prompt_root=str(data.prompts), reports_root=str(data.reports),
                 datasets_root=str(data.pipeline_datasets))
    return data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("manifest")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return ForgeDataPaths.from_root(dest)


def _load(tree):
    return json.loads((tree.root / M.MANIFEST_PATH).read_text())


def _store(tree, manifest):
    (tree.root / M.MANIFEST_PATH).write_text(M.dumps(manifest))


def _fails(tree, counter):
    report = M.check(tree.root)
    assert report["status"] == "FAIL", report
    assert report[counter], (counter, report["problems"][:5])
    assert "[FAIL]" in M.format_report(report)
    return report


def _art(manifest, path):
    return next(a for a in manifest["artifacts"] if a["path"] == path)


# -----------------------------------------------------------------------------
# Schema, inventory, identities
# -----------------------------------------------------------------------------

def test_pipeline_writes_single_valid_canonical_manifest(built):
    report = json.loads((built.root / M.REPORT_PATH).read_text())
    assert report["status"] == "PASS", report["problems"]
    assert M.check(built.root)["status"] == "PASS"
    m = _load(built)
    assert m["schema"] == {"name": "kritva-forge-data-manifest", "version": 1}
    assert m["repository"] == {"name": "kritva-forge-data"}
    assert set(m["versions"]) >= {"manifest", "identity", "provenance", "leakage_schema", "split_schema",
                                  "artifact_schema"}
    assert [x["path"] for x in m["manifests"] if x["role"] == "authoritative"] == [M.MANIFEST_PATH]
    roles = {x["path"]: x["role"] for x in m["manifests"]}
    assert roles["manifests/provenance_manifest.json"] == "component"
    assert roles["splits/split_manifest.json"] == "component"
    assert roles["manifests/migration_manifest.json"] == "historical"
    assert set(m["status_vocabulary"]) == set(M.STATUSES)
    assert not re.search(r"(time|date|host|user|pid)\"\s*:", json.dumps(m["versions"]))


def test_inventory_complete_and_classified(built):
    m = _load(built)
    src = {s["path"]: s for s in m["sources"]}
    assert src["raw/rtl/original/ipa/ipa.sv"]["status"] == "canonical"
    assert src["raw/rtl/original/ipa/ipa.sv"]["role"] == "rtl"
    assert src["raw/rtl/original/ipa/files.f"]["role"] == "filelist"
    assert src["raw/rtl/original/ipa/tb_ipa.sv"] ["status"] == "excluded"
    assert src["raw/rtl/original/ipa/tb_ipa.sv"]["role"] == "unreferenced_rtl"
    assert src["raw/rtl/original/ipa/README.md"]["role"] == "documentation_or_other"
    assert src["raw/rtl/curated/ipa/ipa.sv"]["role"] == "curated_rtl"
    assert len(src["raw/rtl/original/common/lib.sv"]["modules"]) == 8

    arts = {a["path"]: a for a in m["artifacts"]}
    assert arts["normalized/ir/ipa/modules/ipa_m0.yaml"]["status"] == "canonical"
    assert arts["generated/prompts/ipa/ipa_m0.generate.txt"]["status"] == "generated"
    assert arts["manifests/migration_manifest.json"]["status"] == "historical"
    assert arts["splits/.gitkeep"]["status"] == "excluded"
    assert arts[M.MANIFEST_PATH]["sha256"] is None                  # excludes its own hash

    # every canonical IR file and every dataset record is represented
    yamls = sorted(p.relative_to(built.root).as_posix() for p in built.normalized_ir.rglob("modules/*.yaml"))
    assert sorted(x["ir"]["path"] for x in m["modules"]) == yamls
    total = sum(len(built.pipeline_datasets.joinpath(f"{s}.jsonl").read_text().splitlines())
                for s in ("train", "validation", "test"))
    assert len(m["records"]) == total == m["counts"]["dataset_records"]
    assert sum(m["splits"]["counts"].values()) == total
    assert re.fullmatch(r"sp1:[0-9a-f]{16}", m["splits"]["split_identity"])


def test_relationships_source_ir_prompt_record_split(built):
    m = _load(built)
    src = {s["path"]: s for s in m["sources"]}
    arts = {a["path"]: a for a in m["artifacts"]}
    recs = {r["record_id"]: r for r in m["records"]}
    for mod in m["modules"]:
        assert src[mod["source"]["path"]]["sha256"] == mod["source"]["sha256"]
        assert mod["module_id"] in src[mod["source"]["path"]]["modules"]
        assert arts[mod["ir"]["path"]]["sha256"] == mod["ir"]["sha256"]
        assert mod["prompt"] in arts and mod["rtl_copy"] in arts
        for rid in mod["records"]:
            assert recs[rid]["module_id"] == mod["module_id"]
            assert recs[rid]["split"] in (mod["split"] if isinstance(mod["split"], list) else [mod["split"]])


def test_manifest_code_has_no_runtime_identity():
    forbidden = {"time", "now", "getmtime", "getctime", "stat", "uuid4", "uuid1", "getpid", "gethostname",
                 "getuser", "random", "id", "hash"}
    tree_ast = ast.parse((ROOT / "scripts/core/data_manifest.py").read_text())
    calls = {
        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(tree_ast) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    assert not calls & forbidden, calls & forbidden


# -----------------------------------------------------------------------------
# Determinism, relocation, integration
# -----------------------------------------------------------------------------

def test_clean_runs_and_relocation_are_byte_identical(built, tmp_path):
    other = _run(_make_data_root(tmp_path / "far" / "away"))
    for rel in (M.MANIFEST_PATH, M.REPORT_PATH, S.INVENTORY_PATH, S.REPORT_PATH):
        assert (built.root / rel).read_bytes() == (other.root / rel).read_bytes(), rel
    moved = tmp_path / "moved" / "kritva-forge-data"
    shutil.copytree(built.root, moved)
    assert M.dumps(M.build(moved)) == (built.root / M.MANIFEST_PATH).read_text()
    assert str(tmp_path) not in (other.root / M.MANIFEST_PATH).read_text()


def test_gates_still_pass(built):
    from scripts.core.provenance import check_provenance
    from scripts.dataset import leakage as L

    assert check_provenance(built.root)["status"] == "PASS"
    assert S.check(built.root)["status"] == "PASS"
    split = json.loads((built.splits / "split_manifest.json").read_text())
    assert L.check_leakage(L.load_split_identities(str(built.root)), split)["status"] == "PASS"


def test_removed_artifacts_disappear_and_historical_stays_explicit(tree):
    (tree.root / "generated/rtl/pipeline/ipa").mkdir(parents=True)
    shutil.copy(tree.root / "raw/rtl/original/ipa/ipa.sv", tree.root / "generated/rtl/pipeline/ipa/ipa.sv")
    with pytest.raises(M.ManifestBlocked):
        M.build(tree.root)                                   # stale data can never be listed
    S.cleanup(tree.root, apply=True)
    (tree.root / "generated/legacy").mkdir(parents=True)
    (tree.root / "generated/legacy/old.txt").write_text("history")
    S.write(tree.root)
    M.write(tree.root)
    m = _load(tree)
    paths = {a["path"]: a for a in m["artifacts"]}
    assert "generated/rtl/pipeline/ipa/ipa.sv" not in paths
    assert paths["generated/legacy/old.txt"]["status"] == "historical"
    assert M.check(tree.root)["status"] == "PASS"


def test_publication_blocked_when_inventory_is_invalid(tree, monkeypatch):
    (tree.prompts / "ipa" / "notes.md").write_text("stray")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")                 # even with the stale override
    with pytest.raises(RuntimeError, match="KF-DQ-007"):
        _run(tree.root)


# -----------------------------------------------------------------------------
# Negative tests (criteria §14)
# -----------------------------------------------------------------------------

def test_missing_manifest(tree):
    (tree.root / M.MANIFEST_PATH).unlink()
    assert _fails(tree, "missing_manifest")


def test_01_missing_source_artifact(tree):
    (tree.root / "raw/rtl/original/ipd/ipd.sv").unlink()
    report = _fails(tree, "missing_artifacts")
    assert report["stale_references"]


def test_02_missing_ir_artifact(tree):
    (tree.root / "normalized/ir/ipb/modules/ipb_m0.yaml").unlink()
    _fails(tree, "missing_artifacts")


def test_03_hash_mismatch(tree):
    m = _load(tree)
    _art(m, "generated/prompts/ipa/ipa_m0.generate.txt")["sha256"] = "0" * 64
    _store(tree, m)
    _fails(tree, "invalid_hashes")


def test_04_duplicate_canonical_path(tree):
    m = _load(tree)
    m["artifacts"].append(dict(_art(m, "generated/prompts/ipa/ipa_m0.generate.txt")))
    _store(tree, m)
    _fails(tree, "duplicate_paths")


def test_05_duplicate_canonical_identity(tree):
    m = _load(tree)
    m["modules"][1]["module_id"] = m["modules"][0]["module_id"]
    _store(tree, m)
    _fails(tree, "duplicate_identities")


def test_06_absolute_path(tree):
    m = _load(tree)
    _art(m, "generated/prompts/ipa/ipa_m0.generate.txt")["path"] = "/home/user/data/generated/prompts/x.txt"
    _store(tree, m)
    report = _fails(tree, "absolute_paths")
    assert report["relocation_status"] == "location-dependent"


def test_07_path_traversal(tree):
    m = _load(tree)
    _art(m, "generated/prompts/ipa/ipa_m0.generate.txt")["path"] = "generated/../raw/rtl/original/ipa/ipa.sv"
    _store(tree, m)
    _fails(tree, "path_traversal")


def test_08_invalid_identity(tree):
    m = _load(tree)
    m["modules"][0]["module_id"] = "mod9:not-a-hash"
    m["records"][0]["record_id"] = "r1:XYZ"
    _store(tree, m)
    assert _fails(tree, "invalid_identities")["invalid_identities"] >= 2


def test_09_broken_provenance_reference(tree):
    m = _load(tree)
    m["modules"][0]["source"]["path"] = "raw/rtl/original/ipa/gone.sv"
    m["modules"][1]["contributing_sources"].append("raw/rtl/original/ipa/missing.svh")
    _store(tree, m)
    assert _fails(tree, "broken_references")["broken_references"] >= 2


def test_10_broken_dataset_reference(tree):
    m = _load(tree)
    m["modules"][0]["records"].append("r1:0000000000000000")
    m["records"][0]["module_id"] = "mod1:0000000000000000"
    _store(tree, m)
    assert _fails(tree, "broken_references")["broken_references"] >= 2


def test_11_unsupported_schema_version(tree):
    m = _load(tree)
    m["schema"]["version"] = 2
    m["versions"]["provenance"] = 99
    _store(tree, m)
    assert _fails(tree, "schema_errors")["schema_errors"] >= 2


def test_12_historical_artifact_marked_canonical(tree):
    (tree.root / "generated/legacy").mkdir(parents=True)
    (tree.root / "generated/legacy/old.txt").write_text("history")
    S.write(tree.root)
    M.write(tree.root)
    m = _load(tree)
    _art(m, "generated/legacy/old.txt")["status"] = "canonical"
    _store(tree, m)
    _fails(tree, "historical_misclassified")


def test_13_unexpected_unmanaged_artifact(tree):
    (tree.prompts / "ipb" / "ipb_m0.v2.txt").write_text("stray prompt")
    with pytest.raises(M.ManifestBlocked):
        M.write(tree.root)
    _fails(tree, "stale_references")
    (tree.prompts / "ipb" / "ipb_m0.v2.txt").unlink()

    m = _load(tree)
    m["artifacts"].append({"path": "generated/prompts/ipb/ghost.txt", "kind": "prompt",
                           "status": "generated", "sha256": "0" * 64})
    _store(tree, m)
    report = _fails(tree, "unexpected")
    assert report["missing_artifacts"]


def test_14_nondeterministic_ordering(tree):
    m = _load(tree)
    m["artifacts"].reverse()
    _store(tree, m)
    report = _fails(tree, "problems")
    assert report["determinism_status"] == "differs"


# -----------------------------------------------------------------------------
# Real data checkout (runs with KRITVA_FORGE_DATA_ROOT)
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_manifest_is_valid():
    report = M.check(DATA_ROOT)
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["determinism_status"] == "reproducible"
