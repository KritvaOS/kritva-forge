#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : materialize.py
# Description : Materialize the open-source reference corpus into a kritva-forge-data layout root (KF-DQ-012.2)
#
# Component   : Kritva Forge
# Module      : reference
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Build ``build/reference`` from ``reference/corpus.yaml`` (KF-DQ-012.2 AC-016 .. AC-024).

Output::

    build/reference/
      CORPUS_KIND                  "reference" - explicit corpus marker (AC-031)
      reference_manifest.json      evidence: sources, commits, files, sha256 (AC-018)
      kritva-forge-data/           exact kritva-forge-data layout (pipeline DATA_ROOT)
        raw/rtl/original/<ip>/...  byte-identical copies + files.f
        splits/.gitkeep  golden/.gitkeep

The marker and the manifest stay outside the data root, because the
KF-DQ-006 stale gate treats any other root file as UNMANAGED.

Rules:
- every submodule must be at its pinned commit and clean;
- every listed file must exist;
- every ``include`` must resolve inside the IP;
- nothing is written into ``reference/sources``;
- the output is rebuilt from scratch and is deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.reference import corpus as C  # noqa: E402

MANIFEST_SCHEMA = {"name": "kritva-forge-reference-manifest", "version": 1}
DATA_DIR = "kritva-forge-data"
MANIFEST = "reference_manifest.json"
MARKER = "CORPUS_KIND"
MARKER_VALUE = "reference"
_INCLUDE = re.compile(r'^\s*`include\s+"([^"]+)"', re.M)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(doc) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def is_reference_root(data_root) -> bool:
    """True when ``data_root`` is a materialized reference root (explicit marker beside it)."""
    marker = Path(os.path.abspath(data_root)).parent / MARKER
    try:
        return marker.read_text(encoding="utf-8").strip() == MARKER_VALUE
    except OSError:
        return False


def plan(forge_root, doc: dict) -> dict:
    """Resolve and verify every file, include and exclusion (no writes)."""
    forge_root = Path(forge_root)
    C.check_sources(forge_root, doc)
    out = {}
    for ip in doc["ips"]:
        base = forge_root / ip["submodule"] / ip["root"]
        files = []
        for rel in ip["files"]:
            src = base / rel
            if not src.is_file():
                raise C.CorpusError(f"{ip['id']}: listed file {ip['root']}/{rel} missing in {ip['submodule']}")
            data = src.read_bytes()
            files.append({"source": f"{ip['root']}/{rel}".lstrip("/") if ip["root"] not in ("", ".") else rel,
                          "dest": rel, "sha256": _sha(data), "bytes": len(data), "_data": data})
        for e in ip["exclusions"]:
            if not (base / e["path"]).is_file():
                raise C.CorpusError(f"{ip['id']}: excluded file {e['path']} does not exist (stale exclusion)")
        present = {f["dest"] for f in files}
        external = {x["include"] for x in ip["external_includes"]}
        used_external = set()
        dirs = ["."] + list(ip["incdirs"])
        for f in files:
            text = _strip_comments(f["_data"].decode("utf-8", errors="replace"))
            for inc in _INCLUDE.findall(text):
                own = os.path.dirname(f["dest"])
                cands = [os.path.normpath(os.path.join(own, inc))] + \
                        [os.path.normpath(os.path.join(d, inc)) for d in dirs]
                if any(c.replace(os.sep, "/") in present for c in cands):
                    continue
                if inc in external:
                    used_external.add(inc)
                    continue
                raise C.CorpusError(f"{ip['id']}: unresolved include \"{inc}\" in {f['dest']} "
                                    f"(add the file, a documented exclusion or a documented external include)")
        unused = sorted(external - used_external)
        if unused:
            raise C.CorpusError(f"{ip['id']}: documented external include(s) {unused} are never included (stale entry)")
        out[ip["id"]] = {"ip": ip, "files": files}
    return out


def files_f(ip: dict) -> str:
    lines = [f"+incdir+./{d}" if d not in ("", ".") else "+incdir+." for d in ip["incdirs"]]
    lines += [f"./{f}" for f in sorted(ip["files"]) if f.endswith(C.LISTED_SUFFIXES)]
    return "\n".join(lines) + "\n"


