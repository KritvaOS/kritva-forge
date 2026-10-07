# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_validator.py
# Description : Prompt v2 validator negative tests, module level (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 validator - negative tests AC-747 .. AC-775, AC-789 .. AC-794 (module level).

A reference corpus (several fixture modules in one source file) is staged
once; each test corrupts a copy of one prompt / sidecar pair - re-signing the
sidecar where the test targets a single rule, so that exactly that rule is
exercised - and asserts the intended problem code.  Corpus, stale, manifest,
compatibility and dataset-boundary negatives (AC-776 .. AC-788, AC-795 ..
AC-798) are in ``test_prompt_v2_pipeline.py``.  Everything fails closed.
"""

import copy
import json
import shutil

import pytest

from scripts.prompt_v2 import leakage as L
from scripts.prompt_v2 import model as P
from scripts.prompt_v2 import render as R
from scripts.prompt_v2.validator import text_problems, validate_module
from tests.fsm.test_fsm_fixtures import RTL as FSM_RTL
from tests.prompt_v2.helpers import prompt_root
from tests.prompt_v2.test_prompt_v2_fixtures import H01

SRC = "\n".join([FSM_RTL["g19"], FSM_RTL["g08"], FSM_RTL["g15"], FSM_RTL["g16"], FSM_RTL["g22"], H01])


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    root = prompt_root(SRC, tmp_path_factory.mktemp("pv2val"))
    R.write_all(root)
    return root


@pytest.fixture
def root(staged, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(staged, dest)
    return dest


def pair(root, module):
    text = (root / P.prompt_rel("fx", module)).read_text(encoding="utf-8")
    side = (root / P.sidecar_rel("fx", module)).read_text(encoding="utf-8")
    return text, side, R.load_inputs(root, "fx", module)


def codes(problems):
    return {c for c, _ in problems}


def resign(text, side, inputs):
    """A sidecar consistent with ``text`` (sha, size, leakage, identity) so only the targeted rule fails."""
    sc = json.loads(side) if isinstance(side, str) else copy.deepcopy(side)
    sc["prompt"]["sha256"] = P.sha256_text(text)
    sc["prompt"]["bytes"] = len(text.encode("utf-8"))
    sc["leakage"] = L.measure(text, inputs["source_text"],
                              L.canonical_names(inputs["docs"]["semantic_ir"], inputs["docs"]["structural"]))
    sc["identity"] = P.identity(sc)
    return P.dumps(sc)


def fails(text, side, inputs, code):
    got = validate_module(text, side, inputs)
    assert got, "validation unexpectedly passed"
    assert code in codes(got), got[:6]


def test_reference_corpus_is_valid(root):
    for m in ("g19", "g08", "g15", "g16", "g22", "h01", "h01_leaf"):
        text, side, inputs = pair(root, m)
        assert validate_module(text, side, inputs) == [], m


# ---------------------------------------------------------------- AC-747 .. AC-750 missing inputs
@pytest.mark.parametrize("layer", ["semantic_ir", "behavior", "structural", "fsm"])
def test_747_750_missing_input(root, layer):
    (root / R.upstream_rel(layer, "fx", "g19")).unlink()
    with pytest.raises(R.PromptError, match=f"missing {layer} input"):
        R.load_inputs(root, "fx", "g19")


# ---------------------------------------------------------------- AC-751 .. AC-754 stale upstream sha
@pytest.mark.parametrize("layer", ["semantic_ir", "behavior", "structural", "fsm"])
def test_751_754_stale_upstream_sha(root, layer):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["inputs"][layer]["sha256"] = "0" * 64
    fails(text, resign(text, sc, inputs), inputs, "stale")


def test_751_upstream_revision_chain(root):
    """A Semantic IR change under the downstream documents refuses generation (AC-060)."""
    p = root / R.upstream_rel("semantic_ir", "fx", "g19")
    d = json.loads(p.read_text())
    d["generator"]["note"] = "edited"
    p.write_text(json.dumps(d))
    with pytest.raises(R.PromptError, match="stale semantic_ir revision"):
        R.load_inputs(root, "fx", "g19")


def test_754_fsm_document_changed(root):
    p = root / R.upstream_rel("fsm", "fx", "g19")
    d = json.loads(p.read_text())
    d["notes"]["edited"] = 1
    p.write_text(json.dumps(d))
    text, side, inputs = pair(root, "g19")
    fails(text, side, inputs, "stale")


def test_755_malformed_sidecar(root):
    text, _, inputs = pair(root, "g19")
    fails(text, "{not json", inputs, "schema")
    fails(text, json.dumps({"schema": 1}), inputs, "required")


def test_756_identity_mismatch(root):
    text, side, inputs = pair(root, "g19")
    other = json.loads(pair(root, "g08")[1])["identity"]
    sc = json.loads(side)
    sc["identity"] = other
    fails(text, P.dumps(sc), inputs, "identity")


def test_757_content_mismatch(root):
    text, side, inputs = pair(root, "g19")
    fails(text.replace("IDLE -> WORK", "IDLE -> DONE"), side, inputs, "mismatch")


def test_758_unsupported_schema_version(root):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["schema"]["version"] = 1
    fails(text, resign(text, sc, inputs), inputs, "schema")
    sc = json.loads(side)
    sc["inputs"]["fsm"]["schema_version"] = 1                     # FSM v1 is obsolete (A1)
    fails(text, resign(text, sc, inputs), inputs, "schema")


def test_759_unsupported_variant(root):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["variant"] = "interface_only"
    fails(text, resign(text, sc, inputs), inputs, "variant")
    with pytest.raises(R.PromptError, match="unknown prompt variant"):
        R.render(inputs, "interface_only")


def test_760_invalid_identity(root):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["identity"] = "pv2:xyz"
    fails(text, P.dumps(sc), inputs, "identity")


def test_761_missing_provenance(root):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    del sc["inputs"]["fsm"]
    fails(text, resign(text, sc, inputs), inputs, "provenance")
    sc = json.loads(side)
    del sc["source"]
    fails(text, P.dumps(sc), inputs, "required")


def test_762_absolute_path(root):
    text, side, inputs = pair(root, "g19")
    t = text + "Source: /home/user/rtl/g19.v\n"
    fails(t, resign(t, side, inputs), inputs, "absolute_path")


def test_763_parser_metadata(root):
    text, side, inputs = pair(root, "g19")
    t = text + "node_id 4711\n"
    fails(t, resign(t, side, inputs), inputs, "parser_metadata")


def test_764_complete_rtl_statement(root):
    text, side, inputs = pair(root, "g19")
    t = text + "always @(posedge clk) cnt <= cnt + 4'd1;\n"
    fails(t, resign(t, side, inputs), inputs, "hdl_syntax")


def test_765_excessive_4gram_overlap(root):
    text, side, inputs = pair(root, "g19")
    t = text + inputs["source_text"]
    got = validate_module(t, resign(t, side, inputs), inputs)
    assert "leakage" in codes(got)
    assert json.loads(resign(t, side, inputs))["leakage"]["overlap"] > L.OVERLAP_MAX


def test_766_excessive_contiguous_run(root):
    text, side, inputs = pair(root, "g19")
    t = text + "Note: WORK : begin cnt <= cnt + 4'd1 ; if ( cnt == 4'd7 ) st <= DONE\n"
    got = validate_module(t, resign(t, side, inputs), inputs)
    assert "leakage" in codes(got)
    assert json.loads(resign(t, side, inputs))["leakage"]["longest_run"] > L.RUN_MAX


def test_767_invalid_threshold_version(root):
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["leakage"]["threshold_version"] = "thresholds-v0"
    sc["identity"] = P.identity(sc)
    fails(text, P.dumps(sc), inputs, "leakage")
    sc = json.loads(side)
    sc["versions"]["leakage_thresholds"] = "thresholds-v0"
    fails(text, resign(text, sc, inputs), inputs, "leakage")


# ---------------------------------------------------------------- AC-768 .. AC-775 fabricated facts
def _fabricated(root, module, old, new):
    text, side, inputs = pair(root, module)
    assert old in text, old
    t = text.replace(old, new, 1)
    fails(t, resign(t, side, inputs), inputs, "fabricated")


def test_768_fabricated_state(root):
    _fabricated(root, "g19", "DONE = 2", "DONE = 2, ABORT = 3")


def test_769_fabricated_transition(root):
    _fabricated(root, "g19", "- DONE -> IDLE\n", "- DONE -> IDLE\n- DONE -> WORK when req is 1\n")


def test_770_fabricated_reset_value(root):
    _fabricated(root, "g19", "reset by rst_n to 0; controlled by st", "reset by rst_n to 5; controlled by st")


def test_771_fabricated_parameter_value(root):
    _fabricated(root, "g22", "- ON, default 1", "- ON, default 9")


def test_772_fabricated_hierarchy_child(root):
    _fabricated(root, "h01", "- u_leaf:", "- u_fake: instance of fake_cell\n- u_leaf:")


def test_773_candidate_to_confirmed(root):
    _fabricated(root, "g08", "FSM 2: state register b_st (1 bit); status candidate",
                "FSM 2: state register b_st (1 bit); status confirmed")


def test_774_ambiguous_to_confirmed(root):
    _fabricated(root, "g15", "status ambiguous", "status confirmed")


def test_775_unsupported_to_confirmed(root):
    _fabricated(root, "g16", "status unsupported", "status confirmed")


# ---------------------------------------------------------------- AC-789 .. AC-794
def test_789_nondeterministic_ordering(root):
    text, side, inputs = pair(root, "g19")
    head, rest = text.split("\n## Registers\n", 1)
    regs, tail = rest.split("\n## State machines\n", 1)
    t = head + "\n## State machines\n" + tail.rstrip("\n") + "\n\n## Registers\n" + regs.rstrip("\n") + "\n"
    fails(t, resign(t, side, inputs), inputs, "ordering")


def test_790_nondeterministic_identity(root):
    text, side, inputs = pair(root, "g19")
    t1, s1 = R.render(inputs)
    t2, s2 = R.render(R.load_inputs(root, "fx", "g19"))
    assert (t1, P.dumps(s1)) == (t2, P.dumps(s2)) == (text, side)
    sc = json.loads(side)
    sc["leakage"]["prompt_tokens"] += 1                                # identity no longer recomputable
    fails(text, P.dumps(sc), inputs, "identity")


def test_791_relocation_and_absolute_path_in_sidecar(root, tmp_path):
    moved = tmp_path / "elsewhere" / "deeper" / "kritva-forge-data"
    shutil.copytree(root, moved)
    for m in ("g19", "h01"):
        a, b = R.build(root, "fx", m), R.build(moved, "fx", m)
        assert a[0] == b[0] and P.dumps(a[1]) == P.dumps(b[1])
    text, side, inputs = pair(root, "g19")
    sc = json.loads(side)
    sc["source"]["path"] = str(root / sc["source"]["path"])
    got = validate_module(text, resign(text, sc, inputs), inputs)
    assert {"absolute_path", "provenance"} & codes(got)


def test_792_truncation_without_metadata(root):
    text, side, inputs = pair(root, "g19")
    lines = text.split("\n")
    i = lines.index("## Registers")
    t = "\n".join(lines[:i + 1] + ["[truncated: Registers 0/3 records]"] + lines[i + 4:])
    fails(t, resign(t, side, inputs), inputs, "truncation")


def test_793_prompt_exceeds_budget(root):
    text, side, inputs = pair(root, "g19")
    t = text + ("Note: padding line for the size test\n" * 1000)
    fails(t, resign(t, side, inputs), inputs, "size")


def test_794_invalid_uncertainty_vocabulary(root):
    text, side, inputs = pair(root, "g19")
    t = text.replace("- DONE -> IDLE\n", "- DONE -> IDLE [probably]\n")
    fails(t, resign(t, side, inputs), inputs, "vocabulary")
    t = text.replace("status confirmed", "status likely")
    assert "vocabulary" in codes(text_problems(t))


def test_preamble_is_part_of_the_variant(root):
    """D5: the fixed preamble is part of behavior_aware; removing it is an ordering failure."""
    text, side, inputs = pair(root, "g19")
    t = text.split("\n", 1)[1]
    fails(t, resign(t, side, inputs), inputs, "ordering")
