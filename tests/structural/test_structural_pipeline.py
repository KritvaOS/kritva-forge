# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_structural_pipeline.py
# Description : KF-DQ-010 determinism, relocation, stale-gate, manifest, traceability and leakage integration
#
# Component   : Kritva Forge
# Module      : tests/structural
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Structural Analysis v1 in the pipeline (criteria sections 18 - 20, AC-044, AC-047 - AC-055).

* A/B and relocation: byte-identical ``normalized/structural/v1`` trees.
* Semantic IR v2 and Behavioral Semantics v1 are not modified.
* Stale gate: tampered, obsolete-schema, out-of-date (Semantic IR or
  Behavioral Semantics changed), stray and missing structural documents are
  STALE / ORPHAN / UNMANAGED / MISSING and block dataset publication.
* Data manifest v4: every module references its structural document; record
  structural dependencies must name the current artifact (traceability).
* KF-DQ-004 leakage: a structural dependency on a structure shared across
  splits fails the structural gate.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.behavior import model as BM
from scripts.core import data_manifest as DM
from scripts.core import stale_artifacts as S
from scripts.semantic_ir import model as SM
from scripts.structural import analyzer as A
from scripts.structural import model as T
from scripts.structural import validator as V
from tests.data.test_data_manifest import _make_data_root, _run


def _digest(root: Path, sub: str) -> dict:
    base = root / sub
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("strA")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return dest


def _state(root, rel):
    return next(e for e in S.classify(root)["entries"] if e["path"] == rel)


def test_pipeline_writes_valid_structure_for_every_module(built):
    rep = json.loads((built.root / T.REPORT_PATH).read_text())
    assert rep["status"] == "PASS", rep["problems"]
    ir = sorted(p.stem for p in (built.root / "normalized" / "ir").rglob("modules/*.yaml"))
    st = sorted(p.stem for p in (built.root / T.OUTPUT_DIR).rglob("*.json"))
    assert ir == st and rep["documents"] == len(st)
    assert rep["provenance"]["valid"] == rep["provenance"]["objects"] and rep["leakage"]["status"] == "PASS"
    assert V.check(built.root)["status"] == "PASS"


def test_ab_determinism(built, tmp_path):
    b = _run(_make_data_root(tmp_path / "B"))
    assert _digest(b.root, T.OUTPUT_DIR) == _digest(built.root, T.OUTPUT_DIR)
    assert (b.root / T.REPORT_PATH).read_bytes() == (built.root / T.REPORT_PATH).read_bytes()


def test_relocation(built, tmp_path):
    r = _run(_make_data_root(tmp_path / "x" / "y" / "elsewhere"))
    assert _digest(r.root, T.OUTPUT_DIR) == _digest(built.root, T.OUTPUT_DIR)
    for p in (r.root / T.OUTPUT_DIR).rglob("*.json"):
        assert str(r.root) not in p.read_text()


def test_inputs_are_not_modified(tree):
    before = {sub: _digest(tree, sub) for sub in (SM.OUTPUT_DIR, BM.OUTPUT_DIR, "normalized/ir", "raw")}
    A.write_all(tree)
    assert {sub: _digest(tree, sub) for sub in before} == before


def test_hierarchy_resolution_in_pipeline(built):
    doc = json.loads((built.root / T.OUTPUT_DIR / "ipa" / "ipa_top.json").read_text())
    (inst,) = doc["instances"]
    assert inst["status"] == "resolved" and inst["child"]["module"] == "lib_buf"


# ----------------------------------------------------------------------------- stale gate (AC-044)
def test_structural_documents_are_current(built):
    states = [e for e in S.classify(built.root)["entries"] if e["kind"] == "structural"]
    assert states and all(e["state"] == "CURRENT" for e in states)
    assert _state(built.root, T.REPORT_PATH)["state"] == "CURRENT"


def test_tampered_document_is_stale(tree):
    rel = f"{T.OUTPUT_DIR}/ipa/ipa_top.json"
    doc = json.loads((tree / rel).read_text())
    doc["counts"]["signals"] += 1
    (tree / rel).write_text(T.dumps(doc))
    assert _state(tree, rel)["state"] == "STALE"
    assert _state(tree, T.REPORT_PATH)["state"] == "STALE"


def test_semantic_change_makes_structure_stale(tree):
    rel = f"{SM.OUTPUT_DIR}/ipb/ipb_m0.json"
    sem = json.loads((tree / rel).read_text())
    sem["module"]["loc"]["column"] += 1
    (tree / rel).write_text(SM.dumps(sem))
    e = _state(tree, f"{T.OUTPUT_DIR}/ipb/ipb_m0.json")
    assert e["state"] == "STALE" and "older Semantic IR" in e["reason"]


def test_behavior_change_makes_structure_stale(tree):
    rel = f"{BM.OUTPUT_DIR}/ipb/ipb_m1.json"
    beh = json.loads((tree / rel).read_text())
    beh["generator"]["note"] = "edited"
    (tree / rel).write_text(BM.dumps(beh))
    e = _state(tree, f"{T.OUTPUT_DIR}/ipb/ipb_m1.json")
    assert e["state"] == "STALE" and "older Behavioral Semantics" in e["reason"]