def manifest(resolved: dict) -> dict:
    ips = []
    for ip_id in sorted(resolved):
        ip, files = resolved[ip_id]["ip"], resolved[ip_id]["files"]
        ips.append({
            "id": ip_id, "submodule": ip["submodule"], "repository": ip["repository"], "commit": ip["commit"],
            "license": ip["license"], "root": ip["root"], "incdirs": list(ip["incdirs"]),
            "files": [{k: f[k] for k in ("source", "dest", "sha256", "bytes")} for f in files],
            "files_f_sha256": _sha(files_f(ip).encode()),
            "exclusions": [dict(e) for e in ip["exclusions"]],
            "external_includes": [dict(x) for x in ip["external_includes"]],
        })
    corpus = _sha("\n".join(f"{i['id']}/{f['dest']}:{f['sha256']}" for i in ips for f in i["files"]).encode())
    return {"schema": MANIFEST_SCHEMA, "corpus_kind": MARKER_VALUE, "ips": ips,
            "counts": {"ips": len(ips), "files": sum(len(i["files"]) for i in ips),
                       "exclusions": sum(len(i["exclusions"]) for i in ips)},
            "corpus_sha256": corpus}


def materialize(forge_root, corpus_path, out_dir) -> dict:
    forge_root, out_dir = Path(os.path.abspath(forge_root)), Path(os.path.abspath(out_dir))
    doc = C.load(corpus_path)
    resolved = plan(forge_root, doc)
    sources = (forge_root / "reference" / "sources").resolve()
    if out_dir.resolve() == sources or sources in out_dir.resolve().parents:
        raise C.CorpusError("output directory must not be inside reference/sources")
    if out_dir.exists():
        if any(out_dir.iterdir()) and not (out_dir / MARKER).is_file():
            raise C.CorpusError(f"{out_dir} exists and is not a reference build (no {MARKER}); refusing to delete")
        shutil.rmtree(out_dir)
    root = out_dir / DATA_DIR
    for ip_id, r in sorted(resolved.items()):
        ipdir = root / "raw" / "rtl" / "original" / ip_id
        for f in r["files"]:
            dst = ipdir / f["dest"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f["_data"])
        (ipdir / "files.f").write_text(files_f(r["ip"]), encoding="utf-8")
    for keep in ("splits", "golden"):
        (root / keep).mkdir(parents=True, exist_ok=True)
        (root / keep / ".gitkeep").write_text("", encoding="utf-8")
    man = manifest(resolved)
    (out_dir / MANIFEST).write_text(dumps(man), encoding="utf-8")
    (out_dir / MARKER).write_text(MARKER_VALUE + "\n", encoding="utf-8")
    C.check_sources(forge_root, doc)                       # sources untouched (AC-008 / AC-009)
    return man


def sources_state(forge_root, corpus_path) -> list:
    doc = C.load(corpus_path)
    return [C.source_state(forge_root, ip) for ip in doc["ips"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KF-DQ-012.2 reference corpus materialization")
    ap.add_argument("--forge-root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--corpus", default=None, help="default <forge-root>/reference/corpus.yaml")
    ap.add_argument("--out", default=None, help="default <forge-root>/build/reference")
    ap.add_argument("--state", help="write the submodule state (HEAD, clean) to this file and exit")
    ap.add_argument("--check-state", help="compare the submodule state with this file (read-only proof) and exit")
    a = ap.parse_args(argv)
    corpus = a.corpus or str(Path(a.forge_root) / C.CORPUS_PATH)
    out = a.out or str(Path(a.forge_root) / "build" / "reference")
    try:
        if a.state:
            Path(a.state).parent.mkdir(parents=True, exist_ok=True)
            Path(a.state).write_text(dumps(sources_state(a.forge_root, corpus)), encoding="utf-8")
            print(f"[INFO] reference sources state written ({a.state})")
            return 0
        if a.check_state:
            before = json.loads(Path(a.check_state).read_text(encoding="utf-8"))
            after = sources_state(a.forge_root, corpus)
            if before != after:
                print("[FAIL] reference sources changed during the regression:")
                print(dumps({"before": before, "after": after}))
                return 1
            print(f"Reference sources read-only check: PASS ({len(after)} submodules unchanged and clean)")
            return 0
        man = materialize(a.forge_root, corpus, out)
    except C.CorpusError as exc:
        print(f"[STOP] reference corpus: {exc}")
        return 1
    c = man["counts"]
    print(f"Reference corpus materialized: {c['ips']} IPs · {c['files']} files · {c['exclusions']} exclusions · "
          f"corpus {man['corpus_sha256'][:16]} -> {os.path.join(out, DATA_DIR)}")
    for ip in man["ips"]:
        for e in ip["exclusions"]:
            print(f"  excluded {ip['id']}: {e['path']} ({e['reason']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
