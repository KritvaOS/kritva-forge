#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : compat.py
# Description : Cross-repository version compatibility contract and check (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : core
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Cross-repository compatibility contract (KF-DQ-012 AC-508 .. AC-531).

Compatibility between kritva-forge and kritva-forge-data is decided by the
schema, identity and analyzer versions of every layer - never by commit
hashes.  ``REQUIRED`` is the single canonical declaration of the versions
this forge revision requires; every layer's own constants must agree with it
(tested), so a version change cannot happen silently.

``check(data_root)`` compares ``REQUIRED`` with the versions the data
actually records: the canonical data manifest schema version, its ``versions`` block and the
``versions`` block of every Prompt v2 sidecar.  Any mismatch fails closed
(``make check-compat``; part of ``data-quality`` and the apply workflow).

``CONTRACT_VERSION`` versions the contract mechanism (one ``REQUIRED`` table,
the ``required`` block recorded in the manifest compared for exact equality,
sidecar keys); additive requirements are carried by ``REQUIRED`` itself.
KF-DQ-013 added ``dataset_schema`` / ``task_registry`` (manifest-only keys,
``MANIFEST_ONLY_KEYS``) and manifest version 7 without changing the mechanism.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CONTRACT_VERSION = 1
REPORT_PATH = "analysis/reports/compatibility_report.json"

# The one canonical declaration of required versions (AC-511 .. AC-517).
REQUIRED = {
    "manifest": 7,
    "semantic_ir": 2,
    "semantic_identity": 1,
    "behavior": 1,
    "behavior_identity": 1,
    "structural": 1,
    "structural_identity": 1,
    "structural_analyzer": 1,
    "fsm": 2,
    "fsm_identity": 1,
    "fsm_analyzer": 2,
    "prompt": 2,
    "prompt_generator": 1,
    "prompt_identity": 1,
    "tokenizer": "sv-lex-v1",
    "leakage_metric": "leakage-v1",
    "leakage_thresholds": "thresholds-v1",
    "leakage_classifier": "rtl-sim-v1",
    "dataset_schema": 2,                    # KF-DQ-013 multi-task dataset (datasets/multitask/v2)
    "task_registry": 1,
}
# Manifest-only keys: a Prompt v2 sidecar records none of them (KF-DQ-013 AC-052).
MANIFEST_ONLY_KEYS = ("manifest", "leakage_classifier", "dataset_schema", "task_registry")
# Keys a Prompt v2 sidecar records.
SIDECAR_KEYS = tuple(k for k in REQUIRED if k not in MANIFEST_ONLY_KEYS)


def declared() -> dict:
    """The versions declared by the layer modules themselves (must equal ``REQUIRED``)."""
    from scripts.behavior import model as BM
    from scripts.core import data_manifest as DM
    from scripts.fsm import model as FM
    from scripts.prompt_v2 import classify as PC
    from scripts.prompt_v2 import leakage as PL
    from scripts.prompt_v2 import model as PM
    from scripts.semantic_ir import model as SM
    from scripts.structural import model as TM
    from scripts.multitask import registry as MG

    return {
        "manifest": DM.MANIFEST_VERSION,
        "semantic_ir": SM.SCHEMA_VERSION, "semantic_identity": SM.IDENTITY_VERSION,
        "behavior": BM.SCHEMA_VERSION, "behavior_identity": BM.IDENTITY_VERSION,
        "structural": TM.SCHEMA_VERSION, "structural_identity": TM.IDENTITY_VERSION,
        "structural_analyzer": TM.ANALYZER_VERSION,
        "fsm": FM.SCHEMA_VERSION, "fsm_identity": FM.IDENTITY_VERSION, "fsm_analyzer": FM.ANALYZER_VERSION,
        "prompt": PM.SCHEMA_VERSION, "prompt_generator": PM.GENERATOR_VERSION, "prompt_identity": PM.IDENTITY_VERSION,
        "tokenizer": PL.TOKENIZER_VERSION, "leakage_metric": PL.METRIC_VERSION,
        "leakage_thresholds": PL.THRESHOLD_VERSION, "leakage_classifier": PC.CLASSIFIER_VERSION,
        "dataset_schema": MG.DATASET_SCHEMA["version"], "task_registry": MG.TASK_REGISTRY_VERSION,
    }


def check(data_root) -> dict:
    from scripts.core import data_manifest as DM
    from scripts.prompt_v2 import model as PM

    root = Path(os.path.abspath(data_root))
    problems = []
    for key, want in sorted(declared().items()):
        if REQUIRED.get(key) != want:
            problems.append(f"forge: {key} declared {want!r} by its layer but required {REQUIRED.get(key)!r}")
    found = {}
    mpath = root / DM.MANIFEST_PATH
    if not mpath.is_file():
        problems.append(f"data: {DM.MANIFEST_PATH} missing")
    else:
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except ValueError as exc:
            m = {}
            problems.append(f"data: manifest is not valid JSON ({exc})")
        v = m.get("versions") or {}
        found = {k: v.get(k) for k in REQUIRED}
        schema = (m.get("schema") or {}).get("version")
        if schema != REQUIRED["manifest"]:
            problems.append(f"data manifest: schema version is {schema!r}, forge requires {REQUIRED['manifest']!r}")
        for key, want in sorted(REQUIRED.items()):
            if v.get(key) != want:
                problems.append(f"data manifest: {key} is {v.get(key)!r}, forge requires {want!r}")
        recorded = (m.get("compatibility") or {}).get("required")
        if recorded is not None and recorded != REQUIRED:
            problems.append("data manifest: recorded compatibility requirements differ from the forge contract")
    sidecars = 0
    base = root / PM.OUTPUT_DIR
    for path in sorted(base.rglob("*.json")) if base.is_dir() else []:
        sidecars += 1
        try:
            v = json.loads(path.read_text(encoding="utf-8")).get("versions") or {}
        except ValueError:
            problems.append(f"{path.relative_to(root).as_posix()}: invalid JSON")
            continue
        for key in SIDECAR_KEYS:
            if v.get(key) != REQUIRED[key]:
                problems.append(f"{path.relative_to(root).as_posix()}: {key} is {v.get(key)!r}, "
                                f"forge requires {REQUIRED[key]!r}")
    return {
        "contract_version": CONTRACT_VERSION,
        "required": dict(REQUIRED),
        "found": found,
        "sidecars_checked": sidecars,
        "problems": problems[:200],
        "status": "FAIL" if problems else "PASS",
    }


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_report(report: dict) -> str:
    lines = [f"Compatibility check: {report['status']} (contract v{report['contract_version']}; "
             f"{report['sidecars_checked']} Prompt v2 sidecars)"]
    lines += [f"  [FAIL] {p}" for p in report["problems"][:30]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-012 cross-repository version compatibility check")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--json", help="also write the report JSON here")
    parser.add_argument("--write-report", action="store_true", help=f"write {REPORT_PATH}")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    report = check(args.data_root)
    print(format_report(report))
    if args.write_report:
        write_report(args.data_root, report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
