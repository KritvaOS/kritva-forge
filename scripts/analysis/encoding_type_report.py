#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : encoding_type_report.py
# Description : Encoding Type Report implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------------------------------
# Measure value delivered by
# typedef / parameter / localparam / literal FSM extraction.
# ----------------------------------------------------------

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

            if not isinstance(fsm, dict):
                continue

            if len(fsm.get("states", [])) < 2:
                continue

            fsm_count += 1

            enc = fsm.get(
                "state_encoding",
                {}
            )

            if not enc:

                hist["none"] += 1
                continue

            enc_type = enc.get(
                "type",
                "unknown"
            )

            hist[enc_type] += 1

        except Exception:
            pass

print("=" * 80)
print("FSM ENCODING REPORT")
print("=" * 80)

print(
    "FSMs:",
    fsm_count
)

print()

for k in sorted(hist):

    print(
        f"{k:25s} : {hist[k]}"
    )
