# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_extractor.py
# Description : Fsm Extractor implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------------------------------------------
# FSM Extractor
# Reference: https://chatgpt.com/c/6a2fa62d-6120-83ee-8644-ae61f11d5f9b

# revision History:
#    Rev-1.0: 15-06-20216
#             > state_reg
#             > next_state
#             > reset_state
#             > states
#             > transitions
#             > two-process FSMs
#             > one-process FSMs (basic support)

# ----------------------------------------------------------------------

#!/usr/bin/env python3

import re
from scripts.parser.ast_utils import (
    debug,
    evaluate_constant_expression,
    normalize_state_value,
)
from scripts.fsm.fsm_transition import build_transition_graph
from scripts.fsm.fsm_quality import build_fsm_quality

from scripts.parser.process_parser import parse_process

from scripts.rtl_ir.expression_utils import expression_name,expression_to_text,contains_identifier,combine_condition,negate_condition

from scripts.rtl_ir.statement_utils import collect_case_statements,find_first_statement,is_assignment,is_block,is_if,collect_assignments


DEBUG_PARAM = True


# --------------------------------------------------
# Helper
# --------------------------------------------------

def build_literal_encoding(states):

    members = {}

    for state in states:

        decoded = evaluate_constant_expression(
            state
        )

        if decoded is None:
            continue

        members[state] = {

            "value": decoded,

            "raw": state
        }

    if not members:
        return None

    width_expr = ""

    for state in members:

        width_expr = decode_sv_width(
            state
        )

        if width_expr:
            break

    return {

        "type":
            "literal_encoding",

        "width_expr":
            width_expr,

        "members":
            members
    }


def is_literal_state(text):

    text = str(text).strip()

    if re.match(
        r"\d+'[bhd][0-9a-fA-F_xzXZ]+",
        text,
        re.I
    ):
        return True

    if re.match(
        r"^\d+$",
        text
    ):
        return True

    return False



def decode_sv_width(value):

    if value is None:
        return ""

    value = str(value).strip()

    #
    # 4'b0010
    # 4'd10
    # 4'hA
    #
    m = re.match(
        r"(\d+)'s?[bhd]",
        value,
        re.I
    )

    if m:

        width = int(m.group(1))

        return f"[{width-1}:0]"

    return ""

# ------------------------------------------------------
#
# ------------------------------------------------------

def find_reset_state(
        processes,
        state_reg):

    if not state_reg:
        return None

    for process in processes:

        #
        # Sequential process only
        #
        if process["process_type"] not in (
            "always",
            "always_ff",
        ):
            continue

        stmt = process["body"]

        reset_signal = process.get("reset")

        if not reset_signal:
            continue


        reset = find_first_statement(
            stmt,
            lambda s:
                is_if(s)
                and
                contains_identifier(
                    s["condition"],
                    process["reset"]
                )
        )

        if reset is None:
            continue

        assigns = collect_assignments(
            reset["then"]
        )

        for a in assigns:

            lhs = expression_name(
                a["lhs"]
            )

            if lhs != state_reg:
                continue

            return normalize_state_value(
                expression_to_text(
                    a["rhs"]
                )
            )

    return None


