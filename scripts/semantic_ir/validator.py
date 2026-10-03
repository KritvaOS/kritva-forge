#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : Semantic IR v2 schema and reference validation (KF-DQ-008)
#
# Component   : Kritva Forge
# Module      : semantic_ir
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 validation (KF-DQ-008, criteria sections 13 and 17).

``validate_module(doc)`` returns ``[(code, message), ...]`` for one module
document; ``check(data_root)`` validates every document under
``normalized/semantic_ir/v2`` against the canonical module inventory and is
the ``make check-semantic`` gate (fail closed).  Validation is independent of
extraction: it only reads the persisted JSON.

Codes:

==========================  ===================================================
``schema``                  unsupported schema name / version
``identity_version``        unsupported semantic identity version
``required``                missing section or field
``enum``                    value outside an enumeration
``identity``                missing / malformed identity (``sem1:``, ``mod1:``)
``duplicate_identity``      one identity used by several entities
``duplicate_declaration``   one name declared twice in a scope
``provenance``              missing source path / sha256 / location
``absolute_path``           absolute or machine-local path
``path_traversal``          ``.`` / ``..`` path segment
``direction``               invalid port direction
``width``                   invalid width or width inconsistent with ranges
``expression``              malformed expression or statement node
``assignment``              malformed assignment (target, operator, value)
``control``                 malformed condition / case record
``broken_reference``        reference to a non-existent entity, or a
                            resolvable symbol kind without its definition
``broken_instance``         invalid instance module resolution
``ordering``                section not in canonical order
``silent_loss``             unsupported construct not accounted for
``inventory``               document / canonical-module mismatch (corpus)
``duplicate_module_identity``  two documents with one module identity (corpus)
``duplicate_output_path``   two documents for one canonical output (corpus)
``nondeterministic``        bytes differ from the canonical serialisation
==========================  ===================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

from scripts.semantic_ir import model as M

_DECL_SECTIONS = ("parameters", "ports", "signals")
_RESOLVABLE = ("port", "signal", "parameter", "genvar", "local", "enum_member", "subroutine", "type")
_UNRESOLVED_KINDS = ("unresolved", "hierarchical", "external")
_TARGET_OPS = ("ref", "index", "part_select", "member", "concat", "opaque")
_SIZED_TYPES = (None, "logic", "reg", "bit", "wire")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _path_problem(path) -> str | None:
    if not isinstance(path, str) or not path:
        return "provenance"
    if path.startswith("/") or os.path.isabs(path) or "\\" in path or re.match(r"^[A-Za-z]:", path):
        return "absolute_path"
    if any(p in ("..", ".") for p in PurePosixPath(path).parts):
        return "path_traversal"
    return None


