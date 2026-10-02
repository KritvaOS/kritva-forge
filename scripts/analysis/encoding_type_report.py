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
