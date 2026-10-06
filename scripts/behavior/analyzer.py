#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : analyzer.py
# Description : Semantic IR v2 to Behavioral Semantics v1 analysis (KF-DQ-009)
#
# Component   : Kritva Forge
# Module      : behavior
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral process semantics from Semantic IR v2.

``analyze(semantic_doc, semantic_path, semantic_sha256)`` interprets one
Semantic IR v2 module document; ``write_all(data_root)`` does it for every
canonical module.  Only the persisted Semantic IR v2 JSON is read - no RTL
parsing, no parser objects, no duplicated expression trees (behavioral
records reference Semantic IR identities).

Classification is evidence based and conservative:

* process role from keyword, event structure, assignment kinds and
  assignment completeness - never from names (``name_hint`` evidence is
  descriptive only);
* clocks: edge-event signals that are not reset signals; resets: signals of
  the leading ``if`` test whose branch assigns constants (asynchronous when
  the signal is in the event list, synchronous candidate otherwise);
* registers: port/signal targets of sequential processes, with per-register
  priority leaves (reset > update > hold in if-else order), enables
  (a condition with an update branch and a hold-only branch), explicit /
  implicit holds and next-value assignments;
* combinational targets: completeness over all control paths (complete /
  conditional / incomplete / ambiguous) and latch status;
* state candidates: registers whose own value selects constant-valued
  updates (one-process) or whose next value comes from a combinational
  signal selected by the register (two-process); no FSM is built.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from scripts.behavior import model as B

# coverage lattice (criteria section 18)
NONE, PARTIAL, UNKNOWN, COND, FULL = 0, 1, 2, 3, 4
_COMPLETENESS = {FULL: "complete", COND: "conditional", PARTIAL: "incomplete", UNKNOWN: "ambiguous",
                 NONE: "ambiguous"}
_CONF = ("unknown", "low", "medium", "high")
_SIGNAL_KINDS = ("port", "signal")
_CONST_REF_KINDS = ("parameter", "enum_member", "external", "genvar")
_CONST_CALLS = ("$signed", "$unsigned", "$clog2", "$bits", "$size")


class AnalysisError(RuntimeError):
    """Semantic IR input missing, unsupported or inconsistent (fail closed)."""


def _lower(conf: str, steps: int = 1) -> str:
    return _CONF[max(0, _CONF.index(conf) - steps)]


def _ev(code: str, *refs) -> dict:
    assert code in B.EVIDENCE, code
    return {"code": code, "refs": sorted({r for r in refs if r})}


def _guard(statement, branch, item=None) -> dict:
    g = {"statement": statement, "branch": branch}
    if item is not None:
        g["item"] = item
    return g


# =============================================================================
# Semantic IR index
# =============================================================================

class _Sem:
    def __init__(self, sem: dict):
        if not isinstance(sem, dict) or sem.get("schema") != {"name": "kritva-forge-semantic-ir",
                                                               "version": B.SEMANTIC_IR_VERSION}:
            raise AnalysisError(f"unsupported Semantic IR schema {sem.get('schema') if isinstance(sem, dict) else sem!r}")
        if (sem.get("versions") or {}).get("identity") != B.SEMANTIC_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Semantic IR identity version {(sem.get('versions') or {}).get('identity')!r}")
        self.doc = sem
        self.decl = {d["id"]: d for d in sem["ports"] + sem["signals"]}
        self.assign = {a["id"]: a for a in sem["assignments"]}
        self.refs = {r["id"]: r for r in sem["references"]}
        self.conditions = {c["id"]: c for c in sem["conditions"]}
        self.cases = {c["id"]: c for c in sem["cases"]}
        self.stmts, self.stmt_owner = {}, {}
        for p in sem["processes"]:
            for st in p["body"]:
                self._index(st, p["id"])

    def _index(self, st, pid):
        if not isinstance(st, dict) or "stmt" not in st:
            return
        if st["stmt"] != "assign":
            self.stmts[st["id"]] = st
            self.stmt_owner[st["id"]] = pid
        for key in ("then", "else", "body"):
            v = st.get(key)
            if isinstance(v, dict):
                self._index(v, pid)
            elif isinstance(v, list):
                for x in v:
                    self._index(x, pid)
        for it in st.get("items", []) if st["stmt"] == "case" else []:
            self._index(it.get("body"), pid)
        if st["stmt"] == "case" and st.get("default"):
            self._index(st["default"].get("body"), pid)

    def ref_loc(self, rid):
        r = self.refs.get(rid)
        return r["loc"] if r else None

    def name(self, sid):
        d = self.decl.get(sid)
        return d["name"] if d else None


# =============================================================================
# expression helpers (read-only over Semantic IR expression trees)
# =============================================================================

def _children(e):
    for k, v in e.items():
        if k == "loc":
            continue
        if isinstance(v, dict) and "op" in v:
            yield v
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict) and "op" in x:
                    yield x


def is_constant(e) -> bool:
    if not isinstance(e, dict):
        return False
    op = e.get("op")
    if op == "literal":
        return True
    if op == "ref":
        return e.get("ref_kind") in _CONST_REF_KINDS
    if op == "opaque":
        return False
    if op == "call":
        return bool(e.get("system")) and e.get("name") in _CONST_CALLS and all(is_constant(a) for a in e.get("args", []))
    kids = list(_children(e))
    return bool(kids) and all(is_constant(k) for k in kids)


def ref_ids(e, kinds=_SIGNAL_KINDS) -> list:
    out, stack = [], [e]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("op") == "ref":
                if kinds is None or x.get("ref_kind") in kinds:
                    out.append(x["id"])
            else:
                stack.extend(_children(x))
    return sorted(out)


def _same(a, b) -> bool:
    """Structural equality of two expressions ignoring reference identities."""
    if isinstance(a, dict) and isinstance(b, dict):
        ka = {k for k in a if k != "id"}
        if ka != {k for k in b if k != "id"}:
            return False
        return all(_same(a[k], b[k]) for k in ka)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _distinct(values) -> list:
    out = []
    for v in values:
        if not any(_same(v, o) for o in out):
            out.append(v)
    return out


