# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : render.py
# Description : Prompt v2 renderer: canonical analysis documents to behavior-aware prompt + sidecar (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : prompt_v2
# Layer       : Prompt Generation
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 renderer (KF-DQ-012 sections 5 - 19).

``load_inputs(data_root, ip, module)`` reads the four canonical documents of
a module - Semantic IR v2, Behavioral Semantics v1, Structural Analysis v1,
FSM Analysis v2 - and the module's canonical source text, and fails closed
(``PromptError``) on a missing document, a schema / identity / analyzer
version mismatch, a broken provenance chain (a document derived from
another revision of its inputs) or a source file whose sha256 differs from
Semantic IR.  ``render(inputs)`` returns ``(prompt_text, sidecar)``.

The prompt is an abstraction: behavior is rendered as dependency
relationships and FSM guards in a fixed natural-language vocabulary; no
HDL expression, statement, comment, parser field or absolute path is ever
emitted.  Facts come only from the four documents; unknown, ambiguous,
candidate, unsupported, unresolved and derived facts keep their markers.
The source text is used only by the answer-leakage check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.prompt_v2 import leakage as L
from scripts.prompt_v2 import model as P


class PromptError(RuntimeError):
    """Prompt v2 generation refused (fail closed)."""


# =============================================================================
# inputs
# =============================================================================

def upstream_rel(layer: str, ip: str, module: str) -> str:
    return f"{P.UPSTREAM[layer][3]}/{ip}/{module}.json"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_inputs(data_root, ip: str, module: str) -> dict:
    """The four canonical documents + source text of one module (fail closed, AC-051 .. AC-062)."""
    root = Path(os.path.abspath(data_root))
    docs, rels, shas = {}, {}, {}
    for layer, (name, version, identity, _) in P.UPSTREAM.items():
        rel = upstream_rel(layer, ip, module)
        path = root / rel
        if not path.is_file():
            raise PromptError(f"missing {layer} input {rel}")
        raw = path.read_bytes()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise PromptError(f"{rel}: invalid JSON ({exc})") from exc
        if doc.get("schema") != {"name": name, "version": version}:
            raise PromptError(f"{rel}: unsupported schema {doc.get('schema')!r} (expected {name} v{version})")
        if (doc.get("versions") or {}).get("identity") != identity:
            raise PromptError(f"{rel}: unsupported identity version {(doc.get('versions') or {}).get('identity')!r}")
        m = doc.get("module") or {}
        if (m.get("ip"), m.get("name")) != (ip, module):
            raise PromptError(f"{rel}: describes {m.get('ip')}/{m.get('name')}")
        docs[layer], rels[layer], shas[layer] = doc, rel, _sha(raw)
    if (docs["structural"].get("versions") or {}).get("analyzer") != P.STRUCTURAL_ANALYZER_VERSION:
        raise PromptError(f"{rels['structural']}: unsupported structural analyzer version")
    if (docs["fsm"].get("versions") or {}).get("analyzer") != P.FSM_ANALYZER_VERSION:
        raise PromptError(f"{rels['fsm']}: unsupported FSM analyzer version")
    ids = {layer: (d.get("module") or {}).get("module_id") for layer, d in docs.items()}
    if len(set(ids.values())) != 1 or None in ids.values():
        raise PromptError(f"{ip}/{module}: module identities disagree across the four inputs {ids}")
    # provenance chain: every document must be derived from the current revision of its inputs (AC-060)
    chain = (("behavior", "semantic_ir"), ("structural", "semantic_ir"), ("structural", "behavior"),
             ("fsm", "semantic_ir"), ("fsm", "behavior"), ("fsm", "structural"))
    for doc_layer, input_layer in chain:
        ref = (docs[doc_layer].get("module") or {}).get(input_layer) or {}
        if ref.get("sha256") != shas[input_layer] or ref.get("path") != rels[input_layer]:
            raise PromptError(f"{rels[doc_layer]}: derived from a stale {input_layer} revision")
    src = (docs["semantic_ir"].get("module") or {}).get("source") or {}
    spath = root / str(src.get("path"))
    if not src.get("path") or not spath.is_file():
        raise PromptError(f"{ip}/{module}: canonical source {src.get('path')!r} missing")
    sraw = spath.read_bytes()
    if _sha(sraw) != src.get("sha256"):
        raise PromptError(f"{ip}/{module}: canonical source {src.get('path')} differs from its Semantic IR sha256")
    return {"ip": ip, "module": module, "docs": docs, "rels": rels, "shas": shas,
            "source": {"path": src["path"], "sha256": src["sha256"]},
            "source_text": sraw.decode("utf-8", errors="replace")}


