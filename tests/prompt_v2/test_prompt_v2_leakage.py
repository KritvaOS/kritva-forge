# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_leakage.py
# Description : Answer-leakage metric leakage-v1 and classifier rtl-sim-v1 unit tests (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Frozen tokenizer ``sv-lex-v1``, metric ``leakage-v1`` (M1 .. M3) and
classifier ``rtl-sim-v1`` (AC-287 .. AC-368, AC-469 .. AC-507).

The sensitivity cases show the metric separates canonical hardware
vocabulary (names alone never fail) from copied source structure (a pasted
transition statement or the whole module fails).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prompt_v2 import classify as C
from scripts.prompt_v2 import leakage as L
from scripts.prompt_v2 import model as P

RTL = """// controller
module ctl(input clk, input rst_n, input start, output busy);
  /* states */
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) state <= IDLE;
    else if (state == IDLE && start) state <= RUN;
    else state <= IDLE;
  assign busy = (state == RUN);
endmodule
"""
CANON = {"ctl", "clk", "rst_n", "start", "busy", "IDLE", "RUN", "state"}


def test_versions_are_frozen():
    """AC-288, AC-306 .. AC-308, AC-347: versioned contract."""
    assert (L.TOKENIZER_VERSION, L.METRIC_VERSION, L.THRESHOLD_VERSION) == ("sv-lex-v1", "leakage-v1", "thresholds-v1")
    assert (L.OVERLAP_MAX, L.RUN_MAX, L.N) == (0.20, 6, 4)
    assert C.CLASSIFIER_VERSION == "rtl-sim-v1" and (C.NEAR_DUPLICATE, C.STRUCTURAL_SIMILARITY) == (0.70, 0.30)


def test_tokenizer_lexes_systemverilog_and_drops_comments():
    """AC-289 .. AC-291, AC-301."""
    toks = L.tokens("a <= 8'hFF; // c\n /* x y */ b == 'z && c >>> 2'b1?;")
    assert toks == ["a", "<=", "8'hFF", ";", "b", "==", "'z", "&&", "c", ">>>", "2'b1?", ";"]
    assert "controller" not in L.tokens(RTL) and "states" not in L.tokens(RTL)


def test_normalization_maps_names_drops_keywords_and_punctuation():
    """AC-294 .. AC-297."""
    out = L.normalized(L.tokens("always @(posedge clk) if (start) state <= RUN; x <= 1'b0;"), CANON)
    assert out == ["ID", "ID", "ID", "ID", "x", "1'b0"]


def test_names_alone_are_not_leakage():
    """AC-325 .. AC-332: module, port, signal, state and parameter names never fail on their own."""
    prompt = "Module ctl. Ports clk rst_n start busy. Register state. States IDLE RUN. IDLE -> RUN when start is 1."
    m = L.measure(prompt, RTL, CANON)
    assert m["status"] == "PASS" and m["overlap"] == 0.0 and m["longest_run"] <= 1


def test_copied_statement_is_detected():
    """AC-299 .. AC-302: a pasted transition statement is caught by the longest run."""
    m = L.measure("The next state is: else if (state == IDLE && start) state <= RUN;", RTL, CANON)
    assert m["status"] == "FAIL" and m["longest_run"] > L.RUN_MAX
    assert "==" in m["longest_run_tokens"] and "&&" in m["longest_run_tokens"]


def test_whole_module_fails_on_both_axes():
    m = L.measure(RTL, RTL, CANON)
    assert m["status"] == "FAIL" and m["longest_run"] > L.RUN_MAX and m["raw_overlap"] == 1.0


def test_separator_only_difference_still_matches():
    """M3: list separators do not break a run."""
    a = L.measure("if (state == IDLE && start) state <= RUN", RTL, CANON)
    b = L.measure("if (state == IDLE && start) state <= RUN ;;,", RTL, CANON)
    assert a["longest_run"] == b["longest_run"] > L.RUN_MAX


def test_name_only_run_does_not_count():
    """M3: a block made only of canonical identifiers is not a structural run."""
    m = L.measure("clk rst_n start busy", "module ctl(clk rst_n start busy); endmodule", CANON)
    assert m["longest_run"] == 0


def test_metric_reports_counts_and_versions():
    """AC-303 .. AC-308, AC-342."""
    m = L.measure("IDLE -> RUN when start is 1", RTL, CANON)
    assert set(m) >= {"tokenizer_version", "metric_version", "threshold_version", "thresholds", "prompt_tokens",
                      "completion_tokens", "prompt_ngrams", "overlapping_ngrams", "overlap", "longest_run",
                      "longest_run_tokens", "raw_overlap", "status"}


