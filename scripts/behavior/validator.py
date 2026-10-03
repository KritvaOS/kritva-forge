#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : validator.py
# Description : Behavioral Semantics v1 schema, reference and consistency validation (KF-DQ-009)
#
# Component   : Kritva Forge
# Module      : behavior
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 validation (criteria sections 30 and 31) - fail closed.

``validate_module(doc, semantic_doc)`` returns ``[(code, message), ...]``;
``check(data_root)`` validates every document under ``normalized/behavior/v1``
against the canonical module inventory and the current Semantic IR v2 and is
the ``make check-behavior`` gate.

Codes:

========================  =====================================================
``schema``                unsupported schema / Semantic IR / identity version
``required``              missing section or field
``enum``                  value outside an enumeration
``identity``              malformed ``beh1:`` / ``sem1:`` / ``mod1:`` identity
``duplicate_identity``    one behavioral identity used twice
``provenance``            missing location / source / Semantic IR reference
``absolute_path``         absolute or machine-local path
``path_traversal``        ``.`` / ``..`` path segment
``broken_reference``      reference to a non-existent behavioral or Semantic IR object
``event``                 clock / reset event index or edge inconsistent with the process events
``clock``                 clock signal is not the event signal / invalid clock record
``reset``                 reset signal, kind or condition inconsistent with control structure
``role_conflict``         process role / confidence contradicts its evidence
``evidence``              non-unknown classification without evidence
``naming``                classification supported by ``name_hint`` evidence only
``enable_hold``           enable / hold record without matching hold evidence
``priority``              reset leaf not ahead of update / hold leaves, broken ranks
``consistency``           register / combinational / latch record contradicts its process
``semantic_consistency``  output disagrees with its Semantic IR v2 document
``ordering``              section not in canonical order
``inventory``             document / canonical-module mismatch (corpus)
``semantic_input``        Semantic IR v2 input missing or unsupported (corpus)
``stale``                 document differs from a re-analysis of the current Semantic IR
``nondeterministic``      bytes differ from the canonical serialisation
========================  =====================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

from scripts.behavior import model as B

_SHA = re.compile(r"[0-9a-f]{64}")


def _path_problem(path) -> str | None:
    if not isinstance(path, str) or not path:
        return "provenance"
    if path.startswith("/") or os.path.isabs(path) or "\\" in path or re.match(r"^[A-Za-z]:", path):
        return "absolute_path"
    if any(p in ("..", ".") for p in PurePosixPath(path).parts):
        return "path_traversal"
    return None


def _same(a, b) -> bool:
    from scripts.behavior.analyzer import _same as same
    return same(a, b)


