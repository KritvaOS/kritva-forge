# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : model.py
# Description : Behavioral Semantics v1 schema constants, enumerations and identities (KF-DQ-009)
#
# Component   : Kritva Forge
# Module      : behavior
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 contract (``kritva-forge-behavioral-semantics`` version 1).

One JSON document per canonical module at
``<data-root>/normalized/behavior/v1/<ip>/<module>.json``, derived only from
the module's Semantic IR v2 document (``normalized/semantic_ir/v2``), which is
never modified.

Identity namespace ``beh``, version 1: every behavioral object has
``id = "beh1:" + sha256("kf-beh", "v1", category, anchor, qualifier)[:16]``
where ``anchor`` is a Semantic IR v2 ``sem1:`` identity (process, signal,
statement or assignment) - so behavioral identities are stable across runs and
checkout locations and change only when the RTL changes.
"""

from __future__ import annotations

import hashlib
import json
import re

SCHEMA_NAME = "kritva-forge-behavioral-semantics"
SCHEMA_VERSION = 1
IDENTITY_VERSION = 1
IDENTITY_PREFIX = f"beh{IDENTITY_VERSION}:"
SEMANTIC_IR_VERSION = 2                     # consumed Semantic IR schema version
SEMANTIC_IDENTITY_VERSION = 1               # consumed Semantic IR identity version (sem1:)
ANALYZER = "kritva-forge scripts/behavior v1"
OUTPUT_SUBDIR = "behavior/v1"
OUTPUT_DIR = f"normalized/{OUTPUT_SUBDIR}"  # <data-root>/<OUTPUT_DIR>/<ip>/<module>.json
REPORT_PATH = "analysis/reports/behavior_report.json"

ID_RE = re.compile(r"beh1:[0-9a-f]{16}")
SEM_RE = re.compile(r"sem1:[0-9a-f]{16}")
MODULE_ID_RE = re.compile(r"mod1:[0-9a-f]{16}")

ROLES = ("sequential", "combinational", "latch", "initialization", "generic", "unknown", "ambiguous")
CONFIDENCE = ("high", "medium", "low", "unknown")
EDGES = ("posedge", "negedge", "edge")
STATUS = ("confirmed", "candidate", "ambiguous")
POLARITY = ("active_high", "active_low", "unknown")
RESET_KINDS = ("async", "sync")
HOLD_KINDS = ("none", "explicit", "implicit", "mixed", "ambiguous")
UPDATE_KINDS = ("unconditional", "conditional", "case", "mixed", "reset_only", "ambiguous")
COMPLETENESS = ("complete", "conditional", "incomplete", "ambiguous")
LATCH_STATUS = ("explicit", "inferred", "possible", "none", "ambiguous")
LEAF_KINDS = ("reset", "update", "hold_explicit", "hold_implicit")
VALUE_KINDS = ("constant", "self", "expression", "none")
BRANCHES = ("then", "else", "item", "default", "body")
CANDIDATE_KINDS = ("register_candidate", "state_candidate", "next_value_candidate")

# Evidence codes.  ``name_hint`` is descriptive only: it can never be the sole
# evidence of a non-unknown classification (criteria section 25).
EVIDENCE = (
    "keyword_always_ff", "keyword_always_comb", "keyword_always_latch", "keyword_always",
    "keyword_initial", "keyword_final",
    "edge_event", "level_event", "implicit_sensitivity", "no_event_control", "mixed_edge_level_events",
    "complete_sensitivity", "incomplete_sensitivity", "procedural_timing", "opaque_statement",
    "nonblocking_assignments", "blocking_assignments", "mixed_assignment_kinds", "no_assignments",
    "complete_assignment", "conditional_assignment", "incomplete_assignment", "ambiguous_assignment",
    "keyword_event_conflict",
    "event_signal_not_read", "event_signal_read_in_body", "event_expression_not_a_signal",
    "reset_tested_first", "reset_branch_constant", "reset_branch_not_constant", "edge_polarity_match",
    "edge_polarity_mismatch", "reset_in_event_list", "reset_not_in_event_list", "else_branch_present",
    "nonblocking_update", "blocking_update", "self_assignment", "missing_branch", "case_without_default",
    "guarded_update", "unconditional_update", "case_update",
    "self_feedback", "selector_feedback", "constant_state_values", "finite_width", "next_value_feedback",
    "name_hint",
)
NAME_HINT_RE = re.compile(r"(?i)(_?clk|_?clock|_?rst|_?reset|_next|_nxt|^state$|^state_next$|next_state)")

SECTIONS = ("processes", "clocks", "resets", "registers", "next_values", "enables", "holds",
            "combinational", "latches", "candidates")


def behavior_id(category: str, anchor: str, qualifier: str = "") -> str:
    payload = "\x1f".join(("kf-beh", f"v{IDENTITY_VERSION}", category, anchor, qualifier))
    return IDENTITY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def dumps(doc: dict) -> str:
    """Canonical serialisation: sorted keys, compact separators, UTF-8, trailing newline."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def loc_key(obj: dict):
    loc = obj.get("loc") or {}
    return (str(loc.get("file", "")), int(loc.get("line", 0) or 0), int(loc.get("column", 0) or 0),
            str(obj.get("id", "")))