# =============================================================================
# natural-language conditions (AC-074, AC-075, AC-310 .. AC-316)
# =============================================================================

class _Lang:
    def __init__(self, names: dict):
        self.names = names

    def operand(self, e):
        if not isinstance(e, dict):
            return None
        op = e.get("op")
        if op == "ref":
            return self.ref_name(e)
        if op == "literal":
            v = e.get("value")
            return str(v) if isinstance(v, int) and not isinstance(v, bool) else None
        if op == "index":
            b, i = self.operand(e.get("base")), self.operand(e.get("index"))
            return f"bit {i} of {b}" if b and i else None
        if op == "part_select":
            b, lo, hi = self.operand(e.get("base")), self.operand(e.get("left")), self.operand(e.get("right"))
            return f"bits {lo} to {hi} of {b}" if b and lo and hi else None
        return None

    def ref_name(self, e):
        """Declared name of a resolved reference; unresolved source text in natural language (KF-DQ-012.1)."""
        return self.names.get(e.get("target")) or P.select_text(e.get("name"))

    def cond(self, e, neg=False):
        if not isinstance(e, dict):
            return None
        op = e.get("op")
        if op == "unary" and e.get("operator") in ("!", "~"):
            return self.cond(e.get("operand"), not neg)
        if op in ("ref", "index"):
            v = self.operand(e)
            return f"{v} is {'0' if neg else '1'}" if v else None
        if op == "binary" and e.get("operator") in P.COMPARISON:
            a, b = self.operand(e.get("left")), self.operand(e.get("right"))
            if not a or not b:
                return None
            word = P.COMPARISON[e["operator"]]
            return f"{a} {P.NEGATED[word] if neg else word} {b}"
        if op == "binary" and e.get("operator") in ("&&", "||", "&", "|"):
            left, right = self.cond(e.get("left"), neg), self.cond(e.get("right"), neg)
            if not left or not right:
                return None
            conj = "and" if (e["operator"] in ("&&", "&")) != neg else "or"
            return f"({left} {conj} {right})"
        return None

    def refs(self, e) -> list:
        out, stack = set(), [e]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("op") == "ref":
                    n = self.ref_name(x)
                    if n:
                        out.add(n)
                    elif x.get("name"):
                        out.add("an unresolved signal")
                stack.extend(v for k, v in x.items() if k != "loc")
            elif isinstance(x, list):
                stack.extend(x)
        return sorted(out)

    def fallback(self, e) -> str:
        r = self.refs(e)
        return "a condition on " + ", ".join(r) if r else "a condition on constants"


# =============================================================================
# rendering
# =============================================================================

def _edge(edge) -> str:
    return {"posedge": "rising", "negedge": "falling"}.get(edge, "unknown")


