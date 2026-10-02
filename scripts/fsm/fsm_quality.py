# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_quality.py
# Description : Fsm Quality implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import re

def expand_transition_target(dst):

    if not dst:
        return []

    dst = str(dst)

    #
    # ternary operator
    #
    m = re.search(
        r'\?\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)',
        dst,
        re.S
    )

    if m:

        return [
            m.group(1),
            m.group(2)
        ]

    if "?" in str(dst):

        print(
            "[TERNARY TARGET]",
            dst
        )

    return [dst]

def find_unknown_targets(fsm):

    states = set(
        get_real_states(fsm)
    )

    unknown = []

    for t in fsm.get(
            "transitions",
            []):

        dst = t.get(
            "to"
        )

        if dst not in states:

            unknown.append(
                dst
            )

    return sorted(
        set(unknown)
    )

def get_real_states(fsm):

    IGNORE = {

        "DEFAULT",
        "default",
        "OTHERS",
        "others"
    }

    return [

        s

        for s in fsm.get(
            "states",
            []
        )

        if s not in IGNORE
    ]


def build_fsm_quality(fsm):

    return {

        "orphan_states":
            find_orphan_states(
                fsm
            ),

        "terminal_states":
            find_terminal_states(
                fsm
            ),

        "unreachable_states":
            find_unreachable_states(
                fsm
            ),

        "self_loops":
            count_self_loops(
                fsm
            ),

        "transition_coverage":
            transition_coverage(
                fsm
            ),

        "score":
            compute_fsm_score(
                fsm
            ),

        "unknown_targets": find_unknown_targets( fsm),

        "num_states": len(fsm.get("states", [])),

        "num_transitions": len(fsm.get("transitions", []))
    }

# --------------------------------------
# Orphan States
# --------------------------------------

def find_orphan_states(fsm):

    orphan = []

    states = get_real_states( fsm)

    transitions = fsm.get(
        "transitions",
        []
    )

    for state in states:

        outgoing = [

            t

            for t in transitions

            if t.get("from") == state
        ]

        if not outgoing:

            orphan.append(
                state
            )

    return orphan


# --------------------------------------
# Terminal States
# --------------------------------------

def find_terminal_states(fsm):

    terminal = []

    states = get_real_states( fsm)

    transitions = fsm.get(
        "transitions",
        []
    )

    for state in states:

        incoming = [

            t

            for t in transitions

            if t.get("to") == state
        ]

        outgoing = [

            t

            for t in transitions

            if t.get("from") == state
        ]

        if incoming and not outgoing:

            terminal.append(
                state
            )

    return terminal

# -----------------------------------
# Reachability Analysis
# -----------------------------------

def find_unreachable_states(fsm):

    reset_state = fsm.get(
        "reset_state"
    )

    if not reset_state:

        return []

    transitions = fsm.get(
        "transitions",
        []
    )

    reachable = set()

    queue = [
        reset_state
    ]

    while queue:

        state = queue.pop(0)

        if state in reachable:
            continue

        reachable.add(
            state
        )

        for t in transitions:

            if t["from"] == state:

                for nxt in expand_transition_target(
                        t["to"]):

                    queue.append(
                        nxt
                    )

    return [

        s

        for s in fsm.get(
            "states",
            []
        )

        if s not in reachable
    ]


# -------------------------------
# Transition Coverage
# -------------------------------


def transition_coverage(fsm):

    states = get_real_states( fsm)

    transitions = fsm.get( "transitions", [])

    if not states:
        return 0.0

    valid_states = set( states)

    covered = set()

    for t in transitions:
        src = t.get("from")
        if src in valid_states:
            covered.add(src)


    return round(

        100.0 *
        len(covered) /
        len(states),

        1
    )


# -----------------------------------
# Self Loops
# -----------------------------------

def count_self_loops(fsm):

    count = 0

    for t in fsm.get(
        "transitions",
        []
    ):

        if (
            t.get("from")
            ==
            t.get("to")
        ):

            count += 1

    return count

# -----------------------------
# Score
# -----------------------------

def compute_fsm_score(fsm):

    orphan = len(
        find_orphan_states(
            fsm
        )
    )

    unreachable = len(
        find_unreachable_states(
            fsm
        )
    )

    coverage = transition_coverage(
        fsm
    )

    if (
        coverage >= 90
        and orphan == 0
    ):

        return "high"

    if coverage >= 70:

        return "medium"

    return "low"
