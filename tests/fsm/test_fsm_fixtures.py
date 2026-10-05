# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_fixtures.py
# Description : FSM Analysis v2 golden fixtures and query API tests (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/fsm
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""25 golden FSM fixtures (AC-133 .. AC-157) through the real chain
RTL -> Semantic IR v2 -> Behavioral Semantics v1 -> Structural Analysis v1 -> FSM Analysis v2,
plus the query API (AC-223 .. AC-234) and determinism (AC-112 .. AC-117).

Every document produced here must pass ``validate_module`` (see ``helpers.fsm_all``).
"""

import json

import pytest

from scripts.fsm import analyzer as A
from scripts.fsm import model as F
from scripts.fsm import query as Q
from tests.fsm.helpers import by_reg, edges, fsm_all, only, rejected, state_names

RTL = {
    # G01 - two-process, localparam binary, async reset, case, implicit hold, Moore output
    "g01": """
module g01(input clk, input rst_n, input start, input done_i, output busy);
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  reg [1:0] state, state_nx;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) state <= IDLE; else state <= state_nx;
  always @* begin
    state_nx = state;
    case (state)
      IDLE: if (start) state_nx = RUN;
      RUN:  if (done_i) state_nx = DONE;
      DONE: state_nx = IDLE;
      default: state_nx = IDLE;
    endcase
  end
  assign busy = (state == RUN);
endmodule
""",
    # G02 - one-process, literal encoding, sync reset, nested if, explicit hold, derived else
    "g02": """
