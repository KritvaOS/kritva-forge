# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_coverage.py
# Description : Fsm Coverage implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import glob
import yaml

total = 0
encoded = 0

for fn in glob.glob("out/**/*.yaml", recursive=True):
    try:
        with open(fn) as f:
            d = yaml.safe_load(f)

        fsm = d.get("fsm", {})
        if not fsm:
            continue

        total += 1

        se = fsm.get("state_encoding", {})
        if se:
            encoded += 1

    except Exception:
        pass

print(f"FSMs        : {total}")
print(f"With Encoding: {encoded}")
print(f"Coverage    : {100.0*encoded/max(total,1):.1f}%")
