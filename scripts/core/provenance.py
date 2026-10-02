#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : provenance.py
# Description : Canonical RTL provenance manifest and validator (KF-DQ-005)
#
# Component   : Kritva Forge
# Module      : core
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""RTL provenance (KF-DQ-005).

Provenance model (``PROVENANCE_VERSION = 1``)
--------------------------------------------

The provenance chain is::

    raw/rtl/original/<ip>/...            source file      sha256 of the file bytes
      -> normalized/ir/<ip>/modules/<m>  normalized IR    sha256 of the YAML bytes
      -> generated/prompts/<ip>/<m>.*    prompts          sha256 of the prompt bytes
      -> datasets/pipeline/<split>.jsonl dataset records  record_id (KF-DQ-004)

The canonical manifest is ``<data-root>/manifests/provenance_manifest.json``;
the validation report is ``<data-root>/analysis/reports/provenance_report.json``.

Identities (all distinct by construction and by field name):

=====================  ==================================================  ==============
identity               definition                                          defined by
=====================  ==================================================  ==============
source identity        ``sha256`` of the source file bytes (64 hex)        KF-DQ-005
module identity        ``"mod1:" + sha256("kf-module","v1",ip,module)``    KF-DQ-005
                       (first 16 hex) - logical identity of the canonical
                       module ``normalized/ir/<ip>/modules/<module>.yaml``
module body identity   ``m1:...`` comment/whitespace-insensitive body      KF-DQ-004
normalized IR identity ``sha256`` of the IR file (exact) and the KF-DQ-004 KF-DQ-005 /
                       location-free ``normalized_ir`` content identity    KF-DQ-004
                       (``n1:...``, recorded as ``ir_content``)
node identity          ``n1:...`` per IR node (``node_id``)                KF-DQ-003
dataset record         ``r1:...`` over (ip, module, task, prompt_variant)  KF-DQ-004
=====================  ==================================================  ==============

Contributing sources of a module are the primary ``source_file`` plus every
file that physically holds one of its IR nodes (``buffer``, KF-DQ-003) and
every file reached through `` `include "..."`` directives (resolved, in order,
against the including file's directory, the IP's ``files.f`` ``+incdir+``
directories, then a unique basename match inside the IP tree).  An
unconditional include that cannot be resolved is recorded under
``unresolved_includes`` and fails validation.  A conditional include (inside
`` `ifdef`` / `` `ifndef``; macros are not evaluated) that is not part of the
corpus - for example yifive's optional ``ycr_arch_custom.svh`` - is recorded
under ``external_includes`` and reported, not failed.  Nothing is silently
dropped.

Hash policy: SHA-256 of raw bytes; no mtime, ctime, PID, UUID, object id,
temporary path or absolute path is used.  Path policy: every persisted path
is POSIX and relative to the data-repository root (KF-DQ-002).  All
collections are sorted, and JSON is written with sorted keys, so the
manifest is byte-identical across runs and checkout locations.

Validation (``python3 scripts/core/provenance.py --check``) recomputes the
manifest from the data tree and fails on missing / orphan / duplicate
records, missing or duplicate module identities, missing, invalid or
incorrect source hashes, absolute paths, invalid IR references, a schema
version mismatch, unresolved includes, dataset records without source
traceability, and a stored manifest that differs from the recomputed one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

PROVENANCE_VERSION = 1
MANIFEST_NAME = "provenance_manifest.json"
REPORT_NAME = "provenance_report.json"
SPLIT_FILES = ("train", "validation", "test")
ORIGINAL_ROOT = "raw/rtl/original"

_SEP = "\x1f"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MODULE_ID = re.compile(r"mod1:[0-9a-f]{16}")
_INCLUDE_RE = re.compile(r'^[ \t]*`include[ \t]+"([^"]+)"')
_COND_OPEN = re.compile(r"^[ \t]*`(ifdef|ifndef)\b")
_COND_CLOSE = re.compile(r"^[ \t]*`endif\b")
_INCDIR_RE = re.compile(r"\+incdir\+([^\s]+)")


