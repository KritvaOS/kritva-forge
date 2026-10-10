#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : Multi-task dataset gate and dataset report (KF-DQ-013)
#
# Component   : Kritva Forge
# Module      : multitask
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Multi-task dataset gate (KF-DQ-013 AC-040 .. AC-045).

``check(data_root)`` fails closed on any of:

- schema / version / registry mismatch;
- a record that is not canonical JSON or has extra / missing (nested) fields;
- an unknown task, a declared-task record, or a populated task missing a module;
- a wrong or duplicate ``record_id``, or a wrong sort order;
- split inheritance violated (a module in two splits, or a split differing
  from the split schema v2 manifest);
- task provenance inconsistent (source sha256 / module / projection / versions);
- an id, location or absolute-path leak in the metadata or JSON targets;
- the entry authorization not holding;
- any byte difference from a re-derivation of the dataset from the persisted
  artifacts.

It returns the dataset report (``analysis/reports/dataset_v2_report.json``):
per-task and per-split counts, size statistics, FSM positives / negatives,
null counts, the retained soft findings and the dataset identity ``ds2:``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scripts.multitask import build as B
from scripts.multitask import registry as G

_ID_LEAK = re.compile(r"\b(?:sem1|beh1|str1|fsm1|n1|grp1|pv2):[0-9a-f]{16}\b")
_EXPECTED_FILES = tuple(f"{G.OUTPUT_DIR}/{s}.jsonl" for s in G.SPLITS) + (G.REGISTRY_PATH,)


def _quantiles(values: list) -> dict:
    v = sorted(values)
    if not v:
        return {}
    return {f"p{q}": v[min(len(v) - 1, int(round(q / 100 * (len(v) - 1))))] for q in (50, 90, 99, 100)}


def dataset_identity(lines_by_split: dict) -> str:
    rows = []
    for split, lines in lines_by_split.items():
        for line in lines:
            rid = json.loads(line).get("record_id")
            rows.append(f"{rid}\t{split}\t{hashlib.sha256(line.encode('utf-8')).hexdigest()}")
    return "ds2:" + hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def _record_problems(rec, split, problems):
    """Structural checks of one record (AC-013, AC-014, AC-018)."""
    if sorted(rec) != sorted(G.RECORD_KEYS):
        problems.append(f"{split}: record {rec.get('record_id')} has keys {sorted(rec)}")
        return
    for key in ("schema", "task", "module", "input"):
        if not isinstance(rec[key], dict) or sorted(rec[key]) != sorted(G.NESTED[key]):
            problems.append(f"{split}: record {rec['record_id']} {key} fields {sorted(rec[key]) if isinstance(rec[key], dict) else rec[key]!r}")
    tgt = rec["target"]
    want = G.TARGET_JSON if isinstance(tgt, dict) and tgt.get("kind") == "json" else G.TARGET_TEXT
    if not isinstance(tgt, dict) or sorted(tgt) != sorted(want):
        problems.append(f"{split}: record {rec['record_id']} target fields invalid")
    if not isinstance(rec["sources"], list) or any(not isinstance(s, dict) or sorted(s) != sorted(G.NESTED["source"])
                                                   for s in rec["sources"]):
        problems.append(f"{split}: record {rec['record_id']} sources invalid")
    if not isinstance(rec["versions"], dict) or any(isinstance(v, (dict, list)) for v in rec["versions"].values()):
        problems.append(f"{split}: record {rec['record_id']} versions not a flat object")
    if rec["schema"] != G.DATASET_SCHEMA:
        problems.append(f"{split}: record {rec['record_id']} schema {rec['schema']!r}")
    if rec["split"] != split:
        problems.append(f"{split}: record {rec['record_id']} declares split {rec['split']!r}")
    meta = {k: v for k, v in rec.items() if k not in ("input", "target")}
    meta["target"] = {k: v for k, v in tgt.items() if k != "text"} if isinstance(tgt, dict) else tgt
    text = json.dumps(meta, sort_keys=True)
    if _ID_LEAK.search(text) or '"loc"' in text:
        problems.append(f"{split}: record {rec['record_id']} leaks an internal id or location")
    from scripts.core.paths import find_absolute_paths
    if find_absolute_paths(text):
        problems.append(f"{split}: record {rec['record_id']} contains an absolute path")


