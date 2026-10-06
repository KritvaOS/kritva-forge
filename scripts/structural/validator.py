#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : Structural Analysis v1 schema, reference, provenance and consistency validation (KF-DQ-010)
#
# Component   : Kritva Forge
# Module      : structural
# Layer       : Structural Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural Analysis v1 validation (criteria sections 14, 15, 17, 19) - fail closed.

``validate_module(doc, sem, beh, sem_sha256, beh_sha256)`` returns
``[(code, message), ...]``; ``check(data_root)`` validates every document
under ``normalized/structural/v1`` against the canonical module inventory, the
current Semantic IR v2 and Behavioral Semantics v1 (re-analysis must
reproduce each document byte for byte) and the split manifest (leakage), and
is the ``make check-structural`` gate.

Codes:

========================  =====================================================
``schema``                malformed JSON / unsupported schema or version block
``required``              missing section or field
``enum``                  value outside a vocabulary
``identity``              malformed or non-derivable ``str1:`` / ``sem1:`` / ``beh1:`` / ``mod1:`` identity
``duplicate_identity``    one structural identity used twice
``duplicate_edge``        one relationship (dependency, driver, load, connection) recorded twice
``semantic_reference``    reference to a non-existent Semantic IR v2 object
``behavior_reference``    reference to a non-existent Behavioral Semantics v1 object
``driver_reference``      driver list / driver record mismatch or unknown driver
``load_reference``        load list / load record mismatch or unknown load
``broken_reference``      other reference to a non-existent structural object
``provenance``            missing location / anchor / input reference
``absolute_path``         absolute or machine-local path
``path_traversal``        ``.`` / ``..`` path segment
``read_write``            process read / write set inconsistent with loads / drivers / behavior
``role_conflict``         process role differs from Behavioral Semantics (never overridden)
``consistency``           relationship kind / context / boundary / count contradiction
``evidence``              classification without evidence
``naming``                classification supported by ``name_hint`` evidence only
``semantic_consistency``  document disagrees with its Semantic IR v2 input
``behavior_consistency``  document disagrees with its Behavioral Semantics v1 input
``ordering``              section or id list not in canonical order
``inventory``             document / canonical-module mismatch (corpus)
``semantic_input``        Semantic IR v2 input missing or unsupported (corpus)
``behavior_input``        Behavioral Semantics v1 input missing or unsupported (corpus)
``stale``                 document differs from a re-analysis of the current inputs
``nondeterministic``      bytes differ from the canonical serialisation
``leakage``               structural dataset dependency across splits (corpus)
========================  =====================================================
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

from scripts.structural import model as T

_ABS = re.compile(r"^(/|[A-Za-z]:[/\\]|\\\\|~)")
_VERSIONS = {"schema": T.SCHEMA_VERSION, "identity": T.IDENTITY_VERSION, "analyzer": T.ANALYZER_VERSION,
             "provenance": T.PROVENANCE_VERSION, "semantic_ir": T.SEMANTIC_IR_VERSION,
             "semantic_identity": T.SEMANTIC_IDENTITY_VERSION, "behavior": T.BEHAVIOR_VERSION,
             "behavior_identity": T.BEHAVIOR_IDENTITY_VERSION}