# -----------------------------------------------------------------------------
# Identity and hashing
# -----------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    with open(path, "rb") as handle:
        return sha256_bytes(handle.read())


def module_id(ip: str, module: str) -> str:
    """Stable logical identity of the canonical module ``<ip>/<module>``."""
    payload = _SEP.join(("kf-module", f"v{PROVENANCE_VERSION}", str(ip), str(module)))
    return f"mod{PROVENANCE_VERSION}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def portable(path: Path, root: Path) -> str:
    """Repository-relative POSIX form of ``path`` (raises if outside ``root``)."""
    return Path(os.path.normpath(path)).relative_to(root).as_posix()


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


# -----------------------------------------------------------------------------
# Contributing sources
# -----------------------------------------------------------------------------

class IncludeResolver:
    """Deterministic `` `include`` resolution inside the data repository."""

    def __init__(self, root: Path):
        self.root = root
        self._incdirs = {}
        self._basenames = {}
        self._includes = {}

    def incdirs(self, ip: str) -> list[Path]:
        if ip not in self._incdirs:
            dirs = []
            flist = self.root / ORIGINAL_ROOT / ip / "files.f"
            if flist.is_file():
                text = flist.read_text(encoding="utf-8", errors="ignore")
                for match in _INCDIR_RE.finditer(text):
                    for part in match.group(1).split("+"):
                        if part:
                            dirs.append(Path(os.path.normpath(flist.parent / part)))
            self._incdirs[ip] = dirs
        return self._incdirs[ip]

    def by_basename(self, ip: str, name: str) -> list[Path]:
        if ip not in self._basenames:
            index = defaultdict(list)
            ip_root = self.root / ORIGINAL_ROOT / ip
            if ip_root.is_dir():
                for path in sorted(ip_root.rglob("*")):
                    if path.is_file():
                        index[path.name].append(path)
            self._basenames[ip] = index
        return self._basenames[ip].get(os.path.basename(name), [])

    def directives(self, path: Path) -> list[tuple[str, bool]]:
        """``(name, conditional)`` for every `` `include`` in ``path``.

        ``conditional`` is true when the directive sits inside an
        `` `ifdef`` / `` `ifndef`` block (macros are not evaluated).
        """
        if path not in self._includes:
            text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
            found, depth = [], 0
            for line in text.splitlines():
                if _COND_OPEN.match(line):
                    depth += 1
                elif _COND_CLOSE.match(line):
                    depth = max(0, depth - 1)
                match = _INCLUDE_RE.match(line)
                if match:
                    found.append((match.group(1), depth > 0))
            self._includes[path] = found
        return self._includes[path]

    def resolve(self, name: str, including: Path, ip: str) -> Path | None:
        for base in [including.parent, *self.incdirs(ip)]:
            candidate = Path(os.path.normpath(base / name))
            if candidate.is_file():
                return candidate
        matches = self.by_basename(ip, name)
        return matches[0] if len(matches) == 1 else None

    def closure(self, primary: Path, ip: str) -> tuple[list[Path], list[str], list[str]]:
        """Files reached by includes from ``primary``.

        Returns ``(resolved, unresolved, external)``: ``unresolved`` are
        unconditional includes that cannot be found (validation failure);
        ``external`` are conditional includes (inside `` `ifdef``) that are
        not part of the corpus, e.g. an optional project-specific header.
        """
        seen, unresolved, external, queue = set(), set(), set(), [primary]
        while queue:
            current = queue.pop(0)
            for name, conditional in self.directives(current):
                target = self.resolve(name, current, ip)
                if target is None:
                    (external if conditional else unresolved).add(name)
                elif target not in seen and target != primary:
                    seen.add(target)
                    queue.append(target)
        return sorted(seen), sorted(unresolved), sorted(external - unresolved)


