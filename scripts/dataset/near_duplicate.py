#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : near_duplicate.py
# Description : Split-independent rtl-sim-v1 near-duplicate edges for split schema v2 (KF-DQ-013.0)
#
# Component   : Kritva Forge
# Module      : dataset
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Near-duplicate grouping edges for split schema v2 (KF-DQ-013.0).

Candidates are every pair of canonical modules that share a Structural
Analysis fingerprint or an FSM Analysis per-FSM shape fingerprint, over the
whole corpus and independent of any split (no circular dependency).  A pair
whose ``rtl-sim-v1`` similarity is >= 0.70 (``near_duplicate``) is an edge.
The metric, the fingerprint index and the verified source texts are the
KF-DQ-012 classification's own (``scripts/prompt_v2/classify.py``) - one
implementation.  Edges apply to same-IP and cross-IP pairs alike (D1).

Missing documents, missing sources or a sha256 mismatch fail closed.  The
result is deterministic: sorted candidates and edges, scores rounded to 6
decimals, module keys ``ip/module``; no paths, time or process state.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

from scripts.prompt_v2 import classify as C
from scripts.prompt_v2 import leakage as PL

EDGE_KIND = "near_duplicate"
SOURCES = ("fsm", "structural")


class NearDuplicateError(RuntimeError):
    """Near-duplicate edges cannot be computed (fail closed)."""


def key(ip: str, module: str) -> str:
    return f"{ip}/{module}"


def parse_key(text: str) -> tuple:
    ip, sep, module = str(text).partition("/")
    if not sep or not ip or not module:
        raise NearDuplicateError(f"invalid module key {text!r}")
    return ip, module


def empty() -> dict:
    """The edge document of a corpus without edges (same metadata, no candidates)."""
    return {
        "classifier": C.CLASSIFIER_VERSION,
        "tokenizer": PL.TOKENIZER_VERSION,
        "threshold": C.NEAR_DUPLICATE,
        "sources": list(SOURCES),
        "candidate_pairs": 0,
        "edges": [],
    }


def compute(data_root) -> dict:
    """All near-duplicate edges of the corpus at ``data_root`` (split-independent)."""
    try:
        info, by_fp = C.fingerprint_index(data_root)
        text = C.SourceTexts(data_root, info)
        candidates = set()
        for (_kind, _fp), mods in sorted(by_fp.items()):
            for a, b in itertools.combinations(sorted(mods), 2):
                candidates.add((a, b))
        edges = []
        for a, b in sorted(candidates):
            score = round(C.pair_similarity(text, a, b), 6)
            if score >= C.NEAR_DUPLICATE:
                edges.append({"a": key(*a), "b": key(*b), "similarity": score})
    except C.ClassificationError as exc:
        raise NearDuplicateError(str(exc)) from exc
    doc = empty()
    doc["candidate_pairs"] = len(candidates)
    doc["edges"] = edges
    return doc


def pairs(doc: dict | None) -> list:
    """Edge list as ``((ip, module), (ip, module))`` tuples."""
    return [(parse_key(e["a"]), parse_key(e["b"])) for e in (doc or {}).get("edges", [])]


def validate(doc) -> list:
    """Structural checks of an edge document (versions, threshold, ordering, scores)."""
    p = []
    if not isinstance(doc, dict):
        return ["near_duplicate block missing"]
    want = empty()
    for k in ("classifier", "tokenizer", "threshold", "sources"):
        if doc.get(k) != want[k]:
            p.append(f"near_duplicate {k} is {doc.get(k)!r}, expected {want[k]!r}")
    edges = doc.get("edges")
    if not isinstance(edges, list):
        return p + ["near_duplicate edges missing"]
    keys = []
    for e in edges:
        try:
            a, b = parse_key(e.get("a")), parse_key(e.get("b"))
        except (NearDuplicateError, AttributeError) as exc:
            p.append(str(exc))
            continue
        s = e.get("similarity")
        if not isinstance(s, (int, float)) or not C.NEAR_DUPLICATE <= s <= 1.0:
            p.append(f"near_duplicate edge {e.get('a')} ~ {e.get('b')}: similarity {s!r} below the threshold")
        if not a < b:
            p.append(f"near_duplicate edge {e.get('a')} ~ {e.get('b')}: endpoints not ordered")
        keys.append((a, b))
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        p.append("near_duplicate edges not sorted / unique")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-013.0 near-duplicate split edges (rtl-sim-v1)")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--json", action="store_true", help="print the edge document as JSON")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    try:
        doc = compute(args.data_root)
    except NearDuplicateError as exc:
        print(f"[STOP] near-duplicate edges refused: {exc}")
        return 1
    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 0
    print(f"Near-duplicate edges ({doc['classifier']}, >= {doc['threshold']}): "
          f"{len(doc['edges'])} of {doc['candidate_pairs']} candidate pairs")
    for e in doc["edges"]:
        if e["similarity"] < 1.0:
            print(f"  {e['similarity']:.3f}  {e['a']} ~ {e['b']}")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    sys.exit(main())