module g02(input clk, input rst, input a, input b, output reg [1:0] st);
  always @(posedge clk)
    if (rst) st <= 2'b00;
    else if (st == 2'b00) begin if (a) st <= 2'b01; else st <= st; end
    else if (st == 2'b01) begin if (b) st <= 2'b10; end
    else st <= 2'b00;
endmodule
""",
    # G03 - enum typedef with explicit custom values, unique case, rule B (no behavioral state candidate)
    "g03": """
module g03(input logic clk, input logic rst_n, input logic go, output logic ack);
  typedef enum logic [1:0] {S_IDLE = 2'd0, S_WAIT = 2'd1, S_ACK = 2'd3} st_t;
  st_t cur, nxt;
  always_ff @(posedge clk or negedge rst_n) if (!rst_n) cur <= S_IDLE; else cur <= nxt;
  always_comb begin
    nxt = cur;
    unique case (cur)
      S_IDLE: if (go) nxt = S_WAIT;
      S_WAIT: nxt = S_ACK;
      default: nxt = S_IDLE;
    endcase
  end
  assign ack = (cur == S_ACK);
endmodule
""",
    # G04 - one-hot, ternary next value, explicit self-transition
    "g04": """
module g04(input clk, input rst_n, input x, output y);
  localparam [2:0] A = 3'b001, B = 3'b010, C = 3'b100;
  reg [2:0] s;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= A;
    else case (s)
      A: s <= x ? B : A;
      B: s <= C;
      C: s <= A;
      default: s <= A;
    endcase
  assign y = s[2];
endmodule
""",
    # G05 - 1-bit FSM with named states and a Mealy output
    "g05": """
module g05(input clk, input rst_n, input in, output out);
  localparam S0 = 1'b0, S1 = 1'b1;
  reg q;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= S0;
    else case (q) S0: if (in) q <= S1; S1: if (!in) q <= S0; endcase
  assign out = (q == S1) & in;
endmodule
""",
    # G06 - irregular names (no state / next naming)
    "g06": """
module g06(input clk, input rst_n, input k, output reg [1:0] mode_q);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) mode_q <= 2'd3;
    else case (mode_q)
      2'd3: if (k) mode_q <= 2'd1;
      2'd1: mode_q <= 2'd2;
      default: mode_q <= 2'd3;
    endcase
endmodule
""",
    # G07 - counter with several constant loads and a name-only "state" register: no FSM
    "g07": """
module g07(input clk, input rst_n, input clr, input load, output reg [7:0] cnt, output reg [1:0] state);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) cnt <= 8'd0;
    else if (clr) cnt <= 8'd0;
    else if (load) cnt <= 8'hF0;
    else if (cnt == 8'hFF) cnt <= 8'd1;
    else cnt <= cnt + 8'd1;
  always @(posedge clk) state <= {clr, load};
endmodule
""",
    # G08 - two coupled FSMs (b's guard tests a's register); b is a literal 1-bit candidate
    "g08": """
module g08(input clk, input rst_n, input req, output grant);
  localparam [1:0] I = 2'd0, W = 2'd1, G = 2'd2;
  reg [1:0] a_st;
  reg       b_st;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) a_st <= I;
    else case (a_st) I: if (req) a_st <= W; W: a_st <= G; G: a_st <= I; default: a_st <= I; endcase
  always @(posedge clk or negedge rst_n)
    if (!rst_n) b_st <= 1'b0;
    else case (b_st) 1'b0: if (a_st == G) b_st <= 1'b1; 1'b1: if (!req) b_st <= 1'b0; endcase
  assign grant = b_st;
endmodule
""",
    # G09 - anonymous enum, implicit member values (IEEE 1800 6.19)
    "g09": """
module g09(input logic clk, input logic rst_n, input logic go, input logic stop, output logic run);
  enum logic [1:0] {OFF, ARM, ON} cs, ns;
  always_ff @(posedge clk or negedge rst_n) if (!rst_n) cs <= OFF; else cs <= ns;
  always_comb begin
    ns = cs;
    case (cs)
      OFF: if (go) ns = ARM;
      ARM: ns = ON;
      ON:  if (stop) ns = OFF;
      default: ns = OFF;
    endcase
  end
  assign run = (cs == ON);
endmodule
""",
    # G10 - Gray encoding
    "g10": """
module g10(input clk, input rst_n, input go, output reg [1:0] s);
  localparam [1:0] A = 2'b00, B = 2'b01, C = 2'b11, D = 2'b10;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= A;
    else case (s) A: if (go) s <= B; B: s <= C; C: s <= D; D: s <= A; endcase
endmodule
""",
    # G11 - casez over the state: wildcard labels leave the domain incomplete
    "g11": """
module g11(input clk, input rst_n, input a, output reg [2:0] st);
  localparam [2:0] P = 3'b001, Q = 3'b010, R = 3'b100;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= P;
    else casez (st) 3'b??1: if (a) st <= Q; 3'b?1?: st <= R; default: st <= P; endcase
endmodule
""",
    # G12 - multiple outgoing transitions from one state (if / else if)
    "g12": """
module g12(input clk, input rst_n, input a, input b, output busy);
  localparam [1:0] I = 2'd0, X = 2'd1, Y = 2'd2;
  reg [1:0] cs, ns;
  always @(posedge clk or negedge rst_n) if (!rst_n) cs <= I; else cs <= ns;
  always @* begin
    ns = cs;
    case (cs)
      I: if (a) ns = X; else if (b) ns = Y;
      X: ns = I;
      Y: if (!b) ns = I;
      default: ns = I;
    endcase
  end
  assign busy = (cs != I);
endmodule
""",
    # G13 - incomplete FSM: a data load gives an unknown target
    "g13": """
module g13(input clk, input rst_n, input load, input [1:0] din, output reg [1:0] st);
  localparam [1:0] S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= S0;
    else if (load) st <= din;
    else case (st) S0: st <= S1; S1: st <= S2; default: st <= S0; endcase
endmodule
""",
    # G14 - state constants that do not resolve (external names): candidate, no invented values
    "g14": """
module g14(input clk, input rst_n, input go, output reg [1:0] st);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= pkg_idle;
    else case (st) pkg_idle: if (go) st <= pkg_run; default: st <= pkg_idle; endcase
endmodule
""",
    # G15 - register written by two processes (bit slices): ambiguous
    "g15": """
module g15(input clk, input rst_n, input a, output reg [1:0] st);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st[0] <= 1'b0; else if (st[0] == 1'b0) st[0] <= a; else st[0] <= 1'b0;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st[1] <= 1'b0; else if (st[1] == 1'b0) st[1] <= 1'b1; else st[1] <= 1'b0;
endmodule
""",
    # G16 - next value through a function call: unsupported, never confirmed
    "g16": """
module g16(input clk, input rst_n, input a, output reg [1:0] st);
  function [1:0] nxt(input [1:0] s, input x); nxt = x ? s + 2'd1 : s; endfunction
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= 2'd0;
    else case (st) 2'd0: st <= nxt(st, a); 2'd1: st <= 2'd2; default: st <= 2'd0; endcase
endmodule
""",
    # G17 - "state" / "next_state" by name only: zero FSMs
    "g17": """
module g17(input clk, input [3:0] d, output reg [3:0] state, output reg [3:0] next_state);
  always @(posedge clk) state <= d;
  always @* next_state = d ^ 4'h5;
endmodule
""",
    # G18 - no reset: reachability unknown, quality medium
    "g18": """
module g18(input clk, input go, output reg [1:0] st);
  localparam [1:0] W = 2'd0, R = 2'd1, D = 2'd2;
  always @(posedge clk)
    case (st) W: if (go) st <= R; R: st <= D; D: st <= W; default: st <= W; endcase
endmodule
""",
    # G19 - actions: register / output updates per state
    "g19": """
module g19(input clk, input rst_n, input req, output reg ack, output reg [3:0] cnt);
  localparam [1:0] IDLE = 2'd0, WORK = 2'd1, DONE = 2'd2;
  reg [1:0] st;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin st <= IDLE; ack <= 1'b0; cnt <= 4'd0; end
    else case (st)
      IDLE: begin ack <= 1'b0; if (req) begin st <= WORK; cnt <= 4'd0; end end
      WORK: begin cnt <= cnt + 4'd1; if (cnt == 4'd7) st <= DONE; end
      DONE: begin ack <= 1'b1; st <= IDLE; end
      default: st <= IDLE;
    endcase