def _node_buffers(obj, acc: set) -> None:
    if isinstance(obj, dict):
        buffer = obj.get("buffer")
        if isinstance(buffer, str) and buffer:
            acc.add(buffer)
        for value in obj.values():
            _node_buffers(value, acc)
    elif isinstance(obj, list):
        for value in obj:
            _node_buffers(value, acc)


# -----------------------------------------------------------------------------
# Dataset record provenance (embedded in datasets/pipeline/*.jsonl)
# -----------------------------------------------------------------------------

def record_provenance(record: dict, source_path: str, source_sha256: str,
                      ir_path: str, ir_sha256: str, generated_artifact: dict | None = None) -> dict:
    """Compact provenance block for one dataset record (no RTL payload)."""
    from scripts.dataset.leakage import record_id

    return {
        "provenance_version": PROVENANCE_VERSION,
        "record_id": record_id(record),
        "module_id": module_id(record["ip"], record["module"]),
        "source": {"type": "original", "path": source_path, "sha256": source_sha256},
        "normalized_ir": {"path": ir_path, "sha256": ir_sha256},
        "generated_artifact": generated_artifact,
    }


def iter_dataset_records(data_root: str | os.PathLike[str]):
    """Yield ``(split, line_number, record)`` for datasets/pipeline/{split}.jsonl."""
    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(data_root)
    for split in SPLIT_FILES:
        path = data.pipeline_datasets / f"{split}.jsonl"
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line.strip():
                    yield split, line_no, json.loads(line)


# -----------------------------------------------------------------------------
# Manifest
# -----------------------------------------------------------------------------