def attach_state_encoding(
        fsm,
        encoding_db):

    if not encoding_db:
        return fsm

    debug(DEBUG_PARAM, "\nATTACH_ENCODING")
    debug(DEBUG_PARAM, "FSM:", fsm["states"])

    fsm_states = set(
        s
        for s in fsm.get(
            "states",
            []
        )
        if s != "DEFAULT"
    )

    if not fsm_states:
        return fsm

    best_score = 0
    best_enum = None

    for encoding in encoding_db:

        debug(DEBUG_PARAM, "TRY:", list( encoding["members"].keys()))
        debug(DEBUG_PARAM, "OVERLAP:", fsm_states & set( encoding["members"].keys()))

        enum_states = set(
            encoding.get(
                "members",
                {}
            ).keys()
        )

        score = len(
            fsm_states &
            enum_states
        )

        #
        # Debug
        #
        if score > 0:

            debug(DEBUG_PARAM, "[ENCODING MATCH]", encoding["type"], "overlap=", sorted( fsm_states & enum_states))

            debug(DEBUG_PARAM, "[ENUM SCORE]", encoding.get( "type", "unknown"), score)


        debug(DEBUG_PARAM,"")

        debug(DEBUG_PARAM, "candidate =", encoding.get("type"))
        
        debug(DEBUG_PARAM, "score =", score)
        
        debug(DEBUG_PARAM, "best_score =", best_score)

        #
        # Keep highest overlap
        #
        if score > best_score:

            debug(DEBUG_PARAM, "NEW BEST")

            best_score = score
            best_enum = encoding

    #
    # No match found
    #
    required_matches = max(
        2,
        min(3, len(fsm_states))
    )
    if best_score < required_matches :

        debug(DEBUG_PARAM, "\n[NO ENCODING]")

        debug(DEBUG_PARAM, "FSM STATES:")

        debug(DEBUG_PARAM, sorted( fsm_states))

        return fsm

    #
    # Debug
    #
    if DEBUG_PARAM :
        debug(DEBUG_PARAM, "\n[FSM ENCODING MATCH]")

        debug(DEBUG_PARAM, "FSM STATES:")

        debug(DEBUG_PARAM, sorted( fsm_states))

        debug(DEBUG_PARAM, "ENCODING TYPE:", best_enum.get( "type"))

        debug(DEBUG_PARAM, "MATCH SCORE:", best_score)

    #
    # Attach encoding
    #
    fsm["state_encoding"] = {

        "type":
            best_enum.get(
                "type",
                ""
            ),

        "width_expr":
            best_enum.get(
                "width_expr",
                ""
            ),

        "members": {

            k: v

            for k, v in
            best_enum["members"].items()

            if k in fsm_states
        }

    }


    debug(DEBUG_PARAM, "");

    debug(DEBUG_PARAM, "FINAL")
    
    debug(DEBUG_PARAM, best_score)
    
    debug(DEBUG_PARAM, best_enum)

    return fsm


def is_default_case_item(case_item):

    try:

        exprs = getattr(
            case_item,
            "expressions",
            None
        )

        if not exprs:
            return True

        if len(exprs) == 0:
            return True

    except Exception:
        pass

    return False

# --------------------------------------------------
# FSM AST Helpers
# --------------------------------------------------

def ast_state_names(case_item):

    names = []

    try:

        for expr in case_item.expressions:

            if hasattr(expr, "identifier"):
                name = str(expr.identifier)
            else:
                name = str(expr)

            name = re.sub(
                r'//.*?$',
                '',
                name,
                flags=re.MULTILINE
            )

            name = re.sub(
                r'/\*.*?\*/',
                '',
                name,
                flags=re.DOTALL
            )

            name = name.strip()
            if name.startswith("`"):
                name = name[1:]

            #
            # Literal states
            #
            if is_literal_state(name):

                names.append(
                    normalize_state_value(
                        name
                    )
                )

            #
            # Symbolic states
            #
            else:

                names.append(name)

    except Exception:
        pass

    return names


# -------------------------------------------------------
# Helper
# -------------------------------------------------------


# -------------------------------------------------------
# Find state register
# -------------------------------------------------------

def find_state_register(
        processes,
        structural):

    if not structural:
        return {
            "state_reg": None,
            "next_state": None,
            "reset_state": None
        }

    state_reg = structural.get(
        "best_state_reg"
    )

    next_state = structural.get(
        "best_next_state"
    )

    reset_state = find_reset_state(
        processes,
        state_reg
    )

    return {

        "state_reg":
            state_reg,

        "next_state":
            next_state,

        "reset_state":
            reset_state
    }


# -------------------------------------------------------
# Transition extraction
# -------------------------------------------------------

