# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_structural_validator.py
# Description : KF-DQ-010 Structural Analysis validation and negative tests (AC-041, AC-046)
#
# Component   : Kritva Forge
# Module      : tests/structural
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural Analysis v1 validator (acceptance criteria sections 15 and 17).

A valid reference document (with its Semantic IR and Behavioral Semantics) is
built once; each negative test corrupts a deep copy - or a scratch data
repository - and asserts the *intended* problem code.  ``test_NN_*`` map
one-to-one to the eighteen required negative cases; all fail closed.
"""

import copy
import hashlib
import json

import pytest

from scripts.behavior import model as BM
from scripts.semantic_ir import model as SM
from scripts.structural import analyzer as A
from scripts.structural import model as T
from scripts.structural import validator as V
from tests.structural.helpers import stage, structure_all

SRC = """
module child(input i, output o); assign o = ~i; endmodule
module fx(input clk, input rst_n, input en, input [1:0] sel, input [3:0] d, output reg [3:0] q,
          output logic [3:0] y, output z);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 4'd0;
    else if (en) q <= d;
  always_comb case (sel) 2'd0: y = q; default: y = d; endcase
  child u0 (.i(en), .o(z));
endmodule
"""


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    return structure_all(SRC, tmp_path_factory.mktemp("str"))["fx"]


@pytest.fixture
def trio(reference):
    return copy.deepcopy(reference)


def codes(doc, sem, beh):
    return {c for c, _ in V.validate_module(doc, sem, beh)}


def fails(doc, sem, beh, code):
    got = V.validate_module(doc, sem, beh)
    assert got, "validation unexpectedly passed"
    assert code in {c for c, _ in got}, got[:5]


@pytest.fixture
def corpus(tmp_path):
    return stage(SRC, tmp_path)


def test_reference_is_valid(reference):
    doc, sem, beh = reference
    assert V.validate_module(doc, sem, beh) == []
    assert doc["schema"] == {"name": "kritva-forge-structural-analysis", "version": 1}
    assert doc["counts"]["registers"] == 1 and doc["counts"]["instances"] == 1


# ----------------------------------------------------------------------------- 1 - 5
def test_01_malformed_json(corpus):
    path = corpus / A.structural_rel("fx", "fx")
    path.write_text('{"schema": ', encoding="utf-8")
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("schema")
    assert V.validate_module("not a document") == [("schema", "document is not a JSON object")]


def test_02_unsupported_schema_version(trio):
    doc, sem, beh = trio
    doc["schema"]["version"] = 2
    fails(doc, sem, beh, "schema")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["versions"]["analyzer"] = 9
    fails(d2, s2, b2, "schema")
    old = copy.deepcopy(sem)
    old["schema"]["version"] = 1
    with pytest.raises(A.AnalysisError, match="unsupported Semantic IR schema"):
        A.analyze(old, "x", "0" * 64, beh, "y", "0" * 64)


def test_03_invalid_identity(trio):
    doc, sem, beh = trio
    doc["signals"][0]["id"] = "str1:XYZ"
    fails(doc, sem, beh, "identity")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["dependencies"][0]["kind"] = "data" if d2["dependencies"][0]["kind"] != "data" else "control"
    fails(d2, s2, b2, "identity")                               # id no longer derives from its anchor
    d3, s3, b3 = copy.deepcopy(trio)
    d3["id"] = T.struct_id("document", "", "other")
    fails(d3, s3, b3, "identity")                               # not the content hash


def test_04_duplicate_identity(trio):
    doc, sem, beh = trio
    doc["loads"][1]["id"] = doc["loads"][0]["id"]
    fails(doc, sem, beh, "duplicate_identity")


def test_05_duplicate_edge(trio):
    doc, sem, beh = trio
    e = copy.deepcopy(doc["dependencies"][0])
    e["id"] = "str1:ffffffffffffffff"
    doc["dependencies"].append(e)
    fails(doc, sem, beh, "duplicate_edge")


# ----------------------------------------------------------------------------- 6 - 12
def test_06_broken_semantic_ir_reference(trio):
    doc, sem, beh = trio
    a = next(x for x in doc["assignments"] if x["guards"])
    a["guards"] = [{"statement": "sem1:0000000000000000", "branch": "then"}]
    fails(doc, sem, beh, "semantic_reference")


def test_07_broken_behavioral_reference(trio):
    doc, sem, beh = trio
    doc["registers"][0]["clock"]["clock"] = "beh1:0000000000000000"
    fails(doc, sem, beh, "behavior_reference")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["processes"][0]["behavior"] = "beh1:0000000000000000"
    fails(d2, s2, b2, "behavior_reference")


def test_08_broken_provenance(trio):
    doc, sem, beh = trio
    del doc["dependencies"][0]["loc"]["line"]
    fails(doc, sem, beh, "provenance")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["loads"][0]["loc"]["file"] = "/home/user/rtl/fx.sv"
    fails(d2, s2, b2, "absolute_path")
    d3, s3, b3 = copy.deepcopy(trio)
    e = next(x for x in d3["dependencies"] if x["kind"] == "data")
    e["assignments"], e["references"], e["behavior"] = [], [], []
    fails(d3, s3, b3, "provenance")
    d4, s4, b4 = copy.deepcopy(trio)
    d4["module"]["behavior"]["sha256"] = "x"
    fails(d4, s4, b4, "provenance")


def test_09_missing_source_object(corpus):
    (corpus / A.behavior_rel("fx", "fx")).unlink()
    rep = V.check(corpus)
    assert rep["problem_counts"].get("behavior_input")
    with pytest.raises(A.AnalysisError, match="missing Behavioral Semantics input"):
        A.build(corpus, "fx", "fx")
    (corpus / A.semantic_rel("fx", "child")).unlink()
    assert V.check(corpus)["problem_counts"].get("semantic_input")


def test_10_invalid_driver_reference(trio):
    doc, sem, beh = trio
    s = next(x for x in doc["signals"] if x["drivers"])
    s["drivers"] = sorted(s["drivers"] + ["str1:0000000000000000"])
    fails(doc, sem, beh, "driver_reference")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["drivers"][0]["connection"] = "str1:0000000000000000"
    fails(d2, s2, b2, "driver_reference")


def test_11_invalid_load_reference(trio):
    doc, sem, beh = trio
    ld = next(x for x in doc["loads"] if x["kind"] == "assignment_value")
    other = next(s["signal"] for s in doc["signals"] if s["signal"] != ld["signal"])
    ld["signal"] = other
    fails(doc, sem, beh, "load_reference")


def test_12_inconsistent_read_write_set(trio):
    doc, sem, beh = trio
    p = next(x for x in doc["processes"] if x["reads"])
    p["reads"] = p["reads"][:-1]
    fails(doc, sem, beh, "read_write")
    d2, s2, b2 = copy.deepcopy(trio)
    p = next(x for x in d2["processes"] if x["role"] == "sequential")
    p["role"], p["boundary"] = "combinational", "combinational"
    fails(d2, s2, b2, "role_conflict")                          # behavioral roles are never overridden


# ----------------------------------------------------------------------------- 13 - 18 (corpus)
def test_13_stale_artifact(corpus):
    path = corpus / A.structural_rel("fx", "fx")
    doc = json.loads(path.read_text())
    doc["notes"]["tampered"] = 1
    doc["id"] = T.document_id(doc)
    path.write_text(T.dumps(doc))
    assert V.check(corpus)["problem_counts"].get("stale")


def test_14_modified_semantic_ir(corpus):
    sp = corpus / A.semantic_rel("fx", "fx")
    sem = json.loads(sp.read_text())
    sem["module"]["loc"]["column"] += 1
    sp.write_text(SM.dumps(sem))
    pc = V.check(corpus)["problem_counts"]
    assert pc.get("semantic_consistency") and pc.get("stale")
    with pytest.raises(A.AnalysisError, match="different Semantic IR revision"):
        A.build(corpus, "fx", "fx")                             # behavior is stale too: refuse


def test_15_modified_behavioral_semantics(corpus):
    bp = corpus / A.behavior_rel("fx", "fx")
    beh = json.loads(bp.read_text())
    beh["registers"][0]["update"] = "ambiguous"
    bp.write_text(BM.dumps(beh))
    pc = V.check(corpus)["problem_counts"]
    assert pc.get("behavior_consistency") and pc.get("stale")


def test_16_missing_structural_artifact(corpus):
    (corpus / A.structural_rel("fx", "child")).unlink()
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and any("missing Structural Analysis v1 for fx/child" in p for p in rep["problems"])


def test_17_stray_structural_artifact(corpus):
    (corpus / T.OUTPUT_DIR / "fx" / "ghost.json").write_text("{}\n")
    (corpus / T.OUTPUT_DIR / "fx" / "notes.txt").write_text("x\n")
    rep = V.check(corpus)
    assert rep["problem_counts"].get("inventory") == 2


def test_18_nondeterministic_ordering_regression(trio, corpus):
    doc, sem, beh = trio
    doc["dependencies"].reverse()
    fails(doc, sem, beh, "ordering")
    d2, s2, b2 = copy.deepcopy(trio)
    p = next(x for x in d2["processes"] if len(x["reads"]) > 1)
    p["reads"].reverse()
    fails(d2, s2, b2, "ordering")
    path = corpus / A.structural_rel("fx", "fx")
    path.write_text(json.dumps(json.loads(path.read_text()), indent=2))
    assert V.check(corpus)["problem_counts"].get("nondeterministic")


# ----------------------------------------------------------------------------- other validator rules
def test_naming_only_classification(trio):
    doc, sem, beh = trio
    s = next(x for x in doc["signals"] if x["name"] == "en")
    c = next(x for x in s["classes"] if x["class"] == "enable")
    c["evidence"] = [{"code": "name_hint", "count": 1, "refs": [s["signal"]]}]
    fails(doc, sem, beh, "naming")


def test_relationship_consistency(trio):
    doc, sem, beh = trio
    e = next(x for x in doc["dependencies"] if x["kind"] == "clock")
    e["boundary"] = "combinational"
    fails(doc, sem, beh, "consistency")
    d2, s2, b2 = copy.deepcopy(trio)
    d2["counts"]["dependencies"] += 1
    fails(d2, s2, b2, "consistency")
    d3, s3, b3 = copy.deepcopy(trio)
    d3["instances"][0]["child"] = None
    fails(d3, s3, b3, "consistency")


def test_enumerations(trio):
    doc, sem, beh = trio
    doc["loads"][0]["kind"] = "telepathy"
    doc["dependencies"][0]["status"] = "certain"
    assert "enum" in codes(doc, sem, beh)


def test_semantic_and_behavior_sha(trio):
    doc, sem, beh = trio
    got = V.validate_module(doc, sem, beh, semantic_sha256="f" * 64, behavior_sha256="e" * 64)
    assert {"semantic_consistency", "behavior_consistency"} <= {c for c, _ in got}


def test_corpus_check_and_report(corpus, capsys):
    assert V.main(["--check", "--data-root", str(corpus), "--write-report"]) == 0
    out = capsys.readouterr().out
    assert "Structural Analysis v1 check: PASS" in out and "provenance coverage" in out
    rep = json.loads((corpus / T.REPORT_PATH).read_text())
    assert rep["documents"] == 2 and rep["provenance"]["missing"] == 0 and rep["provenance"]["invalid_references"] == 0
    assert rep["provenance"]["valid"] == rep["provenance"]["objects"] > 0 and str(corpus) not in json.dumps(rep)
    assert rep["corpus_sha256"] == V.corpus_sha256(corpus)
    h = hashlib.sha256()
    assert len(rep["corpus_sha256"]) == len(h.hexdigest())
