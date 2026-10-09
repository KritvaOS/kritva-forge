#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : leakage.py
# Description : Leakage identity, deterministic split assignment and leakage gate (KF-DQ-004, split schema v2 KF-DQ-013.0)
#
# Component   : Kritva Forge
# Module      : dataset
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Split leakage prevention (KF-DQ-004).

Leakage identity model (``LEAKAGE_SCHEMA_VERSION = 1``)
------------------------------------------------------

Every dataset record gets these content identities (``<kind>1:`` + first 16
hex digits of SHA-256; inputs are repository-relative, never absolute):

==================  =======================================================  ==============
identity            input                                                    class
==================  =======================================================  ==============
``source_rtl``      text of the source RTL file (newline/trailing-space      hard
                    normalized)
``module_body``     ``module <name> ... endmodule`` slice, comments          hard
                    stripped, whitespace collapsed
``normalized_ir``   canonical JSON of the module IR without location /       hard
                    identity fields (node_id, source_file, buffer, offset,
                    line, column, is_top, identity_version)
``completion``      dataset completion text (newline/trailing-space          hard
                    normalized)
``body_shape``      module body with identifiers -> ``ID`` and numbers ->    soft
                    ``N`` (renamed-identifier / parameter variants)
``module_name``     module name                                              soft
``ip``              IP name                                                  informational
==================  =======================================================  ==============

A *leakage group* is a connected component of records that share any hard
identity.  A hard group must never span two splits.

Split policy (``SPLIT_SCHEMA_VERSION = 2``, KF-DQ-013.0)
--------------------------------------------------------

1. Records are grouped by hard identities.  In addition, a ``body_shape``
   near-duplicate that occurs in more than one IP (a renamed copy, e.g.
   ``usb1d_crc16`` / ``usb1bd_crc16``) joins its records into one group.
   Split schema v2 adds the ``rtl-sim-v1`` near-duplicate edges of
   ``scripts/dataset/near_duplicate.py``: every pair of canonical modules that
   share a Structural / FSM fingerprint and whose alpha-renamed source
   similarity is >= 0.70 joins the records of both modules into one group
   (same-IP and cross-IP alike), so no near-duplicate pair can cross splits.
   The edges are computed over the whole corpus, independent of the split.
   ``structural_similarity`` (0.30 .. 0.70) stays soft.
   Groups that span more than one IP are *shared library* groups (for
   example ``ctech_cells.sv``, ``registers.v``, ``reset_sync.sv`` reused by many
   IPs).  They are assigned to ``train`` as a unit.
2. Every remaining record belongs to exactly one IP; each IP's remaining
   records form one atomic *IP unit*, so validation/test IPs stay unseen
   apart from shared library code.
3. Target counts are ``round(total * ratio)`` for validation and test
   (ratios 0.70 / 0.15 / 0.15), train takes the rest.
4. IP units are visited in order ``(-size, ip)`` and each goes to the split
   with the largest remaining deficit (``target - assigned``); ties resolve
   in the order train, validation, test.

There is no randomness, no pin list and no IP-family table; the assignment
depends only on record content, IP / module names and the persisted analysis
documents, never on paths, enumeration order or process state.  Without
near-duplicate edges, v2 reproduces the v1 assignment exactly.

The split manifest records the edge document (``near_duplicate``) and, per
group, the edge kinds that joined it (``joined_by``: ``hard``, ``body_shape``,
``near_duplicate``).  The gate recomputes the edges from the data root and
fails on an inconsistent edge list, on any edge that spans two splits, on a
non-reproducible assignment and on any split schema other than 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

LEAKAGE_SCHEMA_VERSION = 1
SPLIT_SCHEMA_VERSION = 2
SPLITS = ("train", "validation", "test")
SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}

HARD_IDENTITIES = ("source_rtl", "module_body", "normalized_ir", "completion")
SOFT_IDENTITIES = ("body_shape", "module_name")
INFO_IDENTITIES = ("ip",)
# Soft identities that become grouping edges when they span IPs.
CROSS_IP_NEAR_DUPLICATE = ("body_shape",)
# Split schema v2 (KF-DQ-013.0): rtl-sim-v1 near-duplicate pairs are grouping edges.
NEAR_DUPLICATE_EDGE = "near_duplicate"
POLICY = ("hard leakage groups atomic; cross-IP body_shape and rtl-sim-v1 near-duplicate (>= 0.70) pairs "
          "join groups; cross-IP groups -> train; IP units greedy by deficit")