def whole_write(a: dict, target: str) -> bool:
    t = a.get("target") or {}
    if t.get("op") == "ref":
        return t.get("target") == target
    if t.get("op") == "concat":
        return any(i.get("op") == "ref" and i.get("target") == target for i in t.get("items", []))
    return False


def value_kind(a: dict, target: str) -> str:
    v = a.get("value")
    if v is None:
        return "expression"                       # x++ / x--
    if _same(v, a.get("target")):
        return "self"
    if is_constant(v):
        return "constant"
    return "expression"


def signal_test(e, decl):
    """(signal id, polarity, ref id) when ``e`` tests exactly one 1-bit signal, else None."""
    if not isinstance(e, dict):
        return None

    def sig(x):
        if isinstance(x, dict) and x.get("op") == "ref" and x.get("ref_kind") in _SIGNAL_KINDS and x.get("target"):
            d = decl.get(x["target"])
            if d is not None and d.get("width") in (1, None):
                return x
        return None

    s = sig(e)
    if s:
        return s["target"], "active_high", s["id"]
    if e.get("op") == "unary" and e.get("operator") in ("!", "~"):
        s = sig(e.get("operand"))
        if s:
            return s["target"], "active_low", s["id"]
    if e.get("op") == "binary" and e.get("operator") in ("==", "===", "!=", "!=="):
        for x, y in ((e.get("left"), e.get("right")), (e.get("right"), e.get("left"))):
            s = sig(x)
            if s and isinstance(y, dict) and y.get("op") == "literal" and y.get("value") in (0, 1):
                high = (y["value"] == 1) == (e["operator"] in ("==", "==="))
                return s["target"], "active_high" if high else "active_low", s["id"]
    return None


def _flat(body):
    stmts = [s for s in body if isinstance(s, dict) and s.get("stmt") not in ("null",)]
    while len(stmts) == 1 and stmts[0]["stmt"] in ("block", "timing"):
        inner = stmts[0].get("body")
        inner = inner if isinstance(inner, list) else ([inner] if inner else [])
        stmts = [s for s in inner if isinstance(s, dict) and s.get("stmt") not in ("null",)]
    return stmts


def top_if(body):
    stmts = _flat(body)
    return stmts[0] if len(stmts) == 1 and stmts[0]["stmt"] == "if" else None


# =============================================================================
# control-path analysis
# =============================================================================

def _branch(vals):
    if all(v == FULL for v in vals):
        return FULL
    if all(v == NONE for v in vals):
        return NONE
    if any(v in (NONE, PARTIAL) for v in vals):
        return PARTIAL
    if any(v == UNKNOWN for v in vals):
        return UNKNOWN
    return COND


def cover(st, target, sem) -> int:
    """How completely ``st`` assigns ``target`` over its control paths."""
    if st is None:
        return NONE
    k = st.get("stmt")
    if k == "assign":
        a = sem.assign[st["assignment"]]
        if target not in a["writes"]:
            return NONE
        return FULL if whole_write(a, target) else UNKNOWN          # slice writes: bit coverage unknown
    if k == "block":
        res = NONE
        for c in st["body"]:
            res = max(res, cover(c, target, sem))
        return res
    if k == "if":
        return _branch([cover(st["then"], target, sem), cover(st["else"], target, sem)])
    if k == "case":
        vals = [cover(it.get("body"), target, sem) for it in st["items"]]
        if st.get("default"):
            return _branch(vals + [cover(st["default"].get("body"), target, sem)])
        if not vals:
            return NONE
        r = _branch(vals)
        return COND if r == FULL else r
    if k == "loop":
        return UNKNOWN if cover(st["body"], target, sem) != NONE else NONE
    if k == "timing":
        return cover(st.get("body"), target, sem)
    if k == "opaque":
        return UNKNOWN
    return NONE


def cover_body(body, target, sem) -> int:
    res = NONE
    for st in body:
        res = max(res, cover(st, target, sem))
    return res


def leaves(st, target, sem, path, covered, reset_paths) -> list:
    """Priority leaves of ``target`` below ``st`` in source / if-else order.

    ``covered`` is None, or {"kind": "hold"|"value", "assignment": id} when an
    earlier statement on this path already assigns the whole target.
    """
    if st is None:
        return []
    k = st.get("stmt")
    in_reset = any(_guard_key(g) in reset_paths for g in path)
    if k == "assign":
        a = sem.assign[st["assignment"]]
        if target not in a["writes"]:
            return []
        vk = value_kind(a, target)
        kind = "reset" if in_reset else ("hold_explicit" if vk == "self" else "update")
        return [{"kind": kind, "assignment": a["id"], "guards": list(path), "value": vk}]
    if k == "block":
        out, cov = [], covered
        for c in st["body"]:
            sub = leaves(c, target, sem, path, cov, reset_paths)
            out += sub
            if cov is None and cover(c, target, sem) == FULL:
                kinds = {lf["kind"] for lf in sub}
                cov = {"kind": "hold" if kinds == {"hold_explicit"} else "value",
                       "assignment": sub[-1]["assignment"] if sub else None}
        return out
    if k == "timing":
        return leaves(st.get("body"), target, sem, path, covered, reset_paths)
    if k == "loop":
        return leaves(st["body"], target, sem, path + [_guard(st["id"], "body")], covered, reset_paths)
    if k == "if":
        sid = st["id"]
        branches = [("then", st["then"]), ("else", st["else"])]
        relevant = any(cover(b, target, sem) != NONE for _, b in branches)
        out = []
        for name, b in branches:
            p = path + [_guard(sid, name)]
            sub = leaves(b, target, sem, p, covered, reset_paths)
            out += sub
            if relevant and cover(b, target, sem) == NONE:
                out += _missing(p, covered, reset_paths)
        return out
    if k == "case":
        sid = st["id"]
        relevant = cover(st, target, sem) != NONE
        out = []
        arms = [(_guard(sid, "item", i), it.get("body")) for i, it in enumerate(st["items"])]
        if st.get("default"):
            arms.append((_guard(sid, "default"), st["default"].get("body")))
        for g, b in arms:
            p = path + [g]
            out += leaves(b, target, sem, p, covered, reset_paths)
            if relevant and cover(b, target, sem) == NONE:
                out += _missing(p, covered, reset_paths)
        if relevant and not st.get("default"):
            out += _missing(path + [_guard(sid, "default")], covered, reset_paths)
        return out
    return []


