# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_prompt_v2_pipeline.py
# Description : Prompt v2 pipeline, stale, manifest v6, compatibility and classification integration (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Prompt v2 in the pipeline (criteria sections 20 - 24, 27 AC-776 .. AC-798).

* every canonical module gets one prompt and one sidecar; A/B and relocated
  runs are byte-identical; upstream layers and Prompt v1 are not modified;
* stale gate: tampered prompt / sidecar, unmanaged files and orphan sidecars;
* data manifest v6 references every prompt and sidecar; a missing record, a
  sha mismatch and a v5 manifest fail;
* the compatibility contract, the cross-split classification and the four
  KF-DQ-012 reports fail closed; no dataset record may consume Prompt v2.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.behavior import model as BM
from scripts.core import compat as C
from scripts.core import data_manifest as DM
from scripts.core import stale_artifacts as S
from scripts.fsm import model as F
from scripts.prompt_v2 import classify as PC
from scripts.prompt_v2 import model as P
from scripts.prompt_v2 import render as R
from scripts.prompt_v2 import validator as V
from scripts.semantic_ir import model as SM
from scripts.structural import model as TM
from tests.data.test_data_manifest import _make_data_root, _run


def _fsm_module(name, extra=""):
    return f"""module {name}(input clk, input rst_n, input go, output busy);
  localparam [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  reg [1:0] st;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= IDLE;
    else case (st) IDLE: if (go) st <= RUN; RUN: st <= DONE; DONE: st <= IDLE; default: st <= IDLE; endcase
  assign busy = (st == RUN){extra};
endmodule
"""


def _make_root(base):
    """The KF-DQ-007 scratch repository plus an IP with five FSM modules of one shape."""
    root = _make_data_root(base)
    ipf = root / "raw" / "rtl" / "original" / "ipf"
    ipf.mkdir(parents=True)
    (ipf / "ipf.sv").write_text("".join(_fsm_module(f"ipf_f{i}") for i in range(5)))
    (ipf / "files.f").write_text("ipf.sv\n")
    return root


def _digest(root: Path, sub: str) -> dict:
    base = root / sub
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _run(_make_root(tmp_path_factory.mktemp("pv2A")))


@pytest.fixture
def tree(built, tmp_path):
    dest = tmp_path / "copy" / "kritva-forge-data"
    shutil.copytree(built.root, dest, symlinks=True)
    return dest


def _state(root, rel):
    return next(e for e in S.classify(root)["entries"] if e["path"] == rel)


PREL = P.prompt_rel("ipf", "ipf_f0")
SREL = P.sidecar_rel("ipf", "ipf_f0")


# ----------------------------------------------------------------------------- generation
def test_every_module_has_one_prompt_and_sidecar(built):
    """AC-801 .. AC-805 (scratch corpus): one default variant + sidecar per canonical module."""
    canon = sorted(R.canonical_modules(built.root))
    files = sorted(p.relative_to(built.root).as_posix() for p in (built.root / P.OUTPUT_DIR).rglob("*") if p.is_file())
    assert files == sorted([P.prompt_rel(i, m) for i, m in canon] + [P.sidecar_rel(i, m) for i, m in canon])
    rep = V.check(built.root, with_classification=True)
    assert rep["status"] == "PASS", rep["problems"]
    assert rep["prompts"] == rep["sidecars"] == rep["canonical_modules"] == len(canon)
    assert rep["provenance"]["coverage"] == 1.0 and rep["leakage"]["failures"] == 0
    zero = json.loads((built.root / P.sidecar_rel("ipa", "ipa_m0")).read_text())
    assert zero["fsm"]["fsms"] == 0                                                      # AC-804
    assert json.loads((built.root / P.REPORT_PATH).read_text())["status"] == "PASS"


