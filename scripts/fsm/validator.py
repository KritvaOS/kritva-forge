#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : FSM Analysis v1 schema, reference, provenance and consistency validation (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis v1 validation (criteria sections 19, 21, 22, 24, 25) - fail closed.

``validate_module(doc, sem, sem_rel, sem_sha, beh, beh_rel, beh_sha, st,
st_rel, st_sha)`` returns ``[(code, message), ...]``; ``check(data_root)``
validates every document under ``normalized/fsm/v1`` against the canonical
module inventory and the current Semantic IR v2, Behavioral Semantics v1 and
Structural Analysis v1 (re-analysis must reproduce each document byte for
byte) and the split manifest (leakage), and is the ``make check-fsm`` gate.

Codes:

========================  =====================================================
``schema``                malformed JSON / unsupported schema, version block or analyzer
``required``              missing section or field
``enum``                  value outside a vocabulary
``identity``              malformed or non-derivable ``fsm1:`` / upstream identity
``duplicate_identity``    one FSM identity used twice
``state_reference``       transition / reset / reachability / action state not in the FSM
``semantic_reference``    reference to a non-existent Semantic IR v2 object
``behavior_reference``    reference to a non-existent Behavioral Semantics v1 object
``structural_reference``  reference to a non-existent Structural Analysis v1 object
``broken_reference``      other reference to a non-existent FSM object
``provenance``            missing location / input reference
``absolute_path``         absolute or machine-local path
``path_traversal``        ``.`` / ``..`` path segment
``encoding``              encoding classification contradicts the state values
``consistency``           status / quality / state-set / transition contradiction
``evidence``              classification without the required evidence
``naming``                FSM supported by ``name_hint`` evidence only
``semantic_consistency``  document disagrees with its Semantic IR v2 input
``behavior_consistency``  document disagrees with its Behavioral Semantics v1 input
``structural_consistency`` document disagrees with its Structural Analysis v1 input
``ordering``              section or id list not in canonical order
``inventory``             document / canonical-module mismatch (corpus)
``semantic_input``        Semantic IR v2 input missing or unsupported (corpus)
``behavior_input``        Behavioral Semantics v1 input missing or unsupported (corpus)
``structural_input``      Structural Analysis v1 input missing or unsupported (corpus)
``stale``                 document differs from a re-analysis of the current inputs
``nondeterministic``      bytes differ from the canonical serialisation
``leakage``               FSM dataset dependency across splits (corpus)
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

from scripts.fsm import model as F

_ABS = re.compile(r"^(/|[A-Za-z]:[/\\]|\\\\|~)")
VERSIONS = {"schema": F.SCHEMA_VERSION, "identity": F.IDENTITY_VERSION, "analyzer": F.ANALYZER_VERSION,
            "provenance": F.PROVENANCE_VERSION, "semantic_ir": F.SEMANTIC_IR_VERSION,
            "semantic_identity": F.SEMANTIC_IDENTITY_VERSION, "behavior": F.BEHAVIOR_VERSION,
            "behavior_identity": F.BEHAVIOR_IDENTITY_VERSION, "structural": F.STRUCTURAL_VERSION,
            "structural_identity": F.STRUCTURAL_IDENTITY_VERSION}
INPUTS = (("semantic_ir", F.SEMANTIC_IR_VERSION, F.SEMANTIC_IDENTITY_VERSION),
          ("behavior", F.BEHAVIOR_VERSION, F.BEHAVIOR_IDENTITY_VERSION),
          ("structural", F.STRUCTURAL_VERSION, F.STRUCTURAL_IDENTITY_VERSION))

REQUIRED = {
    "fsms": ("id", "status", "quality", "style", "register", "next_signal", "clock", "reset", "enable", "hold",
             "encoding", "states", "transitions", "outputs", "actions", "reachability", "evidence", "unknowns",
             "fingerprint", "loc"),
    "states": ("id", "value", "width", "name", "aliases", "constant", "declared", "observed", "reachability",
               "reset", "loc"),
    "transitions": ("id", "source", "target", "kind", "guard", "priority", "assignment", "hold", "process",
                    "status", "rendered", "loc"),
    "outputs": ("id", "signal", "name", "kind", "state_sources", "other_sources", "loc"),
    "actions": ("id", "state", "signal", "assignment", "kind", "guard", "loc"),
    "couplings": ("id", "from_fsm", "to_fsm", "kind", "refs"),
    "rejected": ("id", "register", "signal", "name", "reason", "name_hint", "evidence", "loc"),
}
GUARD_FIELDS = ("statement", "predicate", "kind", "branch", "item", "tests_state", "values", "qualifier", "role")
ENUMS = {
    ("fsms", "status"): F.STATUS, ("fsms", "quality"): F.QUALITY, ("fsms", "style"): F.STYLES,
    ("fsms", "hold"): F.HOLD,
    ("states", "reachability"): F.REACHABILITY,
    ("transitions", "kind"): F.TRANSITION_KINDS, ("transitions", "status"): F.TRANSITION_STATUS,
    ("outputs", "kind"): F.OUTPUT_KINDS, ("actions", "kind"): F.ACTION_KINDS,
    ("couplings", "kind"): F.COUPLING_KINDS, ("rejected", "reason"): F.REJECTION_REASONS,
}


