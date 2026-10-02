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

ROOT = "out"

hist = Counter()

fsm_count = 0

for root, dirs, files in os.walk(ROOT):

    for fn in files:

        if not fn.endswith(".yaml"):
            continue

        path = os.path.join(root, fn)

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