REQUIRED = {
    "signals": ("id", "signal", "name", "kind", "direction", "declaration", "width", "drivers", "loads",
                "driver_status", "driver_units", "multiple_drivers", "possible_drivers", "fan_in", "fan_out",
                "classes", "register", "loc"),
    "processes": ("id", "process", "behavior", "kind", "role", "confidence", "boundary", "reads", "writes",
                  "read_write", "assignments", "drivers", "predicates", "loc"),
    "assignments": ("id", "assignment", "process", "kind", "context", "boundary", "targets", "partial", "data",
                    "control", "guards", "order", "generate", "loc"),
    "predicates": ("id", "statement", "kind", "qualifier", "process", "references", "signals", "items", "default",
                   "targets", "parent", "depth", "role", "loc"),
    "drivers": ("id", "signal", "kind", "unit", "process", "role", "assignments", "connection", "references",
                "whole", "status", "loc"),
    "loads": ("id", "signal", "reference", "kind", "consumer", "process", "targets", "loc"),
    "dependencies": ("id", "source", "target", "kind", "context", "boundary", "via", "process", "assignments",
                     "references", "behavior", "direct", "partial", "status", "hold", "loc"),
    "registers": ("id", "register", "signal", "name", "process", "behavior_process", "boundary", "clock", "resets",
                  "enables", "holds", "hold", "update", "next_values", "priority", "state_candidate", "loc"),
    "multiple_drivers": ("id", "signal", "units", "kinds", "reasons", "status", "loc"),
    "cycles": ("id", "kind", "signals", "edges", "length", "status", "loc"),
    "cones": ("id", "signal", "direction", "signals", "registers", "inputs", "outputs", "processes", "assignments",
              "predicates", "instances", "edges", "depth", "cycles", "loc"),
    "instances": ("id", "instance", "name", "module", "parent", "child", "status", "reason", "parameters",
                  "connections", "generate", "loc"),
    "connections": ("id", "instance", "port", "position", "kind", "direction", "flow", "lvalue", "empty", "signals",
                    "index_signals", "references", "status", "loc"),
    "hierarchy": ("id", "relationship", "parent", "child", "child_module", "instance", "status", "cross_module", "loc"),
}
ENUMS = {
    ("signals", "driver_status"): T.DRIVER_STATUS,
    ("processes", "role"): T.ROLES, ("processes", "boundary"): T.BOUNDARIES,
    ("assignments", "context"): T.CONTEXTS, ("assignments", "boundary"): T.BOUNDARIES,
    ("predicates", "kind"): T.PREDICATE_KINDS, ("predicates", "role"): T.PREDICATE_ROLES,
    ("drivers", "kind"): T.DRIVER_KINDS, ("drivers", "status"): T.STATUS,
    ("loads", "kind"): T.LOAD_KINDS,
    ("dependencies", "kind"): T.DEP_KINDS, ("dependencies", "context"): T.CONTEXTS,
    ("dependencies", "boundary"): T.BOUNDARIES, ("dependencies", "status"): T.STATUS,
    ("registers", "boundary"): T.BOUNDARIES,
    ("multiple_drivers", "status"): T.STATUS, ("cycles", "status"): T.STATUS,
    ("cones", "direction"): T.CONE_DIRECTIONS,
    ("instances", "status"): T.INSTANCE_STATUS, ("hierarchy", "status"): T.INSTANCE_STATUS,
    ("connections", "direction"): T.DIRECTIONS, ("connections", "flow"): T.FLOWS, ("connections", "status"): T.STATUS,
}
# allowed contexts of each relationship kind
KIND_CONTEXTS = {
    "data": ("continuous_assignment", "procedural_assignment", "sequential_update", "initialization", "reset",
             "loop_control"),
    "control": ("condition", "case_expression", "case_item", "ternary_condition", "target_index"),
    "reset": ("reset",), "enable": ("enable",), "hold": ("hold",), "clock": ("clock_event",),
}


def _ids(node, out):
    """Every ``id`` value below ``node`` (Semantic IR / Behavioral identities)."""
    stack = [node]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            v = x.get("id")
            if isinstance(v, str):
                out.add(v)
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return out


def _loc_ok(loc) -> bool:
    return (isinstance(loc, dict) and isinstance(loc.get("file"), str) and loc["file"]
            and isinstance(loc.get("line"), int) and loc["line"] > 0 and isinstance(loc.get("column"), int))


def _path_problems(where, path, out):
    if not isinstance(path, str) or not path:
        out.append(("provenance", f"{where}: missing path"))
        return
    if _ABS.match(path):
        out.append(("absolute_path", f"{where}: absolute path {path!r}"))
    if any(seg in (".", "..") for seg in path.replace("\\", "/").split("/")):
        out.append(("path_traversal", f"{where}: path traversal in {path!r}"))


def expected_id(section, rec, inst_by_id):
    if section == "signals":
        return T.struct_id("signal", rec["signal"])
    if section == "processes":
        return T.struct_id("process", rec["process"])
    if section == "assignments":
        return T.struct_id("assignment", rec["assignment"])
    if section == "predicates":
        return T.struct_id("predicate", rec["statement"])
    if section == "drivers":
        return T.struct_id("driver", rec["unit"], rec["signal"])
    if section == "loads":
        return T.struct_id("load", rec["reference"] or rec["signal"], rec["kind"])
    if section == "dependencies":
        return T.struct_id("dependency", rec["via"], f"{rec['source']}>{rec['target']}:{rec['kind']}:{rec['context']}")
    if section == "registers":
        return T.struct_id("register", rec["register"])
    if section == "multiple_drivers":
        return T.struct_id("multiple_drivers", rec["signal"])
    if section == "cycles":
        sig = rec["signals"] or [""]
        return T.struct_id("cycle", sig[0], ",".join(rec["signals"]))
    if section == "cones":
        return T.struct_id("cone", rec["signal"], rec["direction"])
    if section in ("instances", "hierarchy"):
        anchor = rec["instance"] if section == "instances" else (inst_by_id.get(rec["instance"]) or {}).get("instance", "")
        return T.struct_id(section[:-1] if section == "instances" else "hierarchy", anchor)
    if section == "connections":
        anchor = (inst_by_id.get(rec["instance"]) or {}).get("instance", "")
        return T.struct_id("connection", anchor, f"{rec['position']}:{rec['port']}")
    return None