def test_ab_determinism_and_relocation(built, tmp_path):
    """AC-725 .. AC-728, AC-789 .. AC-791, AC-840 .. AC-842."""
    b = _run(_make_root(tmp_path / "x" / "y" / "B"))
    assert _digest(b.root, P.OUTPUT_DIR) == _digest(built.root, P.OUTPUT_DIR)
    for rel in (P.REPORT_PATH, P.CLASSIFICATION_REPORT_PATH, C.REPORT_PATH):
        assert (b.root / rel).read_bytes() == (built.root / rel).read_bytes(), rel
    for p in (b.root / P.OUTPUT_DIR).rglob("*.*"):
        assert str(b.root) not in p.read_text()


def test_upstream_layers_and_prompt_v1_are_not_modified(tree):
    """AC-031 .. AC-040, AC-827 .. AC-833: regeneration touches only generated/prompt/v2."""
    subs = (SM.OUTPUT_DIR, BM.OUTPUT_DIR, TM.OUTPUT_DIR, F.OUTPUT_DIR, "normalized/ir", "raw", "datasets", "splits")
    v1 = [p for p in (tree / "generated").iterdir() if p.name != "prompt"] if (tree / "generated").is_dir() else []
    before = {sub: _digest(tree, sub) for sub in subs}
    before_v1 = {p.name: _digest(tree, p.relative_to(tree).as_posix()) for p in v1 if p.is_dir()}
    R.write_all(tree)
    assert {sub: _digest(tree, sub) for sub in subs} == before
    assert {p.name: _digest(tree, p.relative_to(tree).as_posix()) for p in v1 if p.is_dir()} == before_v1


def test_prompt_v2_artifacts_are_current(built):
    states = [e for e in S.classify(built.root)["entries"] if e["kind"].startswith("prompt_v2")
              or e["kind"] == "prompt_leakage_classification"]
    assert len(states) >= 2 * len(R.canonical_modules(built.root)) + 2
    assert all(e["state"] == "CURRENT" for e in states), [e for e in states if e["state"] != "CURRENT"][:3]


# ----------------------------------------------------------------------------- stale gate (AC-776 .. AC-779)
def test_stale_prompt(tree):
    """AC-776."""
    (tree / PREL).write_text((tree / PREL).read_text() + "Extra line.\n")
    assert _state(tree, PREL)["state"] == "STALE"
    assert _state(tree, P.REPORT_PATH)["state"] == "STALE"
    assert S.check(tree)["status"] == "FAIL" and V.check(tree)["status"] == "FAIL"


def test_stale_sidecar(tree):
    """AC-777."""
    sc = json.loads((tree / SREL).read_text())
    sc["inputs"]["fsm"]["sha256"] = "0" * 64
    (tree / SREL).write_text(P.dumps(sc))
    assert _state(tree, SREL)["state"] == "STALE"


def test_upstream_change_makes_prompt_stale(tree):
    rel = f"{F.OUTPUT_DIR}/ipf/ipf_f0.json"
    d = json.loads((tree / rel).read_text())
    d.setdefault("notes", {})["edited"] = 1
    (tree / rel).write_text(F.dumps(d))
    assert _state(tree, PREL)["state"] == "STALE"


def test_unmanaged_prompt_artifact(tree):
    """AC-778."""
    (tree / P.OUTPUT_DIR / "ipf" / "notes.md").write_text("x\n")
    (tree / P.OUTPUT_DIR / "ipf" / "ipf_f0.raw_rtl.txt").write_text("x\n")
    assert _state(tree, f"{P.OUTPUT_DIR}/ipf/notes.md")["state"] == "UNMANAGED"
    assert _state(tree, f"{P.OUTPUT_DIR}/ipf/ipf_f0.raw_rtl.txt")["state"] == "UNMANAGED"
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("inventory") and rep["problem_counts"].get("variant")


def test_orphan_sidecar(tree):
    """AC-779: a sidecar whose prompt is gone, and a pair for a module that does not exist."""
    (tree / PREL).unlink()
    (tree / P.OUTPUT_DIR / "ipf" / "ghost.behavior_aware.json").write_text("{}\n")
    assert _state(tree, SREL)["state"] == "ORPHAN"
    assert _state(tree, f"{P.OUTPUT_DIR}/ipf/ghost.behavior_aware.json")["state"] == "ORPHAN"
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and any("orphan sidecar" in p for p in rep["problems"])


