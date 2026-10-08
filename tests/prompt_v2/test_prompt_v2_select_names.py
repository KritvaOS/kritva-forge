# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_select_names.py
# Description : Prompt v2 rendering of unresolved index / part-select / member references (KF-DQ-012.1)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""KF-DQ-012.1: an unresolved reference whose source text contains an index or
part select (``req_fifo[0].haddr``, found by the open-source reference corpus
in ycr1 ``ycr_dmem_ahb`` / ``ycr_imem_ahb``) is rendered in natural language,
never as raw HDL text; the validator rejects HDL select syntax explicitly.
"""

import pytest

from scripts.prompt_v2 import model as P
from scripts.prompt_v2.validator import text_problems, validate_module
from tests.prompt_v2.helpers import prompt_all

SRC = """
module s01(input clk, input [31:0] a, input w, output [31:0] y, output [1:0] z, output q);
  typedef struct packed { logic [31:0] haddr; logic hwrite; } req_t;
  req_t req_fifo [0:1];
  always @(posedge clk) begin req_fifo[0].haddr <= a; req_fifo[0].hwrite <= w; req_fifo[1] <= req_fifo[0]; end
  assign y = req_fifo[0].haddr;
  assign z = req_fifo[0].haddr[1:0];
  assign q = req_fifo[1].hwrite;
endmodule
"""


@pytest.mark.parametrize("raw,text", [
    ("req_fifo[0].haddr", "field haddr of element 0 of req_fifo"),
    ("req_fifo[0].haddr[1:0]", "bits 1 to 0 of field haddr of element 0 of req_fifo"),
    ("x[i]", "bit i of x"),
    ("a[3:0]", "bits 3 to 0 of a"),
    ("m[0][1]", "bit 1 of element 0 of m"),
    ("foo", "foo"),
    ("hart_runctrl.redirect", "hart_runctrl.redirect"),     # dotted member names are names (unchanged)
    ("x[a+1]", None),                                        # not representable -> caller renders unresolved
    ("[0]", None),
    ("", None),
])
def test_select_text(raw, text):
    assert P.select_text(raw) == text


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    return prompt_all(SRC, tmp_path_factory.mktemp("sel"), validate=False)["s01"]


def test_struct_array_selects_render_in_natural_language(rendered):
    text, sidecar, inputs = rendered
    assert "- y (continuous) depends on field haddr of element 0 of req_fifo" in text
    assert "- z (continuous) depends on bits 1 to 0 of field haddr of element 0 of req_fifo" in text
    assert "- q (continuous) depends on field hwrite of element 1 of req_fifo" in text
    assert not P.HDL_SELECT_RE.search(text) and "[" not in text.replace("[derived]", "").replace("[unknown]", "")
    assert validate_module(text, P.dumps(sidecar), inputs) == []


def test_validator_rejects_raw_select_syntax(rendered):
    text = rendered[0].replace("field haddr of element 0 of req_fifo", "req_fifo[0].haddr", 1)
    codes = {c for c, _ in text_problems(text)}
    assert "hdl_syntax" in codes


@pytest.mark.parametrize("line", ["- x [derived]", "[truncated: Registers 1/2 records]", "- a -> b [unknown]"])
def test_select_check_ignores_vocabulary_markers(line):
    assert not P.HDL_SELECT_RE.search(line)
