# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_stale_artifacts.py
# Description : KF-DQ-006 tests for the stale generated artifact gate and safe cleanup
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Stale generated artifacts (KF-DQ-006).

A tiny data repository is generated once with the real pipeline; every test
works on a copy, introduces one stale condition and checks the gate result,
the classification and the remediation.
"""

import ast
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

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
    for keep in ("splits", "golden", "generated/metadata"):
        (root / keep).mkdir(parents=True, exist_ok=True)
        (root / keep / ".gitkeep").write_text("")
    return root


def _run(root):
    from scripts.pipeline.run_pipeline import run_pipeline

    data = ForgeDataPaths.from_root(root)
    run_pipeline(str(data.raw_rtl / "original"), str(data.normalized_ir), data_root=str(root),
                 prompt_root=str(data.prompts), reports_root=str(data.reports),
                 datasets_root=str(data.pipeline_datasets))
    return data


def _tree_hash(root, sub):
    h = hashlib.sha256()
    base = Path(root) / sub
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(base).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("stale")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return ForgeDataPaths.from_root(dest)


def _entry(report_or_result, path):
    entries = report_or_result["entries"]
    return next(e for e in entries if e["path"] == path)


def _plan(report, path):
    return next(p for p in report["remediation_plan"] if p["path"] == path)


def _rewrite_jsonl(path, fn):
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    lines = fn(lines)
    path.write_text("".join(json.dumps(r) + "\n" for r in lines))


# -----------------------------------------------------------------------------
# Unit
# -----------------------------------------------------------------------------

def test_clean_pipeline_output_is_current(built):
    report = S.check(built.root)
    assert report["status"] == "PASS", report["problems"]
    assert report["stale"] == report["orphan"] == report["unmanaged"] == 0
    assert report["current"] == report["artifact_records_checked"]
    assert report["missing_expected"] == 0 and report["inventory_status"] == "consistent"
    assert report["dataset_records_checked"] > 0 and report["split_records_checked"] > 0
    stored = json.loads((built.root / S.REPORT_PATH).read_text())
    assert stored == report


def test_expected_inventory_comes_from_canonical_inputs(tree):
    """A missing expected output is reported; existing outputs do not define what is expected."""
    (tree.prompts / "ipb" / "ipb_m1.generate.txt").unlink()
    result = S.classify(tree.root)
    assert "generated/prompts/ipb/ipb_m1.generate.txt" in result["missing"]
    report = S.check(tree.root)
    assert report["status"] == "FAIL"
    assert _plan(report, "generated/prompts/ipb/ipb_m1.generate.txt")["action"] == "REGENERATE"


def test_classification_states_and_inventory_fields(tree):
    (tree.root / "generated/legacy/old").mkdir(parents=True)
    (tree.root / "generated/legacy/old/prompt.txt").write_text("x")
    (tree.root / "datasets/source").mkdir(parents=True)
    (tree.root / "datasets/source/ext.jsonl").write_text("{}\n")
    result = S.classify(tree.root)
    assert _entry(result, "generated/legacy/old/prompt.txt")["state"] == "HISTORICAL"
    assert _entry(result, "datasets/source/ext.jsonl")["state"] == "HISTORICAL"
    assert _entry(result, "splits/.gitkeep")["state"] == "CURRENT"
    prompt = _entry(result, "generated/prompts/ipa/ipa_m0.generate.txt")
    assert prompt["state"] == "CURRENT" and prompt["kind"] == "prompt"
    assert prompt["module_id"].startswith("mod1:") and len(prompt["source_sha256"]) == 64
    assert all(e["state"] in S.STATES for e in result["entries"])
    assert len({e["path"] for e in result["entries"]}) == len(result["entries"])     # exactly one state each
    assert not any(e["path"].startswith("raw/") for e in result["entries"])


def test_freshness_ignores_timestamps(tree):
    before = S.dumps(S.build_inventory(S.classify(tree.root)))
    for p in sorted(tree.root.rglob("*")):
        if p.is_file():
            os.utime(p, (1, 1))
    assert S.dumps(S.build_inventory(S.classify(tree.root))) == before

    forbidden = {"getmtime", "getctime", "getatime", "stat", "time", "now", "uuid4", "random", "getpid", "id", "hash"}
    tree_ast = ast.parse((ROOT / "scripts/core/stale_artifacts.py").read_text())
    calls = {
        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(tree_ast) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    assert not calls & forbidden, calls & forbidden


def test_remediation_planning():
    base = {"symlink": False, "kind": "prompt"}
    assert S.remediation({**base, "state": "CURRENT", "path": "generated/prompts/a/b.generate.txt"}) == "NONE"
    assert S.remediation({**base, "state": "ORPHAN", "path": "generated/prompts/a/b.generate.txt"}) == "REMOVE"
    assert S.remediation({**base, "state": "STALE", "path": "generated/prompts/a/b.generate.txt"}) == "REGENERATE"
    assert S.remediation({**base, "state": "UNMANAGED", "path": "generated/prompts/a/x.md"}) == "QUARANTINE"
    assert S.remediation({**base, "state": "ORPHAN", "kind": "canonical_ir",
                          "path": "normalized/ir/a/modules/b.yaml"}) == "REGENERATE"
    assert S.remediation({**base, "state": "HISTORICAL", "path": "generated/legacy/x"}) == "NONE"
    assert S.remediation({**base, "state": "UNMANAGED", "symlink": True, "path": "generated/x"}) == "MANUAL"


def test_safe_cleanup_path_validation(tree):
    root = tree.root
    (root / "generated/prompts/ipa/extra.md").write_text("x")
    assert S.validate_cleanup_path(root, "generated/prompts/ipa/extra.md") == root / "generated/prompts/ipa/extra.md"
    for bad in ("/etc/passwd", str(root / "generated/prompts/ipa/extra.md"), "../outside.txt",
                "generated/../raw/rtl/original/ipa/ipa.sv", "raw/rtl/original/ipa/ipa.sv",
                "normalized/ir/ipa/modules/ipa_m0.yaml", "generated/legacy/x.txt",
                "datasets/source/x.jsonl", "generated/prompts/ipa/missing.txt", ""):
        with pytest.raises(S.UnsafePath):
            S.validate_cleanup_path(root, bad)
    (root / "generated/link").symlink_to(root / "raw")
    with pytest.raises(S.UnsafePath):
        S.validate_cleanup_path(root, "generated/link/rtl/original/ipa/ipa.sv")


# -----------------------------------------------------------------------------
# Synthetic stale cases (criteria §21)
# -----------------------------------------------------------------------------

def test_case_a_deleted_module(tree):
    (tree.root / "normalized/ir/ipd/modules/ipd_m0.yaml").unlink()
    report = S.check(tree.root)
    assert report["status"] == "FAIL" and report["orphan"] >= 3
    assert _plan(report, "generated/prompts/ipd/ipd_m0.generate.txt") == {
        "path": "generated/prompts/ipd/ipd_m0.generate.txt", "state": "ORPHAN", "action": "REMOVE",
        "reason": "module ipd/ipd_m0 is not canonical"}
    assert _plan(report, "splits/split_manifest.json")["state"] == "ORPHAN"
    assert _plan(report, "datasets/pipeline/manifest.json")["state"] == "ORPHAN"
    assert any(p["path"].startswith("datasets/pipeline/") and p["path"].endswith(".jsonl")
               and p["state"] == "ORPHAN" for p in report["remediation_plan"])


def test_case_b_changed_source_identity(tree):
    src = tree.root / "raw/rtl/original/ipc/ipc.sv"
    src.write_text(src.read_text() + "// changed\n")
    report = S.check(tree.root)
    assert report["status"] == "FAIL" and report["invalid_source_identities"] > 0
    assert _plan(report, "normalized/ir/ipc/modules/ipc_m0.yaml")["state"] == "STALE"
    assert _plan(report, "normalized/ir/ipc/modules/ipc_m0.yaml")["action"] == "REGENERATE"
    assert _plan(report, "manifests/provenance_manifest.json")["state"] == "STALE"
    stale_sets = [p for p in report["remediation_plan"] if p["path"].startswith("datasets/pipeline/") and
                  "source identity" in (p["reason"] or "")]
    assert stale_sets


def test_case_c_obsolete_schema_unless_historical(tree):
    path = tree.pipeline_datasets / "train.jsonl"

    def old(records):
        records[0]["provenance"]["provenance_version"] = 0
        return records

    _rewrite_jsonl(path, old)
    report = S.check(tree.root)
    assert report["obsolete_schema"] >= 1 and _plan(report, "datasets/pipeline/train.jsonl")["state"] == "STALE"

    (tree.root / "datasets/legacy").mkdir(parents=True)
    shutil.copy(path, tree.root / "datasets/legacy/train_v0.jsonl")
    result = S.classify(tree.root)
    assert _entry(result, "datasets/legacy/train_v0.jsonl")["state"] == "HISTORICAL"

    sm = tree.splits / "split_manifest.json"
    data = json.loads(sm.read_text())
    data["split_schema_version"] = 0
    sm.write_text(json.dumps(data))
    assert _plan(S.check(tree.root), "splits/split_manifest.json")["state"] == "STALE"


def test_case_d_unexpected_file(tree):
    (tree.prompts / "ipa" / "notes.md").write_text("scratch")
    (tree.splits / "v0_manifest.json").write_text("{}")
    (tree.root / "scratch").mkdir()
    (tree.root / "scratch" / "tmp.json").write_text("{}")
    report = S.check(tree.root)
    assert report["status"] == "FAIL" and report["unmanaged"] == 3
    assert _plan(report, "generated/prompts/ipa/notes.md")["action"] == "QUARANTINE"
    assert _plan(report, "splits/v0_manifest.json")["action"] == "QUARANTINE"
    assert _plan(report, "scratch/tmp.json")["action"] == "REGENERATE"        # outside cleanable roots: manual


def test_case_e_duplicate_artifact(tree):
    shutil.copy(tree.prompts / "ipb" / "ipb_m0.generate.txt", tree.prompts / "ipb" / "ipb_m0.copy.txt")
    _rewrite_jsonl(tree.pipeline_datasets / "train.jsonl", lambda r: r + [r[0]])
    report = S.check(tree.root)
    assert report["duplicate_artifacts"] >= 2
    assert "second prompt file" in _plan(report, "generated/prompts/ipb/ipb_m0.copy.txt")["reason"]
    assert "duplicate record_id" in _plan(report, "datasets/pipeline/train.jsonl")["reason"]

    (tree.root / "analysis/reports/ipb").mkdir()
    shutil.copy(tree.root / "normalized/ir/ipb/summary.yaml", tree.root / "analysis/reports/ipb/summary.yaml")
    plan = _plan(S.check(tree.root), "analysis/reports/ipb/summary.yaml")
    assert plan["state"] == "STALE" and plan["action"] == "REMOVE" and "superseded duplicate" in plan["reason"]


def test_case_f_stale_dataset_record_blocks_dataset_generation(tree):
    """A removed module is caught by the pre-dataset gate; datasets are not rewritten."""
    datasets_before = _tree_hash(tree.root, "datasets")
    src = tree.root / "raw/rtl/original/ipd/ipd.sv"
    src.write_text(_ip_rtl("ipd", 1))                       # ipd_m1 disappears from the RTL
    with pytest.raises(RuntimeError, match="stale artifact gate \\(pre-dataset\\)"):
        _run(tree.root)
    assert _tree_hash(tree.root, "datasets") == datasets_before
    report = S.check(tree.root)
    assert _plan(report, "normalized/ir/ipd/modules/ipd_m1.yaml")["state"] in ("ORPHAN", "STALE")


def test_override_is_explicit_and_recorded(tree, monkeypatch):
    (tree.prompts / "ipa" / "notes.md").write_text("scratch")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")
    # the override relaxes only the stale gate; the KF-DQ-007 manifest gate
    # still blocks publication
    with pytest.raises(RuntimeError, match="KF-DQ-007"):
        _run(tree.root)
    stored = json.loads((tree.root / S.REPORT_PATH).read_text())
    assert stored["override"] is True and stored["status"] == "FAIL"


# -----------------------------------------------------------------------------
# Negative tests (criteria §22)
# -----------------------------------------------------------------------------

def _mutate_record(tree, fn, split="train"):
    def apply(records):
        fn(records[0])
        return records
    _rewrite_jsonl(tree.pipeline_datasets / f"{split}.jsonl", apply)
    return S.check(tree.root)


def test_missing_provenance(tree):
    report = _mutate_record(tree, lambda r: r.pop("provenance"))
    assert report["status"] == "FAIL" and report["invalid_provenance"] >= 1


def test_invalid_provenance(tree):
    report = _mutate_record(tree, lambda r: r["provenance"].update(record_id="r1:0000000000000000"))
    assert report["invalid_provenance"] >= 1


def test_missing_source_identity(tree):
    report = _mutate_record(tree, lambda r: r["provenance"]["source"].update(sha256=None))
    assert report["invalid_source_identities"] >= 1


def test_missing_module_identity(tree):
    report = _mutate_record(tree, lambda r: r["provenance"].pop("module_id"))
    assert report["invalid_module_identities"] >= 1


def test_missing_normalized_ir(tree):
    report = _mutate_record(tree, lambda r: r["provenance"]["normalized_ir"].update(path="normalized/ir/x/modules/y.yaml"))
    assert report["missing_ir_references"] >= 1


def test_nonportable_absolute_artifact_path(tree):
    report = _mutate_record(tree, lambda r: r["provenance"]["source"].update(
        path="/home/user/kritva-forge-data/" + r["provenance"]["source"]["path"]))
    assert report["status"] == "FAIL" and report["invalid_provenance"] >= 1
    stats = tree.reports / "pipeline_stats.json"
    data = json.loads(stats.read_text())
    data["note"] = "/tmp/build/x"
    stats.write_text(json.dumps(data))
    assert S.check(tree.root)["absolute_paths"] >= 1


def test_duplicate_output_path_in_inventory(tree):
    inv = tree.root / S.INVENTORY_PATH
    data = json.loads(inv.read_text())
    data["artifacts"].append(dict(data["artifacts"][0]))
    inv.write_text(S.dumps(data))
    report = S.check(tree.root)
    assert report["status"] == "FAIL" and report["inventory_status"] == "differs from recomputation"


def test_split_record_referring_to_removed_input(tree):
    sm = tree.splits / "split_manifest.json"
    data = json.loads(sm.read_text())
    data["train"][0]["module"] = "removed_module"
    sm.write_text(json.dumps(data))
    plan = _plan(S.check(tree.root), "splits/split_manifest.json")
    assert plan["state"] == "ORPHAN" and "not canonical" in plan["reason"]


def test_symlink_is_rejected(tree):
    (tree.prompts / "ipa" / "link.txt").symlink_to(tree.root / "raw/rtl/original/ipa/ipa.sv")
    report = S.check(tree.root)
    assert report["status"] == "FAIL" and report["symlinks"] == 1
    assert _plan(report, "generated/prompts/ipa/link.txt")["action"] == "MANUAL"
    S.cleanup(tree.root, apply=True)
    assert (tree.prompts / "ipa" / "link.txt").is_symlink()           # never deleted automatically
    assert (tree.root / "raw/rtl/original/ipa/ipa.sv").is_file()


def test_unsafe_plan_aborts_without_changes(tree):
    (tree.prompts / "ipa" / "notes.md").write_text("scratch")
    before = _tree_hash(tree.root, ".")
    plan = S.check(tree.root)["remediation_plan"] + [
        {"path": "raw/rtl/original/ipa/ipa.sv", "state": "ORPHAN", "action": "REMOVE", "reason": "evil"}]
    with pytest.raises(S.UnsafePath):
        S.cleanup(tree.root, apply=True, plan=plan)
    with pytest.raises(S.UnsafePath):
        S.cleanup(tree.root, apply=True, plan=[{"path": "../escape.txt", "state": "ORPHAN",
                                                "action": "REMOVE", "reason": "evil"}])
    assert _tree_hash(tree.root, ".") == before


# -----------------------------------------------------------------------------
# Cleanup, determinism, relocation
# -----------------------------------------------------------------------------

def _stale_tree(tree):
    (tree.root / "generated/rtl/pipeline/ipa").mkdir(parents=True)
    shutil.copy(tree.root / "raw/rtl/original/ipa/ipa.sv", tree.root / "generated/rtl/pipeline/ipa/ipa.sv")
    (tree.root / "generated/rtl/pipeline/gone").mkdir(parents=True)
    shutil.copy(tree.root / "raw/rtl/original/ipb/ipb.sv", tree.root / "generated/rtl/pipeline/gone/ipb.sv")
    (tree.root / "analysis/reports/ipa").mkdir()
    shutil.copy(tree.root / "normalized/ir/ipa/hierarchy.yaml", tree.root / "analysis/reports/ipa/hierarchy.yaml")
    (tree.prompts / "ipa" / "notes.md").write_text("scratch")
    (tree.root / "generated/legacy").mkdir(parents=True)
    (tree.root / "generated/legacy/keep.txt").write_text("history")


def test_cleanup_dry_run_apply_and_protection(tree):
    _stale_tree(tree)
    raw_before, ir_before = _tree_hash(tree.root, "raw"), _tree_hash(tree.root, "normalized")
    everything = _tree_hash(tree.root, ".")

    dry = S.cleanup(tree.root)
    assert _tree_hash(tree.root, ".") == everything                     # dry run changes nothing
    assert [(i["action"], i["path"]) for i in dry] == [
        ("REMOVE", "analysis/reports/ipa/hierarchy.yaml"),
        ("QUARANTINE", "generated/prompts/ipa/notes.md"),
        ("REMOVE", "generated/rtl/pipeline/gone/ipb.sv"),
        ("REMOVE", "generated/rtl/pipeline/ipa/ipa.sv"),
    ]
    log = S.cleanup(tree.root, apply=True)
    assert [{k: v for k, v in i.items() if k != "applied"} for i in log] == \
           [{k: v for k, v in i.items() if k != "applied"} for i in dry]
    assert _tree_hash(tree.root, "raw") == raw_before and _tree_hash(tree.root, "normalized") == ir_before
    assert (tree.root / "generated/legacy/keep.txt").read_text() == "history"
    assert (tree.root / S.QUARANTINE_ROOT / "generated/prompts/ipa/notes.md").read_text() == "scratch"
    assert not (tree.root / "generated/rtl").exists()

    report = S.write(tree.root)                                           # quarantined file is historical
    assert report["status"] == "PASS", report["problems"]
    assert report["historical"] == 2


def test_inventory_and_reports_deterministic_and_relocatable(tree, tmp_path):
    _stale_tree(tree)
    other = tmp_path / "moved" / "far" / "kritva-forge-data"
    shutil.copytree(tree.root, other, symlinks=True)
    a, b = S.check(tree.root), S.check(other)
    assert S.dumps(a) == S.dumps(b)
    assert S.dumps(S.build_inventory(S.classify(tree.root))) == S.dumps(S.build_inventory(S.classify(other)))
    assert str(tmp_path) not in S.dumps(b)
    assert S.dumps(S.cleanup(tree.root)) == S.dumps(S.cleanup(other))


def test_clean_runs_are_byte_identical(built, tmp_path):
    other = _run(_make_data_root(tmp_path / "b"))
    for rel in (S.INVENTORY_PATH, S.REPORT_PATH):
        assert (built.root / rel).read_bytes() == (other.root / rel).read_bytes()


# -----------------------------------------------------------------------------
# Real data checkout (runs with KRITVA_FORGE_DATA_ROOT)
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_has_no_stale_artifacts():
    report = S.check(DATA_ROOT)
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["stale"] == report["orphan"] == report["unmanaged"] == 0
