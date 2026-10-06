# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_register_boundary.py
# Description : FSM Analysis v2 register-boundary output classification tests (KF-DQ-011.1)
#
# Component   : Kritva Forge
# Module      : tests/fsm
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Registered outputs are temporal boundaries (KF-DQ-011.1).

Fixtures through the real chain RTL -> Semantic IR v2 -> Behavioral Semantics
v1 -> Structural Analysis v1 -> FSM Analysis v2 (AC-145 .. AC-158), and
validator negative tests for the schema-v2 output fields (AC-159 .. AC-170).
"""

import copy

import pytest

from scripts.fsm import model as F
from scripts.fsm import validator as V
from scripts.structural import query as SQ
from tests.fsm.helpers import fsm_all, only

RTL = {
    # R1 - registered non-state output sampling a module input, another register and an enable
    #      condition, without any FSM action; the state register is also an output port.
    "r1": """
module r1(input clk, input rst_n, input go, input en, input din, output reg q, output reg [1:0] st);
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1;
  reg d1;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= IDLE;
    else case (st)
      IDLE: if (go) st <= RUN;
      RUN:  if (!go) st <= IDLE;
      default: st <= IDLE;
    endcase
  always @(posedge clk) d1 <= din;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 1'b0; else if (en) q <= (st == RUN) & d1 & go;
endmodule
""",
    # R2 - combinational output reaching another register only: stays ambiguous
    "r2": """
module r2(input clk, input rst_n, input a, input b, output y);
  localparam [1:0] S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
  reg [1:0] s;
  reg r;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= S0;
    else case (s) S0: if (a) s <= S1; S1: s <= S2; S2: s <= S0; default: s <= S0; endcase
  always @(posedge clk) r <= b;
  assign y = (s == S2) & r;
endmodule
""",
    # R3 - registered output written through a combinational next-value signal (AC-065)
    "r3": """
module r3(input clk, input rst_n, input x, output reg o);
  localparam A = 1'b0, B = 1'b1;
  reg s;
  wire o_nx = (s == B) ? x : 1'b0;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= A; else case (s) A: if (x) s <= B; B: if (!x) s <= A; endcase
  always @(posedge clk or negedge rst_n)
    if (!rst_n) o <= 1'b0; else o <= o_nx;