# IR fields that describe *where* a construct is, not *what* it is.
IR_LOCATION_FIELDS = frozenset({
    "node_id", "source_file", "buffer", "offset", "line", "column",
    "is_top", "identity_version",
})

_SEP = "\x1f"
_DIGEST_HEX = 16

_VERILOG_KEYWORDS = frozenset("""
module endmodule input output inout wire reg logic bit byte int integer
parameter localparam assign always always_ff always_comb always_latch
posedge negedge or and not if else case casez casex endcase default begin
end for while generate endgenerate genvar function endfunction task endtask
typedef enum struct packed signed unsigned initial
""".split())


# -----------------------------------------------------------------------------
# Identities
# -----------------------------------------------------------------------------

def _digest(kind: str, *parts: object) -> str:
    payload = _SEP.join(["kf-leakage", f"v{LEAKAGE_SCHEMA_VERSION}", kind, *map(str, parts)])
    return f"{kind[0]}{LEAKAGE_SCHEMA_VERSION}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_DIGEST_HEX]


def normalize_text(text: str) -> str:
    """Normalize newlines and trailing whitespace; strip leading/trailing blank lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def module_body(source_text: str, module: str) -> str | None:
    """Return the ``module <name> ... endmodule`` slice (comments stripped)."""
    text = strip_comments(source_text)
    start = re.search(r"\bmodule\s+" + re.escape(module) + r"\b", text)
    if not start:
        return None
    end = re.search(r"\bendmodule\b", text[start.start():])
    if not end:
        return None
    return text[start.start(): start.start() + end.end()]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def body_shape(body: str) -> str:
    """Identifier/number-normalized body used for near-duplicate (soft) detection."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*|\d[\d_']*[bBoOdDhH]?[0-9a-fA-FxXzZ_]*|\S", body)
    shaped = []
    for token in tokens:
        if token[0].isalpha() or token[0] == "_":
            shaped.append(token if token in _VERILOG_KEYWORDS else "ID")
        elif token[0].isdigit():
            shaped.append("N")
        else:
            shaped.append(token)
    return " ".join(shaped)


def _strip_ir(obj):
    if isinstance(obj, dict):
        return {k: _strip_ir(v) for k, v in obj.items() if k not in IR_LOCATION_FIELDS}
    if isinstance(obj, list):
        return [_strip_ir(v) for v in obj]
    return obj


def record_id(record: dict) -> str:
    """Stable record identity: (ip, module, task, prompt_variant)."""
    return "r1:" + hashlib.sha256(_SEP.join([
        "kf-record", "v1",
        str(record["ip"]), str(record["module"]),
        str(record.get("task", "")), str(record.get("prompt_variant", "")),
    ]).encode("utf-8")).hexdigest()[:_DIGEST_HEX]


def content_identities(module: str, spec: dict, source_text: str, fallback_body: str | None = None) -> dict:
    """Module-level content identities (``source_rtl``, ``module_body``, ``normalized_ir``).

    Shared with the KF-DQ-005 provenance manifest so both use one definition.
    """
    body = module_body(source_text, module)
    if body is None:
        body = strip_comments(fallback_body if fallback_body is not None else source_text)
    return {
        "source_rtl": _digest("source_rtl", normalize_text(source_text)),
        "module_body": _digest("module_body", _collapse(body)),
        "normalized_ir": _digest("normalized_ir", json.dumps(_strip_ir(spec), sort_keys=True, separators=(",", ":"))),
        "_body": body,
    }


def compute_identities(record: dict, spec: dict, source_text: str) -> dict:
    """All leakage identities of one dataset record."""
    content = content_identities(record["module"], spec, source_text, fallback_body=record["completion"])
    body = content["_body"]
    return {
        "record_id": record_id(record),
        "source_rtl": content["source_rtl"],
        "module_body": content["module_body"],
        "normalized_ir": content["normalized_ir"],
        "completion": _digest("completion", normalize_text(record["completion"])),
        "body_shape": _digest("body_shape", body_shape(body)),
        "module_name": str(record["module"]),
        "ip": str(record["ip"]),
    }


# -----------------------------------------------------------------------------
# Grouping and assignment
# -----------------------------------------------------------------------------

