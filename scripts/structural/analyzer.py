#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : analyzer.py
# Description : Semantic IR v2 + Behavioral Semantics v1 to Structural Analysis v1 (KF-DQ-010)
#
# Component   : Kritva Forge
# Module      : structural
# Layer       : Structural Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural hardware analysis from Semantic IR v2 and Behavioral Semantics v1.

``analyze(sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, inventory)`` builds the
structural document of one module; ``write_all(data_root)`` does it for every
canonical module.  Only persisted JSON is read: no RTL parsing, no parser
objects.  Behavioral classifications (process roles, clocks, resets,
registers, enables, holds) are consumed as they are - never re-derived or
overridden.

Relationships (criteria sections 6-13):

* drivers / loads - one driver per (signal, driver unit: process, continuous
  assignment, instance connection or module input), one load per Semantic IR
  read/connect reference (plus module outputs);
* dependencies ``source -> target`` with kind (data / control / reset /
  enable / hold / clock), context, boundary (combinational / sequential /
  latch / initialization / unknown) and the anchoring Semantic IR construct;
* predicates (if / case with nesting), registers (next value, clock, resets,
  enables, holds, priority), multiple drivers, combinational cycles
  (Tarjan SCC over combinational edges), fan-in / fan-out counts and cones;
* instances, port connections (with flow direction) and hierarchy edges; a
  child without canonical IR stays ``unresolved`` (never fabricated).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from scripts.structural import model as T
from scripts.structural import query as Q

_SIGNAL_KINDS = ("port", "signal")
_LVALUE_OPS = ("ref", "concat", "index", "part_select", "member")
_BOUNDARY = {"sequential": "sequential", "combinational": "combinational", "latch": "latch",
             "initialization": "initialization", "generic": "unknown", "unknown": "unknown",
             "ambiguous": "unknown"}
_FLOW = {"input": "parent_to_child", "output": "child_to_parent", "inout": "bidirectional", "unknown": "unknown"}
_EVIDENCE_REFS = 8                      # anchors listed per evidence entry (the full count is kept)