endmodule
""",
}


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    out = {}
    for name, src in RTL.items():
        doc, inputs = fsm_all(src, tmp_path_factory.mktemp(name))[name]
        out[name] = (doc, inputs)
    return out


def _names(inputs, ids):
    sem = inputs[0]
    nm = {x["id"]: x["name"] for x in sem["ports"] + sem["signals"]}
    return [nm[i] for i in ids]


def _outputs(doc, inputs):
    return {o["name"]: (o["kind"], o["registered"], sorted(_names(inputs, o["sampled_sources"])),
                        sorted(_names(inputs, o["other_sources"]))) for o in only(doc)["outputs"]}


# ============================================================================= fixtures

def test_r1_registered_outputs(docs):
    doc, inputs = docs["r1"]
    f = only(doc)
    assert f["status"] == "confirmed" and f["actions"] == []                      # AC-153: no action evidence
    assert _outputs(doc, inputs) == {
        "q": ("moore", True, ["d1", "en", "go"], []),     # AC-150 / AC-154; E1 enable condition
        "st": ("moore", True, ["go"], []),                                       # AC-155 state-register output
    }
    q = next(o for o in f["outputs"] if o["name"] == "q")
    assert q["state_sources"] == [f["register"]["signal"]]
    # clock and reset reach q in Structural Analysis but are never sampled sources (AC-112, AC-113)
    st = inputs[6]
    timing = {d["source"] for d in st["dependencies"] if d["target"] == q["signal"] and d["kind"] in ("clock", "reset")}
    assert timing and not timing & set(q["sampled_sources"])


def test_r1_structural_cone_is_unchanged(docs):
    """The Structural query still walks the registered output's own update logic (AC-021 .. AC-024);
    only the FSM interpretation changed."""
    doc, inputs = docs["r1"]
    q = next(o for o in only(doc)["outputs"] if o["name"] == "q")
    cone = SQ.cone(inputs[6], q["signal"], "fanin")
    assert set(_names(inputs, cone["inputs"])) >= {"go", "en"}


def test_r2_ambiguous_combinational_output(docs):
    doc, inputs = docs["r2"]
    assert _outputs(doc, inputs) == {"y": ("ambiguous", False, [], ["r"])}       # AC-156


def test_r3_registered_through_next_value_signal(docs):
    doc, inputs = docs["r3"]
    assert _outputs(doc, inputs) == {"o": ("moore", True, ["x"], [])}            # AC-065


def test_shape_fingerprint_sees_output_kinds(docs):
    doc, _ = docs["r1"]
    assert sorted(o["kind"] for o in only(doc)["outputs"]) == ["moore", "moore"]


# ============================================================================= validator (AC-159 .. AC-170)

@pytest.fixture
def ref(docs):
    return copy.deepcopy(docs["r1"])


def _fails(doc, inputs, code):
    got = V.validate_module(doc, *inputs)
    assert code in {c for c, _ in got}, got[:6]


def _q(doc):
    return next(o for o in only(doc)["outputs"] if o["name"] == "q")


def test_valid_reference(ref):
    doc, inputs = ref
    assert V.validate_module(doc, *inputs) == []


def test_registered_output_cannot_be_mealy(ref):
    doc, inputs = ref
    o = _q(doc)
    o["kind"], o["other_sources"] = "mealy", sorted(o["sampled_sources"][:1])
    _fails(doc, inputs, "consistency")


def test_registered_output_without_combinational_sources(ref):
    doc, inputs = ref
    _q(doc)["other_sources"] = sorted(_q(doc)["sampled_sources"])
    _fails(doc, inputs, "consistency")


def test_registered_flag_checked_against_structural_registers(ref):
    doc, inputs = ref
    _q(doc)["registered"] = False
    _fails(doc, inputs, "structural_consistency")


def test_registered_flag_must_be_boolean(ref):
    doc, inputs = ref
    _q(doc)["registered"] = "yes"
    _fails(doc, inputs, "schema")


def test_missing_registered_or_sampled_fields(ref):
    doc, inputs = ref
    del _q(doc)["sampled_sources"]
    _fails(doc, inputs, "required")


@pytest.mark.parametrize("kind", ["clock", "reset"])
def test_clock_and_reset_are_not_sampled_sources(ref, kind):
    doc, inputs = ref
    o = _q(doc)
    sig = next(d["source"] for d in inputs[6]["dependencies"] if d["target"] == o["signal"] and d["kind"] == kind)
    o["sampled_sources"] = sorted(set(o["sampled_sources"]) | {sig})
    _fails(doc, inputs, "consistency")


def test_hold_source_is_not_a_sampled_source(ref):
    """KF-DQ-012 A4 (R-1 from the KF-DQ-011.1 review): a hold dependency is not a sampled input."""
    doc, inputs = ref
    o = _q(doc)
    x = o["sampled_sources"][0]
    deps = inputs[6]["dependencies"]
    deps.append({**next(d for d in deps if d["target"] == o["signal"]), "source": x, "kind": "hold"})
    got = V.validate_module(doc, *inputs)
    assert any(c == "consistency" and "hold source" in m for c, m in got), got[:6]


def test_state_register_is_not_a_sampled_source(ref):
    doc, inputs = ref
    o = _q(doc)
    o["sampled_sources"] = sorted(set(o["sampled_sources"]) | {only(doc)["register"]["signal"]})
    _fails(doc, inputs, "consistency")


def test_sampled_sources_ordering_and_references(ref):
    doc, inputs = ref
    o = _q(doc)
    o["sampled_sources"] = list(reversed(o["sampled_sources"]))
    _fails(doc, inputs, "ordering")
    doc, inputs = copy.deepcopy(ref)
    _q(doc)["sampled_sources"] = sorted(_q(doc)["sampled_sources"] + ["sem1:0000000000000000"])
    _fails(doc, inputs, "semantic_reference")


def test_combinational_output_has_no_sampled_sources(docs):
    doc, inputs = copy.deepcopy(docs["r2"])
    y = only(doc)["outputs"][0]
    y["sampled_sources"] = list(y["other_sources"])
    _fails(doc, inputs, "consistency")


def test_schema_v2_constants():
    assert (F.SCHEMA_VERSION, F.ANALYZER_VERSION, F.IDENTITY_VERSION) == (2, 2, 1)
    assert F.OUTPUT_DIR == "normalized/fsm/v2" and F.OBSOLETE_OUTPUT_DIRS == ("normalized/fsm/v1",)
    assert V.REQUIRED["outputs"] == ("id", "signal", "name", "kind", "registered", "state_sources",
                                     "sampled_sources", "other_sources", "loc")
