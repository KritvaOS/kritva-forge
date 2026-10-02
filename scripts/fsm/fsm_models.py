# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_models.py
# Description : Fsm Models implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
from dataclasses import dataclass
from typing import Any


@dataclass
class StructuralFSM:

    assignment_graph: dict
    dependency_graph: dict
    always_roles: dict

    case_usage: dict

    symbol_db: dict
    state_value_db: dict

    state_scores: dict
    next_scores: dict

    best_state_reg: str | None
    best_next_state: str | None

    style: str

    confidence: dict


    def to_dict(self):

        return {

            "assignment_graph":
                self.assignment_graph,

            "dependency_graph":
                self.dependency_graph,

            "always_roles":
                self.always_roles,

            "case_usage":
                self.case_usage,

            "symbol_db":
                self.symbol_db,

            "state_value_db":
                self.state_value_db,

            "state_scores":
                self.state_scores,

            "next_scores":
                self.next_scores,

            "best_state_reg":
                self.best_state_reg,

            "best_next_state":
                self.best_next_state,

            "style":
                self.style,

            "confidence":
                self.confidence
        }