def validate_module(doc: dict, sem: dict | None = None, semantic_sha256: str | None = None) -> list:
    """Validate one Behavioral Semantics v1 document (optionally against its Semantic IR v2)."""
    problems = []

    def bad(code, msg):
        problems.append((code, msg))

    if not isinstance(doc, dict):
        return [("schema", "document is not an object")]
    if doc.get("schema") != {"name": B.SCHEMA_NAME, "version": B.SCHEMA_VERSION}:
        return [("schema", f"unsupported behavioral schema {doc.get('schema')!r}")]
    for key in ("versions", "generator", "module", "counts") + B.SECTIONS:
        if key not in doc:
            bad("required", f"missing section {key}")
    if problems:
        return problems
    v = doc["versions"]
    if v.get("schema") != B.SCHEMA_VERSION or v.get("semantic_ir") != B.SEMANTIC_IR_VERSION \
            or v.get("semantic_identity") != B.SEMANTIC_IDENTITY_VERSION:
        bad("schema", f"unsupported versions {v!r}")
    if v.get("identity") != B.IDENTITY_VERSION:
        bad("identity", f"unsupported behavioral identity version {v.get('identity')!r}")

    # ---------------------------------------------------------------- module / provenance
    m = doc["module"]
    if not isinstance(m.get("module_id"), str) or not B.MODULE_ID_RE.fullmatch(m["module_id"]):
        bad("identity", f"invalid module identity {m.get('module_id')!r}")
    if not isinstance(m.get("semantic_id"), str) or not B.SEM_RE.fullmatch(m["semantic_id"]):
        bad("identity", f"invalid Semantic IR module identity {m.get('semantic_id')!r}")
    for key in ("source", "semantic_ir"):
        ref = m.get(key)
        if not isinstance(ref, dict):
            bad("provenance", f"module.{key} missing")
            continue
        code = _path_problem(ref.get("path"))
        if code:
            bad(code, f"module.{key}.path {ref.get('path')!r}")
        if not isinstance(ref.get("sha256"), str) or not _SHA.fullmatch(ref["sha256"]):
            bad("provenance", f"module.{key}.sha256 {ref.get('sha256')!r}")
    if (m.get("semantic_ir") or {}).get("schema_version") != B.SEMANTIC_IR_VERSION:
        bad("schema", f"source Semantic IR version {(m.get('semantic_ir') or {}).get('schema_version')!r}")

    ids = Counter()
    objs = {}

    def check_loc(o, where):
        loc = o.get("loc")
        if not isinstance(loc, dict) or "file" not in loc or not loc.get("line"):
            bad("provenance", f"{where}: missing source location")
            return
        code = _path_problem(loc.get("file"))
        if code:
            bad(code, f"{where}: provenance path {loc.get('file')!r}")

    def check_evidence(o, where, required=True):
        ev = o.get("evidence")
        if not isinstance(ev, list):
            bad("required", f"{where}: evidence missing")
            return set()
        codes = set()
        for e in ev:
            if not isinstance(e, dict) or e.get("code") not in B.EVIDENCE or not isinstance(e.get("refs"), list):
                bad("enum", f"{where}: malformed evidence {str(e)[:60]}")
                continue
            codes.add(e["code"])
            for r in e["refs"]:
                if not isinstance(r, str) or not B.SEM_RE.fullmatch(r):
                    bad("identity", f"{where}: evidence reference {r!r}")
        if required and not codes:
            bad("evidence", f"{where}: classification without evidence")
        elif required and codes == {"name_hint"}:
            bad("naming", f"{where}: classification supported by naming evidence only")
        return codes

    for section in B.SECTIONS:
        for o in doc[section]:
            oid = o.get("id")
            where = f"{section}:{o.get('name') or oid}"
            if not isinstance(oid, str) or not B.ID_RE.fullmatch(oid):
                bad("identity", f"{where}: invalid behavioral identity {oid!r}")
            else:
                ids[oid] += 1
                objs[oid] = (section, o)
            check_loc(o, where)
        if doc[section] != sorted(doc[section], key=B.loc_key):
            bad("ordering", f"{section} not in canonical (file, line, column, id) order")
    for oid, n in ids.items():
        if n > 1:
            bad("duplicate_identity", f"behavioral identity {oid} used {n} times")

    def kind_of(oid):
        return objs.get(oid, (None, None))[0]

    procs = {p["id"]: p for p in doc["processes"]}
    regs = {r["id"]: r for r in doc["registers"]}

    # ---------------------------------------------------------------- semantic index (optional)
    S = None
    if sem is not None:
        try:
            from scripts.behavior.analyzer import _Sem
            S = _Sem(sem)
        except Exception as exc:                          # noqa: BLE001 - reported as a finding
            bad("semantic_consistency", f"Semantic IR input unusable: {exc}")
        if S is not None:
            sm = sem["module"]
            if (m.get("module_id"), m.get("semantic_id"), m.get("name"), m.get("ip")) != \
                    (sm.get("module_id"), sm.get("id"), sm.get("name"), sm.get("ip")):
                bad("semantic_consistency", "module identity differs from the Semantic IR module")
            if m.get("source") != sm.get("source"):
                bad("semantic_consistency", "source provenance differs from the Semantic IR module")
            if semantic_sha256 is not None and (m.get("semantic_ir") or {}).get("sha256") != semantic_sha256:
                bad("semantic_consistency", "Semantic IR sha256 is not the analysed document")
            sem_procs = {p["id"]: p for p in sem["processes"]}
            got = Counter(p.get("process") for p in doc["processes"])
            for pid in sorted(set(sem_procs) ^ set(got), key=str):
                bad("semantic_consistency", f"process {pid}: Semantic IR and behavioral processes disagree")
            for pid, n in got.items():
                if n > 1:
                    bad("duplicate_identity", f"process {pid} classified {n} times")

    def sem_has(sid, pool):
        return S is None or sid in pool

    # ---------------------------------------------------------------- processes
    for p in doc["processes"]:
        where = f"process {p.get('process')}"
        for f in ("role", "confidence", "process", "kind", "evidence", "reads", "writes", "conditional_reads",
                  "conditional_writes", "registered_targets", "combinational_targets", "latch_targets",
                  "clocks", "resets", "registers", "enables", "holds", "assignments", "conditions", "cases"):
            if f not in p:
                bad("required", f"{where}: missing {f}")
        if p.get("role") not in B.ROLES:
            bad("enum", f"{where}: role {p.get('role')!r}")
        if p.get("confidence") not in B.CONFIDENCE:
            bad("enum", f"{where}: confidence {p.get('confidence')!r}")
        role, conf = p.get("role"), p.get("confidence")
        codes = check_evidence(p, where, required=True)
        if S is not None and p.get("process") not in {x["id"] for x in sem["processes"]}:
            bad("broken_reference", f"{where}: Semantic IR process does not exist")
            continue
        sp = next((x for x in (sem or {}).get("processes", []) if x["id"] == p.get("process")), None) if S else None
        edges = [e for e in (sp or {}).get("events", []) if e.get("edge") in ("posedge", "negedge", "edge")]
        if S is not None and sp is not None:
            if sp["kind"] != p.get("kind"):
                bad("semantic_consistency", f"{where}: kind {p.get('kind')!r} differs from Semantic IR {sp['kind']!r}")
            if sorted(p.get("assignments", [])) != sorted(a["id"] for a in sem["assignments"] if a["process"] == sp["id"]):
                bad("semantic_consistency", f"{where}: assignment list differs from Semantic IR")
            for a in p.get("assignments", []):
                if a not in S.assign:
                    bad("broken_reference", f"{where}: assignment {a} does not exist")
            for st in p.get("conditions", []) + p.get("cases", []):
                if st not in S.stmts:
                    bad("broken_reference", f"{where}: statement {st} does not exist")
            for key in ("reads", "writes", "conditional_reads", "conditional_writes"):
                for sid in p.get(key, []):
                    if sid not in S.decl:
                        bad("broken_reference", f"{where}: {key} symbol {sid} does not exist")
        # role / evidence consistency (criteria 7, 24)
        if role in ("unknown", "ambiguous") and conf != "unknown":
            bad("role_conflict", f"{where}: {role} process with confidence {conf}")
        if role == "sequential":
            if "edge_event" not in codes or p.get("kind") in ("always_comb", "always_latch", "initial", "final"):
                bad("role_conflict", f"{where}: sequential without edge-event evidence or with kind {p.get('kind')}")
            if S is not None and sp is not None and not edges:
                bad("role_conflict", f"{where}: sequential but the Semantic IR process has no edge event")
            if conf == "high" and not (p.get("kind") == "always_ff" and "nonblocking_assignments" in codes):
                bad("role_conflict", f"{where}: high confidence requires always_ff + nonblocking assignments")
        if role in ("combinational", "latch"):
            if "edge_event" in codes or (S is not None and edges):
                bad("role_conflict", f"{where}: {role} process with edge events")
        if role == "latch" and not ({"keyword_always_latch", "incomplete_assignment"} & set(
                c["code"] for r in doc["latches"] if r.get("process") == p["id"] for c in r.get("evidence", []))
                or "keyword_always_latch" in codes):
            bad("role_conflict", f"{where}: latch role without always_latch or incomplete-assignment evidence")
        if role == "initialization" and p.get("kind") not in ("initial", "final"):
            bad("role_conflict", f"{where}: initialization role for kind {p.get('kind')}")
        if role == "combinational" and p.get("kind") == "always" and not (
                {"implicit_sensitivity", "complete_sensitivity"} & codes):
            bad("role_conflict", f"{where}: generic always classified combinational without sensitivity evidence")
        for key, sec in (("clocks", "clocks"), ("resets", "resets"), ("registers", "registers"),
                         ("enables", "enables"), ("holds", "holds")):
            for oid in p.get(key, []):
                if kind_of(oid) != sec:
                    bad("broken_reference", f"{where}: {key} entry {oid} does not exist")

    # ---------------------------------------------------------------- clocks
    for c in doc["clocks"]:
        where = f"clock {c.get('name')}"
        if c.get("edge") not in B.EDGES:
            bad("event", f"{where}: edge {c.get('edge')!r}")
        if c.get("status") not in B.STATUS:
            bad("enum", f"{where}: status {c.get('status')!r}")
        codes = check_evidence(c, where)
        if c.get("process") not in procs:
            bad("broken_reference", f"{where}: process {c.get('process')} does not exist")
            continue
        p = procs[c["process"]]
        if p.get("role") != "sequential":
            bad("consistency", f"{where}: clock of a {p.get('role')} process")
        if c.get("status") == "confirmed" and "event_signal_not_read" not in codes:
            bad("clock", f"{where}: confirmed clock without event-structure evidence")
        if S is not None:
            if c.get("signal") not in S.decl:
                bad("clock", f"{where}: clock signal {c.get('signal')} is not a port/signal")
            sp = next((x for x in sem["processes"] if x["id"] == p["process"]), None)
            evs = (sp or {}).get("events", [])
            i = c.get("event")
            if not isinstance(i, int) or not 0 <= i < len(evs):
                bad("event", f"{where}: event index {i!r} outside the process event list")
            else:
                e = evs[i]
                if e.get("edge") != c.get("edge"):
                    bad("event", f"{where}: edge {c.get('edge')} differs from event {e.get('edge')}")
                x = e.get("expr") or {}
                tgt = x.get("target") if x.get("op") == "ref" else (x.get("base") or {}).get("target")
                if tgt != c.get("signal"):
                    bad("clock", f"{where}: clock signal is not the event signal")

    # ---------------------------------------------------------------- resets
    for r in doc["resets"]:
        where = f"reset {r.get('name')}"
        if r.get("kind") not in B.RESET_KINDS:
            bad("enum", f"{where}: kind {r.get('kind')!r}")
        if r.get("polarity") not in B.POLARITY:
            bad("enum", f"{where}: polarity {r.get('polarity')!r}")
        if r.get("status") not in B.STATUS:
            bad("enum", f"{where}: status {r.get('status')!r}")
        codes = check_evidence(r, where)
        if r.get("status") == "confirmed" and not {"reset_branch_constant", "edge_polarity_match"} <= codes:
            bad("reset", f"{where}: confirmed reset without constant-branch and edge-polarity evidence")
        if r.get("kind") == "sync" and r.get("status") == "confirmed":
            bad("reset", f"{where}: synchronous resets are candidates, never confirmed by structure alone")
        if r.get("process") not in procs:
            bad("broken_reference", f"{where}: process {r.get('process')} does not exist")
            continue
        if S is not None:
            if r.get("signal") not in S.decl:
                bad("reset", f"{where}: reset signal {r.get('signal')} is not a port/signal")
            st = S.stmts.get(r.get("condition"))
            if st is None or st.get("stmt") != "if":
                bad("reset", f"{where}: condition {r.get('condition')} is not an if statement")
            else:
                from scripts.behavior.analyzer import signal_test
                t = signal_test(st.get("cond"), S.decl)
                if not t or t[0] != r.get("signal") or t[1] != r.get("polarity"):
                    bad("reset", f"{where}: condition does not test the reset signal with polarity {r.get('polarity')}")
            sp = next((x for x in sem["processes"] if x["id"] == procs[r["process"]]["process"]), None)
            ev_sigs = {(e.get("expr") or {}).get("target") for e in (sp or {}).get("events", [])}
            if (r.get("kind") == "async") != (r.get("signal") in ev_sigs):
                bad("reset", f"{where}: {r.get('kind')} reset but event-list membership disagrees")
            for x in r.get("targets", []):
                a = S.assign.get(x.get("assignment"))
                if a is None or x.get("signal") not in a["writes"]:
                    bad("broken_reference", f"{where}: reset target assignment {x.get('assignment')} invalid")

    # ---------------------------------------------------------------- registers
    holds = {h["id"]: h for h in doc["holds"]}
    for g in doc["registers"]:
        where = f"register {g.get('name')}"
        for f, enum in (("update", B.UPDATE_KINDS), ("hold", B.HOLD_KINDS), ("confidence", B.CONFIDENCE),
                        ("candidate", ("register_candidate",))):
            if g.get(f) not in enum:
                bad("enum", f"{where}: {f} {g.get(f)!r}")
        check_evidence(g, where)
        p = procs.get(g.get("process"))
        if p is None:
            bad("broken_reference", f"{where}: process {g.get('process')} does not exist")
            continue
        if p.get("role") != "sequential":
            bad("consistency", f"{where}: register target of a {p.get('role')} process")
        if g.get("clock") is not None and kind_of(g["clock"]) != "clocks":
            bad("broken_reference", f"{where}: clock {g.get('clock')} does not exist")
        for key, sec in (("resets", "resets"), ("enables", "enables"), ("holds", "holds"), ("next_values", "next_values")):
            for oid in g.get(key, []):
                if kind_of(oid) != sec:
                    bad("broken_reference", f"{where}: {key} entry {oid} does not exist")
        if S is not None:
            for a in g.get("assignments", []):
                sa = S.assign.get(a.get("assignment"))
                if sa is None:
                    bad("broken_reference", f"{where}: assignment {a.get('assignment')} does not exist")
                elif g.get("signal") not in sa["writes"] or sa["process"] != p["process"]:
                    bad("semantic_consistency", f"{where}: assignment {sa['id']} does not write the register in its process")
                elif sa["kind"] != a.get("kind"):
                    bad("semantic_consistency", f"{where}: assignment kind {a.get('kind')} differs from Semantic IR")
        # priority (criteria 15 / 16)
        pr = g.get("priority", [])
        if [x.get("rank") for x in pr] != list(range(len(pr))):
            bad("priority", f"{where}: priority ranks are not 0..n-1")
        reset_conds = {doc_r["condition"] for doc_r in doc["resets"] if doc_r["id"] in g.get("resets", [])}
        seen_other = False
        for x in pr:
            if x.get("kind") not in B.LEAF_KINDS:
                bad("enum", f"{where}: priority kind {x.get('kind')!r}")
            if x.get("kind") == "reset":
                if seen_other:
                    bad("priority", f"{where}: reset leaf after an update/hold leaf")
                gs = x.get("guards") or []
                if not gs or gs[0].get("statement") not in reset_conds or gs[0].get("branch") != "then":
                    bad("priority", f"{where}: reset leaf not under the reset condition")
            else:
                seen_other = True
        for hid in g.get("holds", []):
            h = holds.get(hid)
            if h and h.get("register") != g["id"]:
                bad("enable_hold", f"{where}: hold {hid} belongs to another register")
        hk = {holds[h]["kind"] for h in g.get("holds", []) if h in holds}
        want = {"none": set(), "explicit": {"explicit"}, "implicit": {"implicit"}, "mixed": {"explicit", "implicit"}}
        if g.get("hold") in want and hk != want[g["hold"]]:
            bad("enable_hold", f"{where}: hold kind {g.get('hold')} disagrees with hold records {sorted(hk)}")

    # ---------------------------------------------------------------- holds / enables / next values
    for h in doc["holds"]:
        where = f"hold {h.get('id')}"
        if h.get("kind") not in ("explicit", "implicit"):
            bad("enum", f"{where}: kind {h.get('kind')!r}")
        if h.get("register") not in regs:
            bad("broken_reference", f"{where}: register {h.get('register')} does not exist")
            continue
        if h.get("kind") == "implicit" and (h.get("assignment") is not None or not h.get("guards")):
            bad("enable_hold", f"{where}: implicit hold must name the missing branch and no assignment")
        if h.get("kind") == "explicit":
            if not h.get("assignment"):
                bad("enable_hold", f"{where}: explicit hold without a self-assignment")
            elif S is not None:
                a = S.assign.get(h["assignment"])
                if a is None:
                    bad("broken_reference", f"{where}: assignment {h['assignment']} does not exist")
                elif not _same(a.get("value"), a.get("target")):
                    bad("enable_hold", f"{where}: explicit hold assignment is not a self-assignment")
    for e in doc["enables"]:
        where = f"enable {e.get('id')}"
        g = regs.get(e.get("register"))
        if g is None:
            bad("broken_reference", f"{where}: register {e.get('register')} does not exist")
            continue
        if e.get("update_branch") not in ("then", "else") or e.get("hold_branch") not in ("then", "else") \
                or e.get("update_branch") == e.get("hold_branch"):
            bad("enable_hold", f"{where}: invalid update/hold branches")
        if S is not None and e.get("condition") not in S.conditions:
            bad("enable_hold", f"{where}: condition {e.get('condition')} is not a conditional statement")
        hs = [holds[h] for h in g.get("holds", []) if h in holds]
        if not any(any(x.get("statement") == e.get("condition") and x.get("branch") == e.get("hold_branch")
                       for x in h.get("guards", [])) for h in hs):
            bad("enable_hold", f"{where}: no hold on the {e.get('hold_branch')} branch of the enable condition")
    for n in doc["next_values"]:
        where = f"next_value {n.get('id')}"
        if n.get("register") not in regs:
            bad("broken_reference", f"{where}: register {n.get('register')} does not exist")
        if n.get("value") not in B.VALUE_KINDS:
            bad("enum", f"{where}: value {n.get('value')!r}")
        if S is not None:
            a = S.assign.get(n.get("assignment"))
            if a is None:
                bad("broken_reference", f"{where}: assignment {n.get('assignment')} does not exist")
            elif n.get("signal") not in a["writes"]:
                bad("semantic_consistency", f"{where}: assignment does not write {n.get('signal')}")

    # ---------------------------------------------------------------- combinational / latches / candidates
    combs = {c["id"]: c for c in doc["combinational"]}
    for c in doc["combinational"]:
        where = f"combinational {c.get('name')}"
        if c.get("completeness") not in B.COMPLETENESS:
            bad("enum", f"{where}: completeness {c.get('completeness')!r}")
        if c.get("latch") not in B.LATCH_STATUS:
            bad("enum", f"{where}: latch {c.get('latch')!r}")
        check_evidence(c, where)
        p = procs.get(c.get("process"))
        if p is None:
            bad("broken_reference", f"{where}: process {c.get('process')} does not exist")
            continue
        if p.get("role") not in ("combinational", "latch"):
            bad("consistency", f"{where}: combinational target of a {p.get('role')} process")
        if c.get("completeness") == "complete" and c.get("missing"):
            bad("consistency", f"{where}: complete target with missing branches")
        if c.get("completeness") == "incomplete" and not c.get("missing"):
            bad("consistency", f"{where}: incomplete target without missing branches")
    for lt in doc["latches"]:
        where = f"latch {lt.get('name')}"
        if lt.get("status") not in B.LATCH_STATUS or lt.get("status") == "none":
            bad("enum", f"{where}: status {lt.get('status')!r}")
        codes = check_evidence(lt, where)
        if lt.get("combinational") not in combs:
            bad("broken_reference", f"{where}: combinational record {lt.get('combinational')} does not exist")
        if lt.get("status") == "explicit" and "keyword_always_latch" not in codes:
            bad("consistency", f"{where}: explicit latch without always_latch evidence")
        if lt.get("status") == "inferred" and "incomplete_assignment" not in codes:
            bad("consistency", f"{where}: inferred latch without incomplete-assignment evidence")
    for c in doc["candidates"]:
        where = f"candidate {c.get('name')}"
        if c.get("kind") not in ("state_candidate", "next_value_candidate"):
            bad("enum", f"{where}: kind {c.get('kind')!r}")
        if c.get("confidence") not in B.CONFIDENCE:
            bad("enum", f"{where}: confidence {c.get('confidence')!r}")
        codes = check_evidence(c, where)
        if c.get("kind") == "state_candidate":
            if c.get("register") not in regs:
                bad("broken_reference", f"{where}: register {c.get('register')} does not exist")
            if not {"selector_feedback", "constant_state_values", "finite_width"} <= codes:
                bad("evidence", f"{where}: state candidate without feedback / constant-value / width evidence")
        else:
            if kind_of(c.get("state")) != "candidates":
                bad("broken_reference", f"{where}: state candidate {c.get('state')} does not exist")

    # ---------------------------------------------------------------- counts
    from scripts.behavior.analyzer import counts
    if doc["counts"] != counts(doc):
        bad("consistency", "counts disagree with the document")
    return problems


