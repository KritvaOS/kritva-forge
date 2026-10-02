# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_graph.py
# Description : Fsm Graph implementation
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
from collections import defaultdict

from scripts.rtl_ir.expression_utils import (
    collect_identifiers,
    expression_name,
    expression_to_text,
    expression_identifier,
)


# ----------------------------------------------------------
# Build Dependency Graph
#
# Rev-2.1A
#
# Returns
#
# {
#     assignment_graph : {},
#     dependency_graph : {},
#     always_roles     : {}
# }
# ----------------------------------------------------------

def build_assignment_graph(module_info):

    always_roles = {}
    
    multiple_writers = defaultdict(list)

    assignment_graph = defaultdict(set)

    dependency_graph = defaultdict(
        lambda: {

            "drivers": set(),
            "reads": set(),
            "writers": set(),     
            "role": None,
            "block": None
        }
    )

    always_roles = {}

    #
    # --------------------------------------------------
    # Continuous assigns
    # --------------------------------------------------
    #

    for assign in module_info.get(
            "assigns",
            []):

        lhs_expr = assign.get("lhs")
        
        rhs_expr = assign.get("rhs")

        lhs = expression_identifier(lhs_expr)

        if lhs is None:
            lhs = expression_to_text(lhs_expr)

        ids = collect_identifiers(rhs_expr)

        assignment_graph[lhs].update(ids)

        dependency_graph[lhs]["drivers"].update(ids)

        for sig in ids:

            dependency_graph[sig]["reads"].add(lhs)

        dependency_graph[lhs]["role"] = "assign"

    #
    # --------------------------------------------------
    # Always blocks
    # --------------------------------------------------
    #

    for block_id, blk in enumerate(

            module_info.get(
                "always_blocks",
                []
            )):

        role = blk.get(
            "type",
            "always"
        )

        assignments = blk.get(
            "assignments",
            []
        )

        for a in assignments:

            lhs_expr = a.get("lhs")
            
            rhs_expr = a.get("rhs")

            lhs = expression_identifier(lhs_expr)

            if lhs is None:
                lhs = expression_to_text(lhs_expr)

            ids = collect_identifiers(rhs_expr)

            assignment_graph[lhs].update(ids)

            dependency_graph[lhs]["drivers"].update(ids)

            dependency_graph[lhs]["role"] = role

            dependency_graph[lhs]["block"] = block_id

            dependency_graph[lhs]["writers"].add(block_id)


            #
            # Primary role used by FSM detection
            #
            always_roles[lhs] = {
            
                "type": role,
            
                "block": block_id
            }

            #
            # Optional diagnostic database
            #
            multiple_writers.setdefault(lhs, []).append({
            
                "type": role,
            
                "block": block_id
            })

            #
            # Reverse edges
            #

            for sig in ids:

                dependency_graph[sig]["reads"].add(lhs)

    #
    # --------------------------------------------------
    # Convert sets to sorted lists
    # --------------------------------------------------
    #

    graph = {}

    for sig, deps in assignment_graph.items():

        graph[sig] = sorted(deps)

    dep = {}

    for sig, info in dependency_graph.items():

        dep[sig] = {

            "drivers":

                sorted(
                    info["drivers"]
                ),

            "reads":

                sorted(
                    info["reads"]
                ),

            "writers": sorted(info["writers"]),

            "role":

                info["role"],

            "block":

                info["block"]
        }

    return {

        "assignment_graph": graph,

        "dependency_graph": dep,

        "always_roles": always_roles,

         "multiple_writers": multiple_writers
    }

def build_case_usage_db(module_info):

    usage = defaultdict(int)

    for case in module_info.get(
            "case_statements",
            []):


        expr = case.get("expression")

        name = expression_name(expr)
        
        if name:
            usage[name] += 1


    return dict(usage)