def validate_module(doc, sem=None, beh=None, semantic_sha256=None, behavior_sha256=None) -> list:
    from scripts.structural import analyzer as A

    p = []
    if not isinstance(doc, dict):
        return [("schema", "document is not a JSON object")]
    if doc.get("schema") != {"name": T.SCHEMA_NAME, "version": T.SCHEMA_VERSION}:
        return [("schema", f"unsupported structural schema {doc.get('schema')!r}")]
    if doc.get("versions") != _VERSIONS:
        p.append(("schema", f"unsupported versions block {doc.get('versions')!r}"))
        if (doc.get("versions") or {}).get("identity") != T.IDENTITY_VERSION:
            p.append(("identity", "unsupported structural identity version"))
    if (doc.get("generator") or {}).get("analyzer") != T.ANALYZER:
        p.append(("schema", "unsupported analyzer"))
    missing = [k for k in ("module", "counts", "notes", "fingerprint", "id") + T.SECTIONS if k not in doc]
    if missing:
        return p + [("required", f"missing {', '.join(missing)}")]
    for s in T.SECTIONS:
        if not isinstance(doc[s], list):
            return p + [("required", f"section {s} is not a list")]

    # ------------------------------------------------------------- module / provenance of inputs
    m = doc["module"]
    for key in ("ip", "name", "module_id", "semantic_id", "loc", "source", "semantic_ir", "behavior"):
        if key not in m:
            p.append(("provenance", f"module.{key} missing"))
    if p and any(c == "provenance" for c, _ in p):
        return p
    if not T.MODULE_ID_RE.fullmatch(str(m["module_id"])):
        p.append(("identity", f"module_id {m['module_id']!r}"))
    if not T.SEM_RE.fullmatch(str(m["semantic_id"])):
        p.append(("identity", f"module.semantic_id {m['semantic_id']!r}"))
    if not _loc_ok(m["loc"]):
        p.append(("provenance", "module.loc"))
    _path_problems("module.source", (m["source"] or {}).get("path"), p)
    for key, ver, idv in (("semantic_ir", T.SEMANTIC_IR_VERSION, T.SEMANTIC_IDENTITY_VERSION),
                          ("behavior", T.BEHAVIOR_VERSION, T.BEHAVIOR_IDENTITY_VERSION)):
        ref = m[key] or {}
        _path_problems(f"module.{key}", ref.get("path"), p)
        if not T.SHA_RE.fullmatch(str(ref.get("sha256"))):
            p.append(("provenance", f"module.{key}.sha256 missing or malformed"))
        if (ref.get("schema_version"), ref.get("identity_version")) != (ver, idv):
            p.append(("schema", f"module.{key}: unsupported input version {ref.get('schema_version')!r}"))
    if not T.ID_RE.fullmatch(str(doc["id"])) or not T.ID_RE.fullmatch(str(doc["fingerprint"])):
        p.append(("identity", "document id / fingerprint malformed"))

    # ------------------------------------------------------------- per record: required, enums, identity, loc
    inst_by_id = {r.get("id"): r for r in doc["instances"] if isinstance(r, dict)}
    seen = Counter()
    for s in T.SECTIONS:
        prev = None
        for rec in doc[s]:
            if not isinstance(rec, dict):
                p.append(("required", f"{s}: record is not an object"))
                continue
            miss = [f for f in REQUIRED[s] if f not in rec]
            if miss:
                p.append(("required", f"{s} {rec.get('id')}: missing {', '.join(miss)}"))
                continue
            rid = rec["id"]
            seen[rid] += 1
            if not T.ID_RE.fullmatch(str(rid)):
                p.append(("identity", f"{s}: malformed identity {rid!r}"))
            elif expected_id(s, rec, inst_by_id) != rid:
                p.append(("identity", f"{s} {rid}: identity does not derive from its anchor"))
            if prev is not None and str(rid) <= prev:
                p.append(("ordering", f"{s}: {rid} out of canonical (identity) order"))
            prev = str(rid)
            for (sec, field), allowed in ENUMS.items():
                if sec == s and rec[field] not in allowed:
                    p.append(("enum", f"{s} {rid}: {field}={rec[field]!r}"))
            if not _loc_ok(rec["loc"]):
                p.append(("provenance", f"{s} {rid}: missing or invalid location"))
            else:
                _path_problems(f"{s} {rid}.loc", rec["loc"]["file"], p)
            for f in T.SORTED_LISTS:
                v = rec.get(f)
                if isinstance(v, list) and all(isinstance(x, str) for x in v) and v != sorted(v):
                    p.append(("ordering", f"{s} {rid}: {f} not sorted"))
    for rid, n in seen.items():
        if n > 1:
            p.append(("duplicate_identity", f"{rid} used {n} times"))
    if any(c in ("required", "schema") for c, _ in p):
        return p

    sig = {r["signal"]: r for r in doc["signals"]}
    drv = {r["id"]: r for r in doc["drivers"]}
    lod = {r["id"]: r for r in doc["loads"]}
    dep = {r["id"]: r for r in doc["dependencies"]}
    prc = {r["process"]: r for r in doc["processes"]}
    reg = {r["id"]: r for r in doc["registers"]}
    conn = {r["id"]: r for r in doc["connections"]}
    cyc = {r["id"]: r for r in doc["cycles"]}
    pred = {r["id"]: r for r in doc["predicates"]}

    # ------------------------------------------------------------- duplicate relationships
    for name, key in (("dependencies", lambda d: (d["source"], d["target"], d["kind"], d["context"], d["via"])),
                      ("drivers", lambda d: (d["signal"], d["unit"])),
                      ("loads", lambda d: (d["reference"] or d["signal"], d["kind"])),
                      ("connections", lambda d: (d["instance"], d["position"], d["port"]))):
        for k, n in Counter(key(r) for r in doc[name]).items():
            if n > 1:
                p.append(("duplicate_edge", f"{name}: relationship {k} recorded {n} times"))

    # ------------------------------------------------------------- drivers / loads cross references
    for s in doc["signals"]:
        for d in s["drivers"]:
            if d not in drv or drv[d]["signal"] != s["signal"]:
                p.append(("driver_reference", f"signal {s['name']}: driver {d} unknown or for another signal"))
        for d in s["loads"]:
            if d not in lod or lod[d]["signal"] != s["signal"]:
                p.append(("load_reference", f"signal {s['name']}: load {d} unknown or for another signal"))
        if s["register"] is not None and s["register"] not in reg:
            p.append(("broken_reference", f"signal {s['name']}: register {s['register']} unknown"))
        for c in s["classes"]:
            if c.get("class") not in T.CLASSES or c.get("status") not in T.STATUS:
                p.append(("enum", f"signal {s['name']}: class {c.get('class')!r}/{c.get('status')!r}"))
                continue
            ev = c.get("evidence") or []
            if not ev or any(e.get("code") not in T.EVIDENCE for e in ev):
                p.append(("evidence", f"signal {s['name']}: class {c['class']} without valid evidence"))
            elif c["class"] != "unknown" and {e["code"] for e in ev} == {"name_hint"}:
                p.append(("naming", f"signal {s['name']}: class {c['class']} supported by its name only"))
    for d in doc["drivers"]:
        if d["signal"] not in sig or d["id"] not in sig[d["signal"]]["drivers"]:
            p.append(("driver_reference", f"driver {d['id']}: signal {d['signal']} does not list it"))
        if d["connection"] is not None and d["connection"] not in conn:
            p.append(("driver_reference", f"driver {d['id']}: connection {d['connection']} unknown"))
        if not d["assignments"] and d["connection"] is None and d["kind"] != "module_input":
            p.append(("provenance", f"driver {d['id']}: no originating assignment or connection"))
    for ld in doc["loads"]:
        if ld["signal"] not in sig or ld["id"] not in sig[ld["signal"]]["loads"]:
            p.append(("load_reference", f"load {ld['id']}: signal {ld['signal']} does not list it"))
        if ld["reference"] is None and ld["kind"] != "module_output":
            p.append(("provenance", f"load {ld['id']}: no originating reference"))

    # ------------------------------------------------------------- processes: read / write sets
    rd, wr, pd = defaultdict(set), defaultdict(set), defaultdict(set)
    for ld in doc["loads"]:
        if ld["process"] is not None and ld["kind"] != "module_output":
            rd[ld["process"]].add(ld["signal"])
    for d in doc["drivers"]:
        if d["process"] is not None:
            wr[d["process"]].add(d["signal"])
            pd[d["process"]].add(d["id"])
    for pr in doc["processes"]:
        pid = pr["process"]
        if set(pr["reads"]) != rd[pid]:
            p.append(("read_write", f"process {pid}: read set differs from its loads"))
        if set(pr["writes"]) != wr[pid]:
            p.append(("read_write", f"process {pid}: write set differs from its drivers"))
        if set(pr["drivers"]) != pd[pid]:
            p.append(("driver_reference", f"process {pid}: driver list differs from its drivers"))
        both = sorted(set(pr["reads"]) & set(pr["writes"]))
        if [x.get("signal") for x in pr["read_write"]] != both or any(x.get("order") not in T.ORDER for x in pr["read_write"]):
            p.append(("read_write", f"process {pid}: read/write ordering list inconsistent"))
        if pr["boundary"] != {"sequential": "sequential", "combinational": "combinational", "latch": "latch",
                              "initialization": "initialization"}.get(pr["role"], "unknown"):
            p.append(("consistency", f"process {pid}: boundary {pr['boundary']} contradicts role {pr['role']}"))
        for q in pr["predicates"]:
            if q not in pred:
                p.append(("broken_reference", f"process {pid}: predicate {q} unknown"))

    # ------------------------------------------------------------- dependencies
    for d in doc["dependencies"]:
        for end in ("source", "target"):
            if d[end] not in sig:
                p.append(("broken_reference", f"dependency {d['id']}: {end} {d[end]} is not a module signal"))
        if d["context"] not in KIND_CONTEXTS.get(d["kind"], ()):
            p.append(("consistency", f"dependency {d['id']}: kind {d['kind']} with context {d['context']}"))
        if d["process"] is not None and d["process"] in prc and prc[d["process"]]["boundary"] != d["boundary"]:
            p.append(("consistency", f"dependency {d['id']}: boundary {d['boundary']} differs from its process"))
        if d["kind"] == "hold" and (d["source"] != d["target"] or d["hold"] not in T.HOLD_KINDS):
            p.append(("consistency", f"dependency {d['id']}: hold relationship is not a register self-hold"))
        if not (d["assignments"] or d["references"] or d["behavior"]):
            p.append(("provenance", f"dependency {d['id']}: no originating Semantic IR / behavioral object"))

    # ------------------------------------------------------------- other structural references
    for r in doc["multiple_drivers"]:
        if r["signal"] not in sig or any(u not in drv for u in r["units"]) or len(r["units"]) < 2:
            p.append(("driver_reference", f"multiple_drivers {r['id']}: unknown signal / driver units"))
    for c in doc["cycles"]:
        if any(e not in dep for e in c["edges"]) or any(s not in sig for s in c["signals"]) or c["length"] != len(c["signals"]):
            p.append(("broken_reference", f"cycle {c['id']}: unknown edges / signals"))
    for c in doc["cones"]:
        if c["signal"] not in sig or any(s not in sig for s in c["signals"] + c["registers"]) \
                or any(x not in cyc for x in c["cycles"]):
            p.append(("broken_reference", f"cone {c['id']}: unknown signals / cycles"))
    for i in doc["instances"]:
        if any(c not in conn or conn[c]["instance"] != i["id"] for c in i["connections"]):
            p.append(("broken_reference", f"instance {i['id']}: connection list mismatch"))
        if (i["status"] == "resolved") != (i["child"] is not None):
            p.append(("consistency", f"instance {i['id']}: status {i['status']} with child {i['child']!r}"))
        if i["parent"] != m["module_id"]:
            p.append(("consistency", f"instance {i['id']}: parent is not this module"))
    for c in doc["connections"]:
        if c["instance"] not in inst_by_id:
            p.append(("broken_reference", f"connection {c['id']}: instance unknown"))
    for h in doc["hierarchy"]:
        i = inst_by_id.get(h["instance"])
        if i is None or h["child"] != (i["child"] or {}).get("module_id") or h["status"] != i["status"] \
                or h["parent"] != m["module_id"]:
            p.append(("broken_reference", f"hierarchy {h['id']}: inconsistent with its instance"))

    # ------------------------------------------------------------- counts / document identity
    try:
        if doc["counts"] != A.counts(doc):
            p.append(("consistency", "counts do not match the document"))
        if doc["fingerprint"] != A.fingerprint(doc):
            p.append(("identity", "fingerprint does not match the document"))
    except (KeyError, TypeError) as exc:
        p.append(("required", f"cannot recompute counts / fingerprint ({exc})"))
    if T.document_id(doc) != doc["id"]:
        p.append(("identity", "document identity is not the content hash of the document"))

    # ------------------------------------------------------------- Semantic IR
    if sem is not None:
        sm = sem.get("module") or {}
        if (sm.get("ip"), sm.get("name"), sm.get("module_id"), sm.get("id")) != (m["ip"], m["name"], m["module_id"], m["semantic_id"]):
            p.append(("semantic_consistency", "module does not match its Semantic IR"))
        if (sm.get("source") or {}) != m["source"]:
            p.append(("semantic_consistency", "source provenance differs from Semantic IR"))
        if semantic_sha256 is not None and m["semantic_ir"]["sha256"] != semantic_sha256:
            p.append(("semantic_consistency", "derived from a different Semantic IR revision (sha256)"))
        sids = _ids(sem, set())
        decl = {d["id"] for d in sem.get("ports", []) + sem.get("signals", [])}
        if set(sig) != decl:
            p.append(("semantic_consistency", "signal set differs from Semantic IR ports + signals"))
        if set(prc) != {x["id"] for x in sem.get("processes", [])}:
            p.append(("semantic_consistency", "process set differs from Semantic IR"))
        if {i["instance"] for i in doc["instances"]} != {x["id"] for x in sem.get("instances", [])}:
            p.append(("semantic_consistency", "instance set differs from Semantic IR"))

        def need(where, *vals):
            for v in vals:
                if v is None:
                    continue
                if isinstance(v, list):
                    need(where, *v)
                elif isinstance(v, str) and v.startswith("sem1:") and v not in sids:
                    p.append(("semantic_reference", f"{where}: {v} not in Semantic IR"))
                    return

        for s in doc["signals"]:
            need(f"signal {s['id']}", s["signal"])
        for r in doc["processes"]:
            need(f"process {r['id']}", r["process"], r["assignments"])
        for r in doc["assignments"]:
            need(f"assignment {r['id']}", r["assignment"], r["process"], r["targets"], r["data"], r["control"],
                 [g.get("statement") for g in r["guards"]])
        for r in doc["predicates"]:
            need(f"predicate {r['id']}", r["statement"], r["process"], r["references"], r["signals"], r["targets"])
        for r in doc["drivers"]:
            need(f"driver {r['id']}", r["signal"], r["unit"], r["process"], r["assignments"], r["references"])
        for r in doc["loads"]:
            need(f"load {r['id']}", r["signal"], r["reference"], r["consumer"], r["process"], r["targets"])
        for r in doc["dependencies"]:
            need(f"dependency {r['id']}", r["source"], r["target"], r["via"], r["process"], r["assignments"], r["references"])
        for r in doc["registers"]:
            need(f"register {r['id']}", r["signal"], r["process"])
        for r in doc["instances"]:
            need(f"instance {r['id']}", r["instance"], r["generate"])
        for r in doc["connections"]:
            need(f"connection {r['id']}", r["signals"], r["index_signals"], r["references"])

    # ------------------------------------------------------------- Behavioral Semantics
    if beh is not None:
        if behavior_sha256 is not None and m["behavior"]["sha256"] != behavior_sha256:
            p.append(("behavior_consistency", "derived from a different Behavioral Semantics revision (sha256)"))
        if (beh.get("module") or {}).get("module_id") != m["module_id"]:
            p.append(("behavior_consistency", "module does not match its Behavioral Semantics"))
        bids = _ids(beh, set())
        bproc = {x["process"]: x for x in beh.get("processes", [])}
        for pr in doc["processes"]:
            b = bproc.get(pr["process"])
            if b is None or pr["behavior"] != b["id"]:
                p.append(("behavior_reference", f"process {pr['id']}: behavioral process {pr['behavior']} unknown"))
                continue
            if pr["role"] != b["role"] or pr["confidence"] != b["confidence"]:
                p.append(("role_conflict", f"process {pr['id']}: role {pr['role']} overrides behavioral role {b['role']}"))
            if pr["reads"] != b["reads"] or pr["writes"] != b["writes"]:
                p.append(("read_write", f"process {pr['id']}: read/write sets differ from Behavioral Semantics"))
        if {r["register"] for r in doc["registers"]} != {x["id"] for x in beh.get("registers", [])}:
            p.append(("behavior_consistency", "register set differs from Behavioral Semantics"))

        def bneed(where, *vals):
            for v in vals:
                if isinstance(v, list):
                    bneed(where, *v)
                elif isinstance(v, str) and v.startswith("beh1:") and v not in bids:
                    p.append(("behavior_reference", f"{where}: {v} not in Behavioral Semantics"))
                    return

        for r in doc["registers"]:
            bneed(f"register {r['id']}", r["register"], r["behavior_process"], (r["clock"] or {}).get("clock"),
                  [x["reset"] for x in r["resets"]], [x["enable"] for x in r["enables"]],
                  [x["hold"] for x in r["holds"]], [x["next_value"] for x in r["next_values"]], r["state_candidate"])
        for r in doc["dependencies"]:
            bneed(f"dependency {r['id']}", r["behavior"])
        for s in doc["signals"]:
            bneed(f"signal {s['id']}", [e.get("refs", []) for c in s["classes"] for e in c.get("evidence", [])])
    return p


