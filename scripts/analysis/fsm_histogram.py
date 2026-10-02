#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_histogram.py
# Description : Fsm Histogram implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# -----------------------------------------
# Show FSM size distribution.
# -----------------------------------------

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

        summary = data.get(
            "summary",
            {}
        )

        n = summary.get(
            "num_fsm_states",
            0
        )

        hist[n] += 1

        if n > 0:
            fsm_count += 1

    except Exception:
        pass

print("=" * 80)
print("FSM STATE COUNT HISTOGRAM")
print("=" * 80)

for n in sorted(hist):

    print(
        f"{n:3d} states : {hist[n]}"
    )

print()
print(
    "FSM modules:",
    fsm_count
)
