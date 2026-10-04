#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : analyzer.py
# Description : Semantic IR v2 + Behavioral Semantics v1 + Structural Analysis v1 to FSM Analysis v1 (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM interpretation over canonical upstream evidence (KF-DQ-011).

``analyze(sem, ..., st, ...)`` interprets one module;
``write_all(data_root)`` does it for every canonical module.  Only persisted
Semantic IR v2, Behavioral Semantics v1 and Structural Analysis v1 JSON is
read; no RTL parsing, and the legacy parser-integrated FSM path is not used.

Identification (implementation plan section 3, Step B review):

* ``R`` - a behavioral register of a sequential process; ``N`` - ``R`` itself
  (one-process) or the combinational signal in ``R <= N`` (two-process);
* rule A - behavioral ``state_candidate``; rule B - a next-value assignment
  guarded by a predicate over ``R``;
* C - at least two distinct resolved state values across reset and functional
  state assignments (three-valued: unknown is never false);
* L - Structural Analysis control dependency ``R -> N`` and data dependency
  ``N -> R`` (two-process) or control ``R -> R`` (one-process);
* confirmed = (A or B) and C and L; candidate = (A or B) and L and not C;
  ambiguous / unsupported on conflicting or unsupported evidence; registers
  with arithmetic self-feedback, no predicate over themselves or no closed
  loop are recorded in ``rejected`` with a machine-readable reason.

Names never contribute to status (``name_hint`` is descriptive evidence).
There is no minimum register width.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from scripts.fsm import model as F
from scripts.structural import query as SQ

_SIGNAL_KINDS = ("port", "signal")


