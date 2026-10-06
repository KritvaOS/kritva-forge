# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_validator.py
# Description : FSM Analysis v2 validator negative tests (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/fsm
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis v2 validator - negative tests (acceptance criteria section 21).

A valid reference document (two coupled FSMs, outputs and actions) and its
three upstream inputs are built once; each test corrupts a deep copy - or a
scratch data repository - and asserts the *intended* problem code.
``test_NNN_*`` map one-to-one to AC-159 .. AC-190; further tests cover the
remaining validator rules.  Everything fails closed.
"""

import copy
import json
import shutil

import pytest

from scripts.behavior import model as BM
from scripts.fsm import analyzer as A
from scripts.fsm import model as F
from scripts.fsm import validator as V
from scripts.semantic_ir import model as SM
from scripts.structural import model as TM
from tests.fsm.helpers import fsm_all, rejected, stage

SRC = """
module fx(input clk, input rst_n, input req, input go, output grant, output reg led);
  localparam [1:0] I = 2'd0, W = 2'd1, G = 2'd2;
  localparam OFF = 1'b0, ON = 1'b1;
  reg [1:0] a_st, a_nx;
  reg       b_st;
  always @(posedge clk or negedge rst_n) if (!rst_n) a_st <= I; else a_st <= a_nx;
  always @* begin
    a_nx = a_st; led = 1'b0;
    case (a_st)
      I: if (req) a_nx = W;
      W: begin led = 1'b1; a_nx = G; end
      G: a_nx = I;
      default: a_nx = I;
    endcase
  end
  always @(posedge clk or negedge rst_n)
    if (!rst_n) b_st <= OFF;
    else case (b_st) OFF: if (a_st == G) b_st <= ON; ON: if (!go) b_st <= OFF; endcase
  assign grant = b_st;