def validate_module(doc: dict, known_module_ids: set | None = None) -> list:
    problems = []

    def bad(code, msg):
        problems.append((code, msg))

    if not isinstance(doc, dict):
        return [("schema", "document is not an object")]
    if doc.get("schema") != {"name": M.SCHEMA_NAME, "version": M.SCHEMA_VERSION}:
        bad("schema", f"unsupported schema {doc.get('schema')!r}")
        return problems
    for key in ("module", "versions", "generator", "extraction", "coverage", "external", "counts") \
            + M.MODULE_SECTIONS:
        if key not in doc:
            bad("required", f"missing section {key}")
    if problems:
        return problems

    # ---------------------------------------------------------------- versions
    ver = doc["versions"] if isinstance(doc["versions"], dict) else {}
    if ver.get("schema") != M.SCHEMA_VERSION:
        bad("schema", f"versions.schema {ver.get('schema')!r}")
    if ver.get("identity") != M.IDENTITY_VERSION:
        bad("identity_version", f"unsupported semantic identity version {ver.get('identity')!r} "
            f"(expected {M.IDENTITY_VERSION})")
    if not isinstance(ver.get("node_identity"), int):
        bad("identity_version", f"node identity version {ver.get('node_identity')!r}")
    if not isinstance(ver.get("parser"), str) or not ver.get("parser"):
        bad("required", "versions.parser missing")
    if (ver.get("compatibility") or {}).get("normalized_ir") != M.COMPATIBLE_NORMALIZED_IR:
        bad("schema", f"versions.compatibility {ver.get('compatibility')!r}")

    # ---------------------------------------------------------------- module / provenance
    mod = doc["module"] if isinstance(doc["module"], dict) else {}
    for key in ("name", "id", "ip", "loc"):
        if key not in mod:
            bad("required", f"module.{key} missing")
    if not isinstance(mod.get("module_id"), str) or not M.MODULE_ID_RE.fullmatch(mod["module_id"]):
        bad("identity", f"missing or invalid module identity {mod.get('module_id')!r}")
    src = mod.get("source")
    if not isinstance(src, dict):
        bad("provenance", "module.source missing")
    else:
        code = _path_problem(src.get("path"))
        if code:
            bad(code, f"module source path {src.get('path')!r}")
        if not isinstance(src.get("sha256"), str) or not _SHA_RE.fullmatch(src["sha256"]):
            bad("provenance", f"module source sha256 {src.get('sha256')!r}")
    if doc["extraction"] not in M.EXTRACTION:
        bad("enum", f"extraction {doc['extraction']!r}")

    ids = Counter()
    objects = {}

    def register(obj, where):
        oid = obj.get("id") if isinstance(obj, dict) else None
        if not isinstance(oid, str) or not M.ID_RE.fullmatch(oid):
            bad("identity", f"{where}: invalid identity {oid!r}")
            return
        ids[oid] += 1
        objects[oid] = where

    def check_loc(obj, where):
        loc = obj.get("loc") if isinstance(obj, dict) else None
        if not isinstance(loc, dict) or "file" not in loc or not loc.get("line"):
            bad("provenance", f"{where}: missing source location")
            return
        code = _path_problem(loc.get("file"))
        if code:
            bad(code, f"{where}: provenance path {loc.get('file')!r}")

    def check_width(obj, where):
        w = obj.get("width")
        if w is not None and (not isinstance(w, int) or isinstance(w, bool) or w < 1):
            bad("width", f"{where}: invalid width {w!r}")
            return
        packed = obj.get("packed", [])
        if not isinstance(packed, list) or any(not isinstance(r, dict) or "text" not in r for r in packed):
            bad("width", f"{where}: malformed packed dimensions")
            return
        if w is not None and packed and obj.get("type") in _SIZED_TYPES:
            vals = [(r.get("left_value"), r.get("right_value")) for r in packed]
            if all(isinstance(a, int) and isinstance(b, int) for a, b in vals):
                expect = 1
                for a, b in vals:
                    expect *= abs(a - b) + 1
                if expect != w:
                    bad("width", f"{where}: width {w} != packed dimensions {expect}")

    register(mod, "module")
    check_loc(mod, "module")
    decls = {}
    for section in _DECL_SECTIONS:
        for obj in doc[section]:
            where = f"{section}:{obj.get('name')}"
            register(obj, where)
            check_loc(obj, where)
            check_width(obj, where)
            key = (obj.get("scope", ""), obj.get("name"))
            if key in decls:
                bad("duplicate_declaration", f"{where} redeclared in scope {key[0]!r}")
            decls[key] = obj.get("id")
            if section != "parameters" and obj.get("kind") not in M.DECL_KINDS:
                bad("enum", f"{where}: kind {obj.get('kind')!r}")
            if section == "ports" and obj.get("direction") not in M.DIRECTIONS:
                bad("direction", f"{where}: invalid port direction {obj.get('direction')!r}")
    for td in doc["typedefs"]:
        register(td, f"typedef:{td.get('name')}")
        check_loc(td, f"typedef:{td.get('name')}")
        for m in td.get("members", []):
            register(m, f"typedef-member:{m.get('name')}")
    for sub in doc["subroutines"]:
        register(sub, f"subroutine:{sub.get('name')}")
        check_loc(sub, f"subroutine:{sub.get('name')}")
        for p in sub.get("ports", []):
            register(p, f"subroutine-port:{p.get('name')}")
            check_width(p, f"subroutine-port:{p.get('name')}")
    for section in ("assignments", "processes", "instances", "generates"):
        for obj in doc[section]:
            register(obj, f"{section[:-1]}:{obj.get('name') or obj.get('kind')}")
            check_loc(obj, f"{section[:-1]}:{obj.get('id')}")
    for u in doc["unsupported"]:
        check_loc(u, f"unsupported:{u.get('construct')}")
    if not isinstance(doc.get("external"), list):
        bad("required", "external is not a list")
    else:
        for x in doc["external"]:
            if x.get("kind") not in M.EXTERNAL_KINDS:
                bad("enum", f"external:{x.get('name')}: kind {x.get('kind')!r}")
            check_loc(x, f"external:{x.get('name')}")
    external_names = {x.get("name") for x in doc.get("external") or [] if isinstance(x, dict)}

    # ---------------------------------------------------------------- statements + expressions
    statements = {}
    assignment_ids = {a.get("id") for a in doc["assignments"]}
    ref_nodes = []
    expr_opaque, stmt_opaque = set(), set()

    def walk_expr(e, where):
        if e is None:
            return
        if not isinstance(e, dict) or e.get("op") not in M.EXPRESSIONS:
            bad("expression", f"{where}: malformed expression node {str(e)[:80]}")
            return
        for field in M.EXPR_FIELDS[e["op"]]:
            if field not in e:
                bad("expression", f"{where}: {e['op']} node missing {field}")
                return
        op = e["op"]
        if op == "opaque":
            expr_opaque.add(e.get("id"))
        elif op == "ref":
            ref_nodes.append(e)
            if e.get("ref_kind") not in M.REF_KINDS:
                bad("enum", f"{where}: ref kind {e.get('ref_kind')!r}")
            if not isinstance(e.get("id"), str) or not M.ID_RE.fullmatch(e["id"]):
                bad("identity", f"{where}: reference {e.get('name')!r} has invalid identity {e.get('id')!r}")
            return
        elif op in ("unary", "binary") and (not isinstance(e.get("operator"), str) or not e["operator"]):
            bad("expression", f"{where}: {op} without operator")
        elif op in ("binary",) and (e.get("left") is None or e.get("right") is None):
            bad("expression", f"{where}: binary operand missing")
        elif op == "ternary" and any(e.get(k) is None for k in ("cond", "then", "else")):
            bad("expression", f"{where}: ternary operand missing")
        elif op in ("concat", "replicate") and not isinstance(e.get("items"), list):
            bad("expression", f"{where}: {op} items are not a list")
        for k, v in e.items():
            if k == "loc":
                continue
            if isinstance(v, dict) and "op" in v:
                walk_expr(v, where)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, dict) and "op" in x:
                        walk_expr(x, where)

    def walk_tree(x, where):
        """Every expression node below a non-expression container (declarations, instances ...)."""
        if isinstance(x, dict):
            if "op" in x:
                walk_expr(x, where)
                return
            for k, v in x.items():
                if k != "loc":
                    walk_tree(v, where)
        elif isinstance(x, list):
            for v in x:
                walk_tree(v, where)

    def walk_stmt(st, where):
        if st is None:
            return
        if not isinstance(st, dict) or st.get("stmt") not in M.STATEMENTS:
            bad("expression", f"{where}: malformed statement node {str(st)[:80]}")
            return
        for field in M.STMT_FIELDS[st["stmt"]]:
            if field not in st:
                bad("expression", f"{where}: {st['stmt']} statement missing {field}")
                return
        check_loc(st, f"{where}:{st['stmt']}")
        kind = st["stmt"]
        if kind == "assign":
            if st["assignment"] not in assignment_ids:
                bad("broken_reference", f"{where}: statement refers to unknown assignment {st['assignment']}")
            if st["id"] != st["assignment"]:
                bad("identity", f"{where}: assign statement id differs from its assignment")
        else:
            if not isinstance(st["id"], str) or not M.ID_RE.fullmatch(st["id"]):
                bad("identity", f"{where}: statement identity {st['id']!r}")
            elif st["id"] in statements or st["id"] in ids:
                bad("duplicate_identity", f"{where}: statement identity {st['id']} duplicated")
            statements[st["id"]] = st
        if kind == "opaque":
            stmt_opaque.add(st["id"])
        elif kind == "if":
            if st["cond"] is None:
                bad("control", f"{where}: if without predicate")
            walk_expr(st["cond"], where)
            walk_stmt(st["then"], where)
            walk_stmt(st["else"], where)
        elif kind == "case":
            if st["case_kind"] not in M.CASE_KINDS:
                bad("enum", f"{where}: case kind {st['case_kind']!r}")
            if st["expr"] is None:
                bad("control", f"{where}: case without selector")
            walk_expr(st["expr"], where)
            for it in st["items"]:
                if not isinstance(it, dict) or (not it.get("exprs") and (it.get("body") or {}).get("stmt") != "opaque"):
                    bad("control", f"{where}: case item without labels")
                    continue
                for e in it.get("exprs", []):
                    walk_expr(e, where)
                walk_stmt(it.get("body"), where)
            if st["default"] is not None:
                walk_stmt(st["default"].get("body"), where)
        elif kind == "block":
            for x in st["body"]:
                walk_stmt(x, where)
        elif kind == "loop":
            for i in st.get("init", []):
                if "declaration" in i:
                    register(i["declaration"], f"{where}: loop variable")
                    walk_tree(i["declaration"], where)
                    walk_expr(i.get("value"), where)
            walk_expr(st.get("cond"), where)
            walk_stmt(st["body"], where)
        elif kind == "timing":
            walk_stmt(st["body"], where)
        elif kind == "call":
            walk_expr(st["expr"], where)
        elif kind == "return":
            walk_expr(st["value"], where)
        elif kind == "declaration":
            register(st["declaration"], f"{where}: local {st['declaration'].get('name')}")
            check_width(st["declaration"], f"{where}: local {st['declaration'].get('name')}")
            walk_tree(st["declaration"], where)

    for section in _DECL_SECTIONS:
        for obj in doc[section]:
            walk_tree(obj, f"{section}:{obj.get('name')}")
    for td in doc["typedefs"]:
        walk_tree(td.get("members", []), f"typedef:{td.get('name')}")
    for sub in doc["subroutines"]:
        walk_tree(sub.get("ports", []), f"subroutine:{sub.get('name')}")
        for st in sub.get("body", []):
            walk_stmt(st, f"subroutine:{sub.get('name')}")
    for p in doc["processes"]:
        for ev in p.get("events", []):
            if ev.get("edge") not in M.EDGES:
                bad("enum", f"process {p.get('id')}: event edge {ev.get('edge')!r}")
            walk_expr(ev.get("expr"), f"process {p.get('id')}")
        for st in p.get("body", []):
            walk_stmt(st, f"process {p.get('id')}")
    for inst in doc["instances"]:
        walk_tree({k: v for k, v in inst.items() if k not in ("id", "loc")}, f"instance {inst.get('name')}")
    for g in doc["generates"]:
        walk_tree({k: v for k, v in g.items() if k not in ("id", "loc")}, f"generate {g.get('id')}")
    for a in doc["assignments"]:
        if isinstance(a.get("target"), dict) and a["target"].get("op") in _TARGET_OPS:
            walk_expr(a["target"], f"assignment {a.get('id')} target")
        walk_expr(a.get("value"), f"assignment {a.get('id')} value")

    for oid, n in ids.items():
        if n > 1:
            bad("duplicate_identity", f"identity {oid} used by {n} entities")
    ref_ids = Counter(r.get("id") for r in ref_nodes)
    for rid, n in ref_ids.items():
        if n > 1 or rid in ids or rid in statements:
            bad("duplicate_identity", f"reference identity {rid} duplicated")
    targets = set(objects)

    # ---------------------------------------------------------------- references
    for r in ref_nodes:
        kind, tgt = r.get("ref_kind"), r.get("target")
        if kind in _UNRESOLVED_KINDS:
            if tgt is not None:
                bad("broken_reference", f"{kind} reference {r.get('name')!r} carries a target")
            if kind == "external" and r.get("name") not in external_names:
                bad("broken_reference", f"external reference {r.get('name')!r} not declared in the unit")
        elif tgt is None:
            bad("broken_reference", f"{kind} reference {r.get('name')!r} has no defining entity")
        elif tgt not in targets:
            bad("broken_reference", f"reference {r.get('name')!r} -> {tgt} does not resolve")
    index = doc["references"]
    by_node = {r.get("id"): r for r in ref_nodes}
    seen = Counter(x.get("id") for x in index)
    for x in index:
        rid = x.get("id")
        node = by_node.get(rid)
        if seen[rid] > 1:
            bad("duplicate_identity", f"references: {rid} listed {seen[rid]} times")
        if node is None:
            bad("broken_reference", f"references: {rid} has no reference node")
            continue
        if x.get("symbol") != node.get("name") or x.get("target") != node.get("target") \
                or x.get("ref_kind") != node.get("ref_kind"):
            bad("broken_reference", f"references: {rid} disagrees with its reference node")
        if x.get("usage") not in M.USAGES:
            bad("enum", f"references: {rid} usage {x.get('usage')!r}")
        if x.get("source") not in targets and x.get("source") not in statements:
            bad("broken_reference", f"references: {rid} source {x.get('source')} does not exist")
        check_loc(x, f"references:{rid}")
    for rid in sorted(set(by_node) - set(seen), key=str):
        bad("broken_reference", f"reference {rid} missing from the reference index")

    # ---------------------------------------------------------------- assignments
    process_ids = {p.get("id") for p in doc["processes"]}
    sub_ids = {s_.get("id") for s_ in doc["subroutines"]}
    gen_ids = {g.get("id") for g in doc["generates"]}
    for a in doc["assignments"]:
        where = f"assignment {a.get('id')}"
        if a.get("kind") not in M.ASSIGN_KINDS:
            bad("enum", f"{where}: kind {a.get('kind')!r}")
        tgt = a.get("target")
        if not isinstance(tgt, dict) or tgt.get("op") not in _TARGET_OPS:
            bad("assignment", f"{where}: missing or invalid target {str(tgt)[:60]}")
            continue
        if not isinstance(a.get("operator"), str) or not a["operator"]:
            bad("assignment", f"{where}: missing operator")
        if a.get("value") is None and a.get("operator") not in ("++", "--"):
            bad("assignment", f"{where}: missing value expression")
        if a.get("kind") == "nonblocking" and a.get("operator") != "<=":
            bad("assignment", f"{where}: nonblocking assignment with operator {a.get('operator')!r}")
        if a.get("kind") == "continuous" and a.get("process") is not None:
            bad("assignment", f"{where}: continuous assignment inside a process")
        for key, pool in (("process", process_ids), ("subroutine", sub_ids), ("generate", gen_ids)):
            if a.get(key) is not None and a[key] not in pool:
                bad("broken_reference", f"{where}: {key} {a[key]} does not exist")
        for ref in a.get("writes", []) + a.get("reads", []):
            if ref not in targets:
                bad("broken_reference", f"{where}: symbol {ref} does not exist")
        for g in a.get("guards", []):
            if g.get("statement") not in statements:
                bad("broken_reference", f"{where}: guard statement {g.get('statement')} does not exist")
            if g.get("branch") not in M.BRANCHES:
                bad("enum", f"{where}: guard branch {g.get('branch')!r}")
    for p in doc["processes"]:
        where = f"process {p.get('id')}"
        if p.get("kind") not in M.PROCESS_KINDS or p.get("keyword") != p.get("kind"):
            bad("enum", f"{where}: kind {p.get('kind')!r} / keyword {p.get('keyword')!r}")
        if p.get("sensitivity") not in M.SENSITIVITY:
            bad("enum", f"{where}: sensitivity {p.get('sensitivity')!r}")
        for aid in p.get("assignments", []):
            if aid not in assignment_ids:
                bad("broken_reference", f"{where}: assignment {aid} does not exist")

    # ---------------------------------------------------------------- instances / generates
    for inst in doc["instances"]:
        where = f"instance {inst.get('name')}"
        tid = inst.get("target_module_id")
        if inst.get("resolved"):
            if not isinstance(tid, str) or not M.MODULE_ID_RE.fullmatch(tid):
                bad("broken_instance", f"{where}: resolved to invalid module id {tid!r}")
            elif known_module_ids is not None and tid not in known_module_ids:
                bad("broken_instance", f"{where}: module {tid} is not a canonical module")
        elif tid is not None:
            bad("broken_instance", f"{where}: unresolved instance carries a target {tid!r}")
        for c in inst.get("connections", []):
            if c.get("kind") not in M.CONNECTION_KINDS:
                bad("enum", f"{where}: connection kind {c.get('kind')!r}")
            if c.get("direction") not in M.DIRECTIONS:
                bad("direction", f"{where}: connection direction {c.get('direction')!r}")
            for ref in c.get("refs", []):
                if ref not in targets:
                    bad("broken_reference", f"{where}: symbol {ref} does not exist")
    for g in doc["generates"]:
        if g.get("kind") not in M.GENERATE_KINDS:
            bad("enum", f"generate {g.get('id')}: kind {g.get('kind')!r}")
        if g.get("representation") not in M.REPRESENTATION:
            bad("enum", f"generate {g.get('id')}: representation {g.get('representation')!r}")
        if g.get("parent") is not None and g["parent"] not in gen_ids:
            bad("broken_reference", f"generate {g.get('id')}: parent {g['parent']} does not exist")

    # ---------------------------------------------------------------- condition / case indexes
    ifs = {k for k, v in statements.items() if v["stmt"] == "if"}
    cases = {k for k, v in statements.items() if v["stmt"] == "case"}
    owners = process_ids | sub_ids
    for name, records, want in (("conditions", doc["conditions"], ifs), ("cases", doc["cases"], cases)):
        got = Counter(r.get("id") for r in records)
        for rid in sorted(set(want) ^ set(got), key=str):
            bad("control", f"{name}: index and statement trees disagree on {rid}")
        for r in records:
            if got[r.get("id")] > 1:
                bad("duplicate_identity", f"{name}: {r.get('id')} listed twice")
            if r.get("owner") not in owners:
                bad("broken_reference", f"{name}: {r.get('id')} owner {r.get('owner')} does not exist")
            check_loc(r, f"{name}:{r.get('id')}")
            refkeys = ("predicate_references",) if name == "conditions" else ("selector_references",)
            branch_ids = [r.get("then"), r.get("else")] if name == "conditions" else \
                [i.get("body") for i in r.get("items", [])] + [(r.get("default") or {}).get("body")]
            reflist = [x for k in refkeys for x in r.get(k, [])] + \
                [x for i in r.get("items", []) for x in i.get("label_references", [])]
            for x in reflist:
                if x not in by_node:
                    bad("broken_reference", f"{name}: {r.get('id')} reference {x} does not exist")
            for b in branch_ids:
                if b is not None and b not in statements and b not in assignment_ids:
                    bad("broken_reference", f"{name}: {r.get('id')} branch {b} does not exist")
            if name == "cases" and r.get("case_kind") not in M.CASE_KINDS:
                bad("enum", f"cases: {r.get('id')} case kind {r.get('case_kind')!r}")

    # ---------------------------------------------------------------- ordering
    for section in ("parameters", "signals", "typedefs", "subroutines", "assignments", "processes",
                    "instances", "generates", "conditions", "cases", "references", "unsupported"):
        items = doc[section]
        if items != sorted(items, key=M.loc_key):
            bad("ordering", f"{section} not in canonical (file, line, column, id) order")

    # ---------------------------------------------------------------- unsupported
    cov = doc["coverage"]
    if cov.get("members") != cov.get("represented", 0) + cov.get("opaque", 0):
        bad("silent_loss", f"coverage: {cov.get('members')} members != represented + opaque")
    listed = {u.get("id") for u in doc["unsupported"]}
    member_opaque = {u.get("id") for u in doc["unsupported"] if u.get("level") == "member"}
    if len(member_opaque) < cov.get("opaque", 0):
        bad("silent_loss", "opaque members not listed in unsupported")
    for oid in sorted((stmt_opaque | expr_opaque) - listed, key=str):
        bad("silent_loss", f"opaque node {oid} not listed in unsupported")
    if doc["extraction"] == "complete" and doc["unsupported"]:
        bad("silent_loss", "extraction marked complete but unsupported constructs exist")
    if doc["extraction"] == "partial" and not doc["unsupported"]:
        bad("silent_loss", "extraction marked partial without unsupported constructs")
    return problems


