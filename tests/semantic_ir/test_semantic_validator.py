# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_semantic_validator.py
# Description : KF-DQ-008 schema validation and negative tests for Semantic IR v2
#
# Component   : Kritva Forge
# Module      : tests/semantic_ir
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 validator (acceptance criteria sections 13 and 17).

A valid reference document is extracted once.  Each negative test corrupts a
deep copy (or a scratch corpus) and asserts that validation fails with the
*intended* problem code; the untouched document stays clean.  Tests
``test_NN_*`` map one-to-one to the fifteen required negative cases.
"""

import copy
import json
import shutil

import pytest

from scripts.semantic_ir import model as M
from scripts.semantic_ir import validator as V
from tests.semantic_ir.helpers import extract, walk

SRC = """
module leaf(input a, output y); assign y = ~a; endmodule
module fx #(parameter W = 4) (input clk, input rst_n, input [W-1:0] d, input [1:0] s, output reg [W-1:0] q,
                              output y);
  wire n;
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) q <= '0;
    else case (s)
      2'd0: q <= d;
      default: q <= {d[W-2:0], d[W-1]};
    endcase
  assign n = d[0] & s[1];
  leaf u0 (.a(n), .y(y));
endmodule
"""


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    return extract(SRC, tmp_path_factory.mktemp("sem"))["fx"]


@pytest.fixture
def doc(reference):
    return copy.deepcopy(reference)


def fails(d, code):
    got = V.validate_module(d)
    assert got, "validation unexpectedly passed"
    assert code in {c for c, _ in got}, got[:5]
    return got


def first_ref(d):
    return next(n for n in walk(d["assignments"]) if n.get("op") == "ref")


def test_reference_document_is_valid(reference):
    assert V.validate_module(reference) == []
    assert reference["schema"] == {"name": "kritva-forge-semantic-ir", "version": 2}
    assert json.loads(M.dumps(reference)) == reference


# ----------------------------------------------------------------------------- per-document cases

def test_01_missing_source_provenance(doc):
    del doc["module"]["source"]
    fails(doc, "provenance")


def test_01b_missing_entity_location(doc):
    del doc["assignments"][0]["loc"]
    fails(doc, "provenance")


def test_02_absolute_source_path(doc):
    doc["module"]["source"]["path"] = "/home/user/rtl/fx.sv"
    fails(doc, "absolute_path")
    d2 = copy.deepcopy(doc)
    d2["module"]["source"]["path"] = "raw/rtl/original/fx/fx.sv"
    d2["references"][0]["loc"]["file"] = "C:/rtl/fx.sv"
    fails(d2, "absolute_path")


def test_03_path_traversal(doc):
    doc["signals"][0]["loc"]["file"] = "raw/rtl/../../etc/fx.sv"
    fails(doc, "path_traversal")


def test_04_missing_module_identity(doc):
    del doc["module"]["module_id"]
    fails(doc, "identity")


def test_06_duplicate_entity_identity(doc):
    doc["assignments"][1]["id"] = doc["assignments"][0]["id"]
    fails(doc, "duplicate_identity")


def test_06b_duplicate_reference_identity(doc):
    refs = [n for n in walk(doc["assignments"]) if n.get("op") == "ref"]
    refs[1]["id"] = refs[0]["id"]
    fails(doc, "duplicate_identity")


def test_06c_duplicate_declaration(doc):
    dup = copy.deepcopy(doc["signals"][0])
    dup["id"] = M.semantic_id("signal", "duplicate")
    doc["signals"].append(dup)
    fails(doc, "duplicate_declaration")


def test_07_unsupported_schema_version(doc):
    doc["schema"]["version"] = 1
    fails(doc, "schema")
    d2 = copy.deepcopy(doc)
    d2["schema"] = {"name": "kritva-forge-semantic-ir", "version": 2}
    d2["versions"]["schema"] = 3
    fails(d2, "schema")


def test_08_unsupported_identity_version(doc):
    doc["versions"]["identity"] = 2
    fails(doc, "identity_version")
    d2 = copy.deepcopy(doc)
    d2["versions"]["identity"] = 1
    d2["processes"][0]["id"] = "s2:" + "0" * 16                  # foreign identity namespace
    fails(d2, "identity")


def test_09_invalid_port_direction(doc):
    doc["ports"][0]["direction"] = "sideways"
    fails(doc, "direction")


def test_10_invalid_width(doc):
    doc["ports"][0]["width"] = 0
    fails(doc, "width")
    d2 = copy.deepcopy(doc)
    d2["ports"][0]["width"] = 1
    q = next(p for p in d2["ports"] if p["name"] == "q")
    q["width"] = 7                                                # [W-1:0] with W = 4 is 4 bits
    fails(d2, "width")


def test_11_malformed_expression(doc):
    doc["assignments"][0]["value"] = {"op": "frobnicate"}
    fails(doc, "expression")
    d2 = copy.deepcopy(doc)
    d2["assignments"][0]["value"] = None
    a = next(a for a in d2["assignments"] if a["value"] and a["value"]["op"] == "binary")
    del a["value"]["right"]
    fails(d2, "expression")


def test_12_malformed_assignment(doc):
    doc["assignments"][0]["target"] = None
    fails(doc, "assignment")
    d2 = copy.deepcopy(doc)
    d2["assignments"][0]["target"] = {"op": "literal", "text": "1", "value": 1}
    fails(d2, "assignment")
    d3 = copy.deepcopy(doc)
    nb = next(a for a in d3["assignments"] if a["kind"] == "nonblocking")
    nb["operator"] = "="
    fails(d3, "assignment")


def test_13_broken_symbol_reference(doc):
    first_ref(doc)["target"] = M.semantic_id("signal", "nowhere")
    fails(doc, "broken_reference")
    d2 = copy.deepcopy(doc)
    r = first_ref(d2)
    r["target"] = None                                           # resolvable kind without definition
    fails(d2, "broken_reference")


def test_13b_reference_index_disagrees(doc):
    doc["references"].pop()
    fails(doc, "broken_reference")


def test_13c_broken_guard_and_owner(doc):
    a = next(a for a in doc["assignments"] if a["guards"])
    a["guards"][0]["statement"] = M.semantic_id("stmt", "nowhere")
    fails(doc, "broken_reference")
    d2 = copy.deepcopy(doc)
    d2["assignments"][0]["process"] = M.semantic_id("process", "nowhere")
    fails(d2, "broken_reference")


def test_13d_malformed_case_index(doc):
    doc["cases"][0]["case_kind"] = "casey"
    fails(doc, "enum")
    d2 = copy.deepcopy(doc)
    d2["conditions"] = []
    fails(d2, "control")


def test_15_nondeterministic_entity_ordering(doc):
    doc["assignments"].reverse()
    fails(doc, "ordering")
    d2 = copy.deepcopy(doc)
    d2["assignments"].reverse()
    d2["references"].reverse()
    fails(d2, "ordering")


def test_silent_unsupported_loss(doc):
    doc["extraction"] = "partial"
    fails(doc, "silent_loss")


def test_unresolved_instance_with_target(doc):
    doc["instances"][0]["resolved"] = False
    fails(doc, "broken_instance")


def test_enumerations_are_enforced(doc):
    doc["assignments"][0]["kind"] = "magic"
    doc["processes"][0]["sensitivity"] = "psychic"
    got = V.validate_module(doc)
    assert sum(1 for c, _ in got if c == "enum") >= 2


# ----------------------------------------------------------------------------- corpus cases

def _corpus(tmp_path):
    """A data root whose canonical IR and Semantic IR agree (YAML stubs for the inventory)."""
    docs = extract(SRC, tmp_path)
    root = tmp_path / "kritva-forge-data"
    for name in docs:
        p = root / "normalized" / "ir" / "fx" / "modules" / f"{name}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"name: {name}\n")
    return root


def _sem(root):
    return root / M.OUTPUT_DIR / "fx"


def test_corpus_check_passes_and_counts(tmp_path):
    root = _corpus(tmp_path)
    report = V.check(root)
    assert report["status"] == "PASS", report["problems"]
    assert report["documents"] == report["canonical_modules"] == 2
    assert report["totals"]["processes"] == 1 and report["totals"]["instances"] == 1
    assert report["totals"]["cases"] == 1 and report["totals"]["conditions"] == 1
    assert len(report["corpus_sha256"]) == 64


def test_05_duplicate_module_identity(tmp_path):
    root = _corpus(tmp_path)
    leaf, fx = _sem(root) / "leaf.json", _sem(root) / "fx.json"
    d = json.loads(leaf.read_text())
    d["module"]["module_id"] = json.loads(fx.read_text())["module"]["module_id"]
    leaf.write_text(M.dumps(d))
    report = V.check(root)
    assert report["status"] == "FAIL" and report["problem_counts"].get("duplicate_module_identity")


def test_14_duplicate_canonical_output_path(tmp_path):
    root = _corpus(tmp_path)
    shutil.copy(_sem(root) / "fx.json", _sem(root) / "FX.json")             # same output, other case
    report = V.check(root)
    assert report["status"] == "FAIL" and report["problem_counts"].get("duplicate_output_path")


def test_corpus_detects_missing_extra_and_noncanonical(tmp_path):
    root = _corpus(tmp_path)
    leaf = _sem(root) / "leaf.json"
    leaf.write_text(json.dumps(json.loads(leaf.read_text()), indent=2))      # not canonical bytes
    (_sem(root) / "ghost.json").write_text("{}\n")
    (root / "normalized" / "ir" / "fx" / "modules" / "absent.yaml").write_text("name: absent\n")
    pc = V.check(root)["problem_counts"]
    assert pc.get("nondeterministic") and pc.get("inventory", 0) >= 2


def test_corpus_detects_stale_source(tmp_path):
    root = _corpus(tmp_path)
    src = root / "raw" / "rtl" / "original" / "fx" / "fx.sv"
    src.write_text(src.read_text() + "\n// edited\n")
    report = V.check(root)
    assert report["status"] == "FAIL" and report["problem_counts"].get("provenance")


def test_validator_cli(tmp_path, capsys):
    root = _corpus(tmp_path)
    assert V.main(["--check", "--data-root", str(root), "--write-report"]) == 0
    assert "Semantic IR v2 check: PASS" in capsys.readouterr().out
    rep = json.loads((root / M.REPORT_PATH).read_text())
    assert rep["status"] == "PASS" and str(root) not in json.dumps(rep)
    (_sem(root) / "ghost.json").write_text("{}\n")
    assert V.main(["--check", "--data-root", str(root)]) == 1                 # fails closed