def check(data_root, authorize: bool = True) -> dict:
    from scripts.prompt_v2.render import canonical_modules

    root = Path(os.path.abspath(data_root))
    problems = []
    lines_by_split = {}
    for rel in _EXPECTED_FILES:
        if not (root / rel).is_file():
            problems.append(f"missing {rel}")
    base = root / G.OUTPUT_DIR
    extra = sorted(p.relative_to(root).as_posix() for p in (root / "datasets/multitask").rglob("*")
                   if p.is_file() and p.relative_to(root).as_posix() not in _EXPECTED_FILES) \
        if (root / "datasets/multitask").is_dir() else []
    if extra:
        problems.append(f"unmanaged files under datasets/multitask: {extra[:5]}")
    if problems:
        return _report(problems, {}, {}, None, None, None)

    records = {}
    ids = Counter()
    by_module = defaultdict(set)
    task_modules = defaultdict(set)
    for split in G.SPLITS:
        raw = (base / f"{split}.jsonl").read_text(encoding="utf-8")
        lines = raw.splitlines(keepends=True)
        lines_by_split[split] = lines
        recs = []
        for n, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except ValueError as exc:
                problems.append(f"{split}.jsonl:{n}: invalid JSON ({exc})")
                continue
            if G.dumps_record(rec) != line:
                problems.append(f"{split}.jsonl:{n}: not canonical JSON")
            _record_problems(rec, split, problems)
            if sorted(rec) != sorted(G.RECORD_KEYS):
                continue
            task = G.BY_ID.get((rec.get("task") or {}).get("id"))
            if task is None:
                problems.append(f"{split}.jsonl:{n}: unknown task {rec.get('task')!r}")
                continue
            if task["status"] != G.POPULATED:
                problems.append(f"{split}.jsonl:{n}: record of declared task {task['id']}")
            if rec["task"]["version"] != task["version"]:
                problems.append(f"{split}.jsonl:{n}: task {task['id']} version {rec['task']['version']} "
                                f"(registry {task['version']})")
            m = rec["module"]
            if rec["record_id"] != G.record_id(task["id"], rec["task"]["version"], m.get("module_id")):
                problems.append(f"{split}.jsonl:{n}: record_id is not derived from task / module identity")
            ids[rec["record_id"]] += 1
            by_module[(m.get("ip"), m.get("name"))].add(split)
            task_modules[task["id"]].add((m.get("ip"), m.get("name")))
            tgt = rec["target"]
            if task["projection"] and (tgt.get("kind") != "json" or tgt.get("projection") != task["projection"]):
                problems.append(f"{split}.jsonl:{n}: target projection {tgt.get('projection')!r} (registry {task['projection']})")
            for s in rec["sources"]:
                p = root / str(s.get("path"))
                if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != s.get("sha256"):
                    problems.append(f"{split}.jsonl:{n}: stale or missing source {s.get('layer')} {s.get('path')}")
            recs.append(rec)
        keys = [(r["task"]["id"], r["module"]["ip"], r["module"]["name"]) for r in recs]
        if keys != sorted(keys):
            problems.append(f"{split}.jsonl: records not sorted by (task, ip, module)")
        records[split] = recs
    dup = sorted(r for r, c in ids.items() if c > 1)
    if dup:
        problems.append(f"duplicate record_id {dup[:3]}")

    # coverage (AC-009) and split inheritance (AC-035 / AC-036)
    mods = set(canonical_modules(root))
    for task in G.TASKS:
        have = task_modules.get(task["id"], set())
        if task["status"] == G.POPULATED and have != mods:
            problems.append(f"task {task['id']}: {len(mods - have)} canonical modules missing, "
                            f"{len(have - mods)} non-canonical")
    try:
        splits = B.module_splits(root)
    except B.BuildError as exc:
        problems.append(str(exc))
        splits = {}
    for key, ss in sorted(by_module.items()):
        if len(ss) > 1:
            problems.append(f"module {key[0]}/{key[1]} has records in splits {sorted(ss)}")
        elif splits and splits.get(key) not in ss:
            problems.append(f"module {key[0]}/{key[1]}: records in {sorted(ss)}, split manifest {splits.get(key)!r}")

    # registry (AC-011)
    counts = Counter(r["task"]["id"] for s in G.SPLITS for r in records.get(s, []))
    reg_text = (root / G.REGISTRY_PATH).read_text(encoding="utf-8")
    if reg_text != G.dumps(G.document(dict(counts))):
        problems.append("registry.json differs from the forge task registry (with record counts)")

    # entry authorization and re-derivation (AC-037, AC-042)
    auth, stats = None, {}
    try:
        expected = B.build(root, authorize=authorize)
        auth, stats = expected["authorization"], expected["stats"]
        files = B.serialize(expected)
        diff = sorted(rel for rel, text in files.items() if (root / rel).read_text(encoding="utf-8") != text)
        if diff:
            problems.append(f"dataset differs from a re-derivation from the persisted artifacts: {diff}")
    except B.BuildError as exc:
        problems.append(f"re-derivation refused: {exc}")
    return _report(problems, records, counts, lines_by_split, auth, stats)


