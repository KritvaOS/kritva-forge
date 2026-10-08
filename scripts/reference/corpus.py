# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : corpus.py
# Description : Reference corpus contract (corpus.yaml) loader, schema check and source-state check (KF-DQ-012.2)
#
# Component   : Kritva Forge
# Module      : reference
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""``reference/corpus.yaml`` — the single source of truth of the reference corpus.

Schema ``kritva-forge-reference-corpus`` version 1::

    schema: {name: kritva-forge-reference-corpus, version: 1}
    ips:
      - id: aes                                  # IP id in raw/rtl/original/<id>
        submodule: reference/sources/security_core
        repository: https://github.com/dineshannayya/security_core.git
        commit: <40 hex>                         # pinned
        license: Apache-2.0
        root: verilog/rtl                        # source root inside the submodule ("" = top)
        incdirs: []                              # relative to the IP directory
        files: [aes128/core/aes_sbox.sv, ...]    # explicit, relative to root; same path inside the IP
        exclusions:                              # files deliberately not materialized
          - {path: ..., reason: ...}
        external_includes:                       # includes known to be absent (e.g. inside an
          - {include: ..., reason: ...}          # undefined `ifdef); any other missing include fails

Files with ``.sv`` / ``.v`` suffixes are listed in ``files.f``; headers
(``.svh`` / ``.vh``) are copied for ``include`` resolution only.  There is no
filesystem discovery: every materialized file is listed here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

import yaml

SCHEMA = {"name": "kritva-forge-reference-corpus", "version": 1}
CORPUS_PATH = "reference/corpus.yaml"
LISTED_SUFFIXES = (".sv", ".v")
HEADER_SUFFIXES = (".svh", ".vh")
IP_KEYS = ("id", "submodule", "repository", "commit", "license", "root", "incdirs", "files", "exclusions",
           "external_includes")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class CorpusError(RuntimeError):
    """The corpus contract or a source checkout is invalid (fail closed)."""


def _rel_ok(p) -> bool:
    if not isinstance(p, str):
        return False
    if p in ("", "."):
        return True
    pp = PurePosixPath(p)
    return not pp.is_absolute() and ".." not in pp.parts and "\\" not in p


def validate(doc) -> list:
    """Schema problems of a corpus document (empty when valid)."""
    p = []
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA}"]
    ips = doc.get("ips")
    if not isinstance(ips, list) or not ips:
        return ["ips must be a non-empty list"]
    seen = set()
    for n, ip in enumerate(ips):
        where = f"ips[{n}]"
        if not isinstance(ip, dict):
            p.append(f"{where}: not a mapping")
            continue
        miss = [k for k in IP_KEYS if k not in ip]
        extra = sorted(set(ip) - set(IP_KEYS))
        if miss or extra:
            p.append(f"{where}: missing {miss} / unknown {extra}")
            continue
        where = f"ip {ip['id']!r}"
        if not isinstance(ip["id"], str) or not _ID.match(ip["id"]):
            p.append(f"{where}: invalid id")
        if ip["id"] in seen:
            p.append(f"{where}: duplicate id")
        seen.add(ip["id"])
        if not isinstance(ip["commit"], str) or not _HEX40.match(ip["commit"]):
            p.append(f"{where}: commit must be 40 lowercase hex digits")
        if not isinstance(ip["repository"], str) or not ip["repository"].startswith("https://"):
            p.append(f"{where}: repository must be an https URL")
        if not isinstance(ip["license"], str) or not ip["license"]:
            p.append(f"{where}: license missing")
        for key in ("submodule", "root"):
            if not _rel_ok(ip[key]):
                p.append(f"{where}: {key} must be a relative path without '..'")
        if not ip["submodule"] or not str(ip["submodule"]).startswith("reference/sources/"):
            p.append(f"{where}: submodule must live under reference/sources/")
        bad_lists = [k for k in ("incdirs", "files", "exclusions", "external_includes") if not isinstance(ip[k], list)]
        if bad_lists:
            p.append(f"{where}: {bad_lists} must be lists")
            continue
        files = ip["files"]
        if not files:
            p.append(f"{where}: files is empty")
        if len(set(files)) != len(files):
            p.append(f"{where}: duplicate files")
        for f in files:
            if not _rel_ok(f) or f in ("", "."):
                p.append(f"{where}: invalid file path {f!r}")
            elif not f.endswith(LISTED_SUFFIXES + HEADER_SUFFIXES):
                p.append(f"{where}: unsupported file type {f!r}")
        if files != sorted(files):
            p.append(f"{where}: files must be sorted")
        for d in ip["incdirs"]:
            if not _rel_ok(d):
                p.append(f"{where}: invalid incdir {d!r}")
        for e in ip["exclusions"]:
            if not isinstance(e, dict) or set(e) != {"path", "reason"}:
                p.append(f"{where}: exclusion must be {{path, reason}}")
                continue
            if not _rel_ok(e["path"]) or not isinstance(e["reason"], str) or not e["reason"].strip():
                p.append(f"{where}: exclusion {e.get('path')!r} needs a relative path and a reason")
            if e["path"] in files:
                p.append(f"{where}: {e['path']} is both listed and excluded")
        for x in ip["external_includes"]:
            if not isinstance(x, dict) or set(x) != {"include", "reason"} or not str(x.get("include", "")).strip() \
                    or not isinstance(x.get("reason"), str) or not x["reason"].strip():
                p.append(f"{where}: external include must be {{include, reason}} with a non-empty reason")
    return p


def load(path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise CorpusError(f"{path} missing")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = validate(doc)
    if problems:
        raise CorpusError(f"{path}: " + "; ".join(problems[:10]))
    return doc


def _git(repo: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise CorpusError(f"git {' '.join(args)} failed in {repo}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def source_state(forge_root, ip: dict) -> dict:
    """HEAD and cleanliness of one submodule checkout (read-only)."""
    sub = Path(forge_root) / ip["submodule"]
    if not (sub / ".git").exists():
        raise CorpusError(f"{ip['submodule']}: not checked out (run make reference-init)")
    head = _git(sub, "rev-parse", "HEAD")
    status = _git(sub, "status", "--porcelain", "--untracked-files=all")
    return {"submodule": ip["submodule"], "head": head, "clean": status == ""}


def check_sources(forge_root, doc: dict) -> list:
    """Every submodule present, clean and at its pinned commit (AC-010)."""
    states = []
    for ip in doc["ips"]:
        st = source_state(forge_root, ip)
        if st["head"] != ip["commit"]:
            raise CorpusError(f"{ip['submodule']}: at {st['head']}, pinned {ip['commit']}")
        if not st["clean"]:
            raise CorpusError(f"{ip['submodule']}: working tree is dirty")
        states.append(st)
    return states
