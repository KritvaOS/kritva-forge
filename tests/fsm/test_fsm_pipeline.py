# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_fsm_pipeline.py
# Description : FSM Analysis v2 pipeline, stale, manifest v5 and leakage integration tests (KF-DQ-011)
#
# Component   : Kritva Forge
# Module      : tests/fsm
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""FSM Analysis v2 in the pipeline (criteria sections 22 - 25, 27, 28).

* every canonical module gets a document (zero-FSM modules included);
* A/B and relocation: byte-identical ``normalized/fsm/v2`` trees and report;
* Semantic IR, Behavioral Semantics, Structural Analysis, IR v1 and raw RTL
  are not modified;
* stale gate: tampered, obsolete, out-of-date (any of the three inputs),
  stray and missing FSM documents block publication (no override);
* data manifest v5: every module references its FSM document; record FSM
  dependencies must name the current artifact;
* KF-DQ-004 leakage: FSM shapes across splits are soft findings; a record
  depending on such FSM data fails the FSM gate.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.behavior import model as BM
from scripts.core import data_manifest as DM
from scripts.core import stale_artifacts as S
from scripts.fsm import analyzer as A
from scripts.fsm import model as F
from scripts.fsm import validator as V
from scripts.semantic_ir import model as SM
from scripts.structural import model as TM
from tests.data.test_data_manifest import _make_data_root, _run


def _fsm_module(name):
    return f"""module {name}(input clk, input rst_n, input go, output busy);
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  reg [1:0] st;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= IDLE;
    else case (st) IDLE: if (go) st <= RUN; RUN: st <= DONE; DONE: st <= IDLE; default: st <= IDLE; endcase
  assign busy = (st == RUN);
endmodule
"""


def _make_root(base):
    """The KF-DQ-007 scratch repository plus an IP with five FSM modules of one shape."""
    root = _make_data_root(base)
    ipf = root / "raw" / "rtl" / "original" / "ipf"
    ipf.mkdir(parents=True)
    names = [f"ipf_f{i}" for i in range(5)]
    (ipf / "ipf.sv").write_text("".join(_fsm_module(n) for n in names))
    (ipf / "files.f").write_text("ipf.sv\n")
    return root


