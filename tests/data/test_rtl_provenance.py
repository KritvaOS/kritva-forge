# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_rtl_provenance.py
# Description : KF-DQ-005 tests for the canonical RTL provenance manifest and validator
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""RTL provenance metadata (KF-DQ-005).

Builds a tiny data repository, runs the real pipeline once and validates the
provenance manifest; the negative tests corrupt copies of that tree and
expect the validator to fail with the matching counter.
"""

import ast
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from scripts.core import provenance as P
from scripts.core.paths import ForgeDataPaths, find_absolute_paths, iter_module_yamls
from scripts.dataset import leakage as L

ROOT = Path(__file__).resolve().parents[2]

LIB = """\
module lib_buf (input a, output y); assign y = a; endmodule
module lib_inv (input a, output y); assign y = ~a; endmodule
"""

DEFS = """\
`define IPA_ONE 1'b1
`include "ipa_more.svh"
"""

MORE = "`define IPA_ZERO 1'b0\n"

IPA = """\
`include "ipa_defs.svh"
`ifdef IPA_CUSTOM
  `include "ipa_custom.svh"
`endif
module ipa_m0 (input a, output y); assign y = a ^ `IPA_ONE; endmodule
module ipa_m1 (input a, output y); assign y = a | `IPA_ZERO; endmodule
module ipa_top (input a, output y); lib_buf u0 (.a(a), .y(y)); endmodule
"""


def _ip_rtl(name, n):
    mods = [f"module {name}_m{i} (input a, output y); assign y = a ^ 1'b{i % 2}; endmodule\n" for i in range(n)]
    return "".join(mods) + f"module {name}_top (input a, output y); lib_buf u0 (.a(a), .y(y)); endmodule\n"


def _make_data_root(base):
    root = base / "kritva-forge-data"
    original = root / "raw" / "rtl" / "original"
    (original / "common").mkdir(parents=True)
    (original / "common" / "lib.sv").write_text(LIB)
    (original / "ipa" / "inc").mkdir(parents=True)
    (original / "ipa" / "ipa.sv").write_text(IPA)
    (original / "ipa" / "inc" / "ipa_defs.svh").write_text(DEFS)
    (original / "ipa" / "inc" / "ipa_more.svh").write_text(MORE)
    (original / "ipa" / "files.f").write_text("+incdir+inc\nipa.sv\n../common/lib.sv\n")
    for name, n in (("ipb", 4), ("ipc", 3), ("ipd", 2)):
        (original / name).mkdir()
        (original / name / f"{name}.sv").write_text(_ip_rtl(name, n))
        (original / name / "files.f").write_text(f"{name}.sv\n../common/lib.sv\n")
    return root


def _run(root):
    from scripts.pipeline.run_pipeline import run_pipeline

    data = ForgeDataPaths.from_root(root)
    run_pipeline(str(data.raw_rtl / "original"), str(data.normalized_ir), data_root=str(root),
                 prompt_root=str(data.prompts), reports_root=str(data.reports),
                 datasets_root=str(data.pipeline_datasets))
    return data


def _raw_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted((root / "raw").rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("prov")
    root = _make_data_root(base)
    before = _raw_tree(root)
    data = _run(root)
    assert _raw_tree(root) == before          # raw RTL untouched
    return data


@pytest.fixture
def tree(built, tmp_path):
    """Writable copy of the built data repository."""
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest)
    return ForgeDataPaths.from_root(dest)


def _manifest(data):
    return json.loads((data.manifests / P.MANIFEST_NAME).read_text())


def _store(data, manifest):
    (data.manifests / P.MANIFEST_NAME).write_text(P.dumps(manifest))


def _entry(manifest, ip, module):
    return next(m for m in manifest["modules"] if (m["ip"], m["module"]) == (ip, module))


def _fails(data, counter):
    report = P.check_provenance(data.root)
    assert report["status"] == "FAIL", report
    assert report[counter], (counter, report)
    assert "[FAIL]" in P.format_report(report)
    return report


# -----------------------------------------------------------------------------
# Unit
# -----------------------------------------------------------------------------

def test_source_hash_and_module_identity(tmp_path):
    f = tmp_path / "x.v"
    f.write_bytes(b"module x; endmodule\n")
    assert P.sha256_file(f) == hashlib.sha256(b"module x; endmodule\n").hexdigest()
    os.utime(f, (1, 1))
    assert P.sha256_file(f) == hashlib.sha256(b"module x; endmodule\n").hexdigest()   # mtime-independent

    assert P.PROVENANCE_VERSION == 1
    mid = P.module_id("uart", "uart_tx")
    assert re.fullmatch(r"mod1:[0-9a-f]{16}", mid)
    assert mid == P.module_id("uart", "uart_tx")
    assert mid != P.module_id("uartm", "uart_tx") != P.module_id("uart", "uart_rx")


def test_relative_path_normalization(tmp_path):
    root = tmp_path / "d"
    assert P.portable(root / "raw" / "rtl" / "original" / "a" / ".." / "b" / "x.v", root) == "raw/rtl/original/b/x.v"
    with pytest.raises(ValueError):
        P.portable(tmp_path / "elsewhere" / "x.v", root)


def test_include_resolution(tmp_path):
    root = _make_data_root(tmp_path)
    resolver = P.IncludeResolver(root)
    resolved, unresolved, external = resolver.closure(root / "raw/rtl/original/ipa/ipa.sv", "ipa")
    assert [p.relative_to(root).as_posix() for p in resolved] == [
        "raw/rtl/original/ipa/inc/ipa_defs.svh",      # via files.f +incdir+
        "raw/rtl/original/ipa/inc/ipa_more.svh",      # nested, via including directory
    ]
    assert unresolved == [] and external == ["ipa_custom.svh"]

    (root / "raw/rtl/original/ipb/ipb.sv").write_text('`include "nowhere.svh"\n' + _ip_rtl("ipb", 1))
    assert P.IncludeResolver(root).closure(root / "raw/rtl/original/ipb/ipb.sv", "ipb")[1] == ["nowhere.svh"]


def test_provenance_code_has_no_runtime_identity():
    forbidden = {"id", "hash", "uuid1", "uuid4", "getpid", "gethostname", "getuser", "time", "now",
                 "random", "shuffle", "getmtime", "getctime", "stat", "mkdtemp", "mkstemp"}
    tree = ast.parse((ROOT / "scripts/core/provenance.py").read_text())
    calls = {
        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    assert not calls & forbidden, calls & forbidden


# -----------------------------------------------------------------------------
# Manifest built by the pipeline
# -----------------------------------------------------------------------------

def test_pipeline_writes_complete_valid_manifest(built):
    manifest = _manifest(built)
    report = json.loads((built.reports / P.REPORT_NAME).read_text())
    canonical = sorted((p.parent.parent.name, p.stem) for p in iter_module_yamls(built.normalized_ir))

    assert report["status"] == "PASS", report["problems"]
    assert P.check_provenance(built.root)["status"] == "PASS"
    assert sorted((m["ip"], m["module"]) for m in manifest["modules"]) == canonical
    assert manifest["counts"]["modules"] == len(canonical) == report["modules_checked"]
    assert manifest["provenance_version"] == P.PROVENANCE_VERSION
    assert manifest["pipeline"]["identity_version"] == "1"
    assert not find_absolute_paths(P.dumps(manifest))

    for m in manifest["modules"]:
        assert m["transformation"] == "normalized"
        assert m["source"]["path"].startswith("raw/rtl/original/")
        assert m["source"]["sha256"] == P.sha256_file(built.root / m["source"]["path"])
        assert m["normalized_ir"]["path"] == f"normalized/ir/{m['ip']}/modules/{m['module']}.yaml"
        assert m["contributing_sources"][0] == {**m["source"], "role": "primary"}
        assert m["prompts"] and all(p["path"].startswith(f"generated/prompts/{m['ip']}/") for p in m["prompts"])

    ipa = _entry(manifest, "ipa", "ipa_m0")
    assert [s["path"] for s in ipa["contributing_sources"][1:]] == [
        "raw/rtl/original/ipa/inc/ipa_defs.svh", "raw/rtl/original/ipa/inc/ipa_more.svh"]
    assert ipa["external_includes"] == ["ipa_custom.svh"] and ipa["unresolved_includes"] == []
    lib = next(s for s in manifest["sources"] if s["path"] == "raw/rtl/original/common/lib.sv")
    assert len(lib["modules"]) == 8                      # lib_buf / lib_inv in each of 4 IPs


def test_identities_are_distinguishable(built):
    manifest = _manifest(built)
    m = _entry(manifest, "ipb", "ipb_m0")
    record = m["dataset_records"][0]["record_id"]
    values = {
        "source": m["source"]["sha256"],
        "module": m["module_id"],
        "module_body": m["module_body"],
        "ir_file": m["normalized_ir"]["sha256"],
        "ir_content": m["normalized_ir"]["ir_content"],
        "record": record,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", values["source"])
    assert values["module"].startswith("mod1:") and values["module_body"].startswith("m1:")
    assert values["ir_content"].startswith("n1:") and values["record"].startswith("r1:")
    assert len(set(values.values())) == len(values)


def test_dataset_records_trace_to_source(built):
    manifest = _manifest(built)
    by_id = {m["module_id"]: m for m in manifest["modules"]}
    n = 0
    for split, _, record in P.iter_dataset_records(built.root):
        n += 1
        prov = record["provenance"]
        entry = by_id[prov["module_id"]]
        assert (entry["ip"], entry["module"]) == (record["ip"], record["module"])
        assert prov["record_id"] == L.record_id(record)
        assert prov["source"] == {"type": "original", **entry["source"]}
        assert P.sha256_file(built.root / prov["source"]["path"]) == prov["source"]["sha256"]
        assert prov["normalized_ir"]["sha256"] == P.sha256_file(built.root / prov["normalized_ir"]["path"])
        assert prov["generated_artifact"] is None
        assert record["rtl_source"] == "original"
        assert len(json.dumps(prov)) < 1024                # no RTL payload duplicated
        assert any(r["record_id"] == prov["record_id"] and r["split"] == split for r in entry["dataset_records"])
    assert n == manifest["counts"]["dataset_records"] > 0


def test_leakage_gate_still_passes(built):
    manifest = json.loads((built.splits / "split_manifest.json").read_text())
    assert L.check_leakage(L.load_split_identities(str(built.root)), manifest)["status"] == "PASS"


def test_provenance_deterministic_and_relocation_independent(built, tmp_path):
    other = _run(_make_data_root(tmp_path / "somewhere" / "else"))
    for rel in ("manifests/provenance_manifest.json", "analysis/reports/provenance_report.json",
                "datasets/pipeline/train.jsonl", "datasets/pipeline/validation.jsonl",
                "datasets/pipeline/test.jsonl"):
        assert (built.root / rel).read_bytes() == (other.root / rel).read_bytes(), rel
    assert P.dumps(P.build_manifest(built.root)) == P.dumps(P.build_manifest(other.root))
    assert str(tmp_path) not in (other.manifests / P.MANIFEST_NAME).read_text()


# -----------------------------------------------------------------------------
# Negative tests (criteria §16)
# -----------------------------------------------------------------------------

def test_fails_on_missing_manifest(tree):
    (tree.manifests / P.MANIFEST_NAME).unlink()
    assert _fails(tree, "problems")["schema_status"] == "absent"


def test_fails_on_missing_source_file(tree):
    (tree.root / "raw/rtl/original/ipb/ipb.sv").unlink()
    _fails(tree, "unresolved_sources")


def test_fails_on_invalid_source_hash(tree):
    m = _manifest(tree)
    _entry(m, "ipb", "ipb_m0")["contributing_sources"][0]["sha256"] = "not-a-hash"
    _store(tree, m)
    _fails(tree, "invalid_hashes")


def test_fails_on_incorrect_source_hash(tree):
    path = tree.root / "raw/rtl/original/ipc/ipc.sv"
    path.write_text(path.read_text() + "// edited\n")
    report = _fails(tree, "incorrect_hashes")
    assert report["determinism_status"] == "differs"


def test_fails_on_absolute_source_path(tree):
    m = _manifest(tree)
    e = _entry(m, "ipb", "ipb_m0")
    e["source"]["path"] = "/home/user/kritva-forge-data/" + e["source"]["path"]
    _store(tree, m)
    report = _fails(tree, "absolute_paths")
    assert report["unresolved_sources"] and report["relocation_status"] == "location-dependent"


def test_fails_on_missing_module_identity(tree):
    m = _manifest(tree)
    del _entry(m, "ipb", "ipb_m0")["module_id"]
    _store(tree, m)
    _fails(tree, "missing_identities")


def test_fails_on_duplicate_module_identity(tree):
    m = _manifest(tree)
    _entry(m, "ipb", "ipb_m1")["module_id"] = _entry(m, "ipb", "ipb_m0")["module_id"]
    _store(tree, m)
    _fails(tree, "duplicate_identities")


def test_fails_on_missing_ir_reference(tree):
    m = _manifest(tree)
    _entry(m, "ipb", "ipb_m0")["normalized_ir"]["path"] = None
    _entry(m, "ipc", "ipc_m0")["normalized_ir"]["sha256"] = "0" * 64
    _store(tree, m)
    assert _fails(tree, "invalid_ir_refs")["invalid_ir_refs"] == 2


def test_fails_on_missing_provenance_record(tree):
    m = _manifest(tree)
    m["modules"] = [e for e in m["modules"] if (e["ip"], e["module"]) != ("ipd", "ipd_m0")]
    _store(tree, m)
    _fails(tree, "missing_records")


def test_fails_on_orphan_provenance_record(tree):
    m = _manifest(tree)
    ghost = json.loads(json.dumps(_entry(m, "ipd", "ipd_m0")))
    ghost.update(ip="ghost", module_id=P.module_id("ghost", "ipd_m0"))
    m["modules"].append(ghost)
    _store(tree, m)
    _fails(tree, "orphan_records")


def test_fails_on_duplicate_provenance_entry(tree):
    m = _manifest(tree)
    m["modules"].append(json.loads(json.dumps(_entry(m, "ipd", "ipd_m0"))))
    _store(tree, m)
    _fails(tree, "duplicate_entries")


def test_fails_on_invalid_schema_version(tree):
    m = _manifest(tree)
    m["provenance_version"] = 99
    _store(tree, m)
    assert _fails(tree, "problems")["schema_status"] == "invalid"


def test_fails_on_relocation_dependent_provenance(tree):
    m = _manifest(tree)
    _entry(m, "ipb", "ipb_m0")["prompts"][0]["path"] = str(tree.root / "generated/prompts/ipb/x.txt")
    _store(tree, m)
    assert _fails(tree, "absolute_paths")["relocation_status"] == "location-dependent"


def test_fails_on_nondeterministic_provenance(tree):
    m = _manifest(tree)
    m["modules"].reverse()                                # same content, different order
    _store(tree, m)
    assert _fails(tree, "problems")["determinism_status"] == "differs"


def test_fails_on_untraceable_dataset_record(tree):
    path = tree.pipeline_datasets / "train.jsonl"
    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    del first["provenance"]
    path.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n")
    _fails(tree, "untraceable_records")


def test_fails_on_unresolved_include(tree):
    path = tree.root / "raw/rtl/original/ipb/ipb.sv"
    path.write_text('`include "missing_defs.svh"\n' + path.read_text())
    _fails(tree, "unresolved_includes")


# -----------------------------------------------------------------------------
# Real data checkout (runs with KRITVA_FORGE_DATA_ROOT)
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_provenance_is_complete():
    report = P.check_provenance(DATA_ROOT)
    assert report["status"] == "PASS", report["problems"][:10]
    assert report["modules_checked"] == report["manifest_modules"]
    assert report["records_checked"] > 0 and report["untraceable_records"] == 0
