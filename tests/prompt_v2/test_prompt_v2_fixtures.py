# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_fixtures.py
# Description : Prompt v2 golden fixtures, byte-exact prompt and sidecar (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""30 golden fixtures (AC-686 .. AC-745).

Each fixture runs the real chain RTL -> Semantic IR v2 -> Behavioral Semantics
v1 -> Structural Analysis v1 -> FSM Analysis v2 -> Prompt v2 and compares the
prompt and its sidecar byte for byte with ``golden/NN_<name>.txt|.json``
(identity, leakage metrics, truncation and uncertainty status included).
Expected output changes only with a documented review; regenerate with
``KF_PROMPT_V2_REGEN=1`` and review the diff.
"""

import json
import os

import pytest

from scripts.prompt_v2 import model as P
from tests.fsm.test_fsm_fixtures import RTL as FSM_RTL
from tests.fsm.test_fsm_register_boundary import RTL as RB_RTL
from tests.prompt_v2.helpers import GOLDEN, prompt_all

Z01 = """
module z01(input [1:0] sel, input [7:0] a, input [7:0] b, input [7:0] c, output reg [7:0] y, output z);
  always @* begin
    case (sel)
      2'd0: y = a;
      2'd1: y = b;
      default: y = c;
    endcase
  end
  assign z = (sel == 2'd3) ? a[0] : b[0];
endmodule
"""
H01 = """
module h01_leaf(input a, input b, output y);
  assign y = a & b;
endmodule
module h01(input clk, input x, input z, output y, output q);
  wire w;
  h01_leaf u_leaf(.a(x), .b(z), .y(w));
  missing_cell u_ext(.i(w), .o(q));
  assign y = w ^ x;
endmodule
"""
T02 = """
module t02(input clk, input rst_n, input go, input halt, output busy);
  localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] cs, ns;
  always @(posedge clk or negedge rst_n) if (!rst_n) cs <= A; else cs <= ns;
  always @* ns = (cs == A) ? (go ? B : A) : ((cs == B) ? (halt ? A : C) : A);
  assign busy = (cs != A);
endmodule
"""


def _big(n: int = 300) -> str:
    regs = "\n".join(f"  reg [7:0] stage_register_{i:03d};" for i in range(n))
    upd = "\n".join(f"      stage_register_{i:03d} <= stage_register_{i - 1:03d} ^ din;" if i else
                    "      stage_register_000 <= din;" for i in range(n))
    return f"""
module t01(input clk, input rst_n, input [7:0] din, input go, output reg [1:0] st, output [7:0] dout);
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
{regs}
  always @(posedge clk) begin
{upd}
  end
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= IDLE;
    else case (st) IDLE: if (go) st <= RUN; RUN: if (!go) st <= DONE; DONE: st <= IDLE; default: st <= IDLE; endcase
  assign dout = stage_register_{n - 1:03d};
