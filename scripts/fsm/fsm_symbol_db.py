# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_symbol_db.py
# Description : Fsm Symbol Db implementation
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
from scripts.rtl_ir.expression_utils import (
    expression_name,
    collect_identifiers,
    expression_to_text,
)



def is_literal_state(token):
    """
    Return True if token looks like a Verilog literal.

    Examples:
        2'b00
        3'b101
        4'hA
        8'd255
        1'bx
        1'bz
    """

    if not token:
        return False

    token = token.strip()

    return re.match(
        r"^\d+'[bBdDhHoO][0-9a-fA-FxXzZ_]+$",
        token
    ) is not None


# ------------------------------------------------
# Find signals assigned symbolic state values.
# Input:
#    state_d = IDLE;
#    state_d = BUSY;
#    state_d = WAIT;
# Output:
# {
#    "state_d":
#    {
#        "IDLE",
#        "BUSY",
#        "WAIT"
#    }
# }
# -------------------------------------------------

def build_symbol_db(module_info):

    if not module_info:
        return {
            "state_value_db": {},
            "symbol_db": {}
        }


    db = defaultdict(list)

    #
    # -----------------------------------------
    # Build unified symbolic database
    # -----------------------------------------
    #

    symbol_db = {}

    for entry in module_info.get("enum_db", []):

        entry_type = entry.get("type", "")

        members = entry.get("members", {})

        for name, value in members.items():

            symbol_db[name] = {

                "name": name,

                "type": entry_type,

                "value": value,

                "node_id": entry.get("node_id"),

                "offset": entry.get("offset"),

                "buffer": entry.get("buffer")
            }

    #
    # -----------------------------------------
    # Scan assignments
    # -----------------------------------------
    #

    for blk in module_info.get(
            "always_blocks",
            []):

        for stmt in blk.get(
                "assignments",
                []):

            lhs_expr = stmt.get("lhs")

            rhs_expr = stmt.get("rhs")

            lhs = expression_name(lhs_expr)

            if not lhs:
            
                lhs = expression_to_text(lhs_expr)


            if not lhs:
                continue

            ids = collect_identifiers(rhs_expr)


            for token in ids:

                #
                # Symbolic enum/parameter/localparam
                #
                info = symbol_db.get(token)

                entry = {
                    
                        "symbol": token,
                    
                        "rhs": rhs_expr,

                        "lhs": lhs_expr,
                    
                        "statement": stmt
                    }
                #
                # Info or Literal state
                #

                if info or is_literal_state(token):

                    if not any(
                            e["symbol"] == token
                            for e in db[lhs]
                    ):
                    
                        db[lhs].append(entry)

    result = {}
    
    for signal, entries in db.items():
    
        result[signal] = []
    
        for entry in entries:
    
            symbol = entry["symbol"]
    
            info = symbol_db.get(symbol)
    
            if info:
    
                result[signal].append({
                    "name": symbol,
                    "type": info["type"],
                    "value": info["value"],
                    "rhs": entry["rhs"]
                })
    
            else:
    
                result[signal].append({
                    "name": symbol,
                    "type": "literal",
                    "value": symbol,
                    "rhs": entry["rhs"]
                })


    
    
    return {

        "state_value_db": result,

        "symbol_db": symbol_db
    }