def build_manifest(data_root: str | os.PathLike[str]) -> dict:
    """Recompute the canonical provenance manifest from the data tree."""
    import yaml

    from scripts.core.paths import ForgeDataPaths
    from scripts.dataset.leakage import content_identities

    data = ForgeDataPaths.from_root(data_root)
    root = data.root
    resolver = IncludeResolver(root)

    records = defaultdict(list)
    for split, _, record in iter_dataset_records(root):
        prov = record.get("provenance") or {}
        records[(record.get("ip"), record.get("module"))].append({
            "record_id": prov.get("record_id"),
            "split": split,
            "task": record.get("task"),
            "prompt_variant": record.get("prompt_variant"),
        })

    modules, sources = [], {}
    versions = defaultdict(set)

    def source_entry(path: Path) -> dict:
        rel = portable(path, root)
        if rel not in sources:
            sources[rel] = {
                "path": rel,
                "sha256": sha256_file(path) if path.is_file() else None,
                "modules": set(),
            }
        return sources[rel]

    for yaml_path in data.iter_module_yamls():
        ip = yaml_path.parent.parent.name
        name = yaml_path.stem
        ir_bytes = yaml_path.read_bytes()
        spec = yaml.safe_load(ir_bytes.decode("utf-8")) or {}
        mid = module_id(ip, name)
        for key in ("parser", "parser_version", "identity_version"):
            versions[key].add(str(spec.get(key)))

        status = "normalized"
        source_rel = spec.get("source_file")
        primary = root / source_rel if source_rel and not os.path.isabs(source_rel) else None
        contributing, unresolved, external, ident = [], [], [], {}
        if primary is None:
            status = "source_unrecorded"
        elif not primary.is_file():
            status = "source_missing"
        else:
            text = primary.read_text(encoding="utf-8", errors="ignore")
            ident = content_identities(name, spec, text)
            buffers = set()
            _node_buffers(spec, buffers)
            includes, unresolved, external = resolver.closure(primary, ip)
            extra = {root / b for b in buffers if not os.path.isabs(b)} | set(includes)
            extra.discard(primary)
            for path in [primary, *sorted(extra)]:
                entry = source_entry(path)
                entry["modules"].add(mid)
                contributing.append({
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "role": "primary" if path == primary else "include",
                })
            if unresolved:
                status = "include_unresolved"

        prompts = []
        for rec in records.get((ip, name), []):
            prompt = data.prompts / ip / str(rec["prompt_variant"])
            if prompt.is_file():
                prompts.append({"path": portable(prompt, root), "sha256": sha256_file(prompt)})
        prompts = sorted({p["path"]: p for p in prompts}.values(), key=lambda p: p["path"])

        artifacts = []
        if source_rel:
            copy = yaml_path.parent.parent / "rtl" / os.path.basename(source_rel)
            if copy.is_file():
                copy_sha = sha256_file(copy)
                artifacts.append({
                    "kind": "rtl_copy",
                    "path": portable(copy, root),
                    "sha256": copy_sha,
                    "matches_source": bool(contributing) and copy_sha == contributing[0]["sha256"],
                })

        modules.append({
            "ip": ip,
            "module": name,
            "module_id": mid,
            "transformation": status,
            "source": {
                "path": source_rel,
                "sha256": contributing[0]["sha256"] if contributing else None,
            },
            "contributing_sources": contributing,
            "unresolved_includes": unresolved,
            "external_includes": external,
            "normalized_ir": {
                "path": portable(yaml_path, root),
                "sha256": sha256_bytes(ir_bytes),
                "ir_content": ident.get("normalized_ir"),
            },
            "module_body": ident.get("module_body"),
            "prompts": prompts,
            "artifacts": artifacts,
            "dataset_records": sorted(records.get((ip, name), []),
                                      key=lambda r: (str(r["record_id"]), r["split"])),
        })

    modules.sort(key=lambda m: (m["ip"], m["module"]))
    source_list = [
        {"path": s["path"], "sha256": s["sha256"], "modules": sorted(s["modules"])}
        for _, s in sorted(sources.items())
    ]
    from scripts.dataset.leakage import LEAKAGE_SCHEMA_VERSION, SPLIT_SCHEMA_VERSION

    return {
        "provenance_version": PROVENANCE_VERSION,
        "pipeline": {
            **{k: sorted(v)[0] if len(v) == 1 else sorted(v) for k, v in sorted(versions.items())},
            "leakage_schema_version": LEAKAGE_SCHEMA_VERSION,
            "split_schema_version": SPLIT_SCHEMA_VERSION,
        },
        "source_root": ORIGINAL_ROOT,
        "counts": {
            "ips": len({m["ip"] for m in modules}),
            "modules": len(modules),
            "sources": len(source_list),
            "dataset_records": sum(len(m["dataset_records"]) for m in modules),
        },
        "sources": source_list,
        "modules": modules,
    }


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def write_manifest(data_root, manifest: dict | None = None) -> Path:
    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(data_root)
    manifest = build_manifest(data.root) if manifest is None else manifest
    data.manifests.mkdir(parents=True, exist_ok=True)
    path = data.manifests / MANIFEST_NAME
    path.write_text(dumps(manifest), encoding="utf-8")
    return path


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def check_provenance(data_root: str | os.PathLike[str], manifest: dict | None = None) -> dict:
    """Validate ``manifest`` (default: the stored one) against the data tree."""
    from scripts.core.paths import ForgeDataPaths, find_absolute_paths, iter_module_yamls
    from scripts.dataset.leakage import record_id

    data = ForgeDataPaths.from_root(data_root)
    root = data.root
    stored_path = data.manifests / MANIFEST_NAME
    if manifest is None and stored_path.is_file():
        manifest = json.loads(stored_path.read_text(encoding="utf-8"))

    problems = []
    counts = defaultdict(int)

    def bad(kind, message):
        counts[kind] += 1
        problems.append(message)

    rebuilt = build_manifest(root)
    canonical = {(p.parent.parent.name, p.stem) for p in iter_module_yamls(data.normalized_ir)}

    if manifest is None:
        bad("missing_manifest", f"provenance manifest missing: {stored_path.relative_to(root).as_posix()}")
        manifest = {"modules": [], "sources": []}
    elif manifest.get("provenance_version") != PROVENANCE_VERSION:
        bad("invalid_schema", f"invalid provenance_version {manifest.get('provenance_version')!r} "
                              f"(expected {PROVENANCE_VERSION})")

    text = dumps(manifest)
    for line_no, line in find_absolute_paths(text):
        bad("absolute_paths", f"absolute path in manifest line {line_no}: {line.strip()[:100]}")
    if str(root) in text:
        bad("absolute_paths", "manifest contains the data-root location")

    entries = manifest.get("modules", [])
    seen_keys, seen_ids = {}, {}
    for entry in entries:
        key = (entry.get("ip"), entry.get("module"))
        if key in seen_keys:
            bad("duplicate_entries", f"duplicate provenance entry {key[0]}/{key[1]}")
            continue
        seen_keys[key] = entry
        mid = entry.get("module_id")
        if not mid:
            bad("missing_identity", f"{key[0]}/{key[1]}: missing module identity")
        elif not _MODULE_ID.fullmatch(str(mid)) or mid != module_id(*key):
            bad("invalid_identity", f"{key[0]}/{key[1]}: module identity {mid} does not match {module_id(*key)}")
        if mid in seen_ids:
            bad("duplicate_identities", f"duplicate module identity {mid}: {seen_ids[mid]} and {key[0]}/{key[1]}")
        seen_ids[mid] = f"{key[0]}/{key[1]}"

        if key not in canonical:
            bad("orphan_records", f"orphan provenance record {key[0]}/{key[1]} (no canonical IR)")
            continue

        source = entry.get("source") or {}
        spath, ssha = source.get("path"), source.get("sha256")
        if not spath or os.path.isabs(str(spath)) or not str(spath).startswith(ORIGINAL_ROOT + "/"):
            bad("unresolved_sources", f"{key[0]}/{key[1]}: invalid source path {spath!r}")
        elif not (root / spath).is_file():
            bad("unresolved_sources", f"{key[0]}/{key[1]}: source file missing {spath}")
        for src in entry.get("contributing_sources", []) or [source]:
            sha, path = src.get("sha256"), src.get("path")
            if not isinstance(sha, str) or not _HEX64.fullmatch(sha):
                bad("invalid_hashes", f"{key[0]}/{key[1]}: invalid sha256 {sha!r} for {path}")
            elif path and not os.path.isabs(str(path)) and (root / path).is_file() \
                    and sha256_file(root / path) != sha:
                bad("incorrect_hashes", f"{key[0]}/{key[1]}: sha256 mismatch for {path}")

        ir = entry.get("normalized_ir") or {}
        expected_ir = data.module_yaml(*key)
        if ir.get("path") != portable(expected_ir, root):
            bad("invalid_ir_refs", f"{key[0]}/{key[1]}: IR reference {ir.get('path')!r} is not canonical")
        elif ir.get("sha256") != sha256_file(expected_ir):
            bad("invalid_ir_refs", f"{key[0]}/{key[1]}: IR sha256 mismatch")

    # Include resolution is judged on the current tree (recomputed manifest).
    for entry in rebuilt["modules"]:
        if entry.get("external_includes"):
            counts["external_includes"] += 1
        if entry.get("unresolved_includes"):
            bad("unresolved_includes",
                f"{entry['ip']}/{entry['module']}: unresolved include(s) {entry['unresolved_includes']}")

    for key in sorted(canonical - set(seen_keys)):
        bad("missing_records", f"missing provenance record for {key[0]}/{key[1]}")

    # Dataset traceability
    records_checked = 0
    for split, line_no, record in iter_dataset_records(root):
        records_checked += 1
        where = f"{split}.jsonl:{line_no} ({record.get('ip')}/{record.get('module')})"
        prov = record.get("provenance")
        if not isinstance(prov, dict):
            bad("untraceable_records", f"{where}: dataset record has no provenance")
            continue
        entry = seen_keys.get((record.get("ip"), record.get("module")))
        if entry is None:
            bad("untraceable_records", f"{where}: no provenance record for its module")
            continue
        if prov.get("record_id") != record_id(record):
            bad("untraceable_records", f"{where}: record_id mismatch")
        if prov.get("module_id") != entry.get("module_id"):
            bad("untraceable_records", f"{where}: module_id mismatch")
        src = prov.get("source") or {}
        if (src.get("path"), src.get("sha256")) != (entry["source"].get("path"), entry["source"].get("sha256")):
            bad("untraceable_records", f"{where}: source path/sha256 does not match the manifest")
        if (prov.get("normalized_ir") or {}).get("sha256") != (entry.get("normalized_ir") or {}).get("sha256"):
            bad("untraceable_records", f"{where}: normalized IR sha256 does not match the manifest")

    deterministic = dumps(manifest) == dumps(rebuilt)
    if not deterministic and not counts.get("missing_manifest"):
        bad("nondeterministic", "stored provenance manifest differs from the manifest recomputed "
                                "from the data tree (stale or nondeterministic)")

    report = {
        "provenance_version": PROVENANCE_VERSION,
        "records_checked": records_checked,
        "modules_checked": len(canonical),
        "manifest_modules": len(entries),
        "source_files_checked": len(rebuilt["sources"]),
        "missing_records": counts["missing_records"],
        "orphan_records": counts["orphan_records"],
        "duplicate_entries": counts["duplicate_entries"],
        "duplicate_identities": counts["duplicate_identities"],
        "missing_identities": counts["missing_identity"] + counts["invalid_identity"],
        "invalid_hashes": counts["invalid_hashes"],
        "incorrect_hashes": counts["incorrect_hashes"],
        "absolute_paths": counts["absolute_paths"],
        "unresolved_sources": counts["unresolved_sources"],
        "unresolved_includes": counts["unresolved_includes"],
        "modules_with_external_includes": counts["external_includes"],
        "invalid_ir_refs": counts["invalid_ir_refs"],
        "untraceable_records": counts["untraceable_records"],
        "schema_status": "invalid" if counts["invalid_schema"] else ("absent" if counts["missing_manifest"] else "valid"),
        "determinism_status": "reproducible" if deterministic else "differs",
        "relocation_status": "location-independent" if not counts["absolute_paths"] else "location-dependent",
        "problems": problems,
    }
    report["status"] = "FAIL" if problems else "PASS"
    return report


