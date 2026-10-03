# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_behavior_fixtures.py
# Description : KF-DQ-009 golden behavioral fixtures with behavioral assertions
#
# Component   : Kritva Forge
# Module      : tests/behavior
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Golden behavioral fixtures (acceptance criteria section 29).

Each fixture is RTL -> Semantic IR v2 -> Behavioral Semantics v1 with
assertions on the *behavior* (roles, confidence, clocks, resets, registers,
enables, holds, priority, completeness, latches, candidates) - not snapshots.
Every document is also validated against its Semantic IR.
"""

from tests.behavior.helpers import behave, behave_all, by_id, codes, comb, proc, reg

FIXTURES = []


def fixture(fn):
    FIXTURES.append(fn.__name__)
    return fn


# 1 / 2 / 8 -------------------------------------------------------------------
@fixture
def test_01_simple_always_ff_posedge_unconditional(tmp_path):
    b, _ = behave("module fx(input logic clk, input logic [7:0] d, output logic [7:0] q);\n"
                  "  always_ff @(posedge clk) q <= d;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("sequential", "high")
    assert {"keyword_always_ff", "edge_event", "nonblocking_assignments"} <= codes(p)
    (c,) = b["clocks"]
    assert (c["name"], c["edge"], c["status"]) == ("clk", "posedge", "confirmed")
    q = reg(b, "q")
    assert (q["update"], q["hold"], q["clock"], q["resets"]) == ("unconditional", "none", c["id"], [])
    assert [x["kind"] for x in q["priority"]] == ["update"] and q["enables"] == []
    assert p["registered_targets"] == [q["signal"]] and p["reads"] and p["writes"] == [q["signal"]]


@fixture
def test_02_positive_edge_clock(tmp_path):
    b, _ = behave("module fx(input c, input d, output reg q); always @(posedge c) q <= d; endmodule\n", tmp_path)
    (c,) = b["clocks"]
    assert (c["edge"], c["status"]) == ("posedge", "confirmed")
    assert proc(b)["confidence"] == "medium"                       # generic always + edge + nonblocking


@fixture
def test_03_negative_edge_clock(tmp_path):
    b, _ = behave("module fx(input c, input d, output reg q); always @(negedge c) q <= d; endmodule\n", tmp_path)
    (c,) = b["clocks"]
    assert (c["edge"], c["status"], c["name"]) == ("negedge", "confirmed", "c")


# 4 / 6 -----------------------------------------------------------------------
@fixture
def test_04_synchronous_reset_active_high(tmp_path):
    b, _ = behave("""
module fx(input clk, input clr, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) if (clr) q <= 4'd0; else q <= d;
endmodule
""", tmp_path)
    (r,) = b["resets"]
    assert (r["kind"], r["polarity"], r["status"], r["name"]) == ("sync", "active_high", "candidate", "clr")
    assert {"reset_not_in_event_list", "reset_tested_first", "reset_branch_constant", "else_branch_present"} <= codes(r)
    q = reg(b, "q")
    assert q["resets"] == [r["id"]] and [x["kind"] for x in q["priority"]] == ["reset", "update"]
    assert b["clocks"][0]["name"] == "clk"


# 5 / 7 -----------------------------------------------------------------------
@fixture
def test_05_asynchronous_reset(tmp_path):
    b, _ = behave("""
module fx(input clk, input arst, input d, output reg q);
  always @(posedge clk or posedge arst) if (arst) q <= 1'b0; else q <= d;
endmodule
""", tmp_path)
    (r,) = b["resets"]
    assert (r["kind"], r["polarity"], r["status"], r["edge"]) == ("async", "active_high", "confirmed", "posedge")
    assert {"reset_in_event_list", "edge_polarity_match", "reset_branch_constant"} <= codes(r)
    (c,) = b["clocks"]
    assert c["name"] == "clk" and c["status"] == "confirmed"         # the reset is not a clock


@fixture
def test_06_active_high_reset_compare_form(tmp_path):
    b, _ = behave("""
