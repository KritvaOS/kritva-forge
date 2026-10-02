# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_scoring.py
# Description : Fsm Scoring implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import re
from collections import defaultdict
from scripts.parser.ast_utils import extract_identifiers,get_primary_role
from scripts.fsm.fsm_constants import STATE_SCORE


# ------------------------------------------------
# Structural FSM scoring.
# Result:
# {
#    "state_q": 96,
#    "state_d": 42,
#    "opcode": 3
# }
# ------------------------------------------------


def score_state_registers(
        module_info,
        assignment_graph,
        dependency_graph,
        always_roles,
        case_usage,
        state_value_db,
        symbol_db):
    """

    Structural scoring for candidate FSM state registers.

    Scoring:
        +100  Known FSM state register (if already identified)
         +50  Used in case(...)
         +40  Assigned many symbolic FSM state values
         +30  Written in always_ff
         +10  Written in always_comb

    Returns
    -------
    {
        signal :
        {
            "score" : int,
            "evidence" : [...]
        }
    }
    """

    scores = {}

    signals = module_info.get("signals", [])

    for siginfo in signals:

        #
        # --------------------------------------------
        # Signal name
        # --------------------------------------------
        #

        if isinstance(siginfo, dict):
            sig = siginfo.get("name", "").strip()
        else:
            sig = str(siginfo).strip()

        if not sig:
            continue

        score = 0
        evidence = []

        #
        # --------------------------------------------
        # Appears in case(...)
        # --------------------------------------------
        #

        if sig in case_usage:

            cnt = case_usage[sig]

            pts = min(cnt * STATE_SCORE["state_register"]["case_usage_per_hit"], 
                            STATE_SCORE["state_register"]["case_usage_cap"])

            score += pts

            evidence.append(
                f"case_usage({cnt}) +{pts}"
            )

        #
        # --------------------------------------------
        # Has symbolic state values
        # --------------------------------------------
        #

        if sig in state_value_db:

            nstates = len(state_value_db[sig])

            pts = min( nstates * STATE_SCORE["state_register"]["symbolic_state_per"], STATE_SCORE["state_register"]["symbolic_state_cap"])

            score += pts

            evidence.append(
                f"{nstates} symbolic states +{pts}"
            )

        #
        # --------------------------------------------
        # Always role
        # --------------------------------------------
        #

        role = get_primary_role(always_roles, sig)

        if role:

            typ = role.get("type")

            if typ == "always_ff":

                pts   = STATE_SCORE["state_register"]["always_ff"]
                score +=  pts

                evidence.append(
                    f"always_ff +{pts}"
                )

            elif typ == "always_comb":

                pts   = STATE_SCORE["state_register"]["always_comb"]
                score +=  pts

                evidence.append(
                    f"always_comb +{pts}"
                )

            elif typ == "always_latch":

                pts   = STATE_SCORE["state_register"]["always_latch"]
                score +=  pts

                evidence.append(
                    f"always_latch +{pts}"
                )

            elif typ == "assign":

                pts   = STATE_SCORE["state_register"]["continuous_assign"]
                score += pts

                evidence.append(
                    f"continuous_assign +{pts}"
                )

        #
        # --------------------------------------------
        # Dependency graph
        # --------------------------------------------
        #

        dep = dependency_graph.get(sig)

        if dep:

            drivers = dep.get(
                "drivers",
                []
            )

            reads = dep.get(
                "reads",
                []
            )

            #
            # Register driven from another signal
            #

            if len(drivers):

                pts = min(
                    len(drivers) * STATE_SCORE["state_register"]["driver_per"],
                    STATE_SCORE["state_register"]["driver_cap"]
                )

                score += pts

                evidence.append(
                    f"{len(drivers)} drivers +{pts}"
                )

            #
            # Used by other logic
            #

            if len(reads):

                pts = min(
                    len(reads) * STATE_SCORE["state_register"]["fanout_per"],
                    STATE_SCORE["state_register"]["fanout_cap"]
                )

                score += pts

                evidence.append(
                    f"{len(reads)} fanout +{pts}"
                )

        #
        # --------------------------------------------
        # Assignment graph
        # --------------------------------------------
        #

        rhs = assignment_graph.get(sig, [])

        #
        # Symbolic state assignments
        #

        symbolic = 0

        for item in rhs:

            if item in symbol_db:

                symbolic += 1

        if symbolic:

            pts = symbolic * STATE_SCORE["state_register"]["symbolic_assignment"]

            score += pts

            evidence.append(
                f"{symbolic} symbolic assignments +{pts}"
            )

        #
        # Drives *_next signal
        #

        next_cnt = 0

        for item in rhs:

            if item.endswith("_next") \
                    or item.endswith("_nxt"):

                next_cnt += 1

        if next_cnt:

            pts = next_cnt * STATE_SCORE["state_register"]["next_state_edge"]

            score += pts

            evidence.append(
                f"{next_cnt} next-state edge +{pts}"
            )

        #
        # --------------------------------------------
        # FSM self-loop
        #
        # state_q <= state_q
        # --------------------------------------------
        #

        if sig in rhs:

            pts  = STATE_SCORE["state_register"]["self_loop"]
            score += pts

            evidence.append(
                f"self loop +{pts}"
            )

        #
        # --------------------------------------------
        # Register feeds combinational logic
        # --------------------------------------------
        #

        for dst in rhs:

            role = get_primary_role(always_roles, dst)

            if role and role.get("type") == "always_comb":

                pts  = STATE_SCORE["state_register"]["feeds_next_logic"]
                score += pts

                evidence.append(
                    f"feeds {dst} always_comb +{pts}"
                )

        #
        # --------------------------------------------
        # Candidate next-state drives this register
        # --------------------------------------------
        #

        for cand, deps in assignment_graph.items():

            if sig in deps:

                r = get_primary_role(always_roles, cand)

                if r and r.get("type") == "always_comb":

                    pts   = STATE_SCORE["state_register"]["driven_by_comb"]
                    score += pts

                    evidence.append(
                        f"driven by {cand} +{pts}"
                    )

        #
        # --------------------------------------------
        # Small naming bonus
        #
        # ONLY a tie-breaker.
        # --------------------------------------------
        #

        lname = sig.lower()

        if lname.endswith("_state"):

            pts   = STATE_SCORE["state_register"] ["suffix_bonus"]
            score += pts

            evidence.append(
                f"suffix _state +{pts}"
            )

        elif lname.endswith("_fsm"):

            pts   = STATE_SCORE["state_register"] ["suffix_bonus"]
            score += pts

            evidence.append(
                f"suffix _fsm +{pts}"
            )

        elif lname == "state":

            pts  = STATE_SCORE["state_register"] ["suffix_bonus"]
            score += pts

            evidence.append(
                f"name state +{pts}"
            )

        #
        # --------------------------------------------
        #

        if score:

            scores[sig] = {

                "score": score,

                "evidence": evidence
            }

    #
    # Return sorted dictionary
    #

    scores = dict(

        sorted(

            scores.items(),

            key=lambda x:
                x[1]["score"],

            reverse=True

        )

    )

    return scores