# =============================================================================
# corpus gate
# =============================================================================

def behavior_root(data_root) -> Path:
    return Path(os.path.abspath(data_root)) / B.OUTPUT_DIR


def corpus_sha256(data_root) -> str:
    root = Path(os.path.abspath(data_root))
    h = hashlib.sha256()
    base = behavior_root(root)
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


def check(data_root) -> dict:
    from scripts.behavior import analyzer as A
    from scripts.core.paths import find_absolute_paths
    from scripts.core.provenance import module_id

    root = Path(os.path.abspath(data_root))
    base = behavior_root(root)
    canonical = set(A.canonical_modules(root))
    problems, totals, present = [], Counter(), set()
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
        if B.dumps(doc) != text:
            problems.append(("nondeterministic", f"{rel}: not in canonical serialisation"))
        if find_absolute_paths(text):
            problems.append(("absolute_path", f"{rel}: absolute path in document"))
        srel = A.semantic_rel(*key)
        spath = root / srel
        if not spath.is_file():
            problems.append(("semantic_input", f"{rel}: Semantic IR input {srel} missing"))
            continue
        raw = spath.read_bytes()
        sem = json.loads(raw)
        if (doc.get("module") or {}).get("semantic_ir", {}).get("path") != srel:
            problems.append(("semantic_consistency", f"{rel}: Semantic IR path is not {srel}"))
        for code, msg in validate_module(doc, sem, hashlib.sha256(raw).hexdigest()):
            problems.append((code, f"{rel}: {msg}"))
        if (doc.get("module") or {}).get("module_id") != module_id(*key):
            problems.append(("identity", f"{rel}: module identity does not match {key[0]}/{key[1]}"))
        try:
            fresh = B.dumps(A.analyze(sem, srel, hashlib.sha256(raw).hexdigest()))
        except A.AnalysisError as exc:
            problems.append(("semantic_input", f"{rel}: {exc}"))
            continue
        if fresh != text:
            problems.append(("stale", f"{rel}: differs from a re-analysis of the current Semantic IR"))
        totals["modules"] += 1
        for k, v in (doc.get("counts") or {}).items():
            totals[k] += v
        for p in doc.get("processes", []):
            totals[f"process:{p.get('kind')}:{p.get('role')}"] += 1
        for r in doc.get("resets", []):
            totals[f"reset:{r.get('kind')}:{r.get('polarity')}:{r.get('status')}"] += 1
        for g in doc.get("registers", []):
            totals[f"register_update:{g.get('update')}"] += 1
            totals[f"register_hold:{g.get('hold')}"] += 1
            totals[f"register_confidence:{g.get('confidence')}"] += 1
    for key in sorted(canonical - present):
        problems.append(("inventory", f"missing Behavioral Semantics v1 for {key[0]}/{key[1]}"))
    codes = Counter(c for c, _ in problems)
    return {
        "schema": {"name": B.SCHEMA_NAME, "version": B.SCHEMA_VERSION},
        "canonical_modules": len(canonical),
        "documents": len(files),
        "corpus_sha256": corpus_sha256(root),
        "totals": dict(sorted(totals.items())),
        "problem_counts": dict(sorted(codes.items())),
        "problems": [f"[{c}] {m}" for c, m in problems[:200]],
        "status": "FAIL" if problems else "PASS",
    }