class AnalysisError(RuntimeError):
    """Upstream input missing, unsupported or inconsistent (fail closed)."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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


def ref_targets(e) -> set:
    out, stack = set(), [e]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("op") == "ref":
                out.add(x.get("target"))
            else:
                stack.extend(_children(x))
    return out


def has_call(e, system=False) -> bool:
    stack = [e]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("op") == "call" and bool(x.get("system")) == system:
                return True
            if x.get("op") == "ref" and x.get("ref_kind") == "hierarchical":
                return True
            stack.extend(_children(x))
    return False


_BIN = {"==": "==", "!=": "!=", "===": "==", "!==": "!="}


def render(e) -> str:
    """Deterministic human-readable rendering of a Semantic IR expression (never identity)."""
    if not isinstance(e, dict):
        return "?"
    op = e.get("op")
    if op == "ref":
        return str(e.get("name"))
    if op == "literal":
        return str(e.get("text"))
    if op == "unary":
        return f"{e.get('operator')}{render(e.get('operand'))}"
    if op == "binary":
        return f"({render(e.get('left'))} {e.get('operator')} {render(e.get('right'))})"
    if op == "ternary":
        return f"({render(e.get('cond'))} ? {render(e.get('then'))} : {render(e.get('else'))})"
    if op == "concat":
        return "{" + ", ".join(render(i) for i in e.get("items", [])) + "}"
    if op == "replicate":
        return "{" + render(e.get("count")) + "{" + ", ".join(render(i) for i in e.get("items", [])) + "}}"
    if op == "index":
        return f"{render(e.get('base'))}[{render(e.get('index'))}]"
    if op == "part_select":
        return f"{render(e.get('base'))}[{render(e.get('left'))}:{render(e.get('right'))}]"
    if op == "member":
        return f"{render(e.get('base'))}.{e.get('member')}"
    if op == "call":
        return f"{e.get('name')}(" + ", ".join(render(a) for a in e.get("args", [])) + ")"
    if op == "cast":
        return f"{e.get('type')}'({render(e.get('operand'))})"
    return str(e.get("text") or op)


# =============================================================================
# input index
# =============================================================================

class _In:
    def __init__(self, sem, beh, st, sem_sha, beh_sha):
        if not isinstance(sem, dict) or sem.get("schema") != {"name": "kritva-forge-semantic-ir", "version": F.SEMANTIC_IR_VERSION} \
                or (sem.get("versions") or {}).get("identity") != F.SEMANTIC_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Semantic IR schema {sem.get('schema') if isinstance(sem, dict) else sem!r}")
        if not isinstance(beh, dict) or beh.get("schema") != {"name": "kritva-forge-behavioral-semantics", "version": F.BEHAVIOR_VERSION} \
                or (beh.get("versions") or {}).get("identity") != F.BEHAVIOR_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Behavioral Semantics schema {beh.get('schema') if isinstance(beh, dict) else beh!r}")
        if not isinstance(st, dict) or st.get("schema") != {"name": "kritva-forge-structural-analysis", "version": F.STRUCTURAL_VERSION} \
                or (st.get("versions") or {}).get("identity") != F.STRUCTURAL_IDENTITY_VERSION:
            raise AnalysisError(f"unsupported Structural Analysis schema {st.get('schema') if isinstance(st, dict) else st!r}")
        sm, bm, tm = sem.get("module") or {}, beh.get("module") or {}, st.get("module") or {}
        if (bm.get("semantic_ir") or {}).get("sha256") != sem_sha:
            raise AnalysisError("Behavioral Semantics was derived from a different Semantic IR revision")
        if (tm.get("semantic_ir") or {}).get("sha256") != sem_sha or (tm.get("behavior") or {}).get("sha256") != beh_sha:
            raise AnalysisError("Structural Analysis was derived from a different Semantic IR / Behavioral Semantics revision")
        if not (sm.get("module_id") == bm.get("module_id") == tm.get("module_id")):
            raise AnalysisError("upstream documents describe different modules")
        self.sem, self.beh, self.st = sem, beh, st
        self.decl = {d["id"]: d for d in sem["ports"] + sem["signals"]}
        self.ports = {p["id"]: p for p in sem["ports"]}
        self.assign = {a["id"]: a for a in sem["assignments"]}
        self.params = {p["id"]: p for p in sem["parameters"]}
        self.enum, self.enum_val, self.enum_implicit = {}, {}, set()
        self.typedefs = {}
        self.anon_enum = {}                      # member id -> anonymous enum typedef
        for t in sem.get("typedefs", []):
            if t.get("name") is not None:
                self.typedefs[t.get("name")] = t
            if t.get("kind") != "enum":
                continue
            prev = -1
            for m in t.get("members", []):
                self.enum[m["id"]] = (m, t)
                if t.get("name") is None:
                    self.anon_enum[m["id"]] = t
                v = m.get("value")
                if v is None:                    # no initializer: IEEE 1800 6.19 - first 0, else previous + 1
                    val = prev + 1 if prev is not None else None
                    self.enum_implicit.add(m["id"])
                elif isinstance(v, dict) and v.get("op") == "literal" and isinstance(v.get("value"), int):
                    val = v["value"]
                else:
                    val = None
                self.enum_val[m["id"]] = val
                prev = val
        self.ext = {e.get("id"): e for e in sem.get("external", []) if isinstance(e, dict)}
        self.stmt, self.stmt_proc = {}, {}
        for p in sem["processes"]:
            for s in p["body"]:
                self._walk(s, p["id"])
        self.cond = {c["id"]: c for c in sem["conditions"]}
        self.case = {c["id"]: c for c in sem["cases"]}
        self.bproc = {p["id"]: p for p in beh["processes"]}
        self.bproc_by_sem = {p["process"]: p for p in beh["processes"]}
        self.state_cand = {c["register"]: c for c in beh["candidates"] if c["kind"] == "state_candidate"}
        self.nv_cand = {c["signal"]: c for c in beh["candidates"] if c["kind"] == "next_value_candidate"}
        self.bhold = {h["id"]: h for h in beh["holds"]}
        self.breset = {r["id"]: r for r in beh["resets"]}
        self.bclock = {c["id"]: c for c in beh["clocks"]}
        self.benable = {e["id"]: e for e in beh["enables"]}
        self.comb = {c["signal"]: c for c in beh["combinational"]}
        self.reset_conditions = {r["condition"] for r in beh["resets"] if r.get("condition")}
        self.pred = {p["statement"]: p for p in st["predicates"]}
        self.sreg = {r["register"]: r for r in st["registers"]}
        self.ssig = {s["signal"]: s for s in st["signals"]}
        self.multi = {m["signal"] for m in st["multiple_drivers"]}
        self.dep = defaultdict(list)
        for d in st["dependencies"]:
            self.dep[(d["source"], d["target"])].append(d)

    def _walk(self, s, pid):
        if not isinstance(s, dict) or "stmt" not in s:
            return
        if s["stmt"] != "assign":
            self.stmt[s["id"]] = s
            self.stmt_proc[s["id"]] = pid
        for key in ("then", "else"):
            if isinstance(s.get(key), dict):
                self._walk(s[key], pid)
        body = s.get("body")
        for x in body if isinstance(body, list) else [body]:
            self._walk(x, pid)
        if s["stmt"] == "case":
            for it in s.get("items", []):
                self._walk(it.get("body"), pid)
            if s.get("default"):
                self._walk(s["default"].get("body"), pid)

    def width(self, sid):
        d = self.decl.get(sid) or {}
        if d.get("type") == "enum":              # anonymous enum: the Semantic IR width is not the enum width
            return None
        if isinstance(d.get("width"), int):
            return d["width"]
        t = self.typedefs.get(d.get("type"))
        if t and t.get("kind") == "enum":
            ws = [m.get("value", {}).get("width") for m in t.get("members", []) if isinstance(m.get("value"), dict)]
            ws = [w for w in ws if isinstance(w, int)]
            if ws:
                return max(ws)
        return None

    def constant(self, e):
        """(value, kind, name, ref) for a constant expression; ``None`` when not a constant.

        ``value`` is ``None`` when the expression is a constant whose value is unresolved.
        """
        if not isinstance(e, dict):
            return None
        op = e.get("op")
        if op == "literal":
            v = e.get("value")
            return (v if isinstance(v, int) else None, "literal", None, None)
        if op == "ref":
            rk, tgt = e.get("ref_kind"), e.get("target")
            if rk == "parameter" and tgt in self.params:
                p = self.params[tgt]
                v = p.get("value")
                kind = "localparam" if p.get("kind") == "localparam" else "parameter"
                return (v if isinstance(v, int) else None, kind, p.get("name"), tgt)
            if rk == "enum_member" and tgt in self.enum:
                m, _ = self.enum[tgt]
                v = self.enum_val.get(tgt)
                return (v if isinstance(v, int) else None, "enum_member", m.get("name"), tgt)
            if rk in ("parameter", "enum_member", "external", "unresolved"):   # a name that does not resolve
                return (None, "parameter" if rk != "enum_member" else "enum_member", e.get("name"), tgt)
            return None
        return None


# =============================================================================
# per-register analysis
# =============================================================================

class _Analysis:
    def __init__(self, x: _In):
        self.x = x
        self.couplings = []
        self.fsms, self.rejected, self.notes = [], [], {k: 0 for k in F.NOTES}

    # ------------------------------------------------------------------ guard entries
    def _test_values(self, cond, R, width):
        """Source values selected by an if-condition over R (then-branch); ``None`` if not determinable."""
        if not isinstance(cond, dict):
            return None
        op = cond.get("op")
        if op == "ref" and cond.get("target") == R and width == 1:
            return {1}
        if op == "unary" and cond.get("operator") in ("!", "~") and isinstance(cond.get("operand"), dict) \
                and cond["operand"].get("op") == "ref" and cond["operand"].get("target") == R and width == 1:
            return {0}
        if op == "binary" and cond.get("operator") in _BIN:
            l, r = cond.get("left"), cond.get("right")
            for a, b in ((l, r), (r, l)):
                if isinstance(a, dict) and a.get("op") == "ref" and a.get("target") == R:
                    c = self.x.constant(b)
                    if c is None or c[0] is None:
                        return None
                    if _BIN[cond["operator"]] == "==":
                        return {c[0]}
                    return ("not", {c[0]})
        return None

    def _entry(self, g, R, width):
        """GuardEntry for a Semantic IR guard ``{statement, branch, item?}``."""
        x = self.x
        sid = g["statement"]
        s = x.stmt.get(sid) or {}
        pred = x.pred.get(sid)
        e = {"statement": sid, "predicate": pred["id"] if pred else None, "branch": g["branch"],
             "item": g.get("item"), "tests_state": False, "values": None, "qualifier": s.get("qualifier"),
             "role": pred["role"] if pred else "control"}
        vals = None
        if s.get("stmt") == "if":
            e["kind"] = "if"
            refs = ref_targets(s.get("cond"))
            e["tests_state"] = R in refs
            if e["tests_state"]:
                tv = self._test_values(s.get("cond"), R, width)
                if isinstance(tv, set):
                    vals = tv if g["branch"] == "then" else ("not", tv)
                elif isinstance(tv, tuple):
                    vals = ("not", tv[1]) if g["branch"] == "then" else tv[1]
            e["render"] = render(s.get("cond")) if g["branch"] == "then" else f"!{render(s.get('cond'))}"
        elif s.get("stmt") == "case":
            e["kind"] = s.get("case_kind") if s.get("case_kind") in F.GUARD_KINDS else "case"
            sel = s.get("expr")
            is_sel = isinstance(sel, dict) and sel.get("op") == "ref" and sel.get("target") == R
            labels_ref = any(R in ref_targets(ex) for it in s.get("items", []) for ex in it.get("exprs", []))
            e["tests_state"] = is_sel or R in ref_targets(sel) or labels_ref
            items = s.get("items", [])

            def item_vals(it):
                out = set()
                for ex in it.get("exprs", []):
                    c = x.constant(ex)
                    if c is None or c[0] is None:
                        return None
                    out.add(c[0])
                return out

            if is_sel and e["kind"] == "case":
                if g["branch"] == "item" and g.get("item") is not None and g["item"] < len(items):
                    vals = item_vals(items[g["item"]])
                elif g["branch"] == "default":
                    allv = [item_vals(it) for it in items]
                    vals = None if any(v is None for v in allv) else ("not", set().union(*allv) if allv else set())
            if g["branch"] == "item" and g.get("item") is not None and g["item"] < len(items):
                e["render"] = " || ".join(f"{render(sel)} == {render(ex)}" for ex in items[g["item"]].get("exprs", [])) or "item"
            else:
                e["render"] = f"default({render(sel)})"
        elif s.get("stmt") == "loop":
            e["kind"] = "loop"
            e["tests_state"] = R in ref_targets(s.get("cond"))
            e["render"] = f"loop({render(s.get('cond'))})"
        else:
            e["kind"] = "if"
            e["render"] = "?"
        e["_vals"] = vals
        return e

    @staticmethod
    def _resolve(entries, domain, complete):
        """(source value set | None, status) for a guard path."""
        tests = [e for e in entries if e["tests_state"]]
        if not tests:
            return (set(domain), "derived") if complete else (None, "unknown")
        cur, derived = None, False
        for e in tests:
            v = e["_vals"]
            if v is None:
                return None, "unknown"
            if isinstance(v, tuple):
                if not complete:
                    return None, "unknown"
                v = set(domain) - v[1]
                derived = True
            cur = set(v) if cur is None else cur & v
        return cur, ("derived" if derived else "confirmed")

    # ------------------------------------------------------------------ leaves of a next-value expression
    def _leaves(self, assign_id, value, R, N, width, path=()):
        """[(ternary guard entries, kind, value|None, expr)] - kind const|hold|unknown|feedback|unsupported."""
        x = self.x
        if isinstance(value, dict) and value.get("op") == "ternary":
            cond = value.get("cond")
            out = []
            for br, sub in (("then", value.get("then")), ("else", value.get("else"))):
                tv = self._test_values(cond, R, width) if R in ref_targets(cond) else None
                vals = None
                if isinstance(tv, set):
                    vals = tv if br == "then" else ("not", tv)
                elif isinstance(tv, tuple):
                    vals = ("not", tv[1]) if br == "then" else tv[1]
                e = {"statement": assign_id, "predicate": None, "kind": "ternary", "branch": br, "item": None,
                     "tests_state": R in ref_targets(cond), "values": None, "qualifier": None, "role": "control",
                     "render": render(cond) if br == "then" else f"!{render(cond)}", "_vals": vals}
                out += self._leaves(assign_id, sub, R, N, width, path + (e,))
            return out
        if isinstance(value, dict) and value.get("op") == "ref" and value.get("target") in (R, N):
            return [(path, "hold", None, value)]
        c = x.constant(value)
        if c is not None:
            return [(path, "const" if c[0] is not None else "unresolved", c, value)]
        if has_call(value):
            return [(path, "unsupported", None, value)]
        if ref_targets(value) & {R, N}:
            return [(path, "feedback", None, value)]
        return [(path, "unknown", None, value)]

    # ------------------------------------------------------------------ main
    def run(self):
        x = self.x
        regs = sorted(x.beh["registers"], key=lambda r: r["id"])
        n_drivers = defaultdict(set)
        for a in x.sem["assignments"]:
            for w in a["writes"]:
                n_drivers[w].add(a["process"] or a["id"])
        for r in regs:
            bp = x.bproc.get(r["process"])
            if not bp or bp["role"] != "sequential":
                continue
            self._register(r, bp, n_drivers)
        self._couplings()

    def _register(self, r, bp, n_drivers):
        x = self.x
        R, rname = r["signal"], r["name"]
        width = x.width(R)
        spid = bp["process"]
        leaves_kinds = {p["assignment"]: p["kind"] for p in r["priority"] if p.get("assignment")}
        reset_assigns = [a for a, k in leaves_kinds.items() if k == "reset"]
        upd = [a for a, k in leaves_kinds.items() if k in ("update", "hold_explicit")]
        # two-process detection: every update value is one reference to the same combinational signal N
        N, nproc = R, spid
        vals = [x.assign[a].get("value") for a in upd if a in x.assign]
        tgt = {v.get("target") for v in vals if isinstance(v, dict) and v.get("op") == "ref" and v.get("ref_kind") in _SIGNAL_KINDS}
        if vals and len(tgt) == 1 and all(isinstance(v, dict) and v.get("op") == "ref" for v in vals) and R not in tgt:
            cand = next(iter(tgt))
            comb = x.comb.get(cand)
            if comb is not None:
                N = cand
                nproc = x.bproc[comb["process"]]["process"]
        two = N != R
        if two:
            na = sorted((a for a in x.sem["assignments"] if N in a["writes"] and a["process"] == nproc),
                        key=lambda a: (self._okey(a["id"], N), a["id"]))
        else:
            na = sorted((x.assign[a] for a in upd if a in x.assign), key=lambda a: (self._okey(a["id"], R, r), a["id"]))
        reset_vals = []
        for a in reset_assigns:
            c = x.constant((x.assign.get(a) or {}).get("value"))
            reset_vals.append((a, c))
        # leaves and state tests
        leaves = []
        for a in na:
            for path, kind, c, expr in self._leaves(a["id"], a.get("value"), R, N, width):
                leaves.append((a, path, kind, c, expr))
        tests = set()
        for a in na:
            for g in a.get("guards", []):
                s = x.stmt.get(g["statement"]) or {}
                refs = ref_targets(s.get("cond")) if s.get("stmt") == "if" else (
                    ref_targets(s.get("expr")) | {t for it in s.get("items", []) for ex in it.get("exprs", []) for t in ref_targets(ex)})
                if R in refs:
                    tests.add(g["statement"])
        tern_test = any(any(e["tests_state"] for e in path) for _, path, *_ in leaves)
        rule_a = r["id"] in x.state_cand
        rule_b = bool(tests) or tern_test
        resolved = {l[3][0] for l in leaves if l[2] == "const"} | {c[0] for _, c in reset_vals if c and c[0] is not None}
        unresolved = any(l[2] == "unresolved" for l in leaves) or any(c is not None and c[0] is None for _, c in reset_vals)
        hint = bool(F.NAME_HINT_RE.search(rname or ""))
        feedback = any(l[2] == "feedback" for l in leaves)
        unsupported = any(l[2] == "unsupported" for l in leaves)
        interesting = rule_a or rule_b or len(resolved) >= 2 or hint
        if not interesting:
            return
        if feedback:
            return self._reject(r, "arithmetic_feedback", hint, rule_a, rule_b, resolved)
        if not (rule_a or rule_b):
            return self._reject(r, "name_only" if hint and len(resolved) < 2 else "no_state_predicate", hint, rule_a, rule_b, resolved)
        # closed loop in Structural Analysis
        ctrl = [d for d in x.dep.get((R, N), []) if d["kind"] in ("control", "enable", "reset")
                and (d["via"] in tests or d["context"] == "ternary_condition")]
        if two:
            data = [d for d in x.dep.get((N, R), []) if d["kind"] == "data" and d["boundary"] == "sequential"]
            loop = bool(ctrl) and bool(data)
        else:
            data = []
            loop = bool(ctrl)
        if not loop:
            return self._reject(r, "no_closed_loop", hint, rule_a, rule_b, resolved)
        c_state = True if len(resolved) >= 2 else (None if unresolved else False)
        # a 1-bit register with literal values only: two distinct values are its whole domain, so
        # C carries no evidence (flag / handshake false-positive guard, AC-016); without a
        # behavioral state candidate or named state constants it stays a candidate
        trivial = (c_state is True and width == 1 and not rule_a and not self._named(leaves, reset_vals, tests))
        status = "confirmed" if c_state is True and not trivial else "candidate"
        unknowns = []
        if unsupported:
            status = "unsupported"
        elif (two and (len(n_drivers.get(N, ())) > 1 or N in x.multi)) or R in x.multi:
            status, _ = "ambiguous", unknowns.append({"kind": "multiple_driver", "refs": sorted({N, R})})
        elif r.get("update") == "ambiguous":
            status, _ = "ambiguous", unknowns.append({"kind": "ambiguous_update", "refs": [r["id"]]})
        opaque = sorted(s for s, p in x.stmt_proc.items() if p in (spid, nproc) and x.stmt[s].get("stmt") == "opaque")
        if opaque:
            unknowns.append({"kind": "opaque_statement", "refs": opaque})
            if status == "confirmed":
                status = "ambiguous"
        self._build(r, bp, R, N, two, nproc, width, na, leaves, reset_vals, tests, rule_a, rule_b, c_state,
                    status, unknowns, hint, ctrl, data, resolved, unresolved, trivial)

    def _okey(self, aid, sig, r=None):
        o = self._order(aid, sig, r)
        return (o is None, o or 0)

    def _order(self, aid, sig, r=None):
        x = self.x
        if r is not None:
            for a in r["assignments"]:
                if a["assignment"] == aid:
                    return a["order"]
        comb = x.comb.get(sig)
        if comb:
            for a in comb["assignments"]:
                if a["assignment"] == aid:
                    return a["order"]
        return None

    def _reject(self, r, reason, hint, rule_a, rule_b, resolved):
        ev = []
        if rule_a:
            ev.append(self._ev("behavior_state_candidate", [self.x.state_cand[r["id"]]["id"]]))
        if rule_b:
            ev.append(self._ev("predicate_over_register", [r["signal"]]))
        if resolved:
            ev.append(self._ev("resolved_state_values", [r["signal"]], len(resolved)))
        if hint:
            ev.append(self._ev("name_hint", [r["signal"]]))
        self.rejected.append({
            "id": F.fsm_id("rejection", r["id"]), "register": r["id"], "signal": r["signal"], "name": r["name"],
            "reason": reason, "name_hint": hint, "evidence": ev, "loc": r["loc"],
        })

    @staticmethod
    def _ev(code, refs, count=None):
        assert code in F.EVIDENCE, code
        refs = sorted({str(r) for r in refs if r})
        return {"code": code, "count": len(refs) if count is None else count, "refs": refs}

    # ------------------------------------------------------------------ FSM record
    def _named(self, leaves, reset_vals, tests) -> bool:
        """True when a state value is written or compared through a parameter / localparam / enum constant."""
        x = self.x
        if any(l[2] == "const" and l[3][1] != "literal" for l in leaves):
            return True
        if any(c and c[0] is not None and c[1] != "literal" for _, c in reset_vals):
            return True
        for sid in tests:
            st = x.stmt.get(sid) or {}
            exprs = [ex for it in st.get("items", []) for ex in it.get("exprs", [])] if st.get("stmt") == "case" else \
                [(st.get("cond") or {}).get("left"), (st.get("cond") or {}).get("right")]
            if any((x.constant(ex) or (None, "literal"))[1] != "literal" for ex in exprs):
                return True
        return False

    def _build(self, r, bp, R, N, two, nproc, width, na, leaves, reset_vals, tests, rule_a, rule_b, c_state,
               status, unknowns, hint, ctrl, data, resolved, unresolved, trivial=False):
        x = self.x
        fid = F.fsm_id("fsm", r["id"])
        # ---- state domain and constants
        consts = defaultdict(list)            # value -> [(kind, name, ref)]
        observed = set()
        for _, _, kind, c, _ in leaves:
            if kind == "const":
                consts[c[0]].append(c[1:])
                observed.add(c[0])
        for _, c in reset_vals:
            if c and c[0] is not None:
                consts[c[0]].append(c[1:])
                observed.add(c[0])
        tested_unresolved = False
        for sid in sorted(tests):
            s = x.stmt.get(sid) or {}
            exprs = []
            if s.get("stmt") == "case":
                exprs = [ex for it in s.get("items", []) for ex in it.get("exprs", [])]
            elif s.get("stmt") == "if":
                cnd = s.get("cond") or {}
                if cnd.get("op") == "binary":
                    exprs = [cnd.get("left"), cnd.get("right")]
            for ex in exprs:
                c = x.constant(ex)
                if c is None:
                    continue
                if c[0] is None:
                    tested_unresolved = True
                    continue
                consts[c[0]].append(c[1:])
                observed.add(c[0])
        rtype = (x.decl.get(R) or {}).get("type")
        tdef = x.typedefs.get(rtype)
        if rtype == "enum":                      # anonymous enum: linked through the members it is compared/assigned with
            anon = {x.anon_enum[c[2]]["id"]: x.anon_enum[c[2]] for v in sorted(consts) for c in consts[v]
                    if c[0] == "enum_member" and c[2] in x.anon_enum}
            tdef = anon[min(anon)] if len(anon) == 1 else None
            if len(anon) > 1:
                tested_unresolved = True
        if tdef and tdef.get("kind") == "enum":
            for m in tdef.get("members", []):
                v = x.enum_val.get(m["id"])
                if isinstance(v, int):
                    consts[v].append(("enum_member", m.get("name"), m.get("id")))
                else:
                    tested_unresolved = True
        complete = not unresolved and not tested_unresolved and bool(consts)
        if not complete:
            unknowns.append({"kind": "incomplete_domain", "refs": [R]})
        domain = sorted(consts)
        sid_of = {v: F.fsm_id("state", fid, str(v)) for v in domain}

        def pick(v):
            cands = sorted(set(consts[v]), key=lambda c: (["enum_member", "localparam", "parameter", "literal"].index(c[0]),
                                                          c[1] or "", c[2] or ""))
            return cands[0], sorted({c[1] for c in cands if c[1]})

        def pub(e):
            """Canonical guard entry: internal fields dropped, selected source values as state identities."""
            out = {k: v for k, v in e.items() if not k.startswith("_") and k != "render"}
            v = e["_vals"]
            if v is None or (isinstance(v, tuple) and not complete):
                out["values"] = None
            elif isinstance(v, tuple):
                out["values"] = sorted(sid_of[d] for d in domain if d not in v[1])
            else:
                out["values"] = sorted(sid_of[d] for d in v if d in sid_of)
            return out

        # ---- transitions
        trans = {}

        def add(anchor, src, dst, kind, guard, prio, assignment, tstatus, extra="", hold=None):
            key = F.fsm_id("transition", anchor, f"{src}>{dst}:{kind}:{extra}")
            if key in trans:
                return
            ents = [pub(e) for e in guard]
            trans[key] = {"id": key, "source": src, "target": dst, "kind": kind, "guard": ents,
                          "priority": prio, "assignment": assignment, "hold": hold,
                          "process": nproc if assignment else bp["process"],
                          "status": tstatus,
                          "rendered": " && ".join(e["render"] for e in guard if e.get("role") != "reset") or "1",
                          "loc": (x.assign.get(assignment) or {}).get("loc") or r["loc"]}

        rows = []                                  # (order, assignment, entries, kind, value, sources|None, status)
        for a, path, kind, c, expr in leaves:
            ents = [self._entry(g, R, width) for g in a.get("guards", [])]
            fents = [e for e in ents if e["statement"] not in x.reset_conditions] + list(path)
            guarded = len(fents) > 0
            srcs, sst = self._resolve(fents, domain, complete)
            rows.append((self._order(a["id"], N if two else R, None if two else r), a, ents + list(path), fents,
                         kind, c, srcs, sst, guarded))
        rows.sort(key=lambda t: (t[0] is None, t[0] or 0, t[1]["id"]))

        def unconditional_for(row, v):
            _, a, _, fents, kind, _, _, _, _ = row
            if kind not in ("const", "hold") or any(e["kind"] == "ternary" for e in fents):
                return False
            for e in fents:
                if not e["tests_state"]:
                    return False
                vals = e["_vals"]
                if vals is None:
                    return False
                if isinstance(vals, tuple):
                    if not complete or v in vals[1]:
                        return False
                elif v not in vals:
                    return False
            return True

        for i, row in enumerate(rows):
            order, a, ents, fents, kind, c, srcs, sst, guarded = row
            later = rows[i + 1:]
            is_default = any(e["branch"] == "default" for e in fents)
            if srcs is None:
                src_list = ["*unknown"]
            else:
                src_list = [v for v in sorted(srcs) if not any(unconditional_for(l, v) for l in later)]
                if not srcs:
                    src_list = ["*none"]
                elif not src_list:
                    continue                                 # fully overridden on every source state
            extra = ",".join(f"{e['statement']}:{e['branch']}" for e in fents if e["kind"] == "ternary")
            for v in src_list:
                src = sid_of[v] if isinstance(v, int) else v
                if kind == "const":
                    dst = sid_of[c[0]]
                    tk = "default" if is_default else "explicit"
                elif kind == "hold":
                    dst = src if isinstance(v, int) else "*unknown"
                    tk = "implicit_hold" if (two and not guarded) else "explicit_hold"
                else:
                    dst = "*unknown"
                    tk = "default" if is_default else "explicit"
                    if kind == "unresolved":
                        unknowns.append({"kind": "unresolved_constant", "refs": [a["id"]]})
                    else:
                        unknowns.append({"kind": "unknown_target", "refs": [a["id"]]})
                if v == "*unknown":
                    unknowns.append({"kind": "unknown_source", "refs": [a["id"]]})
                add(a["id"], src, dst, tk, ents, order, a["id"], sst if isinstance(v, int) or v == "*none" else "unknown", extra)
        # one-process implicit holds (behavioral hold records)
        if not two:
            for hid in r.get("holds", []):
                h = x.bhold[hid]
                if h["kind"] != "implicit":
                    continue
                ents = [self._entry(g, R, width) for g in h.get("guards", [])]
                fents = [e for e in ents if e["statement"] not in x.reset_conditions]
                srcs, sst = self._resolve(fents, domain, complete)
                for v in (sorted(srcs) if srcs is not None else ["*unknown"]):
                    # a state on which some assignment of the process always writes the register cannot hold
                    if isinstance(v, int) and any(unconditional_for(row, v) for row in rows):
                        continue
                    src = sid_of[v] if isinstance(v, int) else v
                    add(hid, src, src, "implicit_hold", ents, None, None, sst if isinstance(v, int) else "unknown", hold=hid)
        # reset transitions
        for a, c in reset_vals:
            if c and c[0] is not None:
                add(a, "*reset", sid_of[c[0]], "reset", [], 0, a, "confirmed")
        transitions = sorted(trans.values(), key=lambda t: t["id"])
        # ---- reset
        rres = [x.breset[i] for i in r.get("resets", []) if i in x.breset]
        rvals = sorted({c[0] for _, c in reset_vals if c and c[0] is not None})
        reset = {"kind": rres[0]["kind"] if rres else "none",
                 "polarity": rres[0]["polarity"] if rres else None,
                 "status": rres[0]["status"] if rres else None,
                 "reset": rres[0]["id"] if rres else None,
                 "signal": rres[0]["signal"] if rres else None,
                 "state": sid_of[rvals[0]] if len(rvals) == 1 else None,
                 "assignments": sorted(a for a, _ in reset_vals)}
        if len(rvals) > 1:
            unknowns.append({"kind": "ambiguous_reset", "refs": sorted(a for a, _ in reset_vals)})
        # ---- reachability (graph only)
        edges = defaultdict(set)
        unknown_edges = False
        for t in transitions:
            if t["source"] in sid_of.values() and t["target"] in sid_of.values():
                edges[t["source"]].add(t["target"])
            elif t["kind"] != "reset" and "*none" not in (t["source"],) and (t["source"] == "*unknown" or t["target"] == "*unknown"):
                unknown_edges = True
        start = reset["state"]
        reach = set()
        if start:
            todo = [start]
            while todo:
                n = todo.pop()
                if n in reach:
                    continue
                reach.add(n)
                todo.extend(sorted(edges[n]))
        known = bool(start) and not unknown_edges and complete
        # ---- states
        states = []
        for v in domain:
            (kind, name, ref), aliases = pick(v)
            sid = sid_of[v]
            states.append({
                "id": sid, "value": v, "width": width, "name": name, "aliases": [a for a in aliases if a != name],
                "constant": {"kind": kind, "ref": ref, "implicit": ref in x.enum_implicit},
                "declared": any(k != "literal" for k, _, _ in consts[v]), "observed": v in observed,
                "reachability": "graph_reachable" if sid in reach else ("graph_unreachable" if known else "unknown"),
                "reset": v in rvals, "loc": r["loc"],
            })
        if rtype == "enum":
            self.notes["anonymous_enum_registers"] += 1
        self.notes["implicit_enum_states"] += sum(1 for s in states if s["constant"]["implicit"])
        # ---- encoding
        kinds = {pick(v)[0][0] for v in domain}
        src = ("enum" if kinds == {"enum_member"} else "localparam" if kinds == {"localparam"} else
               "parameter" if kinds == {"parameter"} else "literal" if kinds == {"literal"} else
               "mixed" if kinds else "unknown")
        if not complete or not domain:
            enc_status, style = "unknown", "unknown"
        else:
            enc_status = "explicit" if "literal" not in kinds else "inferred"
            val_of = {sid_of[v]: v for v in domain}
            moves = [(val_of[t["source"]], val_of[t["target"]]) for t in transitions
                     if t["source"] in val_of and t["target"] in val_of and t["source"] != t["target"]]
            style = F.encoding_style(domain, width, moves)
        encoding = {"status": enc_status, "style": style, "width": width, "source": src}
        # ---- outputs
        outputs = []
        for p in sorted(x.sem["ports"], key=lambda p: p["id"]):
            if p.get("direction") not in ("output", "inout"):
                continue
            pid = p["id"]
            if pid == R:
                kindo, ss, oth = "moore", [R], []
            else:
                cone = SQ.cone(x.st, pid, "fanin")
                members = set(cone["signals"]) | set(cone["registers"])
                if R not in members and N not in members:
                    continue
                oth_regs = sorted(set(cone["registers"]) - {R})
                ins = sorted(cone["inputs"])
                ss = [R]
                oth = sorted(set(ins) | set(oth_regs))
                kindo = "mealy" if ins else ("moore" if not oth_regs else "ambiguous")
            outputs.append({"id": F.fsm_id("output", fid, pid), "signal": pid, "name": p["name"], "kind": kindo,
                            "state_sources": ss, "other_sources": oth, "loc": p["loc"]})
        # ---- actions: other targets assigned under predicates over R
        actions = {}
        for a in x.sem["assignments"]:
            if a.get("subroutine") is not None or a["process"] is None:
                continue
            tw = [w for w in a["writes"] if w in x.decl and w not in (R, N)]
            if not tw:
                continue
            ents = [self._entry(g, R, width) for g in a.get("guards", [])]
            fents = [e for e in ents if e["statement"] not in x.reset_conditions]
            if not any(e["tests_state"] for e in fents):
                continue
            srcs, _ = self._resolve(fents, domain, complete)
            bpk = x.bproc_by_sem.get(a["process"]) or {}
            for v in (sorted(srcs) if srcs else ["*unknown"]):
                stid = sid_of[v] if isinstance(v, int) else v
                for w in tw:
                    kind = "output" if (x.ports.get(w) or {}).get("direction") in ("output", "inout") else (
                        "register" if bpk.get("role") == "sequential" else "control")
                    aid = F.fsm_id("action", a["id"], f"{fid}:{stid}:{w}")
                    actions[aid] = {"id": aid, "state": stid, "signal": w, "assignment": a["id"], "kind": kind,
                                    "guard": [pub(e) for e in ents],
                                    "loc": a["loc"]}
        # ---- evidence
        ev = []
        if rule_a:
            ev.append(self._ev("behavior_state_candidate", [x.state_cand[r["id"]]["id"]]))
        if two and N in x.nv_cand:
            ev.append(self._ev("behavior_next_value_candidate", [x.nv_cand[N]["id"]]))
        if rule_b:
            ev.append(self._ev("predicate_over_register", sorted(tests) or [R]))
        if resolved:
            ev.append(self._ev("resolved_state_values", [R], len(resolved)))
        if unresolved:
            ev.append(self._ev("unresolved_state_values", [R]))
        if trivial:
            ev.append(self._ev("trivial_state_domain", [R]))
        ev.append(self._ev("closed_loop", [d["id"] for d in ctrl + data]))
        if two:
            ev.append(self._ev("two_process_next_value", [N]))
        if any(t["kind"] == "explicit_hold" for t in transitions):
            ev.append(self._ev("explicit_hold", [t["assignment"] for t in transitions if t["kind"] == "explicit_hold"]))
        if any(t["kind"] == "implicit_hold" for t in transitions):
            ev.append(self._ev("implicit_hold", [t["assignment"] or R for t in transitions if t["kind"] == "implicit_hold"]))
        if reset["state"]:
            ev.append(self._ev("reset_state", reset["assignments"]))
        if any(k != "literal" for k in kinds):
            ev.append(self._ev("named_constants", sorted({c[2] for v in domain for c in consts[v] if c[2]})))
        if hint:
            ev.append(self._ev("name_hint", [R]))
        holds = {t["kind"] for t in transitions if t["kind"] in ("explicit_hold", "implicit_hold")}
        hold = "none" if not holds else ("mixed" if len(holds) == 2 else holds.pop().split("_")[0])
        # ---- quality
        unk_tr = any(t["source"] == "*unknown" or t["target"] == "*unknown" for t in transitions)
        if status == "confirmed":
            quality = "high" if enc_status == "explicit" and reset["state"] and not unk_tr and complete else "medium"
        elif status == "candidate":
            quality = "low"
        else:
            quality = status
        clock = None
        if r.get("clock") and r["clock"] in x.bclock:
            c = x.bclock[r["clock"]]
            clock = {"clock": c["id"], "signal": c["signal"], "edge": c["edge"]}
        enables = []
        for e in r.get("enables", []):
            if e not in x.benable:
                continue
            prefs = set(x.benable[e].get("predicate_references", []))
            enables.append({"enable": e, "condition": x.benable[e]["condition"],
                            "signals": sorted({ref["target"] for ref in x.sem["references"]
                                               if ref["id"] in prefs and ref["target"] in x.decl})})
        agg = defaultdict(set)                   # one record per unknown kind, refs merged
        for u in unknowns:
            agg[u["kind"]].update(u["refs"])
        dedup = [{"kind": k, "count": len(v), "refs": sorted(v)} for k, v in agg.items()]
        self.fsms.append({
            "id": fid, "status": status, "quality": quality, "style": "two_process" if two else "one_process",
            "register": {"signal": R, "name": r["name"], "width": width, "register": r["id"],
                         "structural_register": (x.sreg.get(r["id"]) or {}).get("id"), "process": bp["process"]},
            "next_signal": {"signal": N, "name": (x.decl.get(N) or {}).get("name"), "process": nproc} if two else None,
            "clock": clock, "reset": reset, "enable": sorted(enables, key=lambda e: e["enable"]), "hold": hold,
            "encoding": encoding, "states": states, "transitions": transitions,
            "outputs": sorted(outputs, key=lambda o: o["id"]), "actions": sorted(actions.values(), key=lambda a: a["id"]),
            "reachability": {"start": start, "basis": "graph", "status": "known" if known else "unknown",
                             "reachable": sorted(reach), "unreachable": sorted(s["id"] for s in states if s["reachability"] == "graph_unreachable")},
            "evidence": sorted(ev, key=lambda e: e["code"]),
            "unknowns": sorted(dedup, key=lambda u: u["kind"]),
            "loc": r["loc"],
        })

    # ------------------------------------------------------------------ coupling
    def _couplings(self):
        x = self.x
        out = {}
        for f in self.fsms:
            Rf = f["register"]["signal"]
            for g in self.fsms:
                if g is f:
                    continue
                Rg = g["register"]["signal"]
                pred_refs = []
                for t in g["transitions"]:
                    for e in t["guard"]:
                        s = x.stmt.get(e["statement"]) or {}
                        refs = ref_targets(s.get("cond")) if s.get("stmt") == "if" else ref_targets(s.get("expr")) if s.get("stmt") == "case" else set()
                        if e["kind"] == "ternary":
                            refs = ref_targets((x.assign.get(e["statement"]) or {}).get("value"))
                        if Rf in refs and e.get("predicate"):
                            pred_refs.append(e["predicate"])
                Ng = (g["next_signal"] or {}).get("signal", Rg)
                data = [d["id"] for d in x.dep.get((Rf, Ng), []) + x.dep.get((Rf, Rg), []) if d["kind"] == "data"]
                for kind, refs in (("predicate", pred_refs), ("data", data)):
                    if refs:
                        cid = F.fsm_id("coupling", f["id"], f"{g['id']}:{kind}")
                        out[cid] = {"id": cid, "from_fsm": f["id"], "to_fsm": g["id"], "kind": kind, "refs": sorted(set(refs))}
        self.couplings = sorted(out.values(), key=lambda c: c["id"])


# =============================================================================
# document
# =============================================================================

def counts(doc: dict) -> dict:
    c = {"fsms": len(doc["fsms"]), "couplings": len(doc["couplings"]), "rejected": len(doc["rejected"])}
    for s in F.STATUS:
        c[s] = sum(1 for f in doc["fsms"] if f["status"] == s)
    for q in F.QUALITY:
        c[f"quality_{q}"] = sum(1 for f in doc["fsms"] if f["quality"] == q)
    for k in F.FSM_LISTS:
        c[k] = sum(len(f[k]) for f in doc["fsms"])
    for r in F.REJECTION_REASONS:
        c[f"rejected_{r}"] = sum(1 for x in doc["rejected"] if x["reason"] == r)
    c["objects"] = c["fsms"] + c["couplings"] + c["rejected"] + sum(c[k] for k in F.FSM_LISTS)
    return c


def shape(f: dict) -> list:
    """Names-, identity-, value- and location-free projection of one FSM (state count / encoding /
    transition topology / guard structure / output kinds)."""
    idx = {s["id"]: i for i, s in enumerate(sorted(f["states"], key=lambda s: s["value"]))}
    return [f["status"], f["style"], f["encoding"]["style"], len(f["states"]),
            sorted([str(idx.get(t["source"], t["source"])), str(idx.get(t["target"], t["target"])), t["kind"],
                    ",".join(f"{e['kind']}:{e['branch']}:{int(e['tests_state'])}" for e in t["guard"])]
                   for t in f["transitions"]),
            sorted(o["kind"] for o in f["outputs"])]


def fsm_fingerprint(f: dict) -> str:
    return F.fsm_id("fsm_fingerprint", "", F.dumps(shape(f)))


def fingerprint(doc: dict) -> str:
    """Module-level FSM shape: the sorted per-FSM shapes (leakage analysis)."""
    return F.fsm_id("fingerprint", "", F.dumps(sorted(shape(f) for f in doc["fsms"])))


def analyze(sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, st, st_rel, st_sha) -> dict:
    x = _In(sem, beh, st, sem_sha, beh_sha)
    a = _Analysis(x)
    a.run()
    m = sem["module"]
    doc = {
        "schema": {"name": F.SCHEMA_NAME, "version": F.SCHEMA_VERSION},
        "versions": {"schema": F.SCHEMA_VERSION, "identity": F.IDENTITY_VERSION, "analyzer": F.ANALYZER_VERSION,
                     "provenance": F.PROVENANCE_VERSION, "semantic_ir": F.SEMANTIC_IR_VERSION,
                     "semantic_identity": F.SEMANTIC_IDENTITY_VERSION, "behavior": F.BEHAVIOR_VERSION,
                     "behavior_identity": F.BEHAVIOR_IDENTITY_VERSION, "structural": F.STRUCTURAL_VERSION,
                     "structural_identity": F.STRUCTURAL_IDENTITY_VERSION},
        "generator": {"analyzer": F.ANALYZER},
        "module": {
            "ip": m["ip"], "name": m["name"], "module_id": m["module_id"], "semantic_id": m["id"], "loc": m["loc"],
            "source": dict(m["source"]),
            "semantic_ir": {"path": sem_rel, "sha256": sem_sha, "schema_version": F.SEMANTIC_IR_VERSION,
                            "identity_version": F.SEMANTIC_IDENTITY_VERSION},
            "behavior": {"path": beh_rel, "sha256": beh_sha, "schema_version": F.BEHAVIOR_VERSION,
                         "identity_version": F.BEHAVIOR_IDENTITY_VERSION},
            "structural": {"path": st_rel, "sha256": st_sha, "structural_id": st["id"],
                           "schema_version": F.STRUCTURAL_VERSION, "identity_version": F.STRUCTURAL_IDENTITY_VERSION},
        },
        "fsms": sorted(a.fsms, key=lambda f: f["id"]),
        "couplings": a.couplings,
        "rejected": sorted(a.rejected, key=lambda r: r["id"]),
        "notes": dict(sorted(a.notes.items())),
    }
    for f in doc["fsms"]:
        f["fingerprint"] = fsm_fingerprint(f)
    doc["counts"] = counts(doc)
    doc["fingerprint"] = fingerprint(doc)
    doc["id"] = F.document_id(doc)
    return doc


# =============================================================================
# corpus
# =============================================================================

def canonical_modules(data_root) -> list:
    from scripts.core.paths import ForgeDataPaths, iter_module_yamls

    data = ForgeDataPaths.from_root(data_root)
    return sorted({(p.parent.parent.name, p.stem) for p in iter_module_yamls(data.normalized_ir)})


def semantic_rel(ip, module) -> str:
    return f"normalized/semantic_ir/v2/{ip}/{module}.json"


def behavior_rel(ip, module) -> str:
    return f"normalized/behavior/v1/{ip}/{module}.json"


def structural_rel(ip, module) -> str:
    return f"normalized/structural/v1/{ip}/{module}.json"


def fsm_rel(ip, module) -> str:
    return f"{F.OUTPUT_DIR}/{ip}/{module}.json"


def load_inputs(data_root, ip, module) -> tuple:
    """(sem, rel, sha, beh, rel, sha, st, rel, sha) of a canonical module (fail closed)."""
    root = Path(os.path.abspath(data_root))
    out = []
    for rel, what in ((semantic_rel(ip, module), "Semantic IR"), (behavior_rel(ip, module), "Behavioral Semantics"),
                      (structural_rel(ip, module), "Structural Analysis")):
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


def build(data_root, ip, module) -> dict:
    return analyze(*load_inputs(data_root, ip, module))


def write_all(data_root) -> dict:
    """Write FSM Analysis v1 for every canonical module (fail closed)."""
    from scripts.core.paths import find_absolute_paths

    root = Path(os.path.abspath(data_root))
    written = 0
    for ip, module in canonical_modules(root):
        doc = build(root, ip, module)
        text = F.dumps(doc)
        if find_absolute_paths(text):
            raise AnalysisError(f"{ip}/{module}: absolute path in FSM output")
        out = root / fsm_rel(ip, module)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            out.write_text(text, encoding="utf-8")
        written += 1
    return {"documents": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-011 FSM Analysis v1 analyzer")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--write", action="store_true", help="(re)generate normalized/fsm/v1")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    if not args.write:
        parser.error("nothing to do (use --write; validate with scripts/fsm/validator.py)")
    try:
        res = write_all(args.data_root)
    except AnalysisError as exc:
        print(f"[STOP] FSM analysis refused: {exc}")
        return 1
    print(f"[INFO] wrote {res['documents']} FSM Analysis v1 documents to {F.OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    raise SystemExit(main())
