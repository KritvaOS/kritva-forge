# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_stable_identity.py
# Description : KF-DQ-003 regression tests for deterministic node/buffer identity
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Stable content identity (KF-DQ-003).

``node_id`` and ``buffer`` must be identical across repeated runs, relocated
data roots and parse order, and distinct for distinct constructs.  No
masking of ``node_id`` / ``buffer`` is used anywhere in this module.
"""

import ast
import os
import re
from pathlib import Path

import pytest
import yaml

from scripts.core.identity import IDENTITY_VERSION, node_identity, stable_digest
from scripts.core.paths import ForgeDataPaths, find_absolute_paths, iter_module_yamls

ROOT = Path(__file__).resolve().parents[2]

DEFS_SVH = """\
`define WIDTH_OF(x) (x)
localparam int INC_DEPTH = 4;
"""

ALPHA = """\
module alpha #(parameter int WIDTH = 8) (
    input  logic             clk,
    input  logic [WIDTH-1:0] d,
    output logic [WIDTH-1:0] q,
    output logic [`WIDTH_OF(3):0] m1,
    output logic [`WIDTH_OF(3):0] m2
);
    `include "defs.svh"
    logic [WIDTH-1:0] r;
    assign q = r;
    assign m1 = '0;
    assign m2 = '0;
    always_ff @(posedge clk) r <= d;
endmodule
"""

BETA = """\
module beta #(parameter int WIDTH = 8) (
    input  logic             clk,
    input  logic [WIDTH-1:0] d,
    output logic [WIDTH-1:0] q
);
    logic [WIDTH-1:0] r;
    assign q = r;
    assign q = r;
    always_ff @(posedge clk) r <= d;
