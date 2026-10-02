# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_constants.py
# Description : Fsm Constants implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
STATE_SCORE = {

    # -----------------------------------------
    # State Register Scoring
    # -----------------------------------------

    "state_register": {
        "case_usage_per_hit"    : 60,
        "case_usage_cap"        : 180,
        "always_ff"             : 80,
        "always_comb"           : 20,
        "driver_per"            : 2,
        "driver_cap"            : 20,
        "fanout_per"            : 3,
        "fanout_cap"            : 30,
        "symbolic_assignment"   : 15,
        "suffix_bonus"          : 5,
        "self_loop"             : 20,
        "driven_by_comb"        : 40,
        "feeds_next_logic"      : 25,
        "symbolic_state_per"    : 4,
        "symbolic_state_cap"    : 80,
        "next_state_edge"       : 15,
        "always_latch"          : 10,
        "continuous_assign"     : 5,

    },    

    # -----------------------------------------
    # Next-State Scoring
    # -----------------------------------------

    "next_state": {

        #
        # Strong indicators
        #
        # Direct connection into the selected state register.
        "drives_state_reg"         : 120,
   
        # Assignment of candidate into the sequential state register.
        "seq_assign_state_reg"     : 100,
   
        # Candidate is implemented in combinational logic.
        "always_comb"              : 60,
    
        #
        # Weak indicators
        #
        "continuous_assign"        : 15,
    
        "always_ff_penalty"        : -40,
    
        #
        # Structural
        #
        "case_usage_per_hit"       : 40,
        "case_usage_cap"           : 80,
    
        "symbolic_state_per"       : 4,
        "symbolic_state_cap"       : 50,
    
        #
        # Assignment graph
        #
        # Candidate assigns symbolic enum/localparam/parameter states.
        "symbolic_assignment_per"  : 12,
        "symbolic_assignment_cap"  : 60,
    
        #
        # Connectivity
        #
        # Candidate feeds the selected state register through dependencies.
        "feeds_state_reg"          : 80,
    
        "fanout_per"               : 2,
        "fanout_cap"               : 20,
   
        # Candidate is consumed by sequential logic.
        "feeds_ff"                 : 20,
    
        #
        # Naming
        #
        "suffix_bonus"             : 5,
    },



    # -----------------------------------------
    # Confidence Thresholds
    # -----------------------------------------

    "selection": {
        #
        # Candidate selection
        #
        "state_threshold":       100,
        "next_threshold":         80,

        #
        # Confidence
        #
        "low_confidence":         0,
        "medium_confidence":    160,
        "high_confidence":      280,
    }
}
