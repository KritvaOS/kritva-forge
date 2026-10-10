# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_split_leakage.py
# Description : KF-DQ-004 regression tests for leakage-safe deterministic splits
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Split leakage prevention (KF-DQ-004).

Unit tests use synthetic identities and a tiny temporary data repository;
the last test runs the leakage gate on a real data checkout when
``KRITVA_FORGE_DATA_ROOT`` is set.
"""

import ast
import json
import os
import random
import re
from pathlib import Path

import pytest

from scripts.core.paths import ForgeDataPaths
from scripts.dataset import leakage as L
from tests.data.corpus_kind import private_corpus_only

ROOT = Path(__file__).resolve().parents[2]


def _ident(ip, module, *, source=None, body=None, ir=None, comp=None, shape=None):
    """Synthetic identities; hard keys default to unique values per (ip, module)."""
    rec = {"ip": ip, "module": module, "task": "rtl_generation", "prompt_variant": f"{module}.generate.txt"}
    uniq = f"{ip}/{module}"
    return {
        "record_id": L.record_id(rec),
        "source_rtl": source or f"s:{uniq}",
        "module_body": body or f"b:{uniq}",
        "normalized_ir": ir or f"i:{uniq}",
        "completion": comp or f"c:{uniq}",
        "body_shape": shape or f"h:{uniq}",
        "module_name": module,
        "ip": ip,
    }


def _corpus():
    idents = []
    for ip, n in (("alpha", 12), ("beta", 9), ("gamma", 7), ("delta", 5), ("eps", 3)):
        idents += [_ident(ip, f"{ip}_m{i}") for i in range(n)]
    # shared library file reused by three IPs (same source / completion)
    for ip in ("alpha", "beta", "gamma"):
        idents.append(_ident(ip, "ctech_buf", source="s:lib", comp="c:lib", body="b:buf", ir="i:buf"))
    # renamed copy across IPs (near-duplicate only)
    idents.append(_ident("delta", "d_crc5", shape="h:crc5"))
    idents.append(_ident("eps", "e_crc5", shape="h:crc5"))
    # same-IP near duplicate (must stay soft)
    idents.append(_ident("alpha", "sbox", shape="h:sbox"))
    idents.append(_ident("alpha", "inv_sbox", shape="h:sbox"))
    return idents


def _split_identities(idents, assignment):
    return {s: [i for i in idents if assignment[i["record_id"]] == s] for s in L.SPLITS}


# -----------------------------------------------------------------------------
# Identity model
# -----------------------------------------------------------------------------

SOURCE = """\
// file header
module a (input x, output y);
  assign y = x;   // pass
endmodule

module b (input p, output q);
  /* block
     comment */
  assign q = ~p;