endmodule
"""


def _make_data_root(base):
    data_root = base / "kritva-forge-data"
    ip = data_root / "raw" / "rtl" / "original" / "demo"
    ip.mkdir(parents=True)
    (ip / "alpha.sv").write_text(ALPHA)
    (ip / "beta.sv").write_text(BETA)
    (ip / "defs.svh").write_text(DEFS_SVH)
    (ip / "files.f").write_text("+incdir+.\nalpha.sv\nbeta.sv\n")
    return data_root


def _parse(data_root):
    from scripts.parser.rtl_parser_slang import parse_ip

    return parse_ip(str(data_root / "raw" / "rtl" / "original" / "demo"))


def _nodes(obj):
    """Yield every dict carrying a node_id, at any depth."""
    if isinstance(obj, dict):
        if obj.get("node_id") is not None:
            yield obj
        for value in obj.values():
            yield from _nodes(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _nodes(item)


def _identities(modules):
    """(module, node_id, buffer, syntax_type, offset) for every persisted node."""
    out = []
    for name in sorted(modules):
        mod = {k: v for k, v in modules[name].items() if k != "source_path"}
        for node in _nodes(mod):
            out.append((name, node["node_id"], node.get("buffer"), node["syntax_type"], node.get("offset")))
    return out


def _write(data_root):
    from scripts.dataset.yaml_generator import write_ip_outputs

    data = ForgeDataPaths.from_root(data_root)
    modules, top = _parse(data_root)
    write_ip_outputs("demo", modules, top, str(data.normalized_ir), prompt_root=str(data.prompts))
    return {
        p.name: p.read_text()
        for p in sorted(iter_module_yamls(data.normalized_ir))
    }


# -----------------------------------------------------------------------------
# Identity model
# -----------------------------------------------------------------------------

def test_identity_algorithm_is_pinned():
    """Golden value: changing the payload requires bumping IDENTITY_VERSION."""
    assert IDENTITY_VERSION == 1
    assert node_identity(
        "raw/rtl/original/uart/uart_tx.v",
        "ParameterDeclarationStatementSyntax",
        "raw/rtl/original/uart/uart_tx.v|342",
        "raw/rtl/original/uart/uart_tx.v|360",
    ) == "n1:" + stable_digest(
        "kf-node", "v1",
        "raw/rtl/original/uart/uart_tx.v",
        "ParameterDeclarationStatementSyntax",
        "raw/rtl/original/uart/uart_tx.v|342",
        "raw/rtl/original/uart/uart_tx.v|360",
    )
    assert re.fullmatch(r"n1:[0-9a-f]{16}", node_identity("a", "b", "c", "d"))


def test_identity_versioned_in_module_ir(tmp_path):
    outputs = _write(_make_data_root(tmp_path))

    for text in outputs.values():
        assert yaml.safe_load(text)["identity_version"] == IDENTITY_VERSION


def test_identity_sources_have_no_runtime_identity():
    """ID-02/ID-03/ID-04: no id()/hash()/uuid/time/pid calls in the identity code path."""
    forbidden_calls = {"id", "hash", "getpid", "gethostname", "getuser", "uuid1", "uuid4", "time", "now"}
    for rel in ("scripts/core/identity.py", "scripts/parser/rtl_parser_slang.py"):
        tree = ast.parse((ROOT / rel).read_text())
        calls = {
            (node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert not calls & forbidden_calls, (rel, calls & forbidden_calls)


# -----------------------------------------------------------------------------
# Stability
# -----------------------------------------------------------------------------

def test_stable_node_ids(tmp_path):
    data_root = _make_data_root(tmp_path)

    first = _identities(_parse(data_root)[0])
    second = _identities(_parse(data_root)[0])

    assert first and first == second
    assert all(re.fullmatch(r"n1:[0-9a-f]{16}", nid) for _, nid, *_ in first)


def test_stable_buffer_ids(tmp_path):
    data_root = _make_data_root(tmp_path)

    buffers = {(m, st, off): buf for m, _, buf, st, off in _identities(_parse(data_root)[0])}

    assert set(buffers.values()) <= {
        "raw/rtl/original/demo/alpha.sv",
        "raw/rtl/original/demo/beta.sv",
        "raw/rtl/original/demo/defs.svh",
    }
    # the included localparam is attributed to the include file, not alpha.sv
    assert "raw/rtl/original/demo/defs.svh" in buffers.values()
    assert not any("BufferID" in str(b) for b in buffers.values())


def test_identity_repeatability(tmp_path):
    """Unrelated parsing in between (shared pyslang state) must not change identities."""
    from scripts.parser.rtl_parser_slang import parse_ip

    data_root = _make_data_root(tmp_path / "a")
    other = _make_data_root(tmp_path / "noise")
    (other / "raw/rtl/original/demo/gamma.sv").write_text(BETA.replace("beta", "gamma"))

    first = _write(data_root)
    parse_ip(str(other / "raw/rtl/original/demo"))
    parse_ip(str(other / "raw/rtl/original/demo"))
    second = _write(data_root)

    assert first == second


def test_identity_relocation(tmp_path):
    original = _write(_make_data_root(tmp_path / "home" / "user" / "checkout"))
    relocated = _write(_make_data_root(tmp_path / "relocated"))

    assert original == relocated
    for text in original.values():
        assert not find_absolute_paths(text)
        assert str(tmp_path) not in text


def test_identity_deterministic_ordering(tmp_path):
    """Per-file identities do not depend on which files were parsed first."""
    from scripts.parser.rtl_parser_slang import parse_file

    data_root = _make_data_root(tmp_path)
    ip = data_root / "raw/rtl/original/demo"
    files = [ip / "alpha.sv", ip / "beta.sv"]

    def run(order):
        result = {}
        for path in order:
            rel = str(path.relative_to(data_root))
            result.update(parse_file(str(path), [str(ip)], source_file=rel, data_root=str(data_root)))
        return _identities(result)

    assert run(files) == run(list(reversed(files)))


def test_identity_collision_scope(tmp_path):
    ids = _identities(_parse(_make_data_root(tmp_path))[0])

    by_id = {}
    for module, nid, buf, syntax_type, offset in ids:
        by_id.setdefault(nid, set()).add((module, buf, syntax_type, offset))

    # distinct constructs never share an identity
    assert all(len(v) == 1 for v in by_id.values()), [v for v in by_id.values() if len(v) > 1]

    def ids_of(module, syntax_type):
        return [nid for m, nid, _, st, _ in ids if m == module and st == syntax_type]

    # same construct name (parameter WIDTH, port clk, ...) in different modules
    assert set(ids_of("alpha", "ParameterDeclarationSyntax")).isdisjoint(ids_of("beta", "ParameterDeclarationSyntax"))
    # different constructs in the same module
    assert len(set(nid for m, nid, *_ in ids if m == "alpha")) > 5
    # textually identical constructs at different source locations
    beta_assigns = ids_of("beta", "ContinuousAssignSyntax")
    assert len(beta_assigns) == 2 and len(set(beta_assigns)) == 2
    # the same macro expanded at two sites (ports m1 / m2)
    alpha_ports = [n for n in _nodes(_parse(_make_data_root(tmp_path / "b"))[0]["alpha"]["interfaces"])
                   if n.get("name") in ("m1", "m2")]
    assert len({p["node_id"] for p in alpha_ports}) == 2


def test_identity_excludes_absolute_paths(tmp_path):
    data_root = _make_data_root(tmp_path)
    ids = _identities(_parse(data_root)[0])

    for _, nid, buf, *_ in ids:
        assert str(tmp_path) not in nid and str(tmp_path) not in str(buf)
        assert not os.path.isabs(str(buf))


# -----------------------------------------------------------------------------
# Real data checkout (runs with KRITVA_FORGE_DATA_ROOT)
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_identities_are_stable_form():
    data = ForgeDataPaths.from_root(DATA_ROOT)
    problems = []
    for path in iter_module_yamls(data.normalized_ir):
        spec = yaml.safe_load(path.read_text())
        if spec.get("identity_version") != IDENTITY_VERSION:
            problems.append(f"{path.name}: identity_version {spec.get('identity_version')}")
        seen = {}
        for node in _nodes(spec):
            nid = node["node_id"]
            if not re.fullmatch(r"n1:[0-9a-f]{16}", str(nid)):
                problems.append(f"{path.name}: node_id {nid}")
            if not str(node.get("buffer", "")).startswith("raw/rtl/"):
                problems.append(f"{path.name}: buffer {node.get('buffer')}")
            key = (node.get("syntax_type"), node.get("offset"), node.get("buffer"))
            if seen.setdefault(nid, key) != key:
                problems.append(f"{path.name}: collision {nid}")
    assert problems == [], problems[:10]