def _ids(node, out):
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


def _records(doc):
    """(section, record, owner fsm) for every identified record."""
    for f in doc["fsms"]:
        yield "fsms", f, None
        if isinstance(f, dict):
            for s in F.FSM_LISTS:
                for r in f.get(s) or []:
                    yield s, r, f
    for s in ("couplings", "rejected"):
        for r in doc[s]:
            yield s, r, None


def expected_id(section, rec, owner):
    if section == "fsms":
        return F.fsm_id("fsm", (rec.get("register") or {}).get("register", ""))
    if section == "states":
        return F.fsm_id("state", owner["id"], str(rec["value"]))
    if section == "transitions":
        extra = ",".join(f"{e.get('statement')}:{e.get('branch')}" for e in rec["guard"] if e.get("kind") == "ternary")
        anchor = rec["hold"] if rec["hold"] else rec["assignment"]
        return F.fsm_id("transition", anchor or "", f"{rec['source']}>{rec['target']}:{rec['kind']}:{extra}")
    if section == "outputs":
        return F.fsm_id("output", owner["id"], rec["signal"])
    if section == "actions":
        return F.fsm_id("action", rec["assignment"], f"{owner['id']}:{rec['state']}:{rec['signal']}")
    if section == "couplings":
        return F.fsm_id("coupling", rec["from_fsm"], f"{rec['to_fsm']}:{rec['kind']}")
    if section == "rejected":
        return F.fsm_id("rejection", rec["register"])
    return None