def format_report(report: dict) -> str:
    rows = [
        ("records checked", "records_checked"), ("modules checked", "modules_checked"),
        ("manifest modules", "manifest_modules"), ("source files checked", "source_files_checked"),
        ("missing records", "missing_records"), ("orphan records", "orphan_records"),
        ("duplicate entries", "duplicate_entries"), ("duplicate identities", "duplicate_identities"),
        ("missing identities", "missing_identities"), ("invalid hashes", "invalid_hashes"),
        ("incorrect hashes", "incorrect_hashes"), ("absolute paths", "absolute_paths"),
        ("unresolved sources", "unresolved_sources"), ("unresolved includes", "unresolved_includes"),
        ("external includes", "modules_with_external_includes"),
        ("invalid IR refs", "invalid_ir_refs"), ("untraceable records", "untraceable_records"),
        ("schema", "schema_status"), ("determinism", "determinism_status"),
        ("relocation", "relocation_status"),
    ]
    lines = [f"Provenance check: {report['status']}"]
    lines += [f"  {label:21s}: {report[key]}" for label, key in rows]
    lines += [f"  [FAIL] {p}" for p in report["problems"][:40]]
    if len(report["problems"]) > 40:
        lines.append(f"  ... {len(report['problems']) - 40} more")
    return "\n".join(lines)


def write_report(data_root, report: dict) -> Path:
    from scripts.core.paths import ForgeDataPaths

    data = ForgeDataPaths.from_root(data_root)
    data.reports.mkdir(parents=True, exist_ok=True)
    path = data.reports / REPORT_NAME
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-005 RTL provenance manifest / validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate the stored manifest (default)")
    mode.add_argument("--write", action="store_true", help="regenerate the manifest, then validate")
    parser.add_argument("--report", help="also write the JSON report here")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())

    if args.write:
        print(f"[INFO] wrote {write_manifest(args.data_root)}")
    report = check_provenance(args.data_root)
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
