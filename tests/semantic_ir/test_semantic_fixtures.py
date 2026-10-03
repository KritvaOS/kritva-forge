# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_semantic_fixtures.py
# Description : KF-DQ-008 representative-RTL semantic assertions for Semantic IR v2
#
# Component   : Kritva Forge
# Module      : tests/semantic_ir
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Representative RTL coverage (acceptance criteria sections 6 and 16).

Each case is a small module plus *semantic* assertions on the extracted
document (entities, types, widths, expression structure, assignment kinds,
conditions / cases, instances, declarations vs references), not a parser
snapshot.  Every document must also pass the schema validator.  The same
constructs are measured on the canonical IP corpus by
``tests/data/test_semantic_ir_corpus.py``.
"""

from scripts.semantic_ir import model as M
from scripts.semantic_ir.validator import validate_module
from tests.semantic_ir.helpers import assigns_to, by_name, extract, refs, sig_id, stmts, uses, walk

COVERAGE = {}                      # section 16 construct -> test


def covers(*constructs):
    def deco(fn):
        for c in constructs:
            COVERAGE.setdefault(c, []).append(fn.__name__)
        return fn
    return deco


def _doc(tmp_path, src, module="fx"):
    docs = extract(src, tmp_path)
    for name, d in docs.items():
        assert validate_module(d) == [], (name, validate_module(d)[:3])
    return docs[module]


# ----------------------------------------------------------------------------- module / provenance

@covers("simple combinational logic", "continuous assignments")
def test_simple_combinational_continuous(tmp_path):
    d = _doc(tmp_path, "module fx(input a, input b, output y); assign y = a & b; endmodule\n")
    (a,) = assigns_to(d, "y")
    assert a["kind"] == "continuous" and a["operator"] == "=" and a["process"] is None
    assert a["value"]["op"] == "binary" and a["value"]["operator"] == "&"
    assert [x["name"] for x in (a["value"]["left"], a["value"]["right"])] == ["a", "b"]   # operand order
    assert sorted(a["reads"]) == sorted([sig_id(d, "a"), sig_id(d, "b")]) and a["writes"] == [sig_id(d, "y")]
    assert d["extraction"] == "complete" and d["unsupported"] == []


def test_module_identity_versions_and_provenance(tmp_path):
    d = _doc(tmp_path, "module fx(input a, output y); assign y = a; endmodule\n")
    m = d["module"]
    assert M.MODULE_ID_RE.fullmatch(m["module_id"]) and M.ID_RE.fullmatch(m["id"])
    assert m["source"]["path"] == "raw/rtl/original/fx/fx.sv" and len(m["source"]["sha256"]) == 64
    assert m["loc"] == {"file": "raw/rtl/original/fx/fx.sv", "line": 1, "column": 1, "offset": 0}
    v = d["versions"]
    assert (v["schema"], v["identity"], v["node_identity"]) == (2, 1, 1)
    assert v["parser"].startswith("pyslang ") and v["compatibility"] == {"normalized_ir": 1}
    assert all(i.startswith("sem1:") for i in (n["id"] for n in walk(d) if "id" in n and n.get("op") != "opaque"))


# ----------------------------------------------------------------------------- declarations / types

@covers("parameterized modules", "vectors")
def test_parameters_and_vector_widths(tmp_path):
    d = _doc(tmp_path, """
module fx #(parameter W = 8, parameter logic [3:0] K = 4'd3, localparam D = $clog2(W))
           (input [W-1:0] a, output [D:0] n);
  logic [2*W-1:0] wide;
  logic [7:0] mem [0:3];
  assign n = a[D:0];
endmodule
""")
    w, k, dd = (by_name(d["parameters"], x) for x in ("W", "K", "D"))
    assert (w["kind"], w["value"], w["width"], w["port_param"]) == ("parameter", 8, None, True)
    assert (k["type"], k["signed"], k["width"], k["value"]) == ("logic [3:0]", False, 4, 3)
    assert (dd["kind"], dd["value"]) == ("localparam", 3)
    assert by_name(d["ports"], "a")["width"] == 8 and by_name(d["ports"], "n")["width"] == 4
    assert by_name(d["signals"], "wide")["width"] == 16
    mem = by_name(d["signals"], "mem")
    assert mem["width"] == 8 and [u["text"] for u in mem["unpacked"]] == ["[0:3]"]
    rng = by_name(d["ports"], "a")["packed"][0]
    assert rng["left"]["op"] == "binary" and refs(rng["left"]) == ["W"] and rng["left_value"] == 7
    assert {r["source"] for r in uses(d, "W")} >= {by_name(d["ports"], "a")["id"], by_name(d["signals"], "wide")["id"]}


@covers("signed/unsigned signals")
def test_signed_unsigned(tmp_path):
    d = _doc(tmp_path, """