def _validate_fsm(f, p, sids, bids, tids, preds, ports, beh_regs):
    fid = f["id"]
    reg = f["register"] or {}
    states = {s["id"]: s for s in f["states"]}
    pseudo = set(F.PSEUDO_STATES)
    # ---- register / state register
    for k in ("signal", "name", "width", "register", "structural_register", "process"):
        if k not in reg:
            p.append(("required", f"fsm {fid}: register.{k} missing"))
            return
    if reg["signal"] not in sids or reg["process"] not in sids:
        p.append(("semantic_reference", f"fsm {fid}: register signal / process not in Semantic IR"))
    if reg["register"] not in beh_regs:
        p.append(("behavior_reference", f"fsm {fid}: register {reg['register']} is not a behavioral register"))
    elif beh_regs[reg["register"]]["signal"] != reg["signal"]:
        p.append(("behavior_consistency", f"fsm {fid}: register signal differs from Behavioral Semantics"))
    if reg["structural_register"] is not None and reg["structural_register"] not in tids:
        p.append(("structural_reference", f"fsm {fid}: structural register unknown"))
    ns = f["next_signal"]
    if (f["style"] == "two_process") != (ns is not None):
        p.append(("consistency", f"fsm {fid}: style {f['style']} with next_signal {ns!r}"))
    if ns is not None and (ns.get("signal") not in sids or ns.get("signal") == reg["signal"]):
        p.append(("semantic_reference", f"fsm {fid}: next-state signal invalid"))
    if f["clock"] is not None and f["clock"].get("clock") not in bids:
        p.append(("behavior_reference", f"fsm {fid}: clock unknown"))
    for e in f["enable"]:
        if e.get("enable") not in bids or e.get("condition") not in sids:
            p.append(("behavior_reference", f"fsm {fid}: enable {e.get('enable')} unknown"))
    # ---- reset
    rs = f["reset"]
    if rs.get("kind") not in F.RESET_KINDS:
        p.append(("enum", f"fsm {fid}: reset.kind {rs.get('kind')!r}"))
    if rs.get("reset") is not None and rs["reset"] not in bids:
        p.append(("behavior_reference", f"fsm {fid}: reset {rs['reset']} unknown"))
    if (rs.get("kind") == "none") != (rs.get("reset") is None):
        p.append(("consistency", f"fsm {fid}: reset kind {rs.get('kind')} with reset {rs.get('reset')!r}"))
    if rs.get("state") is not None and rs["state"] not in states:
        p.append(("state_reference", f"fsm {fid}: reset state {rs['state']} not an FSM state"))
    if any(a not in sids for a in rs.get("assignments", [])):
        p.append(("semantic_reference", f"fsm {fid}: reset assignment not in Semantic IR"))
    reset_states = {s["id"] for s in f["states"] if s["reset"]}
    if rs.get("state") is not None and reset_states != {rs["state"]}:
        p.append(("consistency", f"fsm {fid}: reset state flag disagrees with reset.state"))
    # ---- states / encoding
    enc = f["encoding"]
    for k, voc in (("status", F.ENCODING_STATUS), ("style", F.ENCODING_STYLE), ("source", F.ENCODING_SOURCE)):
        if enc.get(k) not in voc:
            p.append(("enum", f"fsm {fid}: encoding.{k} {enc.get(k)!r}"))
    values = []
    for s in f["states"]:
        c = s["constant"] or {}
        if not isinstance(s["value"], int) or s["value"] < 0:
            p.append(("consistency", f"state {s['id']}: value {s['value']!r} is not a resolved constant"))
            continue
        values.append(s["value"])
        if c.get("kind") not in F.CONSTANT_KINDS:
            p.append(("enum", f"state {s['id']}: constant.kind {c.get('kind')!r}"))
        elif c.get("kind") == "literal":
            if c.get("ref") is not None or s["name"] is not None:
                p.append(("consistency", f"state {s['id']}: literal state with a constant reference / name"))
        elif c.get("ref") not in sids:
            p.append(("semantic_reference", f"state {s['id']}: constant {c.get('ref')} not in Semantic IR"))
        if s["declared"] != (c.get("kind") != "literal"):
            p.append(("consistency", f"state {s['id']}: declared flag contradicts its constant"))
        if s["width"] != reg["width"]:
            p.append(("consistency", f"state {s['id']}: width differs from the state register"))
        if s["aliases"] != sorted(s["aliases"]):
            p.append(("ordering", f"state {s['id']}: aliases not sorted"))
    if len(set(values)) != len(values):
        p.append(("consistency", f"fsm {fid}: two states with one value"))
    if enc.get("width") != reg["width"]:
        p.append(("encoding", f"fsm {fid}: encoding width differs from the state register"))
    moves = [(states[t["source"]]["value"], states[t["target"]]["value"]) for t in f["transitions"]
             if t["source"] in states and t["target"] in states and t["source"] != t["target"]]
    if enc.get("status") in ("explicit", "inferred"):
        want = F.encoding_style(values, reg["width"], moves)
        if enc.get("style") != want:
            p.append(("encoding", f"fsm {fid}: encoding style {enc.get('style')} but the values are {want}"))
        kinds = {(s["constant"] or {}).get("kind") for s in f["states"]}
        if (enc["status"] == "explicit") != ("literal" not in kinds):
            p.append(("encoding", f"fsm {fid}: encoding status {enc['status']} contradicts the state constants"))
    elif enc.get("style") != "unknown":
        p.append(("encoding", f"fsm {fid}: unknown encoding status with style {enc.get('style')}"))
    # ---- transitions
    for t in f["transitions"]:
        for end in ("source", "target"):
            if t[end] not in states and t[end] not in pseudo:
                p.append(("state_reference", f"transition {t['id']}: {end} {t[end]} not an FSM state"))
        if t["target"] in ("*reset", "*none"):
            p.append(("consistency", f"transition {t['id']}: pseudo state {t['target']} as target"))
        if (t["kind"] == "reset") != (t["source"] == "*reset"):
            p.append(("consistency", f"transition {t['id']}: kind {t['kind']} with source {t['source']}"))
        if t["kind"] in ("explicit_hold", "implicit_hold") and t["source"] in states and t["source"] != t["target"]:
            p.append(("consistency", f"transition {t['id']}: hold to another state"))
        if t["assignment"] is None and t["hold"] is None:
            p.append(("provenance", f"transition {t['id']}: no originating assignment or hold"))
        if t["assignment"] is not None and t["assignment"] not in sids:
            p.append(("semantic_reference", f"transition {t['id']}: assignment not in Semantic IR"))
        if t["hold"] is not None and t["hold"] not in bids:
            p.append(("behavior_reference", f"transition {t['id']}: hold not in Behavioral Semantics"))
        if t["process"] not in sids:
            p.append(("semantic_reference", f"transition {t['id']}: process not in Semantic IR"))
        if t["priority"] is not None and (not isinstance(t["priority"], int) or t["priority"] < 0):
            p.append(("consistency", f"transition {t['id']}: priority {t['priority']!r}"))
        if (t["source"] == "*unknown") and t["status"] != "unknown":
            p.append(("consistency", f"transition {t['id']}: unknown source with status {t['status']}"))
        if not isinstance(t["rendered"], str):
            p.append(("required", f"transition {t['id']}: rendered predicate missing"))
        _validate_guard(t["guard"], f"transition {t['id']}", p, sids, preds, states)
    # ---- reachability (graph only, AC-040 .. AC-047)
    rc = f["reachability"]
    if rc.get("basis") != "graph" or rc.get("status") not in F.REACH_STATUS:
        p.append(("enum", f"fsm {fid}: reachability basis/status {rc.get('basis')!r}/{rc.get('status')!r}"))
    if rc.get("start") != rs.get("state"):
        p.append(("consistency", f"fsm {fid}: reachability does not start at the reset state"))
    for k in ("reachable", "unreachable"):
        if any(s not in states for s in rc.get(k, [])):
            p.append(("state_reference", f"fsm {fid}: reachability.{k} references an unknown state"))
        if rc.get(k) != sorted(rc.get(k, [])):
            p.append(("ordering", f"fsm {fid}: reachability.{k} not sorted"))
    edges = defaultdict(set)
    for t in f["transitions"]:
        if t["source"] in states and t["target"] in states:
            edges[t["source"]].add(t["target"])
    reach, todo = set(), [rc.get("start")] if rc.get("start") in states else []
    while todo:
        n = todo.pop()
        if n not in reach:
            reach.add(n)
            todo.extend(edges[n])
    if set(rc.get("reachable", [])) != reach:
        p.append(("consistency", f"fsm {fid}: reachable set is not the graph closure of the reset state"))
    for s in f["states"]:
        want = "graph_reachable" if s["id"] in reach else ("graph_unreachable" if rc.get("status") == "known" else "unknown")
        if s["reachability"] != want:
            p.append(("consistency", f"state {s['id']}: reachability {s['reachability']} (expected {want})"))
    if rc.get("status") == "known" and set(rc.get("unreachable", [])) != set(states) - reach:
        p.append(("consistency", f"fsm {fid}: unreachable set inconsistent"))
    if rc.get("status") == "unknown" and rc.get("unreachable"):
        p.append(("consistency", f"fsm {fid}: unreachable states claimed with unknown reachability"))
    # ---- outputs / actions
    for o in f["outputs"]:
        if reg["signal"] not in o["state_sources"]:
            p.append(("consistency", f"output {o['id']}: not derived from the state register"))
        if any(x not in sids for x in o["state_sources"] + o["other_sources"]):
            p.append(("semantic_reference", f"output {o['id']}: source not in Semantic IR"))
        if o["kind"] == "moore" and any(ports.get(x, {}).get("direction") == "input" for x in o["other_sources"]):
            p.append(("consistency", f"output {o['id']}: Moore output with module-input sources"))
        if o["kind"] == "mealy" and not any(ports.get(x, {}).get("direction") in ("input", "inout") for x in o["other_sources"]):
            p.append(("consistency", f"output {o['id']}: Mealy output without input sources"))
    for a in f["actions"]:
        if a["state"] not in states and a["state"] != "*unknown":
            p.append(("state_reference", f"action {a['id']}: state {a['state']} not an FSM state"))
        if a["signal"] not in sids or a["assignment"] not in sids:
            p.append(("semantic_reference", f"action {a['id']}: signal / assignment not in Semantic IR"))
        _validate_guard(a["guard"], f"action {a['id']}", p, sids, preds, states)
        if not any(e.get("tests_state") for e in a["guard"]):
            p.append(("evidence", f"action {a['id']}: no guard over the state register"))
    # ---- evidence / status / quality
    codes = Counter()
    for e in f["evidence"]:
        if e.get("code") not in F.EVIDENCE or not isinstance(e.get("refs"), list) or not e["refs"]:
            p.append(("evidence", f"fsm {fid}: invalid evidence {e.get('code')!r}"))
            continue
        codes[e["code"]] = e.get("count", 0)
        for r in e["refs"]:
            if not (r in sids or r in bids or r in tids):
                p.append(("provenance", f"fsm {fid}: evidence {e['code']} references unknown {r}"))
                break
    if set(codes) <= {"name_hint"}:
        p.append(("naming", f"fsm {fid}: supported by its name only"))
    ident = "behavior_state_candidate" in codes or "predicate_over_register" in codes
    if not ident or "closed_loop" not in codes:
        p.append(("evidence", f"fsm {fid}: identification (A or B) / closed-loop evidence missing"))
    if f["status"] == "confirmed" and codes.get("resolved_state_values", 0) < 2:
        p.append(("evidence", f"fsm {fid}: confirmed with fewer than two resolved state values"))
    if f["status"] == "confirmed" and "trivial_state_domain" in codes:
        p.append(("evidence", f"fsm {fid}: confirmed on a trivial (1-bit literal) state domain"))
    if f["status"] == "candidate" and codes.get("resolved_state_values", 0) >= 2 and "trivial_state_domain" not in codes:
        p.append(("consistency", f"fsm {fid}: candidate although two resolved state values exist"))
    unk_tr = any("*unknown" in (t["source"], t["target"]) for t in f["transitions"])
    want = {"candidate": "low", "ambiguous": "ambiguous", "unsupported": "unsupported"}.get(f["status"])
    if f["status"] == "confirmed":
        high = enc.get("status") == "explicit" and rs.get("state") is not None and not unk_tr and \
            not any(u.get("kind") == "incomplete_domain" for u in f["unknowns"])
        want = "high" if high else "medium"
    if f["quality"] != want:
        p.append(("consistency", f"fsm {fid}: quality {f['quality']} (expected {want} for status {f['status']})"))
    for u in f["unknowns"]:
        if u.get("kind") not in F.UNKNOWN_KINDS or u.get("count") != len(u.get("refs", [])) or not u.get("refs"):
            p.append(("enum", f"fsm {fid}: unknown record {u.get('kind')!r}"))
    if [u.get("kind") for u in f["unknowns"]] != sorted({u.get("kind") for u in f["unknowns"]}):
        p.append(("ordering", f"fsm {fid}: unknowns not one sorted record per kind"))
    if unk_tr and not f["unknowns"]:
        p.append(("consistency", f"fsm {fid}: unknown transitions without unknown records"))