def build_groups(identities: list[dict], kinds=HARD_IDENTITIES, cross_ip_kinds=(), edges=()) -> list[dict]:
    """Connected components of records sharing any identity in ``kinds``.

    ``cross_ip_kinds`` identities only connect records when the identity
    value occurs in more than one IP (renamed copies across IPs).
    ``edges`` are ``((ip, module), (ip, module))`` near-duplicate pairs
    (split schema v2); each joins every record of both modules.  An edge whose
    module has no record is ignored here (the gate reports it).
    Returns groups sorted by group_id; each group lists sorted record_ids and
    the edge kinds that joined two different components (``joined_by``).
    """
    ordered = sorted(identities, key=lambda i: i["record_id"])
    ips_of = defaultdict(set)
    for ident in ordered:
        for kind in cross_ip_kinds:
            ips_of[(kind, ident[kind])].add(ident["ip"])
    active = lambda kind, ident: kind in kinds or len(ips_of[(kind, ident[kind])]) > 1
    parent = {i["record_id"]: i["record_id"] for i in ordered}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    joined = []

    def union(x, y, why):
        a, b = find(x), find(y)
        if a != b:
            parent[max(a, b)] = min(a, b)
            joined.append((min(a, b), why))

    first = {}
    for ident in ordered:
        for kind in (*kinds, *cross_ip_kinds):
            if not active(kind, ident):
                continue
            key = (kind, ident[kind])
            if key in first:
                union(ident["record_id"], first[key], "hard" if kind in kinds else kind)
            else:
                first[key] = ident["record_id"]

    records_of = defaultdict(list)
    for ident in ordered:
        records_of[(ident["ip"], ident["module_name"])].append(ident["record_id"])
    for a, b in sorted(tuple(sorted(e)) for e in edges):
        ra, rb = records_of.get(tuple(a), []), records_of.get(tuple(b), [])
        chain = [*ra, *rb]
        for x, y in zip(chain, chain[1:]):
            union(x, y, NEAR_DUPLICATE_EDGE)

    members = defaultdict(list)
    by_id = {i["record_id"]: i for i in ordered}
    for rid in parent:
        members[find(rid)].append(rid)
    why = defaultdict(set)
    for root_id, kind in joined:
        why[find(root_id)].add(kind)

    groups = []
    for rids in members.values():
        rids = sorted(rids)
        groups.append({
            "group_id": "g1:" + hashlib.sha256(_SEP.join(rids).encode()).hexdigest()[:_DIGEST_HEX],
            "records": rids,
            "ips": sorted({by_id[r]["ip"] for r in rids}),
            "modules": sorted({by_id[r]["module_name"] for r in rids}),
            "joined_by": sorted(why[find(rids[0])]),
        })
    return sorted(groups, key=lambda g: g["group_id"])


def split_targets(total: int) -> dict:
    validation = round(total * SPLIT_RATIOS["validation"])
    test = round(total * SPLIT_RATIOS["test"])
    return {"train": total - validation - test, "validation": validation, "test": test}