def emit_transition(
        transitions,
        from_state,
        to_state,
        condition):

    if not to_state:
        return

    cond = (
        condition
        if condition
        else "1"
    )

    #
    # Prevent duplicates
    #
    for t in transitions:

        if (
            t["from"] == from_state and
            t["to"] == to_state and
            t["condition"] == cond
        ):
            return

    transitions.append({

        "from": from_state,

        "to": to_state,

        "condition": cond
    })


def emit_action(
        actions,
        lhs,
        rhs,
        condition):

    if not lhs:
        return

    cond = (
        condition
        if condition
        else "1"
    )

    for a in actions:

        if (
            a["lhs"] == lhs
            and
            a["rhs"] == rhs
            and
            a["condition"] == cond
        ):
            return

    actions.append({

        "lhs": lhs,
        "rhs": rhs,
        "condition": cond
    })
# -------------------------------------------------------
# Recursive condition walker
# -------------------------------------------------------

def walk_transition_tree(

        stmt,

        current_state,

        target_signal,

        condition,

        transitions):


    if is_if(stmt):
    
        cond = expression_to_text(stmt["condition"])
    
        then_cond = combine_condition(
            condition,
            cond
        )
    
        walk_transition_tree(
            stmt["then"],
            current_state,
            target_signal,
            then_cond,
            transitions
        )
    
        if stmt["else"]:
    
            else_cond = negate_condition(
                condition,
                cond
            )
    
            walk_transition_tree(
                stmt["else"],
                current_state,
                target_signal,
                else_cond,
                transitions
            )
    
        return


    # Assignment

    if is_assignment(stmt):
    
        lhs = expression_name(
            stmt["lhs"]
        )
    
        if lhs == target_signal:
    
            emit_transition(
    
                transitions,
    
                current_state,
    
                normalize_state_value(
    
                    expression_to_text(
                        stmt["rhs"]
                    )
                ),
    
                condition
            )
    
        return

    # Block
    if is_block(stmt):
    
        for child in stmt["statements"]:
    
            walk_transition_tree(
    
                child,
    
                current_state,
    
                target_signal,
    
                condition,
    
                transitions
            )
    
        return

    #
    # Unsupported Statement
    #
    return


def walk_action_tree(

    stmt,

    state_reg,

    current_condition,

    actions
    ):

    if is_assignment(stmt):
    
        lhs = expression_name(stmt["lhs"])
    
        #
        # Ignore FSM transition
        #
        if lhs == state_reg:
            return
    
        #
        # Everything else is an action
        #
        emit_action(

            actions,
        
            expression_to_text(stmt["lhs"]),
        
            expression_to_text(stmt["rhs"]),
        
            current_condition
        )

    
        return

    if is_block(stmt):
    
        for child in stmt["statements"]:
    
            walk_action_tree(
    
                child,
    
                state_reg,
    
                current_condition,
    
                actions
            )
    
        return

    #
    # IF Statement
    #
    if is_if(stmt):
    
        cond = expression_to_text(
            stmt["condition"]
        )
    
        then_condition = combine_condition(
            current_condition,
            cond
        )
    
        walk_action_tree(
    
            stmt["then"],
    
            state_reg,
    
            then_condition,
    
            actions
        )
    
        #
        # ELSE branch
        #
        if stmt["else"]:
    
            else_condition = negate_condition(
    
                current_condition,
    
                cond
            )
    
            walk_action_tree(
    
                stmt["else"],
    
                state_reg,
    
                else_condition,
    
                actions
            )
    
        return
    
    
    #
    # Unsupported statement
    #
    return




# -------------------------------------------------------
# Find case(state)
# -------------------------------------------------------

def find_state_case(
        process,
        state_reg):

    cases = collect_case_statements(
        process["body"]
    )

    for case in cases:

        expr = case["expression"]

        if expression_name(expr) == state_reg:

            return case

    return None