module fx(input k, input z, input d, output reg q);
  always @(posedge k or posedge z) if (z == 1'b1) q <= 1'b1; else q <= d;
endmodule
""", tmp_path)
    (r,) = b["resets"]
    assert (r["name"], r["polarity"], r["status"]) == ("z", "active_high", "confirmed")
    assert b["clocks"][0]["name"] == "k"                            # names carry no meaning


@fixture
def test_07_active_low_reset(tmp_path):
    b, _ = behave("""
module fx(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 8'h00;
    else        q <= d;
endmodule
""", tmp_path)
    (r,) = b["resets"]
    assert (r["kind"], r["polarity"], r["status"], r["edge"]) == ("async", "active_low", "confirmed", "negedge")
    assert "name_hint" in codes(r) and len(codes(r)) > 1             # the name is descriptive only


@fixture
def test_08_unconditional_register_update(tmp_path):
    b, _ = behave("module fx(input clk, input [3:0] a, output reg [3:0] q);\n"
                  "  always @(posedge clk) q <= a + 4'd1;\nendmodule\n", tmp_path)
    q = reg(b, "q")
    assert (q["update"], q["hold"]) == ("unconditional", "none")
    (nv,) = [n for n in b["next_values"] if n["register"] == q["id"]]
    assert (nv["value"], nv["guards"]) == ("expression", []) and nv["value_references"]


# 9 / 10 / 11 -----------------------------------------------------------------
@fixture
def test_09_register_enable(tmp_path):
    b, _ = behave("module fx(input clk, input en, input d, output reg q);\n"
                  "  always @(posedge clk) if (en) q <= d;\nendmodule\n", tmp_path)
    q = reg(b, "q")
    (e,) = b["enables"]
    assert (e["register"], e["update_branch"], e["hold_branch"], e["hold"]) == (q["id"], "then", "else", "implicit")
    assert q["update"] == "conditional" and q["enables"] == [e["id"]]


@fixture
def test_10_explicit_hold(tmp_path):
    b, _ = behave("module fx(input clk, input en, input d, output reg q);\n"
                  "  always @(posedge clk) if (en) q <= d; else q <= q;\nendmodule\n", tmp_path)
    q = reg(b, "q")
    (h,) = b["holds"]
    assert (q["hold"], h["kind"], h["guards"][-1]["branch"]) == ("explicit", "explicit", "else")
    assert h["assignment"] is not None and "self_assignment" in codes(q)
    assert b["enables"][0]["hold"] == "explicit"


@fixture
def test_11_implicit_hold(tmp_path):
    b, _ = behave("module fx(input clk, input en, input d, output reg q);\n"
                  "  always @(posedge clk) if (en) q <= d;\nendmodule\n", tmp_path)
    q = reg(b, "q")
    (h,) = b["holds"]
    assert (q["hold"], h["kind"], h["assignment"]) == ("implicit", "implicit", None)
    assert h["guards"][-1]["branch"] == "else" and "missing_branch" in codes(q)


# 12 --------------------------------------------------------------------------
@fixture
def test_12_nested_priority_reset_enable_hold(tmp_path):
    b, _ = behave("""
module fx(input clk, input rst, input en, input [3:0] d, output reg [3:0] q);
  always @(posedge clk)
    if (rst) q <= 4'd0;
    else if (en) q <= d;
    else q <= q;
endmodule
""", tmp_path)
    q = reg(b, "q")
    assert [x["kind"] for x in q["priority"]] == ["reset", "update", "hold_explicit"]     # reset > enable > hold
    assert [x["rank"] for x in q["priority"]] == [0, 1, 2]
    (r,) = b["resets"]
    assert q["priority"][0]["guards"][0] == {"statement": r["condition"], "branch": "then"}
    (e,) = b["enables"]
    assert e["condition"] != r["condition"] and e["hold"] == "explicit"


# 13 / 14 / 15 ----------------------------------------------------------------
@fixture
def test_13_complete_combinational(tmp_path):
    b, _ = behave("module fx(input logic a, input logic b, input s, output logic y);\n"
                  "  always_comb if (s) y = a; else y = b;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("combinational", "high")
    y = comb(b, "y")
    assert (y["completeness"], y["latch"], y["missing"]) == ("complete", "none", [])
    assert b["latches"] == [] and p["combinational_targets"] == [y["signal"]]


@fixture
def test_14_incomplete_combinational_infers_latch(tmp_path):
    b, _ = behave("module fx(input en, input a, output reg y);\n  always @* if (en) y = a;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("latch", "medium")
    y = comb(b, "y")
    assert (y["completeness"], y["latch"]) == ("incomplete", "inferred")
    assert y["missing"][0][-1]["branch"] == "else"
    (lt,) = b["latches"]
    assert lt["status"] == "inferred" and "incomplete_assignment" in codes(lt)


@fixture
def test_15_explicit_latch(tmp_path):
    b, _ = behave("module fx(input logic en, input logic d, output logic q);\n"
                  "  always_latch if (en) q = d;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("latch", "high")
    (lt,) = b["latches"]
    assert lt["status"] == "explicit" and "keyword_always_latch" in codes(lt)
    assert p["latch_targets"] == [lt["signal"]]


# 16 --------------------------------------------------------------------------
@fixture
def test_16_generic_always_stays_generic(tmp_path):
    b, _ = behave("module fx(input a, input b, output reg y);\n  always @(a) y = a & b;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("generic", "low")       # incomplete sensitivity list
    assert "incomplete_sensitivity" in codes(p) and b["combinational"] == []
    b2, _ = behave("module fx(input a, input b, output reg y);\n  always @(a or b) y = a & b;\nendmodule\n",
                   tmp_path / "complete")
    assert (proc(b2)["role"], proc(b2)["confidence"]) == ("combinational", "medium")


# 17 --------------------------------------------------------------------------
@fixture
def test_17_multiple_assignments_preserved(tmp_path):
    b, sem = behave("""
module fx(input s, input t, input a, input b, output logic y);
  always_comb begin
    y = 1'b0;
    if (s) y = a;
    if (t) y = b;
  end
endmodule
""", tmp_path)
    y = comb(b, "y")
    assert [a["order"] for a in y["assignments"]] == [0, 1, 2]
    assert [a["value"] for a in y["assignments"]] == ["constant", "expression", "expression"]
    assert [len(a["guards"]) for a in y["assignments"]] == [0, 1, 1]
    assert y["assignments"][0]["overridden_by"] == []                # later ones are conditional
    assert y["completeness"] == "complete"
    b2, _ = behave("module fx(input a, input b, output logic y);\n"
                   "  always_comb begin y = a; y = b; end\nendmodule\n", tmp_path / "override")
    y2 = comb(b2, "y")
    assert y2["assignments"][0]["overridden_by"] == [y2["assignments"][1]["assignment"]]


# 18 / 20 ---------------------------------------------------------------------
@fixture
def test_18_case_based_register_update(tmp_path):
    b, sem = behave("""
module fx(input clk, input [1:0] sel, input [3:0] a, input [3:0] c, output reg [3:0] q);
  always @(posedge clk)
    case (sel)
      2'd0: q <= a;
      2'd1: q <= c;
      default: q <= q;
    endcase
endmodule
""", tmp_path)
    q = reg(b, "q")
    assert (q["update"], q["hold"]) == ("case", "explicit")
    br = [x["guards"][-1]["branch"] for x in q["priority"]]
    assert br == ["item", "item", "default"]
    (cs,) = sem["cases"]
    assert proc(b)["cases"] == [cs["id"]]


@fixture
def test_19_casez_without_default_is_conditional(tmp_path):
    b, sem = behave("""
module fx(input [3:0] req, output reg [1:0] g);
  always @* casez (req)
    4'b???1: g = 2'd0;
    4'b??10: g = 2'd1;
  endcase
endmodule
""", tmp_path)
    g = comb(b, "g")
    assert (g["completeness"], g["latch"]) == ("conditional", "possible")
    assert g["missing"][0][-1]["branch"] == "default" and "case_without_default" in codes(g)
    assert sem["cases"][0]["case_kind"] == "casez" and proc(b)["cases"] == [sem["cases"][0]["id"]]
    assert proc(b)["confidence"] == "low"


@fixture
def test_20_casex_register_update(tmp_path):
    b, sem = behave("""
module fx(input clk, input [2:0] op, input [3:0] a, output reg [3:0] q);
  always @(posedge clk) casex (op)
    3'b1xx: q <= a;
    3'b01x: q <= 4'd0;
  endcase
endmodule
""", tmp_path)
    q = reg(b, "q")
    assert sem["cases"][0]["case_kind"] == "casex"
    assert (q["update"], q["hold"]) == ("case", "implicit")
    assert any(h["guards"][-1]["branch"] == "default" for h in b["holds"])


# 21 / 22 ---------------------------------------------------------------------
@fixture
def test_21_unique_case(tmp_path):
    b, sem = behave("""
module fx(input [1:0] s, input [3:0] a, output logic [3:0] y);
  always_comb unique case (s)
    2'd0: y = a;
    default: y = 4'd0;
  endcase
endmodule
""", tmp_path)
    assert sem["cases"][0]["qualifier"] == "unique" and proc(b)["cases"] == [sem["cases"][0]["id"]]
    assert comb(b, "y")["completeness"] == "complete"


@fixture
def test_22_priority_case(tmp_path):
    b, sem = behave("""
module fx(input [1:0] s, input [3:0] a, output logic [3:0] y);
  always_comb priority case (s)
    2'd0: y = a;
    2'd1: y = 4'd1;
  endcase
endmodule
""", tmp_path)
    assert sem["cases"][0]["qualifier"] == "priority"
    y = comb(b, "y")
    assert (y["completeness"], y["latch"]) == ("conditional", "possible")


# 23 --------------------------------------------------------------------------
@fixture
def test_23_candidate_state_registers(tmp_path):
    b, _ = behave("""
module fx(input clk, input rst, input go, output reg busy);
  localparam IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  reg [1:0] st, st_n;
  always @(posedge clk) if (rst) st <= IDLE; else st <= st_n;
  always @* begin
    st_n = st;
    case (st)
      IDLE: if (go) st_n = RUN;
      RUN:  st_n = DONE;
      default: st_n = IDLE;
    endcase
  end
  reg [1:0] m;
  always @(posedge clk) case (m) 2'd0: m <= 2'd1; 2'd1: m <= 2'd2; default: m <= 2'd0; endcase
  reg [3:0] cnt;
  always @(posedge clk) if (cnt == 4'd9) cnt <= 4'd0; else cnt <= cnt + 4'd1;
endmodule
""", tmp_path)
    cands = {(c["name"], c["kind"]) for c in b["candidates"]}
    assert ("st", "state_candidate") in cands and ("st_n", "next_value_candidate") in cands      # two-process
    assert ("m", "state_candidate") in cands                                                 # one-process
    assert not any(n == "cnt" for n, _ in cands)                       # counter: arithmetic self-feedback
    st = next(c for c in b["candidates"] if c["name"] == "st")
    assert {"selector_feedback", "constant_state_values", "finite_width", "next_value_feedback"} <= codes(st)
    assert by_id(b, "candidates", st["next_value"])["name"] == "st_n"


# 24 --------------------------------------------------------------------------
@fixture
def test_24_ambiguous_process(tmp_path):
    b, _ = behave("module fx(input clk, input r, input d, output reg q);\n"
                  "  always @(posedge clk or r) q <= d;\nendmodule\n", tmp_path)
    p = proc(b)
    assert (p["role"], p["confidence"]) == ("ambiguous", "unknown")
    assert "mixed_edge_level_events" in codes(p)
    assert b["registers"] == [] and b["clocks"] == []


# 25 --------------------------------------------------------------------------
@fixture
def test_25_unsupported_opaque_behavior(tmp_path):
    b, sem = behave("""
module fx(input clk, input a, input d, output reg q);
  always @(posedge clk) begin wait (a); q <= d; end
endmodule
""", tmp_path)
    p = proc(b)
    assert sem["unsupported"] and "opaque_statement" in codes(p)
    assert (p["role"], p["confidence"]) == ("sequential", "low")      # medium lowered by opaque behavior
    assert reg(b, "q")["hold"] == "none"          # the update after the opaque wait still covers q
    b2, _ = behave("""
module fx(input clk, input a, input d, output reg q);
  always @(posedge clk) begin if (a) wait (d); else q <= d; end
endmodule
""", tmp_path / "unknown")
    assert reg(b2, "q")["hold"] == "ambiguous"     # the opaque branch may or may not assign q


# extra -----------------------------------------------------------------------
def test_blocking_assignment_in_clocked_process(tmp_path):
    b, _ = behave("module fx(input clk, input d, output reg q); always @(posedge clk) q = d; endmodule\n", tmp_path)
    assert (proc(b)["role"], proc(b)["confidence"]) == ("sequential", "low")
    q = reg(b, "q")
    assert q["confidence"] == "unknown"           # low process confidence, lowered for a blocking update
    assert "blocking_update" in codes(q)


def test_initialization_process(tmp_path):
    b, _ = behave("module fx(output reg q); initial q = 1'b0; endmodule\n", tmp_path)
    assert (proc(b)["role"], proc(b)["confidence"]) == ("initialization", "high")


def test_naming_has_no_effect(tmp_path):
    """A data input named like a clock is not a clock; an unnamed edge signal is."""
    b, _ = behave("""
module fx(input clk, input rst, input tick, output reg q, output reg y);
  always @(posedge tick) q <= clk;
  always @* y = rst;
endmodule
""", tmp_path)
    (c,) = b["clocks"]
    assert c["name"] == "tick" and b["resets"] == []
    assert proc(b, "always", 1)["role"] == "combinational"


def test_fixture_inventory_is_complete():
    assert len(FIXTURES) == 25