def score_next_state_signals(
        module_info,
        state_reg,
        assignment_graph,
        dependency_graph,
        always_roles,
        case_usage,
        state_value_db,
        symbol_db):
    """
    Structural next-state scoring.

    Parameters
    ----------
    state_reg :
        Best state register selected from
        score_state_registers()

    Returns
    -------
    {
        signal :
        {
            "score" : int,
            "evidence" : [...]
        }
    }
    """

    scores = {}

    if not state_reg:
        return scores

    signals = module_info.get("signals", [])

    #
    # Signals assigned into state register
    #
    state_inputs = dependency_graph.get(
        state_reg,
        {}
    ).get(
        "drivers",
        []
    )

    for siginfo in signals:

        if isinstance(siginfo, dict):
            sig = siginfo.get("name", "").strip()
        else:
            sig = str(siginfo).strip()

        if not sig:
            continue

        if sig == state_reg:
            continue

        score = 0
        evidence = []

        #
        ###################################################
        # 1. Directly drives state register
        ###################################################
        #

        if sig in state_inputs:

            pts   = STATE_SCORE["next_state"]["drives_state_reg"]
            score += pts

            evidence.append(
                f"drives {state_reg} +{pts}"
            )

        #
        ###################################################
        # 2. Sequential assignment
        #
        # state_q <= sig
        ###################################################
        #

        for lhs, deps in assignment_graph.items():

            if lhs != state_reg:
                continue

            if sig in deps:

                pts   = STATE_SCORE["next_state"]["seq_assign_state_reg"]
                score += pts

                evidence.append(
                    f"{state_reg} <= {sig} +{pts}"
                )

        #
        ###################################################
        # 3. always_comb role
        ###################################################
        #

        role = get_primary_role(always_roles, sig)

        if role:

            typ = role.get("type")

            if typ == "always_comb":

                pts   = STATE_SCORE["next_state"]["always_comb"]
                score += pts

                evidence.append(
                    f"always_comb +{pts}"
                )

            elif typ == "assign":

                pts   = STATE_SCORE["next_state"]["continuous_assign"]
                score += pts

                evidence.append(
                    f"continuous_assign +{pts}"
                )

            elif typ == "always_ff":

                #
                # Usually not a next-state signal.
                #
                pts   = STATE_SCORE["next_state"]["always_ff_penalty"]
                score += pts


                evidence.append(
                    f"always_ff {pts}"
                )

        #
        ###################################################
        # 4. Appears in case()
        ###################################################
        #

        if sig in case_usage:

            cnt = case_usage[sig]

            pts = min(
                    cnt * STATE_SCORE["next_state"]["case_usage_per_hit"],
                    STATE_SCORE["next_state"]["case_usage_cap"]
                )

            score += pts

            evidence.append(
                f"case_usage({cnt}) +{pts}"
            )

        #
        ###################################################
        # 5. Has symbolic state assignments
        ###################################################
        #

        if sig in state_value_db:

            nstates = len(
                state_value_db[sig]
            )

            pts = min(
                nstates * STATE_SCORE["next_state"]["symbolic_state_per"],
                STATE_SCORE["next_state"]["symbolic_state_cap"]
            )

            score += pts

            evidence.append(
                f"{nstates} symbolic states +{pts}"
            )

        #
        ###################################################
        # 6. Drives symbolic states
        ###################################################
        #

        rhs = assignment_graph.get(
            sig,
            []
        )

        symbolic = 0

        for item in rhs:

            if item in symbol_db:

                symbolic += 1

        if symbolic:

            pts = min(symbolic * 
                    STATE_SCORE["next_state"]["symbolic_assignment_per"], 
                    STATE_SCORE["next_state"]["symbolic_assignment_cap"])

            score += pts

            evidence.append(
                f"{symbolic} symbolic targets +{pts}"
            )

        #
        ###################################################
        # 7. Candidate feeds state register
        ###################################################
        #

        dep = dependency_graph.get(
            sig,
            {}
        )

        reads = dep.get(
            "reads",
            []
        )

        if state_reg in reads:

            pts    = STATE_SCORE["next_state"]["feeds_state_reg"]
            score += pts

            evidence.append(
                f"feeds {state_reg} +{pts}"
            )

        #
        ###################################################
        # 8. Fanout
        ###################################################
        #

        fanout = len(reads)

        if fanout:

            pts = min(
                fanout * STATE_SCORE["next_state"]["fanout_per"],
                STATE_SCORE["next_state"]["fanout_cap"]
            )

            score += pts

            evidence.append(
                f"{fanout} fanout +{pts}"
            )

        #
        ###################################################
        # 9. Candidate used by always_ff
        ###################################################
        #

        for dst in reads:

            role = get_primary_role(always_roles, dst)

            if role and role["type"] == "always_ff":

                pts  = STATE_SCORE["next_state"]["feeds_ff"]
                score += pts

                evidence.append(
                    f"feeds FF {dst} +{pts}"
                )

        #
        ###################################################
        # 10. Small naming bonus
        #
        # Tie-break only
        ###################################################
        #

        lname = sig.lower()

        if lname.endswith("_next"):

            pts  = STATE_SCORE["next_state"]["suffix_bonus"]
            score += pts

            evidence.append(
                f"_next +{pts}"
            )

        elif lname.endswith("_nxt"):

            pts  = STATE_SCORE["next_state"]["suffix_bonus"]
            score += pts

            evidence.append(
                f"_nxt +{pts}"
            )

        elif lname == "next_state":

            pts  = STATE_SCORE["next_state"]["suffix_bonus"]
            score += pts

            evidence.append(
                f"next_state +{pts}"
            )

        #
        ###################################################
        # 11. Never score negative
        ###################################################
        #

        if score < 0:
            score = 0

        if score:

            scores[sig] = {

                "score": score,

                "evidence": evidence

            }

    #
    #######################################################
    # Sort descending
    #######################################################
    #

    scores = dict(

        sorted(

            scores.items(),

            key=lambda x:
                x[1]["score"],

            reverse=True

        )

    )

    return scores
