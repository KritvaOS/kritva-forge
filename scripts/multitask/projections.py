# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : projections.py
# Description : Frozen JSON projections interface-v1 / structural-v1 / dependency-v1 / fsm-v1 (KF-DQ-013)
#
# Component   : Kritva Forge
# Module      : multitask
# Layer       : Dataset
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Projection contracts of the multi-task dataset (KF-DQ-013 AC-023 .. AC-029, AC-102 .. AC-110).

Every projection reads persisted, validated documents (``load_inputs``: schema /
identity / analyzer versions, module identity, provenance chain, source sha256)
and emits only the allowed fields listed below: names resolved from ids,
deterministic order, no ids, paths or locations.  Names and FSM conditions use
the Prompt v2 name map and natural-language guard renderer - one
implementation.  Nothing is recomputed: dependency kinds, cones, FSM
classification come from the documents as persisted.

``interface-v1``  (Semantic IR v2)  ``{module, parameters, ports}``
``structural-v1`` (Structural v1)   ``{module, registers, instances, processes, counts}``
``dependency-v1`` (Structural v1)   ``{module, targets}``
``fsm-v1``        (FSM Analysis v2) ``{module, fsms}``; excluded: actions, couplings,
                                    evidence, reachability details, unknown lists, fingerprints

Each projection returns ``(value, stats)``; ``stats`` counts ``null`` values and
unresolved names (reported by the dataset report, AC-029 / AC-110).
"""

from __future__ import annotations

from collections import Counter

from scripts.prompt_v2 import render as R

UNRESOLVED = "an unresolved signal"


class ProjectionError(RuntimeError):
    """A projection cannot be produced from the persisted documents (fail closed)."""


class _Ctx:
    def __init__(self, inputs: dict):
        self.r = R._Renderer(inputs)
        self.sem = inputs["docs"]["semantic_ir"]
        self.st = inputs["docs"]["structural"]
        self.fsm = inputs["docs"]["fsm"]
        self.module = inputs["module"]
        self.stats = Counter()

    def name(self, sid):
        n = self.r.names.get(sid)
        if n:
            return n
        self.stats["unresolved_names"] += 1
        return UNRESOLVED

    def null(self, value, field):
        if value is None:
            self.stats[f"null:{field}"] += 1
        return value


def _dims(dims) -> list:
    return [d.get("text") if isinstance(d, dict) else None for d in (dims or [])]


def interface(inputs: dict) -> tuple:
    c = _Ctx(inputs)
    params = []
    for p in c.sem.get("parameters", []):
        if p.get("kind") != "parameter" or p.get("scope"):
            continue
        params.append({"name": p.get("name"), "port_param": bool(p.get("port_param")),
                       "type": c.null(p.get("type"), "parameter.type"),
                       "width": c.null(p.get("width"), "parameter.width"),
                       "signed": bool(p.get("signed")),
                       "default_text": c.null((p.get("default") or {}).get("text"), "parameter.default_text")})
    ports = []
    for p in c.sem.get("ports", []):
        ports.append({"name": p.get("name"), "direction": c.null(p.get("direction"), "port.direction"),
                      "kind": p.get("kind"), "type": c.null(p.get("type"), "port.type"),
                      "width": c.null(p.get("width"), "port.width"), "signed": bool(p.get("signed")),
                      "packed": _dims(p.get("packed")), "unpacked": _dims(p.get("unpacked"))})
    if len(ports) != (c.sem.get("counts") or {}).get("ports", len(ports)):
        raise ProjectionError(f"{c.module}: interface port count disagrees with Semantic IR counts")
    return {"module": c.module, "parameters": params, "ports": ports}, dict(c.stats)


def structural(inputs: dict) -> tuple:
    c = _Ctx(inputs)
    regs = []
    for r in sorted(c.st.get("registers", []), key=lambda r: (r.get("name") or "", r["id"])):
        ck = r.get("clock") or None
        regs.append({"name": r.get("name"),
                     "clock": {"signal": c.name(ck.get("signal")), "edge": ck.get("edge")} if ck else c.null(None, "register.clock"),
                     "enables": sorted({c.name(s) for e in r.get("enables", []) for s in e.get("signals", [])}),
                     "hold": c.null(r.get("hold"), "register.hold")})
    conns = {x["id"]: x for x in c.st.get("connections", [])}
    insts = []
    for i in sorted(c.st.get("instances", []), key=lambda i: (i.get("name") or "", i["id"])):
        cs = []
        for cid in i.get("connections", []):
            x = conns.get(cid)
            if x is None:
                raise ProjectionError(f"{c.module}: instance {i.get('name')} references a missing connection")
            cs.append({"port": x.get("port") if isinstance(x.get("port"), str) else c.null(None, "connection.port"),
                       "direction": c.null(x.get("direction"), "connection.direction"),
                       "signals": sorted({c.name(s) for s in x.get("signals", [])})})
        insts.append({"name": c.null(i.get("name"), "instance.name"), "module": i.get("module"),
                      "status": i.get("status"), "connections": cs})
    counts = c.st.get("counts") or {}
    out = {"module": c.module, "registers": regs, "instances": insts,
           "processes": dict(sorted(Counter(p.get("boundary") or "unknown" for p in c.st.get("processes", [])).items())),
           "counts": {k: counts.get(k) for k in ("signals", "registers", "instances", "processes", "dependencies")}}
    if len(regs) != counts.get("registers") or len(insts) != counts.get("instances"):
        raise ProjectionError(f"{c.module}: structural register / instance counts disagree with the document")
    return out, dict(c.stats)


def dependency(inputs: dict) -> tuple:
    c = _Ctx(inputs)
    ports = {p["id"]: p for p in c.sem.get("ports", [])}
    inputs_ports = {pid for pid, p in ports.items() if p.get("direction") in ("input", "inout")}
    outs = {pid for pid, p in ports.items() if p.get("direction") == "output"}
    regs = {r.get("signal") for r in c.st.get("registers", []) if r.get("signal")}
    cones = {}
    for cone in sorted(c.st.get("cones", []), key=lambda x: x["id"]):
        if cone.get("direction") == "fanin":
            cones.setdefault(cone.get("signal"), cone)
    deps = {}
    for d in c.st.get("dependencies", []):
        deps.setdefault(d.get("target"), set()).add((c.name(d.get("source")), d.get("kind")))
    targets = []
    for sid in sorted(outs | regs, key=lambda s: (c.name(s), s)):
        role = ("registered_output" if sid in outs and sid in regs else "output" if sid in outs else "register")
        cone = cones.get(sid)
        if cone is None:
            ins, rg = c.null(None, "target.inputs"), c.null(None, "target.registers")
        else:
            ins = sorted({c.name(x) for x in cone.get("inputs", []) if x in inputs_ports})
            rg = sorted({c.name(x) for x in cone.get("registers", [])})
        targets.append({"name": c.name(sid), "role": role, "inputs": ins, "registers": rg,
                        "sources": [{"signal": s, "kind": k} for s, k in sorted(deps.get(sid, set()), key=lambda x: (x[0], str(x[1])))]})
    return {"module": c.module, "targets": targets}, dict(c.stats)


def fsm(inputs: dict) -> tuple:
    c = _Ctx(inputs)
    out = []
    for f in sorted((f for f in c.fsm.get("fsms", []) if f.get("status") in ("confirmed", "candidate")),
                    key=lambda f: ((f.get("register") or {}).get("name") or "", f["id"])):
        label = {s["id"]: (s.get("name") or f"value {s.get('value')}") for s in f.get("states", [])}
        reg = f.get("register") or {}
        enc = f.get("encoding") or {}
        ck = f.get("clock") or {}
        rs = f.get("reset") or {}
        states = [{"name": label[s["id"]], "value": c.null(s.get("value"), "state.value"), "reset": bool(s.get("reset"))}
                  for s in sorted(f.get("states", []), key=lambda s: (s.get("value") is None, s.get("value") or 0, s["id"]))]
        transitions = []
        for t in sorted(f.get("transitions", []), key=lambda t: (t.get("priority") is None, t.get("priority") or 0, t["id"])):
            if t.get("kind") == "reset" or t.get("source") == "*none":
                continue
            transitions.append({"from": label.get(t.get("source"), "an unknown state"),
                                "to": label.get(t.get("target"), "an unknown state"),
                                "condition": c.r._guard(t) or None, "kind": t.get("kind"), "status": t.get("status")})
        out.append({
            "state_register": reg.get("name"), "width": c.null(reg.get("width"), "fsm.width"),
            "status": f.get("status"), "quality": f.get("quality"), "style": f.get("style"),
            "encoding": {"style": enc.get("style") if enc.get("status") in ("explicit", "inferred") else c.null(None, "encoding.style"),
                         "width": c.null(enc.get("width"), "encoding.width")},
            "clock": {"signal": c.name(ck["signal"]), "edge": ck.get("edge")} if ck.get("signal") else c.null(None, "fsm.clock"),
            "reset": ({"signal": c.name(rs["signal"]), "kind": rs.get("kind"),
                       "state": label.get(rs.get("state")) if rs.get("state") in label else c.null(None, "reset.state")}
                      if rs.get("signal") else c.null(None, "fsm.reset")),
            "states": states,
            "transitions": transitions,
            "outputs": [{"name": o.get("name"), "kind": o.get("kind"), "registered": bool(o.get("registered"))}
                        for o in sorted(f.get("outputs", []), key=lambda o: (o.get("name") or "", o["id"]))],
        })
    c.stats["fsms"] = len(out)
    c.stats["guard_fallbacks"] = c.r.stats["guard_fallbacks"]
    return {"module": c.module, "fsms": out}, dict(c.stats)


PROJECTORS = {"interface-v1": interface, "structural-v1": structural, "dependency-v1": dependency, "fsm-v1": fsm}