def _digest(root: Path, sub: str) -> dict:
    base = root / sub
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_root(tmp_path_factory.mktemp("fsmA")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return dest


def _state(root, rel):
    return next(e for e in S.classify(root)["entries"] if e["path"] == rel)


def test_pipeline_writes_valid_fsm_documents_for_every_module(built):
    rep = json.loads((built.root / F.REPORT_PATH).read_text())
    assert rep["status"] == "PASS", rep["problems"]
    ir = sorted(p.stem for p in (built.root / "normalized" / "ir").rglob("modules/*.yaml"))
    fs = sorted(p.stem for p in (built.root / F.OUTPUT_DIR).rglob("*.json"))
    assert ir == fs and rep["documents"] == len(fs)
    assert rep["totals"]["fsms"] == 5 and rep["totals"]["confirmed"] == 5 and rep["totals"]["modules_with_fsms"] == 5
    zero = json.loads((built.root / F.OUTPUT_DIR / "ipa" / "ipa_m0.json").read_text())
    assert zero["fsms"] == [] and zero["counts"]["fsms"] == 0                    # AC-020 / AC-192
    assert rep["provenance"]["valid"] == rep["provenance"]["objects"] and rep["leakage"]["status"] == "PASS"
    assert V.check(built.root)["status"] == "PASS"


def test_ab_determinism(built, tmp_path):
    b = _run(_make_root(tmp_path / "B"))
    assert _digest(b.root, F.OUTPUT_DIR) == _digest(built.root, F.OUTPUT_DIR)
    assert (b.root / F.REPORT_PATH).read_bytes() == (built.root / F.REPORT_PATH).read_bytes()


def test_relocation(built, tmp_path):
    r = _run(_make_root(tmp_path / "x" / "y" / "elsewhere"))
    assert _digest(r.root, F.OUTPUT_DIR) == _digest(built.root, F.OUTPUT_DIR)
    for p in (r.root / F.OUTPUT_DIR).rglob("*.json"):
        assert str(r.root) not in p.read_text()


def test_inputs_are_not_modified(tree):
    subs = (SM.OUTPUT_DIR, BM.OUTPUT_DIR, TM.OUTPUT_DIR, "normalized/ir", "raw")
    before = {sub: _digest(tree, sub) for sub in subs}
    A.write_all(tree)
    assert {sub: _digest(tree, sub) for sub in subs} == before


# ----------------------------------------------------------------------------- stale gate (AC-207 .. AC-215)
def test_fsm_documents_are_current(built):
    states = [e for e in S.classify(built.root)["entries"] if e["kind"] == "fsm"]
    assert states and all(e["state"] == "CURRENT" for e in states)
    assert _state(built.root, F.REPORT_PATH)["state"] == "CURRENT"


def test_tampered_document_is_stale(tree):
    rel = f"{F.OUTPUT_DIR}/ipf/ipf_f0.json"
    doc = json.loads((tree / rel).read_text())
    doc["counts"]["states"] += 1
    (tree / rel).write_text(F.dumps(doc))
    assert _state(tree, rel)["state"] == "STALE"
    assert _state(tree, F.REPORT_PATH)["state"] == "STALE"


@pytest.mark.parametrize("sub,dumps,what", [
    (SM.OUTPUT_DIR, SM.dumps, "Semantic IR"),
    (BM.OUTPUT_DIR, BM.dumps, "Behavioral Semantics"),
    (TM.OUTPUT_DIR, TM.dumps, "Structural Analysis"),
])
def test_upstream_change_makes_fsm_stale(tree, sub, dumps, what):
    rel = f"{sub}/ipf/ipf_f1.json"
    d = json.loads((tree / rel).read_text())
    d.setdefault("notes", {})["edited"] = 1
    (tree / rel).write_text(dumps(d))
    e = _state(tree, f"{F.OUTPUT_DIR}/ipf/ipf_f1.json")
    assert e["state"] == "STALE"
    assert what in e["reason"] or "input unavailable" in e["reason"]


def test_obsolete_schema_or_analyzer_is_stale(tree):
    rel = f"{F.OUTPUT_DIR}/ipf/ipf_f2.json"
    doc = json.loads((tree / rel).read_text())
    doc["versions"]["analyzer"] = 0
    (tree / rel).write_text(F.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE" and "obsolete FSM schema" in e["reason"]


def test_stray_and_missing_fsm_files(tree):
    (tree / F.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    (tree / "normalized" / "fsm" / "notes.txt").write_text("x\n")
    (tree / F.OUTPUT_DIR / "ipc" / "ipc_m0.json").unlink()
    assert _state(tree, f"{F.OUTPUT_DIR}/ipa/not_a_module.json")["state"] == "ORPHAN"
    assert _state(tree, "normalized/fsm/notes.txt")["state"] == "UNMANAGED"
    assert f"{F.OUTPUT_DIR}/ipc/ipc_m0.json" in S.classify(tree)["missing"]
    assert S.check(tree)["status"] == "FAIL"


def test_obsolete_v1_tree_is_stale(tree):
    """KF-DQ-011.1 I1: FSM v2 is the only canonical tree; a leftover v1 document fails both gates."""
    src = tree / F.OUTPUT_DIR / "ipf" / "ipf_f0.json"
    old = tree / "normalized" / "fsm" / "v1" / "ipf" / "ipf_f0.json"
    old.parent.mkdir(parents=True)
    old.write_bytes(src.read_bytes())
    e = _state(tree, "normalized/fsm/v1/ipf/ipf_f0.json")
    assert e["state"] == "STALE" and "obsolete FSM Analysis v1" in e["reason"]
    assert S.check(tree)["status"] == "FAIL"
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and any("obsolete FSM Analysis layout" in p for p in rep["problems"])


def test_pipeline_publishes_only_v2(built):
    assert not (built.root / "normalized" / "fsm" / "v1").exists()
    docs = [json.loads(p.read_text()) for p in (built.root / F.OUTPUT_DIR).rglob("*.json")]
    assert docs and all(d["schema"] == {"name": F.SCHEMA_NAME, "version": 2} for d in docs)
    outs = [o for d in docs for f in d["fsms"] for o in f["outputs"]]
    assert outs and all(isinstance(o["registered"], bool) and isinstance(o["sampled_sources"], list) for o in outs)


def test_stale_fsm_blocks_publication(tree, monkeypatch):
    """A stray FSM document fails the FSM gate even with the stale override (AC-249)."""
    (tree / F.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")
    with pytest.raises(RuntimeError, match="KF-DQ-011"):
        _run(tree)


def test_split_change_makes_report_stale(tree):
    path = tree / "splits" / "split_manifest.json"
    path.write_text(path.read_text() + " ")
    assert _state(tree, F.REPORT_PATH)["state"] == "STALE"


# ----------------------------------------------------------------------------- data manifest v5 (AC-197 .. AC-206)
def test_manifest_v5_references_fsm(built):
    m = json.loads((built.root / DM.MANIFEST_PATH).read_text())
    assert m["schema"] == {"name": "kritva-forge-data-manifest", "version": 5}
    assert (m["versions"]["fsm"], m["versions"]["fsm_identity"], m["versions"]["fsm_analyzer"]) == (2, 1, 2)
    arts = {a["path"]: a for a in m["artifacts"]}
    for mod in m["modules"]:
        f = mod["fsm"]
        doc = json.loads((built.root / f["path"]).read_text())
        assert f["path"] == f"{F.OUTPUT_DIR}/{mod['ip']}/{mod['module']}.json" and f["fsm_id"] == doc["id"]
        assert (f["schema_version"], f["identity_version"], f["analyzer_version"], f["provenance_version"]) == (2, 1, 2, 1)
        assert (f["status"], f["module_id"]) == ("canonical", mod["module_id"])
        assert f["derived_from"] == {
            "semantic_ir": mod["semantic_ir"]["path"], "semantic_ir_sha256": mod["semantic_ir"]["sha256"],
            "behavior": mod["behavior"]["path"], "behavior_sha256": mod["behavior"]["sha256"],
            "structural": mod["structural"]["path"], "structural_sha256": mod["structural"]["sha256"]}
        assert arts[f["path"]]["kind"] == "fsm" and arts[f["path"]]["sha256"] == f["sha256"]
        assert arts[f["path"]]["status"] == "canonical"
    assert arts[F.REPORT_PATH]["kind"] == "fsm_report"
    assert all("fsm" not in r for r in m["records"])                 # no record consumes FSM data yet
    assert DM.check(built.root)["status"] == "PASS"


def test_manifest_detects_fsm_mismatch(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["modules"][0]["fsm"]["derived_from"]["structural_sha256"] = "0" * 64
    m["modules"][1]["fsm"]["fsm_id"] = "fsm1:0000000000000000"
    m["modules"][2]["fsm"]["sha256"] = "0" * 64
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = DM.check(tree)
    assert rep["status"] == "FAIL" and rep["broken_references"] >= 3


def test_record_fsm_traceability(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    rec = m["records"][0]
    mod = next(x for x in m["modules"] if x["module_id"] == rec["module_id"])
    rec["fsm"] = {"path": mod["fsm"]["path"], "sha256": mod["fsm"]["sha256"]}
    assert DM.check(tree, m)["broken_references"] == 0
    rec["fsm"]["sha256"] = "0" * 64                                    # not the exact artifact used
    rep = DM.check(tree, m)
    assert rep["status"] == "FAIL" and rep["broken_references"] == 1


def test_manifest_v4_is_rejected(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["schema"]["version"] = 4
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    assert DM.check(tree)["schema_errors"]


# ----------------------------------------------------------------------------- KF-DQ-004 leakage (AC-216 .. AC-222)
def _move_apart(tree, a, b):
    """Put module b into a split other than module a's."""
    sm_path = tree / "splits" / "split_manifest.json"
    sm = json.loads(sm_path.read_text())
    where = {f"{r['ip']}/{r['module']}": s for s in ("train", "validation", "test") for r in sm[s]}
    if where[a] != where[b]:
        return where
    other = next(s for s in ("train", "validation", "test") if s != where[a])
    moved = next(r for r in sm[where[b]] if f"{r['ip']}/{r['module']}" == b)
    sm[where[b]].remove(moved)
    sm[other].append(moved)
    sm_path.write_text(json.dumps(sm))
    where[b] = other
    return where


def test_leakage_report_and_fsm_dependency(tree):
    rep = V.check(tree)
    lk = rep["leakage"]
    assert lk["status"] == "PASS" and lk["fsm_dependent_records"] == 0 and lk["shared_fsm_fingerprints"] == 1
    assert lk["structural_findings"]["classification"] == "soft"     # KF-DQ-010 findings carried, not promoted
    where = _move_apart(tree, "ipf/ipf_f0", "ipf/ipf_f1")
    lk = V.check(tree)["leakage"]
    cross = [c for c in lk["cross_split_fingerprints"] if {"ipf/ipf_f0", "ipf/ipf_f1"} <= set(c["modules"])]
    assert lk["status"] == "PASS" and cross and cross[0]["classification"] == "soft"
    # a dataset record that consumes FSM data of that shape must fail (hard)
    path = tree / "datasets" / "pipeline" / f"{where['ipf/ipf_f0']}.jsonl"
    out, hit = [], 0
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if f"{r['ip']}/{r['module']}" == "ipf/ipf_f0" and not hit:
            r["provenance"]["fsm"] = {"path": f"{F.OUTPUT_DIR}/ipf/ipf_f0.json", "sha256": "0" * 64}
            hit = 1
        out.append(json.dumps(r))
    path.write_text("\n".join(out) + "\n")
    assert hit
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("leakage") == 1
    assert rep["leakage"]["fsm_dependent_records"] == 1


def test_zero_fsm_modules_do_not_form_leakage_groups(built):
    lk = V.check(built.root)["leakage"]
    mods = {m for c in lk["cross_split_fingerprints"] for m in c["modules"]}
    assert all(m.startswith("ipf/") for m in mods)
