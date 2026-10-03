# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_semantic_pipeline.py
# Description : KF-DQ-008 determinism, relocation, stale-gate and manifest integration of Semantic IR v2
#
# Component   : Kritva Forge
# Module      : tests/semantic_ir
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic IR v2 in the pipeline (acceptance criteria sections 21-24, 28, 29).

* A/B: two clean runs produce byte-identical ``normalized/semantic_ir/v2`` trees.
* Relocation: a run in a different checkout location produces identical bytes.
* Stale gate: tampered, obsolete-schema, out-of-date and stray semantic
  documents are STALE / ORPHAN / UNMANAGED.
* Data manifest v2: every module references its Semantic IR document.
* Compilation-unit declarations, anonymous enums and bare system calls.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.core import data_manifest as DM
from scripts.core import stale_artifacts as S
from scripts.semantic_ir import model as M
from scripts.semantic_ir import validator as V
from tests.data.test_data_manifest import _make_data_root, _run
from tests.semantic_ir.helpers import assigns_to, by_name, extract, walk


def _tree_digest(root: Path) -> dict:
    sem = root / M.OUTPUT_DIR
    return {p.relative_to(sem).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(sem.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_data_root(tmp_path_factory.mktemp("semA")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return dest


def _state(root, rel):
    result = S.classify(root)
    return next(e for e in result["entries"] if e["path"] == rel)


def test_pipeline_writes_one_valid_document_per_canonical_module(built):
    report = json.loads((built.root / M.REPORT_PATH).read_text())
    assert report["status"] == "PASS", report["problems"]
    ir = sorted(p.stem for p in (built.root / "normalized" / "ir").rglob("modules/*.yaml"))
    sem = sorted(p.stem for p in (built.root / M.OUTPUT_DIR).rglob("*.json"))
    assert ir == sem and len(sem) == report["documents"]
    assert V.check(built.root)["status"] == "PASS"


def test_ab_determinism(built, tmp_path):
    b = _run(_make_data_root(tmp_path / "B"))
    assert _tree_digest(b.root) == _tree_digest(built.root)
    assert (b.root / M.REPORT_PATH).read_bytes() == (built.root / M.REPORT_PATH).read_bytes()


def test_relocation(built, tmp_path):
    r = _run(_make_data_root(tmp_path / "some" / "deeper" / "place"))
    assert _tree_digest(r.root) == _tree_digest(built.root)
    for p in (r.root / M.OUTPUT_DIR).rglob("*.json"):
        assert str(r.root) not in p.read_text()


def test_identities_are_location_independent(built, tmp_path):
    a = json.loads(next((built.root / M.OUTPUT_DIR).rglob("ipa_top.json")).read_text())
    moved = tmp_path / "moved" / "kritva-forge-data"
    shutil.copytree(built.root, moved)
    b = json.loads(next((moved / M.OUTPUT_DIR).rglob("ipa_top.json")).read_text())
    assert [n["id"] for n in walk(a) if "id" in n] == [n["id"] for n in walk(b) if "id" in n]


# ----------------------------------------------------------------------------- stale gate

def test_semantic_documents_are_current(built):
    states = [e for e in S.classify(built.root)["entries"] if e["kind"] == "semantic_ir"]
    assert states and all(e["state"] == "CURRENT" for e in states)
    assert _state(built.root, M.REPORT_PATH)["state"] == "CURRENT"


def test_tampered_document_is_stale(tree):
    rel = "normalized/semantic_ir/v2/ipa/ipa_m0.json"
    doc = json.loads((tree / rel).read_text())
    doc["assignments"][0]["process"] = M.semantic_id("process", "ghost")
    (tree / rel).write_text(M.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE" and "validation" in e["reason"]
    assert _state(tree, M.REPORT_PATH)["state"] == "STALE"               # corpus changed under the report


def test_obsolete_schema_is_stale(tree):
    rel = "normalized/semantic_ir/v2/ipa/ipa_m1.json"
    doc = json.loads((tree / rel).read_text())
    doc["schema"]["version"] = 1
    (tree / rel).write_text(M.dumps(doc))
    e = _state(tree, rel)
    assert e["state"] == "STALE" and "obsolete semantic schema" in e["reason"]


def test_source_change_makes_document_stale(tree):
    src = tree / "raw" / "rtl" / "original" / "ipb" / "ipb.sv"
    src.write_text(src.read_text() + "// touched\n")
    e = _state(tree, "normalized/semantic_ir/v2/ipb/ipb_m0.json")
    assert e["state"] == "STALE" and "source sha256" in e["reason"]


def test_stray_semantic_files(tree):
    (tree / "normalized/semantic_ir/v2/ipa/not_a_module.json").write_text("{}\n")
    (tree / "normalized/semantic_ir/notes.txt").write_text("x\n")
    assert _state(tree, "normalized/semantic_ir/v2/ipa/not_a_module.json")["state"] == "ORPHAN"
    assert _state(tree, "normalized/semantic_ir/notes.txt")["state"] == "UNMANAGED"
    assert S.check(tree)["status"] == "FAIL"


def test_missing_document_is_reported(tree):
    (tree / "normalized/semantic_ir/v2/ipc/ipc_m0.json").unlink()
    assert "normalized/semantic_ir/v2/ipc/ipc_m0.json" in S.classify(tree)["missing"]


# ----------------------------------------------------------------------------- data manifest v2

def test_manifest_v2_references_semantic_ir(built):
    m = json.loads((built.root / DM.MANIFEST_PATH).read_text())
    assert m["schema"] == {"name": "kritva-forge-data-manifest", "version": 3}
    assert m["versions"]["semantic_ir"] == 2 and m["versions"]["semantic_identity"] == 1
    assert m["versions"]["semantic_parser_version"].startswith("pyslang")
    arts = {a["path"]: a for a in m["artifacts"]}
    for mod in m["modules"]:
        sem = mod["semantic_ir"]
        assert sem["path"] == f"normalized/semantic_ir/v2/{mod['ip']}/{mod['module']}.json"
        assert sem["schema_version"] == 2 and sem["identity_version"] == 1 and sem["status"] == "canonical"
        assert sem["derived_from"] == {"source": mod["source"]["path"], "source_sha256": mod["source"]["sha256"]}
        assert arts[sem["path"]]["kind"] == "semantic_ir" and arts[sem["path"]]["status"] == "canonical"
        assert arts[sem["path"]]["sha256"] == sem["sha256"]
        assert arts[sem["path"]]["module_id"] == mod["module_id"]
    assert DM.check(built.root)["status"] == "PASS"


def test_manifest_detects_semantic_hash_mismatch(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["modules"][0]["semantic_ir"]["sha256"] = "0" * 64
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    report = DM.check(tree)
    assert report["status"] == "FAIL" and report["broken_references"]


def test_manifest_v1_is_rejected(tree):
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["schema"]["version"] = 1
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    report = DM.check(tree)
    assert report["status"] == "FAIL" and report["schema_errors"]


# ----------------------------------------------------------------------------- extraction details

def test_compilation_unit_declarations_resolve_as_external(tmp_path):
    header = "parameter HW = 16;\nlocalparam [1:0] ST_IDLE = 2'd0;\n"
    src = """`include "defs.svh"
module fx(input [HW-1:0] a, output [1:0] s, output [HW-1:0] y);
  assign s = ST_IDLE;
  assign y = a;
endmodule
"""
    d = extract(src, tmp_path, extra={"defs.svh": header})["fx"]
    ext = {x["name"]: x for x in d["external"]}
    assert ext["HW"]["kind"] == "parameter" and ext["ST_IDLE"]["kind"] == "localparam"
    assert ext["HW"]["loc"]["file"].endswith("defs.svh")
    ref = assigns_to(d, "s")[0]["value"]
    assert (ref["ref_kind"], ref["target"]) == ("external", None)
    assert d["counts"]["unresolved_references"] == 0 and d["counts"]["external_references"] >= 2
    assert V.validate_module(d) == []


def test_anonymous_enum_members_resolve(tmp_path):
    d = extract("""
module fx(input clk, output logic busy);
  enum logic [1:0] {IDLE = 2'd0, RUN = 2'd1} state;
  always_ff @(posedge clk) state <= (state == IDLE) ? RUN : IDLE;
  assign busy = state == RUN;
endmodule
""", tmp_path)["fx"]
    anon = next(t for t in d["typedefs"] if t["name"] is None)
    assert anon["kind"] == "enum" and [m["name"] for m in anon["members"]] == ["IDLE", "RUN"]
    kinds = {n["name"]: n["ref_kind"] for n in walk(d["assignments"]) if n.get("op") == "ref"}
    assert kinds["IDLE"] == kinds["RUN"] == "enum_member"
    assert by_name(d["signals"], "state")["type"] == "enum"
    assert V.validate_module(d) == []


def test_bare_system_calls_are_modelled(tmp_path):
    d = extract("""
module fx(input clk, output reg [63:0] t);
  always @(posedge clk) begin t <= $time; if (t > 64'd10) $stop; end
endmodule
""", tmp_path)["fx"]
    assert d["extraction"] == "complete" and d["unsupported"] == []
    calls = [n for n in walk(d) if n.get("op") == "call"]
    assert {c["name"] for c in calls} == {"$time", "$stop"} and all(c["system"] for c in calls)