def _missing(path, covered, reset_paths):
    if any(_guard_key(g) in reset_paths for g in path):
        return []                                   # not reset: no hold leaf inside the reset branch
    if covered is None:
        return [{"kind": "hold_implicit", "assignment": None, "guards": list(path), "value": "none"}]
    if covered["kind"] == "hold":
        return [{"kind": "hold_explicit", "assignment": covered["assignment"], "guards": list(path),
                 "value": "self", "default": True}]
    return []


def _guard_key(g):
    return (g["statement"], g["branch"], g.get("item"))


# =============================================================================
# module analysis
# =============================================================================

class _Analysis:
    def __init__(self, sem: dict, semantic_path: str, semantic_sha256: str):
        self.s = _Sem(sem)
        self.sem = sem
        self.semantic_path = semantic_path
        self.semantic_sha256 = semantic_sha256
        self.out = {k: [] for k in B.SECTIONS}
        self.ids = set()

    # -------------------------------------------------------------- identities
    def _id(self, category, anchor, qualifier=""):
        bid = B.behavior_id(category, anchor, qualifier)
        if bid in self.ids:
            raise AnalysisError(f"behavioral identity collision {category} {anchor} {qualifier}")
        self.ids.add(bid)
        return bid

    def _loc_of(self, sem_id):
        if sem_id in self.s.assign:
            return self.s.assign[sem_id]["loc"]
        if sem_id in self.s.stmts:
            return self.s.stmts[sem_id]["loc"]
        if sem_id in self.s.decl:
            return self.s.decl[sem_id]["loc"]
        return self.s.ref_loc(sem_id)

    def _name_hint(self, sid):
        name = self.s.name(sid) or ""
        return [_ev("name_hint", sid)] if B.NAME_HINT_RE.search(name) else []

    # -------------------------------------------------------------- driver
    def run(self) -> dict:
        procs = sorted(self.sem["processes"], key=B.loc_key)
        comb_targets = {}                           # signal -> [process ids] of combinational processes
        self._proc_info = {}
        for p in procs:
            self._process(p)
        for rec in self.out["processes"]:
            if rec["role"] in ("combinational", "latch"):
                for t in rec["combinational_targets"] + rec["latch_targets"]:
                    comb_targets.setdefault(t, []).append(rec["process"])
        self._state_candidates(comb_targets)
        doc = {
            "schema": {"name": B.SCHEMA_NAME, "version": B.SCHEMA_VERSION},
            "versions": {"schema": B.SCHEMA_VERSION, "identity": B.IDENTITY_VERSION,
                         "semantic_ir": B.SEMANTIC_IR_VERSION, "semantic_identity": B.SEMANTIC_IDENTITY_VERSION},
            "generator": {"analyzer": B.ANALYZER},
            "module": {
                "name": self.sem["module"]["name"], "ip": self.sem["module"]["ip"],
                "module_id": self.sem["module"]["module_id"], "semantic_id": self.sem["module"]["id"],
                "source": dict(self.sem["module"]["source"]),
                "semantic_ir": {"path": self.semantic_path, "sha256": self.semantic_sha256,
                                "schema_version": B.SEMANTIC_IR_VERSION},
                "loc": self.sem["module"]["loc"],
            },
        }
        for k in B.SECTIONS:
            doc[k] = sorted(self.out[k], key=B.loc_key)
        doc["counts"] = counts(doc)
        return doc

    # -------------------------------------------------------------- per process
    def _process(self, p):
        s = self.s
        pid = p["id"]
        kind = p["kind"]
        own = sorted((a for a in self.sem["assignments"] if a["process"] == pid), key=B.loc_key)
        akinds = sorted({a["kind"] for a in own})
        body = p["body"]
        events = p.get("events", [])
        edges = [(i, e) for i, e in enumerate(events) if e.get("edge") in ("posedge", "negedge", "edge")]
        levels = [(i, e) for i, e in enumerate(events) if e.get("edge") == "level"]
        stmt_ids = {sid for sid, owner in s.stmt_owner.items() if owner == pid}
        opaque = [sid for sid in stmt_ids if s.stmts[sid]["stmt"] == "opaque"]
        timing = [sid for sid in stmt_ids if s.stmts[sid]["stmt"] == "timing"]
        scope = {pid} | stmt_ids | {a["id"] for a in own}
        evidence = []
        ev_refs = [e["expr"]["id"] for _, e in edges + levels if isinstance(e.get("expr"), dict) and e["expr"].get("op") == "ref"]

        # ---------------------------------------------------- keyword / events
        evidence.append(_ev({"always_ff": "keyword_always_ff", "always_comb": "keyword_always_comb",
                             "always_latch": "keyword_always_latch", "always": "keyword_always",
                             "initial": "keyword_initial", "final": "keyword_final"}[kind], pid))
        if edges:
            evidence.append(_ev("edge_event", *[e["expr"].get("id") for _, e in edges if isinstance(e.get("expr"), dict)]))
        if levels:
            evidence.append(_ev("level_event", *[e["expr"].get("id") for _, e in levels if isinstance(e.get("expr"), dict)]))
        if p.get("sensitivity") == "implicit":
            evidence.append(_ev("implicit_sensitivity", pid))
        if p.get("sensitivity") == "none" and kind == "always":
            evidence.append(_ev("no_event_control", pid))
        if timing:
            evidence.append(_ev("procedural_timing", *timing))
        if opaque:
            evidence.append(_ev("opaque_statement", *opaque))
        if not own:
            evidence.append(_ev("no_assignments", pid))
        elif akinds == ["nonblocking"]:
            evidence.append(_ev("nonblocking_assignments", *[a["id"] for a in own]))
        elif "nonblocking" in akinds:
            evidence.append(_ev("mixed_assignment_kinds", *[a["id"] for a in own]))
        else:
            evidence.append(_ev("blocking_assignments", *[a["id"] for a in own]))

        targets = sorted({w for a in own for w in a["writes"] if w in s.decl})

        # ---------------------------------------------------- role
        role, conf = "unknown", "unknown"
        clocks, resets, reset_paths = [], [], set()
        if kind in ("initial", "final"):
            role, conf = "initialization", "high"
        elif edges and levels:
            role = "ambiguous"
            evidence.append(_ev("mixed_edge_level_events", *ev_refs))
        elif kind == "always_ff" and not edges:
            role = "ambiguous"
            evidence.append(_ev("keyword_event_conflict", pid))
        elif kind in ("always_comb", "always_latch") and edges:
            role = "ambiguous"
            evidence.append(_ev("keyword_event_conflict", pid))
        elif edges:
            clocks, resets, reset_paths, ok = self._clock_reset(p, edges, scope)
            if not ok:
                role = "ambiguous"
            elif kind == "always_ff":
                role, conf = "sequential", ("high" if akinds == ["nonblocking"] else "medium")
            else:
                role, conf = "sequential", ("medium" if akinds == ["nonblocking"] else "low")
        elif kind == "always_latch":
            role, conf = "latch", "high"
        elif kind == "always_comb":
            role, conf = "combinational", "high"
        elif kind == "always" and (p.get("sensitivity") == "implicit" or levels):
            if levels and not self._sensitivity_complete(p, levels, scope, targets):
                role, conf = "generic", "low"
                evidence.append(_ev("incomplete_sensitivity", *ev_refs))
            else:
                if levels:
                    evidence.append(_ev("complete_sensitivity", *ev_refs))
                role, conf = "combinational", "medium"
        elif kind == "always":
            role, conf = "generic", ("low" if timing else "unknown")
        if opaque and role not in ("unknown", "ambiguous"):
            conf = _lower(conf)
        if role in ("unknown", "ambiguous"):
            conf = "unknown"

        rec = {
            "id": self._id("process", pid), "process": pid, "kind": kind, "sensitivity": p.get("sensitivity"),
            "role": role, "confidence": conf, "clocks": [], "resets": [], "registers": [], "enables": [],
            "holds": [], "assignments": [a["id"] for a in own],
            "conditions": sorted(c for c in stmt_ids if s.stmts[c]["stmt"] == "if"),
            "cases": sorted(c for c in stmt_ids if s.stmts[c]["stmt"] == "case"),
            "registered_targets": [], "combinational_targets": [], "latch_targets": [],
            "loc": p["loc"],
        }

        # ---------------------------------------------------- read/write summary (section 22)
        reads = sorted({r["target"] for r in self.sem["references"]
                        if r["source"] in scope and r["usage"] == "read" and r["target"] in s.decl})
        cond_reads = sorted({r["target"] for r in self.sem["references"]
                             if r["source"] in stmt_ids and r["usage"] == "read" and r["target"] in s.decl})
        rec.update(reads=reads, writes=targets, conditional_reads=cond_reads,
                   conditional_writes=sorted({w for a in own if a["guards"] for w in a["writes"] if w in s.decl}))

        # ---------------------------------------------------- sequential: clocks, resets, registers
        if role == "sequential":
            for c in clocks:
                c["process"] = rec["id"]
                rec["clocks"].append(c["id"])
                self.out["clocks"].append(c)
            for r in resets:
                r["process"] = rec["id"]
                rec["resets"].append(r["id"])
                self.out["resets"].append(r)
            for t in targets:
                self._register(rec, p, t, own, clocks, resets, reset_paths, conf)
            rec["registered_targets"] = targets
        elif role in ("combinational", "latch"):
            comp = self._combinational(rec, p, targets, own, kind)
            if role == "combinational" and kind == "always":
                if any(c == "incomplete" for c in comp.values()):
                    role, conf = "latch", "medium"
                elif any(c in ("conditional", "ambiguous") for c in comp.values()):
                    conf = "low"
            elif role == "combinational" and kind == "always_comb" and any(c != "complete" for c in comp.values()):
                conf = "medium"
            if opaque:
                conf = _lower(conf)
            rec["role"], rec["confidence"] = role, conf
        rec["evidence"] = evidence
        self.out["processes"].append(rec)

    def _sensitivity_complete(self, p, levels, scope, targets):
        listed = {e["expr"].get("target") for _, e in levels if isinstance(e.get("expr"), dict)
                  and e["expr"].get("op") == "ref"}
        need = {r["target"] for r in self.sem["references"]
                if r["source"] in scope and r["source"] != p["id"] and r["usage"] == "read"
                and r["target"] in self.s.decl and r["target"] not in targets}
        return need <= listed

    # -------------------------------------------------------------- clocks / resets
    def _event_signal(self, e):
        x = e.get("expr")
        if isinstance(x, dict) and x.get("op") == "ref" and x.get("ref_kind") in _SIGNAL_KINDS and x.get("target"):
            return x["target"], x["id"], True
        if isinstance(x, dict) and x.get("op") in ("index", "part_select") and isinstance(x.get("base"), dict) \
                and x["base"].get("op") == "ref" and x["base"].get("target") in self.s.decl:
            return x["base"]["target"], x["base"]["id"], False
        return None, None, False

    def _read_in_body(self, sig, scope, pid):
        return sorted(r["id"] for r in self.sem["references"]
                      if r["target"] == sig and r["source"] in scope and r["source"] != pid)

    def _branch_assignments(self, st):
        out, stack = [], [st]
        while stack:
            x = stack.pop()
            if not isinstance(x, dict):
                continue
            if x.get("stmt") == "assign":
                out.append(self.s.assign[x["assignment"]])
            for key in ("then", "else", "body"):
                v = x.get(key)
                if isinstance(v, dict):
                    stack.append(v)
                elif isinstance(v, list):
                    stack.extend(v)
            if x.get("stmt") == "case":
                stack.extend(it.get("body") for it in x.get("items", []))
                if x.get("default"):
                    stack.append(x["default"].get("body"))
        return sorted(out, key=B.loc_key)

    def _clock_reset(self, p, edges, scope):
        """Clock and reset records for an edge-triggered process; ok=False when ambiguous."""
        pid = p["id"]
        ev_sig = {}
        for i, e in edges:
            sig, rid, simple = self._event_signal(e)
            if sig is None:
                return [], [], set(), False
            ev_sig[sig] = (i, e, rid, simple)
        resets, reset_paths, chain_sigs = [], set(), []
        st = top_if(p["body"])
        rank = 0
        # ---- asynchronous: leading if / else-if chain testing event signals
        while st is not None and len(edges) >= 2:
            t = signal_test(st["cond"], self.s.decl)
            if not t or t[0] not in ev_sig or t[0] in chain_sigs:
                break
            sig, pol, tref = t
            i, e, rid, _ = ev_sig[sig]
            chain_sigs.append(sig)
            assigns = self._branch_assignments(st["then"])
            const = bool(assigns) and all(is_constant(a.get("value")) for a in assigns)
            match = (pol == "active_low" and e["edge"] == "negedge") or (pol == "active_high" and e["edge"] == "posedge")
            ev = [_ev("reset_in_event_list", rid), _ev("reset_tested_first", st["id"], tref),
                  _ev("reset_branch_constant" if const else "reset_branch_not_constant", *[a["id"] for a in assigns]),
                  _ev("edge_polarity_match" if match else "edge_polarity_mismatch", rid, tref)] + self._name_hint(sig)
            resets.append({
                "id": self._id("reset", pid, sig), "signal": sig, "name": self.s.name(sig), "kind": "async",
                "polarity": pol, "edge": e["edge"], "status": "confirmed" if (const and match) else "ambiguous",
                "condition": st["id"], "branch": "then", "priority": rank, "event": i,
                "targets": [{"assignment": a["id"], "signal": w, "constant": is_constant(a.get("value"))}
                            for a in assigns for w in a["writes"] if w in self.s.decl],
                "evidence": ev, "loc": st["loc"], "semantic": sorted({st["id"], rid, tref}),
            })
            reset_paths.add((st["id"], "then", None))
            rank += 1
            nxt = st.get("else")
            st = nxt if isinstance(nxt, dict) and nxt.get("stmt") == "if" else (top_if([nxt]) if nxt else None)
        clock_sigs = [s_ for s_ in ev_sig if s_ not in chain_sigs]
        clocks = []
        for sig in clock_sigs:
            i, e, rid, simple = ev_sig[sig]
            read = self._read_in_body(sig, scope, pid)
            if len(clock_sigs) != 1:
                status = "ambiguous"
            else:
                status = "confirmed" if (not read and simple) else "candidate"
            ev = [_ev("edge_event", rid), _ev("event_signal_read_in_body" if read else "event_signal_not_read", rid, *read)]
            if not simple:
                ev.append(_ev("event_expression_not_a_signal", rid))
            clocks.append({
                "id": self._id("clock", pid, sig), "signal": sig, "name": self.s.name(sig), "edge": e["edge"],
                "event": i, "status": status, "evidence": ev + self._name_hint(sig),
                "loc": self.s.ref_loc(rid), "semantic": [rid],
            })
        if len(clock_sigs) != 1:
            return clocks, resets, reset_paths, False
        # ---- synchronous reset candidate: leading if on a non-clock 1-bit signal, constant branch, else present
        if not resets:
            st = top_if(p["body"])
            t = signal_test(st["cond"], self.s.decl) if st else None
            if t and t[0] not in ev_sig and st.get("else") is not None:
                sig, pol, tref = t
                assigns = self._branch_assignments(st["then"])
                if assigns and all(is_constant(a.get("value")) for a in assigns):
                    resets.append({
                        "id": self._id("reset", pid, sig), "signal": sig, "name": self.s.name(sig), "kind": "sync",
                        "polarity": pol, "edge": None, "status": "candidate", "condition": st["id"],
                        "branch": "then", "priority": 0, "event": None,
                        "targets": [{"assignment": a["id"], "signal": w, "constant": True}
                                    for a in assigns for w in a["writes"] if w in self.s.decl],
                        "evidence": [_ev("reset_not_in_event_list", tref), _ev("reset_tested_first", st["id"], tref),
                                     _ev("reset_branch_constant", *[a["id"] for a in assigns]),
                                     _ev("else_branch_present", st["else"].get("id"))] + self._name_hint(sig),
                        "loc": st["loc"], "semantic": sorted({st["id"], tref}),
                    })
                    reset_paths.add((st["id"], "then", None))
        return clocks, resets, reset_paths, True

    # -------------------------------------------------------------- registers
    def _register(self, prec, p, t, own, clocks, resets, reset_paths, pconf):
        s = self.s
        pid = p["id"]
        lv = []
        for st in p["body"]:
            lv += leaves(st, t, s, [], None, reset_paths)
        mine = [a for a in own if t in a["writes"]]
        reg_id = self._id("register", pid, t)
        reset_ids = [r["id"] for r in resets if any(x["signal"] == t for x in r["targets"])]
        reset_keys = reset_paths

        def plain(guards):
            return [g for g in guards if _guard_key(g) not in reset_keys]

        # assignments in source order, override relation (later assignment whose guards prefix the earlier one)
        arecs = []
        for n, a in enumerate(mine):
            over = [b["id"] for b in mine[n + 1:] if b["guards"] == a["guards"][:len(b["guards"])] and whole_write(b, t)]
            arecs.append({"assignment": a["id"], "order": n, "kind": a["kind"], "guards": a["guards"],
                          "value": value_kind(a, t), "overridden_by": over})
        updates = [lf for lf in lv if lf["kind"] == "update"]
        holds = [lf for lf in lv if lf["kind"] in ("hold_explicit", "hold_implicit")]
        region = None
        rif = [r for r in resets]
        # coverage of the normal-update region (outside reset branches)
        if rif:
            last = s.stmts.get(rif[-1]["condition"])
            region = cover(last.get("else"), t, s) if last else UNKNOWN
        else:
            region = cover_body(p["body"], t, s)
        hk = {lf["kind"] for lf in holds}
        if region == UNKNOWN:
            hold = "ambiguous"
        elif hk == {"hold_explicit"}:
            hold = "explicit"
        elif hk == {"hold_implicit"}:
            hold = "implicit"
        elif hk:
            hold = "mixed"
        else:
            hold = "none"
        classes = set()
        for lf in updates:
            g = plain(lf["guards"])
            classes.add("case" if any(x["branch"] in ("item", "default") for x in g) else
                        ("conditional" if g else "unconditional"))
        if not updates:
            update = "reset_only" if any(lf["kind"] == "reset" for lf in lv) else "ambiguous"
        else:
            update = classes.pop() if len(classes) == 1 else "mixed"
        if region == UNKNOWN and update not in ("reset_only",):
            update = "ambiguous" if not updates else update

        evidence = []
        kinds = {a["kind"] for a in mine}
        if kinds == {"nonblocking"}:
            evidence.append(_ev("nonblocking_update", *[a["id"] for a in mine]))
        else:
            evidence.append(_ev("blocking_update", *[a["id"] for a in mine if a["kind"] != "nonblocking"]))
        if hold in ("explicit", "mixed"):
            evidence.append(_ev("self_assignment", *[lf["assignment"] for lf in holds if lf["kind"] == "hold_explicit"]))
        if hold in ("implicit", "mixed"):
            evidence.append(_ev("missing_branch", *[lf["guards"][-1]["statement"] for lf in holds
                                                     if lf["kind"] == "hold_implicit"]))
        evidence.append(_ev({"unconditional": "unconditional_update", "conditional": "guarded_update",
                             "case": "case_update", "mixed": "guarded_update", "reset_only": "guarded_update",
                             "ambiguous": "ambiguous_assignment"}[update], *[lf["assignment"] for lf in updates]))
        conf = pconf if kinds == {"nonblocking"} else _lower(pconf)
        if hold == "ambiguous":
            conf = _lower(conf)

        # priority leaves (criteria sections 15 / 16)
        priority = []
        for rank, lf in enumerate(lv):
            item = {"rank": rank, "kind": lf["kind"], "assignment": lf["assignment"], "guards": lf["guards"]}
            if lf.get("default"):
                item["default"] = True
            priority.append(item)

        # holds
        hold_ids = []
        for lf in holds:
            q = "|".join(f"{g['statement']}:{g['branch']}:{g.get('item', '')}" for g in lf["guards"]) + "|" + lf["kind"]
            anchor = lf["guards"][-1]["statement"] if lf["guards"] else (lf["assignment"] or pid)
            hid = self._id("hold", f"{pid}|{t}", q)
            hold_ids.append(hid)
            self.out["holds"].append({
                "id": hid, "register": reg_id, "signal": t, "kind": "explicit" if lf["kind"] == "hold_explicit" else "implicit",
                "assignment": lf["assignment"], "guards": lf["guards"], "default": bool(lf.get("default")),
                "loc": self._loc_of(lf["assignment"]) if lf["assignment"] else self._loc_of(anchor),
                "semantic": sorted({x for x in [lf["assignment"], anchor] if x}),
            })
        # next values
        nv_ids = []
        for lf in updates:
            a = s.assign[lf["assignment"]]
            nid = self._id("next_value", lf["assignment"], t)
            nv_ids.append(nid)
            self.out["next_values"].append({
                "id": nid, "register": reg_id, "signal": t, "assignment": a["id"], "kind": a["kind"],
                "guards": plain(lf["guards"]), "value": lf["value"],
                "value_references": ref_ids(a.get("value")), "loc": a["loc"], "semantic": [a["id"]],
            })
        # enables: an if with an update-only branch and a hold-only branch
        en_ids = []
        conds = sorted({g["statement"] for lf in lv for g in lf["guards"]
                        if g["branch"] in ("then", "else") and _guard_key(g) not in reset_keys})
        for sid in conds:
            br = {}
            for lf in lv:
                g = next((x for x in lf["guards"] if x["statement"] == sid), None)
                if g:
                    br.setdefault(g["branch"], set()).add(lf["kind"])
            up = [b for b, k_ in br.items() if k_ == {"update"}]
            ho = [b for b, k_ in br.items() if k_ and k_ <= {"hold_explicit", "hold_implicit"}]
            if len(up) == 1 and len(ho) == 1:
                hkinds = br[ho[0]]
                eid = self._id("enable", sid, t)
                en_ids.append(eid)
                cond = s.conditions.get(sid, {})
                self.out["enables"].append({
                    "id": eid, "register": reg_id, "signal": t, "condition": sid,
                    "update_branch": up[0], "hold_branch": ho[0],
                    "hold": "explicit" if hkinds == {"hold_explicit"} else ("implicit" if hkinds == {"hold_implicit"} else "mixed"),
                    "predicate_references": cond.get("predicate_references", []),
                    "loc": s.stmts[sid]["loc"], "semantic": [sid],
                })
        d = s.decl[t]
        self.out["registers"].append({
            "id": reg_id, "signal": t, "name": d["name"], "width": d.get("width"), "process": prec["id"],
            "candidate": "register_candidate", "confidence": conf,
            "clock": clocks[0]["id"] if len(clocks) == 1 else None, "resets": sorted(reset_ids),
            "assignment_kinds": sorted(kinds), "assignments": arecs, "update": update, "hold": hold,
            "priority": priority, "enables": sorted(en_ids), "holds": sorted(hold_ids), "next_values": sorted(nv_ids),
            "evidence": evidence, "loc": mine[0]["loc"], "semantic": sorted({t} | {a["id"] for a in mine}),
        })
        prec["registers"].append(reg_id)
        prec["enables"] += en_ids
        prec["holds"] += hold_ids
        prec["registers"].sort(), prec["enables"].sort(), prec["holds"].sort()

    # -------------------------------------------------------------- combinational / latch
    def _combinational(self, prec, p, targets, own, kind):
        s = self.s
        pid = p["id"]
        comp = {}
        for t in targets:
            c = cover_body(p["body"], t, s)
            completeness = _COMPLETENESS[c]
            lv = []
            for st in p["body"]:
                lv += leaves(st, t, s, [], None, set())
            missing = [lf["guards"] for lf in lv if lf["kind"] == "hold_implicit"]
            mine = [a for a in own if t in a["writes"]]
            if kind == "always_latch":
                latch = "explicit"
            else:
                latch = {"complete": "none", "incomplete": "inferred", "conditional": "possible",
                         "ambiguous": "ambiguous"}[completeness]
            code = {"complete": "complete_assignment", "conditional": "conditional_assignment",
                    "incomplete": "incomplete_assignment", "ambiguous": "ambiguous_assignment"}[completeness]
            ev = [_ev(code, *[a["id"] for a in mine])]
            if completeness == "conditional":
                ev.append(_ev("case_without_default", *[g[-1]["statement"] for g in missing if g]))
            if missing:
                ev.append(_ev("missing_branch", *[g[-1]["statement"] for g in missing if g]))
            cid = self._id("combinational", pid, t)
            arecs = []
            for n, a in enumerate(mine):
                over = [b["id"] for b in mine[n + 1:] if b["guards"] == a["guards"][:len(b["guards"])] and whole_write(b, t)]
                arecs.append({"assignment": a["id"], "order": n, "kind": a["kind"], "guards": a["guards"],
                              "value": value_kind(a, t), "overridden_by": over})
            self.out["combinational"].append({
                "id": cid, "process": prec["id"], "signal": t, "name": s.decl[t]["name"],
                "completeness": completeness, "latch": latch, "missing": missing, "assignments": arecs,
                "evidence": ev, "loc": mine[0]["loc"], "semantic": sorted({t} | {a["id"] for a in mine}),
            })
            if latch != "none":
                lev = [_ev("keyword_always_latch", pid)] if kind == "always_latch" else []
                self.out["latches"].append({
                    "id": self._id("latch", pid, t), "process": prec["id"], "signal": t, "name": s.decl[t]["name"],
                    "status": latch, "completeness": completeness, "combinational": cid,
                    "evidence": lev + ev, "loc": mine[0]["loc"], "semantic": sorted({t} | {a["id"] for a in mine}),
                })
            comp[t] = completeness
            if latch in ("explicit", "inferred"):
                prec["latch_targets"].append(t)
            else:
                prec["combinational_targets"].append(t)
        return comp

    # -------------------------------------------------------------- state candidates (section 11 / 34)
    def _selector_refs(self, sid):
        st = self.s.stmts.get(sid)
        if st is None:
            return set()
        rec = self.s.conditions.get(sid) or self.s.cases.get(sid) or {}
        ids = rec.get("predicate_references") or rec.get("selector_references") or []
        return {self.s.refs[i]["target"] for i in ids if i in self.s.refs}

    def _state_candidates(self, comb_targets):
        s = self.s
        nv_by_reg = {}
        for nv in self.out["next_values"]:
            nv_by_reg.setdefault(nv["register"], []).append(nv)
        for reg in sorted(self.out["registers"], key=lambda r: r["id"]):
            t = reg["signal"]
            width = reg.get("width")
            if not isinstance(width, int) or width < 1 or width > 64 or reg["update"] in ("ambiguous", "reset_only"):
                continue
            nvs = nv_by_reg.get(reg["id"], [])
            if width < 2:
                continue                                    # a 1-bit flag is not reported as a state candidate
            arith = [nv for nv in nvs if nv["value"] == "expression"
                     and any(s.refs[r]["target"] == t for r in nv["value_references"] if r in s.refs)]
            if arith:
                continue                                    # arithmetic self-feedback: counter-like, not a state candidate
            ev = [_ev("finite_width", t)]
            # (a) one process: the register selects its own constant-valued updates
            sel = sorted({g["statement"] for nv in nvs for g in nv["guards"] if t in self._selector_refs(g["statement"])})
            consts = _distinct([s.assign[nv["assignment"]]["value"] for nv in nvs if nv["value"] == "constant"])
            if sel and len(consts) >= 2:
                self._candidate(reg, None, ev + [_ev("selector_feedback", *sel),
                                                 _ev("constant_state_values", *[nv["assignment"] for nv in nvs
                                                                                if nv["value"] == "constant"])])
                continue
            # (b) two processes: next value is one combinational signal selected by the register
            srcs = set()
            for nv in nvs:
                v = s.assign[nv["assignment"]].get("value") or {}
                srcs.add(v.get("target") if v.get("op") == "ref" and v.get("ref_kind") in _SIGNAL_KINDS else None)
            if len(srcs) != 1 or None in srcs:
                continue
            n = srcs.pop()
            if n == t or n not in comb_targets:
                continue
            n_assigns = [a for a in self.sem["assignments"] if n in a["writes"] and a["process"] in comb_targets[n]]
            nsel = sorted({g["statement"] for a in n_assigns for g in a["guards"] if t in self._selector_refs(g["statement"])})
            nconst = [a for a in n_assigns if is_constant(a.get("value"))]
            if nsel and len(_distinct([a["value"] for a in nconst])) >= 2:
                self._candidate(reg, n, ev + [_ev("next_value_feedback", *[nv["assignment"] for nv in nvs]),
                                              _ev("selector_feedback", *nsel),
                                              _ev("constant_state_values", *[a["id"] for a in nconst])],
                                n_assigns=n_assigns)

    def _candidate(self, reg, n, ev, n_assigns=()):
        t = reg["signal"]
        sid = self._id("state_candidate", t)
        nvc = None
        if n is not None:
            nvc = self._id("next_value_candidate", n, t)
            self.out["candidates"].append({
                "id": nvc, "kind": "next_value_candidate", "signal": n, "name": self.s.name(n), "state": sid,
                "register": None, "next_value": None, "confidence": "medium",
                "evidence": [e for e in ev if e["code"] != "finite_width"] + self._name_hint(n),
                "loc": self.s.decl[n]["loc"], "semantic": sorted({n} | {a["id"] for a in n_assigns}),
            })
        self.out["candidates"].append({
            "id": sid, "kind": "state_candidate", "signal": t, "name": reg["name"], "state": None,
            "register": reg["id"], "next_value": nvc, "confidence": "medium",
            "evidence": ev + self._name_hint(t), "loc": reg["loc"], "semantic": sorted({t} | set(reg["semantic"])),
        })


