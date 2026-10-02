#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_quality_report.py
# Description : Fsm Quality Report implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# --------------------------------
# FSM Quality Report
# --------------------------------

import os
import yaml
from collections import Counter

from scripts.core.paths import iter_module_yamls, normalized_root_from_argv

# Canonical module IR only: <normalized-root>/<ip>/modules/*.yaml (KF-DQ-001).
# Usage: python -m <this module> [normalized_root]
ROOT = normalized_root_from_argv()

fsm_count = 0

score_hist = Counter()

fsm_with_orphans = 0
fsm_with_terminal = 0
fsm_with_unreachable = 0

coverage_sum = 0.0
self_loop_sum = 0

worst_fsms = []

for path in iter_module_yamls(ROOT):

    fn = path.name

    try:

        with open(path) as f:
            data = yaml.safe_load(f)

        fsm = data.get("fsm")

        if not isinstance(fsm, dict):
            continue

        states = fsm.get(
            "states",
            []
        )

        if len(states) < 2:
            continue

        quality = fsm.get(
            "quality",
            {}
        )

        fsm_count += 1

        score = quality.get(
            "score",
            "unknown"
        )

        score_hist[score] += 1

        orphan_states = quality.get(
            "orphan_states",
            []
        )

        terminal_states = quality.get(
            "terminal_states",
            []
        )

        unreachable_states = quality.get(
            "unreachable_states",
            []
        )

        unknown_targets = quality.get(
            "unknown_targets",
            []
        )

        if unknown_targets:
            print( "UNKNOWN TARGETS:")
            for t in unknown_targets[:10]:
                print( "   ", t)


        if orphan_states:
            fsm_with_orphans += 1

        if terminal_states:
            fsm_with_terminal += 1

        if unreachable_states:
            fsm_with_unreachable += 1

        coverage = quality.get(
            "transition_coverage",
            0.0
        )

        self_loops = quality.get(
            "self_loops",
            0
        )

        coverage_sum += coverage
        self_loop_sum += self_loops

        module_name = data.get(
            "module_name",
            fn.replace(
                ".yaml",
                ""
            )
        )

        worst_fsms.append({

            "module":
                module_name,

            "score":
                score,

            "coverage":
                coverage,

            "orphans":
                len(orphan_states),

            "terminal":
                len(terminal_states),

            "unreachable":
                len(unreachable_states),
            "unknown_targets":
                len(unknown_targets)
        })

    except Exception:
        pass

print("=" * 80)
print("FSM QUALITY REPORT")
print("=" * 80)

print(
    "FSMs                 :",
    fsm_count
)

print()

print(
    "High Quality         :",
    score_hist["high"]
)

print(
    "Medium Quality       :",
    score_hist["medium"]
)

print(
    "Low Quality          :",
    score_hist["low"]
)

print(
    "Unknown              :",
    score_hist["unknown"]
)

print()

print(
    "FSMs With Orphans    :",
    fsm_with_orphans
)

print(
    "FSMs With Dead Ends  :",
    fsm_with_terminal
)

print(
    "FSMs Unreachable     :",
    fsm_with_unreachable
)

print()

if fsm_count:

    print(
        "Average Coverage     :",
        round(
            coverage_sum / fsm_count,
            1
        ),
        "%"
    )

    print(
        "Average Self Loops   :",
        round(
            self_loop_sum / fsm_count,
            2
        )
    )

print()

#
# Worst FSMs
#

print("=" * 80)
print("FSMs NEEDING REVIEW")
print("=" * 80)

worst_fsms.sort(

    key=lambda x: (
        x["score"] != "low",
        -x["orphans"],
        -x["unreachable"],
        x["coverage"]
    )
)

for item in worst_fsms[:20]:

    if (
        item["score"] == "high"
        and
        item["orphans"] == 0
        and
        item["unreachable"] == 0
    ):
        continue

    print()

    print(
        "MODULE      :",
        item["module"]
    )

    print(
        "SCORE       :",
        item["score"]
    )

    print(
        "COVERAGE    :",
        item["coverage"]
    )

    print(
        "ORPHANS     :",
        item["orphans"]
    )

    print(
        "TERMINAL    :",
        item["terminal"]
    )

    print(
        "UNREACHABLE :",
        item["unreachable"]
    )
    print(
        "UNKNOWN     :",
        item["unknown_targets"]
    )
