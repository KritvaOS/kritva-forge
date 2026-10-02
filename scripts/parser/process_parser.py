# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : process_parser.py
# Description : Process Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
from scripts.rtl_ir.process import new_process

from scripts.parser.statement_parser import parse_statement

from scripts.parser.ast_utils import (
    get_node_text,
    get_node_location,
)

def parse_processes(module):

    processes = []

    for member in module.members:

        if type(member).__name__ == "ProceduralBlockSyntax":
            processes.append(
                parse_process(member)
            )

    return processes

# -------------------------------
#
# -------------------------------
def parse_sensitivity(node):
    """
    TODO:
        Parse TimingControlSyntax into Process IR sensitivity list.
    """
    return []


def parse_process(node):

    if node is None:
        return None

    body = parse_statement(
        node.statement
    )


    process_type = detect_process_type(node)
    
    sensitivity = parse_sensitivity(node)
    

    return new_process(

        process_type=process_type,

        body=body,

        sensitivity=sensitivity,

        text=get_node_text(node),

        syntax_kind=str(node.kind),

        location=get_node_location(node),
    )


def detect_process_type(node):

    stmt = node.statement

    if type(stmt).__name__ != "TimingControlStatementSyntax":
        return "unknown"

    tc_name = type(stmt.timingControl).__name__

    mapping = {
        "AlwaysFFSyntax": "always_ff",
        "AlwaysCombSyntax": "always_comb",
        "AlwaysLatchSyntax": "always_latch",
        "AlwaysSyntax": "always",
    }

    return mapping.get(tc_name, "unknown")