endmodule
"""


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    doc, inputs = fsm_all(SRC, tmp_path_factory.mktemp("fsm"))["fx"]
    return doc, inputs


@pytest.fixture
def ref(reference):
    return copy.deepcopy(reference)


def problems(doc, inputs):
    return V.validate_module(doc, *inputs)


def fails(doc, inputs, code):
    got = problems(doc, inputs)
    assert got, "validation unexpectedly passed"
    assert code in {c for c, _ in got}, got[:6]


def fa(doc, reg="a_st"):
    return next(f for f in doc["fsms"] if f["register"]["name"] == reg)


@pytest.fixture
def corpus(tmp_path):
    return stage(SRC, tmp_path)


def _rel(*parts):
    return "/".join(parts)


def test_reference_is_valid(reference):
    doc, inputs = reference
    assert problems(doc, inputs) == []
    assert doc["counts"]["fsms"] == 2 and doc["counts"]["confirmed"] == 2 and doc["counts"]["couplings"] == 1
    assert fa(doc)["actions"] and fa(doc)["outputs"]


# ============================================================================= AC-159 .. AC-190

def test_159_malformed_json(corpus):
    path = corpus / A.fsm_rel("fx", "fx")
    path.write_text("{not json", encoding="utf-8")
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("schema") == 1
    assert V.validate_module("not a document") == [("schema", "document is not a JSON object")]


def test_160_missing_schema(ref):
    doc, inputs = ref
    del doc["schema"]
    fails(doc, inputs, "schema")


def test_161_unsupported_schema_version(ref):
    doc, inputs = ref
    doc["schema"]["version"] = 1                                    # FSM Analysis v1 is obsolete (KF-DQ-011.1)
    fails(doc, inputs, "schema")
    doc, inputs = copy.deepcopy(ref)
    doc["schema"]["version"] = 3
    fails(doc, inputs, "schema")


def test_162_invalid_analyzer_version(ref):
    doc, inputs = ref
    doc["versions"]["analyzer"] = 7
    fails(doc, inputs, "schema")
    doc, inputs = copy.deepcopy(ref)
    doc["generator"]["analyzer"] = "legacy fsm_extractor"
    fails(doc, inputs, "schema")


def test_163_invalid_fsm_identity(ref):
    doc, inputs = ref
    fa(doc)["id"] = "fsm1:XYZ"
    fails(doc, inputs, "identity")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["id"] = F.fsm_id("fsm", "beh1:0000000000000000")      # well formed, not derivable
    fails(doc, inputs, "identity")


def test_164_duplicate_fsm_identity(ref):
    doc, inputs = ref
    doc["fsms"].append(copy.deepcopy(doc["fsms"][0]))
    fails(doc, inputs, "duplicate_identity")


def test_165_duplicate_state_identity(ref):
    doc, inputs = ref
    f = fa(doc)
    f["states"].append(copy.deepcopy(f["states"][-1]))
    fails(doc, inputs, "duplicate_identity")


def test_166_duplicate_transition_identity(ref):
    doc, inputs = ref
    f = fa(doc)
    f["transitions"].append(copy.deepcopy(f["transitions"][-1]))
    fails(doc, inputs, "duplicate_identity")


def test_167_broken_state_reference(ref):
    doc, inputs = ref
    t = next(t for t in fa(doc)["transitions"] if t["kind"] == "explicit")
    t["target"] = F.fsm_id("state", "nowhere", "9")
    fails(doc, inputs, "state_reference")


def test_168_broken_predicate_reference(ref):
    doc, inputs = ref
    g = next(g for t in fa(doc)["transitions"] for g in t["guard"] if g["predicate"])
    g["predicate"] = "str1:0000000000000000"
    fails(doc, inputs, "structural_reference")


def test_169_broken_provenance(ref):
    doc, inputs = ref
    t = next(t for t in fa(doc)["transitions"] if t["kind"] == "explicit")
    t["assignment"] = "sem1:0000000000000000"
    fails(doc, inputs, "semantic_reference")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["states"][0]["loc"] = None
    fails(doc, inputs, "provenance")


def test_170_absolute_provenance_path(ref):
    doc, inputs = ref
    doc["module"]["structural"]["path"] = "/home/user/kritva-forge-data/normalized/structural/v1/fx/fx.json"
    fails(doc, inputs, "absolute_path")


def test_171_path_traversal(ref):
    doc, inputs = ref
    fa(doc)["loc"]["file"] = "raw/rtl/original/../../etc/fx.sv"
    fails(doc, inputs, "path_traversal")


def test_172_invalid_encoding(ref):
    doc, inputs = ref
    fa(doc)["encoding"]["style"] = "one_hot"                        # values are 0, 1, 2
    fails(doc, inputs, "encoding")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["encoding"]["status"] = "inferred"                      # all states are named constants
    fails(doc, inputs, "encoding")


def test_173_invalid_transition(ref):
    doc, inputs = ref
    t = next(t for t in fa(doc)["transitions"] if t["kind"] == "explicit")
    t["kind"] = "reset"                                            # reset kind without the *reset source
    fails(doc, inputs, "consistency")
    doc, inputs = copy.deepcopy(ref)
    t = next(t for t in fa(doc)["transitions"] if t["kind"] == "explicit")
    t["target"] = "*reset"                                         # pseudo state as target
    fails(doc, inputs, "consistency")


def test_174_invalid_state_set(ref):
    doc, inputs = ref
    f = fa(doc)
    f["states"][1]["value"] = f["states"][0]["value"]              # two states with one value
    fails(doc, inputs, "consistency")
    doc, inputs = copy.deepcopy(ref)
    s = fa(doc)["states"][2]
    s["reachability"] = "graph_unreachable"                        # contradicts the graph closure
    fails(doc, inputs, "consistency")


def test_175_fabricated_fsm(ref):
    doc, inputs = ref
    f = fa(doc)
    f["evidence"] = [{"code": "name_hint", "count": 1, "refs": [f["register"]["signal"]]}]
    fails(doc, inputs, "naming")


def test_176_name_only_state_register(tmp_path):
    src = "module fx(input clk, input [1:0] d, output reg [1:0] state); always @(posedge clk) state <= d; endmodule\n"
    doc = fsm_all(src, tmp_path)["fx"][0]
    assert doc["fsms"] == [] and rejected(doc) == [("state", "name_only")]


def test_177_name_only_next_state(tmp_path, ref):
    src = """module fx(input clk, input a, output reg q);
  reg next_state;
  always @* next_state = a;
  always @(posedge clk) q <= next_state;
