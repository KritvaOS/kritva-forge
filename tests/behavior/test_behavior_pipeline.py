# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_behavior_pipeline.py
# Description : KF-DQ-009 determinism, relocation, stale-gate and manifest integration of Behavioral Semantics
#
# Component   : Kritva Forge
# Module      : tests/behavior
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 in the pipeline (criteria sections 28, 32, 35, 36).

* A/B and relocation: byte-identical ``normalized/behavior/v1`` trees.
* Semantic IR v2 is not modified by behavioral analysis.
* Stale gate: tampered, out-of-date, obsolete-schema, stray and missing
  behavioral documents are STALE / ORPHAN / UNMANAGED / MISSING and block
  dataset publication.
* Data manifest (v4): every module references its behavioral document.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.behavior import model as B
from scripts.behavior import validator as V
from scripts.core import data_manifest as DM
from scripts.core import stale_artifacts as S
from scripts.semantic_ir import model as SM
from tests.data.test_data_manifest import _make_data_root, _run


def _digest(root: Path, sub: str) -> dict:
    base = root / sub
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("behA")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return dest


def _state(root, rel):
    return next(e for e in S.classify(root)["entries"] if e["path"] == rel)


def test_pipeline_writes_valid_behavior_for_every_module(built):
    rep = json.loads((built.root / B.REPORT_PATH).read_text())
    assert rep["status"] == "PASS", rep["problems"]
    ir = sorted(p.stem for p in (built.root / "normalized" / "ir").rglob("modules/*.yaml"))
    beh = sorted(p.stem for p in (built.root / B.OUTPUT_DIR).rglob("*.json"))
    assert ir == beh and rep["documents"] == len(beh)
    assert V.check(built.root)["status"] == "PASS"


def test_ab_determinism(built, tmp_path):
    b = _run(_make_data_root(tmp_path / "B"))
    assert _digest(b.root, B.OUTPUT_DIR) == _digest(built.root, B.OUTPUT_DIR)
    assert (b.root / B.REPORT_PATH).read_bytes() == (built.root / B.REPORT_PATH).read_bytes()


def test_relocation(built, tmp_path):
    r = _run(_make_data_root(tmp_path / "x" / "y" / "elsewhere"))
    assert _digest(r.root, B.OUTPUT_DIR) == _digest(built.root, B.OUTPUT_DIR)
    for p in (r.root / B.OUTPUT_DIR).rglob("*.json"):
        assert str(r.root) not in p.read_text()


def test_semantic_ir_is_not_modified(tree):
    from scripts.behavior import analyzer as A
    before = _digest(tree, SM.OUTPUT_DIR)
    A.write_all(tree)
    assert _digest(tree, SM.OUTPUT_DIR) == before


# ----------------------------------------------------------------------------- stale gate

def test_behavior_documents_are_current(built):
    states = [e for e in S.classify(built.root)["entries"] if e["kind"] == "behavior"]
    assert states and all(e["state"] == "CURRENT" for e in states)
    assert _state(built.root, B.REPORT_PATH)["state"] == "CURRENT"


def test_tampered_document_is_stale(tree):
    rel = f"{B.OUTPUT_DIR}/ipa/ipa_top.json"
    doc = json.loads((tree / rel).read_text())
    doc["counts"]["processes"] += 1
    (tree / rel).write_text(B.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE"
    assert _state(tree, B.REPORT_PATH)["state"] == "STALE"


def test_semantic_change_makes_behavior_stale(tree):
    rel = f"{SM.OUTPUT_DIR}/ipb/ipb_m0.json"
    sem = json.loads((tree / rel).read_text())
    sem["module"]["loc"]["column"] += 1
    (tree / rel).write_text(SM.dumps(sem))
    e = _state(tree, f"{B.OUTPUT_DIR}/ipb/ipb_m0.json")
    assert e["state"] == "STALE" and "older Semantic IR" in e["reason"]


def test_obsolete_schema_is_stale(tree):
    rel = f"{B.OUTPUT_DIR}/ipa/ipa_m1.json"
    doc = json.loads((tree / rel).read_text())
    doc["schema"]["version"] = 0
    (tree / rel).write_text(B.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE" and "obsolete behavioral schema" in e["reason"]


def test_stray_and_missing_behavior_files(tree):
    (tree / B.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    (tree / "normalized" / "behavior" / "notes.txt").write_text("x\n")
    (tree / B.OUTPUT_DIR / "ipc" / "ipc_m0.json").unlink()
    assert _state(tree, f"{B.OUTPUT_DIR}/ipa/not_a_module.json")["state"] == "ORPHAN"
    assert _state(tree, "normalized/behavior/notes.txt")["state"] == "UNMANAGED"
    assert f"{B.OUTPUT_DIR}/ipc/ipc_m0.json" in S.classify(tree)["missing"]
    assert S.check(tree)["status"] == "FAIL"


def test_stale_behavior_blocks_publication(tree, monkeypatch):
    """A stray behavioral document fails the behavior gate even with the stale override."""
    (tree / B.OUTPUT_DIR / "ipa" / "not_a_module.json").write_text("{}\n")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")
    with pytest.raises(RuntimeError, match="KF-DQ-009"):
        _run(tree)


# ----------------------------------------------------------------------------- data manifest

def test_manifest_references_behavior(built):
    m = json.loads((built.root / DM.MANIFEST_PATH).read_text())
    assert m["schema"] == {"name": "kritva-forge-data-manifest", "version": 6}
    assert (m["versions"]["behavior"], m["versions"]["behavior_identity"]) == (1, 1)
    arts = {a["path"]: a for a in m["artifacts"]}
    for mod in m["modules"]:
        b = mod["behavior"]
        assert b["path"] == f"{B.OUTPUT_DIR}/{mod['ip']}/{mod['module']}.json"
        assert (b["schema_version"], b["identity_version"], b["status"]) == (1, 1, "canonical")
        assert b["module_id"] == mod["module_id"]
        assert b["derived_from"] == {"semantic_ir": mod["semantic_ir"]["path"],
                                     "semantic_ir_sha256": mod["semantic_ir"]["sha256"]}
        assert arts[b["path"]]["kind"] == "behavior" and arts[b["path"]]["sha256"] == b["sha256"]
    assert DM.check(built.root)["status"] == "PASS"


def test_manifest_detects_behavior_mismatch(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["modules"][0]["behavior"]["derived_from"]["semantic_ir_sha256"] = "0" * 64
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = DM.check(tree)
    assert rep["status"] == "FAIL" and rep["broken_references"]


def test_manifest_v2_is_rejected(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["schema"]["version"] = 2
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = DM.check(tree)
    assert rep["status"] == "FAIL" and rep["schema_errors"]
