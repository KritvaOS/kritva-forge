# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_reference_corpus.py
# Description : Reference corpus contract, materialization and summary tests (KF-DQ-012.2)
#
# Component   : Kritva Forge
# Module      : tests/reference
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""KF-DQ-012.2 AC-050 .. AC-054.

The unit tests build throw-away git repositories under ``tmp_path``, so they
need no network. The tests of the committed contract read ``reference/``. The
test that materializes the real corpus skips when the submodules are not
initialised (``make reference-init``).
"""

import configparser
import copy
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.reference import corpus as C
from scripts.reference import materialize as M
from scripts.reference import summary as S

FORGE = Path(__file__).resolve().parents[2]
PINNED = {
    "qspi": ("reference/sources/qspim", "https://github.com/dineshannayya/qspim.git",
             "55f8c4323611a33a0e01f8066940fb6d76ffa12a"),
    "rtc": ("reference/sources/rtc", "https://github.com/dineshannayya/rtc.git",
            "48943b7aa6ce9d66fd23db83417a7a097376c21d"),
    "fpu": ("reference/sources/fpu", "https://github.com/dineshannayya/fpu.git",
            "621d988a3c2cc0be61e74bd29a6fcf4a923308f9"),
    "aes": ("reference/sources/security_core", "https://github.com/dineshannayya/security_core.git",
            "de2e6a5333261f94ef7f14a0c401eb5ced9bed04"),
    "ycr1": ("reference/sources/ycr1cr", "https://github.com/dineshannayya/ycr1cr.git",
             "a6c76b34a44ceee89c3876f67f3761a60540fa00"),
}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(path: Path, files: dict) -> str:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return _git(path, "rev-parse", "HEAD")


@pytest.fixture
def forge(tmp_path):
    """A fake forge root with one source repository and a valid corpus."""
    root = tmp_path / "forge"
    commit = _repo(root / "reference/sources/demo", {
        "rtl/top.sv": '`include "defs.svh"\nmodule top(input a, output y); leaf u(.a(a), .y(y)); endmodule\n',
        "rtl/leaf.v": "module leaf(input a, output y); assign y = a; endmodule\n",
        "rtl/inc/defs.svh": "`define W 8\n",
        "rtl/ext.sv": '`include "parent_soc.svh"\nmodule ext; endmodule\n',
        "rtl/opt.sv": '`ifdef CUSTOM\n`include "custom.svh"\n`endif\nmodule opt; endmodule\n',
        "tb/tb.sv": "module tb; endmodule\n",
    })
    doc = {"schema": dict(C.SCHEMA), "ips": [{
        "id": "demo", "submodule": "reference/sources/demo", "repository": "https://example.invalid/demo.git",
        "commit": commit, "license": "Apache-2.0", "root": "rtl", "incdirs": ["inc"],
        "files": ["inc/defs.svh", "leaf.v", "opt.sv", "top.sv"],
        "exclusions": [{"path": "ext.sv", "reason": "external_parent_soc_include:parent_soc.svh"}],
        "external_includes": [{"include": "custom.svh", "reason": "only under `ifdef CUSTOM"}],
    }]}
    return root, doc


def _write(root, doc):
    p = root / "reference" / "corpus.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _run(root, doc, out=None):
    return M.materialize(root, _write(root, doc), out or root / "build" / "reference")


# ----------------------------------------------------------------------------- schema (AC-015)
@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(schema={"name": "x", "version": 1}), "schema"),
    (lambda d: d["ips"][0].update(commit="abc"), "commit"),
    (lambda d: d["ips"][0].update(id="Bad-Id"), "invalid id"),
    (lambda d: d["ips"][0].update(repository="git@x:y"), "https"),
    (lambda d: d["ips"][0].update(submodule="../x"), "submodule"),
    (lambda d: d["ips"][0].update(files=["/abs.sv"]), "invalid file path"),
    (lambda d: d["ips"][0].update(files=["b.sv", "a.sv"]), "sorted"),
    (lambda d: d["ips"][0].update(files=["x.txt"]), "unsupported file type"),
    (lambda d: d["ips"][0]["exclusions"].append({"path": "y.sv", "reason": " "}), "reason"),
    (lambda d: d["ips"][0]["external_includes"].append({"include": "z.svh", "reason": ""}), "external include"),
    (lambda d: d["ips"].append(copy.deepcopy(d["ips"][0])), "duplicate id"),
    (lambda d: d["ips"][0].pop("license"), "missing"),
])
def test_schema_errors(forge, mutate, needle):
    _, doc = forge
    bad = copy.deepcopy(doc)
    mutate(bad)
    assert any(needle in p for p in C.validate(bad)), C.validate(bad)


def test_valid_corpus(forge):
    assert C.validate(forge[1]) == []


# ----------------------------------------------------------------------------- sources (AC-008 .. AC-010)
def test_pinned_commit_mismatch(forge):
    root, doc = forge
    doc["ips"][0]["commit"] = "0" * 40
    with pytest.raises(C.CorpusError, match="pinned"):
        _run(root, doc)


def test_dirty_source_refused(forge):
    root, doc = forge
    (root / "reference/sources/demo/rtl/leaf.v").write_text("changed\n", encoding="utf-8")
    with pytest.raises(C.CorpusError, match="dirty"):
        _run(root, doc)


def test_missing_source_checkout(forge):
    root, doc = forge
    doc["ips"][0]["submodule"] = "reference/sources/absent"
    with pytest.raises(C.CorpusError, match="not checked out"):
        _run(root, doc)


# ----------------------------------------------------------------------------- materialization (AC-016 .. AC-024)
def test_missing_listed_file(forge):
    root, doc = forge
    doc["ips"][0]["files"] = sorted(doc["ips"][0]["files"] + ["gone.sv"])
    with pytest.raises(C.CorpusError, match="missing"):
        _run(root, doc)


def test_unresolved_include_fails(forge):
    root, doc = forge
    doc["ips"][0]["exclusions"] = []
    doc["ips"][0]["files"] = sorted(doc["ips"][0]["files"] + ["ext.sv"])
    with pytest.raises(C.CorpusError, match='unresolved include "parent_soc.svh"'):
        _run(root, doc)


def test_undocumented_conditional_include_fails(forge):
    root, doc = forge
    doc["ips"][0]["external_includes"] = []
    with pytest.raises(C.CorpusError, match='"custom.svh"'):
        _run(root, doc)


def test_stale_external_include_fails(forge):
    root, doc = forge
    doc["ips"][0]["external_includes"].append({"include": "never.svh", "reason": "stale"})
    with pytest.raises(C.CorpusError, match="never included"):
        _run(root, doc)


def test_stale_exclusion_fails(forge):
    root, doc = forge
    doc["ips"][0]["exclusions"].append({"path": "nothere.sv", "reason": "x"})
    with pytest.raises(C.CorpusError, match="stale exclusion"):
        _run(root, doc)


def test_materialization_layout_and_copies(forge):
    root, doc = forge
    man = _run(root, doc)
    out = root / "build" / "reference"
    data = out / "kritva-forge-data"
    ip = data / "raw/rtl/original/demo"
    for rel in doc["ips"][0]["files"]:
        assert (ip / rel).read_bytes() == (root / "reference/sources/demo/rtl" / rel).read_bytes()   # AC-017
    assert not (ip / "ext.sv").exists() and not (ip / "tb.sv").exists()                         # explicit only
    assert (ip / "files.f").read_text() == "+incdir+./inc\n./leaf.v\n./opt.sv\n./top.sv\n"
    assert (data / "splits/.gitkeep").is_file() and (data / "golden/.gitkeep").is_file()
    assert sorted(p.name for p in data.iterdir()) == ["golden", "raw", "splits"]                 # pure layout
    assert (out / "CORPUS_KIND").read_text().strip() == "reference"
    assert M.is_reference_root(data) and not M.is_reference_root(root)
    assert man["ips"][0]["exclusions"] == [{"path": "ext.sv", "reason": "external_parent_soc_include:parent_soc.svh"}]
    text = (out / "reference_manifest.json").read_text()
    assert str(root) not in text and json.loads(text) == man


def test_manifest_is_deterministic_and_relocatable(forge, tmp_path):
    root, doc = forge
    _run(root, doc, tmp_path / "a" / "reference")
    _run(root, doc, tmp_path / "x" / "y" / "reference")
    a = (tmp_path / "a/reference/reference_manifest.json").read_bytes()
    b = (tmp_path / "x/y/reference/reference_manifest.json").read_bytes()
    assert a == b


def test_sources_are_read_only(forge):
    root, doc = forge
    before = M.sources_state(root, _write(root, doc))
    _run(root, doc)
    _run(root, doc)                                   # rebuild from scratch
    assert M.sources_state(root, root / "reference/corpus.yaml") == before
    assert _git(root / "reference/sources/demo", "status", "--porcelain") == ""


def test_refuses_output_inside_sources_or_foreign_directory(forge, tmp_path):
    root, doc = forge
    with pytest.raises(C.CorpusError, match="inside reference/sources"):
        _run(root, doc, root / "reference/sources/demo/out")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x")
    with pytest.raises(C.CorpusError, match="refusing to delete"):
        _run(root, doc, foreign)
    assert (foreign / "keep.txt").is_file()


# ----------------------------------------------------------------------------- summary (AC-026 .. AC-029)
def _fake_root(base: Path) -> Path:
    r = base / "kritva-forge-data"
    (r / "normalized/ir/demo/modules").mkdir(parents=True)
    (r / "normalized/ir/demo/modules/top.yaml").write_text("name: top\n")
    (r / "analysis/reports").mkdir(parents=True)
    for rel in S.REPORTS.values():
        (r / rel).write_text(json.dumps({"status": "PASS"}))
    (r / "generated/prompt/v2/demo").mkdir(parents=True)
    (r / "generated/prompt/v2/demo/top.behavior_aware.txt").write_text("x\n")
    (base / "reference_manifest.json").write_text(json.dumps({"corpus_sha256": "c" * 64, "ips": []}))
    return r


def test_summary_deterministic_and_compare(tmp_path):
    a, b = _fake_root(tmp_path / "a"), _fake_root(tmp_path / "elsewhere" / "b")
    assert S.dumps(S.build(a)) == S.dumps(S.build(b))                 # AC-027 / AC-038 / AC-039
    assert str(tmp_path) not in S.dumps(S.build(a))
    exp = tmp_path / "expected.json"
    assert S.main(["--data-root", str(a), "--write", str(exp)]) == 0
    assert S.main(["--data-root", str(b), "--compare", str(exp)]) == 0
    (b / "generated/prompt/v2/demo/top.behavior_aware.txt").write_text("changed\n")
    (b / "analysis/reports/fsm_report.json").write_text(json.dumps({"status": "FAIL"}))
    assert S.main(["--data-root", str(b), "--compare", str(exp)]) == 1   # AC-028
    keys = [k for k, _, _ in S.diff(json.loads(exp.read_text()), S.build(b))]
    assert "gates.fsm" in keys and "layers.generated/prompt/v2.tree_sha256" in keys


# ----------------------------------------------------------------------------- committed contract (AC-006, AC-012, AC-021, AC-041, AC-052, AC-053)
@pytest.fixture(scope="module")
def committed():
    return C.load(FORGE / C.CORPUS_PATH)


def test_committed_corpus_is_valid_and_pinned(committed):
    ips = {ip["id"]: ip for ip in committed["ips"]}
    assert sorted(ips) == sorted(PINNED) and "yifive" not in ips
    for ip_id, (sub, url, commit) in PINNED.items():
        assert (ips[ip_id]["submodule"], ips[ip_id]["repository"], ips[ip_id]["commit"]) == (sub, url, commit)
        assert ips[ip_id]["license"] == "Apache-2.0"
    assert ips["qspi"]["exclusions"] == [{"path": "src/qspim_top.sv",
                                          "reason": "external_parent_soc_include:user_reg_map.svh"}]


def test_gitmodules_match_corpus(committed):
    cfg = configparser.ConfigParser()
    cfg.read(FORGE / ".gitmodules")
    mods = {cfg[s]["path"]: cfg[s]["url"] for s in cfg.sections()}
    assert mods == {ip["submodule"]: ip["repository"] for ip in committed["ips"]}
    assert all(u.startswith("https://") for u in mods.values())


def test_committed_summary_is_consistent(committed):
    s = json.loads((FORGE / "reference/expected/summary.json").read_text(encoding="utf-8"))
    assert s["schema"] == S.SCHEMA
    assert sorted(s["ips"]) == sorted(ip["id"] for ip in committed["ips"])
    assert s["modules"] == sum(s["ips"].values()) == 149
    assert {x["id"]: x["commit"] for x in s["sources"]} == {ip["id"]: ip["commit"] for ip in committed["ips"]}
    assert set(s["gates"].values()) == {"PASS"}
    assert s["prompt_v2"]["prompts"] == s["prompt_v2"]["sidecars"] == 149
    assert s["prompt_v2"]["leakage"]["failures"] == 0


def test_materialize_committed_corpus(tmp_path, committed):
    """Runs on the real submodules; skipped until `make reference-init`."""
    try:
        C.check_sources(FORGE, committed)
    except C.CorpusError as exc:
        pytest.skip(f"reference submodules not initialised: {exc}")
    man = M.materialize(FORGE, FORGE / C.CORPUS_PATH, tmp_path / "reference")
    exp = json.loads((FORGE / "reference/expected/summary.json").read_text(encoding="utf-8"))
    assert man["corpus_sha256"] == exp["reference_corpus_sha256"]
    assert man["counts"]["ips"] == 5 and man["counts"]["exclusions"] == 1
