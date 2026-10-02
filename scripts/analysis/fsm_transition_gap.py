#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_transition_gap.py
# Description : Fsm Transition Gap implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# -------------------------------------
# FSM transition coverage report
# -------------------------------------

import os
import yaml

from scripts.core.paths import iter_module_yamls, normalized_root_from_argv

# Canonical module IR only: <normalized-root>/<ip>/modules/*.yaml (KF-DQ-001).
# Usage: python -m <this module> [normalized_root]
ROOT = normalized_root_from_argv()

rows = []

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

        transitions = fsm.get(
            "transitions",
            []
        )

        quality = fsm.get(
            "quality",
            {}
        )

        module_name = data.get(
            "module_name",
            fn.replace(
                ".yaml",
                ""
            )
        )

        rows.append({

            "module":
                module_name,

            "states":
                len(states),

            "transitions":
                len(transitions),

            "coverage":
                quality.get(
                    "transition_coverage",
                    0.0
                ),

            "style":
                fsm.get(
                    "style"
                ),

            "confidence":
                fsm.get(
                    "confidence"
                )
        })

    except Exception:
        pass

#
# sort worst first
#

rows.sort(

    key=lambda x: (

        x["coverage"],
        x["transitions"]

    )
)

print("=" * 80)
print("FSM TRANSITION GAP REPORT")
print("=" * 80)

print()

print(
    f"{'MODULE':30s}"
    f"{'STATES':>8s}"
    f"{'TRANS':>8s}"
    f"{'COV%':>8s}"
    f"{'STYLE':>14s}"
)

print("-" * 80)

for r in rows[:50]:

    print(

        f"{r['module'][:30]:30s}"

        f"{r['states']:8d}"

        f"{r['transitions']:8d}"

        f"{r['coverage']:8.1f}"

        f"{str(r['style']):14s}"
    )

print()

#
# zero transition FSMs
#

zero_trans = [

    r

    for r in rows

    if r["transitions"] == 0
]

print("=" * 80)
print("ZERO TRANSITION FSMS")
print("=" * 80)

for r in zero_trans:

    print(

        f"{r['module']:30s}"

        f" states={r['states']}"
    )

print()

#
# likely extraction misses
#

print("=" * 80)
print("LIKELY EXTRACTION MISSES")
print("=" * 80)

for r in rows:

    if (
        r["states"] >= 4
        and
        r["transitions"] <= 2
    ):

        print(

            f"{r['module']:30s}"

            f" states={r['states']}"

            f" trans={r['transitions']}"
        )