def synthesize_self_transitions(
        states,
        transitions):

    result = list(transitions)

    for state in states:

        #
        # Ignore DEFAULT
        #
        if state == "DEFAULT":
            continue

        outgoing = [
            t
            for t in transitions
            if (
                t["from"] == state
                and
                t["to"] != state
            )
        ]

        if not outgoing:
            continue

        if len(outgoing) != 1:
            continue

        cond = outgoing[0]["condition"]

        if (
            not cond
            or cond == "1"
        ):
            continue

        emit_transition(
            result,
            state,
            state,
            f"!({cond})"
        )

    return result

# -------------------------------------------------------
# Main API
# -------------------------------------------------------
def extract_fsm_ast(
        module,
        module_info=None):

    fsm = {

        "state_reg": None,

        "next_state": None,

        "reset_state": None,

        "states": [],

        "transitions": [],

        "state_actions": {},

        "state_encoding": None,

        "style": "unknown",

        "confidence": "low",

        "quality": {},

        "structural": {}
    }

    #
    # ------------------------------------------------
    # Build Process IR
    # ------------------------------------------------
    #
    
    processes = []
    
    for member in module.members:
    
        #
        # Only procedural blocks
        #
        if type(member).__name__ != "ProceduralBlockSyntax":
            continue
    
        process = parse_process(member)
    
        if process is not None:
    
            processes.append(process)


    #
    # ------------------------------------------------
    # Structural Analysis
    # ------------------------------------------------
    #

    structural = {}

    if module_info:

        try:

            structural = module_info.get( "structural", {})
            
            state_reg = structural.get( "best_state_reg")
            next_state = structural.get( "best_next_state")

        except Exception as e:

            print(
                "[WARN] Structural FSM analysis:",
                e
            )

    fsm["structural"] = structural

    # ------------------------------------------------
    # State register detection
    # ------------------------------------------------
    #

    info = find_state_register(
    
        processes,
    
        structural
    
    )

    fsm["state_reg"] = info.get(
        "state_reg"
    )

    fsm["next_state"] = info.get(
        "next_state"
    )

    fsm["reset_state"] = info.get(
        "reset_state"
    )

    if not fsm["state_reg"]:

        return {}

    #
    # ------------------------------------------------
    # Find case(state)
    # ------------------------------------------------
    #

    case_node = None
    
    for process in processes:
    
        case_node = find_state_case(
    
            process,
    
            fsm["state_reg"]
    
        )
    
        if case_node:
    
            break

    if not case_node:

        return fsm

    # ------------------------------------------------
    # build transition graph
    # ------------------------------------------------

    transition_graph = build_transition_graph(
    
        processes,
    
        module_info,
    
        fsm["state_reg"],
    
        fsm["next_state"]
    
    )


    fsm["states"] = transition_graph["states"]

    fsm["transitions"] = transition_graph["transitions"]

    fsm["state_actions"] = transition_graph["actions"]

    # ------------------------------------------------
    # Encoding
    # ------------------------------------------------
    #

    encoding_db = []

    if module_info:
    
        encoding_db = list(
            module_info.get(
                "enum_db",
                []
            )
        )


    #
    # Literal encoding fallback
    #

    literal = build_literal_encoding(

        fsm["states"]

    )

    if literal:

        encoding_db.append(literal)

    attach_state_encoding(

        fsm,

        encoding_db

    )

    #
    # ------------------------------------------------
    # Structural refinement
    # ------------------------------------------------
    #

    if structural:

        fsm["state_reg"] = structural.get(
            "best_state_reg",
            fsm["state_reg"]
        )

        fsm["next_state"] = structural.get(
            "best_next_state",
            fsm["next_state"]
        )

        fsm["style"] = structural.get(
            "style",
            fsm["style"]
        )

        fsm["confidence"] = structural.get(
            "confidence",
            fsm["confidence"]
        )

    #
    # ------------------------------------------------
    # FSM Quality
    # ------------------------------------------------
    #

    try:

        fsm["quality"] = build_fsm_quality(

            fsm

        )

    except Exception:

        pass

    return fsm
