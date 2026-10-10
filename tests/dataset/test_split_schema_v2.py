# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_split_schema_v2.py
# Description : KF-DQ-013.0 split schema v2 - near-duplicate grouping edges, gate and pipeline tests
#
# Component   : Kritva Forge
# Module      : tests/dataset
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Split schema v2 (KF-DQ-013.0 AC-043 .. AC-046, AC-042, AC-024).

Unit tests use synthetic identities and edges; the fail-closed and pipeline
tests use a tiny data repository in which ``ipc_tx`` / ``ipd_tx`` are a
cross-IP near-duplicate pair that split schema v1 places in different splits.
"""

import json
import os
import random
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from scripts.core.paths import ForgeDataPaths
from scripts.dataset import leakage as L
from scripts.dataset import near_duplicate as ND
from scripts.prompt_v2 import classify as C

ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Synthetic identities
# -----------------------------------------------------------------------------

def _ident(ip, module, *, source=None, shape=None):
    rec = {"ip": ip, "module": module, "task": "rtl_generation", "prompt_variant": f"{module}.generate.txt"}
    uniq = f"{ip}/{module}"
    return {
        "record_id": L.record_id(rec),
        "source_rtl": source or f"s:{uniq}",
        "module_body": f"b:{uniq}" if not source else f"b:{source}",
        "normalized_ir": f"i:{uniq}" if not source else f"i:{source}",
        "completion": f"c:{uniq}" if not source else f"c:{source}",
        "body_shape": shape or f"h:{uniq}",
        "module_name": module,
        "ip": ip,
    }


def _corpus():
    idents = []
    for ip, n in (("alpha", 12), ("beta", 9), ("gamma", 7), ("delta", 5), ("eps", 3)):
        idents += [_ident(ip, f"{ip}_m{i}") for i in range(n)]
    for ip in ("alpha", "beta", "gamma"):
        idents.append(_ident(ip, "ctech_buf", source="lib"))
    idents.append(_ident("delta", "d_crc5", shape="h:crc5"))
    idents.append(_ident("eps", "e_crc5", shape="h:crc5"))
    return idents


def _v1_assign(identities):
    """Frozen copy of the split schema v1 policy (KF-DQ-004) - the AC-015 reference."""
    groups = L.build_groups(identities, cross_ip_kinds=L.CROSS_IP_NEAR_DUPLICATE)
    assignment, counts, units = {}, {s: 0 for s in L.SPLITS}, defaultdict(list)
    for g in groups:
        if len(g["ips"]) > 1:
            for r in g["records"]:
                assignment[r] = "train"
            counts["train"] += len(g["records"])
        else:
            units[g["ips"][0]].extend(g["records"])
    targets = L.split_targets(len(identities))
    for ip, rids in sorted(units.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        split = max(L.SPLITS, key=lambda s: (targets[s] - counts[s], -L.SPLITS.index(s)))
        for r in rids:
            assignment[r] = split
        counts[split] += len(rids)
    return assignment


def _rid(idents, ip, module):
    return next(i["record_id"] for i in idents if i["ip"] == ip and i["module_name"] == module)


def _split_identities(idents, assignment):
    return {s: [i for i in idents if assignment[i["record_id"]] == s] for s in L.SPLITS}


def _edge_doc(*pairs, score=0.9):
    doc = ND.empty()
    doc["candidate_pairs"] = len(pairs)
    doc["edges"] = sorted(({"a": ND.key(*a), "b": ND.key(*b), "similarity": score}
                           for a, b in (sorted(p) for p in pairs)), key=lambda e: (e["a"], e["b"]))
    return doc


# -----------------------------------------------------------------------------
# Policy (AC-012 .. AC-015, AC-043)
# -----------------------------------------------------------------------------

def test_split_schema_version_is_2():
    assert L.SPLIT_SCHEMA_VERSION == 2 and L.LEAKAGE_SCHEMA_VERSION == 1


def test_v2_without_edges_equals_v1():
    idents = _corpus()
    assert L.assign_splits(idents)[0] == _v1_assign(idents)
    assert L.assign_splits(idents, [])[0] == _v1_assign(idents)


def test_cross_ip_edge_joins_and_promotes_shared_library():
    idents = _corpus()
    v1 = _v1_assign(idents)
    a, b = ("delta", "delta_m0"), ("eps", "eps_m0")
    assert v1[_rid(idents, *a)] != v1[_rid(idents, *b)]          # crosses splits under v1
    assignment, groups = L.assign_splits(idents, [(a, b)])
    assert assignment[_rid(idents, *a)] == assignment[_rid(idents, *b)] == "train"
    g = next(g for g in groups if _rid(idents, *a) in g["records"])
    assert g["policy"] == "shared_library->train" and "near_duplicate" in g["joined_by"]
    assert set(g["ips"]) == {"delta", "eps"}


def test_same_ip_edge_joins_a_shared_library_member():
    idents = _corpus()
    lib, own = ("alpha", "ctech_buf"), ("alpha", "alpha_m0")
    v1 = _v1_assign(idents)
    assert v1[_rid(idents, *lib)] == "train"
    assignment, groups = L.assign_splits(idents, [(lib, own)])
    assert assignment[_rid(idents, *own)] == assignment[_rid(idents, *lib)]
    g = next(g for g in groups if _rid(idents, *own) in g["records"])
    assert "near_duplicate" in g["joined_by"] and "hard" in g["joined_by"]


def test_assignment_independent_of_input_and_edge_order():
    idents = _corpus()
    edges = [(("delta", "delta_m0"), ("eps", "eps_m0")), (("beta", "beta_m1"), ("gamma", "gamma_m2"))]
    reference = L.assign_splits(idents, edges)[0]
    rng = random.Random(7)
    for _ in range(5):
        shuffled, es = idents[:], [tuple(reversed(e)) for e in edges]
        rng.shuffle(shuffled)
        rng.shuffle(es)
        assert L.assign_splits(shuffled, es)[0] == reference


def test_edge_threshold_boundary(monkeypatch):
    info = {(f"ip{i}", f"m{i}"): {"module_id": f"x{i}", "source": {}} for i in range(4)}
    by_fp = {("structural", "s1"): {("ip0", "m0"), ("ip1", "m1")}, ("fsm", "f1"): {("ip2", "m2"), ("ip3", "m3")}}
    scores = {(("ip0", "m0"), ("ip1", "m1")): 0.70, (("ip2", "m2"), ("ip3", "m3")): 0.6999994}
    monkeypatch.setattr(C, "fingerprint_index", lambda root: (info, by_fp))
    monkeypatch.setattr(C, "SourceTexts", lambda root, info: None)
    monkeypatch.setattr(C, "pair_similarity", lambda text, a, b: scores[(a, b)])
    doc = ND.compute("unused")
    assert doc["candidate_pairs"] == 2
    assert doc["edges"] == [{"a": "ip0/m0", "b": "ip1/m1", "similarity": 0.7}]
    assert ND.validate(doc) == []


def test_edge_document_validation():
    assert ND.validate(None) == ["near_duplicate block missing"]
    doc = _edge_doc((("a", "x"), ("b", "y")))
    assert ND.validate(doc) == []
    bad = json.loads(json.dumps(doc))
    bad["edges"][0]["similarity"] = 0.5
    assert any("below the threshold" in p for p in ND.validate(bad))
    bad = json.loads(json.dumps(doc))
    bad["classifier"] = "rtl-sim-v0"
    assert any("classifier" in p for p in ND.validate(bad))
    bad = json.loads(json.dumps(doc))
    bad["edges"][0]["a"], bad["edges"][0]["b"] = bad["edges"][0]["b"], bad["edges"][0]["a"]
    assert any("not ordered" in p for p in ND.validate(bad))


# -----------------------------------------------------------------------------
# Gate (AC-019 .. AC-023, AC-044)
# -----------------------------------------------------------------------------

def _gate_setup(edges):
    idents = _corpus()
    doc = _edge_doc(*edges)
    assignment, groups = L.assign_splits(idents, ND.pairs(doc))
    records = [{"ip": i["ip"], "module": i["module_name"], "task": "rtl_generation",
                "prompt_variant": f"{i['module_name']}.generate.txt"} for i in idents]
    manifest = L.build_manifest(records, idents, assignment, groups, doc)
    return idents, doc, assignment, manifest


EDGE = (("delta", "delta_m0"), ("eps", "eps_m0"))


def test_gate_passes_and_reports_edges():
    idents, doc, assignment, manifest = _gate_setup([EDGE])
    report = L.check_leakage(_split_identities(idents, assignment), manifest, doc)
    assert report["status"] == "PASS", report["problems"]
    nd = report["near_duplicate"]
    assert nd["edges"] == 1 and nd["effective_edges"] == 1 and nd["cross_split_edges"] == 0
    assert nd["edge_status"] == "consistent" and nd["classifier"] == "rtl-sim-v1"
    assert "near-dup edges" in L.format_report(report)
    assert manifest["split_schema_version"] == 2 and manifest["near_duplicate"] == doc
    assert all("joined_by" in g for g in manifest["groups"])


def test_gate_fails_on_cross_split_edge():
    idents = _corpus()
    v1 = _v1_assign(idents)
    _, doc, _, manifest = _gate_setup([EDGE])
    # a split that ignores the edge (the v1 split) with the v2 manifest metadata
    manifest = json.loads(json.dumps(manifest))
    for s in L.SPLITS:
        manifest[s] = [{"record_id": i["record_id"], **{k: i[k] for k in L.HARD_IDENTITIES}}
                       for i in idents if v1[i["record_id"]] == s]
    report = L.check_leakage(_split_identities(idents, v1), manifest, doc)
    assert report["status"] == "FAIL"
    assert report["near_duplicate"]["cross_split_edges"] == 1
    assert any("cross splits" in p and "near_duplicate edge" in p for p in report["problems"])
    assert any("not reproducible" in p for p in report["problems"])


def test_gate_fails_on_inconsistent_edge_list():
    idents, doc, assignment, manifest = _gate_setup([EDGE])
    recomputed = _edge_doc(EDGE, (("beta", "beta_m1"), ("gamma", "gamma_m2")))
    report = L.check_leakage(_split_identities(idents, assignment), manifest, recomputed)
    assert report["status"] == "FAIL"
    assert any("near_duplicate edges inconsistent" in p for p in report["problems"])
    assert report["near_duplicate"]["edge_status"] == "inconsistent"


def test_gate_fails_on_split_schema_1():
    idents, doc, assignment, manifest = _gate_setup([EDGE])
    manifest["split_schema_version"] = 1
    report = L.check_leakage(_split_identities(idents, assignment), manifest, doc)
    assert report["status"] == "FAIL"
    assert any("split_schema_version mismatch" in p for p in report["problems"])


def test_gate_fails_on_missing_near_duplicate_block():
    idents, doc, assignment, manifest = _gate_setup([EDGE])
    del manifest["near_duplicate"]
    report = L.check_leakage(_split_identities(idents, assignment), manifest, doc)
    assert report["status"] == "FAIL"
    assert any("near_duplicate block missing" in p for p in report["problems"])


def test_gate_fails_on_determinism_mismatch():
    idents, doc, assignment, manifest = _gate_setup([])
    moved = dict(assignment)
    rid = _rid(idents, "alpha", "alpha_m0")
    moved[rid] = "test" if moved[rid] != "test" else "validation"
    for s in L.SPLITS:
        manifest[s] = [{"record_id": i["record_id"], **{k: i[k] for k in L.HARD_IDENTITIES}}
                       for i in idents if moved[i["record_id"]] == s]
    report = L.check_leakage(_split_identities(idents, moved), manifest, doc)
    assert report["status"] == "FAIL"
    assert report["determinism_status"].startswith("differs")


def test_gate_fails_on_edge_to_unknown_module():
    idents, doc, assignment, manifest = _gate_setup([EDGE])
    doc = _edge_doc(EDGE, (("alpha", "alpha_m0"), ("zeta", "ghost")))
    manifest["near_duplicate"] = doc
    report = L.check_leakage(_split_identities(idents, assignment), manifest, doc)
    assert report["status"] == "FAIL"
    assert any("modules without records" in p for p in report["problems"])


# -----------------------------------------------------------------------------
# Tiny data repository (AC-009 / AC-045, AC-046, AC-024, AC-042)
# -----------------------------------------------------------------------------

LIB = "module lib_buf (input a, output y); assign y = a; endmodule\nmodule lib_inv (input a, output y); assign y = ~a; endmodule\n"
BODIES = {
    "ipa": "input [3:0] a, input [3:0] b, output [3:0] y); assign y = (a & b) | (a ^ {3'b0, b[0]});",
    "ipb": "input clk, input en, output reg [7:0] q); always @(posedge clk) if (en) q <= q + 8'd1;",
    "ipc": "input [1:0] s, input [7:0] d0, input [7:0] d1, output [7:0] y); assign y = s[0] ? d1 : (s[1] ? ~d0 : 8'hff);",
    "ipd": "input clk, input rst, input din, output reg [15:0] sr); always @(posedge clk) if (rst) sr <= 16'h0; "
           "else sr <= {sr[14:0], din};",
}
TX = """module {n} (input clk, input rst_n, input [7:0] din, input load, output reg [7:0] dout, output reg busy);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin dout <= 8'h00; busy <= 1'b0; end
    else if (load) begin dout <= din{x}; busy <= 1'b1; end
    else busy <= 1'b0;