def test_bypassed_prompt_gate_fails(tree, monkeypatch):
    """AC-784: the stale override does not bypass the Prompt v2 gate."""
    (tree / P.OUTPUT_DIR / "ipa" / "ghost.behavior_aware.txt").write_text("x\n")
    monkeypatch.setenv(S.OVERRIDE_ENV, "1")
    with pytest.raises(RuntimeError, match="KF-DQ-012"):
        _run(tree)


# ----------------------------------------------------------------------------- manifest v6 (AC-780 .. AC-782)
def test_manifest_v6_references_prompt_v2(built):
    m = json.loads((built.root / DM.MANIFEST_PATH).read_text())
    assert m["schema"]["version"] == 7 and m["compatibility"]["required"] == C.REQUIRED
    arts = {a["path"]: a for a in m["artifacts"]}
    for mod in m["modules"]:
        pv = mod["prompt_v2"]
        assert pv["path"] == P.prompt_rel(mod["ip"], mod["module"])
        assert pv["sidecar_path"] == P.sidecar_rel(mod["ip"], mod["module"])
        sc = json.loads((built.root / pv["sidecar_path"]).read_text())
        assert pv["identity"] == sc["identity"] and pv["module_id"] == mod["module_id"]
        assert arts[pv["path"]]["kind"] == "prompt_v2" and arts[pv["sidecar_path"]]["kind"] == "prompt_v2_sidecar"
        assert pv["derived_from"]["fsm"]["sha256"] == mod["fsm"]["sha256"]
    assert m["counts"]["prompt_v2"] == m["counts"]["prompt_v2_sidecars"] == len(m["modules"])
    assert all("prompt_v2" not in json.dumps(r.get("provenance") or {}) for r in m["records"])
    rep = DM.check(built.root)
    assert rep["status"] == "PASS" and rep["compatibility_status"] == "compatible"


def test_missing_manifest_record(tree):
    """AC-780."""
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    del m["modules"][0]["prompt_v2"]
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    assert DM.check(tree)["status"] == "FAIL"


def test_manifest_sha_mismatch(tree):
    """AC-781."""
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["modules"][0]["prompt_v2"]["sha256"] = "0" * 64
    m["modules"][1]["prompt_v2"]["sidecar_sha256"] = "0" * 64
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = DM.check(tree)
    assert rep["status"] == "FAIL" and rep["broken_references"] >= 2


def test_manifest_v5_is_rejected(tree):
    """AC-782."""
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["schema"]["version"] = 5
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    assert DM.check(tree)["schema_errors"]
    assert C.check(tree)["status"] == "FAIL"


# ----------------------------------------------------------------------------- compatibility (AC-783)
def test_compatibility_contract(built):
    """AC-508 .. AC-531: one canonical declaration, equal to the layers' own constants."""
    assert C.declared() == C.REQUIRED
    rep = C.check(built.root)
    assert rep["status"] == "PASS" and rep["sidecars_checked"] == len(R.canonical_modules(built.root))
    assert json.loads((built.root / C.REPORT_PATH).read_text())["status"] == "PASS"


@pytest.mark.parametrize("key,value", [("fsm", 1), ("prompt", 1), ("tokenizer", "sv-lex-v0")])
def test_compatibility_mismatch(tree, key, value):
    """AC-783: a version mismatch in the manifest or in one sidecar fails closed."""
    m = json.loads((tree / DM.MANIFEST_PATH).read_text())
    m["versions"][key] = value
    (tree / DM.MANIFEST_PATH).write_text(DM.dumps(m))
    rep = C.check(tree)
    assert rep["status"] == "FAIL" and any(key in p for p in rep["problems"])


def test_sidecar_version_mismatch(tree):
    sc = json.loads((tree / SREL).read_text())
    sc["versions"]["leakage_metric"] = "leakage-v0"
    (tree / SREL).write_text(P.dumps(sc))
    rep = C.check(tree)
    assert rep["status"] == "FAIL" and any(SREL in p for p in rep["problems"])


