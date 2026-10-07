# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : helpers.py
# Description : Inline RTL to Prompt v2 test helpers (KF-DQ-012)
#
# Component   : Kritva Forge
# Module      : tests/prompt_v2
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Inline RTL -> Semantic IR v2 -> Behavioral Semantics v1 -> Structural Analysis v1 -> FSM Analysis v2 -> Prompt v2."""

from pathlib import Path

from scripts.prompt_v2 import model as P
from scripts.prompt_v2 import render as R
from scripts.prompt_v2.validator import validate_module
from tests.fsm.helpers import stage

GOLDEN = Path(__file__).parent / "golden"


def prompt_root(src: str, base: Path, ip: str = "fx") -> Path:
    """Scratch data repository with the four analysis layers of ``src``; return its root."""
    return stage(src, base, ip=ip)


def prompt_all(src: str, base: Path, ip: str = "fx", validate: bool = True) -> dict:
    """{module: (prompt text, sidecar, inputs)}; every pair must validate against its inputs."""
    root = prompt_root(src, base, ip=ip)
    out = {}
    for ip_, name in R.canonical_modules(root):
        inputs = R.load_inputs(root, ip_, name)
        text, sidecar = R.render(inputs)
        if validate:
            problems = validate_module(text, P.dumps(sidecar), inputs)
            assert problems == [], (name, problems[:5])
        out[name] = (text, sidecar, inputs)
    return out


def write_corpus(root: Path) -> Path:
    R.write_all(root)
    return root
