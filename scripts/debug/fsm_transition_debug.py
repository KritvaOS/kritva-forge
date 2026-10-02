#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_transition_debug.py
# Description : Fsm Transition Debug implementation
#
# Component   : Kritva Forge
# Module      : debug
# Layer       : Development Tools
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------
# FSM Transition Debug
# ----------------------------------
import os
import yaml

from scripts.core.paths import iter_module_yamls, normalized_root_from_argv

# Canonical module IR only: <normalized-root>/<ip>/modules/*.yaml (KF-DQ-001).
# Usage: python -m <this module> [normalized_root]
ROOT = normalized_root_from_argv()

print("=" * 80)
print("FSM TRANSITION DEBUG")
print("=" * 80)

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

        transitions = fsm.get(
            "transitions",
            []
        )

        if (
            len(states) >= 4
            and
            len(transitions) == 0
        ):

            print()
            print("-" * 80)

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
                "STATE REG:",
                fsm.get(
                    "state_reg"
                )
            )

            print(
                "NEXT STATE:",
                fsm.get(
                    "next_state"
                )
            )

            print(
                "STATES:"
            )

            for s in states:

                print(
                    "   ",
                    s
                )

    except Exception:
        pass