module fx(input signed [7:0] s, input [7:0] u, output signed [8:0] y, output [8:0] z);
  assign y = s + $signed(u);
  assign z = $unsigned(s) + u;
endmodule
""")
    assert by_name(d["ports"], "s")["signed"] is True and by_name(d["ports"], "u")["signed"] is False
    assert by_name(d["ports"], "y")["signed"] is True
    calls = [n for n in walk(assigns_to(d, "y")[0]["value"]) if n.get("op") == "call"]
    assert [(c["name"], c["system"]) for c in calls] == [("$signed", True)] and refs(calls[0]["args"][0]) == ["u"]


def test_net_variable_kinds_and_port_defaults(tmp_path):
    d = _doc(tmp_path, """
module fx(input wire a, input logic b = 1'b1, output reg q, output logic r);
  wire w; reg rg; logic lg; integer i;
  assign w = a; always @* begin rg = b; lg = w; r = lg; q = rg; i = 0; end
endmodule
""")
    kinds = {p["name"]: (p["kind"], p["type"]) for p in d["ports"] + d["signals"]}
    assert kinds["w"][0] == "net" and kinds["rg"] == ("variable", "reg") and kinds["lg"] == ("variable", "logic")
    assert kinds["i"] == ("variable", "integer") and by_name(d["signals"], "i")["width"] == 32
    assert by_name(d["ports"], "q")["type"] == "reg"
    assert by_name(d["ports"], "b")["default"]["op"] == "literal" and by_name(d["ports"], "a")["default"] is None
    assert {p["direction"] for p in d["ports"]} == {"input", "output"}


def test_enums_and_typedefs(tmp_path):
    d = _doc(tmp_path, """
module fx(input clk, output logic busy);
  typedef enum logic [1:0] {IDLE, RUN} st_t;
  st_t st;
  always_ff @(posedge clk) st <= (st == IDLE) ? RUN : IDLE;
  assign busy = st == RUN;
endmodule
""")
    td = by_name(d["typedefs"], "st_t")
    assert td["kind"] == "enum" and [m["name"] for m in td["members"]] == ["IDLE", "RUN"]
    assert by_name(d["signals"], "st")["type"] == "st_t"
    kinds = {r["symbol"]: r["ref_kind"] for r in d["references"]}
    assert kinds["IDLE"] == kinds["RUN"] == "enum_member"


# ----------------------------------------------------------------------------- expressions

@covers("concatenation/indexing/part-selects")
def test_concat_replicate(tmp_path):
    d = _doc(tmp_path, """
module fx(input [3:0] a, input [3:0] b, output [11:0] y, output [7:0] r);
  assign y = {a, b, 4'h0};
  assign r = {2{a}};
endmodule
""")
    y = assigns_to(d, "y")[0]["value"]
    assert y["op"] == "concat" and [i.get("name") or i["op"] for i in y["items"]] == ["a", "b", "literal"]
    r = assigns_to(d, "r")[0]["value"]
    assert r["op"] == "replicate" and r["count"]["value"] == 2 and r["items"][0]["name"] == "a"


@covers("concatenation/indexing/part-selects")
def test_index_part_selects(tmp_path):
    d = _doc(tmp_path, """
module fx(input [15:0] a, input [3:0] i, output b, output [3:0] p, output [3:0] q, output [3:0] r);
  assign b = a[i];
  assign p = a[7:4];
  assign q = a[i +: 4];
  assign r = a[15 -: 4];
endmodule
""")
    b = assigns_to(d, "b")[0]
    assert b["value"]["op"] == "index" and b["value"]["base"]["name"] == "a" and b["value"]["index"]["name"] == "i"
    assert [assigns_to(d, n)[0]["value"]["mode"] for n in ("p", "q", "r")] == [":", "+:", "-:"]


def test_ternary_unary_literal_cast(tmp_path):
    d = _doc(tmp_path, """
module fx(input s, input [7:0] a, output [7:0] y, output z, output [15:0] w);
  assign y = s ? ~a : 8'hzF;
  assign z = !s;
  assign w = 16'(a);
endmodule
""")
    v = assigns_to(d, "y")[0]["value"]
    assert v["op"] == "ternary" and v["cond"]["name"] == "s" and v["then"]["op"] == "unary"
    assert v["else"]["op"] == "literal" and v["else"]["has_xz"] is True and v["else"]["width"] == 8
    assert assigns_to(d, "z")[0]["value"]["operator"] == "!"
    assert assigns_to(d, "w")[0]["value"]["op"] == "cast"


# ----------------------------------------------------------------------------- assignments

@covers("sequential logic", "nonblocking assignments")
def test_sequential_nonblocking(tmp_path):
    d = _doc(tmp_path, """
module fx(input clk, input rst_n, input [7:0] d, output reg [7:0] q1, output reg [7:0] q2);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin q1 <= 8'h00; q2 <= 8'h00; end
    else begin q1 <= d; q2 <= q1; end
endmodule
""")
    (p,) = d["processes"]
    assert p["kind"] == "always" and p["sensitivity"] == "list"
    assert [(e["edge"], e["expr"]["name"]) for e in p["events"]] == [("posedge", "clk"), ("negedge", "rst_n")]
    assert {a["kind"] for a in d["assignments"]} == {"nonblocking"}
    assert all(a["operator"] == "<=" and a["process"] == p["id"] for a in d["assignments"])
    assert sorted(p["assignments"]) == sorted(a["id"] for a in d["assignments"])
    q2 = [a for a in assigns_to(d, "q2") if a["reads"]][0]
    assert q2["reads"] == [sig_id(d, "q1")]
    assert "role" not in p                                                    # process roles: KF-DQ-009


@covers("blocking assignments", "simple combinational logic")
def test_blocking_always_comb(tmp_path):
    d = _doc(tmp_path, """
module fx(input logic [3:0] a, output logic [3:0] y);
  logic [3:0] t;
  always_comb begin t = a + 4'd1; y = t; end
endmodule
""")
    (p,) = d["processes"]
    assert (p["kind"], p["sensitivity"], p["events"]) == ("always_comb", "implicit", [])
    t, y = assigns_to(d, "t")[0], assigns_to(d, "y")[0]
    assert t["kind"] == y["kind"] == "blocking" and y["reads"] == [sig_id(d, "t")]


def test_assignment_kinds_enumerated(tmp_path):
    d = _doc(tmp_path, """
module fx(input clk, input [3:0] a, output reg [3:0] c, output [3:0] y);
  wire [3:0] w = a;
  integer n;
  always @(posedge clk) begin c += a; n++; end
  assign y = w;
endmodule
""")
    kinds = {(a["target"]["name"], a["kind"], a["operator"]) for a in d["assignments"]}
    assert ("w", "declaration", "=") in kinds and ("y", "continuous", "=") in kinds
    assert ("c", "compound", "+=") in kinds and ("n", "compound", "++") in kinds
    assert {a["kind"] for a in d["assignments"]} <= set(M.ASSIGN_KINDS)
    inc = next(a for a in d["assignments"] if a["operator"] == "++")
    assert inc["value"] is None and inc["reads"] == inc["writes"]


# ----------------------------------------------------------------------------- conditions / cases

@covers("conditional logic")
def test_conditions_index_and_guards(tmp_path):
    d = _doc(tmp_path, """
module fx(input s1, input s2, input a, input b, input c, output reg y);
  always @* begin
    if (s1) begin
      if (s2) y = a;
      else    y = b;
    end else y = c;
  end
endmodule
""")
    outer, inner = d["conditions"]
    assert outer["else"] is not None and inner["else"] is not None
    assert outer["owner"] == inner["owner"] == d["processes"][0]["id"]
    ya, yb, yc = assigns_to(d, "y")
    assert [g["branch"] for g in ya["guards"]] == ["then", "then"]
    assert [(g["statement"], g["branch"]) for g in yb["guards"]] == [(outer["id"], "then"), (inner["id"], "else")]
    assert yc["guards"] == [{"statement": outer["id"], "branch": "else"}]
    pred = {r["id"]: r for r in d["references"]}[outer["predicate_references"][0]]
    assert pred["symbol"] == "s1" and pred["usage"] == "read" and pred["source"] == outer["id"]


@covers("case logic")
def test_case_casez_casex_default_qualifiers(tmp_path):
    d = _doc(tmp_path, """
module fx(input [1:0] sel, input [3:0] req, input [2:0] op, input [3:0] a, output reg [3:0] y,
          output reg [1:0] g, output reg z);
  always @* unique case (sel)
    2'd0: y = a;
    2'd1, 2'd2: y = ~a;
    default: y = 4'h0;
  endcase
  always @* priority casez (req)
    4'b???1: g = 2'd0;
    4'b??10: g = 2'd1;
    default: g = 2'd3;
  endcase
  always @* casex (op)
    3'b1xx: z = 1'b1;
    default: z = 1'b0;
  endcase
endmodule
""")
    c1, c2, c3 = d["cases"]
    assert [(c["case_kind"], c["qualifier"]) for c in d["cases"]] == \
        [("case", "unique"), ("casez", "priority"), ("casex", None)]
    assert [i["labels"] for i in c1["items"]] == [1, 2] and c1["default"] is not None
    sel = {r["id"]: r for r in d["references"]}[c1["selector_references"][0]]
    assert sel["symbol"] == "sel"
    tree = stmts(d["processes"][1], "case")[0]
    assert tree["items"][0]["exprs"][0]["has_xz"] is True
    dflt = [a for a in assigns_to(d, "y") if a["guards"][-1]["branch"] == "default"]
    assert len(dflt) == 1 and dflt[0]["guards"][-1]["statement"] == c1["id"]
    item1 = [a for a in assigns_to(d, "y") if a["guards"][-1].get("item") == 1]
    assert len(item1) == 1


# ----------------------------------------------------------------------------- instances

@covers("module instances")
def test_instances_resolved_unresolved(tmp_path):
    docs = extract("""
module leaf #(parameter W = 1) (input [W-1:0] a, output [W-1:0] y); assign y = ~a; endmodule
module fx(input [3:0] x, output [3:0] z, output n);
  wire [3:0] mid;
  leaf #(.W(4)) u0 (.a(x), .y(mid));
  leaf #(4) u1 (mid, z);
  vendor_cell u2 (.i(x[0]), .o(n));
endmodule
""", tmp_path)
    d = docs["fx"]
    assert validate_module(d) == []
    u0, u1, u2 = d["instances"]
    assert (u0["module"], u0["resolved"], u0["target_module_id"]) == ("leaf", True, docs["leaf"]["module"]["module_id"])
    assert [(p["name"], p["value"]["value"]) for p in u0["parameters"]] == [("W", 4)]
    assert [(c["kind"], c["port"], c["direction"]) for c in u0["connections"]] == \
        [("named", "a", "input"), ("named", "y", "output")]
    assert [(c["kind"], c["port"]) for c in u1["connections"]] == [("ordered", "a"), ("ordered", "y")]
    assert (u2["resolved"], u2["target_module_id"]) == (False, None)
    assert [c["direction"] for c in u2["connections"]] == ["unknown", "unknown"]
    conn = [r for r in uses(d, "mid") if r["usage"] == "connect"]
    assert {r["source"] for r in conn} == {u0["id"], u1["id"]}


# ----------------------------------------------------------------------------- references

def test_declarations_and_references_are_distinct(tmp_path):
    d = _doc(tmp_path, """
module fx #(parameter N = 2) (input [N-1:0] a, output [N-1:0] y);
  wire [N-1:0] t;
  assign t = a;
  assign y = t;
endmodule
""")
    decl_ids = {x["id"] for s in ("parameters", "ports", "signals") for x in d[s]}
    ref_ids = {r["id"] for r in d["references"]}
    assert decl_ids.isdisjoint(ref_ids)
    t = sig_id(d, "t")
    t_uses = [r for r in d["references"] if r["target"] == t]
    assert sorted(r["usage"] for r in t_uses) == ["read", "write"]
    assert all(r["loc"]["file"] == "raw/rtl/original/fx/fx.sv" and r["loc"]["line"] for r in d["references"])
    assert d["counts"]["references"] == len(d["references"]) and d["counts"]["unresolved_references"] == 0


def test_unresolved_symbol_is_explicit(tmp_path):
    d = _doc(tmp_path, "module fx(output y); assign y = pkg::C; endmodule\n")
    r = next(r for r in d["references"] if r["symbol"] == "pkg::C")
    assert (r["ref_kind"], r["target"]) == ("unresolved", None)
    assert d["counts"]["unresolved_references"] == 1


def test_generate_blocks_scope_references(tmp_path):
    d = _doc(tmp_path, """
module fx #(parameter N = 4) (input [N-1:0] a, output [N-1:0] y);
  genvar g;
  generate for (g = 0; g < N; g = g + 1) begin : bit_g
    assign y[g] = ~a[g];
  end endgenerate
endmodule
""")
    loop = next(g for g in d["generates"] if g["kind"] == "loop")
    assert loop["genvar"] == "g" and loop["representation"] == "source-level"
    ya = assigns_to(d, "y")[0]
    assert ya["generate"] in {g["id"] for g in d["generates"]} and "bit_g" in ya["scope"]
    assert {r["ref_kind"] for r in d["references"] if r["symbol"] == "g"} == {"genvar"}


def test_unsupported_construct_is_explicit(tmp_path):
    d = _doc(tmp_path, """
module fx(input clk, input a, output reg y);
  always @(posedge clk) begin
    wait (a);
    y <= a;
  end
endmodule
""")
    assert d["extraction"] == "partial"
    (u,) = d["unsupported"]
    assert (u["construct"], u["level"], u["loc"]["line"]) == ("WaitStatement", "statement", 4)
    assert len(assigns_to(d, "y")) == 1


def test_section_16_coverage_is_complete():
    required = {"simple combinational logic", "sequential logic", "parameterized modules", "vectors",
                "signed/unsigned signals", "continuous assignments", "blocking assignments",
                "nonblocking assignments", "conditional logic", "case logic", "module instances",
                "concatenation/indexing/part-selects"}
    assert required <= set(COVERAGE), required - set(COVERAGE)