class _Renderer:
    def __init__(self, inputs: dict):
        self.i = inputs
        d = inputs["docs"]
        self.sem, self.beh, self.st, self.fsm = d["semantic_ir"], d["behavior"], d["structural"], d["fsm"]
        self.decl = {x["id"]: x for x in self.sem.get("ports", []) + self.sem.get("signals", [])}
        self.names = {k: v.get("name") for k, v in self.decl.items()}
        self.names.update({p["id"]: p.get("name") for p in self.sem.get("parameters", [])})
        for t in self.sem.get("typedefs", []):
            for m in t.get("members", []) or []:
                if m.get("id"):
                    self.names[m["id"]] = m.get("name")
        self.lang = _Lang(self.names)
        self.stmts = {}
        for p in self.sem.get("processes", []):
            for s in p.get("body", []):
                self._walk(s)
        self.assign = {a["id"]: a for a in self.sem.get("assignments", [])}
        self.stats = {"guard_fallbacks": 0}

    def _walk(self, s):
        if not isinstance(s, dict) or "stmt" not in s:
            return
        self.stmts[s["id"]] = s
        for k in ("then", "else"):
            self._walk(s.get(k))
        body = s.get("body")
        for x in body if isinstance(body, list) else [body]:
            self._walk(x)
        for it in s.get("items", []) or []:
            self._walk(it.get("body"))
        if isinstance(s.get("default"), dict):
            self._walk(s["default"].get("body"))

    def name(self, sid) -> str:
        return self.names.get(sid) or "an unresolved signal"

    # ------------------------------------------------------------------ sections
    def module(self) -> list:
        m = self.i["module"]
        lines = [f"Name: {m}"]
        params = [p for p in self.sem.get("parameters", []) if p.get("kind") == "parameter" and not p.get("scope")]
        if params:
            lines.append("Parameters:")
            for p in params:
                v = p.get("value")
                lines.append(f"- {p['name']}, default {v if isinstance(v, int) and not isinstance(v, bool) else 'unresolved'}")
        lines.append("Ports:")
        for p in self.sem.get("ports", []):
            lines.append(f"- {p['name']}: {p.get('direction') or 'unknown direction'}, {P.width_text(p.get('width'))}")
        return lines

    def clocks(self) -> list:
        clocks = sorted({(self.name(c["signal"]), _edge(c.get("edge"))) for c in self.beh.get("clocks", [])})
        lines = [f"- clock {n}, {e} edge" for n, e in clocks]
        resets = sorted({(self.name(x["signal"]), x.get("kind") or "unknown", x.get("polarity"), x.get("status"))
                         for x in self.beh.get("resets", [])}, key=lambda r: tuple(str(v) for v in r))
        for n, kind, pol, status in resets:
            lines.append(f"- reset {n}: {kind}, {(pol or 'unknown polarity').replace('_', ' ')}"
                         + (" (candidate)" if status != "confirmed" else ""))
        return lines

    def registers(self) -> list:
        clocks = {c["id"]: c for c in self.beh.get("clocks", [])}
        resets = {x["id"]: x for x in self.beh.get("resets", [])}
        nv = {x["id"]: x for x in self.beh.get("next_values", [])}
        refs = {x["id"]: x.get("target") for x in self.sem.get("references", [])}
        out = []
        for reg in sorted(self.beh.get("registers", []), key=lambda r: (r.get("name") or "", r["id"])):
            parts = [f"{reg.get('name')} ({P.width_text(reg.get('width'))})"]
            c = clocks.get(reg.get("clock"))
            if c:
                parts.append(f"updated on the {_edge(c.get('edge'))} edge of {self.name(c['signal'])}")
            rv = set()
            for rid in reg.get("resets", []):
                rs = resets.get(rid)
                if not rs:
                    continue
                for t in rs.get("targets", []):
                    if t.get("signal") == reg.get("signal"):
                        v = self.lang.operand((self.assign.get(t.get("assignment")) or {}).get("value"))
                        rv.add(f"reset by {self.name(rs['signal'])} to {v if v else 'an unresolved value'}")
            parts += sorted(rv)
            srcs = set()
            for n in reg.get("next_values", []):
                for ref in (nv.get(n) or {}).get("value_references", []):
                    t = refs.get(ref)
                    if t in self.decl:
                        srcs.add(self.decl[t]["name"])
            if srcs:
                parts.append("next value depends on " + ", ".join(sorted(srcs)))
            ctl = {self.name(d["source"]) for d in self.st.get("dependencies", [])
                   if d["target"] == reg.get("signal") and d["kind"] in ("control", "enable")
                   and d["source"] != reg.get("signal") and d["source"] in self.decl}
            if ctl:
                parts.append("controlled by " + ", ".join(sorted(ctl)))
            if reg.get("hold") in ("implicit", "explicit", "mixed"):
                parts.append(f"otherwise holds its value ({reg['hold']} hold)")
            out.append("- " + "; ".join(parts))
        return out

    def combinational(self) -> list:
        out = []
        deps = self.st.get("dependencies", [])
        for cmb in sorted(self.beh.get("combinational", []), key=lambda x: (self.name(x["signal"]), x["signal"])):
            s = cmb["signal"]
            data = sorted({self.name(d["source"]) for d in deps
                           if d["target"] == s and d["kind"] == "data" and d["source"] in self.decl})
            ctl = sorted({self.name(d["source"]) for d in deps
                          if d["target"] == s and d["kind"] == "control" and d["source"] in self.decl})
            txt = f"- {self.name(s)} depends on {', '.join(data) if data else 'constants only'}"
            if ctl:
                txt += f"; selected by {', '.join(ctl)}"
            out.append(txt)
        cont = [a for a in self.sem.get("assignments", []) if a.get("process") is None
                and a.get("kind") in ("continuous", "declaration") and a.get("subroutine") is None]
        rows = set()
        for a in cont:
            for w in a.get("writes", []):
                srcs = [x for x in self.lang.refs(a.get("value")) if x != self.name(w)]
                rows.add(f"- {self.name(w)} (continuous) depends on {', '.join(srcs) if srcs else 'constants only'}")
        return out + sorted(rows)

    def _guard(self, t) -> str:
        out = []
        tern = [g for g in t.get("guard", []) if g.get("kind") == "ternary"]
        for g in t.get("guard", []):
            if g.get("role") == "reset" or (g.get("tests_state") and g.get("values")) or g.get("kind") == "ternary":
                continue
            s = self.stmts.get(g.get("statement"))
            if s is None:
                out.append("an unknown condition")
                continue
            if s.get("stmt") == "if":
                c = self.lang.cond(s.get("cond"), g.get("branch") == "else")
                if not c:
                    self.stats["guard_fallbacks"] += 1
                    c = self.lang.fallback(s.get("cond"))
                out.append(c)
            elif s.get("stmt") == "case":
                sel = self.lang.operand(s.get("expr")) or ("a selector over " + ", ".join(self.lang.refs(s.get("expr"))))
                if g.get("branch") == "item" and isinstance(g.get("item"), int) and g["item"] < len(s.get("items", [])):
                    labels = [self.lang.operand(x) or "an unrendered value" for x in s["items"][g["item"]].get("exprs", [])]
                    out.append(f"{sel} is {' or '.join(labels)}")
                else:
                    out.append(f"{sel} matches no listed value")
            elif s.get("stmt") == "loop":
                out.append("inside a loop")
            else:
                out.append("an unknown condition")
        if tern:
            v = (self.assign.get(tern[0].get("statement")) or {}).get("value")
            for g in tern:
                if not isinstance(v, dict) or v.get("op") != "ternary":
                    break
                if not (g.get("tests_state") and g.get("values")):
                    c = self.lang.cond(v.get("cond"), g.get("branch") == "else")
                    if not c:
                        self.stats["guard_fallbacks"] += 1
                        c = self.lang.fallback(v.get("cond"))
                    out.append(c)
                v = v.get("then") if g.get("branch") == "then" else v.get("else")
        return " and ".join(out)

    def state_machines(self) -> tuple:
        """(fixed lines, truncatable lines, couplings, FSM count); truncatable = transitions and actions (A8)."""
        fixed, items = [], []
        fsms = sorted(self.fsm.get("fsms", []), key=lambda f: ((f.get("register") or {}).get("name") or "", f["id"]))
        number = {f["id"]: i for i, f in enumerate(fsms, 1)}
        for f in fsms:
            i = number[f["id"]]
            label = {s["id"]: (s.get("name") or f"value {s.get('value')}") for s in f.get("states", [])}
            reg = f.get("register") or {}
            enc = f.get("encoding") or {}
            head = (f"FSM {i}: state register {reg.get('name')} ({P.width_text(reg.get('width'))}); "
                    f"status {f.get('status')}; quality {f.get('quality')}; {str(f.get('style')).replace('_', '-')}; "
                    f"encoding {enc.get('style') if enc.get('status') in ('explicit', 'inferred') else 'unknown'}")
            fixed.append((i, head))
            ck = f.get("clock") or {}
            rs = f.get("reset") or {}
            timing = []
            if ck.get("signal"):
                timing.append(f"clock {self.name(ck['signal'])}, {_edge(ck.get('edge'))} edge")
            if rs.get("signal"):
                timing.append(f"reset {self.name(rs['signal'])} ({rs.get('kind') or 'unknown'}"
                              + (", candidate" if rs.get("status") != "confirmed" else "") + ")"
                              + (f" to {label[rs['state']]}" if rs.get("state") in label else ""))
            en = sorted({self.name(x) for e in f.get("enable", []) for x in e.get("signals", [])})
            if en:
                timing.append("enabled by " + ", ".join(en))
            if f.get("hold") in ("implicit", "explicit", "mixed"):
                timing.append(f"{f['hold']} hold")
            if timing:
                fixed.append((i, "Timing: " + "; ".join(timing)))
            if f.get("states"):
                st = []
                for s in sorted(f["states"], key=lambda s: (s.get("value") is None, s.get("value") or 0, s["id"])):
                    txt = label[s["id"]] if not s.get("name") else f"{label[s['id']]} = {s.get('value')}"
                    if (s.get("constant") or {}).get("implicit"):
                        txt += " (implicit value)"
                    if s.get("reset"):
                        txt += " (reset)"
                    if s.get("reachability") == "graph_unreachable":
                        txt += " (unreachable in the transition graph)"
                    st.append(txt)
                fixed.append((i, "States: " + ", ".join(st)))
            else:
                fixed.append((i, "States: unresolved"))
            reach = (f.get("reachability") or {}).get("status")
            fixed.append((i, "Reachability from the reset state: "
                          + ("known (transition graph only)" if reach == "known" else "unknown")))
            for o in sorted(f.get("outputs", []), key=lambda o: (o.get("name") or "", o["id"])):
                if o.get("registered"):
                    src = ", ".join(sorted(self.name(x) for x in o.get("sampled_sources", [])))
                    txt = (f"Output {o['name']}: {o['kind']}, registered; updated at the clock edge from "
                           + (src if src else "state only"))
                else:
                    oth = ", ".join(sorted(self.name(x) for x in o.get("other_sources", [])))
                    txt = f"Output {o['name']}: {o['kind']}" + (f", also depends on {oth}" if oth else "")
                fixed.append((i, txt))
            unk = []
            for u in f.get("unknowns", []):
                k = str(u.get("kind")).replace("_", " ")
                if k not in unk:
                    unk.append(k)
            if unk:
                fixed.append((i, "Uncertain: " + ", ".join(unk)))
            for t in sorted(f.get("transitions", []),
                            key=lambda t: (t.get("priority") is None, t.get("priority") or 0, t["id"])):
                if t.get("kind") == "reset" or t.get("source") == "*none":
                    continue
                src = label.get(t.get("source"), "an unknown state")
                dst = label.get(t.get("target"), "an unknown state")
                cond = self._guard(t)
                kind = {"explicit_hold": " (explicit hold)", "implicit_hold": " (holds)",
                        "default": " (default)"}.get(t.get("kind"), "")
                txt = (f"- {src} -> {dst}" + (f" when {cond}" if cond else "") + kind
                       + (" [derived]" if t.get("status") == "derived" else "")
                       + (" [unknown]" if t.get("status") == "unknown" else "")
                       + (" (priority unknown)" if t.get("priority") is None else ""))
                items.append((i, "transition", txt))
            acts = sorted({(label.get(a.get("state"), "an unknown state"), self.name(a.get("signal")), a.get("kind"))
                           for a in f.get("actions", [])})
            for state, sig, kind in acts:
                items.append((i, "action", f"- in {state}: {sig} is assigned ({kind})"))
        couplings = []
        for c in sorted(self.fsm.get("couplings", []), key=lambda c: c["id"]):
            a, b = number.get(c.get("from_fsm")), number.get(c.get("to_fsm"))
            if a is None or b is None:
                continue
            if c.get("kind") == "predicate":
                couplings.append(f"Coupling: FSM {b} tests the state of FSM {a}")
            else:
                couplings.append(f"Coupling: the state of FSM {a} feeds the next state of FSM {b}")
        return fixed, items, sorted(set(couplings)), len(fsms)

    def submodules(self) -> list:
        conns = {c["id"]: c for c in self.st.get("connections", [])}
        out = []
        for inst in sorted(self.st.get("instances", []), key=lambda x: (x.get("name") or "", x["id"])):
            cs = []
            for cid in inst.get("connections", []):
                c = conns.get(cid) or {}
                sigs = ", ".join(sorted(self.name(s) for s in c.get("signals", []))) or "nothing"
                arrow = {"parent_to_child": "<-", "child_to_parent": "->"}.get(c.get("flow"), "<->")
                port = c.get("port") if isinstance(c.get("port"), str) else f"position {c.get('position')}"
                cs.append(f"{port} {arrow} {sigs}")
            out.append(f"- {inst.get('name') or 'an unnamed instance'}: instance of {inst.get('module')}"
                       + (" (unresolved)" if inst.get("status") != "resolved" else "")
                       + (": " + "; ".join(cs) if cs else ""))
        return out


