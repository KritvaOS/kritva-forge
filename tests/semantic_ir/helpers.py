# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : helpers.py
# Description : Shared helpers for Semantic IR v2 tests (KF-DQ-008)
#
# Component   : Kritva Forge
# Module      : tests/semantic_ir
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Extract Semantic IR v2 documents from inline RTL through the real writer path."""

import contextlib
import io
import json
from pathlib import Path


def extract(src: str, base: Path, ip: str = "fx", filename: str = "fx.sv", extra: dict | None = None) -> dict:
    """Write ``src`` as ``raw/rtl/original/<ip>/<filename>`` of a scratch data
    repository, run parse_ip + write_semantic_ir and return {module: document}."""
    from scripts.dataset.yaml_generator import write_semantic_ir
    from scripts.parser.rtl_parser_slang import parse_ip

    root = Path(base) / "kritva-forge-data"
    ipdir = root / "raw" / "rtl" / "original" / ip
    ipdir.mkdir(parents=True, exist_ok=True)
    (ipdir / filename).write_text(src, encoding="utf-8")
    for name, text in (extra or {}).items():
        (ipdir / name).write_text(text, encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        modules, top = parse_ip(str(ipdir), data_root=str(root))
    out = root / "normalized" / "ir"
    for name in sorted(modules):
        write_semantic_ir(ip, name, modules, name == top, str(out))
    sem = root / "normalized" / "semantic_ir" / "v2" / ip
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(sem.glob("*.json"))}


def walk(node):
    """Yield every dict below ``node`` (pre-order)."""
    stack = [node]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            yield x
            stack.extend(reversed(list(x.values())))
        elif isinstance(x, list):
            stack.extend(reversed(x))


def by_name(items, name):
    return next(i for i in items if i.get("name") == name)


def sig_id(doc, name):
    for section in ("ports", "signals"):
        for item in doc[section]:
            if item["name"] == name:
                return item["id"]
    raise KeyError(name)


def uses(doc, name, usage=None):
    """Reference-index records whose defining entity is the port/signal/parameter ``name``."""
    ids = {i["id"] for s in ("ports", "signals", "parameters") for i in doc[s] if i["name"] == name}
    return [r for r in doc["references"] if r["target"] in ids and (usage is None or r["usage"] == usage)]


def assigns_to(doc, name):
    sid = sig_id(doc, name)
    return [a for a in doc["assignments"] if sid in a["writes"]]


def refs(expr):
    return sorted(n["name"] for n in walk(expr) if n.get("op") == "ref")


def stmts(process, kind=None):
    out = [n for n in walk(process["body"]) if "stmt" in n]
    return [s for s in out if kind is None or s["stmt"] == kind]
