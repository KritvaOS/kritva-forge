# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : model.py
# Description : Prompt v2 schema constants, vocabularies, layout and identity (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : prompt_v2
# Layer       : Prompt Generation
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 contract (``kritva-forge-prompt`` version 2).

One prompt text and one JSON sidecar per canonical module and variant:

    generated/prompt/v2/<ip>/<module>.<variant>.txt
    generated/prompt/v2/<ip>/<module>.<variant>.json

The only variant is ``behavior_aware``.  Prompts are derived from the
persisted Semantic IR v2, Behavioral Semantics v1, Structural Analysis v1
and FSM Analysis v2 documents of the module and never from RTL; the
module's canonical source text is read only by the answer-leakage check.

Identity: ``pv2:`` + the first 16 hex digits of the sha256 of the canonical
sidecar without its ``identity`` field (non-recursive).  The sidecar records
the sha256 of the prompt text, so the identity covers the prompt bytes.
"""

from __future__ import annotations

import hashlib
import json
import re

SCHEMA_NAME = "kritva-forge-prompt"
SCHEMA_VERSION = 2
GENERATOR_VERSION = 1
IDENTITY_VERSION = 1
IDENTITY_PREFIX = "pv2:"
GENERATOR = "kritva-forge scripts/prompt_v2 v1"

# Upstream contracts consumed (AC-044, AC-051 .. AC-062; FSM Analysis v2 per amendment A1).
SEMANTIC_IR_VERSION = 2
SEMANTIC_IDENTITY_VERSION = 1
BEHAVIOR_VERSION = 1
BEHAVIOR_IDENTITY_VERSION = 1
STRUCTURAL_VERSION = 1
STRUCTURAL_IDENTITY_VERSION = 1
STRUCTURAL_ANALYZER_VERSION = 1
FSM_VERSION = 2
FSM_IDENTITY_VERSION = 1
FSM_ANALYZER_VERSION = 2
UPSTREAM = {
    "semantic_ir": ("kritva-forge-semantic-ir", SEMANTIC_IR_VERSION, SEMANTIC_IDENTITY_VERSION, "normalized/semantic_ir/v2"),
    "behavior": ("kritva-forge-behavioral-semantics", BEHAVIOR_VERSION, BEHAVIOR_IDENTITY_VERSION, "normalized/behavior/v1"),
    "structural": ("kritva-forge-structural-analysis", STRUCTURAL_VERSION, STRUCTURAL_IDENTITY_VERSION,
                   "normalized/structural/v1"),
    "fsm": ("kritva-forge-fsm-analysis", FSM_VERSION, FSM_IDENTITY_VERSION, "normalized/fsm/v2"),
}

# Layout (AC-401 .. AC-412).
OUTPUT_DIR = "generated/prompt/v2"
VARIANTS = ("behavior_aware",)
DEFAULT_VARIANT = "behavior_aware"
REPORT_PATH = "analysis/reports/prompt_v2_report.json"
CLASSIFICATION_REPORT_PATH = "analysis/reports/prompt_leakage_classification.json"

# Size budget (AC-369 .. AC-400).
BUDGET_BYTES = 32768

# Section order and truncation policy (AC-372 .. AC-378, amendment A8).
SECTIONS = ("Module", "Clocks and resets", "Registers", "Combinational logic", "State machines", "Submodules")
TRUNCATION_ORDER = ("Submodules", "Combinational logic", "Registers", "State machines")
NEVER_TRUNCATED = ("Module", "Clocks and resets")
TRUNCATION_NOTICE = "[truncated: {section} {emitted}/{total} records]"
TRUNCATION_RE = re.compile(r"^\[truncated: (Submodules|Combinational logic|Registers|State machines) (\d+)/(\d+) records\]$")

PREAMBLE = ("Write synthesizable Verilog/SystemVerilog RTL for the hardware module specified below. "
            "The specification describes behavior and structure, not source code.")

# Uncertainty vocabulary (AC-271 .. AC-286).
UNCERTAINTY = ("unknown", "ambiguous", "candidate", "unsupported", "unresolved", "derived")
MARKERS = {
    "[derived]": "derived",
    "[unknown]": "unknown",
    "(candidate)": "candidate",
    "(unresolved)": "unresolved",
    "an unknown state": "unknown",
    "unknown width": "unknown",
    "an unresolved value": "unresolved",
    "status candidate": "candidate",
    "status ambiguous": "ambiguous",
    "status unsupported": "unsupported",
    "States: unresolved": "unresolved",
    "a condition on": "unknown",
    "priority unknown": "unknown",
    "an unrendered value": "unknown",
    "an unknown condition": "unknown",
    "an unresolved signal": "unresolved",
}
BRACKET_MARKERS = ("[derived]", "[unknown]")
FSM_STATUS = ("confirmed", "candidate", "ambiguous", "unsupported")

# Natural-language vocabulary (AC-074, AC-075, AC-310 .. AC-316).
COMPARISON = {"==": "is", "===": "is", "!=": "is not", "!==": "is not", "<": "is less than", "<=": "is at most",
              ">": "is greater than", ">=": "is at least"}
NEGATED = {"is": "is not", "is not": "is", "is less than": "is at least", "is at most": "is greater than",
           "is greater than": "is at most", "is at least": "is less than"}

# HDL syntax that must never appear in a prompt (AC-065 .. AC-070, AC-317 .. AC-322).
HDL_SYNTAX_RE = re.compile(
    r"(<=|==|!=|&&|\|\||\?|\b(always|always_ff|always_comb|always_latch|assign|begin|endmodule|endcase|"
    r"posedge|negedge)\b)")
PARSER_NOISE_RE = re.compile(r"\b(node_id|syntax_type|BufferID|SyntaxKind|SyntaxNode)\b|\b(offset|buffer)\s*[:=]\s*\d")
ABS_PATH_RE = re.compile(r"(^|[\s\"'=:(,])(/(home|tmp|mnt|Users|workspace|root|var)/|[A-Za-z]:\\)")

ID_RE = re.compile(r"pv2:[0-9a-f]{16}")
SHA_RE = re.compile(r"[0-9a-f]{64}")


def prompt_rel(ip: str, module: str, variant: str = DEFAULT_VARIANT) -> str:
    return f"{OUTPUT_DIR}/{ip}/{module}.{variant}.txt"


def sidecar_rel(ip: str, module: str, variant: str = DEFAULT_VARIANT) -> str:
    return f"{OUTPUT_DIR}/{ip}/{module}.{variant}.json"


def dumps(doc: dict) -> str:
    """Canonical sidecar serialisation: sorted keys, two-space indent, UTF-8, trailing newline."""
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def identity(sidecar: dict) -> str:
    """``pv2:`` + sha256 of the canonical sidecar without ``identity`` (AC-045, AC-046)."""
    body = {k: v for k, v in sidecar.items() if k != "identity"}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return IDENTITY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def width_text(width) -> str:
    if not isinstance(width, int):
        return "unknown width"
    return "1 bit" if width == 1 else f"{width} bits"