# -----------------------------------------------------------------------------
# corpus gate
# -----------------------------------------------------------------------------

def semantic_root(data_root) -> Path:
    return Path(os.path.abspath(data_root)) / M.OUTPUT_DIR


def corpus_sha256(data_root) -> str:
    """sha256 over the sorted (relative path, file sha256) pairs of the semantic tree."""
    import hashlib

    root = Path(os.path.abspath(data_root))
    sem = semantic_root(root)
    h = hashlib.sha256()
    for path in sorted(sem.rglob("*")) if sem.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / M.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def check(data_root) -> dict:
    """Validate every Semantic IR v2 document against the canonical module inventory."""
    from scripts.core.paths import ForgeDataPaths, find_absolute_paths, iter_module_yamls
    from scripts.core.provenance import module_id, sha256_file

    data = ForgeDataPaths.from_root(data_root)
    root = data.root
    sem = semantic_root(root)
    canonical = {(p.parent.parent.name, p.stem) for p in iter_module_yamls(data.normalized_ir)}
    known = {module_id(ip, m) for ip, m in canonical}
    problems = []
    totals = Counter()
    present = set()
    owners = {}                       # module identity -> document
    claims = {}                       # (ip, module) claimed by a document -> document
    folded = {}                       # case-folded output path -> document
    files = sorted(sem.rglob("*.json")) if sem.is_dir() else []
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(sem).parts
        if len(parts) != 2:
            problems.append(("inventory", f"{rel}: not <ip>/<module>.json"))
            continue
        key = (parts[0], path.stem)
        present.add(key)
        if rel.lower() in folded:
            problems.append(("duplicate_output_path", f"{rel}: same canonical output as {folded[rel.lower()]}"))
        folded.setdefault(rel.lower(), rel)
        if key not in canonical:
            problems.append(("inventory", f"{rel}: no canonical module {key[0]}/{key[1]}"))
            continue
        text = path.read_text(encoding="utf-8")
        try:
            doc = json.loads(text)
        except ValueError as exc:
            problems.append(("schema", f"{rel}: invalid JSON ({exc})"))
            continue
        if M.dumps(doc) != text:
            problems.append(("nondeterministic", f"{rel}: not in canonical serialisation"))
        if find_absolute_paths(text):
            problems.append(("absolute_path", f"{rel}: absolute path in document"))
        for code, msg in validate_module(doc, known):
            problems.append((code, f"{rel}: {msg}"))
        mod = doc.get("module", {})
        mid = mod.get("module_id")
        if mid in owners:
            problems.append(("duplicate_module_identity", f"{rel}: module identity {mid} also used by {owners[mid]}"))
        owners.setdefault(mid, rel)
        claim = (mod.get("ip"), mod.get("name"))
        if claim in claims:
            problems.append(("duplicate_output_path", f"{rel}: {claim[0]}/{claim[1]} already published as {claims[claim]}"))
        claims.setdefault(claim, rel)
        if mod.get("module_id") != module_id(*key) or mod.get("name") != key[1] or mod.get("ip") != key[0]:
            problems.append(("identity", f"{rel}: module identity does not match {key[0]}/{key[1]}"))
        src = (mod.get("source") or {})
        if src.get("path") and (root / src["path"]).is_file() and sha256_file(root / src["path"]) != src.get("sha256"):
            problems.append(("provenance", f"{rel}: source sha256 is not current"))
        totals["modules"] += 1
        totals[f"extraction_{doc.get('extraction')}"] += 1
        for k, v in (doc.get("counts") or {}).items():
            totals[k] += v
        for u in doc.get("unsupported", []):
            totals[f"unsupported:{u.get('construct')}"] += 1
        for p in doc.get("processes", []):
            totals[f"process:{p.get('kind')}:{p.get('sensitivity')}"] += 1
        for a in doc.get("assignments", []):
            totals[f"assignment:{a.get('kind')}"] += 1
        for c in doc.get("cases", []):
            totals[f"case:{c.get('case_kind')}{':' + c['qualifier'] if c.get('qualifier') else ''}"] += 1
        totals["conditions_with_else"] += sum(1 for c in doc.get("conditions", []) if c.get("else"))
        totals["cases_with_default"] += sum(1 for c in doc.get("cases", []) if c.get("default"))
    for key in sorted(canonical - present):
        problems.append(("inventory", f"missing Semantic IR v2 for {key[0]}/{key[1]}"))
    codes = Counter(code for code, _ in problems)
    report = {
        "schema": {"name": M.SCHEMA_NAME, "version": M.SCHEMA_VERSION},
        "canonical_modules": len(canonical),
        "documents": len(files),
        "corpus_sha256": corpus_sha256(root),
        "totals": dict(sorted(totals.items())),
        "problem_counts": dict(sorted(codes.items())),
        "problems": [f"[{c}] {m}" for c, m in problems[:200]],
        "status": "FAIL" if problems else "PASS",
    }
    return report