def _validate_guard(guard, where, p, sids, preds, states):
    if not isinstance(guard, list):
        p.append(("required", f"{where}: guard path is not a list"))
        return
    for e in guard:
        if not isinstance(e, dict) or any(k not in e for k in GUARD_FIELDS):
            p.append(("required", f"{where}: malformed guard entry"))
            continue
        if e["kind"] not in F.GUARD_KINDS or e["branch"] not in F.GUARD_BRANCHES:
            p.append(("enum", f"{where}: guard kind/branch {e['kind']!r}/{e['branch']!r}"))
        if e["statement"] not in sids:
            p.append(("semantic_reference", f"{where}: guard statement {e['statement']} not in Semantic IR"))
        if e["predicate"] is not None and preds.get(e["predicate"]) != e["statement"]:
            p.append(("structural_reference", f"{where}: predicate {e['predicate']} unknown or for another statement"))
        if e["kind"] not in ("ternary", "loop") and e["predicate"] is None:
            p.append(("structural_reference", f"{where}: control guard without its structural predicate"))
        if e["values"] is not None and (not e["tests_state"] or any(v not in states for v in e["values"])):
            p.append(("state_reference", f"{where}: guard values reference unknown states"))
        if (e["branch"] == "item") != (e["item"] is not None):
            p.append(("consistency", f"{where}: guard branch {e['branch']} with item {e['item']!r}"))