endmodule
"""


def _make_data_root(base):
    root = base / "kritva-forge-data"
    original = root / "raw" / "rtl" / "original"
    (original / "common").mkdir(parents=True)
    (original / "common" / "lib.sv").write_text(LIB)
    for name, n in (("ipa", 6), ("ipb", 4), ("ipc", 3), ("ipd", 2)):
        (original / name).mkdir()
        (original / name / f"{name}.sv").write_text("".join(f"module {name}_m{i} ({BODIES[name]} endmodule\n"
                                                            for i in range(n)))
        files = [f"{name}.sv"]
        if name in ("ipc", "ipd"):                     # renamed copies, not body_shape-identical
            (original / name / f"{name}_tx.sv").write_text(TX.format(n=f"{name}_tx", x="" if name == "ipc" else " ^ 8'h5a"))
            files.append(f"{name}_tx.sv")
        (original / name / "files.f").write_text("\n".join(files + ["../common/lib.sv"]) + "\n")
    return root


def _run(root):
    from scripts.pipeline.run_pipeline import run_pipeline

    data = ForgeDataPaths.from_root(root)
    run_pipeline(str(data.raw_rtl / "original"), str(data.normalized_ir), data_root=str(root),
                 prompt_root=str(data.prompts), reports_root=str(data.reports),
                 datasets_root=str(data.pipeline_datasets))
    return data


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("splitv2")))


@pytest.fixture
def scratch(corpus, tmp_path):
    dst = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(corpus.root, dst)
    return ForgeDataPaths.from_root(dst)


def test_pipeline_groups_near_duplicate_pair_that_v1_splits(corpus):
    manifest = json.loads((corpus.splits / "split_manifest.json").read_text())
    report = json.loads((corpus.reports / "split_leakage_report.json").read_text())
    assert manifest["split_schema_version"] == 2
    assert report["status"] == "PASS" and report["near_duplicate"]["cross_split_edges"] == 0
    pair = {"a": "ipc/ipc_tx", "b": "ipd/ipd_tx"}
    edge = next(e for e in manifest["near_duplicate"]["edges"] if {e["a"], e["b"]} == set(pair.values()))
    assert C.NEAR_DUPLICATE <= edge["similarity"] < 1.0

    si = L.load_split_identities(str(corpus.root))
    idents = [i for s in L.SPLITS for i in si[s]]
    v1 = _v1_assign(idents)
    assert v1[_rid(idents, "ipc", "ipc_tx")] != v1[_rid(idents, "ipd", "ipd_tx")]   # v1: crosses splits
    split_of = {e["module"]: s for s in L.SPLITS for e in manifest[s] if e["ip"] in ("ipc", "ipd")}
    assert split_of["ipc_tx"] == split_of["ipd_tx"] == "train"                    # v2: one shared group
    g = next(g for g in manifest["groups"] if "ipc_tx" in g["modules"])
    assert g["joined_by"] == ["near_duplicate"] and g["policy"] == "shared_library->train"
    assert all(manifest["counts"][s] > 0 for s in L.SPLITS)                       # not degenerate

    gate = L.check_leakage(si, manifest, ND.compute(corpus.root))
    assert gate["status"] == "PASS", gate["problems"]
    cls = json.loads((corpus.reports / "prompt_leakage_classification.json").read_text())
    assert cls["counts"]["near_duplicate"] == 0 and cls["kf_dq_013_entry"] == "open"


def test_near_duplicate_cli(corpus, capsys):
    assert ND.main(["--data-root", str(corpus.root)]) == 0
    assert "ipc/ipc_tx ~ ipd/ipd_tx" in capsys.readouterr().out
    assert L.main(["--data-root", str(corpus.root)]) == 0
    assert "near-dup edges" in capsys.readouterr().out


def test_fail_closed_missing_fingerprint_document(scratch):
    from scripts.prompt_v2.render import upstream_rel
    (scratch.root / upstream_rel("structural", "ipc", "ipc_tx")).unlink()
    with pytest.raises(ND.NearDuplicateError, match="missing"):
        ND.compute(scratch.root)
    assert L.main(["--data-root", str(scratch.root)]) == 1


def test_fail_closed_missing_source(scratch):
    (scratch.root / "raw/rtl/original/ipd/ipd_tx.sv").unlink()
    with pytest.raises(ND.NearDuplicateError, match="missing"):
        ND.compute(scratch.root)


def test_fail_closed_source_sha256_mismatch(scratch):
    path = scratch.root / "raw/rtl/original/ipd/ipd_tx.sv"
    path.write_text(path.read_text() + "// changed\n")
    with pytest.raises(ND.NearDuplicateError, match="sha256"):
        ND.compute(scratch.root)


def test_generate_datasets_refuses_without_data_root(corpus, tmp_path):
    from scripts.dataset.dataset_generator import generate_datasets

    yaml_root = tmp_path / "outside" / "ir"
    shutil.copytree(corpus.normalized_ir, yaml_root)
    with pytest.raises(ValueError, match="KF-DQ-013.0"):
        generate_datasets(str(yaml_root), str(tmp_path / "out"), prompt_root=str(corpus.prompts),
                          splits_root=str(tmp_path / "splits"), reports_root=str(tmp_path / "reports"))


def test_edges_and_assignment_independent_of_hash_seed(corpus):
    code = ("import json,sys; from scripts.dataset import leakage as L, near_duplicate as ND; "
            "d=ND.compute(sys.argv[1]); si=L.load_split_identities(sys.argv[1]); "
            "ids=[i for s in L.SPLITS for i in si[s]]; a,g=L.assign_splits(ids, ND.pairs(d)); "
            "print(json.dumps([d, sorted(a.items()), g], sort_keys=True))")
    outs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
        outs.append(subprocess.run([sys.executable, "-c", code, str(corpus.root)], cwd=ROOT, env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert outs[0] == outs[1]
