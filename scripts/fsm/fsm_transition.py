# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_transition.py
# Description : Fsm Transition implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------------------------------------   
#   
#   fsm_transition.py
#   
#   ├── _extract_case_tree()
#   │
#   ├── _walk_transition_body()
#   │
#   ├── extract_transitions()
#   │
#   ├── _collect_actions()
#   │
#   ├── extract_actions()
#   │
#   ├── normalize_transitions()      # future
#   │
#   ├── merge_default_edges()        # future
#   │
#   └── build_transition_graph()
# ----------------------------------------------------------------

import re
from collections import defaultdict
from scripts.parser.ast_utils import extract_identifiers

# ------------------------------------------------------
# Convert every case statement into a normalized tree.
# ------------------------------------------------------
# 
# Input:
#     module_info
#     best_state_reg
#     best_next_state
# ------------------------------------------------------
# Output:
#  [
#      {
#          "block": 0,
#          "expression": "state_q",
#          "items": [
#              {
#                  "states":["IDLE"],
#                  "condition":"1",
#                  "body":[...]
#              },
#              {
#                  "states":["BUSY"],
#                  "condition":"1",
#                  "body":[...]
#              },
#              {
#                  "states":["default"],
#                  "condition":"default",
#                  "body":[...]
#              }
#          ]
#      }
#  ]
# ---------------------------------------------------------
def _extract_case_tree(module_info,
                      best_state_reg):

    trees = []

    for blk in module_info.get("always_blocks", []):

        if blk["type"] != "always_comb":
            continue

        for case in blk.get("case_statements", []):

            expr = case.get("expression")

            #
            # Only FSM case(state)
            #
            if expr != best_state_reg:
                continue

            tree = {

                "block": blk.get("block"),

                "expression": expr,

                "items":[]
            }

            for item in case.get("items", []):

                states = []

                for label in item.get("labels", []):

                    if isinstance(label, dict):

                        states.append(
                            label.get("normalized") or
                            label.get("raw")
                        )

                    else:

                        states.append(label)


                tree["items"].append({

                    "states": states,

                    "condition":"1",

                    "body": item.get("statements", [])
                })

            trees.append(tree)

    return trees

# ------------------------------------------------------------------------
# Convert case tree into transition edges.
# ------------------------------------------------------------------------
# Input: case_tree
# 
# Output:
#  [
#      {
#          "current_state":"IDLE",
#          "next_state":"BUSY",
#          "condition":"start",
#          "priority":0,
#          "default":False
#      },
#      {
#          "current_state":"BUSY",
#          "next_state":"DONE",
#          "condition":"done"
#      }
#  ]

def extract_transitions(case_trees,
                        next_state_signal):
    transitions = []
    for tree in case_trees:
        for item in tree["items"]:
            current_states = item["states"]
            body = item["body"]
            _walk_transition_body(
                body,
                current_states,
                "1",
                next_state_signal,
                transitions
            )
    return transitions


# ---------------------------------------------------------------
# Recursive Walker
# Handles: 
#   Assignment
#   IfStatement
#   CaseStatement
#   BlockStatement
#   ConditionalOperator
#
# recursion automatically supports:
#   nested if
#   nested begin/end
#   nested case
#   
# ---------------------------------------------------------------
def _walk_transition_body(body,
                         current_states,
                         condition,
                         next_signal,
                         transitions):

    for stmt in body:

        typ = stmt.get("type")

        #
        # next_state <= XXX
        #
        if typ == "assignment":

            if stmt["lhs"] != next_signal:
                continue

        if not isinstance(current_states, list):
            current_states = [current_states]
        
            for state in current_states:
            
                transitions.append({
            
                    "current_state": state,
            
                    "next_state": stmt["rhs"],
            
                    "condition": condition,
            
                    "priority": 0,
            
                    "default": False
                })


        #
        # if(...)
        #
        elif typ == "if":

            c = stmt["condition"]

            _walk_transition_body(

                stmt["then"],

                current_states,

                f"({condition}) && ({c})",

                next_signal,

                transitions
            )

            _walk_transition_body(

                stmt["else"],

                current_states,

                f"({condition}) && !({c})",

                next_signal,

                transitions
            )


# ---------------------------------------------------------------
# This is independent of transitions. 
# ---------------------------------------------------------------
# Output:
# {
#      "IDLE":
#      [
#          {
#              "lhs":"busy",
#              "rhs":"0"
#          },
#          {
#              "lhs":"counter",
#              "rhs":"0"
#          }
#      ]
#  }
# ---------------------------------------------------------------

def extract_actions(case_trees,
                    next_state_signal):

    actions = {}

    for tree in case_trees:

        for item in tree["items"]:

            for state in item["states"]:

                actions.setdefault(state, [])

                _collect_actions(

                    item["body"],

                    next_state_signal,

                    actions[state]
                )

    return actions


# -------------------------------------------------------------------
#
# -------------------------------------------------------------------
def _collect_actions(body,
                    next_signal,
                    actions):

    for stmt in body:

        typ = stmt.get("type")

        if typ == "assignment":

            if stmt["lhs"] == next_signal:
                continue

            actions.append(stmt)

        elif typ == "if":

            _collect_actions(
                stmt["then"],
                next_signal,
                actions
            )

            _collect_actions(
                stmt["else"],
                next_signal,
                actions
            )

        elif typ == "block":

            _collect_actions(
                stmt["body"],
                next_signal,
                actions
            )


# ---------------------------------------------------------------
# build_transition_graph()
#
# Output:
#   fsm = {
#   
#       "states":{
#   
#           "IDLE":{
#   
#               "actions":[...]
#   
#           },
#   
#           "BUSY":{
#   
#               "actions":[...]
#   
#           }
#   
#       },
#   
#       "transitions":[
#   
#           ...
#   
#       ]
#   }
# ----------------------------------------------------------------

def build_transition_graph(
        module_info,
        state_reg,
        next_state):

    #
    # Build normalized case tree
    #
    case_tree = _extract_case_tree(
        module_info,
        state_reg
    )

    #
    # Recover transitions
    #
    transitions = extract_transitions(
        case_tree,
        next_state
    )

    #
    # Recover state actions
    #
    actions = extract_actions(
        case_tree,
        next_state
    )

    #
    # Build state list
    #

    states = set()

    for tr in transitions:
    
        states.add(tr["current_state"])
    
        states.add(tr["next_state"])
    
    for s in actions:
    
        states.add(s)
    
    states = sorted(states)

    return {

        "states": states,

        "transitions": transitions,

        "actions": actions
    }
