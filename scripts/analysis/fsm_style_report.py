#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_style_report.py
# Description : Fsm Style Report implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ---------------------------------------------
# FSM STYLE REPORT
# ---------------------------------------------

import os
import yaml
from collections import Counter

from scripts.core.paths import iter_module_yamls, normalized_root_from_argv

# Canonical module IR only: <normalized-root>/<ip>/modules/*.yaml (KF-DQ-001).
# Usage: python -m <this module> [normalized_root]
ROOT = normalized_root_from_argv()

hist = Counter()

fsm_count = 0

for path in iter_module_yamls(ROOT):

    fn = path.name

    try:

        with open(path) as f:
            data = yaml.safe_load(f)

        fsm = data.get("fsm")

        #
        # Skip modules with no FSM
        #
        if not isinstance(fsm, dict):
            continue

        states = fsm.get(
            "states",
            []
        )

        #
        # Match coverage.py definition
        #
        if len(states) < 2:
            continue

        fsm_count += 1

        style = fsm.get(
            "style"
        )

        if not style:
            style = "unknown"

        hist[style] += 1

    except Exception:
        pass

print("=" * 80)
print("FSM STYLE REPORT")
print("=" * 80)

print(
    "FSMs:",
    fsm_count
)

print()

for style in sorted(hist.keys()):

    print(
        f"{style:20s} : {hist[style]}"
    )

print()

total = sum(hist.values())

if total:

    print("-" * 80)

    for style in sorted(hist.keys()):

        pct = (
            100.0 *
            hist[style] /
            total
        )

        print(
            f"{style:20s} : "
            f"{hist[style]:4d} "
            f"({pct:5.1f}%)"
        )
