# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : classify.py
# Description : Cross-split structural / FSM group classification by RTL similarity, rtl-sim-v1 (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : prompt_v2
# Layer       : Prompt Generation
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Cross-split leakage classification ``rtl-sim-v1`` (KF-DQ-012 AC-469 .. AC-507, D3, A7).

Groups are recomputed from the persisted documents - never from reports:
modules sharing a Structural Analysis fingerprint, or an FSM Analysis
per-FSM shape fingerprint, whose members sit in more than one split of
``splits/split_manifest.json``.  Groups with the same member set are merged
and keyed by the sorted member module identities.

Similarity of two modules: their canonical source texts (located through
Semantic IR ``module.source``, sha256 verified) are tokenized with the frozen
``sv-lex-v1`` tokenizer (comments removed), identifiers that are not HDL
keywords are alpha-renamed in order of first occurrence (``v0, v1, ...``),
and ``difflib.SequenceMatcher(autojunk=False).ratio()`` is taken.  A group's
score is the maximum over member pairs in different splits.

Classification (frozen): ``near_duplicate`` >= 0.70 > ``structural_similarity``
>= 0.30 > ``informational``.  ``near_duplicate`` groups must be re-split before
KF-DQ-013 consumes Prompt v2; KF-DQ-012 changes no split.  Prompt content and
dataset task labels are never used.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from scripts.prompt_v2 import leakage as L
from scripts.prompt_v2 import model as P

SCHEMA_NAME = "kritva-forge-prompt-leakage-classification"
SCHEMA_VERSION = 1
CLASSIFIER_VERSION = "rtl-sim-v1"
NEAR_DUPLICATE = 0.70
STRUCTURAL_SIMILARITY = 0.30
CLASSES = ("near_duplicate", "structural_similarity", "informational")
SPLIT_MANIFEST = "splits/split_manifest.json"
SPLITS = ("train", "validation", "test")
ACTION = {
    "near_duplicate": "re-split required before KF-DQ-013 consumes Prompt v2",
    "structural_similarity": "retained as a soft finding; KF-DQ-013 reviews it before publication",
    "informational": "does not block KF-DQ-013",
}


class ClassificationError(RuntimeError):
    """Classification refused (fail closed)."""


def classify_score(score: float) -> str:
    if score >= NEAR_DUPLICATE:
        return "near_duplicate"
    if score >= STRUCTURAL_SIMILARITY:
        return "structural_similarity"
    return "informational"


def renamed_tokens(text: str) -> list:
    names, out = {}, []
    for t in L.tokens(text):
        if (t[0].isalpha() or t[0] in "_$") and t not in L.KEYWORDS:
            names.setdefault(t, f"v{len(names)}")
            out.append(names[t])
        else:
            out.append(t)
    return out


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, renamed_tokens(a), renamed_tokens(b), autojunk=False).ratio()