endmodule
""",
    # G20 - two-process 1-bit FSM with a Mealy output assigned in the next-state block
    "g20": """
module g20(input clk, input rst_n, input x, output reg z);
  localparam S0 = 1'b0, S1 = 1'b1;
  reg cs, ns;
  always @(posedge clk or negedge rst_n) if (!rst_n) cs <= S0; else cs <= ns;
  always @* begin
    ns = cs; z = 1'b0;
    case (cs) S0: if (x) ns = S1; S1: begin z = x; if (!x) ns = S0; end endcase
  end
endmodule
""",
    # G21 - 1-bit handshake flag with literal values: candidate (trivial state domain)
    "g21": """
module g21(input clk, input rst_n, input req, output reg ack);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) ack <= 1'b0; else if (ack) ack <= 1'b0; else if (req) ack <= 1'b1;
endmodule
""",
    # G22 - encoding through module parameters
    "g22": """
module g22 #(parameter [1:0] OFF = 2'd0, parameter [1:0] ON = 2'd1, parameter [1:0] ERR = 2'd2)
  (input clk, input rst_n, input e, input f, output reg [1:0] m);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) m <= OFF;
    else case (m) OFF: if (e) m <= ON; ON: if (f) m <= ERR; else if (!e) m <= OFF; ERR: m <= ERR; default: m <= OFF; endcase
endmodule
""",
    # G23 - graph-unreachable states
    "g23": """
module g23(input clk, input rst_n, input go, output reg [1:0] st);
  localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2, Z = 2'd3;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= A;
    else case (st) A: if (go) st <= B; B: st <= A; Z: st <= C; C: st <= A; default: st <= A; endcase
endmodule
""",
    # G24 - priority: a later abort assignment, unique case qualifier
    "g24": """
module g24(input clk, input rst_n, input a, input abort, output reg [1:0] st);
  localparam [1:0] I = 2'd0, R = 2'd1, F = 2'd2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= I;
    else begin
      unique case (st) I: if (a) st <= R; R: st <= F; F: st <= I; default: st <= I; endcase
      if (abort) st <= I;
    end
endmodule
""",
    # G25 - state register with an enable
    "g25": """
module g25(input clk, input rst_n, input en, input go, output reg [1:0] st);
  localparam [1:0] I = 2'd0, A = 2'd1, B = 2'd2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= I;
    else if (en) case (st) I: if (go) st <= A; A: st <= B; B: st <= I; default: st <= I; endcase
