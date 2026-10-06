# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : model.py
# Description : Semantic IR v2 schema constants, enumerations and identities (KF-DQ-008)
#
# Component   : Kritva Forge
# Module      : semantic_ir
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 contract (``kritva-forge-semantic-ir`` version 2).

One JSON document per canonical module, written to the single canonical
location ``<data-root>/normalized/semantic_ir/v2/<ip>/<module>.json`` next
to the v1 canonical IR (``normalized/ir``, unchanged and independently
valid).  Every document states its versions explicitly (``versions``):
schema, semantic identity, KF-DQ-003 node identity, parser and the
normalized-IR version it coexists with.

Identity namespace ``sem``, version 1 (``IDENTITY_VERSION``): every semantic
entity has ``id = "sem1:" + sha256("kf-sem", "v1", category,
n1-node-identity, qualifier)[:16]``.  The KF-DQ-003 ``n1`` node identity is
derived from the repository-relative source file, syntax kind and token
positions, so semantic identities are stable across runs, parse order and
checkout locations and change only when the RTL changes.  Modules keep their
KF-DQ-005 ``mod1:`` identity (``module.module_id``).
"""

from __future__ import annotations

import hashlib
import re

SCHEMA_NAME = "kritva-forge-semantic-ir"
SCHEMA_VERSION = 2
IDENTITY_VERSION = 1                     # "sem1:" namespace
IDENTITY_PREFIX = f"sem{IDENTITY_VERSION}:"
COMPATIBLE_NORMALIZED_IR = 1             # coexists with (does not replace) normalized/ir v1
EXTRACTOR = "kritva-forge scripts/semantic_ir v2"
OUTPUT_SUBDIR = "semantic_ir/v2"                          # sibling of normalized/ir
OUTPUT_DIR = f"normalized/{OUTPUT_SUBDIR}"                 # <data-root>/<OUTPUT_DIR>/<ip>/<module>.json
REPORT_PATH = "analysis/reports/semantic_ir_report.json"   # corpus gate report (validator --write-report)

ID_RE = re.compile(r"sem1:[0-9a-f]{16}")
MODULE_ID_RE = re.compile(r"mod1:[0-9a-f]{16}")

EXTRACTION = ("complete", "partial")
PROCESS_KINDS = ("always", "always_ff", "always_comb", "always_latch", "initial", "final")
SENSITIVITY = ("list", "implicit", "none")                  # as written; semantics are KF-DQ-009
ASSIGN_KINDS = ("continuous", "blocking", "nonblocking", "compound", "declaration")
EDGES = ("posedge", "negedge", "edge", "level")
CASE_KINDS = ("case", "casez", "casex")
STATEMENTS = ("assign", "if", "case", "block", "loop", "timing", "null", "return", "call",
              "declaration", "opaque")
EXPRESSIONS = ("ref", "literal", "unary", "binary", "ternary", "concat", "replicate", "index",
               "part_select", "member", "call", "cast", "opaque")
REF_KINDS = ("port", "signal", "parameter", "genvar", "local", "enum_member", "subroutine",
             "type", "unresolved", "hierarchical", "external")
USAGES = ("read", "write", "connect")
BRANCHES = ("then", "else", "item", "default", "body")
EXTERNAL_KINDS = ("parameter", "localparam", "typedef", "enum_member", "function", "task")
DECL_KINDS = ("net", "variable")
DIRECTIONS = ("input", "output", "inout", "ref", "unknown")
CONNECTION_KINDS = ("named", "ordered", "implicit", "wildcard", "empty")
GENERATE_KINDS = ("region", "loop", "if", "case", "block")
REPRESENTATION = ("source-level",)

# Required fields of each expression node (beyond "op").
EXPR_FIELDS = {
    "ref": ("id", "name", "ref_kind", "target"),          # source span: references[] index
    "literal": ("text",),
    "unary": ("operator", "operand"),
    "binary": ("operator", "left", "right"),
    "ternary": ("cond", "then", "else"),
    "concat": ("items",),
    "replicate": ("count", "items"),
    "index": ("base", "index"),
    "part_select": ("base", "mode", "left", "right"),
    "member": ("base", "member"),
    "call": ("name", "system", "args"),
    "cast": ("type", "operand"),
    "opaque": ("construct", "text", "reason"),
}

# Required fields of each statement node (beyond "stmt").
STMT_FIELDS = {
    "assign": ("id", "assignment", "loc"),
    "if": ("id", "cond", "then", "else", "loc"),
    "case": ("id", "case_kind", "expr", "items", "default", "loc"),
    "block": ("id", "name", "body", "loc"),
    "loop": ("id", "loop_kind", "body", "loc"),
    "timing": ("id", "control", "body", "loc"),
    "null": ("id", "loc"),
    "return": ("id", "value", "loc"),
    "call": ("id", "expr", "loc"),
    "declaration": ("id", "declaration", "loc"),
    "opaque": ("id", "construct", "reason", "loc"),
}

MODULE_SECTIONS = ("parameters", "ports", "signals", "typedefs", "subroutines", "assignments",
                   "processes", "instances", "generates", "conditions", "cases", "references", "unsupported")


def semantic_id(category: str, node_identity: str, qualifier: str = "") -> str:
    payload = "\x1f".join(("kf-sem", f"v{IDENTITY_VERSION}", category, node_identity, qualifier))
    return IDENTITY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def dumps(doc: dict) -> str:
    """Canonical serialisation: sorted keys, compact separators, UTF-8, trailing newline.

    Compact form keeps the corpus near 21 MB (32 MB indented); use
    ``python -m json.tool`` to read a document.
    """
    import json

    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def loc_key(obj: dict):
    loc = obj.get("loc") or {}
    return (str(loc.get("file", "")), int(loc.get("line", 0) or 0), int(loc.get("column", 0) or 0),
            str(obj.get("id", "")))