def _assemble(sections: list) -> str:
    lines = [P.PREAMBLE]
    for name, fixed, items, notice in sections:
        if not fixed and not items and not notice:
            continue
        lines += ["", f"## {name}"]
        lines += fixed
        lines += items
        if notice:
            lines.append(notice)
    return "\n".join(lines) + "\n"


def _fsm_lines(fixed, items, couplings, removed: int) -> tuple[list, list]:
    """Interleave per-FSM fixed lines and the kept truncatable lines (transitions / actions)."""
    keep = items[:len(items) - removed] if removed else items
    out = []
    numbers = sorted({n for n, _ in fixed})
    for n in numbers:
        out += [t for k, t in fixed if k == n]
        tr = [t for k, kind, t in keep if k == n and kind == "transition"]
        ac = [t for k, kind, t in keep if k == n and kind == "action"]
        if tr:
            out.append("Transitions:")
            out += tr
        if ac:
            out.append("Actions:")
            out += ac
    return out + couplings, keep


def render(inputs: dict, variant: str = P.DEFAULT_VARIANT) -> tuple[str, dict]:
    """(prompt text, sidecar) for one module (deterministic, fail closed)."""
    if variant not in P.VARIANTS:
        raise PromptError(f"unknown prompt variant {variant!r}")
    r = _Renderer(inputs)
    module, clocks, regs, comb, subs = r.module(), r.clocks(), r.registers(), r.combinational(), r.submodules()
    fixed, items, couplings, n_fsm = r.state_machines()
    records = {"Registers": regs, "Combinational logic": comb, "Submodules": subs}
    removed = {"Registers": 0, "Combinational logic": 0, "Submodules": 0, "State machines": 0}
    totals = {"Registers": len(regs), "Combinational logic": len(comb), "Submodules": len(subs),
              "State machines": len(items)}

    def build() -> str:
        secs = [("Module", module, [], None), ("Clocks and resets", clocks, [], None)]
        for name in ("Registers", "Combinational logic"):
            keep = records[name][:totals[name] - removed[name]]
            notice = P.TRUNCATION_NOTICE.format(section=name, emitted=len(keep), total=totals[name]) if removed[name] else None
            secs.append((name, keep, [], notice))
        fsm_text, _ = _fsm_lines(fixed, items, couplings, removed["State machines"])
        notice = (P.TRUNCATION_NOTICE.format(section="State machines", emitted=totals["State machines"]
                                             - removed["State machines"], total=totals["State machines"])
                  if removed["State machines"] else None)
        secs.append(("State machines", fsm_text, [], notice))
        keep = records["Submodules"][:totals["Submodules"] - removed["Submodules"]]
        notice = P.TRUNCATION_NOTICE.format(section="Submodules", emitted=len(keep), total=totals["Submodules"]) \
            if removed["Submodules"] else None
        secs.append(("Submodules", keep, [], notice))
        return _assemble(secs)

    text = build()
    original = len(text.encode("utf-8"))
    for name in P.TRUNCATION_ORDER:                     # A8: whole records, lowest priority first
        while len(text.encode("utf-8")) > P.BUDGET_BYTES and removed[name] < totals[name]:
            removed[name] += 1
            text = build()
    if len(text.encode("utf-8")) > P.BUDGET_BYTES:
        raise PromptError(f"{inputs['ip']}/{inputs['module']}: mandatory sections exceed the "
                          f"{P.BUDGET_BYTES}-byte budget (AC-391)")
    present = [s for s in P.SECTIONS if f"\n## {s}\n" in text]
    sections = []
    for s in present:
        total = totals.get(s)
        sections.append({"name": s, "records": total if total is not None else None,
                         "emitted": (total - removed[s]) if total is not None else None,
                         "truncated": bool(removed.get(s))})
    truncated = [{"section": s, "emitted": totals[s] - removed[s], "total": totals[s]}
                 for s in P.TRUNCATION_ORDER if removed[s]]
    canon = L.canonical_names(r.sem, r.st)
    leak = L.measure(text, inputs["source_text"], canon)
    fsms = r.fsm.get("fsms", [])
    status_counts = {s: sum(1 for f in fsms if f.get("status") == s) for s in P.FSM_STATUS}
    sidecar = {
        "schema": {"name": P.SCHEMA_NAME, "version": P.SCHEMA_VERSION},
        "generator": {"name": P.GENERATOR, "version": P.GENERATOR_VERSION},
        "versions": versions(),
        "module": {"ip": inputs["ip"], "name": inputs["module"],
                   "module_id": (r.sem.get("module") or {}).get("module_id")},
        "variant": variant,
        "inputs": {
            layer: {"path": inputs["rels"][layer], "sha256": inputs["shas"][layer],
                    "schema_version": P.UPSTREAM[layer][1], "identity_version": P.UPSTREAM[layer][2]}
            for layer in P.UPSTREAM
        },
        "source": dict(inputs["source"]),
        "prompt": {
            "path": P.prompt_rel(inputs["ip"], inputs["module"], variant),
            "sha256": P.sha256_text(text),
            "bytes": len(text.encode("utf-8")),
            "original_bytes": original,
            "budget_bytes": P.BUDGET_BYTES,
            "truncated": bool(truncated),
            "truncated_sections": truncated,
            "sections": sections,
            "omitted_sections": [s for s in P.SECTIONS if s not in present],
        },
        "abstraction": {
            "guard_fallbacks": r.stats["guard_fallbacks"],
            "rendering": "dependency relationships and natural-language conditions; no HDL expressions",
        },
        "uncertainty": uncertainty(text),
        "fsm": {
            "fsms": len(fsms), **status_counts,
            "quality": {q: sum(1 for f in fsms if f.get("quality") == q)
                        for q in ("high", "medium", "low", "ambiguous", "unsupported")},
            "states": sum(len(f.get("states", [])) for f in fsms),
            "transitions": sum(len(f.get("transitions", [])) for f in fsms),
            "transitions_rendered": sum(1 for _, kind, _ in items if kind == "transition"),
            "actions_rendered": sum(1 for _, kind, _ in items if kind == "action"),
            "unknowns": sum(len(f.get("unknowns", [])) for f in fsms),
            "couplings": len(r.fsm.get("couplings", [])),
            "section_truncated": bool(removed["State machines"]),
        },
        "leakage": leak,
    }
    sidecar["identity"] = P.identity(sidecar)
    return text, sidecar


