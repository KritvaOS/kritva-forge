# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statement_walker.py
# Description : Statement Walker implementation
#
# Component   : Kritva Forge
# Module      : analysis
# Layer       : Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# -----------------------------
# Generic walker
# -----------------------------

def walk_statement_tree(
        stmt,
        condition,
        callback,
        context):

    if stmt is None:
        return

    #
    # Assignment
    #
    if is_assignment(stmt):

        callback(
            stmt,
            condition,
            context
        )

        return

    #
    # Block
    #
    if is_block(stmt):

        for child in stmt["statements"]:

            walk_statement_tree(
                child,
                condition,
                callback,
                context
            )

        return

    #
    # If
    #
    if is_if(stmt):

        cond = expression_to_text(
            stmt["condition"]
        )

        walk_statement_tree(

            stmt["then"],

            combine_condition(
                condition,
                cond
            ),

            callback,

            context
        )

        if stmt["else"]:

            walk_statement_tree(

                stmt["else"],

                negate_condition(
                    condition,
                    cond
                ),

                callback,

                context
            )

        return