def assign_splits(identities: list[dict], near_duplicate_edges=()) -> tuple[dict, list[dict]]:
    """Deterministic leakage-safe assignment. Returns ({record_id: split}, groups).

    ``near_duplicate_edges``: ``((ip, module), (ip, module))`` pairs from
    ``scripts/dataset/near_duplicate.py`` (split schema v2).  With no edges the
    result equals the split schema v1 assignment.
    """
    groups = build_groups(identities, cross_ip_kinds=CROSS_IP_NEAR_DUPLICATE, edges=near_duplicate_edges)
    assignment = {}
    counts = {s: 0 for s in SPLITS}

    ip_units = defaultdict(list)
    for group in groups:
        if len(group["ips"]) > 1:
            group["policy"] = "shared_library->train"
            for rid in group["records"]:
                assignment[rid] = "train"
            counts["train"] += len(group["records"])
        else:
            group["policy"] = "ip_unit"
            ip_units[group["ips"][0]].extend(group["records"])

    targets = split_targets(len(identities))
    for ip, rids in sorted(ip_units.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        split = max(SPLITS, key=lambda s: (targets[s] - counts[s], -SPLITS.index(s)))
        for rid in rids:
            assignment[rid] = split
        counts[split] += len(rids)

    for group in groups:
        group["split"] = assignment[group["records"][0]]
    return assignment, groups


# -----------------------------------------------------------------------------
# Manifest and checks
# -----------------------------------------------------------------------------

def build_manifest(records: list[dict], identities: list[dict], assignment: dict, groups: list[dict],
                   near_duplicate: dict | None = None) -> dict:
    """Split manifest; ``near_duplicate`` is the edge document used for the assignment."""
    from scripts.dataset import near_duplicate as ND

    by_id = {i["record_id"]: (r, i) for r, i in zip(records, identities)}
    group_of = {rid: g["group_id"] for g in groups for rid in g["records"]}
    manifest = {
        "split_schema_version": SPLIT_SCHEMA_VERSION,
        "leakage_schema_version": LEAKAGE_SCHEMA_VERSION,
        "policy": POLICY,
        "ratios": SPLIT_RATIOS,
        "hard_identities": list(HARD_IDENTITIES),
        "counts": {s: sum(1 for v in assignment.values() if v == s) for s in SPLITS},
        "near_duplicate": near_duplicate if near_duplicate is not None else ND.empty(),
        "groups": [
            {k: g[k] for k in ("group_id", "split", "policy", "joined_by", "ips", "modules", "records")}
            for g in groups
        ],
    }
    for split in SPLITS:
        entries = []
        for rid in sorted(r for r, s in assignment.items() if s == split):
            record, ident = by_id[rid]
            entries.append({
                "record_id": rid,
                "ip": record["ip"],
                "module": record["module"],
                "task": record.get("task"),
                "prompt_variant": record.get("prompt_variant"),
                "group_id": group_of[rid],
                **{k: ident[k] for k in HARD_IDENTITIES},
            })
        manifest[split] = entries
    return manifest


def check_leakage(split_identities: dict, manifest: dict | None = None, near_duplicate: dict | None = None) -> dict:
    """Leakage gate over {split: [identities]}; returns a report with status PASS/FAIL.

    ``near_duplicate`` is the edge document recomputed from the data root
    (``scripts/dataset/near_duplicate.py``).  When given, the manifest's edge
    list must equal it; when omitted, the manifest's own edges are used and
    edge consistency is reported as ``not checked``.
    """
    from scripts.dataset import near_duplicate as ND

    problems = []
    report = {
        "leakage_schema_version": LEAKAGE_SCHEMA_VERSION,
        "records_scanned": sum(len(v) for v in split_identities.values()),
        "counts": {s: len(split_identities.get(s, [])) for s in SPLITS},
        "hard": {}, "soft": {}, "informational": {},
    }

    required = ("record_id", "ip", "module_name") + HARD_IDENTITIES + SOFT_IDENTITIES
    missing = [
        f"{split}: record {ident.get('record_id', '?')} ({ident.get('ip', '?')}/{ident.get('module_name', '?')}) "
        f"missing {', '.join(k for k in required if not ident.get(k))}"
        for split in SPLITS for ident in split_identities.get(split, [])
        if any(not ident.get(k) for k in required)
    ]
    if missing:
        report.update(hard_groups=0, cross_split_hard_groups=0, manifest_status="not checked",
                      near_duplicate={"edges": 0, "effective_edges": 0, "cross_split_edges": 0,
                                      "edge_status": "not checked", "classifier": None},
                      manifest_problems=[], determinism_status="not checked",
                      informational={"ip": {"ips": 0, "ips_in_multiple_splits": 0, "names": []}},
                      problems=[f"missing split identities: {len(missing)} record(s)"] + missing[:20],
                      status="FAIL")
        return report

    seen = {}
    for split in SPLITS:
        for ident in split_identities.get(split, []):
            rid = ident["record_id"]
            if rid in seen:
                problems.append(f"duplicate record {rid} in {seen[rid]} and {split}")
            seen[rid] = split

    def cross(kind):
        splits_of = defaultdict(set)
        members = defaultdict(list)
        for split in SPLITS:
            for ident in split_identities.get(split, []):
                splits_of[ident[kind]].add(split)
                members[ident[kind]].append(f"{ident['ip']}/{ident['module_name']}@{split}")
        crossing = sorted(k for k, v in splits_of.items() if len(v) > 1)
        return len(splits_of), crossing, members

    for kind in HARD_IDENTITIES:
        n, crossing, members = cross(kind)
        report["hard"][kind] = {"groups": n, "cross_split_groups": len(crossing),
                                "examples": [members[k][:6] for k in crossing[:5]]}
        if crossing:
            problems.append(f"hard leakage: {len(crossing)} {kind} group(s) cross splits")
    for kind in SOFT_IDENTITIES:
        n, crossing, members = cross(kind)
        report["soft"][kind] = {"groups": n, "cross_split_groups": len(crossing),
                                "examples": [members[k][:6] for k in crossing[:5]]}
    n, crossing, members = cross("ip")
    report["informational"]["ip"] = {"ips": n, "ips_in_multiple_splits": len(crossing),
                                     "names": crossing}

    all_idents = [i for s in SPLITS for i in split_identities.get(s, [])]
    split_of = {i["record_id"]: s for s in SPLITS for i in split_identities.get(s, [])}

    # -- split schema v2: near-duplicate edges (KF-DQ-013.0) --------------------
    stored_nd = (manifest or {}).get("near_duplicate")
    nd_problems = ND.validate(stored_nd) if manifest is not None else []
    if near_duplicate is not None:
        edge_doc = near_duplicate
        if manifest is not None and stored_nd != near_duplicate:
            nd_problems.append("near_duplicate edges inconsistent: the manifest edge list differs from the "
                               "edges recomputed from the data root")
        edge_status = "consistent" if not nd_problems else "inconsistent"
    else:
        edge_doc = stored_nd if isinstance(stored_nd, dict) else ND.empty()
        edge_status = "not checked" if not nd_problems else "inconsistent"
    try:
        edges = ND.pairs(edge_doc)
    except ND.NearDuplicateError as exc:
        nd_problems.append(str(exc))
        edges = []
    modules_split = defaultdict(set)
    for i in all_idents:
        modules_split[(i["ip"], i["module_name"])].add(split_of[i["record_id"]])
    unknown = sorted(f"{a[0]}/{a[1]} ~ {b[0]}/{b[1]}" for a, b in edges
                     if a not in modules_split or b not in modules_split)
    if unknown:
        nd_problems.append(f"near_duplicate edges reference modules without records: {unknown[:3]}")
    crossing_edges = sorted(f"{a[0]}/{a[1]}@{'+'.join(sorted(modules_split[a]))} ~ "
                            f"{b[0]}/{b[1]}@{'+'.join(sorted(modules_split[b]))}"
                            for a, b in edges if a in modules_split and b in modules_split
                            and len(modules_split[a] | modules_split[b]) > 1)
    if crossing_edges:
        nd_problems.append(f"{len(crossing_edges)} near_duplicate edge(s) cross splits, e.g. {crossing_edges[:3]}")
    v1_groups = build_groups(all_idents, cross_ip_kinds=CROSS_IP_NEAR_DUPLICATE)
    v1_group_of = {r: g["group_id"] for g in v1_groups for r in g["records"]}
    first_record = {}
    for i in sorted(all_idents, key=lambda i: i["record_id"]):
        first_record.setdefault((i["ip"], i["module_name"]), i["record_id"])
    effective = sum(1 for a, b in edges if a in first_record and b in first_record
                    and v1_group_of[first_record[a]] != v1_group_of[first_record[b]])
    report["near_duplicate"] = {
        "classifier": edge_doc.get("classifier") if isinstance(edge_doc, dict) else None,
        "threshold": edge_doc.get("threshold") if isinstance(edge_doc, dict) else None,
        "candidate_pairs": edge_doc.get("candidate_pairs") if isinstance(edge_doc, dict) else None,
        "edges": len(edges),
        "effective_edges": effective,
        "cross_split_edges": len(crossing_edges),
        "examples": crossing_edges[:5],
        "edge_status": edge_status,
    }
    problems.extend(nd_problems)

    groups = build_groups(all_idents)
    report["hard_groups"] = len(groups)
    crossing_groups = [g for g in groups if len({split_of[r] for r in g["records"]}) > 1]
    report["cross_split_hard_groups"] = len(crossing_groups)
    if crossing_groups:
        problems.append(f"{len(crossing_groups)} hard leakage group(s) cross splits")

    # Determinism: recomputing the policy from the persisted identities must
    # reproduce the stored assignment exactly.
    expected, _ = assign_splits(all_idents, edges) if all_idents else ({}, [])
    moved = sorted(r for r, s in split_of.items() if expected.get(r) != s)
    report["determinism_status"] = "reproducible" if not moved else f"differs ({len(moved)} records)"
    if moved:
        problems.append(f"split assignment not reproducible: {len(moved)} record(s) differ, e.g. {moved[:3]}")

    if manifest is None:
        report["manifest_status"] = "absent"
        problems.append("split manifest missing")
    else:
        mstat = []
        if manifest.get("split_schema_version") != SPLIT_SCHEMA_VERSION:
            mstat.append(f"split_schema_version mismatch: manifest {manifest.get('split_schema_version')!r}, "
                         f"forge requires {SPLIT_SCHEMA_VERSION} (regenerate the split)")
        if manifest.get("leakage_schema_version") != LEAKAGE_SCHEMA_VERSION:
            mstat.append("leakage_schema_version mismatch")
        for split in SPLITS:
            want = sorted(e["record_id"] for e in manifest.get(split, []))
            have = sorted(i["record_id"] for i in split_identities.get(split, []))
            if want != have:
                mstat.append(f"{split}: manifest {len(want)} records vs dataset {len(have)}")
            idents = {i["record_id"]: i for i in split_identities.get(split, [])}
            for entry in manifest.get(split, []):
                ident = idents.get(entry["record_id"])
                if ident and any(entry.get(k) != ident[k] for k in HARD_IDENTITIES):
                    mstat.append(f"{split}: identity mismatch for {entry['record_id']}")
                    break
        report["manifest_status"] = "consistent" if not mstat else "inconsistent"
        report["manifest_problems"] = mstat
        problems.extend(mstat)

    report["problems"] = problems
    report["status"] = "FAIL" if problems else "PASS"
    return report


def format_report(report: dict) -> str:
    lines = [
        f"Split leakage check: {report['status']}",
        f"  records scanned     : {report['records_scanned']}",
        f"  train / val / test  : {report['counts']['train']} / {report['counts']['validation']} / {report['counts']['test']}",
        f"  hard leakage groups : {report['hard_groups']}",
        f"  cross-split groups  : {report['cross_split_hard_groups']}",
    ]
    for kind, info in report["hard"].items():
        lines.append(f"  hard {kind:14s}: {info['groups']} groups, {info['cross_split_groups']} cross-split")
    for kind, info in report["soft"].items():
        lines.append(f"  soft {kind:14s}: {info['groups']} groups, {info['cross_split_groups']} cross-split (reported only)")
    nd = report.get("near_duplicate") or {}
    lines.append(f"  near-dup edges      : {nd.get('edges', 0)} ({nd.get('classifier')}; "
                 f"{nd.get('effective_edges', 0)} effective, {nd.get('cross_split_edges', 0)} cross-split; "
                 f"edge list {nd.get('edge_status')})")
    ip = report["informational"]["ip"]
    lines.append(f"  info ip             : {ip['ips_in_multiple_splits']} of {ip['ips']} IPs span splits (shared library)")
    lines.append(f"  manifest status     : {report['manifest_status']}")
    lines.append(f"  determinism status  : {report['determinism_status']}")
    for problem in report["problems"]:
        lines.append(f"  [FAIL] {problem}")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Data-repository gate
# -----------------------------------------------------------------------------

def load_split_identities(data_root: str) -> dict:
    """Recompute identities for every record of datasets/pipeline/{split}.jsonl."""
    import yaml

    from scripts.core.paths import ForgeDataPaths, resolve_provenance_path

    data = ForgeDataPaths.from_root(data_root)
    out = {}
    for split in SPLITS:
        path = data.pipeline_datasets / f"{split}.jsonl"
        idents = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                spec = yaml.safe_load(data.module_yaml(record["ip"], record["module"]).read_text())
                source = resolve_provenance_path(spec["source_file"], data.root)
                with open(source, encoding="utf-8", errors="ignore") as src:
                    idents.append(compute_identities(record, spec, src.read()))
        out[split] = idents
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-004 split leakage gate")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--report", help="write the JSON report here")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())

    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(args.data_root)
    manifest_path = data.splits / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    from scripts.dataset import near_duplicate as ND

    try:
        edges = ND.compute(args.data_root)
    except ND.NearDuplicateError as exc:
        print(f"Split leakage check: FAIL\n  [FAIL] near-duplicate edges cannot be computed: {exc}")
        return 1
    report = check_leakage(load_split_identities(args.data_root), manifest, edges)
    print(format_report(report))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