# =============================================================================
# corpus
# =============================================================================

def structural_root(root: Path) -> Path:
    return root / T.OUTPUT_DIR


def corpus_sha256(data_root) -> str:
    root = Path(os.path.abspath(data_root))
    h = hashlib.sha256()
    base = structural_root(root)
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


SPLIT_MANIFEST = "splits/split_manifest.json"


def leakage(data_root, fingerprints: dict) -> dict:
    """KF-DQ-004 integration (AC-052): structural fingerprints vs. splits.

    ``fingerprints`` maps (ip, module) -> fingerprint.  Modules sharing a
    fingerprint across splits are reported (soft: no current dataset record
    consumes structural information); a dataset record that declares a
    structural dependency on such a module is a hard ``leakage`` failure.
    """
    from scripts.core.provenance import iter_dataset_records

    root = Path(os.path.abspath(data_root))
    path = root / SPLIT_MANIFEST
    if not path.is_file():
        return {"status": "SKIPPED", "reason": f"{SPLIT_MANIFEST} not present", "problems": []}
    raw = path.read_bytes()
    sm = json.loads(raw)
    split = defaultdict(set)
    for s in ("train", "validation", "test"):
        for r in sm.get(s, []):
            split[(r["ip"], r["module"])].add(s)
    groups = defaultdict(list)
    for key, fp in sorted(fingerprints.items()):
        groups[fp].append(key)
    cross = []
    for fp, mods in sorted(groups.items()):
        splits = sorted({s for k in mods for s in split.get(k, ())})
        if len(splits) > 1:
            cross.append({"fingerprint": fp, "modules": [f"{ip}/{m}" for ip, m in mods], "splits": splits})
    crossing = {m for c in cross for m in c["modules"]}
    dependent, problems = 0, []
    for sp, _, rec in iter_dataset_records(root):
        ref = (rec.get("provenance") or {}).get("structural")
        if ref is None:
            continue
        dependent += 1
        key = f"{rec.get('ip')}/{rec.get('module')}"
        if key in crossing:
            problems.append(f"record {(rec.get('provenance') or {}).get('record_id')} ({sp}) depends on structural "
                            f"data of {key}, whose structure also occurs in another split")
    return {
        "status": "FAIL" if problems else "PASS",
        "split_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprints": len(groups),
        "shared_fingerprints": sum(1 for v in groups.values() if len(v) > 1),
        "cross_split_fingerprints": cross,
        "structural_dependent_records": dependent,
        "problems": problems,
    }


