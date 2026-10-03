# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_behavior_validator.py
# Description : KF-DQ-009 Behavioral Semantics validation and negative tests
#
# Component   : Kritva Forge
# Module      : tests/behavior
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 validator (acceptance criteria sections 30 and 31).

A valid reference document (with its Semantic IR) is built once; each
negative test corrupts a deep copy and asserts the *intended* problem code.
``test_NN_*`` map one-to-one to the eighteen required negative cases.
"""

import copy
import json

import pytest

from scripts.behavior import analyzer as A
from scripts.behavior import model as B
from scripts.behavior import validator as V
from tests.behavior.helpers import behave

SRC = """
module fx(input clk, input rst_n, input en, input [1:0] sel, input [3:0] d, output reg [3:0] q,
          output reg [1:0] st, output logic [3:0] y);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 4'd0;
    else if (en) q <= d;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= 2'd0;
    else case (st)
      2'd0: st <= 2'd1;
      2'd1: st <= 2'd2;
      default: st <= 2'd0;
    endcase
  always_comb y = q ^ d;
endmodule
"""


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    return behave(SRC, tmp_path_factory.mktemp("beh"))


@pytest.fixture
def pair(reference):
    return copy.deepcopy(reference)


def fails(doc, sem, code):
    got = V.validate_module(doc, sem)
    assert got, "validation unexpectedly passed"
    assert code in {c for c, _ in got}, got[:5]


def seq(doc):
    return next(p for p in doc["processes"] if p["role"] == "sequential")


def test_reference_is_valid(reference):
    doc, sem = reference
    assert V.validate_module(doc, sem) == []
    assert doc["schema"] == {"name": "kritva-forge-behavioral-semantics", "version": 1}
    assert doc["counts"]["state_candidates"] == 1 and doc["counts"]["enables"] == 1


# ----------------------------------------------------------------------------- 1 / 2 (input)

def test_01_missing_semantic_ir_input(tmp_path):
    with pytest.raises(A.AnalysisError, match="missing Semantic IR input"):
        A.build(tmp_path, "fx", "nothing")


def test_02_unsupported_semantic_ir_version(pair):
    doc, sem = pair
    old = copy.deepcopy(sem)
    old["schema"]["version"] = 1
    with pytest.raises(A.AnalysisError, match="unsupported Semantic IR schema"):
        A.analyze(old, "x", "0" * 64)
    old = copy.deepcopy(sem)
    old["versions"]["identity"] = 9
    with pytest.raises(A.AnalysisError, match="identity version"):
        A.analyze(old, "x", "0" * 64)
    doc["versions"]["semantic_ir"] = 1
    fails(doc, sem, "schema")


# ----------------------------------------------------------------------------- 3 .. 18

def test_03_broken_process_reference(pair):
    doc, sem = pair
    doc["processes"][0]["process"] = "sem1:" + "0" * 16
    fails(doc, sem, "broken_reference")
    d2, s2 = copy.deepcopy(pair)
    d2["registers"][0]["process"] = B.behavior_id("process", "nowhere")
    fails(d2, s2, "broken_reference")


def test_04_broken_assignment_reference(pair):
    doc, sem = pair
    doc["registers"][0]["assignments"][0]["assignment"] = "sem1:" + "1" * 16
    fails(doc, sem, "broken_reference")
    d2, s2 = copy.deepcopy(pair)
    d2["next_values"][0]["assignment"] = "sem1:" + "1" * 16
    fails(d2, s2, "broken_reference")


def test_05_invalid_event_representation(pair):
    doc, sem = pair
    doc["clocks"][0]["event"] = 7
    fails(doc, sem, "event")
    d2, s2 = copy.deepcopy(pair)
    d2["clocks"][0]["edge"] = "negedge"                       # the event is a posedge
    fails(d2, s2, "event")


def test_06_invalid_clock_identity(pair):
    doc, sem = pair
    rst = next(p for p in sem["ports"] if p["name"] == "rst_n")
    doc["clocks"][0]["signal"] = rst["id"]                    # a real port, but not the clock event
    fails(doc, sem, "clock")


def test_07_invalid_reset_identity(pair):
    doc, sem = pair
    en = next(p for p in sem["ports"] if p["name"] == "en")
    doc["resets"][0]["signal"] = en["id"]
    fails(doc, sem, "reset")
    d2, s2 = copy.deepcopy(pair)
    d2["resets"][0]["polarity"] = "active_high"               # !rst_n is active low
    fails(d2, s2, "reset")


def test_08_conflicting_process_role_evidence(pair):
    doc, sem = pair
    c = next(p for p in doc["processes"] if p["kind"] == "always_comb")
    c["role"] = "sequential"
    fails(doc, sem, "role_conflict")
    d2, s2 = copy.deepcopy(pair)
    p = seq(d2)
    p["role"], p["evidence"] = "combinational", [e for e in p["evidence"] if e["code"] != "edge_event"]
    fails(d2, s2, "role_conflict")
    d3, s3 = copy.deepcopy(pair)
    seq(d3)["confidence"] = "high"                            # generic always cannot be high
    fails(d3, s3, "role_conflict")


def test_09_invalid_behavioral_identity(pair):
    doc, sem = pair
    doc["registers"][0]["id"] = "beh1:XYZ"
    fails(doc, sem, "identity")
    d2, s2 = copy.deepcopy(pair)
    d2["versions"]["identity"] = 2
    fails(d2, s2, "identity")


def test_10_duplicate_behavioral_identity(pair):
    doc, sem = pair
    doc["holds"][0]["id"] = doc["registers"][0]["id"]
    fails(doc, sem, "duplicate_identity")


def test_11_missing_behavioral_provenance(pair):
    doc, sem = pair
    del doc["registers"][0]["loc"]
    fails(doc, sem, "provenance")
    d2, s2 = copy.deepcopy(pair)
    del d2["module"]["semantic_ir"]
    fails(d2, s2, "provenance")


def test_12_absolute_provenance_path(pair):
    doc, sem = pair
    doc["clocks"][0]["loc"]["file"] = "/home/user/rtl/fx.sv"
    fails(doc, sem, "absolute_path")
    d2, s2 = copy.deepcopy(pair)
    d2["module"]["semantic_ir"]["path"] = "C:/data/fx.json"
    fails(d2, s2, "absolute_path")


def test_13_nondeterministic_ordering(pair):
    doc, sem = pair
    doc["registers"].reverse()
    fails(doc, sem, "ordering")


def test_14_missing_evidence_for_classification(pair):
    doc, sem = pair
    seq(doc)["evidence"] = []
    fails(doc, sem, "evidence")
    d2, s2 = copy.deepcopy(pair)
    st = next(c for c in d2["candidates"] if c["kind"] == "state_candidate")
    st["evidence"] = [e for e in st["evidence"] if e["code"] != "selector_feedback"]
    fails(d2, s2, "evidence")


def test_15_naming_only_classification(pair):
    doc, sem = pair
    r = doc["resets"][0]
    r["evidence"] = [{"code": "name_hint", "refs": [r["signal"]]}]
    fails(doc, sem, "naming")
    assert "reset" in {c for c, _ in V.validate_module(doc, sem)}     # and the confirmed status is unsupported


def test_16_invalid_enable_hold_relationship(pair):
    doc, sem = pair
    doc["enables"][0]["hold_branch"] = doc["enables"][0]["update_branch"]
    fails(doc, sem, "enable_hold")
    d2, s2 = copy.deepcopy(pair)
    q = next(r for r in d2["registers"] if r["name"] == "q")
    q["hold"] = "explicit"                                    # q only has an implicit hold
    fails(d2, s2, "enable_hold")
    d3, s3 = copy.deepcopy(pair)
    h = d3["holds"][0]
    h["kind"], h["assignment"] = "explicit", d3["next_values"][0]["assignment"]      # not a self-assignment
    fails(d3, s3, "enable_hold")


def test_17_invalid_reset_update_priority(pair):
    doc, sem = pair
    q = next(r for r in doc["registers"] if r["name"] == "q")
    q["priority"][0], q["priority"][1] = q["priority"][1], q["priority"][0]
    for i, x in enumerate(q["priority"]):
        x["rank"] = i
    fails(doc, sem, "priority")
    d2, s2 = copy.deepcopy(pair)
    next(r for r in d2["registers"] if r["name"] == "q")["priority"][0]["rank"] = 5
    fails(d2, s2, "priority")


def test_18_output_inconsistent_with_semantic_ir(pair):
    doc, sem = pair
    sem2 = copy.deepcopy(sem)
    sem2["processes"] = sem2["processes"][:-1]               # Semantic IR has one process fewer
    sem2["assignments"] = [a for a in sem2["assignments"] if a["process"] != sem["processes"][-1]["id"]]
    fails(doc, sem2, "semantic_consistency")
    got = V.validate_module(doc, sem, semantic_sha256="f" * 64)
    assert "semantic_consistency" in {c for c, _ in got}
    d3, s3 = copy.deepcopy(pair)
    d3["module"]["module_id"] = "mod1:" + "0" * 16
    fails(d3, s3, "semantic_consistency")


# ----------------------------------------------------------------------------- schema details

def test_enumerations_and_counts(pair):
    doc, sem = pair
    doc["processes"][0]["confidence"] = "certain"
    doc["registers"][0]["hold"] = "sticky"
    got = {c for c, _ in V.validate_module(doc, sem)}
    assert "enum" in got
    d2, s2 = copy.deepcopy(pair)
    d2["counts"]["registers"] += 1
    fails(d2, s2, "consistency")


def test_register_in_combinational_process_is_inconsistent(pair):
    doc, sem = pair
    comb = next(p for p in doc["processes"] if p["role"] == "combinational")
    doc["registers"][0]["process"] = comb["id"]
    fails(doc, sem, "consistency")


# ----------------------------------------------------------------------------- corpus

def _corpus(tmp_path):
    from tests.semantic_ir.helpers import extract

    extract(SRC, tmp_path)
    root = tmp_path / "kritva-forge-data"
    p = root / "normalized" / "ir" / "fx" / "modules" / "fx.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("name: fx\n")
    A.write_all(root)
    return root


def test_corpus_check_and_cli(tmp_path, capsys):
    root = _corpus(tmp_path)
    assert V.main(["--check", "--data-root", str(root), "--write-report"]) == 0
    assert "Behavioral Semantics v1 check: PASS" in capsys.readouterr().out
    rep = json.loads((root / B.REPORT_PATH).read_text())
    assert rep["documents"] == 1 and rep["totals"]["registers"] == 2 and str(root) not in json.dumps(rep)


def test_corpus_detects_stale_and_missing_input(tmp_path):
    root = _corpus(tmp_path)
    sem_path = root / A.semantic_rel("fx", "fx")
    sem = json.loads(sem_path.read_text())
    sem["processes"][0]["loc"]["column"] += 1                 # any Semantic IR change
    from scripts.semantic_ir import model as SM
    sem_path.write_text(SM.dumps(sem))
    pc = V.check(root)["problem_counts"]
    assert pc.get("stale") and pc.get("semantic_consistency")
    sem_path.unlink()
    pc = V.check(root)["problem_counts"]
    assert pc.get("semantic_input")
    with pytest.raises(A.AnalysisError):
        A.write_all(root)


def test_corpus_detects_inventory_and_bytes(tmp_path):
    root = _corpus(tmp_path)
    beh = root / A.behavior_rel("fx", "fx")
    beh.write_text(json.dumps(json.loads(beh.read_text()), indent=2))
    (beh.parent / "ghost.json").write_text("{}\n")
    pc = V.check(root)["problem_counts"]
    assert pc.get("nondeterministic") and pc.get("inventory")