def format_report(report: dict) -> str:
    t = report["totals"]
    keys = ("modules", "extraction_complete", "extraction_partial", "parameters", "ports", "signals",
            "typedefs", "subroutines", "processes", "assignments", "conditions", "cases", "instances",
            "unresolved_instances", "generates", "statements", "expressions", "references",
            "resolved_references", "write_references", "external_references", "hierarchical_references",
            "unresolved_references", "external_declarations", "unsupported")
    lines = [f"Semantic IR v2 check: {report['status']} (schema {M.SCHEMA_NAME} v{M.SCHEMA_VERSION})",
             f"  {'canonical modules':24s}: {report['canonical_modules']}",
             f"  {'documents':24s}: {report['documents']}"]
    lines += [f"  {k.replace('_', ' '):24s}: {t.get(k, 0)}" for k in keys]
    lines += [f"  [FAIL] {p}" for p in report["problems"][:30]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-008 Semantic IR v2 validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate (default)")
    parser.add_argument("--json", help="also write the report JSON here")
    parser.add_argument("--write-report", action="store_true",
                        help=f"write <data-root>/{M.REPORT_PATH} (pipeline semantic gate)")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    report = check(args.data_root)
    print(format_report(report))
    if args.write_report:
        write_report(args.data_root, report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