def _report(problems, records, counts, lines_by_split, auth, stats) -> dict:
    per_split = {s: len(records.get(s, [])) for s in G.SPLITS}
    by_task_split = {t["id"]: {s: sum(1 for r in records.get(s, []) if r["task"]["id"] == t["id"]) for s in G.SPLITS}
                     for t in G.TASKS}
    sizes = {}
    for t in G.POPULATED_TASKS:
        recs = [r for s in G.SPLITS for r in records.get(s, []) if r["task"]["id"] == t["id"]]
        tgt = [len(r["target"]["text"]) if "text" in r["target"]
               else len(json.dumps(r["target"]["value"], sort_keys=True, separators=(",", ":"))) for r in recs]
        sizes[t["id"]] = {"input_chars": _quantiles([len(r["input"]["text"]) for r in recs]),
                          "target_chars": _quantiles(tgt)}
    fsm = [r for s in G.SPLITS for r in records.get(s, []) if r["task"]["id"] == "fsm_extraction"]
    empty = Counter()
    for s in G.SPLITS:
        for r in records.get(s, []):
            v = r["target"].get("value")
            if isinstance(v, dict):
                for k, x in v.items():
                    if isinstance(x, list) and not x:
                        empty[f"{r['target']['projection']}:{k}"] += 1
    return {
        "schema": {"name": "kritva-forge-dataset-report", "version": 1},
        "dataset_schema": G.DATASET_SCHEMA,
        "task_registry": G.TASK_REGISTRY_VERSION,
        "rtl_slice": G.RTL_SLICE_VERSION,
        "tasks": {t["id"]: {"version": t["version"], "status": t["status"], "projection": t["projection"],
                            "records": counts.get(t["id"], 0)} for t in G.TASKS},
        "counts": {"records": sum(per_split.values()), "splits": per_split, "by_task": by_task_split},
        "dataset_identity": dataset_identity(lines_by_split) if lines_by_split else None,
        "sizes": sizes,
        "fsm_extraction": {"positive": sum(1 for r in fsm if r["target"]["value"]["fsms"]),
                           "negative": sum(1 for r in fsm if not r["target"]["value"]["fsms"]),
                           "fsms": sum(len(r["target"]["value"]["fsms"]) for r in fsm)},
        "empty_collections": dict(sorted(empty.items())),
        "nulls_and_unresolved": stats,
        "authorization": auth,
        "soft_findings": {
            "structural_similarity": (auth or {}).get("structural_similarity"),
            "ruling": "KF-DQ-013 AC-039: retained cross-split structural_similarity groups reviewed and kept soft",
        },
        "problems": problems,
        "status": "FAIL" if problems else "PASS",
    }


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / G.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(G.dumps(report), encoding="utf-8")
    return path


def format_report(rep: dict) -> str:
    c = rep["counts"]
    lines = [f"Multi-task dataset check: {rep['status']} ({rep['dataset_schema']['name']} v"
             f"{rep['dataset_schema']['version']}, task registry v{rep['task_registry']})",
             f"  records             : {c['records']} (train / validation / test "
             f"{c['splits']['train']} / {c['splits']['validation']} / {c['splits']['test']})"]
    for tid, t in rep["tasks"].items():
        lines.append(f"  {tid:22s}: v{t['version']} {t['status']:9s} {t['records']} records")
    f = rep["fsm_extraction"]
    lines.append(f"  fsm_extraction      : {f['positive']} positive / {f['negative']} negative modules, {f['fsms']} FSMs")
    lines.append(f"  dataset identity    : {rep['dataset_identity']}")
    a = rep.get("authorization") or {}
    lines.append(f"  entry authorization : kf_dq_013_entry {a.get('kf_dq_013_entry')} (split gate {a.get('split_gate')})")
    for p in rep["problems"][:30]:
        lines.append(f"  [FAIL] {p}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-013 multi-task dataset gate")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate (default)")
    parser.add_argument("--report", action="store_true", help=f"write {G.REPORT_PATH}")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    rep = check(args.data_root)
    if args.report:
        write_report(args.data_root, rep)
    print(format_report(rep))
    return 0 if rep["status"] == "PASS" else 1


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    sys.exit(main())