endmodule
"""


def _real_identities(module, source=SOURCE, spec=None, completion=None):
    record = {"ip": "demo", "module": module, "task": "rtl_generation",
              "prompt_variant": f"{module}.generate.txt", "completion": completion or source}
    return L.compute_identities(record, spec or {"module": module, "node_id": "n1:x", "source_file": "raw/x"}, source)


def test_leakage_identities_are_versioned_and_deterministic():
    assert L.LEAKAGE_SCHEMA_VERSION == 1 and L.SPLIT_SCHEMA_VERSION == 2
    first, second = _real_identities("a"), _real_identities("a")
    assert first == second
    for kind in L.HARD_IDENTITIES:
        assert re.fullmatch(r"[a-z]1:[0-9a-f]{16}", first[kind]), kind
    assert re.fullmatch(r"r1:[0-9a-f]{16}", first["record_id"])


def test_module_body_identity_ignores_comments_and_whitespace():
    a = _real_identities("a")
    b = _real_identities("b")
    reformatted = SOURCE.replace("assign y = x;   // pass", "assign   y   =\n    x;").replace("// file header", "")
    a2 = _real_identities("a", source=reformatted)

    assert a["source_rtl"] == b["source_rtl"]          # same file
    assert a["module_body"] != b["module_body"]        # different modules
    assert a2["module_body"] == a["module_body"]        # comments/whitespace ignored
    assert a2["source_rtl"] != a["source_rtl"]          # raw text identity is exact
    assert L.module_body(reformatted, "a") is not None
    assert " ".join(L.strip_comments(SOURCE).split()).count("module") == 4


def test_normalized_ir_identity_ignores_location_fields():
    base = {"module": "a", "ports": [{"name": "x", "node_id": "n1:aaaa", "offset": 10,
                                      "buffer": "raw/rtl/original/x/a.sv", "source_file": "raw/rtl/original/x/a.sv"}]}
    moved = json.loads(json.dumps(base))
    moved["ports"][0].update(node_id="n1:bbbb", offset=99, buffer="raw/rtl/original/y/a.sv",
                             source_file="raw/rtl/original/y/a.sv")
    moved["is_top"] = True
    assert _real_identities("a", spec=base)["normalized_ir"] == _real_identities("a", spec=moved)["normalized_ir"]


def test_identities_exclude_runtime_and_paths():
    tree = ast.parse((ROOT / "scripts/dataset/leakage.py").read_text())
    calls = {
        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
        for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    assert not calls & {"id", "hash", "uuid1", "uuid4", "getpid", "gethostname", "getuser", "time", "now", "shuffle", "random"}
    ident = _real_identities("a")
    assert not any(str(v).startswith("/") for v in ident.values())


# -----------------------------------------------------------------------------
# Grouping and assignment
# -----------------------------------------------------------------------------

def test_hard_groups_never_cross_splits():
    idents = _corpus()
    assignment, groups = L.assign_splits(idents)

    for group in groups:
        assert len({assignment[r] for r in group["records"]}) == 1, group
    report = L.check_leakage(_split_identities(idents, assignment),
                             L.build_manifest([{"ip": i["ip"], "module": i["module_name"]} for i in idents],
                                              idents, assignment, groups))
    assert report["status"] == "PASS", report["problems"]
    assert report["cross_split_hard_groups"] == 0


def test_shared_library_groups_go_to_train():
    idents = _corpus()
    assignment, groups = L.assign_splits(idents)

    lib = [i for i in idents if i["module_name"] == "ctech_buf"]
    assert {assignment[i["record_id"]] for i in lib} == {"train"}
    shared = [g for g in groups if g["policy"] == "shared_library->train"]
    assert any(set(g["ips"]) == {"alpha", "beta", "gamma"} for g in shared)


def test_cross_ip_near_duplicates_grouped_same_ip_soft():
    idents = _corpus()
    assignment, groups = L.assign_splits(idents)
    by_module = {i["module_name"]: i["record_id"] for i in idents}

    # renamed copy across IPs: one shared group -> train
    assert assignment[by_module["d_crc5"]] == assignment[by_module["e_crc5"]] == "train"
    # same-IP near duplicates are not merged into a separate group
    group_of = {r: g["group_id"] for g in groups for r in g["records"]}
    assert group_of[by_module["sbox"]] != group_of[by_module["inv_sbox"]]


def test_assignment_independent_of_input_order():
    idents = _corpus()
    reference = L.assign_splits(idents)[0]
    for seed in range(5):
        shuffled = idents[:]
        random.Random(seed).shuffle(shuffled)
        assert L.assign_splits(shuffled)[0] == reference


def test_split_targets_and_ip_units_atomic():
    idents = _corpus()
    assignment, groups = L.assign_splits(idents)
    assert L.split_targets(100) == {"train": 70, "validation": 15, "test": 15}

    for ip in {i["ip"] for i in idents}:
        unit = {assignment[g["records"][0]] for g in groups if g["policy"] == "ip_unit" and g["ips"] == [ip]}
        assert len(unit) <= 1, ip
    assert all(any(v == s for v in assignment.values()) for s in L.SPLITS)


# -----------------------------------------------------------------------------
# Gate
# -----------------------------------------------------------------------------

def _good():
    idents = _corpus()
    assignment, groups = L.assign_splits(idents)
    records = [{"ip": i["ip"], "module": i["module_name"]} for i in idents]
    return idents, assignment, L.build_manifest(records, idents, assignment, groups)


def test_gate_fails_on_cross_split_hard_leakage():
    idents, assignment, manifest = _good()
    lib = [i for i in idents if i["module_name"] == "ctech_buf"][0]
    split_ids = _split_identities(idents, assignment)
    split_ids["train"].remove(lib)
    split_ids["test"].append(lib)

    report = L.check_leakage(split_ids, manifest)

    assert report["status"] == "FAIL"
    assert report["cross_split_hard_groups"] >= 1
    assert any("source_rtl" in p for p in report["problems"])


def test_gate_fails_on_duplicate_missing_or_inconsistent_manifest():
    idents, assignment, manifest = _good()
    split_ids = _split_identities(idents, assignment)

    dup = {k: list(v) for k, v in split_ids.items()}
    dup["validation"].append(dup["train"][0])
    assert any("duplicate record" in p for p in L.check_leakage(dup, manifest)["problems"])

    missing = L.check_leakage(split_ids, None)
    assert missing["status"] == "FAIL" and missing["manifest_status"] == "absent"

    broken = json.loads(json.dumps(manifest))
    broken["test"].pop()
    report = L.check_leakage(split_ids, broken)
    assert report["status"] == "FAIL" and report["manifest_status"] == "inconsistent"

    assert L.check_leakage(split_ids, manifest)["status"] == "PASS"
    text = L.format_report(L.check_leakage(split_ids, manifest))
    for needle in ("records scanned", "hard leakage groups", "cross-split groups", "manifest status",
                   "determinism status", "PASS"):
        assert needle in text


def test_gate_fails_on_nonreproducible_assignment():
    """A leak-free split that the policy would not produce is rejected."""
    idents, assignment, _ = _good()
    ip_unit = next(i["ip"] for i in idents if assignment[i["record_id"]] != "train")
    moved = dict(assignment)
    for i in idents:
        if i["ip"] == ip_unit and assignment[i["record_id"]] != "train":
            moved[i["record_id"]] = "train"
    _, groups = L.assign_splits(idents)
    records = [{"ip": i["ip"], "module": i["module_name"]} for i in idents]
    manifest = L.build_manifest(records, idents, moved, groups)

    report = L.check_leakage(_split_identities(idents, moved), manifest)

    assert report["cross_split_hard_groups"] == 0 and report["manifest_status"] == "consistent"
    assert report["status"] == "FAIL" and report["determinism_status"].startswith("differs")


def test_gate_fails_on_missing_identity():
    idents, assignment, manifest = _good()
    split_ids = _split_identities(idents, assignment)
    broken = {k: [dict(i) for i in v] for k, v in split_ids.items()}
    del broken["test"][0]["module_body"]

    report = L.check_leakage(broken, manifest)

    assert report["status"] == "FAIL"
    assert any("missing split identities" in p for p in report["problems"])
    assert any("module_body" in p for p in report["problems"])
    assert "[FAIL]" in L.format_report(report)


# -----------------------------------------------------------------------------
# End to end through the pipeline (tiny data repository)
# -----------------------------------------------------------------------------

LIB = """\
module lib_buf (input a, output y); assign y = a; endmodule
module lib_inv (input a, output y); assign y = ~a; endmodule
"""


def _ip_rtl(name, n):
    mods = [f"module {name}_m{i} (input a, output y); assign y = a ^ 1'b{i % 2}; endmodule\n" for i in range(n)]
    top = f"module {name}_top (input a, output y); lib_buf u0 (.a(a), .y(y)); endmodule\n"
    return "".join(mods) + top


def _make_data_root(base):
    root = base / "kritva-forge-data"
    original = root / "raw" / "rtl" / "original"
    (original / "common").mkdir(parents=True)
    (original / "common" / "lib.sv").write_text(LIB)
    for name, n in (("ipa", 6), ("ipb", 4), ("ipc", 3), ("ipd", 2)):
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


def test_pipeline_writes_leakage_safe_split_and_manifest(tmp_path):
    data = _run(_make_data_root(tmp_path))

    manifest = json.loads((data.splits / "split_manifest.json").read_text())
    report = json.loads((data.reports / "split_leakage_report.json").read_text())
    assert report["status"] == "PASS" and report["manifest_status"] == "consistent"
    assert sum(manifest["counts"].values()) == report["records_scanned"]

    # the library modules (lib_buf/lib_inv, present in every IP) are only in train
    for split in ("validation", "test"):
        assert not [e for e in manifest[split] if e["module"].startswith("lib_")]

    gate = L.check_leakage(L.load_split_identities(str(data.root)), manifest)
    assert gate["status"] == "PASS", gate["problems"]


def test_split_repeatable_and_relocation_independent(tmp_path):
    a = _run(_make_data_root(tmp_path / "home" / "user" / "checkout"))
    b = _run(_make_data_root(tmp_path / "relocated"))

    for rel in ("splits/split_manifest.json", "analysis/reports/split_leakage_report.json",
                "datasets/pipeline/train.jsonl", "datasets/pipeline/validation.jsonl",
                "datasets/pipeline/test.jsonl"):
        assert (a.root / rel).read_bytes() == (b.root / rel).read_bytes(), rel
    assert str(tmp_path) not in (a.root / "splits/split_manifest.json").read_text()


# -----------------------------------------------------------------------------
# Real data checkout
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_split_has_no_leakage():
    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(DATA_ROOT)
    manifest_path = data.splits / "split_manifest.json"
    assert manifest_path.exists(), "split manifest missing"
    report = L.check_leakage(L.load_split_identities(DATA_ROOT), json.loads(manifest_path.read_text()))
    assert report["status"] == "PASS", L.format_report(report)


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
@private_corpus_only
def test_data_repository_split_schema_v2_counts():
    """KF-DQ-013.0 AC-031: split schema v2 on the private corpus (248 / 51 / 51, no cross-split near-duplicate)."""
    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(DATA_ROOT)
    manifest = json.loads((data.splits / "split_manifest.json").read_text())
    assert manifest["split_schema_version"] == 2
    assert manifest["counts"] == {"train": 248, "validation": 51, "test": 51}
    report = json.loads((data.reports / "split_leakage_report.json").read_text())
    assert report["near_duplicate"]["cross_split_edges"] == 0
    cls = json.loads((data.reports / "prompt_leakage_classification.json").read_text())
    assert cls["counts"]["near_duplicate"] == 0 and cls["kf_dq_013_entry"] == "open"