def validate_module(doc, sem=None, sem_rel=None, sem_sha=None, beh=None, beh_rel=None, beh_sha=None,
                    st=None, st_rel=None, st_sha=None) -> list:
    from scripts.fsm import analyzer as A

    p = []
    if not isinstance(doc, dict):
        return [("schema", "document is not a JSON object")]
    if doc.get("schema") != {"name": F.SCHEMA_NAME, "version": F.SCHEMA_VERSION}:
        return [("schema", f"unsupported FSM schema {doc.get('schema')!r}")]
    if doc.get("versions") != VERSIONS:
        p.append(("schema", f"unsupported versions block {doc.get('versions')!r}"))
    if (doc.get("generator") or {}).get("analyzer") != F.ANALYZER:
        p.append(("schema", "unsupported analyzer"))
    missing = [k for k in ("module", "counts", "notes", "fingerprint", "id") + F.SECTIONS if k not in doc]
    if missing:
        return p + [("required", f"missing {', '.join(missing)}")]
    for s in F.SECTIONS:
        if not isinstance(doc[s], list):
            return p + [("required", f"section {s} is not a list")]
    if doc["notes"] != {k: (doc["notes"] or {}).get(k) for k in F.NOTES} or \
            any(not isinstance(v, int) for v in doc["notes"].values()):
        p.append(("required", "notes block malformed"))

    # ------------------------------------------------------------- module / input provenance
    m = doc["module"]
    for key in ("ip", "name", "module_id", "semantic_id", "loc", "source", "semantic_ir", "behavior", "structural"):
        if key not in m:
            p.append(("provenance", f"module.{key} missing"))
    if any(c == "provenance" for c, _ in p):
        return p
    if not F.MODULE_ID_RE.fullmatch(str(m["module_id"])):
        p.append(("identity", f"module_id {m['module_id']!r}"))
    if not F.SEM_RE.fullmatch(str(m["semantic_id"])):
        p.append(("identity", f"module.semantic_id {m['semantic_id']!r}"))
    if not _loc_ok(m["loc"]):
        p.append(("provenance", "module.loc"))
    _path_problems("module.source", (m["source"] or {}).get("path"), p)
    for key, ver, idv in INPUTS:
        ref = m[key] or {}
        _path_problems(f"module.{key}", ref.get("path"), p)
        if not F.SHA_RE.fullmatch(str(ref.get("sha256"))):
            p.append(("provenance", f"module.{key}.sha256 missing or malformed"))
        if (ref.get("schema_version"), ref.get("identity_version")) != (ver, idv):
            p.append(("schema", f"module.{key}: unsupported input version {ref.get('schema_version')!r}"))
    if not F.STR_RE.fullmatch(str((m["structural"] or {}).get("structural_id"))):
        p.append(("identity", "module.structural.structural_id malformed"))
    if not F.ID_RE.fullmatch(str(doc["id"])) or not F.ID_RE.fullmatch(str(doc["fingerprint"])):
        p.append(("identity", "document id / fingerprint malformed"))

    # ------------------------------------------------------------- per record
    seen = Counter()
    prev = {}
    for s, rec, owner in _records(doc):
        if not isinstance(rec, dict):
            p.append(("required", f"{s}: record is not an object"))
            continue
        miss = [k for k in REQUIRED[s] if k not in rec]
        if miss:
            p.append(("required", f"{s} {rec.get('id')}: missing {', '.join(miss)}"))
            continue
        rid = rec["id"]
        seen[rid] += 1
        if not F.ID_RE.fullmatch(str(rid)):
            p.append(("identity", f"{s}: malformed identity {rid!r}"))
        else:
            try:
                ok = expected_id(s, rec, owner) == rid
            except (KeyError, TypeError, AttributeError):
                ok = False
            if not ok:
                p.append(("identity", f"{s} {rid}: identity does not derive from its anchor"))
        key = (s, owner["id"] if owner else None)
        okey = (rec["value"], "") if s == "states" else (0, str(rid))   # states: by encoded value
        if key in prev and okey <= prev[key]:
            p.append(("ordering", f"{s}: {rid} out of canonical order"))
        prev[key] = okey
        for (sec, field), allowed in ENUMS.items():
            if sec == s and rec[field] not in allowed:
                p.append(("enum", f"{s} {rid}: {field}={rec[field]!r}"))
        if "loc" in REQUIRED[s]:
            if not _loc_ok(rec["loc"]):
                p.append(("provenance", f"{s} {rid}: missing or invalid location"))
            else:
                _path_problems(f"{s} {rid}.loc", rec["loc"]["file"], p)
    for rid, n in seen.items():
        if n > 1:
            p.append(("duplicate_identity", f"{rid} used {n} times"))
    if any(c in ("required", "schema") for c, _ in p):
        return p

    # ------------------------------------------------------------- counts / fingerprints / document identity
    try:
        if doc["counts"] != A.counts(doc):
            p.append(("consistency", "counts do not match the document"))
        for f in doc["fsms"]:
            if f["fingerprint"] != A.fsm_fingerprint(f):
                p.append(("identity", f"fsm {f['id']}: fingerprint does not match its shape"))
        if doc["fingerprint"] != A.fingerprint(doc):
            p.append(("identity", "fingerprint does not match the document"))
    except (KeyError, TypeError, AttributeError) as exc:
        p.append(("required", f"cannot recompute counts / fingerprint ({exc})"))
    if F.document_id(doc) != doc["id"]:
        p.append(("identity", "document identity is not the content hash of the document"))

    # ------------------------------------------------------------- upstream inputs
    sids = _ids(sem, set()) if sem is not None else None
    bids = _ids(beh, set()) if beh is not None else None
    tids = _ids(st, set()) if st is not None else None
    for doc_in, rel, sha, key, code in ((sem, sem_rel, sem_sha, "semantic_ir", "semantic_consistency"),
                                        (beh, beh_rel, beh_sha, "behavior", "behavior_consistency"),
                                        (st, st_rel, st_sha, "structural", "structural_consistency")):
        if doc_in is None:
            continue
        if sha is not None and m[key]["sha256"] != sha:
            p.append((code, f"derived from a different {key} revision (sha256)"))
        if rel is not None and m[key]["path"] != rel:
            p.append((code, f"{key} path is not {rel}"))
        if (doc_in.get("module") or {}).get("module_id") != m["module_id"]:
            p.append((code, f"module does not match its {key} input"))
    if sem is not None:
        sm = sem.get("module") or {}
        if (sm.get("ip"), sm.get("name"), sm.get("id")) != (m["ip"], m["name"], m["semantic_id"]):
            p.append(("semantic_consistency", "module does not match its Semantic IR"))
        if (sm.get("source") or {}) != m["source"]:
            p.append(("semantic_consistency", "source provenance differs from Semantic IR"))
    if st is not None and st.get("id") != m["structural"]["structural_id"]:
        p.append(("structural_consistency", "structural_id differs from the Structural Analysis document"))
    if sem is None or beh is None or st is None:
        return p
    preds = {q["id"]: q["statement"] for q in st.get("predicates", [])}
    ports = {x["id"]: x for x in sem.get("ports", [])}
    out_ports = {k: v for k, v in ports.items() if v.get("direction") in ("output", "inout")}
    beh_regs = {r["id"]: r for r in beh.get("registers", [])}
    for f in doc["fsms"]:
        _validate_fsm(f, p, sids, bids, tids, preds, ports, beh_regs)
        for o in f["outputs"]:
            if o["signal"] not in out_ports:
                p.append(("semantic_reference", f"output {o['id']}: {o['signal']} is not an output port"))
    regs_used = Counter(f["register"]["register"] for f in doc["fsms"]) + Counter(r["register"] for r in doc["rejected"])
    for r, n in regs_used.items():
        if n > 1:
            p.append(("consistency", f"register {r} is both an FSM and rejected, or recorded twice"))
    fsm_ids = {f["id"] for f in doc["fsms"]}
    for c in doc["couplings"]:
        if c["from_fsm"] not in fsm_ids or c["to_fsm"] not in fsm_ids or c["from_fsm"] == c["to_fsm"]:
            p.append(("broken_reference", f"coupling {c['id']}: FSM references invalid"))
        if not c["refs"] or c["refs"] != sorted(set(c["refs"])) or any(r not in tids for r in c["refs"]):
            p.append(("structural_reference", f"coupling {c['id']}: evidence references invalid"))
    for r in doc["rejected"]:
        if r["register"] not in beh_regs or beh_regs[r["register"]]["signal"] != r["signal"]:
            p.append(("behavior_reference", f"rejected {r['id']}: register unknown"))
        for e in r["evidence"]:
            if e.get("code") not in F.EVIDENCE or any(x not in sids and x not in bids for x in e.get("refs", [])):
                p.append(("evidence", f"rejected {r['id']}: invalid evidence"))
    return p


