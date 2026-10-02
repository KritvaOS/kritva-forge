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

#!/usr/bin/env python3

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
