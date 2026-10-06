# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_structural_fixtures.py
# Description : KF-DQ-010 golden structural fixtures (criteria section 16, AC-045)
#
# Component   : Kritva Forge
# Module      : tests/structural
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Golden structural fixtures (acceptance criteria section 16).

Each fixture is RTL -> Semantic IR v2 -> Behavioral Semantics v1 ->
Structural Analysis v1 with assertions on the *structure* (drivers, loads,
dependencies with kind / context / boundary, predicates, registers,
multiple drivers, cycles, cones, hierarchy) - not snapshots.  Every document
is validated against both inputs by the helper.
"""

from scripts.structural import query as Q
from tests.structural.helpers import (classes, dep, drivers, edges, loads, names, predicate, register, sid,
                                      signal, structure, structure_all)

FIXTURES = []


def fixture(fn):
    FIXTURES.append(fn.__name__)
    return fn


# 1 - 3: combinational expressions --------------------------------------------
@fixture
def test_01_simple_combinational_assignment(tmp_path):
    d = structure("module fx(input a, output y); assign y = a; endmodule\n", tmp_path)
    (e,) = dep(d, "a", "y", "data")
    assert (e["context"], e["boundary"], e["direct"], e["status"]) == ("continuous_assignment", "combinational", True, "confirmed")
    (drv,) = [x for x in drivers(d, "y")]
    assert drv["kind"] == "continuous_assignment" and drv["assignments"] == e["assignments"]
    assert {x["kind"] for x in loads(d, "a")} == {"assignment_value"}
    assert {x["kind"] for x in loads(d, "y")} == {"module_output"}
    assert signal(d, "y")["driver_status"] == "driven" and signal(d, "a")["driver_status"] == "external"
    assert signal(d, "y")["fan_in"]["direct"] == 1 and signal(d, "a")["fan_out"]["outputs"] == 1


@fixture
def test_02_multi_input_combinational_logic(tmp_path):
    d = structure("module fx(input a, b, c, output y); assign y = (a & b) | c; endmodule\n", tmp_path)
    assert edges(d, dst="y") == [("a", "y", "data", "continuous_assignment"), ("b", "y", "data", "continuous_assignment"),
                                 ("c", "y", "data", "continuous_assignment")]
    y = signal(d, "y")
    assert y["fan_in"]["expression"] == 3 and y["fan_in"]["direct"] == 0 and y["fan_in"]["signals"] == 3


@fixture
def test_03_nested_expressions(tmp_path):
    d = structure("""
module fx(input a, b, c, d, e, input [3:0] f, output [2:0] y);
  assign y = (a & (b ^ c)) ? {d, f[1:0]} : {e, f[3:2]};
endmodule
""", tmp_path)
    assert edges(d, dst="y", kind="control") == [("a", "y", "control", "ternary_condition"),
                                                 ("b", "y", "control", "ternary_condition"),
                                                 ("c", "y", "control", "ternary_condition")]
    assert edges(d, dst="y", kind="data") == [(s, "y", "data", "continuous_assignment") for s in ("d", "e", "f")]
    assert classes(d, "a")["control"] == "confirmed" and "data" not in classes(d, "a")   # not an ordinary data input


# 4 - 6: if / nested if / priority ----------------------------------------------
@fixture
def test_04_if_else(tmp_path):
    d = structure("""
module fx(input s, a, b, output logic y);
  always_comb if (s) y = a; else y = b;
endmodule
""", tmp_path)
    assert edges(d, "s", "y") == [("s", "y", "control", "condition")]
    assert edges(d, dst="y", kind="data") == [("a", "y", "data", "procedural_assignment"),
                                              ("b", "y", "data", "procedural_assignment")]
    p = predicate(d, "if")
    assert p["default"] is True and names(d, p["signals"]) == ["s"] and names(d, p["targets"]) == ["y"]
    assert (p["role"], p["parent"], p["depth"]) == ("control", None, 0)
    assert all(e["boundary"] == "combinational" for e in d["dependencies"])


@fixture
def test_05_nested_if(tmp_path):
    d = structure("""
module fx(input s1, s2, a, b, c, output logic y);
  always_comb if (s1) begin if (s2) y = a; else y = b; end else y = c;
