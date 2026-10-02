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

ROOT = "out"

print("=" * 80)
print("FSM TRANSITION DEBUG")
print("=" * 80)

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
