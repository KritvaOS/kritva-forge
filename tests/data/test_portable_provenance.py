# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_portable_provenance.py
# Description : KF-DQ-002 regression tests for portable provenance paths
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Portable provenance (KF-DQ-002).

Persisted provenance must be repository-relative
(``raw/rtl/original/<path>``) and identical for any checkout location.
Unit tests build throw-away data roots; the artifact scan at the bottom runs
only when ``KRITVA_FORGE_DATA_ROOT`` points at a real data checkout.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.core.paths import (
    ForgeDataPaths,
    find_absolute_paths,
    infer_data_root,
    resolve_provenance_path,
    scan_absolute_paths,
    to_provenance_path,
)

ROOT = Path(__file__).resolve().parents[2]
REL = "raw/rtl/original/common/pulse_gen_type2.sv"

RTL = """\
module pulse_gen_type2 (
    input  logic clk,
    input  logic reset_n,
    input  logic trigger,
    output logic pulse
);
    logic trigger_d;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) trigger_d <= 1'b0;
        else          trigger_d <= trigger;
    end
    assign pulse = trigger & ~trigger_d;
endmodule
"""

FORBIDDEN = ("/tmp/", "/home/", "/workspace/", "/mnt/", "/Users/")


def _make_data_root(base):
    data_root = base / "kritva-forge-data"
    rtl = data_root / REL
    rtl.parent.mkdir(parents=True)
    rtl.write_text(RTL)
    return data_root, rtl


def _assert_portable(source_file):
    assert source_file == REL
    for prefix in FORBIDDEN:
        assert prefix not in source_file
    assert not os.path.isabs(source_file)


