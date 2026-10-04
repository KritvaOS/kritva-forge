# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : model.py
# Description : Structural Analysis v1 schema constants, vocabularies and identities (KF-DQ-010)
#
# Component   : Kritva Forge
# Module      : structural
# Layer       : Structural Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural Hardware Analysis v1 contract (``kritva-forge-structural-analysis`` version 1).

One JSON document per canonical module at
``<data-root>/normalized/structural/v1/<ip>/<module>.json``, derived only from
the module's Semantic IR v2 document, its Behavioral Semantics v1 document and
the canonical module inventory (for hierarchy resolution).  None of the inputs
is modified.

Identity namespace ``str``, version 1:

* object identity ``id = "str1:" + sha256("kf-str", "v1", category, anchor,
  qualifier)[:16]`` where ``anchor`` is a Semantic IR ``sem1:`` (or Behavioral
  ``beh1:``) identity and ``qualifier`` disambiguates objects sharing an
  anchor (for a dependency: ``source>target:kind:context``);
* document identity ``id = "str1:" + sha256("kf-str", "v1", "document",
  <canonical document without id>)[:16]`` - a content hash;
* ``fingerprint`` - the same hash over an identity- and location-free
  projection (names, kinds, widths, relationships); used by the leakage check.

All inputs of every hash are content (RTL-derived identities, names, kinds);
never paths, time, host, process or object identity.
"""

from __future__ import annotations

import hashlib
import json
import re

SCHEMA_NAME = "kritva-forge-structural-analysis"
SCHEMA_VERSION = 1
IDENTITY_VERSION = 1
IDENTITY_PREFIX = f"str{IDENTITY_VERSION}:"
ANALYZER_VERSION = 1
PROVENANCE_VERSION = 1                      # provenance rules of this schema (loc + anchors)
SEMANTIC_IR_VERSION = 2
SEMANTIC_IDENTITY_VERSION = 1
BEHAVIOR_VERSION = 1
BEHAVIOR_IDENTITY_VERSION = 1
ANALYZER = "kritva-forge scripts/structural v1"
OUTPUT_SUBDIR = "structural/v1"
OUTPUT_DIR = f"normalized/{OUTPUT_SUBDIR}"  # <data-root>/<OUTPUT_DIR>/<ip>/<module>.json
REPORT_PATH = "analysis/reports/structural_report.json"

ID_RE = re.compile(r"str1:[0-9a-f]{16}")
SEM_RE = re.compile(r"sem1:[0-9a-f]{16}")
BEH_RE = re.compile(r"beh1:[0-9a-f]{16}")
MODULE_ID_RE = re.compile(r"mod1:[0-9a-f]{16}")
SHA_RE = re.compile(r"[0-9a-f]{64}")

# ----------------------------------------------------------------------------- vocabularies
ROLES = ("sequential", "combinational", "latch", "initialization", "generic", "unknown", "ambiguous")
STATUS = ("confirmed", "candidate", "ambiguous", "unsupported")
# relationship kinds (AC-022) and contexts (AC-018)
DEP_KINDS = ("data", "control", "reset", "enable", "hold", "clock")
CONTEXTS = ("continuous_assignment", "procedural_assignment", "sequential_update", "initialization",
            "condition", "case_expression", "case_item", "ternary_condition", "target_index",
            "reset", "enable", "hold", "clock_event", "loop_control")
BOUNDARIES = ("combinational", "sequential", "latch", "initialization", "unknown")
DRIVER_KINDS = ("continuous_assignment", "net_declaration", "procedural", "initializer",
                "instance_output", "instance_inout", "instance_unknown", "module_input")
LOAD_KINDS = ("assignment_value", "ternary_condition", "target_index", "condition", "case_expression",
              "case_item", "event", "loop_condition", "instance_input", "instance_inout", "instance_unknown",
              "instance_index", "instance_parameter", "subroutine", "statement", "declaration",
              "module_output")
DRIVER_STATUS = ("driven", "undriven", "external", "unknown")
ORDER = ("read_first", "write_first", "nonblocking", "mixed", "unknown")
DIRECTIONS = ("input", "output", "inout", "unknown")
FLOWS = ("parent_to_child", "child_to_parent", "bidirectional", "unknown")
INSTANCE_STATUS = ("resolved", "unresolved")
PREDICATE_KINDS = ("if", "case", "casez", "casex")
PREDICATE_ROLES = ("control", "reset", "enable")
CONE_DIRECTIONS = ("fanin", "fanout")
HOLD_KINDS = ("explicit", "implicit")
CLASSES = ("data", "control", "reset", "enable", "hold", "clock", "hierarchy", "port_connection",
           "driver", "load", "sequential_boundary", "unknown")
EVIDENCE = (
    "behavior_clock", "behavior_reset", "behavior_enable", "behavior_hold", "behavior_register",
    "data_source", "predicate_reference", "case_selector", "case_label", "ternary_condition",
    "target_index", "event_reference", "instance_connection", "has_driver", "has_load",
    "module_input", "module_output", "unknown_direction", "opaque_reference", "no_structural_use",
    "name_hint",
)
NAME_HINT_RE = re.compile(r"(?i)(clk|clock|rst|reset|_en$|^en_|enable|_next$|_nxt$|^state$|next_state)")

SECTIONS = ("signals", "processes", "assignments", "predicates", "drivers", "loads", "dependencies",
            "registers", "multiple_drivers", "cycles", "cones", "instances", "connections", "hierarchy")
# id-list fields that are kept in canonical (sorted) order; every section is sorted by id
SORTED_LISTS = ("drivers", "loads", "reads", "writes", "assignments", "signals", "targets", "units",
                "references", "registers", "inputs", "outputs", "processes", "predicates", "instances",
                "connections", "edges", "cycles", "semantic", "behavior", "data", "control", "kinds")


def struct_id(category: str, anchor: str, qualifier: str = "") -> str:
    payload = "\x1f".join(("kf-str", f"v{IDENTITY_VERSION}", category, anchor, qualifier))
    return IDENTITY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def dumps(doc: dict) -> str:
    """Canonical serialisation: sorted keys, compact separators, UTF-8, trailing newline."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def document_id(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "id"}
    return struct_id("document", "", dumps(body))