endmodule
"""


# (number, name, module, RTL, what it covers) - AC-687 .. AC-716 in order
FIXTURES = [
    (1, "zero_fsm", "z01", Z01, "zero-FSM module (case + ternary combinational logic)"),
    (2, "two_process", "g01", FSM_RTL["g01"], "confirmed two-process FSM"),
    (3, "one_process", "g24", FSM_RTL["g24"], "confirmed one-process FSM (priority, later abort)"),
    (4, "one_bit", "g05", FSM_RTL["g05"], "one-bit FSM"),
    (5, "ambiguous", "g15", FSM_RTL["g15"], "ambiguous FSM (multiple drivers)"),
    (6, "unsupported", "g16", FSM_RTL["g16"], "unsupported FSM (function-call next value)"),
    (7, "localparam_encoding", "g12", FSM_RTL["g12"], "localparam state encoding"),
    (8, "enum_encoding", "g03", FSM_RTL["g03"], "enum state encoding"),
    (9, "implicit_enum", "g09", FSM_RTL["g09"], "implicit enum values"),
    (10, "custom_encoding", "g06", FSM_RTL["g06"], "custom encoding (literal values)"),
    (11, "one_hot", "g04", FSM_RTL["g04"], "one-hot encoding"),
    (12, "gray", "g10", FSM_RTL["g10"], "gray encoding"),
    (13, "explicit_hold", "g02", FSM_RTL["g02"], "explicit hold"),
    (14, "implicit_hold", "g23", FSM_RTL["g23"], "implicit hold (and graph-unreachable states)"),
    (15, "default_transition", "g13", FSM_RTL["g13"], "derived default transition, unknown target"),
    (16, "incomplete_domain", "g14", FSM_RTL["g14"], "incomplete state domain (unresolved constants)"),
    (17, "moore_output", "g22", FSM_RTL["g22"], "Moore output (registered) and module parameters"),
    (18, "mealy_output", "g20", FSM_RTL["g20"], "Mealy output"),
    (19, "fsm_actions", "g19", FSM_RTL["g19"], "FSM actions"),
    (20, "coupled_fsms", "g08", FSM_RTL["g08"], "coupled FSMs"),
    (21, "unresolved_hierarchy", "h01", H01, "resolved and unresolved child instances"),
    (22, "clock_reset", "g18", FSM_RTL["g18"], "clock / reset semantics (no reset: reachability unknown)"),
    (23, "enable", "g25", FSM_RTL["g25"], "enable semantics"),
    (24, "uncertainty", "g21", FSM_RTL["g21"], "uncertainty rendering (candidate, derived)"),
    (25, "guard_language", "r1", RB_RTL["r1"], "natural-language guards"),
    (26, "ternary_guard", "t02", T02, "ternary guard rendering"),
    (27, "case_default_guard", "g11", FSM_RTL["g11"], "case / default guards (casez wildcards unrendered)"),
    (28, "truncation", "t01", _big(), "size-budget truncation"),
    (29, "leakage_safe", "g07", FSM_RTL["g07"], "leakage-safe semantic rendering (counter, no FSM)"),
    (30, "identity", "g17", FSM_RTL["g17"], "deterministic Prompt / sidecar identity"),
]
IDS = [f"{n:02d}_{name}" for n, name, *_ in FIXTURES]


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = {}
    for n, name, module, src, _ in FIXTURES:
        res = prompt_all(src, tmp_path_factory.mktemp(f"pv2_{n:02d}"))
        out[f"{n:02d}_{name}"] = res[module][:2]
    return out


def _golden(key, text, sidecar):
    t, j = GOLDEN / f"{key}.txt", GOLDEN / f"{key}.json"
    if os.environ.get("KF_PROMPT_V2_REGEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
        j.write_text(P.dumps(sidecar), encoding="utf-8")
    return t.read_text(encoding="utf-8"), j.read_text(encoding="utf-8")


def test_suite_size_and_order():
    """AC-686 / AC-742: 30 independent fixtures, numbered in AC order."""
    assert [n for n, *_ in FIXTURES] == list(range(1, 31))
    assert len({src for *_, src, _ in FIXTURES}) == 30


@pytest.mark.parametrize("key", IDS)
def test_golden_prompt_and_sidecar(rendered, key):
    """AC-717 .. AC-723: byte-exact prompt, sidecar, identity, leakage, truncation and uncertainty."""
    text, sidecar = rendered[key]
    want_text, want_side = _golden(key, text, sidecar)
    assert text == want_text
    assert P.dumps(sidecar) == want_side
    assert sidecar["identity"] == P.identity(sidecar)
    assert sidecar["leakage"]["status"] == "PASS"


def test_specific_semantics(rendered):
    t = {k: v[0] for k, v in rendered.items()}
    s = {k: v[1] for k, v in rendered.items()}
    assert "## State machines" not in t["01_zero_fsm"] and s["01_zero_fsm"]["fsm"]["fsms"] == 0
    assert "two-process" in t["02_two_process"] and "IDLE -> RUN when start is 1" in t["02_two_process"]
    assert "status ambiguous" in t["05_ambiguous"] and "status unsupported" in t["06_unsupported"]
    assert "(implicit value)" in t["09_implicit_enum"] and "encoding gray" in t["12_gray"]
    assert "(explicit hold)" in t["13_explicit_hold"] and "(unreachable in the transition graph)" in t["14_implicit_hold"]
    assert "States: unresolved" in t["16_incomplete_domain"] and "an unknown state" in t["16_incomplete_domain"]
    assert "Output z: mealy, also depends on x" in t["18_mealy_output"]
    assert "Actions:" in t["19_fsm_actions"] and "Coupling: FSM 2 tests the state of FSM 1" in t["20_coupled_fsms"]
    assert "instance of missing_cell (unresolved)" in t["21_unresolved_hierarchy"]
    assert "Reachability from the reset state: unknown" in t["22_clock_reset"]
    assert "status candidate" in t["24_uncertainty"] and "[derived]" in t["24_uncertainty"]
    assert "A -> B when go is 1" in t["26_ternary_guard"]
    assert "matches no listed value" in t["27_case_default_guard"]
    tr = s["28_truncation"]["prompt"]
    assert tr["truncated"] and tr["original_bytes"] > P.BUDGET_BYTES >= tr["bytes"]
    assert "[truncated: Registers" in t["28_truncation"] and "## State machines" in t["28_truncation"]


def test_no_hdl_expressions_in_any_fixture(rendered):
    """AC-731 .. AC-733: no HDL syntax, no parser fields, natural-language guards only."""
    for key, (text, sidecar) in rendered.items():
        assert not P.HDL_SYNTAX_RE.search(text), key
        assert not P.PARSER_NOISE_RE.search(text), key
        assert sidecar["leakage"]["longest_run"] <= 6 and sidecar["leakage"]["overlap"] <= 0.2, key


def test_fixtures_are_reproducible(tmp_path):
    """AC-725 / AC-726 / AC-728: a fixture rendered in isolation, elsewhere, is byte-identical."""
    n, name, module, src, _ = FIXTURES[1]
    a = prompt_all(src, tmp_path / "a")[module]
    b = prompt_all(src, tmp_path / "x" / "y" / "b")[module]
    assert a[0] == b[0] and P.dumps(a[1]) == P.dumps(b[1])
    want = json.loads((GOLDEN / f"{n:02d}_{name}.json").read_text(encoding="utf-8"))
    assert want["identity"] == a[1]["identity"]
