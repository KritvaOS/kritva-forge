# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : model.py
# Description : FSM Analysis v2 schema constants, vocabularies and identities (KF-DQ-011, KF-DQ-011.1)
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis contract (``kritva-forge-fsm-analysis`` version 2).

One JSON document per canonical module at
``<data-root>/normalized/fsm/v2/<ip>/<module>.json``, derived only from the
module's Semantic IR v2, Behavioral Semantics v1 and Structural Analysis v1
documents.  None of the inputs is modified, and the legacy parser-integrated
FSM path (``scripts/fsm/fsm_*.py``, ``scripts/structural/fsm_structural.py``,
the v1 IR ``fsm`` field) is neither imported nor read (AC-001 .. AC-008).

Identity namespace ``fsm``, version 1:

* object identity ``id = "fsm1:" + sha256("kf-fsm", "v1", category, anchor,
  qualifier)[:16]``; ``anchor`` is an upstream ``sem1:`` / ``beh1:`` identity;
* ``fingerprint`` - hash of a names-free, identity-free and location-free
  projection (state count, encoding style, transition topology, guard shape);
* document ``id`` - hash of the canonical document without ``id`` and
  ``fingerprint`` (no recursion; Step B review change 1).

Schema version 2 (KF-DQ-011.1) changes only the output records: every output
carries ``registered`` (the output is itself a register with a sequential
boundary), ``sampled_sources`` (inputs / other registers read by its update
logic, enable conditions included; clock, reset and hold excluded) and
``other_sources`` (non-state sources of the *combinational* output cone, ``[]``
for a registered output).
A registered output is a temporal boundary and is therefore never Mealy.
Version 1 documents (``normalized/fsm/v1``) are obsolete; identities (``fsm1:``)
are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re

SCHEMA_NAME = "kritva-forge-fsm-analysis"
SCHEMA_VERSION = 2                    # KF-DQ-011.1: registered / sampled_sources outputs
IDENTITY_VERSION = 1
IDENTITY_PREFIX = f"fsm{IDENTITY_VERSION}:"
ANALYZER_VERSION = 2                  # KF-DQ-011.1: register-boundary output classification
PROVENANCE_VERSION = 1
SEMANTIC_IR_VERSION = 2
SEMANTIC_IDENTITY_VERSION = 1
BEHAVIOR_VERSION = 1
BEHAVIOR_IDENTITY_VERSION = 1
STRUCTURAL_VERSION = 1
STRUCTURAL_IDENTITY_VERSION = 1
ANALYZER = "kritva-forge scripts/fsm v2"
OUTPUT_SUBDIR = "fsm/v2"
OBSOLETE_OUTPUT_DIRS = ("normalized/fsm/v1",)  # superseded layouts (KF-DQ-011.1)
OUTPUT_DIR = f"normalized/{OUTPUT_SUBDIR}"  # <data-root>/<OUTPUT_DIR>/<ip>/<module>.json
REPORT_PATH = "analysis/reports/fsm_report.json"

ID_RE = re.compile(r"fsm1:[0-9a-f]{16}")
SEM_RE = re.compile(r"sem1:[0-9a-f]{16}")
BEH_RE = re.compile(r"beh1:[0-9a-f]{16}")
STR_RE = re.compile(r"str1:[0-9a-f]{16}")
MODULE_ID_RE = re.compile(r"mod1:[0-9a-f]{16}")
SHA_RE = re.compile(r"[0-9a-f]{64}")

# ----------------------------------------------------------------------------- vocabularies
STATUS = ("confirmed", "candidate", "ambiguous", "unsupported")
QUALITY = ("high", "medium", "low", "ambiguous", "unsupported")
STYLES = ("one_process", "two_process")
HOLD = ("none", "explicit", "implicit", "mixed")
ENCODING_STATUS = ("explicit", "inferred", "unknown", "ambiguous")
ENCODING_STYLE = ("binary", "one_hot", "gray", "custom", "unknown")
ENCODING_SOURCE = ("parameter", "localparam", "enum", "literal", "mixed", "unknown")
CONSTANT_KINDS = ("parameter", "localparam", "enum_member", "literal")
REACHABILITY = ("graph_reachable", "graph_unreachable", "unknown")
REACH_STATUS = ("known", "unknown")
TRANSITION_KINDS = ("explicit", "explicit_hold", "implicit_hold", "default", "reset")
TRANSITION_STATUS = ("confirmed", "derived", "unknown")
PSEUDO_STATES = ("*unknown", "*none", "*reset")       # unknown / provably empty source / reset source
GUARD_KINDS = ("if", "case", "casez", "casex", "ternary", "loop")
GUARD_BRANCHES = ("then", "else", "item", "default", "body")
OUTPUT_KINDS = ("moore", "mealy", "ambiguous")
ACTION_KINDS = ("output", "register", "control")
COUPLING_KINDS = ("predicate", "data")
REJECTION_REASONS = ("arithmetic_feedback", "no_state_predicate", "name_only", "single_value",
                     "no_closed_loop", "unsupported_function", "unsupported_hierarchical_next")
RESET_KINDS = ("async", "sync", "none")
UNKNOWN_KINDS = ("unknown_target", "unknown_source", "unresolved_constant", "opaque_statement",
                 "multiple_driver", "incomplete_domain", "ambiguous_update", "ambiguous_reset")
EVIDENCE = ("behavior_state_candidate", "behavior_next_value_candidate", "predicate_over_register",
            "resolved_state_values", "unresolved_state_values", "closed_loop", "two_process_next_value",
            "explicit_hold", "implicit_hold", "reset_state", "named_constants", "name_hint", "trivial_state_domain")
NAME_HINT_RE = re.compile(r"(?i)(state|_st$|^st$|^st_|fsm|_ns$|_cs$|next|nxt)")

NOTES = ("anonymous_enum_registers", "implicit_enum_states")   # descriptive counters (document ``notes``)

SECTIONS = ("fsms", "couplings", "rejected")
FSM_LISTS = ("states", "transitions", "outputs", "actions")


def fsm_id(category: str, anchor: str, qualifier: str = "") -> str:
    payload = "\x1f".join(("kf-fsm", f"v{IDENTITY_VERSION}", category, anchor, qualifier))
    return IDENTITY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def encoding_style(values, width, moves) -> str:
    """Encoding style of a complete, resolved state-value set (AC-030 .. AC-033).

    ``moves`` are the (source value, target value) pairs of the distinct-state
    transitions.  Gray is tested first: a counting (binary) FSM always has a
    move that flips more than one bit.
    """
    values = sorted(values)
    if not values:
        return "unknown"
    if len(values) >= 3 and moves and all(bin(a ^ b).count("1") == 1 for a, b in moves):
        return "gray"
    if values == list(range(len(values))):
        return "binary"
    if len(values) >= 2 and all(bin(v).count("1") == 1 for v in values) and width == len(values):
        return "one_hot"
    return "custom"


def dumps(doc: dict) -> str:
    """Canonical serialisation: sorted keys, compact separators, UTF-8, trailing newline."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def document_id(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k not in ("id", "fingerprint")}
    return fsm_id("document", "", dumps(body))