def test_obsolete_schema_or_analyzer_is_stale(tree):
    rel = f"{T.OUTPUT_DIR}/ipa/ipa_m1.json"
    doc = json.loads((tree / rel).read_text())
    doc["versions"]["analyzer"] = 0
    (tree / rel).write_text(T.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE" and "obsolete structural schema" in e["reason"]


def test_stray_and_missing_structural_files(tree):
    (tree / T.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    (tree / "normalized" / "structural" / "notes.txt").write_text("x\n")
    (tree / T.OUTPUT_DIR / "ipc" / "ipc_m0.json").unlink()
    assert _state(tree, f"{T.OUTPUT_DIR}/ipa/not_a_module.json")["state"] == "ORPHAN"
    assert _state(tree, "normalized/structural/notes.txt")["state"] == "UNMANAGED"
    assert f"{T.OUTPUT_DIR}/ipc/ipc_m0.json" in S.classify(tree)["missing"]
    assert S.check(tree)["status"] == "FAIL"


def test_stale_structure_blocks_publication(tree, monkeypatch):
    """A stray structural document fails the structural gate even with the stale override."""
    (tree / T.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")
    with pytest.raises(RuntimeError, match="KF-DQ-010"):
        _run(tree)


def test_split_change_makes_report_stale(tree):
    path = tree / "splits" / "split_manifest.json"
    path.write_text(path.read_text() + " ")
    assert _state(tree, T.REPORT_PATH)["state"] == "STALE"


# ----------------------------------------------------------------------------- data manifest v4+ (AC-050, AC-051)
def test_manifest_references_structure(built):
    m = json.loads((built.root / DM.MANIFEST_PATH).read_text())
    assert m["schema"] == {"name": "kritva-forge-data-manifest", "version": 5}
    assert (m["versions"]["structural"], m["versions"]["structural_identity"], m["versions"]["structural_analyzer"]) == (1, 1, 1)
    arts = {a["path"]: a for a in m["artifacts"]}
    for mod in m["modules"]:
        s = mod["structural"]
        doc = json.loads((built.root / s["path"]).read_text())
        assert s["path"] == f"{T.OUTPUT_DIR}/{mod['ip']}/{mod['module']}.json" and s["structural_id"] == doc["id"]
        assert (s["schema_version"], s["identity_version"], s["status"], s["module_id"]) == (1, 1, "canonical", mod["module_id"])
        assert s["derived_from"] == {"semantic_ir": mod["semantic_ir"]["path"], "semantic_ir_sha256": mod["semantic_ir"]["sha256"],
                                     "behavior": mod["behavior"]["path"], "behavior_sha256": mod["behavior"]["sha256"]}
        assert arts[s["path"]]["kind"] == "structural" and arts[s["path"]]["sha256"] == s["sha256"]
    assert all("structural" not in r for r in m["records"])          # no record consumes structure yet
    assert DM.check(built.root)["status"] == "PASS"


def test_manifest_detects_structural_mismatch(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["modules"][0]["structural"]["derived_from"]["behavior_sha256"] = "0" * 64
    m["modules"][1]["structural"]["structural_id"] = "str1:0000000000000000"
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = DM.check(tree)
    assert rep["status"] == "FAIL" and rep["broken_references"] >= 2


def test_record_structural_traceability(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    rec = m["records"][0]
    mod = next(x for x in m["modules"] if x["module_id"] == rec["module_id"])
    rec["structural"] = {"path": mod["structural"]["path"], "sha256": mod["structural"]["sha256"]}
    assert DM.check(tree, m)["broken_references"] == 0
    rec["structural"]["sha256"] = "0" * 64                           # not the exact artifact used
    rep = DM.check(tree, m)
    assert rep["status"] == "FAIL" and rep["broken_references"] == 1


def test_manifest_v3_is_rejected(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["schema"]["version"] = 3
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    assert DM.check(tree)["schema_errors"]


# ----------------------------------------------------------------------------- KF-DQ-004 leakage (AC-052)
def test_leakage_report_and_structural_dependency(tree):
    rep = V.check(tree)
    lk = rep["leakage"]
    assert lk["status"] == "PASS" and lk["structural_dependent_records"] == 0 and lk["shared_fingerprints"] >= 1
    # two modules with one structure (ipX_m0 copies), placed in different splits
    fps = {}
    for p in sorted((tree / T.OUTPUT_DIR).rglob("*.json")):
        fps.setdefault(json.loads(p.read_text())["fingerprint"], []).append(f"{p.parent.name}/{p.stem}")
    a, b = next(v for v in fps.values() if len(v) > 1)[:2]
    sm_path = tree / "splits" / "split_manifest.json"
    sm = json.loads(sm_path.read_text())
    where = {f"{r['ip']}/{r['module']}": s for s in ("train", "validation", "test") for r in sm[s]}
    other = next(s for s in ("train", "validation", "test") if s != where[a])
    moved = next(r for r in sm[where[b]] if f"{r['ip']}/{r['module']}" == b)
    sm[where[b]].remove(moved)
    sm[other].append(moved)
    sm_path.write_text(json.dumps(sm))
    lk = V.check(tree)["leakage"]
    assert lk["status"] == "PASS" and any({a, b} <= set(c["modules"]) for c in lk["cross_split_fingerprints"])   # soft
    # a dataset record that consumes structural data of that structure must fail (hard)
    path = tree / "datasets" / "pipeline" / f"{where[a]}.jsonl"
    out = []
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if f"{r['ip']}/{r['module']}" == a:
            r["provenance"]["structural"] = {"path": f"{T.OUTPUT_DIR}/{a}.json", "sha256": "0" * 64}
        out.append(json.dumps(r))
    path.write_text("\n".join(out) + "\n")
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("leakage") == 1
    assert rep["leakage"]["structural_dependent_records"] == 1
