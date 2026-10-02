# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_gap_analysis.py
# Description : Fsm Gap Analysis implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# Find modules where no FSM was extracted
# but the RTL looks FSM-like.
# =============================================================================

#!/usr/bin/env python3

import os
import yaml
import re

from scripts.core.paths import iter_module_yamls, normalized_root_from_argv

# Canonical module IR only: <normalized-root>/<ip>/modules/*.yaml (KF-DQ-001).
# Usage: python -m <this module> [normalized_root]
ROOT = normalized_root_from_argv()

print("=" * 80)
print("FSM GAP ANALYSIS")
print("=" * 80)

for path in iter_module_yamls(ROOT):

    fn = path.name

    try:
        with open(path) as f:
            data = yaml.safe_load(f)

        summary = data.get("summary", {})

        fsm_states = summary.get(
            "num_fsm_states",
            0
        )

        if fsm_states != 0:
            continue

        signals = data.get(
            "signals",
            []
        )

        state_signals = []

        for sig in signals:

            name = sig.get(
                "name",
                ""
            )

            if re.search(
                r'(fsm|state)',
                name,
                re.I
            ):
                state_signals.append(
                    name
                )

        case_count = summary.get(
            "num_case_statements",
            0
        )

        ff_count = summary.get(
            "num_always_ff",
            0
        )

        comb_count = summary.get(
            "num_always_comb",
            0
        )

        #
        # Likely FSM candidate
        #
        if (
            case_count > 0
            and
            state_signals
        ):

            print("\n" + "-" * 60)

            print(
                "MODULE:",
                data.get(
                    "module_name",
                    fn.replace(
                        ".yaml",
                        ""
                    )
                )
            )

            print(
                "CASES:",
                case_count
            )

            print(
                "ALWAYS_FF:",
                ff_count
            )

            print(
                "ALWAYS_COMB:",
                comb_count
            )

            print(
                "STATE SIGNALS:"
            )

            for s in state_signals[:10]:
                print(
                    "   ",
                    s
                )

    except Exception:
        pass