# ----------------------------------------------------------------------------- KF-DQ-013 boundary (AC-785)
def test_unauthorized_dataset_consumption(tree):
    path = next(p for p in (tree / "datasets" / "pipeline" / f"{s}.jsonl" for s in ("train", "validation", "test"))
                if p.is_file() and p.read_text().strip())
    lines = path.read_text().splitlines()
    r = json.loads(lines[0])
    r["provenance"]["prompt_v2"] = {"path": PREL, "sha256": "0" * 64}
    lines[0] = json.dumps(r)
    path.write_text("\n".join(lines) + "\n")
    rep = V.check(tree)
    assert rep["status"] == "FAIL" and rep["problem_counts"].get("consumption") == 1


# ----------------------------------------------------------------------------- classification (AC-786 .. AC-788)
def _move_apart(tree, a, b):
    sm_path = tree / "splits" / "split_manifest.json"
    sm = json.loads(sm_path.read_text())
    where = {f"{r['ip']}/{r['module']}": s for s in ("train", "validation", "test") for r in sm[s]}
    if where[a] != where[b]:
        return
    other = next(s for s in ("train", "validation", "test") if s != where[a])
    moved = next(r for r in sm[where[b]] if f"{r['ip']}/{r['module']}" == b)
    sm[where[b]].remove(moved)
    sm[other].append(moved)
    sm_path.write_text(json.dumps(sm))


def test_classification_report_and_no_split_change(built):
    """AC-469 .. AC-507: recomputed from documents, classified, splits untouched."""
    rep = json.loads((built.root / P.CLASSIFICATION_REPORT_PATH).read_text())
    assert rep == PC.build(built.root) and PC.validate(rep) == []
    assert rep["classifier_version"] == "rtl-sim-v1" and rep["splits_changed"] is False
    sm = (built.root / "splits" / "split_manifest.json").read_bytes()
    assert rep["split_manifest_sha256"] == hashlib.sha256(sm).hexdigest()


def test_split_mutation_makes_classification_stale(tree):
    """AC-786."""
    path = tree / "splits" / "split_manifest.json"
    path.write_text(path.read_text() + " ")
    assert _state(tree, P.CLASSIFICATION_REPORT_PATH)["state"] == "STALE"


def test_near_duplicate_is_reported_unresolved(tree):
    """AC-787: identical FSM modules in different splits are near_duplicate and block KF-DQ-013 entry."""
    _move_apart(tree, "ipf/ipf_f0", "ipf/ipf_f1")
    rep = PC.build(tree)
    nd = [g for g in rep["groups"] if g["classification"] == "near_duplicate"]
    assert nd and rep["unresolved_near_duplicates"] == [g["id"] for g in nd]
    assert rep["kf_dq_013_entry"].startswith("blocked") and rep["splits_changed"] is False
    assert any({"ipf_f0", "ipf_f1"} <= {m["module"] for m in g["members"]} for g in nd)
    hidden = dict(rep, unresolved_near_duplicates=[])
    assert PC.validate(hidden)


def test_invalid_classification_version(tree):
    """AC-788."""
    path = tree / P.CLASSIFICATION_REPORT_PATH
    rep = json.loads(path.read_text())
    rep["classifier_version"] = "rtl-sim-v0"
    path.write_text(PC.dumps(rep))
    assert _state(tree, P.CLASSIFICATION_REPORT_PATH)["state"] == "STALE"
    assert any("classifier version" in m for _, m in V.reports_check(tree))


# ----------------------------------------------------------------------------- reports (AC-795 .. AC-798)
@pytest.mark.parametrize("rel,what", [(P.REPORT_PATH, "corpus"), (C.REPORT_PATH, "compatibility"),
                                      (S.REPORT_PATH, "stale"), (P.CLASSIFICATION_REPORT_PATH, "leakage classification")])
def test_missing_report(tree, rel, what):
    (tree / rel).unlink()
    found = V.reports_check(tree)
    assert any(f"{what} report" in m and "missing" in m for _, m in found)