def _load(root: Path, rel: str) -> dict:
    path = root / rel
    if not path.is_file():
        raise ClassificationError(f"missing {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


def build(data_root) -> dict:
    from scripts.prompt_v2.render import canonical_modules, upstream_rel

    root = Path(os.path.abspath(data_root))
    smp = root / SPLIT_MANIFEST
    if not smp.is_file():
        raise ClassificationError(f"{SPLIT_MANIFEST} not present")
    raw = smp.read_bytes()
    sm = json.loads(raw)
    split = defaultdict(set)
    for s in SPLITS:
        for r in sm.get(s, []):
            split[(r["ip"], r["module"])].add(s)
    groups = defaultdict(lambda: {"sources": set(), "fingerprints": set()})
    by_fp = defaultdict(set)
    info = {}
    for ip, module in canonical_modules(root):
        sem = _load(root, upstream_rel("semantic_ir", ip, module))
        st = _load(root, upstream_rel("structural", ip, module))
        fsm = _load(root, upstream_rel("fsm", ip, module))
        info[(ip, module)] = {"module_id": (sem.get("module") or {}).get("module_id"),
                              "source": (sem.get("module") or {}).get("source") or {}}
        if st.get("fingerprint"):
            by_fp[("structural", st["fingerprint"])].add((ip, module))
        for f in fsm.get("fsms", []):
            if f.get("fingerprint"):
                by_fp[("fsm", f["fingerprint"])].add((ip, module))
    for (kind, fp), mods in sorted(by_fp.items()):
        if len({s for k in mods for s in split.get(k, ())}) < 2:
            continue
        key = tuple(sorted(info[k]["module_id"] for k in mods))
        groups[key]["sources"].add(kind)
        groups[key]["fingerprints"].add(fp)
        groups[key]["members"] = sorted(mods)
    texts = {}

    def text(k):
        if k not in texts:
            src = info[k]["source"]
            path = root / str(src.get("path"))
            if not path.is_file():
                raise ClassificationError(f"{k[0]}/{k[1]}: source {src.get('path')!r} missing")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != src.get("sha256"):
                raise ClassificationError(f"{k[0]}/{k[1]}: source {src.get('path')} differs from its Semantic IR sha256")
            texts[k] = data.decode("utf-8", errors="replace")
        return texts[k]

    out = []
    sims = {}
    for key, g in sorted(groups.items()):
        members = g["members"]
        pairs = []
        for a, b in itertools.combinations(members, 2):
            if split.get(a, set()) == split.get(b, set()):
                continue                                 # same split: not a cross-split pair
            pk = tuple(sorted((a, b)))
            if text(a) == text(b):
                score = 1.0
            else:
                if pk not in sims:
                    sims[pk] = similarity(text(a), text(b))
                score = sims[pk]
            pairs.append({"a": f"{a[0]}/{a[1]}", "b": f"{b[0]}/{b[1]}", "similarity": round(score, 6)})
        score = max((p["similarity"] for p in pairs), default=0.0)
        cls = classify_score(score)
        gid = "grp1:" + hashlib.sha256("\x1f".join(key).encode("utf-8")).hexdigest()[:16]
        out.append({
            "id": gid,
            "members": [{"ip": ip, "module": m, "module_id": info[(ip, m)]["module_id"],
                         "splits": sorted(split.get((ip, m), ()))} for ip, m in members],
            "splits": sorted({s for k in members for s in split.get(k, ())}),
            "sources": sorted(g["sources"]),
            "fingerprints": sorted(g["fingerprints"]),
            "pairs": sorted(pairs, key=lambda p: (-p["similarity"], p["a"], p["b"])),
            "metric": {"name": "alpha-renamed token sequence ratio", "aggregation": "max over cross-split pairs",
                       "value": round(score, 6)},
            "classification": cls,
            "action": ACTION[cls],
        })
    out.sort(key=lambda g: g["id"])
    counts = {c: sum(1 for g in out if g["classification"] == c) for c in CLASSES}
    return {
        "schema": {"name": SCHEMA_NAME, "version": SCHEMA_VERSION},
        "classifier_version": CLASSIFIER_VERSION,
        "tokenizer_version": L.TOKENIZER_VERSION,
        "thresholds": {"near_duplicate": NEAR_DUPLICATE, "structural_similarity": STRUCTURAL_SIMILARITY},
        "split_manifest": SPLIT_MANIFEST,
        "split_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "groups": out,
        "counts": {"groups": len(out), **counts},
        "unresolved_near_duplicates": [g["id"] for g in out if g["classification"] == "near_duplicate"],
        "kf_dq_013_entry": "blocked until every near_duplicate group is re-split" if counts["near_duplicate"]
        else "open",
        "splits_changed": False,
        "status": "PASS",
    }


def dumps(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def write(data_root, report: dict | None = None) -> Path:
    root = Path(os.path.abspath(data_root))
    report = report if report is not None else build(root)
    path = root / P.CLASSIFICATION_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(report), encoding="utf-8")
    return path


def validate(report: dict) -> list:
    """Structural checks of a classification report (version, vocabulary, completeness)."""
    p = []
    if report.get("schema") != {"name": SCHEMA_NAME, "version": SCHEMA_VERSION}:
        p.append(f"unsupported classification schema {report.get('schema')!r}")
    if report.get("classifier_version") != CLASSIFIER_VERSION:
        p.append(f"unsupported classifier version {report.get('classifier_version')!r}")
    if report.get("thresholds") != {"near_duplicate": NEAR_DUPLICATE, "structural_similarity": STRUCTURAL_SIMILARITY}:
        p.append("classification thresholds differ from rtl-sim-v1")
    for g in report.get("groups", []):
        if g.get("classification") not in CLASSES:
            p.append(f"group {g.get('id')}: invalid classification {g.get('classification')!r}")
        elif g["classification"] != classify_score((g.get("metric") or {}).get("value", -1)):
            p.append(f"group {g.get('id')}: classification disagrees with its similarity")
    nd = sorted(g.get("id") for g in report.get("groups", []) if g.get("classification") == "near_duplicate")
    if sorted(report.get("unresolved_near_duplicates", [])) != nd:
        p.append("unresolved_near_duplicates disagrees with the group classifications")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-012 cross-split leakage classification (rtl-sim-v1)")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--write", action="store_true", help=f"write {P.CLASSIFICATION_REPORT_PATH}")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    try:
        report = build(args.data_root)
    except ClassificationError as exc:
        print(f"[STOP] classification refused: {exc}")
        return 1
    if args.write:
        write(args.data_root, report)
    c = report["counts"]
    print(f"Cross-split classification ({CLASSIFIER_VERSION}): {c['groups']} groups · near_duplicate "
          f"{c['near_duplicate']} · structural_similarity {c['structural_similarity']} · informational {c['informational']}")
    for g in report["groups"]:
        names = ", ".join(f"{m['ip']}/{m['module']}" for m in g["members"])
        print(f"  {g['classification']:22s} {g['metric']['value']:.3f}  {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