endmodule
"""
    doc = fsm_all(src, tmp_path)["fx"][0]
    assert doc["fsms"] == []
    doc, inputs = ref                                              # identification evidence removed
    f = fa(doc)
    f["evidence"] = [e for e in f["evidence"] if e["code"] not in ("behavior_state_candidate", "predicate_over_register")]
    fails(doc, inputs, "evidence")


def test_178_counter_false_positive(tmp_path, ref):
    src = """module fx(input clk, input rst_n, input clr, output reg [3:0] c);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) c <= 4'd0; else if (clr) c <= 4'd5; else if (c == 4'd9) c <= 4'd0; else c <= c + 4'd1;
endmodule
"""
    doc = fsm_all(src, tmp_path)["fx"][0]
    assert doc["fsms"] == [] and rejected(doc) == [("c", "arithmetic_feedback")]
    doc, inputs = ref                                              # confirmed without two resolved values
    f = fa(doc)
    f["evidence"] = [e for e in f["evidence"] if e["code"] != "resolved_state_values"]
    fails(doc, inputs, "evidence")


@pytest.mark.parametrize("which,sub,code", [
    ("semantic", SM.OUTPUT_DIR, "semantic_input"),                # AC-179
    ("behavior", BM.OUTPUT_DIR, "behavior_input"),                # AC-180
    ("structural", TM.OUTPUT_DIR, "structural_input"),            # AC-181
])
def test_179_180_181_missing_upstream(corpus, which, sub, code):
    (corpus / sub / "fx" / "fx.json").unlink()
    with pytest.raises(A.AnalysisError, match="missing"):
        A.build(corpus, "fx", "fx")
    with pytest.raises(A.AnalysisError):
        A.write_all(corpus)
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get(code) == 1


def test_182_stale_upstream_evidence(corpus):
    path = corpus / TM.OUTPUT_DIR / "fx" / "fx.json"
    st = json.loads(path.read_text())
    st["notes"]["edited"] = 1                                       # structural document changed after FSM analysis
    path.write_text(TM.dumps(st))
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and "structural_consistency" in rep["problem_counts"]


def test_183_tampered_upstream_evidence(corpus):
    path = corpus / SM.OUTPUT_DIR / "fx" / "fx.json"
    sem = json.loads(path.read_text())
    sem["module"]["loc"]["column"] += 1
    path.write_text(SM.dumps(sem))
    with pytest.raises(A.AnalysisError, match="different Semantic IR"):
        A.build(corpus, "fx", "fx")                                 # behavior / structure no longer match it
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and "stale" in rep["problem_counts"]


def test_184_semantic_dependency_mismatch(ref):
    doc, inputs = ref
    doc["module"]["semantic_ir"]["sha256"] = "0" * 64
    fails(doc, inputs, "semantic_consistency")


def test_185_behavioral_dependency_mismatch(ref):
    doc, inputs = ref
    doc["module"]["behavior"]["sha256"] = "1" * 64
    fails(doc, inputs, "behavior_consistency")


def test_186_structural_dependency_mismatch(ref):
    doc, inputs = ref
    doc["module"]["structural"]["structural_id"] = "str1:0000000000000000"
    fails(doc, inputs, "structural_consistency")


def test_187_missing_fsm_artifact(corpus):
    (corpus / A.fsm_rel("fx", "fx")).unlink()
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and rep["problem_counts"] == {"inventory": 1}


def test_188_stray_fsm_artifact(corpus):
    shutil.copy(corpus / A.fsm_rel("fx", "fx"), corpus / A.fsm_rel("fx", "ghost"))
    (corpus / F.OUTPUT_DIR / "fx" / "notes.txt").write_text("x\n")
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and rep["problem_counts"] == {"inventory": 2}


def test_189_nondeterministic_output(corpus):
    path = corpus / A.fsm_rel("fx", "fx")
    first = path.read_bytes()
    A.write_all(corpus)
    assert path.read_bytes() == first                               # equivalent runs are byte-identical
    path.write_text(json.dumps(json.loads(first), indent=1))       # same content, other bytes
    rep = V.check(corpus)
    assert rep["status"] == "FAIL" and "nondeterministic" in rep["problem_counts"]


def test_190_unsupported_construct(tmp_path):
    src = """module fx(input clk, input rst_n, input a, output reg [1:0] st);
  function [1:0] nxt(input [1:0] s, input x); nxt = x ? s + 2'd1 : s; endfunction
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= 2'd0;
    else case (st) 2'd0: st <= nxt(st, a); 2'd1: st <= 2'd2; default: st <= 2'd0; endcase
endmodule
"""
    doc, inputs = fsm_all(src, tmp_path)["fx"]
    (f,) = doc["fsms"]
    assert (f["status"], f["quality"]) == ("unsupported", "unsupported")
    f["status"], f["quality"] = "confirmed", "unsupported"          # silently promoted
    fails(doc, inputs, "consistency")


# ============================================================================= further validator rules

def test_counts_fingerprint_and_document_identity(ref):
    doc, inputs = ref
    doc["counts"]["states"] += 1
    fails(doc, inputs, "consistency")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["fingerprint"] = F.fsm_id("x", "y")
    fails(doc, inputs, "identity")
    doc, inputs = copy.deepcopy(ref)
    doc["notes"]["anonymous_enum_registers"] = 3                    # content changed, id not
    fails(doc, inputs, "identity")


def test_vocabulary_and_quality(ref):
    doc, inputs = ref
    fa(doc)["status"] = "probable"
    fails(doc, inputs, "enum")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["quality"] = "medium"                                  # high is implied by the evidence
    fails(doc, inputs, "consistency")


def test_ordering(ref):
    doc, inputs = ref
    f = fa(doc)
    f["transitions"].reverse()
    fails(doc, inputs, "ordering")
    doc, inputs = copy.deepcopy(ref)
    fa(doc)["states"].reverse()
    fails(doc, inputs, "ordering")


def test_coupling_references(ref):
    doc, inputs = ref
    doc["couplings"][0]["to_fsm"] = doc["couplings"][0]["from_fsm"]
    fails(doc, inputs, "broken_reference")


def test_output_and_action_references(ref):
    doc, inputs = ref
    o = fa(doc, "b_st")["outputs"][0]
    o["kind"] = "mealy"                                             # grant = b_st has no input source
    fails(doc, inputs, "consistency")
    doc, inputs = copy.deepcopy(ref)
    a = fa(doc)["actions"][0]
    a["state"] = F.fsm_id("state", "nowhere", "7")
    fails(doc, inputs, "state_reference")


def test_guard_values_must_be_states(ref):
    doc, inputs = ref
    g = next(g for t in fa(doc)["transitions"] for g in t["guard"] if g["values"])
    g["values"] = [F.fsm_id("state", "nowhere", "5")]
    fails(doc, inputs, "state_reference")


def test_register_must_be_behavioral(ref):
    doc, inputs = ref
    fa(doc)["register"]["register"] = "beh1:0000000000000000"
    fails(doc, inputs, "behavior_reference")


def test_reset_state_consistency(ref):
    doc, inputs = ref
    f = fa(doc)
    f["reset"]["state"] = f["states"][1]["id"]
    fails(doc, inputs, "consistency")


def test_corpus_check_passes_and_reports(corpus):
    rep = V.check(corpus)
    assert rep["status"] == "PASS", rep["problems"]
    assert rep["documents"] == rep["canonical_modules"] == 1 and rep["totals"]["fsms"] == 2
    assert rep["provenance"]["valid"] == rep["provenance"]["objects"] > 0
    assert rep["leakage"]["status"] == "SKIPPED"                    # no split manifest in a scratch repository
    assert "FSM Analysis check: PASS" in V.format_report(rep)
    path = V.write_report(corpus, rep)
    assert json.loads(path.read_text())["corpus_sha256"] == V.corpus_sha256(corpus)