def counts(doc: dict) -> dict:
    c = {"processes": len(doc["processes"])}
    for role in B.ROLES:
        c[f"role_{role}"] = sum(1 for p in doc["processes"] if p["role"] == role)
    for conf in B.CONFIDENCE:
        c[f"confidence_{conf}"] = sum(1 for p in doc["processes"] if p["confidence"] == conf)
    c["clocks"] = len(doc["clocks"])
    for st in B.STATUS:
        c[f"clocks_{st}"] = sum(1 for x in doc["clocks"] if x["status"] == st)
        c[f"resets_{st}"] = sum(1 for x in doc["resets"] if x["status"] == st)
    c["resets"] = len(doc["resets"])
    c["resets_async"] = sum(1 for x in doc["resets"] if x["kind"] == "async")
    c["resets_sync"] = sum(1 for x in doc["resets"] if x["kind"] == "sync")
    c["registers"] = len(doc["registers"])
    c["next_values"] = len(doc["next_values"])
    c["enables"] = len(doc["enables"])
    c["holds"] = len(doc["holds"])
    c["holds_explicit"] = sum(1 for h in doc["holds"] if h["kind"] == "explicit")
    c["holds_implicit"] = sum(1 for h in doc["holds"] if h["kind"] == "implicit")
    c["combinational_targets"] = len(doc["combinational"])
    for comp in B.COMPLETENESS:
        c[f"combinational_{comp}"] = sum(1 for x in doc["combinational"] if x["completeness"] == comp)
    c["latches"] = len(doc["latches"])
    for st in B.LATCH_STATUS:
        if st != "none":
            c[f"latches_{st}"] = sum(1 for x in doc["latches"] if x["status"] == st)
    c["state_candidates"] = sum(1 for x in doc["candidates"] if x["kind"] == "state_candidate")
    c["next_value_candidates"] = sum(1 for x in doc["candidates"] if x["kind"] == "next_value_candidate")
    return c