def test_metric_is_deterministic_across_processes(tmp_path):
    """AC-324, AC-348 .. AC-350: the same numbers under another locale and hash seed."""
    code = ("import json,sys; from scripts.prompt_v2 import leakage as L; "
            f"print(json.dumps(L.measure({RTL!r}[:200], {RTL!r}, set({sorted(CANON)!r})), sort_keys=True))")
    root = Path(__file__).resolve().parents[2]
    outs = set()
    for seed, loc in (("1", "C"), ("777", "C.UTF-8")):
        env = dict(os.environ, PYTHONHASHSEED=seed, LC_ALL=loc, PYTHONDONTWRITEBYTECODE="1")
        outs.add(subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True,
                                text=True, check=True).stdout)
    assert len(outs) == 1


def test_canonical_names_include_child_ports():
    """M1."""
    sem = {"module": {"name": "top"}, "ports": [{"name": "a"}], "signals": [{"name": "w"}],
           "parameters": [{"name": "W"}], "typedefs": [{"members": [{"name": "S0"}]}],
           "instances": [{"name": "u0", "module": "leaf"}]}
    st = {"instances": [{"name": "u1", "module": "cell"}], "connections": [{"port": "din"}, {"port": None}]}
    assert L.canonical_names(sem, st) == {"top", "a", "w", "W", "S0", "u0", "leaf", "u1", "cell", "din"}


def test_prompt_vocabulary_has_no_hdl_operators():
    """AC-309 .. AC-316: the natural-language guard vocabulary is HDL free."""
    for word in ("is", "is not", "and", "or", "not"):
        assert not P.HDL_SYNTAX_RE.search(f"when x {word} 1")
    for raw in ("state == IDLE && start", "a <= b", "always_ff", "x ? y : z"):
        assert P.HDL_SYNTAX_RE.search(raw)


# ----------------------------------------------------------------------------- rtl-sim-v1 classifier
def test_renaming_cannot_hide_a_duplicate():
    """AC-505: alpha-renaming makes a renamed copy identical."""
    renamed = RTL.replace("state", "cur").replace("start", "go").replace("ctl", "other")
    assert C.renamed_tokens(RTL) == C.renamed_tokens(renamed)
    assert C.similarity(RTL, renamed) == 1.0 and C.classify_score(1.0) == "near_duplicate"


def test_unrelated_modules_are_informational():
    other = ("module m(input [7:0] a, input [7:0] b, input [2:0] op, output reg [8:0] s);\n"
             "  function [8:0] f; input [7:0] x; f = {x[0], x[7:1], 1'b0}; endfunction\n"
             "  always @* begin\n    case (op)\n      3'd0: s = a + b;\n      3'd1: s = a - b;\n"
             "      3'd2: s = {1'b0, a & b} | f(a);\n      3'd3: s = {a[3:0], b[7:4], 1'b1} ^ 9'h1ff;\n"
             "      3'd4: s = {1'b0, ~a} + {8'd0, b[0]};\n      3'd5: s = f(b) >> 2;\n"
             "      default: s = 9'd0;\n    endcase\n  end\nendmodule\n")
    score = C.similarity(RTL, other)
    assert score < C.STRUCTURAL_SIMILARITY and C.classify_score(score) == "informational"


@pytest.mark.parametrize("score,cls", [(0.70, "near_duplicate"), (0.6999, "structural_similarity"),
                                       (0.30, "structural_similarity"), (0.2999, "informational"),
                                       (0.0, "informational")])
def test_classification_boundaries(score, cls):
    assert C.classify_score(score) == cls


def _report(score=0.9):
    cls = C.classify_score(score)
    g = {"id": "grp1:x", "classification": cls, "metric": {"value": score}}
    return {"schema": {"name": C.SCHEMA_NAME, "version": C.SCHEMA_VERSION}, "classifier_version": C.CLASSIFIER_VERSION,
            "thresholds": {"near_duplicate": C.NEAR_DUPLICATE, "structural_similarity": C.STRUCTURAL_SIMILARITY},
            "groups": [g], "unresolved_near_duplicates": ["grp1:x"] if cls == "near_duplicate" else []}


def test_classification_validation():
    """AC-787 / AC-788: wrong version, wrong class or a hidden near_duplicate fail."""
    assert C.validate(_report()) == []
    r = _report(); r["classifier_version"] = "rtl-sim-v0"
    assert any("classifier version" in p for p in C.validate(r))
    r = _report(); r["groups"][0]["classification"] = "informational"
    assert any("disagrees" in p for p in C.validate(r))
    r = _report(); r["unresolved_near_duplicates"] = []
    assert any("unresolved_near_duplicates" in p for p in C.validate(r))
    r = _report(); r["thresholds"]["near_duplicate"] = 0.9
    assert any("thresholds" in p for p in C.validate(r))