def versions() -> dict:
    from scripts.prompt_v2 import leakage as LK
    return {
        "prompt": P.SCHEMA_VERSION, "prompt_generator": P.GENERATOR_VERSION, "prompt_identity": P.IDENTITY_VERSION,
        "semantic_ir": P.SEMANTIC_IR_VERSION, "semantic_identity": P.SEMANTIC_IDENTITY_VERSION,
        "behavior": P.BEHAVIOR_VERSION, "behavior_identity": P.BEHAVIOR_IDENTITY_VERSION,
        "structural": P.STRUCTURAL_VERSION, "structural_identity": P.STRUCTURAL_IDENTITY_VERSION,
        "structural_analyzer": P.STRUCTURAL_ANALYZER_VERSION,
        "fsm": P.FSM_VERSION, "fsm_identity": P.FSM_IDENTITY_VERSION, "fsm_analyzer": P.FSM_ANALYZER_VERSION,
        "tokenizer": LK.TOKENIZER_VERSION, "leakage_metric": LK.METRIC_VERSION,
        "leakage_thresholds": LK.THRESHOLD_VERSION,
    }


def uncertainty(text: str) -> dict:
    counts = {k: 0 for k in P.UNCERTAINTY}
    markers = {}
    for marker, cat in sorted(P.MARKERS.items()):
        n = text.count(marker)
        if n:
            markers[marker] = n
            counts[cat] += n
    return {"by_category": counts, "markers": markers}