def write_report(data_root, report: dict) -> Path:
    path = Path(os.path.abspath(data_root)) / B.REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def format_report(report: dict) -> str:
    t = report["totals"]
    keys = ["modules", "processes", "role_sequential", "role_combinational", "role_latch", "role_initialization",
            "role_generic", "role_unknown", "role_ambiguous", "confidence_high", "confidence_medium",
            "confidence_low", "confidence_unknown", "clocks", "clocks_confirmed", "clocks_candidate",
            "clocks_ambiguous", "resets", "resets_async", "resets_sync", "resets_confirmed", "resets_candidate",
            "resets_ambiguous", "registers", "next_values", "enables", "holds", "holds_explicit", "holds_implicit",
            "combinational_targets", "combinational_complete", "combinational_conditional",
            "combinational_incomplete", "combinational_ambiguous", "latches", "latches_explicit",
            "latches_inferred", "latches_possible", "latches_ambiguous", "state_candidates", "next_value_candidates"]
    lines = [f"Behavioral Semantics v1 check: {report['status']} (schema {B.SCHEMA_NAME} v{B.SCHEMA_VERSION})",
             f"  {'canonical modules':24s}: {report['canonical_modules']}",
             f"  {'documents':24s}: {report['documents']}"]
    lines += [f"  {k.replace('_', ' '):24s}: {t.get(k, 0)}" for k in keys]
    lines += [f"  [FAIL] {p}" for p in report["problems"][:30]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KF-DQ-009 Behavioral Semantics v1 validator")
    parser.add_argument("--data-root", default=os.environ.get("KRITVA_FORGE_DATA_ROOT"))
    parser.add_argument("--check", action="store_true", help="validate (default)")
    parser.add_argument("--json", help="also write the report JSON here")
    parser.add_argument("--write-report", action="store_true", help=f"write <data-root>/{B.REPORT_PATH}")
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