endmodule
""", tmp_path)
    outer = next(p for p in d["predicates"] if names(d, p["signals"]) == ["s1"])
    inner = next(p for p in d["predicates"] if names(d, p["signals"]) == ["s2"])
    assert outer["parent"] is None and inner["parent"] == {"statement": outer["statement"], "branch": "then"}
    assert (outer["depth"], inner["depth"]) == (0, 1)
    a_assign = next(x for x in d["assignments"] if names(d, x["data"]) == ["a"])
    assert [g["statement"] for g in a_assign["guards"]] == [outer["statement"], inner["statement"]]
    assert names(d, a_assign["control"]) == ["s1", "s2"]
    assert edges(d, "s2", "y") == [("s2", "y", "control", "condition")]


@fixture
def test_06_priority_logic(tmp_path):
    d = structure("""
module fx(input r1, r2, a, b, c, output logic y);
  always_comb if (r1) y = a; else if (r2) y = b; else y = c;
endmodule
""", tmp_path)
    p1 = next(p for p in d["predicates"] if names(d, p["signals"]) == ["r1"])
    p2 = next(p for p in d["predicates"] if names(d, p["signals"]) == ["r2"])
    assert p2["parent"] == {"statement": p1["statement"], "branch": "else"}
    c_assign = next(x for x in d["assignments"] if names(d, x["data"]) == ["c"])
    assert [(g["statement"], g["branch"]) for g in c_assign["guards"]] == [(p1["statement"], "else"), (p2["statement"], "else")]
    orders = sorted(x["order"] for x in d["assignments"])
    assert orders == [0, 1, 2]                                    # source order of the priority chain


# 7 - 10: case ------------------------------------------------------------------
@fixture
def test_07_case(tmp_path):
    d = structure("""
module fx(input [1:0] sel, input a, b, c, output logic y);
  always_comb case (sel) 2'd0: y = a; 2'd1: y = b; default: y = c; endcase
endmodule
""", tmp_path)
    p = predicate(d, "case")
    assert (p["default"], len(p["items"]), names(d, p["signals"])) == (True, 2, ["sel"])
    assert edges(d, "sel", "y") == [("sel", "y", "control", "case_expression")]
    assert [l["kind"] for l in loads(d, "sel")] == ["case_expression"]


@fixture
def test_08_casez(tmp_path):
    d = structure("""
module fx(input [1:0] sel, input a, b, output logic y);
  always_comb begin y = 1'b0; casez (sel) 2'b1?: y = a; 2'b01: y = b; endcase end
endmodule
""", tmp_path)
    p = predicate(d, "casez")
    assert p["default"] is False and edges(d, "sel", "y") == [("sel", "y", "control", "case_expression")]


@fixture
def test_09_casex(tmp_path):
    d = structure("""
module fx(input [1:0] sel, input a, b, output logic y);
  always_comb casex (sel) 2'b1x: y = a; default: y = b; endcase
endmodule
""", tmp_path)
    assert predicate(d, "casex")["kind"] == "casex" and edges(d, "sel", "y")


@fixture
def test_10_default_case_with_signal_labels(tmp_path):
    d = structure("""