def check(data_root, with_leakage: bool = True) -> dict:
    from scripts.core.paths import find_absolute_paths
    from scripts.core.provenance import module_id
    from scripts.structural import analyzer as A

    root = Path(os.path.abspath(data_root))
    base = structural_root(root)
    canonical = set(A.canonical_modules(root))
    inv = A.inventory(root)
    problems, totals, present = [], Counter(), set()
    prov = Counter()
    fingerprints = {}
    files = sorted(base.rglob("*.json")) if base.is_dir() else []
    others = sorted(p for p in base.rglob("*") if p.is_file() and p.suffix != ".json") if base.is_dir() else []
    for p in others:
        problems.append(("inventory", f"{p.relative_to(root).as_posix()}: not <ip>/<module>.json"))
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(base).parts
        if len(parts) != 2:
            problems.append(("inventory", f"{rel}: not <ip>/<module>.json"))
            continue
        key = (parts[0], path.stem)
        present.add(key)
        if key not in canonical:
            problems.append(("inventory", f"{rel}: no canonical module {key[0]}/{key[1]}"))
            continue
        text = path.read_text(encoding="utf-8")
        try:
            doc = json.loads(text)
        except ValueError as exc:
            problems.append(("schema", f"{rel}: invalid JSON ({exc})"))
            continue
        if T.dumps(doc) != text:
            problems.append(("nondeterministic", f"{rel}: not in canonical serialisation"))
        if find_absolute_paths(text):
            problems.append(("absolute_path", f"{rel}: absolute path in document"))
        try:
            sem, srel, ssha, beh, brel, bsha = A.load_inputs(root, *key)
        except A.AnalysisError as exc:
            problems.append(("behavior_input" if "Behavioral" in str(exc) else "semantic_input", f"{rel}: {exc}"))
            continue
        m = doc.get("module") if isinstance(doc, dict) else None
        if isinstance(m, dict):
            if (m.get("semantic_ir") or {}).get("path") != srel:
                problems.append(("semantic_consistency", f"{rel}: Semantic IR path is not {srel}"))
            if (m.get("behavior") or {}).get("path") != brel:
                problems.append(("behavior_consistency", f"{rel}: Behavioral Semantics path is not {brel}"))
            if m.get("module_id") != module_id(*key):
                problems.append(("identity", f"{rel}: module identity does not match {key[0]}/{key[1]}"))
        found = validate_module(doc, sem, beh, ssha, bsha)
        for code, msg in found:
            problems.append((code, f"{rel}: {msg}"))
        try:
            fresh = T.dumps(A.analyze(sem, srel, ssha, beh, brel, bsha, inv))
        except A.AnalysisError as exc:
            problems.append(("stale", f"{rel}: inputs no longer analysable ({exc})"))
            continue
        if fresh != text:
            problems.append(("stale", f"{rel}: differs from a re-analysis of the current Semantic IR / Behavioral Semantics"))
        if not isinstance(doc, dict) or "counts" not in doc:
            continue
        totals["modules"] += 1
        totals["ips"] = len({k[0] for k in present})
        for k, v in (doc.get("counts") or {}).items():
            totals[k] += v
        for d in doc.get("dependencies", []):
            totals[f"dependency:{d.get('kind')}:{d.get('boundary')}"] += 1
        for d in doc.get("drivers", []):
            totals[f"driver:{d.get('kind')}"] += 1
        for d in doc.get("loads", []):
            totals[f"load:{d.get('kind')}"] += 1
        objects = doc["counts"].get("objects", 0)
        bad_prov = sum(1 for c, _ in found if c in ("provenance", "absolute_path", "path_traversal"))
        bad_ref = sum(1 for c, _ in found if c.endswith("_reference"))
        prov["objects"] += objects
        prov["missing"] += bad_prov
        prov["invalid_references"] += bad_ref
        prov["valid"] += max(0, objects - bad_prov - bad_ref)
        fingerprints[key] = doc.get("fingerprint")
    for key in sorted(canonical - present):
        problems.append(("inventory", f"missing Structural Analysis v1 for {key[0]}/{key[1]}"))
    leak = {"status": "SKIPPED", "reason": "not requested", "problems": []}
    if with_leakage:
        leak = leakage(root, fingerprints)
        problems += [("leakage", x) for x in leak["problems"]]
    codes = Counter(c for c, _ in problems)
    coverage = (prov["valid"] / prov["objects"]) if prov["objects"] else 0.0
    return {
        "schema": {"name": T.SCHEMA_NAME, "version": T.SCHEMA_VERSION},
        "canonical_modules": len(canonical),
        "documents": len(files),
        "corpus_sha256": corpus_sha256(root),
        "totals": dict(sorted(totals.items())),
        "provenance": {"objects": prov["objects"], "valid": prov["valid"], "missing": prov["missing"],
                       "invalid_references": prov["invalid_references"], "coverage": round(coverage, 6)},
        "leakage": leak,
        "problem_counts": dict(sorted(codes.items())),
        "problems": [f"[{c}] {m}" for c, m in problems[:200]],
        "status": "FAIL" if problems else "PASS",
    }


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / T.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_report(report: dict) -> str:
    t = report["totals"]
    keys = ["ips", "modules", "processes", "signals", "dependencies", "dependencies_data", "dependencies_control",
            "dependencies_reset", "dependencies_enable", "dependencies_hold", "dependencies_clock",
            "sequential_boundaries", "drivers", "loads", "multiple_drivers", "signals_undriven", "signals_unknown",
            "registers", "predicates", "instances", "connections", "unresolved_instances", "unknown_connections",
            "cycles", "cones"]
    pv = report["provenance"]
    lk = report["leakage"]
    lines = [f"Structural Analysis v1 check: {report['status']} (schema {T.SCHEMA_NAME} v{T.SCHEMA_VERSION})",
             f"  {'canonical modules':24s}: {report['canonical_modules']}",
             f"  {'documents':24s}: {report['documents']}"]
    lines += [f"  {k.replace('_', ' '):24s}: {t.get(k, 0)}" for k in keys]
    lines.append(f"  {'provenance coverage':24s}: {pv['valid']}/{pv['objects']} valid, {pv['missing']} missing, "
                 f"{pv['invalid_references']} invalid references")
    if lk.get("status") == "SKIPPED":
        lines.append(f"  {'leakage':24s}: SKIPPED ({lk.get('reason')})")
    else:
        lines.append(f"  {'leakage':24s}: {lk['status']} ({lk['structural_dependent_records']} structural-dependent "
                     f"records; {len(lk['cross_split_fingerprints'])} shared structures span splits)")
    lines += [f"  [FAIL] {x}" for x in report["problems"][:30]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-010 Structural Analysis v1 validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate (default)")
    parser.add_argument("--json", help="also write the report JSON here")
    parser.add_argument("--write-report", action="store_true", help=f"write <data-root>/{T.REPORT_PATH}")
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