def _provenance_values(obj):
    """Yield every ``source_file`` value at any depth of the IR."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "source_file":
                yield value
            yield from _provenance_values(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _provenance_values(item)


def _mask(text):
    text = re.sub(r"node_id: \d+", "node_id: N", text)
    return re.sub(r"BufferID\(\d+\)", "BufferID(N)", text)


# -----------------------------------------------------------------------------
# Path helpers
# -----------------------------------------------------------------------------

def test_to_provenance_path_is_repository_relative(tmp_path):
    data_root, rtl = _make_data_root(tmp_path / "a")

    _assert_portable(to_provenance_path(rtl, data_root))


def test_two_roots_produce_identical_provenance(tmp_path):
    root_a, rtl_a = _make_data_root(tmp_path / "first" / "checkout")
    root_b, rtl_b = _make_data_root(tmp_path / "elsewhere")

    assert to_provenance_path(rtl_a, root_a) == to_provenance_path(rtl_b, root_b) == REL


def test_infer_data_root_from_rtl_and_ir_locations(tmp_path):
    data_root, rtl = _make_data_root(tmp_path)
    (data_root / "normalized" / "ir" / "common").mkdir(parents=True)

    assert infer_data_root(rtl.parent) == data_root.resolve()
    assert infer_data_root(data_root / "normalized" / "ir" / "common") == data_root.resolve()
    assert infer_data_root(tmp_path / "unrelated") is None


def test_path_outside_data_root_is_rejected(tmp_path):
    data_root, _ = _make_data_root(tmp_path / "data")
    outside = tmp_path / "outside.sv"
    outside.write_text(RTL)

    with pytest.raises(ValueError, match="outside the data root"):
        to_provenance_path(outside, data_root)


def test_resolve_provenance_round_trip(tmp_path):
    data_root, rtl = _make_data_root(tmp_path)

    resolved = resolve_provenance_path(REL, data_root)

    assert resolved == rtl.resolve()
    assert resolved.read_text() == RTL


@pytest.mark.parametrize(
    "text",
    [
        "source_file: /home/dinesha/workarea/kritvaos/kritva-forge-data/raw/x.v",
        "source_file: /home/user/x.v",
        '{"path": "/tmp/kf-relocation-test/x.v"}',
        "  - /mnt/data/x.v",
        "path=/Users/someone/x.v",
        "/workspace/x.v",
    ],
)
def test_absolute_path_guard_rejects_host_paths(text):
    assert find_absolute_paths(text)


@pytest.mark.parametrize(
    "text",
    [
        "source_file: raw/rtl/original/common/pulse_gen_type2.sv",
        "source_file: raw/rtl/original/tmp/x.v",
        "comment about a /homepage/ link",
    ],
)
def test_absolute_path_guard_accepts_relative_paths(text):
    assert not find_absolute_paths(text)


# -----------------------------------------------------------------------------
# Real generation path: parser -> module IR -> persisted YAML / prompt
# -----------------------------------------------------------------------------

def _parse(data_root):
    from scripts.parser.rtl_parser_slang import parse_ip

    return parse_ip(str(data_root / "raw" / "rtl" / "original" / "common"))


def test_parser_records_portable_provenance_at_every_depth(tmp_path):
    data_root, rtl = _make_data_root(tmp_path)

    modules, top = _parse(data_root)

    mod = modules["pulse_gen_type2"]
    _assert_portable(mod["source_file"])

    nested = list(_provenance_values({k: v for k, v in mod.items() if k != "source_path"}))
    assert len(nested) > 1
    assert set(nested) == {REL}

    # runtime-only absolute location is kept separately for reading RTL
    assert Path(mod["source_path"]) == rtl.resolve()


def test_persisted_ir_and_prompt_are_portable(tmp_path):
    from scripts.dataset.yaml_generator import write_ip_outputs

    data_root, _ = _make_data_root(tmp_path)
    data = ForgeDataPaths.from_root(data_root)
    modules, top = _parse(data_root)

    write_ip_outputs("common", modules, top, str(data.normalized_ir), prompt_root=str(data.prompts))

    module_yaml = data.module_yaml("common", "pulse_gen_type2")
    spec = yaml.safe_load(module_yaml.read_text())
    _assert_portable(spec["source_file"])
    assert set(_provenance_values(spec)) == {REL}
    assert scan_absolute_paths([data.normalized_ir, data.prompts]) == []


def test_relocated_roots_generate_identical_ir(tmp_path):
    from scripts.dataset.yaml_generator import write_ip_outputs

    outputs = []
    for base in (tmp_path / "home_like", tmp_path / "relocated" / "deeper"):
        data_root, _ = _make_data_root(base)
        data = ForgeDataPaths.from_root(data_root)
        modules, top = _parse(data_root)
        write_ip_outputs("common", modules, top, str(data.normalized_ir), prompt_root=str(data.prompts))
        outputs.append(_mask(data.module_yaml("common", "pulse_gen_type2").read_text()))

    assert outputs[0] == outputs[1]
    assert str(tmp_path) not in outputs[0]


def test_writer_refuses_absolute_provenance(tmp_path):
    from scripts.dataset.yaml_generator import _dump_portable_yaml

    with pytest.raises(ValueError, match="refusing to persist absolute host path"):
        _dump_portable_yaml(
            {"module": "x", "source_file": "/home/dinesha/x.sv"},
            tmp_path / "x.yaml",
        )
    assert not (tmp_path / "x.yaml").exists()


def test_pipeline_guard_rejects_absolute_paths(tmp_path):
    from scripts.pipeline.run_pipeline import check_portable_provenance

    (tmp_path / "ok.yaml").write_text(f"source_file: {REL}\n")
    check_portable_provenance([tmp_path])

    (tmp_path / "bad.jsonl").write_text('{"prompt": "source_file: /tmp/x/raw/y.v"}\n')
    with pytest.raises(RuntimeError, match="1 absolute host path"):
        check_portable_provenance([tmp_path])


def test_pipeline_runs_as_script():
    proc = subprocess.run(
        [sys.executable, "scripts/pipeline/run_pipeline.py", "--help"],
        cwd=ROOT,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--data-root" in proc.stdout


# -----------------------------------------------------------------------------
# Absolute-path guard over a real data checkout
# -----------------------------------------------------------------------------

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_artifacts_have_no_absolute_paths():
    data = ForgeDataPaths.from_root(DATA_ROOT)
    roots = [data.normalized_ir, data.prompts, data.reports, data.pipeline_datasets]

    findings = scan_absolute_paths(roots)

    assert findings == [], [f"{p}:{n}" for p, n, _ in findings[:10]]


@pytest.mark.skipif(not DATA_ROOT, reason="KRITVA_FORGE_DATA_ROOT not set")
def test_data_repository_ir_provenance_is_canonical():
    from scripts.core.paths import iter_module_yamls

    data = ForgeDataPaths.from_root(DATA_ROOT)
    bad = []
    for path in iter_module_yamls(data.normalized_ir):
        for value in set(_provenance_values(yaml.safe_load(path.read_text()))):
            if not str(value).startswith("raw/rtl/original/"):
                bad.append(f"{path.relative_to(data.normalized_ir)}: {value}")

    assert bad == [], bad[:10]