# =============================================================================
# corpus
# =============================================================================

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def analyze(sem: dict, semantic_path: str, semantic_sha256: str) -> dict:
    return _Analysis(sem, semantic_path, semantic_sha256).run()


def canonical_modules(data_root) -> list:
    from scripts.core.paths import ForgeDataPaths, iter_module_yamls

    data = ForgeDataPaths.from_root(data_root)
    return sorted({(p.parent.parent.name, p.stem) for p in iter_module_yamls(data.normalized_ir)})


def semantic_rel(ip, module) -> str:
    from scripts.semantic_ir import model as SM

    return f"{SM.OUTPUT_DIR}/{ip}/{module}.json"


def behavior_rel(ip, module) -> str:
    return f"{B.OUTPUT_DIR}/{ip}/{module}.json"


def build(data_root, ip, module) -> dict:
    root = Path(os.path.abspath(data_root))
    rel = semantic_rel(ip, module)
    path = root / rel
    if not path.is_file():
        raise AnalysisError(f"missing Semantic IR input {rel}")
    raw = path.read_bytes()
    try:
        sem = json.loads(raw)
    except ValueError as exc:
        raise AnalysisError(f"{rel}: invalid JSON ({exc})") from exc
    m = sem.get("module") or {}
    if (m.get("ip"), m.get("name")) != (ip, module):
        raise AnalysisError(f"{rel}: Semantic IR describes {m.get('ip')}/{m.get('name')}")
    return analyze(sem, rel, sha256_bytes(raw))


def write_all(data_root) -> dict:
    """Write Behavioral Semantics v1 for every canonical module (fail closed)."""
    from scripts.core.paths import find_absolute_paths

    root = Path(os.path.abspath(data_root))
    written = 0
    for ip, module in canonical_modules(root):
        doc = build(root, ip, module)
        text = B.dumps(doc)
        if find_absolute_paths(text):
            raise AnalysisError(f"{ip}/{module}: absolute path in behavioral output")
        out = root / behavior_rel(ip, module)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written += 1
    return {"documents": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-009 Behavioral Semantics v1 analyzer")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--write", action="store_true", help="(re)generate normalized/behavior/v1 from Semantic IR v2")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    if not args.write:
        parser.error("nothing to do (use --write; validate with scripts/behavior/validator.py)")
    try:
        res = write_all(args.data_root)
    except AnalysisError as exc:
        print(f"[STOP] behavioral analysis refused: {exc}")
        return 1
    print(f"[INFO] wrote {res['documents']} Behavioral Semantics v1 documents to {B.OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