module fx(input a, b, x, z, w, output logic y);
  always_comb case (1'b1) a: y = x; b: y = z; default: y = w; endcase
endmodule
""", tmp_path)
    p = predicate(d, "case")
    assert p["default"] and [names(d, it["signals"]) for it in p["items"]] == [["a"], ["b"]]
    # labels select items; the default branch depends on every label
    assert edges(d, dst="y", kind="control") == [("a", "y", "control", "case_item"), ("b", "y", "control", "case_item")]
    w_assign = next(x for x in d["assignments"] if names(d, x["data"]) == ["w"])
    assert names(d, w_assign["control"]) == ["a", "b"]
    assert {l["kind"] for l in loads(d, "a")} == {"case_item"}


# 11 - 16: sequential --------------------------------------------------------------
@fixture
def test_11_sequential_register(tmp_path):
    d = structure("module fx(input clk, input [3:0] d, output reg [3:0] q); always @(posedge clk) q <= d; endmodule\n",
                  tmp_path)
    (e,) = dep(d, "d", "q", "data")
    assert (e["context"], e["boundary"]) == ("sequential_update", "sequential")
    (c,) = dep(d, "clk", "q", "clock")
    assert (c["context"], c["status"]) == ("clock_event", "confirmed")
    r = register(d, "q")
    assert r["clock"]["signal"] == sid(d, "clk") and r["boundary"] == "sequential"
    assert [n["sources"] for n in r["next_values"]] == [[sid(d, "d")]]
    assert classes(d, "q")["sequential_boundary"] == "confirmed" and classes(d, "clk")["clock"] == "confirmed"
    assert d["counts"]["sequential_boundaries"] == 2


@fixture
def test_12_register_enable(tmp_path):
    d = structure("""
module fx(input clk, en, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) if (en) q <= d;
endmodule
""", tmp_path)
    (e,) = dep(d, "en", "q", "enable")
    assert (e["context"], e["boundary"]) == ("enable", "sequential") and e["behavior"]
    assert not dep(d, "en", "q", "control")                       # an enable is not an ordinary control edge
    assert Q.registers_controlled_by(d, sid(d, "en")) == [sid(d, "q")]
    assert classes(d, "en")["enable"] == "confirmed"
    assert register(d, "q")["enables"][0]["signals"] == [sid(d, "en")]


@fixture
def test_13_explicit_hold(tmp_path):
    d = structure("""
module fx(input clk, en, d, output reg q);
  always @(posedge clk) if (en) q <= d; else q <= q;
endmodule
""", tmp_path)
    (h,) = dep(d, "q", "q", "hold")
    assert (h["hold"], h["context"], len(h["assignments"])) == ("explicit", "hold", 1)
    assert [x["kind"] for x in register(d, "q")["holds"]] == ["explicit"]
    assert classes(d, "q")["hold"] == "confirmed"


@fixture
def test_14_implicit_hold(tmp_path):
    d = structure("""
module fx(input clk, en, d, output reg q);
  always @(posedge clk) if (en) q <= d;
endmodule
""", tmp_path)
    (h,) = dep(d, "q", "q", "hold")
    assert (h["hold"], h["assignments"], h["boundary"]) == ("implicit", [], "sequential") and h["behavior"]
    assert {x["kind"] for x in register(d, "q")["holds"]} == {"implicit"}


@fixture
def test_15_synchronous_reset(tmp_path):
    d = structure("""
module fx(input clk, clr, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) if (clr) q <= 4'd0; else q <= d;
endmodule
""", tmp_path)
    (e,) = dep(d, "clr", "q", "reset")
    assert (e["context"], e["status"]) == ("reset", "candidate")         # synchronous resets are candidates
    (r,) = register(d, "q")["resets"]
    assert (r["kind"], r["polarity"], r["status"]) == ("sync", "active_high", "candidate") and r["assignments"]
    assert classes(d, "clr")["reset"] == "candidate"
    assert [p["kind"] for p in register(d, "q")["priority"]] == ["reset", "update"]


@fixture
def test_16_asynchronous_reset(tmp_path):
    d = structure("""
module fx(input clk, rst_n, input [7:0] d, output reg [7:0] q);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 8'h00; else q <= d;
endmodule
""", tmp_path)
    (e,) = dep(d, "rst_n", "q", "reset")
    assert e["status"] == "confirmed" and not dep(d, "rst_n", "q", "control")
    (r,) = register(d, "q")["resets"]
    assert (r["kind"], r["polarity"], r["status"]) == ("async", "active_low", "confirmed")
    assert classes(d, "rst_n")["reset"] == "confirmed"
    assert predicate(d, "if")["role"] == "reset"
    assert {l["kind"] for l in loads(d, "rst_n")} == {"event", "condition"}


# 17 - 20: multiple assignments / drivers, cycles, register boundary ---------------
@fixture
def test_17_multiple_assignments(tmp_path):
    d = structure("""
module fx(input s, a, b, output logic y);
  always_comb begin y = a; if (s) y = b; end
endmodule
""", tmp_path)
    (drv,) = drivers(d, "y")
    assert drv["kind"] == "procedural" and len(drv["assignments"]) == 2            # one driver, both assignments
    first = next(x for x in d["assignments"] if names(d, x["data"]) == ["a"])
    second = next(x for x in d["assignments"] if names(d, x["data"]) == ["b"])
    assert (first["order"], second["order"], first["guards"], len(second["guards"])) == (0, 1, [], 1)
    assert not signal(d, "y")["multiple_drivers"]


@fixture
def test_18_multiple_drivers(tmp_path):
    d = structure("""
module fx(input a, b, output wire y, output wire [1:0] z);
  assign y = a;
  assign y = b;
  assign z[0] = a;
  assign z[1] = b;
endmodule
""", tmp_path)
    y = signal(d, "y")
    assert (y["driver_units"], y["multiple_drivers"]) == (2, True)
    my = next(m for m in d["multiple_drivers"] if m["signal"] == y["signal"])
    assert (my["status"], my["reasons"], my["kinds"]) == ("confirmed", [], ["continuous_assignment"])
    mz = next(m for m in d["multiple_drivers"] if m["signal"] == sid(d, "z"))
    assert (mz["status"], mz["reasons"]) == ("candidate", ["partial_writes"])     # disjoint bits: never collapsed


@fixture
def test_19_combinational_cycle(tmp_path):
    d = structure("""
module fx(input c, input e, output wire y);
  wire a, b;
  assign a = b & c;
  assign b = a | e;
  assign y = a;
endmodule
""", tmp_path)
    (cy,) = d["cycles"]
    assert names(d, cy["signals"]) == ["a", "b"] and cy["status"] == "confirmed" and len(cy["edges"]) == 2
    c = Q.cone(d, sid(d, "y"), "fanin")                           # traversal terminates on the cycle
    assert names(d, c["signals"]) == ["a", "b", "c", "e"] and c["cycles"] == [cy["id"]]


@fixture
def test_20_register_boundary(tmp_path):
    d = structure("""
module fx(input clk, d, x, output y);
  reg q1, q2;
  always @(posedge clk) begin q1 <= d; q2 <= q1; end
  assign y = q2 & x;
endmodule
""", tmp_path)
    fin = next(c for c in d["cones"] if c["signal"] == sid(d, "y") and c["direction"] == "fanin")
    assert names(d, fin["signals"]) == ["q2", "x"] and names(d, fin["registers"]) == ["q2"]   # stops at q2
    fout = next(c for c in d["cones"] if c["signal"] == sid(d, "d") and c["direction"] == "fanout")
    assert names(d, fout["registers"]) == ["q1"] and names(d, fout["signals"]) == ["q1"]
    (e,) = dep(d, "q1", "q2", "data")
    assert e["boundary"] == "sequential" and dep(d, "q2", "y", "data")[0]["boundary"] == "combinational"


# 21 - 24: hierarchy ------------------------------------------------------------------
HIER = """
module child(input i, output o); assign o = ~i; endmodule
module fx(input a, b, output z, output w);
  child u0 (.i(a & b), .o(z));
  missing_mod u1 (.p(a), .q(w));
endmodule
"""


@fixture
def test_21_module_instance_connectivity(tmp_path):
    d = structure(HIER, tmp_path)
    u0 = next(i for i in d["instances"] if i["name"] == "u0")
    assert (u0["status"], u0["module"], u0["child"]["module"], u0["child"]["ip"]) == ("resolved", "child", "child", "fx")
    assert u0["parent"] == d["module"]["module_id"] and len(u0["connections"]) == 2
    h = next(x for x in d["hierarchy"] if x["instance"] == u0["id"])
    assert (h["relationship"], h["child"], h["cross_module"]) == ("instantiates", u0["child"]["module_id"], True)
    assert not [e for e in d["dependencies"] if e["source"] == sid(d, "a") and e["target"] == sid(d, "z")]   # not flattened


@fixture
def test_22_input_connectivity(tmp_path):
    d = structure(HIER, tmp_path)
    c = next(x for x in d["connections"] if x["port"] == "i")
    assert (c["direction"], c["flow"], c["status"], c["lvalue"]) == ("input", "parent_to_child", "confirmed", False)
    assert names(d, c["signals"]) == ["a", "b"]
    assert {l["kind"] for l in loads(d, "b")} == {"instance_input"}
    assert signal(d, "a")["fan_out"]["instances"] == 2


@fixture
def test_23_output_connectivity(tmp_path):
    d = structure(HIER, tmp_path)
    c = next(x for x in d["connections"] if x["port"] == "o")
    assert (c["direction"], c["flow"]) == ("output", "child_to_parent")
    (drv,) = drivers(d, "z")
    assert (drv["kind"], drv["connection"], drv["whole"]) == ("instance_output", c["id"], True)
    assert signal(d, "z")["driver_status"] == "driven" and classes(d, "z")["port_connection"] == "confirmed"


@fixture
def test_24_unresolved_hierarchy_reference(tmp_path):
    docs = structure_all(HIER, tmp_path, canonical=["fx"])       # child has no canonical IR either
    d = docs["fx"][0]
    u1 = next(i for i in d["instances"] if i["name"] == "u1")
    assert (u1["status"], u1["reason"], u1["child"]) == ("unresolved", "not_resolved_by_elaboration", None)
    u0 = next(i for i in d["instances"] if i["name"] == "u0")
    assert (u0["status"], u0["reason"], u0["child"]) == ("unresolved", "no_canonical_child_ir", None)   # never fabricated
    q = next(x for x in d["connections"] if x["port"] == "q")
    assert (q["direction"], q["flow"], q["status"]) == ("unknown", "unknown", "candidate")
    w = signal(d, "w")
    assert (w["driver_status"], w["possible_drivers"], w["driver_units"]) == ("unknown", 1, 0)   # not "undriven"
    assert d["counts"]["unresolved_instances"] == 2


# 25: mixed cone ----------------------------------------------------------------------
@fixture
def test_25_mixed_sequential_combinational_cone(tmp_path):
    d = structure("""
module fx(input clk, en, input [3:0] a, b, output [3:0] y, output [3:0] z);
  wire [3:0] s = a + b;
  reg  [3:0] q;
  always @(posedge clk) if (en) q <= s;
  assign y = q ^ a;
  assign z = s;
endmodule
""", tmp_path)
    fq = next(c for c in d["cones"] if c["signal"] == sid(d, "q") and c["direction"] == "fanin")
    assert names(d, fq["signals"]) == ["a", "b", "clk", "en", "s"]
    assert sorted(names(d, fq["inputs"])) == ["a", "b", "clk", "en"] and fq["registers"] == []
    fa = Q.cone(d, sid(d, "a"), "fanout")
    assert names(d, fa["signals"]) == ["q", "s", "y", "z"] and names(d, fa["registers"]) == ["q"]
    assert names(d, fa["outputs"]) == ["y", "z"]
    fy = Q.cone(d, sid(d, "y"), "fanin")
    assert names(d, fy["signals"]) == ["a", "q"] and names(d, fy["registers"]) == ["q"]   # sequential boundary
    assert {e["boundary"] for e in d["dependencies"]} == {"combinational", "sequential"}


def test_fixture_inventory():
    assert len(FIXTURES) == 25 and len(set(FIXTURES)) == 25


# ----------------------------------------------------------------------------- extras
def test_undriven_is_distinct_from_unknown(tmp_path):
    d = structure("""
module fx(input a, output y, output u);
  wire n;
  assign y = a & n;
endmodule
""", tmp_path)
    assert signal(d, "n")["driver_status"] == "undriven" and signal(d, "u")["driver_status"] == "undriven"
    assert signal(d, "a")["driver_status"] == "external"


def test_read_write_ordering(tmp_path):
    d = structure("""
module fx(input clk, input [3:0] a, output logic [3:0] y, output reg [3:0] c);
  logic [3:0] t;
  always_comb begin t = a; y = t + 1; end
  always @(posedge clk) c <= c + 1;
endmodule
""", tmp_path)
    by = {p["kind"]: p for p in d["processes"]}
    assert [(names(d, [x["signal"]])[0], x["order"]) for x in by["always_comb"]["read_write"]] == [("t", "write_first")]
    seq = by["always"]
    assert [(x["order"]) for x in seq["read_write"]] == ["nonblocking"]
    d2 = structure("""
module fx(input [3:0] a, output logic [3:0] y);
  logic [3:0] t;
  always_comb begin t = a; t = t + 1; y = t; end
endmodule
""", tmp_path / "b")
    (rw,) = d2["processes"][0]["read_write"]
    assert rw["order"] == "write_first" and not d2["cycles"]          # a process-local value is not a cycle
    d3 = structure("""
module fx(input s, input [3:0] a, output logic [3:0] y, output logic [3:0] t);
  always_comb begin y = t; t = a; end
  always_comb begin if (s) t2 = a; y2 = t2; end
  logic [3:0] t2, y2;
endmodule
""", tmp_path / "c")
    orders = sorted(x["order"] for p in d3["processes"] for x in p["read_write"])
    assert orders == ["mixed", "read_first"]                         # conditional first write stays explicit


def test_naming_is_never_sufficient(tmp_path):
    d = structure("""
module fx(input clk_en, input rst, input d, output y);
  assign y = d & clk_en & rst;
endmodule
""", tmp_path)
    for n in ("clk_en", "rst"):
        assert set(classes(d, n)) <= {"data", "load", "hierarchy"}       # no clock / reset / enable by name


def test_identities_are_deterministic(tmp_path):
    src = "module fx(input clk, d, output reg q); always @(posedge clk) q <= d; endmodule\n"
    a = structure(src, tmp_path / "a")
    b = structure(src, tmp_path / "x" / "elsewhere")
    assert a == b and a["id"].startswith("str1:") and a["fingerprint"].startswith("str1:")


def test_queries(tmp_path):
    d = structure("""
module fx(input clk, rst_n, en, input [3:0] d, output reg [3:0] q);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else if (en) q <= d;
endmodule
""", tmp_path)
    q = sid(d, "q")
    assert names(d, Q.controls_of(d, q)) == ["clk", "en", "rst_n"]
    assert Q.registers_controlled_by(d, sid(d, "rst_n"), "reset") == [q]
    assert [x["kind"] for x in Q.drivers_of(d, q)] == ["procedural"]
    assert Q.loads_of(d, q) and Q.scc({1: {2}, 2: {1}, 3: set()}) == [[1, 2], [3]]
