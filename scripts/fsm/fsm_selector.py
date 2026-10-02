# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_selector.py
# Description : Fsm Selector implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import re

from scripts.fsm.fsm_constants import STATE_SCORE
from scripts.parser.ast_utils import get_primary_role

# ---------------------------------------------------
#
# ---------------------------------------------------

def select_best_state_register(state_scores):
    """
    Select the highest scoring state register.
    """

    if not state_scores:
        return None

    best_sig = None
    best_score = -1
    best_evidence = -1

    for sig, info in state_scores.items():

        score = info.get("score", 0)
        evidence = len(info.get("evidence", []))
    
        if (
            score > best_score or
            (
                score == best_score and
                evidence > best_evidence
            ) or
            (
                score == best_score and
                evidence == best_evidence and
                sig < best_sig
            )
        ):
    
            best_sig = sig
            best_score = score
            best_evidence = evidence


    #
    # Ignore weak candidates
    #

    if best_score <  STATE_SCORE["selection"]["state_threshold"]:
        return None

    return best_sig


def select_best_next_state(next_scores):
    """
    Select the highest scoring next-state signal.

    Parameters
    ----------
    next_scores :
        {
            signal :
            {
                "score": int,
                "evidence": [...]
            }
        }

    Returns
    -------
    str | None
    """

    if not next_scores:
        return None

    #
    # Already sorted by score, but use max()
    # to be safe.
    #

    best_sig = None
    best_score = -1
    best_evidence = -1

    for sig, info in next_scores.items():

        score = info.get("score", 0)
        evidence = len(info.get("evidence", []))
    
        if (
            score > best_score or
            (
                score == best_score and
                evidence > best_evidence
            ) or
            (
                score == best_score and
                evidence == best_evidence and
                sig < best_sig
            )
        ):
    
            best_sig = sig
            best_score = score
            best_evidence = evidence

    #
    # Reject weak candidates
    #

    if best_score < STATE_SCORE["selection"]["next_threshold"]:
        return None

    return best_sig


# ------------------------------------------------------------
# Compute FSM confidence
#
# Returns
#
# {
#     "level" : high | medium | low,
#     "score" : 285,
#     "thresholds" : { ... },
#     "metrics" : { ... },
#     "reasons" : [ ... ]
# }
# ------------------------------------------------------------
def compute_confidence(
        state_scores,
        best_state_reg,
        best_next_state,
        state_value_db,
        always_roles,
        style):

    #
    # No candidate
    #
    if not best_state_reg:
        return {
        
            "level": "low",
        
            "score": 0,
        
            "is_high": False,
            "is_medium": False,
            "is_low": True,
        
            "thresholds": {
        
                "medium": STATE_SCORE["selection"]["medium_confidence"],
        
                "high": STATE_SCORE["selection"]["high_confidence"]
            },
        
            "confidence_percent": 0,
        
            "metrics": {
        
                "state_register": None,
        
                "next_state": None,
        
                "num_states": 0,
        
                "state_role": None,
        
                "next_role": None,

                "fsm_style": "unknown"
            },
        
            "reasons": [
                "No candidate state register detected."
            ]
        }

    #
    # Candidate information
    #
    info = state_scores.get(best_state_reg, {})

    score = info.get("score", 0)

    evidence = list(
        info.get(
            "evidence",
            []
        )
    )

    #
    # Number of symbolic states
    #
    nstates = len(
        state_value_db.get(
            best_state_reg,
            []
        )
    )

    #
    # Roles
    #
    state_role = get_primary_role(always_roles, best_state_reg)
    state_role = state_role.get("type") if state_role else None

    next_role = get_primary_role(always_roles, best_next_state)
    next_role = next_role.get("type") if next_role else None

    #
    # Build explanation
    #
    reasons = list(evidence)

    #
    # Structural observations
    #
    if state_role == "always_ff":

        reasons.append(
            "State register implemented in always_ff."

        )

    elif state_role == "always_comb":

        reasons.append(
            "State register implemented in always_comb."
        )

    elif state_role == "assign":

        reasons.append(
            "State register driven by continuous assignment."
        )

    if best_next_state:

        reasons.append(
            f"Next-state signal detected ({best_next_state})."
        )

    if next_role == "always_comb":

        reasons.append(
            "Next-state implemented in always_comb."
        )

    elif next_role == "always_ff":

        reasons.append(
            "Next-state implemented in always_ff."
        )

    if nstates:

        reasons.append(
            f"{nstates} symbolic state values detected."
        )

    #
    # Determine confidence
    #
    if score >= STATE_SCORE["selection"]["high_confidence"]:

        level = "high"

        reasons.append(
            "Score exceeds High confidence threshold."
        )

    elif score >= STATE_SCORE["selection"]["medium_confidence"]:

        level = "medium"

        reasons.append(
            "Score exceeds Medium confidence threshold."
        )

    else:

        level = "low"

        reasons.append(
            "Score below Medium confidence threshold."
        )

    confidence_percent = max(
        0,
        min(
            100,
            int(
                score * 100 /
                STATE_SCORE["selection"]["high_confidence"]
            )
        )
    )

    reasons = list(dict.fromkeys(reasons))

    #
    # Return result
    #
    return {

        "level": level,

        "score": score,

        "is_high": level == "high",

        "is_medium": level == "medium",

        "is_low": level == "low",


        "thresholds": {

            "medium":
                STATE_SCORE["selection"]["medium_confidence"],

            "high":
                STATE_SCORE["selection"]["high_confidence"]
        },
        "confidence_percent": confidence_percent,

        "metrics": {

            "state_register": best_state_reg,

            "next_state": best_next_state,

            "num_states": nstates,

            "state_role": state_role,

            "next_role": next_role,

            "fsm_style": style,

            "state_score": score,

            "num_evidence": len(evidence),

            "confidence_percent": confidence_percent

        },

        "num_reasons": len(reasons),

        "reasons": reasons

    }



# ------------------------------------------------------------
# Detect FSM implementation style
#
# Returns:
#   one_process
#   two_process
#   three_process
#   distributed
#   unknown
# ------------------------------------------------------------

def detect_fsm_style(
        always_roles,
        best_state_reg,
        best_next_state):

    if not best_state_reg:
        return "unknown"

    state_role = get_primary_role(always_roles, best_state_reg)
    state_role = state_role.get("type") if state_role else None
    
    next_role = get_primary_role(always_roles, best_next_state)
    next_role = next_role.get("type") if next_role else None


    #
    # One-process FSM
    #
    if state_role == "always_ff" and \
       best_next_state is None:

        return "one_process"

    #
    # Two-process FSM
    #
    if state_role == "always_ff" and \
       next_role == "always_comb":

        return "two_process"

    #
    # Three-process FSM
    #
    # (future extension)
    #
    # TODO:
    # Detect dedicated output decode block.
    # For now all always_ff + always_comb FSMs
    # are classified as two_process.

    #if state_role == "always_ff" and \
    #   next_role == "always_comb":

    #    #
    #    # Later:
    #    # detect output decode block
    #    #
    #    return "two_process"

    #
    # Distributed implementation
    #

    if state_role:

        return "distributed"

    return "unknown"