# =============================================================================
# corpus
# =============================================================================

def canonical_modules(data_root) -> list:
    from scripts.fsm import analyzer as FA
    return FA.canonical_modules(data_root)


def build(data_root, ip: str, module: str, variant: str = P.DEFAULT_VARIANT) -> tuple[str, dict]:
    return render(load_inputs(data_root, ip, module), variant)


def write_all(data_root) -> dict:
    """Write Prompt v2 (text + sidecar) for every canonical module (fail closed, AC-801 .. AC-806)."""
    from scripts.core.paths import find_absolute_paths

    root = Path(os.path.abspath(data_root))
    written = 0
    for ip, module in canonical_modules(root):
        text, sidecar = build(root, ip, module)
        side = P.dumps(sidecar)
        if find_absolute_paths(text) or find_absolute_paths(side):
            raise PromptError(f"{ip}/{module}: absolute path in Prompt v2 output")
        for rel, content in ((P.prompt_rel(ip, module), text), (P.sidecar_rel(ip, module), side)):
            out = root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.is_file() or out.read_text(encoding="utf-8") != content:
                out.write_text(content, encoding="utf-8")
        written += 1
    return {"prompts": written, "sidecars": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-012 Prompt v2 generator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--write", action="store_true", help=f"(re)generate {P.OUTPUT_DIR}")
    args = parser.parse_args(argv)
    if not args.data_root:
        from scripts.core.paths import default_data_root
        args.data_root = str(default_data_root())
    if not args.write:
        parser.error("nothing to do (use --write; validate with scripts/prompt_v2/validator.py)")
    try:
        res = write_all(args.data_root)
    except PromptError as exc:
        print(f"[STOP] Prompt v2 generation refused: {exc}")
        return 1
    print(f"[INFO] wrote {res['prompts']} Prompt v2 prompts and {res['sidecars']} sidecars to {P.OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