# =============================================================================
# corpus
# =============================================================================

def fsm_root(root: Path) -> Path:
    return root / F.OUTPUT_DIR


def corpus_sha256(data_root) -> str:
    root = Path(os.path.abspath(data_root))
    h = hashlib.sha256()
    base = fsm_root(root)
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


SPLIT_MANIFEST = "splits/split_manifest.json"
STRUCTURAL_REPORT = "analysis/reports/structural_report.json"


def leakage(data_root, fingerprints: dict) -> dict:
    """KF-DQ-004 integration (AC-216 .. AC-222): FSM shape fingerprints vs. splits.

    ``fingerprints`` maps (ip, module) -> [per-FSM fingerprint].  FSM shapes
    occurring in modules of more than one split are reported as soft findings
    (no dataset record consumes FSM information yet); a dataset record that
    declares an ``fsm`` provenance dependency on such a module is a hard
    ``leakage`` failure.  The KF-DQ-010 structural findings are carried over
    unchanged and never promoted (AC-219).
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
    groups = defaultdict(set)
    for key, fps in sorted(fingerprints.items()):
        for fp in fps:
            groups[fp].add(key)
    cross = []
    for fp, mods in sorted(groups.items()):
        splits = sorted({s for k in mods for s in split.get(k, ())})
        if len(splits) > 1:
            cross.append({"fingerprint": fp, "modules": [f"{ip}/{m}" for ip, m in sorted(mods)], "splits": splits,
                          "classification": "soft"})
    crossing = {m for c in cross for m in c["modules"]}
    dependent, problems = 0, []
    for sp, _, rec in iter_dataset_records(root):
        ref = (rec.get("provenance") or {}).get("fsm")
        if ref is None:
            continue
        dependent += 1
        key = f"{rec.get('ip')}/{rec.get('module')}"
        if key in crossing:
            problems.append(f"record {(rec.get('provenance') or {}).get('record_id')} ({sp}) depends on FSM data "
                            f"of {key}, whose FSM shape also occurs in another split")
    structural = {"status": "SKIPPED", "reason": f"{STRUCTURAL_REPORT} not present"}
    sp = root / STRUCTURAL_REPORT
    if sp.is_file():
        lk = (json.loads(sp.read_text(encoding="utf-8")).get("leakage") or {})
        structural = {"status": lk.get("status"), "classification": "soft",
                      "cross_split_fingerprints": len(lk.get("cross_split_fingerprints", [])),
                      "structural_dependent_records": lk.get("structural_dependent_records")}
    return {
        "status": "FAIL" if problems else "PASS",
        "split_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "fsm_fingerprints": len(groups),
        "shared_fsm_fingerprints": sum(1 for v in groups.values() if len(v) > 1),
        "cross_split_fingerprints": cross,
        "fsm_dependent_records": dependent,
        "structural_findings": structural,
        "problems": problems,
    }


def check(data_root, with_leakage: bool = True) -> dict:
    from scripts.core.paths import find_absolute_paths
    from scripts.core.provenance import module_id
    from scripts.fsm import analyzer as A

    root = Path(os.path.abspath(data_root))
    base = fsm_root(root)
    canonical = set(A.canonical_modules(root))
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
        if F.dumps(doc) != text:
            problems.append(("nondeterministic", f"{rel}: not in canonical serialisation"))
        if find_absolute_paths(text):
            problems.append(("absolute_path", f"{rel}: absolute path in document"))
        try:
            inputs = A.load_inputs(root, *key)
        except A.AnalysisError as exc:
            msg = str(exc)
            code = "structural_input" if "Structural" in msg else "behavior_input" if "Behavioral" in msg else "semantic_input"
            problems.append((code, f"{rel}: {exc}"))
            continue
        m = doc.get("module") if isinstance(doc, dict) else None
        if isinstance(m, dict) and m.get("module_id") != module_id(*key):
            problems.append(("identity", f"{rel}: module identity does not match {key[0]}/{key[1]}"))
        found = validate_module(doc, *inputs)
        for code, msg in found:
            problems.append((code, f"{rel}: {msg}"))
        try:
            fresh = F.dumps(A.analyze(*inputs))
        except A.AnalysisError as exc:
            problems.append(("stale", f"{rel}: inputs no longer analysable ({exc})"))
            continue
        if fresh != text:
            problems.append(("stale", f"{rel}: differs from a re-analysis of the current upstream evidence"))
        if not isinstance(doc, dict) or "counts" not in doc:
            continue
        totals["modules"] += 1
        totals["modules_with_fsms"] += 1 if doc["fsms"] else 0
        for k, v in (doc.get("counts") or {}).items():
            totals[k] += v
        for f in doc.get("fsms", []):
            totals[f"encoding_{(f.get('encoding') or {}).get('style')}"] += 1
            totals[f"style_{f.get('style')}"] += 1
            for o in f.get("outputs", []):
                totals[f"output_{o.get('kind')}"] += 1
            for t in f.get("transitions", []):
                totals[f"transition_{t.get('kind')}"] += 1
                totals["transitions_unknown"] += 1 if "*unknown" in (t.get("source"), t.get("target")) else 0
            if (f.get("reset") or {}).get("state"):
                totals["reset_state_known"] += 1
            if (f.get("reachability") or {}).get("status") == "known":
                totals["reachability_known"] += 1
        for k, v in (doc.get("notes") or {}).items():
            totals[f"note_{k}"] += v
        objects = doc["counts"].get("objects", 0)
        bad_prov = sum(1 for c, _ in found if c in ("provenance", "absolute_path", "path_traversal"))
        bad_ref = sum(1 for c, _ in found if c.endswith("_reference"))
        prov["objects"] += objects
        prov["missing"] += bad_prov
        prov["invalid_references"] += bad_ref
        prov["valid"] += max(0, objects - bad_prov - bad_ref)
        fingerprints[key] = [f.get("fingerprint") for f in doc.get("fsms", [])]
    totals["ips"] = len({k[0] for k in present})
    for key in sorted(canonical - present):
        problems.append(("inventory", f"missing FSM Analysis v1 for {key[0]}/{key[1]}"))
    leak = {"status": "SKIPPED", "reason": "not requested", "problems": []}
    if with_leakage:
        leak = leakage(root, fingerprints)
        problems += [("leakage", x) for x in leak["problems"]]
    codes = Counter(c for c, _ in problems)
    coverage = (prov["valid"] / prov["objects"]) if prov["objects"] else 0.0
    return {
        "schema": {"name": F.SCHEMA_NAME, "version": F.SCHEMA_VERSION},
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
    path = Path(os.path.abspath(data_root)) / F.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_report(report: dict) -> str:
    t = report["totals"]
    keys = ["ips", "modules", "modules_with_fsms", "fsms", "confirmed", "candidate", "ambiguous", "unsupported",
            "quality_high", "quality_medium", "quality_low", "states", "transitions", "transitions_unknown",
            "outputs", "output_moore", "output_mealy", "output_ambiguous", "actions", "couplings", "rejected",
            "rejected_arithmetic_feedback", "rejected_no_state_predicate", "rejected_name_only",
            "rejected_no_closed_loop", "reset_state_known", "reachability_known"]
    pv = report["provenance"]
    lk = report["leakage"]
    lines = [f"FSM Analysis v1 check: {report['status']} (schema {F.SCHEMA_NAME} v{F.SCHEMA_VERSION})",
             f"  {'canonical modules':28s}: {report['canonical_modules']}",
             f"  {'documents':28s}: {report['documents']}"]
    lines += [f"  {k.replace('_', ' '):28s}: {t.get(k, 0)}" for k in keys]
    lines.append(f"  {'provenance coverage':28s}: {pv['valid']}/{pv['objects']} valid, {pv['missing']} missing, "
                 f"{pv['invalid_references']} invalid references")
    if lk.get("status") == "SKIPPED":
        lines.append(f"  {'leakage':28s}: SKIPPED ({lk.get('reason')})")
    else:
        sf = lk.get("structural_findings") or {}
        lines.append(f"  {'leakage':28s}: {lk['status']} ({lk['fsm_dependent_records']} FSM-dependent records; "
                     f"{len(lk['cross_split_fingerprints'])} FSM shapes span splits (soft); "
                     f"KF-DQ-010 structural groups preserved: {sf.get('cross_split_fingerprints', 'n/a')} (soft))")
    lines += [f"  [FAIL] {x}" for x in report["problems"][:30]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-011 FSM Analysis v1 validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate (default)")
    parser.add_argument("--json", help="also write the report JSON here")
    parser.add_argument("--write-report", action="store_true", help=f"write <data-root>/{F.REPORT_PATH}")
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
