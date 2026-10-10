#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : summary.py
# Description : Reference regression summary - generate, write and compare against the committed baseline (KF-DQ-012.2)
#
# Component   : Kritva Forge
# Module      : reference
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Regression summary of a pipeline-processed reference root (KF-DQ-012.2 AC-025 .. AC-029, AC-039).

The summary contains:
- the reference corpus sha256 (from ``reference_manifest.json``);
- IPs and module counts;
- per-layer file counts and tree hashes, in locale-independent order;
- gate statuses (read from the persisted reports);
- Prompt v2 size, leakage and truncation statistics;
- the classification counts;
- split counts and identity;
- the multi-task dataset counts and identity (KF-DQ-013).

It holds no time, host or path data. ``--compare`` reports every differing key and exits 1 on any difference.
``--write`` is used only by ``make reference-baseline``; the regression never writes the baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SCHEMA = {"name": "kritva-forge-reference-summary", "version": 1}
LAYERS = (
    "raw/rtl/original",
    "normalized/ir",
    "normalized/semantic_ir/v2",
    "normalized/behavior/v1",
    "normalized/structural/v1",
    "normalized/fsm/v2",
    "generated/prompts",
    "generated/prompt/v2",
    "analysis/reports",
    "datasets/pipeline",
    "datasets/multitask/v2",
    "splits",
    "manifests",
)
REPORTS = {
    "semantic_ir": "analysis/reports/semantic_ir_report.json",
    "behavior": "analysis/reports/behavior_report.json",
    "structural": "analysis/reports/structural_report.json",
    "fsm": "analysis/reports/fsm_report.json",
    "prompt_v2": "analysis/reports/prompt_v2_report.json",
    "compatibility": "analysis/reports/compatibility_report.json",
    "stale_artifacts": "analysis/reports/stale_artifact_report.json",
    "provenance": "analysis/reports/provenance_report.json",
    "split_leakage": "analysis/reports/split_leakage_report.json",
    "data_manifest": "analysis/reports/data_manifest_report.json",
    "dataset_v2": "analysis/reports/dataset_v2_report.json",
}


def _tree(root: Path, rel: str) -> dict:
    base = root / rel
    files = sorted((p for p in base.rglob("*") if p.is_file()), key=lambda p: p.relative_to(base).as_posix().encode())
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(base).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    return {"files": len(files), "tree_sha256": h.hexdigest()}


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(data_root, manifest_path=None) -> dict:
    root = Path(os.path.abspath(data_root))
    manifest_path = Path(manifest_path) if manifest_path else root.parent / "reference_manifest.json"
    man = _json(manifest_path) or {}
    ir = root / "normalized" / "ir"
    ips = {}
    if ir.is_dir():
        for d in sorted(ir.iterdir()):
            if (d / "modules").is_dir():
                ips[d.name] = len(list((d / "modules").glob("*.yaml")))
    gates = {}
    for name, rel in REPORTS.items():
        rep = _json(root / rel)
        gates[name] = rep.get("status", "UNKNOWN") if isinstance(rep, dict) else "MISSING"
    pv = _json(root / REPORTS["prompt_v2"]) or {}
    cls = _json(root / "analysis/reports/prompt_leakage_classification.json") or {}
    dm = _json(root / "manifests/data_manifest.json") or {}
    sizes, lk = pv.get("sizes") or {}, pv.get("leakage") or {}
    return {
        "schema": SCHEMA,
        "reference_corpus_sha256": man.get("corpus_sha256"),
        "sources": [{"id": i.get("id"), "commit": i.get("commit"), "files": len(i.get("files", [])),
                     "exclusions": [e.get("path") for e in i.get("exclusions", [])]} for i in man.get("ips", [])],
        "ips": ips,
        "modules": sum(ips.values()),
        "layers": {rel: _tree(root, rel) for rel in LAYERS if (root / rel).exists()},
        "gates": gates,
        "prompt_v2": {
            "prompts": pv.get("prompts"), "sidecars": pv.get("sidecars"),
            "sizes": {k: sizes.get(k) for k in ("p50", "p90", "p99", "p100", "truncated")},
            "leakage": {"overlap_max": (lk.get("overlap") or {}).get("p100"),
                        "longest_run_max": (lk.get("longest_run") or {}).get("p100"),
                        "failures": lk.get("failures")},
            "guard_fallbacks": (pv.get("abstraction") or {}).get("guard_fallbacks"),
            "corpus_sha256": pv.get("corpus_sha256"),
        },
        "classification": cls.get("counts"),
        "splits": {"counts": (dm.get("splits") or {}).get("counts"),
                   "split_identity": (dm.get("splits") or {}).get("split_identity")},
        "multitask": {"records": (dm.get("multitask") or {}).get("records"),
                      "splits": (dm.get("multitask") or {}).get("splits"),
                      "tasks": {k: v.get("records") for k, v in ((dm.get("multitask") or {}).get("tasks") or {}).items()},
                      "dataset_identity": (dm.get("multitask") or {}).get("dataset_identity")},
    }


def dumps(doc) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def _flat(x, prefix=""):
    if isinstance(x, dict):
        out = {}
        for k in sorted(x):
            out.update(_flat(x[k], f"{prefix}.{k}" if prefix else str(k)))
        return out if x else {prefix: {}}
    return {prefix: x}


def diff(expected: dict, actual: dict) -> list:
    """Every differing key (dotted path), as (key, expected, actual)."""
    a, b = _flat(expected), _flat(actual)
    return [(k, a.get(k, "<absent>"), b.get(k, "<absent>")) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KF-DQ-012.2 reference regression summary")
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--manifest", help="default <data-root>/../reference_manifest.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", help="write the summary here (baseline update only)")
    g.add_argument("--compare", help="compare with this committed baseline")
    a = ap.parse_args(argv)
    cur = build(a.data_root, a.manifest)
    if a.write:
        Path(a.write).parent.mkdir(parents=True, exist_ok=True)
        Path(a.write).write_text(dumps(cur), encoding="utf-8")
        print(f"[INFO] reference summary written: {a.write} ({cur['modules']} modules, {len(cur['ips'])} IPs)")
        return 0
    exp = json.loads(Path(a.compare).read_text(encoding="utf-8"))
    d = diff(exp, cur)
    if d:
        print(f"Reference regression summary: FAIL ({len(d)} differing keys vs {a.compare})")
        for k, e, c in d[:200]:
            print(f"  [DIFF] {k}: expected {e!r} · actual {c!r}")
        return 1
    print(f"Reference regression summary: PASS ({cur['modules']} modules, {len(cur['ips'])} IPs; "
          f"identical to {a.compare})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
