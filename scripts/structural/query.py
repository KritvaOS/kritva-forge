# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : query.py
# Description : Deterministic structural queries: fan-in / fan-out cones, drivers, SCCs (KF-DQ-010)
#
# Component   : Kritva Forge
# Module      : structural
# Layer       : Structural Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Queries over a persisted Structural Analysis v1 document (criteria section 11 / 26).

All functions read only the document (no re-analysis), are iterative (no
recursion limits), visit every node at most once (cycle safe) and return
sorted results, so answers are deterministic:

* ``cone(doc, signal, "fanin" | "fanout")`` - combinational cone that stops
  at sequential boundaries (registers) and records them;
* ``drivers_of``, ``loads_of``, ``controls_of``, ``registers_controlled_by``;
* ``scc(graph)`` - Tarjan strongly connected components (cycle detection).
"""

from __future__ import annotations

from collections import defaultdict

_SKIP_BOUNDARY = ("initialization",)


def scc(graph: dict) -> list:
    """Strongly connected components of ``{node: {successor, ...}}`` (iterative Tarjan), sorted."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = 0
    nodes = sorted(set(graph) | {t for ts in graph.values() for t in ts})
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(graph.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(graph.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(sorted(comp))
    return sorted(out)


def _index(doc):
    ins, outs = defaultdict(list), defaultdict(list)
    for d in doc["dependencies"]:
        if d["boundary"] in _SKIP_BOUNDARY or (d["kind"] == "hold" and d["source"] == d["target"]):
            continue
        ins[d["target"]].append(d)
        outs[d["source"]].append(d)
    return ins, outs


def cone(doc: dict, signal: str, direction: str) -> dict:
    """Fan-in / fan-out cone of ``signal`` (a Semantic IR port/signal identity)."""
    if direction not in ("fanin", "fanout"):
        raise ValueError(direction)
    ins, outs = _index(doc)
    regs = {r["signal"] for r in doc["registers"]}
    dirs = {s["signal"]: s.get("direction") for s in doc["signals"]}
    pred = {p["statement"]: p["id"] for p in doc["predicates"]}
    seen, boundary, used = {signal}, set(), {}
    level, depth = [signal], 0
    while level:
        nxt = []
        for n in level:
            if n != signal and n in boundary:
                continue
            for e in (ins[n] if direction == "fanin" else outs[n]):
                used[e["id"]] = e
                other = e["source"] if direction == "fanin" else e["target"]
                stop = other in regs and other != signal          # sequential boundary
                if stop:
                    boundary.add(other)
                if other not in seen:
                    seen.add(other)
                    if not stop:
                        nxt.append(other)
        if nxt:
            depth += 1
        level = sorted(nxt)
    members = seen - {signal}
    allsig = members | {signal}
    if direction == "fanin":
        inst = {d["connection"] for d in doc["drivers"] if d["signal"] in allsig and d.get("connection")}
    else:
        inst = {ld["consumer"] for ld in doc["loads"] if ld["signal"] in allsig and ld["kind"].startswith("instance_")}
    conn_inst = {c["id"]: c["instance"] for c in doc["connections"]}
    return {
        "signal": signal, "direction": direction,
        "signals": sorted(members),
        "registers": sorted(boundary),
        "inputs": sorted(s for s in members if dirs.get(s) in ("input", "inout")),
        "outputs": sorted(s for s in members if dirs.get(s) in ("output", "inout")),
        "processes": sorted({e["process"] for e in used.values() if e["process"]}),
        "assignments": sorted({a for e in used.values() for a in e["assignments"]}),
        "predicates": sorted({pred[e["via"]] for e in used.values() if e["via"] in pred}),
        "instances": sorted({conn_inst[c] for c in inst if c in conn_inst}),
        "edges": len(used),
        "depth": depth,
        "cycles": sorted(c["id"] for c in doc["cycles"] if allsig & set(c["signals"])),
    }


def drivers_of(doc: dict, signal: str) -> list:
    return sorted((d for d in doc["drivers"] if d["signal"] == signal), key=lambda d: d["id"])


def loads_of(doc: dict, signal: str) -> list:
    return sorted((x for x in doc["loads"] if x["signal"] == signal), key=lambda x: x["id"])


def controls_of(doc: dict, signal: str) -> list:
    """Signals with a control / reset / enable / clock dependency into ``signal``."""
    return sorted({d["source"] for d in doc["dependencies"]
                   if d["target"] == signal and d["kind"] in ("control", "reset", "enable", "clock")})


def registers_controlled_by(doc: dict, signal: str, kind: str = "enable") -> list:
    regs = {r["signal"] for r in doc["registers"]}
    return sorted({d["target"] for d in doc["dependencies"]
                   if d["source"] == signal and d["kind"] == kind and d["target"] in regs})