class AnalysisError(RuntimeError):
    """Semantic IR / Behavioral Semantics input missing, unsupported or inconsistent (fail closed)."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _children(e):
    for k, v in e.items():
        if k == "loc":
            continue
        if isinstance(v, dict) and "op" in v:
            yield k, v
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict) and "op" in x:
                    yield k, x


def expr_roles(e, role: str, out: dict) -> dict:
    """Map every reference id below ``e`` to its structural role.

    ``role`` is ``write`` (assignment target), ``value`` (assignment value) or
    ``conn`` (instance connection).  Select expressions of a target or
    connection become ``target_index`` / ``index``; ternary conditions of a
    value become ``ternary_condition``.
    """
    stack = [(e, role)]
    while stack:
        x, r = stack.pop()
        if not isinstance(x, dict):
            continue
        op = x.get("op")
        if op == "ref":
            out[x["id"]] = r
            continue
        for key, child in _children(x):
            cr = r
            if op == "ternary" and key == "cond" and r == "value":
                cr = "ternary_condition"
            elif op in ("index", "part_select") and key != "base" and r in ("write", "conn", "conn_index"):
                cr = "target_index" if r == "write" else "conn_index"
            stack.append((child, cr))
    return out


def whole_write(a: dict, target: str) -> bool:
    t = a.get("target") or {}
    if t.get("op") == "ref":
        return t.get("target") == target
    if t.get("op") == "concat":
        return any(i.get("op") == "ref" and i.get("target") == target for i in t.get("items", []))
    return False


_COUNT_ONLY = ("data_source", "has_driver", "has_load", "instance_connection", "event_reference")


def _ev(code: str, refs=(), count=None) -> dict:
    """Evidence entry; bulky usage evidence keeps only its count (the signal lists its drivers / loads)."""
    assert code in T.EVIDENCE, code
    refs = sorted({r for r in refs if r})
    n = len(refs) if count is None else count
    return {"code": code, "count": n, "refs": [] if code in _COUNT_ONLY else refs[:_EVIDENCE_REFS]}


def _merge_loc(a, b):
    return a if b is None else (b if a is None else min(a, b, key=_lk))


def _lk(loc):
    return (str(loc.get("file", "")), int(loc.get("line", 0) or 0), int(loc.get("column", 0) or 0))


# =============================================================================
# input indexes
# =============================================================================

class _Inputs:
    def __init__(self, sem: dict, beh: dict, sem_sha: str):
        if not isinstance(sem, dict) or sem.get("schema") != {"name": "kritva-forge-semantic-ir",
                                                               "version": T.SEMANTIC_IR_VERSION}:
            raise AnalysisError(f"unsupported Semantic IR schema {sem.get('schema') if isinstance(sem, dict) else sem!r}")
        if (sem.get("versions") or {}).get("identity") != T.SEMANTIC_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Semantic IR identity version {(sem.get('versions') or {}).get('identity')!r}")
        if not isinstance(beh, dict) or beh.get("schema") != {"name": "kritva-forge-behavioral-semantics",
                                                               "version": T.BEHAVIOR_VERSION}:
            raise AnalysisError(f"unsupported Behavioral Semantics schema {beh.get('schema') if isinstance(beh, dict) else beh!r}")
        if (beh.get("versions") or {}).get("identity") != T.BEHAVIOR_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Behavioral Semantics identity version {(beh.get('versions') or {}).get('identity')!r}")
        bm, sm = beh.get("module") or {}, sem.get("module") or {}
        if (bm.get("semantic_ir") or {}).get("sha256") != sem_sha:
            raise AnalysisError("Behavioral Semantics was derived from a different Semantic IR revision")
        if bm.get("module_id") != sm.get("module_id") or bm.get("semantic_id") != sm.get("id"):
            raise AnalysisError("Behavioral Semantics describes a different module")
        self.sem, self.beh = sem, beh
        self.decl = {d["id"]: d for d in sem["ports"] + sem["signals"]}
        self.ports = {p["id"]: p for p in sem["ports"]}
        self.assign = {a["id"]: a for a in sem["assignments"]}
        self.refs = {r["id"]: r for r in sem["references"]}
        self.cond = {c["id"]: c for c in sem["conditions"]}
        self.case = {c["id"]: c for c in sem["cases"]}
        self.inst = {i["id"]: i for i in sem["instances"]}
        self.subroutines = {s["id"] for s in sem.get("subroutines", [])}
        self.subroutine_stmts = set()                # statements inside function / task bodies
        stack = [s.get("body") for s in sem.get("subroutines", [])]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "stmt" in node and isinstance(node.get("id"), str):
                    self.subroutine_stmts.add(node["id"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        self.proc = {p["id"]: p for p in sem["processes"]}
        # statements: owner process, parent guard, depth, process body order of assignments
        self.stmt, self.stmt_owner, self.stmt_parent, self.stmt_depth = {}, {}, {}, {}
        self.order = {}                              # assignment id -> position in its process body
        self.loop_assign = set()                     # for-loop init / step assignments (loop control)
        for p in sem["processes"]:
            n = [0]
            for st in p["body"]:
                self._walk(st, p["id"], None, 0, n)
        # behavior
        self.bproc = {p["process"]: p for p in beh["processes"]}
        self.bclock = {c["id"]: c for c in beh["clocks"]}
        self.breset = {r["id"]: r for r in beh["resets"]}
        self.benable = {e["id"]: e for e in beh["enables"]}
        self.bhold = {h["id"]: h for h in beh["holds"]}
        self.bnext = {n["id"]: n for n in beh["next_values"]}
        self.breg = {r["id"]: r for r in beh["registers"]}
        self.state_cand = {c["register"]: c["id"] for c in beh["candidates"] if c["kind"] == "state_candidate"}
        self.reg_by = {(r["process"], r["signal"]): r for r in beh["registers"]}
        self.bproc_by_id = {p["id"]: p for p in beh["processes"]}
        # leaf kind of each (assignment, register signal) from register priority leaves
        self.leaf = {}
        for r in beh["registers"]:
            for x in r["priority"]:
                if x.get("assignment"):
                    self.leaf[(x["assignment"], r["signal"])] = x["kind"]
        # reset / enable predicate roles, keyed by (statement, register signal)
        self.reset_of = defaultdict(list)            # condition -> [reset records]
        for r in beh["resets"]:
            if r.get("condition"):
                self.reset_of[r["condition"]].append(r)
        self.enable_of = {}                          # (condition, signal) -> enable record
        for e in beh["enables"]:
            reg = self.breg.get(e["register"])
            if reg:
                self.enable_of[(e["condition"], reg["signal"])] = e

    def _walk(self, st, pid, parent, depth, n):
        if not isinstance(st, dict) or "stmt" not in st:
            return
        if st["stmt"] == "assign":
            self.order[st["assignment"]] = n[0]
            n[0] += 1
            return
        self.stmt[st["id"]] = st
        self.stmt_owner[st["id"]] = pid
        self.stmt_parent[st["id"]] = parent
        self.stmt_depth[st["id"]] = depth
        if st["stmt"] == "loop":
            for a in [i.get("assignment") for i in st.get("init", []) if isinstance(i, dict)] + list(st.get("steps", [])):
                if a:
                    self.loop_assign.add(a)
        if st["stmt"] == "if":
            for br in ("then", "else"):
                if isinstance(st.get(br), dict):
                    self._walk(st[br], pid, {"statement": st["id"], "branch": br}, depth + 1, n)
            return
        if st["stmt"] == "case":
            for k, it in enumerate(st.get("items", [])):
                self._walk(it.get("body"), pid, {"statement": st["id"], "branch": "item", "item": k}, depth + 1, n)
            if st.get("default"):
                self._walk(st["default"].get("body"), pid, {"statement": st["id"], "branch": "default"}, depth + 1, n)
            return
        body = st.get("body")
        for x in body if isinstance(body, list) else [body]:
            self._walk(x, pid, parent, depth, n)

    def sig(self, rid):
        """Declaration (port / signal) targeted by reference ``rid``, else None."""
        r = self.refs.get(rid)
        if r and r["ref_kind"] in _SIGNAL_KINDS and r["target"] in self.decl:
            return r["target"]
        return None

    def role(self, pid):
        if pid is None:
            return None
        bp = self.bproc.get(pid)
        if bp is None:
            raise AnalysisError(f"process {pid} has no Behavioral Semantics record")
        return bp["role"]


# =============================================================================
# analysis
# =============================================================================

class _Analysis:
    def __init__(self, sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, inventory):
        self.x = _Inputs(sem, beh, sem_sha)
        self.sem, self.beh = sem, beh
        self.sem_rel, self.sem_sha, self.beh_rel, self.beh_sha = sem_rel, sem_sha, beh_rel, beh_sha
        self.inventory = inventory or {}
        self.out = {s: [] for s in T.SECTIONS}
        self.deps = {}                                   # key -> record
        self.ref_role = {}                               # ref id -> role within its assignment / connection
        self.conn_of_ref = {}                            # ref id -> connection record
        self.conn_whole = set()                          # connection refs that are whole signals
        self.notes = defaultdict(int)

    # ------------------------------------------------------------------ helpers
    def _assign_ctx(self, a, t):
        x = self.x
        if a["kind"] == "continuous":
            return "continuous_assignment"
        if a["id"] in x.loop_assign:
            return "loop_control"
        if a["kind"] == "declaration":
            return "continuous_assignment" if x.decl[t].get("kind") == "net" else "initialization"
        role = x.role(a["process"])
        if role == "initialization":
            return "initialization"
        if role == "sequential":
            leaf = x.leaf.get((a["id"], t))
            return {"reset": "reset", "hold_explicit": "hold"}.get(leaf, "sequential_update")
        return "procedural_assignment"

    def _boundary(self, a, t=None):
        if a["process"] is None:
            if a["kind"] == "declaration" and t is not None and self.x.decl[t].get("kind") != "net":
                return "initialization"
            return "combinational"
        return _BOUNDARY[self.x.role(a["process"])]

    def _dep(self, source, target, kind, context, boundary, via, process, loc, *, assignment=None,
             reference=None, behavior=(), direct=False, partial=False, status="confirmed", hold=None):
        key = (source, target, kind, context, via)
        d = self.deps.get(key)
        if d is None:
            d = self.deps[key] = {
                "id": T.struct_id("dependency", via, f"{source}>{target}:{kind}:{context}"),
                "source": source, "target": target, "kind": kind, "context": context, "boundary": boundary,
                "via": via, "process": process, "assignments": set(), "references": set(), "behavior": set(),
                "direct": direct, "partial": partial, "status": status, "hold": hold, "loc": loc,
            }
        if assignment:
            d["assignments"].add(assignment)
        if reference:
            d["references"].add(reference)
        d["behavior"].update(b for b in behavior if b)
        d["direct"] = d["direct"] and direct
        d["partial"] = d["partial"] or partial
        d["loc"] = _merge_loc(d["loc"], loc)
        return d

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        x, sem = self.x, self.sem
        for a in sem["assignments"]:
            roles = {}
            expr_roles(a.get("target"), "write", roles)
            expr_roles(a.get("value"), "value", roles)
            for rid, r in roles.items():
                self.ref_role[rid] = r
        self._instances()
        self._assignments()
        self._predicates()
        self._registers()
        self._drivers()
        self._loads()
        self._processes()
        self._signals()
        self._cycles()
        self._cones()
        doc = self._document()
        return doc

    # ------------------------------------------------------------------ instances / connections / hierarchy
    def _instances(self):
        x, mod = self.x, self.sem["module"]
        for inst in self.sem["instances"]:
            iid = inst["id"]
            sid = T.struct_id("instance", iid)
            child, status, reason = None, "resolved", None
            target = inst.get("target_module_id")
            if not inst.get("resolved") or not target:
                status, reason = "unresolved", "not_resolved_by_elaboration"
            elif target not in self.inventory:
                status, reason = "unresolved", "no_canonical_child_ir"
            else:
                cip, cmod = self.inventory[target]
                child = {"module_id": target, "ip": cip, "module": cmod,
                         "semantic_ir": f"normalized/semantic_ir/v2/{cip}/{cmod}.json",
                         "structural": f"{T.OUTPUT_DIR}/{cip}/{cmod}.json"}
            params = []
            for p in inst.get("parameters", []):
                roles = expr_roles(p.get("value"), "param", {})
                for rid in roles:
                    self.ref_role[rid] = "instance_parameter"
                params.append({"name": p.get("name"), "position": p.get("position"),
                               "references": sorted(roles),
                               "signals": sorted({x.sig(r) for r in roles if x.sig(r)})})
            conns = []
            for c in inst.get("connections", []):
                cid = T.struct_id("connection", iid, f"{c.get('position')}:{c.get('port')}")
                roles = expr_roles(c.get("expr"), "conn", {}) if c.get("expr") else {}
                direction = c.get("direction") if c.get("direction") in T.DIRECTIONS else "unknown"
                lvalue = isinstance(c.get("expr"), dict) and c["expr"].get("op") in _LVALUE_OPS
                rec = {
                    "id": cid, "instance": sid, "port": c.get("port"), "position": c.get("position"),
                    "kind": c.get("kind"), "direction": direction, "flow": _FLOW[direction],
                    "lvalue": bool(lvalue), "empty": not c.get("expr"),
                    "signals": sorted({x.sig(r) for r, ro in roles.items() if ro == "conn" and x.sig(r)}),
                    "index_signals": sorted({x.sig(r) for r, ro in roles.items() if ro == "conn_index" and x.sig(r)}),
                    "references": sorted(roles),
                    "status": "confirmed" if status == "resolved" and direction != "unknown" else "candidate",
                    "loc": inst["loc"],
                }
                for rid, ro in roles.items():
                    self.ref_role[rid] = ro
                    self.conn_of_ref[rid] = rec
                e = c.get("expr") or {}
                for item in [e] + (e.get("items", []) if e.get("op") == "concat" else []):
                    if isinstance(item, dict) and item.get("op") == "ref":
                        self.conn_whole.add(item["id"])
                conns.append(rec)
                self.out["connections"].append(rec)
            self.out["instances"].append({
                "id": sid, "instance": iid, "name": inst.get("name"), "module": inst.get("module"),
                "parent": mod["module_id"], "child": child, "status": status, "reason": reason,
                "parameters": params, "connections": sorted(c["id"] for c in conns),
                "generate": inst.get("generate"), "loc": inst["loc"],
            })
            self.out["hierarchy"].append({
                "id": T.struct_id("hierarchy", iid), "relationship": "instantiates", "parent": mod["module_id"],
                "child": child["module_id"] if child else None, "child_module": inst.get("module"),
                "instance": sid, "status": status, "cross_module": True, "loc": inst["loc"],
            })

    # ------------------------------------------------------------------ assignments and their dependencies
    def _guard_sources(self, g):
        """[(signal, ref id, context)] of the predicate of guard ``g``."""
        x, out = self.x, []
        st = g["statement"]
        if st in x.cond:
            for rid in x.cond[st].get("predicate_references", []):
                if x.sig(rid):
                    out.append((x.sig(rid), rid, "condition"))
        elif st in x.case:
            c = x.case[st]
            for rid in c.get("selector_references", []):
                if x.sig(rid):
                    out.append((x.sig(rid), rid, "case_expression"))
            items = c.get("items", [])
            sel = [items[g["item"]]] if g.get("branch") == "item" and g.get("item") is not None and g["item"] < len(items) \
                else (items if g.get("branch") == "default" else [])
            for it in sel:
                for rid in it.get("label_references", []):
                    if x.sig(rid):
                        out.append((x.sig(rid), rid, "case_item"))
        return out

    def _assignments(self):
        x = self.x
        for a in self.sem["assignments"]:
            if a.get("subroutine") is not None or (a["process"] is None and a["kind"] not in ("continuous", "declaration")):
                self.notes["subroutine_assignments"] += 1
                continue
            targets = [w for w in a["writes"] if w in x.decl]
            if not targets:
                self.notes["assignments_without_signal_target"] += 1
                continue
            if a.get("unresolved_writes"):
                self.notes["unresolved_writes"] += len(a["unresolved_writes"])
            roles = self._ref_ids(a)
            data = sorted({(x.sig(r), r) for r, ro in roles.items() if ro == "value" and x.sig(r)})
            tern = sorted({(x.sig(r), r) for r, ro in roles.items() if ro == "ternary_condition" and x.sig(r)})
            tidx = sorted({(x.sig(r), r) for r, ro in roles.items() if ro == "target_index" and x.sig(r)})
            v = a.get("value") or {}
            direct_src = v.get("target") if v.get("op") == "ref" else None
            pid = a["process"]
            control = set()
            boundary0 = self._boundary(a, targets[0])
            for t in targets:
                ctx = self._assign_ctx(a, t)
                boundary = self._boundary(a, t)
                partial = not whole_write(a, t)
                for s, rid in data:
                    hold = ctx == "hold" and s == t
                    self._dep(s, t, "hold" if hold else "data", ctx, boundary, a["id"], pid, a["loc"],
                              assignment=a["id"], reference=rid, direct=(s == direct_src), partial=partial,
                              hold="explicit" if hold else None,
                              behavior=[x.reg_by.get((x.bproc.get(pid, {}).get("id"), t), {}).get("id")] if hold else ())
                for s, rid in tern:
                    self._dep(s, t, "control", "ternary_condition", boundary, a["id"], pid, a["loc"],
                              assignment=a["id"], reference=rid, partial=partial)
                    control.add(s)
                for s, rid in tidx:
                    self._dep(s, t, "control", "target_index", boundary, a["id"], pid, a["loc"],
                              assignment=a["id"], reference=rid, partial=True)
                    control.add(s)
                for g in a.get("guards", []):
                    st = g["statement"]
                    stloc = (x.stmt.get(st) or {}).get("loc") or a["loc"]
                    for s, rid, gctx in self._guard_sources(g):
                        kind, context, beh, status = "control", gctx, (), "confirmed"
                        rst = [r for r in x.reset_of.get(st, ()) if r["signal"] == s
                               and x.bproc_by_id.get(r["process"], {}).get("process") == pid]
                        en = x.enable_of.get((st, t))
                        if rst:
                            kind, context, beh = "reset", "reset", [r["id"] for r in rst]
                            status = rst[0]["status"]
                        elif en and rid in en.get("predicate_references", []):
                            kind, context, beh = "enable", "enable", [en["id"]]
                        self._dep(s, t, kind, context, boundary, st, pid, stloc, assignment=a["id"],
                                  reference=rid, behavior=beh, partial=partial, status=status)
                        control.add(s)
            self.out["assignments"].append({
                "id": T.struct_id("assignment", a["id"]), "assignment": a["id"], "process": pid, "kind": a["kind"],
                "context": self._assign_ctx(a, targets[0]), "boundary": boundary0,
                "targets": sorted(targets), "partial": any(not whole_write(a, t) for t in targets),
                "data": sorted({s for s, _ in data}), "control": sorted(control),
                "guards": a.get("guards", []), "order": x.order.get(a["id"]),
                "generate": a.get("generate"), "loc": a["loc"],
            })

    def _ref_ids(self, a):
        out = {}
        expr_roles(a.get("target"), "write", out)
        expr_roles(a.get("value"), "value", out)
        return out

    # ------------------------------------------------------------------ predicates
    def _predicates(self):
        x = self.x
        targets = defaultdict(set)
        for a in self.sem["assignments"]:
            for g in a.get("guards", []):
                targets[g["statement"]].update(w for w in a["writes"] if w in x.decl)
        for sid, st in sorted(x.stmt.items()):
            if st["stmt"] not in ("if", "case"):
                continue
            pid = x.stmt_owner[sid]
            if st["stmt"] == "if":
                c = x.cond.get(sid) or {}
                refs = c.get("predicate_references", [])
                kind, items, default = "if", [], isinstance(st.get("else"), dict)
            else:
                c = x.case.get(sid) or {}
                refs = c.get("selector_references", [])
                kind = st.get("case_kind") if st.get("case_kind") in T.PREDICATE_KINDS else "case"
                items = [{"index": k, "labels": it.get("labels"), "references": sorted(it.get("label_references", [])),
                          "signals": sorted({x.sig(r) for r in it.get("label_references", []) if x.sig(r)})}
                         for k, it in enumerate(c.get("items", []))]
                default = bool(st.get("default"))
            role = "control"
            if any(r.get("condition") == sid for r in x.beh["resets"]):
                role = "reset"
            elif any(e["condition"] == sid for e in x.beh["enables"]):
                role = "enable"
            self.out["predicates"].append({
                "id": T.struct_id("predicate", sid), "statement": sid, "kind": kind,
                "qualifier": c.get("qualifier"), "process": pid,
                "references": sorted(refs), "signals": sorted({x.sig(r) for r in refs if x.sig(r)}),
                "items": items, "default": default, "targets": sorted(targets.get(sid, ())),
                "parent": x.stmt_parent[sid], "depth": x.stmt_depth[sid], "role": role, "loc": st["loc"],
            })

    # ------------------------------------------------------------------ registers (behavioral) and clock / hold edges
    def _registers(self):
        x = self.x
        for r in sorted(x.beh["registers"], key=lambda r: r["id"]):
            bp = x.bproc_by_id[r["process"]]
            pid, t = bp["process"], r["signal"]
            boundary = _BOUNDARY[bp["role"]]
            clock = None
            if r.get("clock"):
                c = x.bclock[r["clock"]]
                clock = {"clock": c["id"], "signal": c["signal"], "edge": c["edge"], "status": c["status"]}
                ref = c["semantic"][0] if c.get("semantic") else None
                self._dep(c["signal"], t, "clock", "clock_event", boundary, pid, pid, c["loc"],
                          reference=ref, behavior=[c["id"], r["id"]], status=c["status"])
            resets = []
            for rid in r.get("resets", []):
                rs = x.breset[rid]
                resets.append({"reset": rid, "signal": rs["signal"], "kind": rs["kind"], "polarity": rs["polarity"],
                               "status": rs["status"], "condition": rs.get("condition"),
                               "assignments": sorted(tg["assignment"] for tg in rs.get("targets", []) if tg["signal"] == t)})
            enables = []
            for eid in r.get("enables", []):
                e = x.benable[eid]
                enables.append({"enable": eid, "condition": e["condition"], "update_branch": e["update_branch"],
                                "hold_branch": e["hold_branch"],
                                "signals": sorted({x.sig(q) for q in e.get("predicate_references", []) if x.sig(q)})})
            holds = []
            for hid in r.get("holds", []):
                h = x.bhold[hid]
                holds.append({"hold": hid, "kind": h["kind"], "assignment": h.get("assignment")})
            implicit = [h["hold"] for h in holds if h["kind"] == "implicit"]
            if implicit:
                self._dep(t, t, "hold", "hold", boundary, pid, pid, r["loc"], behavior=implicit + [r["id"]],
                          hold="implicit")
            nexts = []
            for nid in r.get("next_values", []):
                nv = x.bnext[nid]
                nexts.append({"next_value": nid, "assignment": nv["assignment"], "value": nv["value"],
                              "sources": sorted({x.sig(q) for q in nv.get("value_references", []) if x.sig(q)})})
            self.out["registers"].append({
                "id": T.struct_id("register", r["id"]), "register": r["id"], "signal": t, "name": r["name"],
                "process": pid, "behavior_process": bp["id"], "boundary": boundary, "clock": clock,
                "resets": resets, "enables": enables, "holds": holds, "hold": r["hold"], "update": r["update"],
                "next_values": nexts, "priority": [dict(p) for p in r["priority"]],
                "state_candidate": x.state_cand.get(r["id"]), "loc": r["loc"],
            })

    # ------------------------------------------------------------------ drivers
    def _drivers(self):
        x = self.x
        drv = {}

        def add(signal, unit, kind, loc, *, process=None, assignment=None, connection=None, reference=None,
                whole=True, status="confirmed", role=None):
            key = (signal, unit)
            d = drv.get(key)
            if d is None:
                d = drv[key] = {"id": T.struct_id("driver", unit, signal), "signal": signal, "kind": kind,
                                "unit": unit, "process": process, "role": role, "assignments": [],
                                "connection": connection, "references": set(), "whole": True,
                                "status": status, "loc": loc}
            if assignment:
                d["assignments"].append(assignment)
            if reference:
                d["references"].add(reference)
            d["whole"] = d["whole"] and whole
            d["loc"] = _merge_loc(d["loc"], loc)

        for a in self.sem["assignments"]:
            if a.get("subroutine") is not None or (a["process"] is None and a["kind"] not in ("continuous", "declaration")):
                continue
            wrefs = defaultdict(set)
            for rid, ro in self._ref_ids(a).items():
                if ro == "write" and x.sig(rid):
                    wrefs[x.sig(rid)].add(rid)
            for t in a["writes"]:
                if t not in x.decl:
                    continue
                if a["kind"] == "continuous":
                    kind, unit, role = "continuous_assignment", a["id"], None
                elif a["kind"] == "declaration":
                    kind = "net_declaration" if x.decl[t].get("kind") == "net" else "initializer"
                    unit, role = a["id"], None
                else:
                    role = x.role(a["process"])
                    kind, unit = ("initializer" if role == "initialization" else "procedural"), a["process"]
                for rid in sorted(wrefs.get(t, ())) or [None]:
                    add(t, unit, kind, a["loc"], process=a["process"], assignment=a["id"], reference=rid,
                        whole=whole_write(a, t), role=role)
        for c in self.out["connections"]:
            if c["empty"]:
                continue
            if c["direction"] == "output":
                kind = "instance_output"
            elif c["direction"] == "inout":
                kind = "instance_inout"
            elif c["direction"] == "unknown" and c["lvalue"]:
                kind = "instance_unknown"
            else:
                continue
            refs = [r for r in c["references"] if self.ref_role.get(r) == "conn" and x.sig(r)]
            for rid in refs:
                add(x.sig(rid), c["id"], kind, c["loc"], connection=c["id"], reference=rid,
                    whole=rid in self.conn_whole,
                    status="candidate" if kind == "instance_unknown" else c["status"])
        mid = self.sem["module"]["id"]
        for p in self.sem["ports"]:
            if p.get("direction") in ("input", "inout"):
                add(p["id"], mid, "module_input", p["loc"])
        for d in drv.values():
            d["assignments"] = sorted(set(d["assignments"]))
            d["references"] = sorted(d["references"])
            self.out["drivers"].append(d)

    # ------------------------------------------------------------------ loads
    def _loads(self):
        x = self.x
        assigned = {a["id"]: a for a in self.sem["assignments"]}
        for r in self.sem["references"]:
            if r["usage"] not in ("read", "connect") or not x.sig(r["id"]):
                continue
            src, rid = r["source"], r["id"]
            consumer, process, targets, kind = src, None, [], None
            if src in assigned:
                a = assigned[src]
                process = a["process"]
                targets = sorted(w for w in a["writes"] if w in x.decl)
                if a.get("subroutine") is not None or (a["process"] is None and a["kind"] not in ("continuous", "declaration")):
                    kind = "subroutine"
                else:
                    kind = {"value": "assignment_value", "ternary_condition": "ternary_condition",
                            "target_index": "target_index", "write": "target_index"}.get(self.ref_role.get(rid))
            elif src in x.cond:
                kind, process = "condition", x.stmt_owner.get(src, x.cond[src].get("owner"))
            elif src in x.case:
                c = x.case[src]
                kind = "case_expression" if rid in c.get("selector_references", []) else "case_item"
                process = x.stmt_owner.get(src, c.get("owner"))
            elif src in x.proc:
                kind, process = "event", src
            elif src in x.inst:
                ro = self.ref_role.get(rid)
                conn = self.conn_of_ref.get(rid)
                if ro == "instance_parameter":
                    kind = "instance_parameter"
                elif ro == "conn_index":
                    kind = "instance_index"
                elif conn is not None:
                    if conn["direction"] == "output":
                        continue                                         # a driver, not a load
                    kind = {"input": "instance_input", "inout": "instance_inout"}.get(conn["direction"], "instance_unknown")
                consumer = conn["id"] if conn is not None else T.struct_id("instance", src)
            elif src in x.stmt_owner:
                kind = "loop_condition" if x.stmt[src]["stmt"] == "loop" else "statement"
                process = x.stmt_owner[src]
            elif src in x.subroutines or src in x.subroutine_stmts:
                kind = "subroutine"
            elif src in x.decl:
                kind = "declaration"
            if kind is None:
                kind = "statement"
                self.notes["loads_unclassified"] += 1
            self.out["loads"].append({
                "id": T.struct_id("load", rid, kind), "signal": r["target"], "reference": rid, "kind": kind,
                "consumer": consumer, "process": process, "targets": targets, "loc": r["loc"],
            })
        for p in self.sem["ports"]:
            if p.get("direction") in ("output", "inout"):
                self.out["loads"].append({
                    "id": T.struct_id("load", p["id"], "module_output"), "signal": p["id"], "reference": None,
                    "kind": "module_output", "consumer": self.sem["module"]["id"], "process": None,
                    "targets": [], "loc": p["loc"],
                })

    # ------------------------------------------------------------------ processes (read / write sets, ordering)
    def _processes(self):
        x = self.x
        loads_by_proc = defaultdict(set)
        for ld in self.out["loads"]:
            if ld["process"] is not None and ld["kind"] != "module_output":
                loads_by_proc[ld["process"]].add(ld["signal"])
        writes_by_proc = defaultdict(set)
        nb = defaultdict(lambda: True)
        for a in self.sem["assignments"]:
            if a["process"] is None or a.get("subroutine") is not None:
                continue
            for w in a["writes"]:
                if w in x.decl:
                    writes_by_proc[a["process"]].add(w)
                    nb[(a["process"], w)] = nb[(a["process"], w)] and a["kind"] == "nonblocking"
        drivers_by_proc = defaultdict(list)
        for d in self.out["drivers"]:
            if d["process"] is not None:
                drivers_by_proc[d["process"]].append(d["id"])
        preds_by_proc = defaultdict(list)
        for p in self.out["predicates"]:
            preds_by_proc[p["process"]].append(p["id"])
        self.write_first = set()
        for p in self.sem["processes"]:
            pid = p["id"]
            bp = x.bproc.get(pid)
            if bp is None:
                raise AnalysisError(f"process {pid} has no Behavioral Semantics record")
            reads, writes = sorted(loads_by_proc[pid]), sorted(writes_by_proc[pid])
            first = self._first_events(p)
            rw = []
            for s in sorted(set(reads) & set(writes)):
                ev = first.get(s)
                if nb[(pid, s)]:
                    order = "nonblocking"
                elif ev is None or ev[2]:
                    order = "unknown"
                elif ev[0] == "read":
                    order = "read_first"
                elif ev[1] == 0:
                    order = "write_first"
                    self.write_first.add((pid, s))
                else:
                    order = "mixed"
                rw.append({"signal": s, "order": order})
            self.out["processes"].append({
                "id": T.struct_id("process", pid), "process": pid, "behavior": bp["id"], "kind": p["kind"],
                "role": bp["role"], "confidence": bp["confidence"], "boundary": _BOUNDARY[bp["role"]],
                "reads": reads, "writes": writes, "read_write": rw,
                "assignments": sorted(a["id"] for a in self.sem["assignments"] if a["process"] == pid),
                "drivers": sorted(drivers_by_proc[pid]), "predicates": sorted(preds_by_proc[pid]),
                "loc": p["loc"],
            })

    def _first_events(self, p):
        """signal -> (event, guard depth, uncertain) of its first occurrence in body order."""
        x, first = self.x, {}
        uncertain = [False]

        def note(sig, ev, depth):
            if sig not in first:
                first[sig] = (ev, depth, uncertain[0])

        def visit(st, depth):
            if not isinstance(st, dict) or "stmt" not in st:
                return
            k = st["stmt"]
            if k == "assign":
                a = x.assign.get(st["assignment"])
                if a is None:
                    return
                for s in a.get("reads", []):
                    if s in x.decl:
                        note(s, "read", depth)
                for s in a.get("writes", []):
                    if s in x.decl:
                        note(s, "write", depth)
                return
            if k == "if":
                for rid in (x.cond.get(st["id"]) or {}).get("predicate_references", []):
                    if x.sig(rid):
                        note(x.sig(rid), "read", depth)
                for br in ("then", "else"):
                    visit(st.get(br), depth + 1)
                return
            if k == "case":
                c = x.case.get(st["id"]) or {}
                for rid in c.get("selector_references", []) + [q for it in c.get("items", []) for q in it.get("label_references", [])]:
                    if x.sig(rid):
                        note(x.sig(rid), "read", depth)
                for it in st.get("items", []):
                    visit(it.get("body"), depth + 1)
                if st.get("default"):
                    visit(st["default"].get("body"), depth + 1)
                return
            if k not in ("block", "null"):
                uncertain[0] = True                    # loop / call / timing / opaque: order not established
            body = st.get("body")
            for b in body if isinstance(body, list) else [body]:
                visit(b, depth)

        for st in p["body"]:
            visit(st, 0)
        return first

    # ------------------------------------------------------------------ signals: drivers, loads, fan-in / fan-out, classes
    def _signals(self):
        x = self.x
        drivers, loads = defaultdict(list), defaultdict(list)
        for d in self.out["drivers"]:
            drivers[d["signal"]].append(d)
        for ld in self.out["loads"]:
            loads[ld["signal"]].append(ld)
        dep_in, dep_out = defaultdict(list), defaultdict(list)
        for d in self.deps.values():
            dep_in[d["target"]].append(d)
            dep_out[d["source"]].append(d)
        regs = {r["signal"]: r for r in self.out["registers"]}
        clocks = defaultdict(list)
        for c in x.beh["clocks"]:
            clocks[c["signal"]].append(c)
        resets = defaultdict(list)
        for r in x.beh["resets"]:
            resets[r["signal"]].append(r)
        enables = defaultdict(list)
        for e in x.beh["enables"]:
            for q in e.get("predicate_references", []):
                if x.sig(q):
                    enables[x.sig(q)].append(e["id"])
        conns = defaultdict(list)
        for c in self.out["connections"]:
            for s in c["signals"] + c["index_signals"]:
                conns[s].append(c)
        incomplete = self.sem.get("extraction") != "complete" or bool(self.sem.get("unsupported"))
        for sid, decl in sorted(x.decl.items()):
            ds, ls = drivers[sid], loads[sid]
            port = sid in x.ports
            direction = decl.get("direction") if port else None
            real = [d for d in ds if d["kind"] not in ("initializer", "instance_unknown")]
            units = [d for d in ds if d["kind"] not in ("initializer", "instance_unknown")]
            if port and direction in ("input", "inout"):
                status = "external"
            elif real or any(d["kind"] == "initializer" for d in ds):
                status = "driven"
            elif any(d["kind"] == "instance_unknown" for d in ds) or any(l["kind"] in ("statement", "subroutine", "instance_unknown") for l in ls) or incomplete:
                status = "unknown"
            else:
                status = "undriven"
            ins, outs = dep_in[sid], dep_out[sid]
            fan_in = {
                "direct": len({d["source"] for d in ins if d["kind"] == "data" and d["direct"]}),
                "expression": len({d["source"] for d in ins if d["kind"] in ("data", "hold") and not d["direct"]}),
                "control": len({d["source"] for d in ins if d["kind"] not in ("data", "hold")}),
                "processes": len({d["process"] for d in ds if d["process"]}),
                "drivers": len(units),
                "signals": len({d["source"] for d in ins}),
            }
            fan_out = {
                "processes": len({l["process"] for l in ls if l["process"]}),
                "assignments": len({l["consumer"] for l in ls if l["consumer"] in x.assign}),
                "signals": len({d["target"] for d in outs}),
                "outputs": len({d["target"] for d in outs if x.ports.get(d["target"], {}).get("direction") in ("output", "inout")})
                + (1 if direction in ("output", "inout") else 0),
                "instances": len({c["instance"] for c in conns[sid] if c["direction"] != "output"}),
                "loads": len(ls),
            }
            classes = self._classes(sid, decl, ds, ls, ins, outs, regs.get(sid), clocks[sid], resets[sid],
                                    enables[sid], conns[sid], status)
            self.out["signals"].append({
                "id": T.struct_id("signal", sid), "signal": sid, "name": decl["name"],
                "kind": "port" if port else "signal", "direction": direction if port else None,
                "declaration": decl.get("kind"), "width": decl.get("width"),
                "drivers": sorted(d["id"] for d in ds), "loads": sorted(l["id"] for l in ls),
                "driver_status": status, "driver_units": len(units), "multiple_drivers": len(units) > 1,
                "possible_drivers": sum(1 for d in ds if d["kind"] == "instance_unknown"),
                "fan_in": fan_in, "fan_out": fan_out, "classes": classes,
                "register": regs[sid]["id"] if sid in regs else None, "loc": decl["loc"],
            })
            if len(units) > 1:
                reasons = sorted({"partial_writes" for d in units if not d["whole"]}
                                 | {"generate" for d in units for a in d["assignments"] if x.assign[a].get("generate")})
                self.out["multiple_drivers"].append({
                    "id": T.struct_id("multiple_drivers", sid), "signal": sid, "units": sorted(d["id"] for d in units),
                    "kinds": sorted({d["kind"] for d in units}), "reasons": reasons,
                    "status": "candidate" if reasons else "confirmed", "loc": decl["loc"],
                })

    def _classes(self, sid, decl, ds, ls, ins, outs, reg, clocks, resets, enables, conns, status):
        out = {}

        def put(cls, st, *ev):
            out[cls] = {"class": cls, "status": st, "evidence": [e for e in ev if e]}

        hint = _ev("name_hint", [sid]) if T.NAME_HINT_RE.search(decl["name"] or "") else None
        if clocks:
            st = "confirmed" if any(c["status"] == "confirmed" for c in clocks) else clocks[0]["status"]
            put("clock", st, _ev("behavior_clock", [c["id"] for c in clocks]),
                _ev("event_reference", [l["reference"] for l in ls if l["kind"] == "event"]) if any(l["kind"] == "event" for l in ls) else None,
                hint)
        if resets:
            sts = {r["status"] for r in resets}
            st = "confirmed" if "confirmed" in sts else ("candidate" if "candidate" in sts else "ambiguous")
            put("reset", st, _ev("behavior_reset", [r["id"] for r in resets]), hint)
        if enables:
            put("enable", "confirmed", _ev("behavior_enable", enables), hint)
        if reg is not None:
            st = "confirmed" if reg["boundary"] == "sequential" and (reg["clock"] or {}).get("status") == "confirmed" else "candidate"
            put("sequential_boundary", st, _ev("behavior_register", [reg["register"]]), hint)
            if reg["holds"]:
                put("hold", "confirmed", _ev("behavior_hold", [h["hold"] for h in reg["holds"]]))
        ctl = [d for d in outs if d["kind"] in ("control", "reset", "enable")]
        if ctl:
            codes = []
            for ctx, code in (("condition", "predicate_reference"), ("case_expression", "case_selector"),
                              ("case_item", "case_label"), ("ternary_condition", "ternary_condition"),
                              ("target_index", "target_index"), ("reset", "predicate_reference"),
                              ("enable", "predicate_reference")):
                sel = [d["id"] for d in ctl if d["context"] == ctx]
                if sel and code not in {c["code"] for c in codes}:
                    codes.append(_ev(code, sel))
            put("control", "confirmed", *codes)
        data = [d["id"] for d in outs if d["kind"] == "data"]
        if data:
            put("data", "confirmed", _ev("data_source", data))
        real = [d for d in ds if d["kind"] != "module_input"]
        if real:
            st = "candidate" if all(d["status"] != "confirmed" for d in real) else "confirmed"
            put("driver", st, _ev("has_driver", [d["id"] for d in real]))
        loads = [l for l in ls if l["kind"] != "module_output"]
        if loads:
            put("load", "confirmed", _ev("has_load", [l["id"] for l in loads]))
        if conns:
            st = "confirmed" if any(c["status"] == "confirmed" for c in conns) else "candidate"
            put("port_connection", st, _ev("instance_connection", [c["id"] for c in conns]),
                _ev("unknown_direction", [c["id"] for c in conns if c["direction"] == "unknown"])
                if any(c["direction"] == "unknown" for c in conns) else None)
        direction = decl.get("direction")
        if decl["id"] in self.x.ports:
            put("hierarchy", "confirmed",
                _ev("module_input", [sid]) if direction in ("input", "inout") else None,
                _ev("module_output", [sid]) if direction in ("output", "inout") else None,
                _ev("instance_connection", []) if direction not in ("input", "inout", "output") else None)
            if not out["hierarchy"]["evidence"]:
                out["hierarchy"]["evidence"] = [_ev("module_input", [sid], 0)]
        if not out or set(out) == {"hierarchy"} and not loads and not real:
            st = "unsupported" if status == "unknown" else "ambiguous"
            ev = [_ev("opaque_reference", [l["id"] for l in ls if l["kind"] in ("statement", "subroutine")])] \
                if any(l["kind"] in ("statement", "subroutine") for l in ls) else [_ev("no_structural_use", [sid])]
            put("unknown", st, *ev)
        return [out[c] for c in T.CLASSES if c in out]

    # ------------------------------------------------------------------ combinational cycles
    def _cycles(self):
        graph = defaultdict(set)
        edges = defaultdict(list)
        for d in self.deps.values():
            if d["boundary"] not in ("combinational", "latch") or d["kind"] in ("hold", "clock") \
                    or d["context"] == "loop_control":
                continue
            if d["process"] is not None and (d["process"], d["source"]) in self.write_first:
                continue                                   # process-local value written before it is read
            graph[d["source"]].add(d["target"])
            edges[(d["source"], d["target"])].append(d)
        for comp in Q.scc(graph):
            nodes = set(comp)
            if len(comp) == 1 and comp[0] not in graph.get(comp[0], ()):
                continue
            es = [d for (s, t), ds in edges.items() if s in nodes and t in nodes for d in ds]
            sig = sorted(nodes)
            self.out["cycles"].append({
                "id": T.struct_id("cycle", sig[0], ",".join(sig)), "kind": "combinational", "signals": sig,
                "edges": sorted(d["id"] for d in es), "length": len(sig),
                "status": "candidate" if any(d["partial"] for d in es) else "confirmed",
                "loc": min((d["loc"] for d in es), key=_lk),
            })

    # ------------------------------------------------------------------ cones
    def _cones(self):
        x = self.x
        roots = []
        for r in self.out["registers"]:
            roots += [(r["signal"], "fanin"), (r["signal"], "fanout")]
        for p in self.sem["ports"]:
            if p.get("direction") in ("output", "inout"):
                roots.append((p["id"], "fanin"))
            if p.get("direction") in ("input", "inout"):
                roots.append((p["id"], "fanout"))
        view = self._query_view()
        for sig, direction in sorted(set(roots)):
            c = Q.cone(view, sig, direction)
            self.out["cones"].append(dict(c, id=T.struct_id("cone", sig, direction), loc=x.decl[sig]["loc"]))

    def _query_view(self) -> dict:
        return {
            "dependencies": list(self.deps.values()),
            "signals": [{"signal": s, "direction": d.get("direction") if s in self.x.ports else None}
                        for s, d in self.x.decl.items()],
            "registers": self.out["registers"], "cycles": self.out["cycles"],
            "connections": self.out["connections"], "drivers": self.out["drivers"], "loads": self.out["loads"],
            "predicates": self.out["predicates"],
        }

    # ------------------------------------------------------------------ document
    def _document(self) -> dict:
        x = self.x
        deps = []
        for d in self.deps.values():
            deps.append(dict(d, assignments=sorted(d["assignments"]), references=sorted(d["references"]),
                             behavior=sorted(d["behavior"])))
        self.out["dependencies"] = deps
        for s in T.SECTIONS:
            self.out[s].sort(key=lambda r: r["id"])
        m = self.sem["module"]
        doc = {
            "schema": {"name": T.SCHEMA_NAME, "version": T.SCHEMA_VERSION},
            "versions": {"schema": T.SCHEMA_VERSION, "identity": T.IDENTITY_VERSION, "analyzer": T.ANALYZER_VERSION,
                         "provenance": T.PROVENANCE_VERSION, "semantic_ir": T.SEMANTIC_IR_VERSION,
                         "semantic_identity": T.SEMANTIC_IDENTITY_VERSION, "behavior": T.BEHAVIOR_VERSION,
                         "behavior_identity": T.BEHAVIOR_IDENTITY_VERSION},
            "generator": {"analyzer": T.ANALYZER},
            "module": {
                "ip": m["ip"], "name": m["name"], "module_id": m["module_id"], "semantic_id": m["id"],
                "loc": m["loc"], "source": dict(m["source"]),
                "semantic_ir": {"path": self.sem_rel, "sha256": self.sem_sha, "schema_version": T.SEMANTIC_IR_VERSION,
                                "identity_version": T.SEMANTIC_IDENTITY_VERSION},
                "behavior": {"path": self.beh_rel, "sha256": self.beh_sha, "schema_version": T.BEHAVIOR_VERSION,
                             "identity_version": T.BEHAVIOR_IDENTITY_VERSION},
            },
        }
        doc.update({s: self.out[s] for s in T.SECTIONS})
        doc["counts"] = counts(doc)
        doc["notes"] = dict(sorted(self.notes.items()))
        doc["fingerprint"] = fingerprint(doc)
        doc["id"] = T.document_id(doc)
        return doc


# =============================================================================
# counts / fingerprint
# =============================================================================

def counts(doc: dict) -> dict:
    c = {s: len(doc[s]) for s in T.SECTIONS}
    for k in T.DEP_KINDS:
        c[f"dependencies_{k}"] = sum(1 for d in doc["dependencies"] if d["kind"] == k)
    for b in T.BOUNDARIES:
        c[f"boundary_{b}"] = sum(1 for d in doc["dependencies"] if d["boundary"] == b)
    c["sequential_boundaries"] = c["boundary_sequential"]
    for k in T.DRIVER_STATUS:
        c[f"signals_{k}"] = sum(1 for s in doc["signals"] if s["driver_status"] == k)
    c["unresolved_instances"] = sum(1 for i in doc["instances"] if i["status"] == "unresolved")
    c["unknown_connections"] = sum(1 for x in doc["connections"] if x["direction"] == "unknown")
    c["cycles_confirmed"] = sum(1 for x in doc["cycles"] if x["status"] == "confirmed")
    c["cycles_candidate"] = sum(1 for x in doc["cycles"] if x["status"] == "candidate")
    c["objects"] = sum(len(doc[s]) for s in T.SECTIONS)
    return c


def fingerprint(doc: dict) -> str:
    """Identity- and location-free structure hash (names, kinds, widths, relationships)."""
    name = {s["signal"]: s["name"] for s in doc["signals"]}
    inst = {i["id"]: i for i in doc["instances"]}
    proj = {
        "signals": sorted([s["name"], s["kind"], s["direction"] or "", str(s["width"]), s["driver_status"]]
                          for s in doc["signals"]),
        "dependencies": sorted([name.get(d["source"], "?"), name.get(d["target"], "?"), d["kind"], d["context"],
                                d["boundary"]] for d in doc["dependencies"]),
        "connections": sorted([inst[c["instance"]]["module"] or "", inst[c["instance"]]["name"] or "",
                               str(c["port"]), c["direction"], ",".join(sorted(name.get(s, "?") for s in c["signals"]))]
                              for c in doc["connections"]),
        "instances": sorted([i["module"] or "", i["name"] or ""] for i in doc["instances"]),
    }
    return T.struct_id("fingerprint", "", T.dumps(proj))


# =============================================================================
# corpus
# =============================================================================

def analyze(sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, inventory=None) -> dict:
    return _Analysis(sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, inventory).run()


def canonical_modules(data_root) -> list:
    from scripts.core.paths import ForgeDataPaths, iter_module_yamls

    data = ForgeDataPaths.from_root(data_root)
    return sorted({(p.parent.parent.name, p.stem) for p in iter_module_yamls(data.normalized_ir)})


def inventory(data_root) -> dict:
    """Canonical module identity -> (ip, module), for hierarchy resolution."""
    from scripts.core.provenance import module_id

    return {module_id(ip, m): (ip, m) for ip, m in canonical_modules(data_root)}


def semantic_rel(ip, module) -> str:
    return f"normalized/semantic_ir/v2/{ip}/{module}.json"


def behavior_rel(ip, module) -> str:
    return f"normalized/behavior/v1/{ip}/{module}.json"


def structural_rel(ip, module) -> str:
    return f"{T.OUTPUT_DIR}/{ip}/{module}.json"


def load_inputs(data_root, ip, module) -> tuple:
    """(sem, sem_rel, sem_sha, beh, beh_rel, beh_sha) of a canonical module (fail closed)."""
    root = Path(os.path.abspath(data_root))
    out = []
    for rel, what in ((semantic_rel(ip, module), "Semantic IR"), (behavior_rel(ip, module), "Behavioral Semantics")):
        path = root / rel
        if not path.is_file():
            raise AnalysisError(f"missing {what} input {rel}")
        raw = path.read_bytes()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise AnalysisError(f"{rel}: invalid JSON ({exc})") from exc
        m = doc.get("module") or {}
        if (m.get("ip"), m.get("name")) != (ip, module):
            raise AnalysisError(f"{rel}: describes {m.get('ip')}/{m.get('name')}")
        out += [doc, rel, sha256_bytes(raw)]
    return tuple(out)


def build(data_root, ip, module, inv=None) -> dict:
    sem, srel, ssha, beh, brel, bsha = load_inputs(data_root, ip, module)
    return analyze(sem, srel, ssha, beh, brel, bsha, inventory(data_root) if inv is None else inv)


def write_all(data_root) -> dict:
    """Write Structural Analysis v1 for every canonical module (fail closed)."""
    from scripts.core.paths import find_absolute_paths

    root = Path(os.path.abspath(data_root))
    inv = inventory(root)
    written = 0
    for ip, module in canonical_modules(root):
        doc = build(root, ip, module, inv)
        text = T.dumps(doc)
        if find_absolute_paths(text):
            raise AnalysisError(f"{ip}/{module}: absolute path in structural output")
        out = root / structural_rel(ip, module)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            out.write_text(text, encoding="utf-8")
        written += 1
    return {"documents": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-010 Structural Analysis v1 analyzer")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--write", action="store_true", help="(re)generate normalized/structural/v1")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    if not args.write:
        parser.error("nothing to do (use --write; validate with scripts/structural/validator.py)")
    try:
        res = write_all(args.data_root)
    except AnalysisError as exc:
        print(f"[STOP] structural analysis refused: {exc}")
        return 1
    print(f"[INFO] wrote {res['documents']} Structural Analysis v1 documents to {T.OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