endmodule
""",
}


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    out = {}
    for name, src in RTL.items():
        res = fsm_all(src, tmp_path_factory.mktemp(name))
        out[name] = res[name][0]
        out[name + ":inputs"] = res[name][1]
    return out


def ev(f):
    return {e["code"] for e in f["evidence"]}


def names(docs, module, ids):
    sem = docs[module + ":inputs"][0]
    nm = {x["id"]: x["name"] for x in sem["ports"] + sem["signals"]}
    return [nm[i] for i in ids]


# ============================================================================= golden fixtures

def test_g01_two_process_binary(docs):
    f = only(docs["g01"])
    assert (f["status"], f["quality"], f["style"]) == ("confirmed", "high", "two_process")
    assert f["encoding"] == {"status": "explicit", "style": "binary", "width": 2, "source": "localparam"}
    assert state_names(f) == [(0, "IDLE"), (1, "RUN"), (2, "DONE")]
    assert edges(f) == [("*none", "0", "default"), ("*reset", "0", "reset"), ("0", "0", "implicit_hold"),
                        ("0", "1", "explicit"), ("1", "1", "implicit_hold"), ("1", "2", "explicit"),
                        ("2", "0", "explicit")]
    assert (f["reset"]["kind"], f["reset"]["polarity"]) == ("async", "active_low")
    assert f["reset"]["state"] == next(s["id"] for s in f["states"] if s["name"] == "IDLE")
    assert f["next_signal"]["name"] == "state_nx" and f["hold"] == "implicit"
    assert [(o["name"], o["kind"], o["registered"], o["sampled_sources"]) for o in f["outputs"]] == \
        [("busy", "moore", False, [])]                     # combinational Moore output (KF-DQ-011.1 AC-149)
    assert {"behavior_state_candidate", "closed_loop", "two_process_next_value", "reset_state"} <= ev(f)
    assert f["reachability"]["status"] == "known" and not f["reachability"]["unreachable"]


def test_g02_one_process_literal_sync_reset(docs):
    f = only(docs["g02"])
    assert (f["status"], f["quality"], f["style"]) == ("confirmed", "medium", "one_process")
    assert f["encoding"]["status"] == "inferred" and f["encoding"]["source"] == "literal"
    assert f["reset"]["kind"] == "sync" and f["hold"] == "mixed"
    assert ("0", "0", "explicit_hold") in edges(f) and ("1", "1", "implicit_hold") in edges(f)
    t = next(t for t in f["transitions"] if t["kind"] == "explicit"
             and edges({**f, "transitions": [t]}) == [("2", "0", "explicit")])
    assert t["status"] == "derived"                    # final else: complement of {0, 1} in a complete domain
    nested = next(t for t in f["transitions"] if edges({**f, "transitions": [t]}) == [("1", "2", "explicit")])
    assert [g["branch"] for g in nested["guard"] if g["role"] != "reset"] == ["else", "then", "then"]


def test_g03_enum_custom_rule_b(docs):
    f = only(docs["g03"])
    assert (f["status"], f["quality"]) == ("confirmed", "high")
    assert "behavior_state_candidate" not in ev(f) and "predicate_over_register" in ev(f)
    assert f["encoding"] == {"status": "explicit", "style": "custom", "width": 2, "source": "enum"}
    assert state_names(f) == [(0, "S_IDLE"), (1, "S_WAIT"), (3, "S_ACK")]
    assert all(s["constant"]["kind"] == "enum_member" and s["constant"]["ref"].startswith("sem1:") for s in f["states"])
    assert {g["qualifier"] for t in f["transitions"] for g in t["guard"] if g["kind"] == "case"} == {"unique"}


def test_g04_one_hot_ternary_self_loop(docs):
    f = only(docs["g04"])
    assert f["encoding"]["style"] == "one_hot" and f["quality"] == "high"
    assert ("1", "1", "explicit") in edges(f) and ("1", "2", "explicit") in edges(f)
    tern = [g for t in f["transitions"] for g in t["guard"] if g["kind"] == "ternary"]
    assert tern and {g["branch"] for g in tern} == {"then", "else"} and all(g["predicate"] is None for g in tern)


def test_g05_one_bit_mealy(docs):
    f = only(docs["g05"])
    assert (f["status"], f["register"]["width"], f["encoding"]["style"]) == ("confirmed", 1, "binary")
    assert [(o["name"], o["kind"], o["registered"]) for o in f["outputs"]] == [("out", "mealy", False)]
    assert [names(docs, "g05", o["other_sources"]) for o in f["outputs"]] == [["in"]]   # AC-148 unchanged
    assert "trivial_state_domain" not in ev(f)         # named states are evidence


def test_g06_irregular_names(docs):
    f = only(docs["g06"])
    assert f["register"]["name"] == "mode_q" and f["status"] == "confirmed" and "name_hint" not in ev(f)
    assert f["encoding"]["style"] == "custom" and state_names(f) == [(1, None), (2, None), (3, None)]
    assert f["states"][2]["reset"] is True


def test_g07_counter_is_not_an_fsm(docs):
    d = docs["g07"]
    assert d["fsms"] == [] and d["counts"]["fsms"] == 0
    assert rejected(d) == [("cnt", "arithmetic_feedback"), ("state", "name_only")]


def test_g08_coupled_fsms(docs):
    d = docs["g08"]
    a, b = by_reg(d, "a_st"), by_reg(d, "b_st")
    assert (a["status"], b["status"], b["quality"]) == ("confirmed", "candidate", "low")
    assert "trivial_state_domain" in ev(b)
    (c,) = d["couplings"]
    assert (c["from_fsm"], c["to_fsm"], c["kind"]) == (a["id"], b["id"], "predicate")
    assert all(r.startswith("str1:") for r in c["refs"])
    assert len(d["fsms"]) == 2                         # never merged


def test_g09_anonymous_enum_implicit_values(docs):
    f = only(docs["g09"])
    assert state_names(f) == [(0, "OFF"), (1, "ARM"), (2, "ON")]
    assert all(s["constant"]["implicit"] for s in f["states"])
    assert f["register"]["width"] is None and f["encoding"]["source"] == "enum"   # Semantic IR width not trusted
    assert docs["g09"]["notes"] == {"anonymous_enum_registers": 1, "implicit_enum_states": 3}


def test_g10_gray(docs):
    f = only(docs["g10"])
    assert f["encoding"]["style"] == "gray" and f["quality"] == "high"


def test_g11_casez_incomplete(docs):
    f = only(docs["g11"])
    assert {g["kind"] for t in f["transitions"] for g in t["guard"]} >= {"casez"}
    assert f["encoding"]["status"] == "unknown" and f["reachability"]["status"] == "unknown"
    assert {u["kind"] for u in f["unknowns"]} >= {"incomplete_domain", "unknown_source"}
    assert f["quality"] == "medium"


def test_g12_multiple_outgoing(docs):
    f = only(docs["g12"])
    out = [t for t in Q.outgoing(f, "I") if t["kind"] == "explicit"]
    assert sorted(Q.state(f, t["target"])["name"] for t in out) == ["X", "Y"]
    assert len({json.dumps(t["guard"], sort_keys=True) for t in out}) == 2


def test_g13_unknown_target(docs):
    f = only(docs["g13"])
    assert ("0", "*unknown", "explicit") in edges(f)
    assert [u["kind"] for u in f["unknowns"]] == ["unknown_target"]
    assert (f["status"], f["quality"], f["reachability"]["status"]) == ("confirmed", "medium", "unknown")


def test_g14_unresolved_constants_are_not_invented(docs):
    f = only(docs["g14"])
    assert (f["status"], f["quality"]) == ("candidate", "low")
    assert f["states"] == [] and f["encoding"]["style"] == "unknown"
    assert "unresolved_state_values" in ev(f) and {"incomplete_domain", "unresolved_constant"} <= {u["kind"] for u in f["unknowns"]}


def test_g15_multiple_drivers_ambiguous(docs):
    fs = docs["g15"]["fsms"]
    assert fs and all((f["status"], f["quality"]) == ("ambiguous", "ambiguous") for f in fs)
    assert all("multiple_driver" in {u["kind"] for u in f["unknowns"]} for f in fs)


def test_g16_function_next_value_unsupported(docs):
    f = only(docs["g16"])
    assert (f["status"], f["quality"]) == ("unsupported", "unsupported")
    assert ("0", "*unknown", "explicit") in edges(f)


def test_g17_name_only_registers(docs):
    d = docs["g17"]
    assert d["fsms"] == [] and rejected(d) == [("state", "name_only")]


def test_g18_no_reset(docs):
    f = only(docs["g18"])
    assert f["reset"]["kind"] == "none" and f["reset"]["state"] is None
    assert f["reachability"] == {"start": None, "basis": "graph", "status": "unknown", "reachable": [], "unreachable": []}
    assert f["quality"] == "medium" and all(s["reachability"] == "unknown" for s in f["states"])


def test_g19_actions(docs):
    d = docs["g19"]
    f = only(d)
    acts = {(Q.state(f, a["state"])["name"], next(s["name"] for s in d["fsms"][0]["outputs"] if s["signal"] == a["signal"]),
             a["kind"]) for a in f["actions"]}
    assert ("DONE", "ack", "output") in acts and ("IDLE", "ack", "output") in acts and ("WORK", "cnt", "output") in acts
    assert all(any(g["tests_state"] for g in a["guard"]) for a in f["actions"])
    assert ("ack", "no_state_predicate") in rejected(d)


def test_g19_registered_outputs_are_moore(docs):
    """KF-DQ-011.1 AC-145 .. AC-147, AC-151, AC-152: ack and cnt are registers - temporal boundaries."""
    f = only(docs["g19"])
    got = {o["name"]: (o["kind"], o["registered"], names(docs, "g19", o["sampled_sources"]), o["other_sources"])
           for o in f["outputs"]}
    assert got == {"ack": ("moore", True, [], []),          # clock / reset / state only (AC-151)
                   "cnt": ("moore", True, ["req"], [])}     # samples req (enable condition, E1); action evidence
    assert all(o["state_sources"] == [f["register"]["signal"]] for o in f["outputs"])


def test_g20_mealy_from_next_state_block(docs):
    f = only(docs["g20"])
    assert f["style"] == "two_process" and [(o["name"], o["kind"]) for o in f["outputs"]] == [("z", "mealy")]
    assert f["outputs"][0]["registered"] is False          # `output reg` assigned in always @* is combinational
    (a,) = f["actions"]
    assert Q.state(f, a["state"])["name"] == "S1" and a["kind"] == "output"


def test_g21_literal_flag_is_a_candidate(docs):
    f = only(docs["g21"])
    assert (f["status"], f["quality"]) == ("candidate", "low") and "trivial_state_domain" in ev(f)


def test_g22_parameter_encoding(docs):
    f = only(docs["g22"])
    assert f["encoding"] == {"status": "explicit", "style": "binary", "width": 2, "source": "parameter"}
    assert ("2", "2", "explicit") in edges(f)          # ERR: m <= ERR is a self-transition by constant


def test_g23_graph_unreachable(docs):
    f = only(docs["g23"])
    assert sorted(s["name"] for s in Q.states(f, "graph_unreachable")) == ["C", "Z"]
    assert Q.reachability(f)["predicate_feasibility"] == "not_analyzed"


def test_g24_priority_order(docs):
    f = only(docs["g24"])
    ts = Q.transitions(f)
    prios = [t["priority"] for t in ts if t["priority"] is not None]
    assert prios == sorted(prios)
    explicit = [t for t in ts if t["kind"] == "explicit"]
    abort = [t for t in explicit if not any(g["tests_state"] for g in t["guard"])]   # if (abort) st <= I
    case = [t for t in explicit if t not in abort]
    assert len(abort) == 3 and case and min(t["priority"] for t in abort) > max(t["priority"] for t in case)
    assert {Q.state(f, t["source"])["name"] for t in abort} == {"I", "R", "F"}
    # R and F are always written by the case statement: no hold there, whatever abort does
    holds = {Q.state(f, t["source"])["name"] for t in ts if t["kind"] == "implicit_hold"}
    assert holds == {"I"}


def test_g25_enable(docs):
    f = only(docs["g25"])
    (en,) = f["enable"]
    assert en["enable"].startswith("beh1:") and en["signals"]
    assert any(g["role"] == "enable" for t in f["transitions"] for g in t["guard"])


# ============================================================================= cross-cutting

def test_every_fixture_has_a_document_and_zero_fsm_documents_are_valid(docs):
    for name in RTL:
        d = docs[name]
        assert d["schema"] == {"name": F.SCHEMA_NAME, "version": 2}
        assert d["counts"]["fsms"] == len(d["fsms"])


def test_names_never_decide(docs):
    """AC-009/010: renaming every signal keeps statuses, encodings and graph shapes."""
    import re
    import tempfile
    from pathlib import Path

    src = re.sub(r"\bstate_nx\b", "q7", re.sub(r"\bstate\b", "zz", RTL["g01"]))
    with tempfile.TemporaryDirectory() as d:
        doc = fsm_all(src, Path(d))["g01"][0]
    a, b = only(docs["g01"]), only(doc)
    assert (a["status"], a["quality"], a["encoding"], edges(a)) == (b["status"], b["quality"], b["encoding"], edges(b))
    assert a["fingerprint"] == b["fingerprint"]
    assert "name_hint" in ev(a) and "name_hint" not in ev(b)


def test_determinism_and_identity(docs):
    for name in RTL:
        d = docs[name]
        again = A.analyze(*docs[name + ":inputs"])
        assert F.dumps(again) == F.dumps(d)
        assert d["id"] == F.document_id(d) and d["fingerprint"] == A.fingerprint(d)
        assert "/tmp" not in F.dumps(d)


# ============================================================================= query API

def test_query_api(docs):
    d = docs["g01"]
    (f,) = Q.fsms(d)
    assert Q.fsms(d, status="candidate") == [] and Q.fsms(d, quality="high") == [f]
    assert Q.fsm(d, "state") == Q.fsm(d, f["id"]) == Q.fsm(d, f["register"]["signal"]) == f
    with pytest.raises(KeyError):
        Q.fsm(d, "nope")
    reg = Q.state_register(f)
    assert reg["register"]["name"] == "state" and reg["next_signal"]["name"] == "state_nx" and reg["style"] == "two_process"
    assert [s["name"] for s in Q.states(f)] == ["IDLE", "RUN", "DONE"]
    assert Q.state(f, 1)["name"] == "RUN" and Q.state(f, "RUN") == Q.state(f, Q.state(f, "RUN")["id"])
    assert sorted(t["kind"] for t in Q.incoming(f, "IDLE")) == ["default", "explicit", "implicit_hold", "reset"]
    assert all(t["source"] == Q.state(f, "RUN")["id"] for t in Q.outgoing(f, "RUN"))
    assert Q.outgoing(f, "*reset")[0]["kind"] == "reset"
    t = next(t for t in Q.outgoing(f, "IDLE") if t["kind"] == "explicit")
    g = Q.guard(f, t["id"])
    assert g["path"] == t["guard"] and "start" in g["rendered"] and g["path"][0]["kind"] == "case"
    enc = Q.encoding(f)
    assert enc["style"] == "binary" and [v["name"] for v in enc["values"]] == ["IDLE", "RUN", "DONE"]
    assert [o["name"] for o in Q.outputs(f, "moore")] == ["busy"] and Q.outputs(f, "mealy") == []
    assert Q.actions(f) == [] and Q.quality(f)["quality"] == "high"
    r = Q.reachability(f)
    assert r["basis"] == "graph" and r["predicate_feasibility"] == "not_analyzed"
    assert Q.couplings(d) == [] and Q.rejected(docs["g07"], "arithmetic_feedback")[0]["name"] == "cnt"
    # results are copies: mutating them never changes the document (AC-234)
    Q.states(f)[0]["name"] = "X"
    assert Q.states(f)[0]["name"] == "IDLE"
    assert Q.transitions(f) == Q.transitions(json.loads(json.dumps(f)))
