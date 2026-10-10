# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : registry.py
# Description : Versioned task registry and record schema of the multi-task dataset (KF-DQ-013)
#
# Component   : Kritva Forge
# Module      : multitask
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Task registry ``task_registry`` v1 and record schema ``kritva-forge-dataset`` v2 (KF-DQ-013).

This module is the single declaration of the multi-task dataset contract
(AC-006 .. AC-012):

- ``TASKS`` - every task with its own version.  ``populated`` tasks have
  exactly one record per canonical module, derived by a frozen projection;
  ``declared`` tasks exist at schema level only and have no records.
- the record schema (top-level and nested fields, AC-013), the record
  identity ``r2:`` (AC-014), the RTL view ``rtl-slice-v1`` and the projection
  versions.

Changing a task's input, target, projection or population rule needs a new
task version; changing the task set or the semantics of this registry needs
a new ``TASK_REGISTRY_VERSION`` (``tests`` pin ``digest()``).
"""

from __future__ import annotations

import hashlib
import json

TASK_REGISTRY_VERSION = 1
DATASET_SCHEMA = {"name": "kritva-forge-dataset", "version": 2}
RTL_SLICE_VERSION = "rtl-slice-v1"
OUTPUT_DIR = "datasets/multitask/v2"
REGISTRY_PATH = f"{OUTPUT_DIR}/registry.json"
REPORT_PATH = "analysis/reports/dataset_v2_report.json"
SPLITS = ("train", "validation", "test")

POPULATED = "populated"
DECLARED = "declared"

PROJECTIONS = {
    "interface-v1": {"layer": "semantic_ir", "task": "interface_extraction"},
    "structural-v1": {"layer": "structural", "task": "structural_extraction"},
    "dependency-v1": {"layer": "structural", "task": "dependency_analysis"},
    "fsm-v1": {"layer": "fsm", "task": "fsm_extraction"},
}


def _task(tid, version, status, input_kind, target_kind, layers, projection, description, rule):
    return {"id": tid, "version": version, "status": status, "input_kind": input_kind,
            "target_kind": target_kind, "source_layers": layers, "projection": projection,
            "description": description, "population_rule": rule}


_ONE_PER_MODULE = "exactly one record per canonical module"
_NONE = "no records (declared only; target contract defined by a later task)"

TASKS = (
    _task("rtl_generation", 2, POPULATED, "prompt_v2", "rtl",
          ["prompt_v2", "source"], None,
          "Prompt v2 behavior-aware description -> module RTL (rtl-slice-v1)", _ONE_PER_MODULE),
    _task("rtl_understanding", 1, POPULATED, "rtl", "prompt_v2",
          ["prompt_v2", "source"], None,
          "module RTL (rtl-slice-v1) -> Prompt v2 behavior-aware description", _ONE_PER_MODULE),
    _task("interface_extraction", 1, POPULATED, "rtl", "json",
          ["semantic_ir", "source"], "interface-v1",
          "module RTL -> parameters and ports (Semantic IR v2 projection)", _ONE_PER_MODULE),
    _task("structural_extraction", 1, POPULATED, "rtl", "json",
          ["semantic_ir", "structural", "source"], "structural-v1",
          "module RTL -> registers, instances, process boundaries (Structural Analysis v1 projection)",
          _ONE_PER_MODULE),
    _task("dependency_analysis", 1, POPULATED, "rtl", "json",
          ["semantic_ir", "structural", "source"], "dependency-v1",
          "module RTL -> fan-in of every output port and register (Structural Analysis v1 projection)",
          _ONE_PER_MODULE),
    _task("fsm_extraction", 1, POPULATED, "rtl", "json",
          ["semantic_ir", "fsm", "source"], "fsm-v1",
          "module RTL -> confirmed / candidate FSMs, or none (FSM Analysis v2 projection)", _ONE_PER_MODULE),
    _task("rtl_explanation", 1, DECLARED, None, None, [], None,
          "module RTL -> human-oriented explanation (not an alias of Prompt v2)", _NONE),
    _task("assertion_generation", 1, DECLARED, None, None, [], None,
          "module RTL / specification -> assertions", _NONE),
    _task("rtl_repair", 1, DECLARED, None, None, [], None,
          "faulty RTL -> repaired RTL", _NONE),
    _task("rtl_optimization", 1, DECLARED, None, None, [], None,
          "RTL -> optimized RTL", _NONE),
)
BY_ID = {t["id"]: t for t in TASKS}
POPULATED_TASKS = tuple(t for t in TASKS if t["status"] == POPULATED)

# AC-013: record schema - exact top-level keys and nested fields
RECORD_KEYS = ("input", "module", "record_id", "schema", "sources", "split", "target", "task", "versions")
NESTED = {
    "schema": ("name", "version"),
    "task": ("id", "version"),
    "module": ("ip", "module_id", "name"),
    "input": ("kind", "text"),
    "source": ("layer", "path", "sha256"),
}
TARGET_TEXT = ("kind", "text")
TARGET_JSON = ("kind", "projection", "value")
INPUT_KINDS = ("prompt_v2", "rtl")


def record_id(task_id: str, task_version: int, module_id: str) -> str:
    """``r2:`` + 16 hex of SHA-256 over ``kf-record \\x1f v2 \\x1f task \\x1f version \\x1f module_id`` (AC-014)."""
    pre = "\x1f".join(["kf-record", "v2", str(task_id), str(task_version), str(module_id)])
    return "r2:" + hashlib.sha256(pre.encode("utf-8")).hexdigest()[:16]


def document(counts: dict | None = None) -> dict:
    """Canonical registry document (``datasets/multitask/v2/registry.json``, AC-011)."""
    return {
        "schema": {"name": "kritva-forge-task-registry", "version": TASK_REGISTRY_VERSION},
        "dataset_schema": DATASET_SCHEMA,
        "rtl_slice": RTL_SLICE_VERSION,
        "projections": {k: {"layer": v["layer"], "task": v["task"]} for k, v in sorted(PROJECTIONS.items())},
        "tasks": [dict(t, records=(counts or {}).get(t["id"], 0)) for t in TASKS],
    }


def digest() -> str:
    """SHA-256 of the registry semantics (without record counts) - pinned by the tests (AC-012)."""
    return hashlib.sha256(json.dumps(document(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dumps_record(record: dict) -> str:
    """Canonical JSON line (AC-019)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
