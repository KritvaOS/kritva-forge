#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : leakage.py
# Description : Leakage identity, deterministic split assignment and leakage gate (KF-DQ-004)
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

Split policy (``SPLIT_SCHEMA_VERSION = 1``)
------------------------------------------

1. Records are grouped by hard identities.  In addition, a ``body_shape``
   near-duplicate that occurs in more than one IP (a renamed copy, e.g.
   ``usb1d_crc16`` / ``usb1bd_crc16``) joins its records into one group;
   same-IP near-duplicates (e.g. ``aes_sbox`` / ``aes_inv_sbox``, which differ
   only in table constants) stay soft and are only reported.
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

There is no randomness; the assignment depends only on record content and
IP / module names, never on paths, enumeration order or process state.
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
SPLIT_SCHEMA_VERSION = 1
SPLITS = ("train", "validation", "test")
SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}

HARD_IDENTITIES = ("source_rtl", "module_body", "normalized_ir", "completion")
SOFT_IDENTITIES = ("body_shape", "module_name")
INFO_IDENTITIES = ("ip",)
# Soft identities that become grouping edges when they span IPs.
CROSS_IP_NEAR_DUPLICATE = ("body_shape",)

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


def compute_identities(record: dict, spec: dict, source_text: str) -> dict:
    """All leakage identities of one dataset record."""
    body = module_body(source_text, record["module"])
    if body is None:
        body = strip_comments(record["completion"])
    return {
        "record_id": record_id(record),
        "source_rtl": _digest("source_rtl", normalize_text(source_text)),
        "module_body": _digest("module_body", _collapse(body)),
        "normalized_ir": _digest("normalized_ir", json.dumps(_strip_ir(spec), sort_keys=True, separators=(",", ":"))),
        "completion": _digest("completion", normalize_text(record["completion"])),
        "body_shape": _digest("body_shape", body_shape(body)),
        "module_name": str(record["module"]),
        "ip": str(record["ip"]),
    }


# -----------------------------------------------------------------------------
# Grouping and assignment
# -----------------------------------------------------------------------------

def build_groups(identities: list[dict], kinds=HARD_IDENTITIES, cross_ip_kinds=()) -> list[dict]:
    """Connected components of records sharing any identity in ``kinds``.

    ``cross_ip_kinds`` identities only connect records when the identity
    value occurs in more than one IP (renamed copies across IPs).
    Returns groups sorted by group_id; each group lists sorted record_ids.
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

    first = {}
    for ident in ordered:
        for kind in (*kinds, *cross_ip_kinds):
            if not active(kind, ident):
                continue
            key = (kind, ident[kind])
            if key in first:
                a, b = find(ident["record_id"]), find(first[key])
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                first[key] = ident["record_id"]

    members = defaultdict(list)
    by_id = {i["record_id"]: i for i in ordered}
    for rid in parent:
        members[find(rid)].append(rid)

    groups = []
    for rids in members.values():
        rids = sorted(rids)
        groups.append({
            "group_id": "g1:" + hashlib.sha256(_SEP.join(rids).encode()).hexdigest()[:_DIGEST_HEX],
            "records": rids,
            "ips": sorted({by_id[r]["ip"] for r in rids}),
            "modules": sorted({by_id[r]["module_name"] for r in rids}),
        })
    return sorted(groups, key=lambda g: g["group_id"])


def split_targets(total: int) -> dict:
    validation = round(total * SPLIT_RATIOS["validation"])
    test = round(total * SPLIT_RATIOS["test"])
    return {"train": total - validation - test, "validation": validation, "test": test}


def assign_splits(identities: list[dict]) -> tuple[dict, list[dict]]:
    """Deterministic leakage-safe assignment. Returns ({record_id: split}, groups)."""
    groups = build_groups(identities, cross_ip_kinds=CROSS_IP_NEAR_DUPLICATE)
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

def build_manifest(records: list[dict], identities: list[dict], assignment: dict, groups: list[dict]) -> dict:
    by_id = {i["record_id"]: (r, i) for r, i in zip(records, identities)}
    group_of = {rid: g["group_id"] for g in groups for rid in g["records"]}
    manifest = {
        "split_schema_version": SPLIT_SCHEMA_VERSION,
        "leakage_schema_version": LEAKAGE_SCHEMA_VERSION,
        "policy": "hard leakage groups atomic; cross-IP groups -> train; IP units greedy by deficit",
        "ratios": SPLIT_RATIOS,
        "hard_identities": list(HARD_IDENTITIES),
        "counts": {s: sum(1 for v in assignment.values() if v == s) for s in SPLITS},
        "groups": [
            {k: g[k] for k in ("group_id", "split", "policy", "ips", "modules", "records")}
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


def check_leakage(split_identities: dict, manifest: dict | None = None) -> dict:
    """Leakage gate over {split: [identities]}; returns a report with status PASS/FAIL."""
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
    groups = build_groups(all_idents)
    report["hard_groups"] = len(groups)
    split_of = {i["record_id"]: s for s in SPLITS for i in split_identities.get(s, [])}
    crossing_groups = [g for g in groups if len({split_of[r] for r in g["records"]}) > 1]
    report["cross_split_hard_groups"] = len(crossing_groups)
    if crossing_groups:
        problems.append(f"{len(crossing_groups)} hard leakage group(s) cross splits")

    # Determinism: recomputing the policy from the persisted identities must
    # reproduce the stored assignment exactly.
    expected, _ = assign_splits(all_idents) if all_idents else ({}, [])
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
            mstat.append("split_schema_version mismatch")
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
    report = check_leakage(load_split_identities(args.data_root), manifest)
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
