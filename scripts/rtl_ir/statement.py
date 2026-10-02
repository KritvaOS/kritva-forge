# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statement.py
# Description : Statement implementation
#
# Component   : Kritva Forge
# Module      : rtl_ir
# Layer       : RTL IR
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#  ---------------------------------  
#  
#  ├── Base
#  │      new_statement()
#  │
#  ├── Constructors
#  │      new_assignment_stmt()
#  │      new_if_stmt()
#  │      new_case_stmt()
#  │      new_case_item()
#  │      new_block_stmt()
#  │      new_loop_stmt()
#  │      new_return_stmt()
#  │      new_break_stmt()
#  │      new_continue_stmt()
#  │      new_null_stmt()
#  │      new_delay_stmt()
#  │
#  └── Small helpers
#         statement_type()
#         statement_children()
#  
# --------------------------------

# --------------------------------------------------------
# Helper
# --------------------------------------------------------
def statement_type(stmt):

    if not isinstance(stmt, dict):
        return None

    return stmt.get("stmt_type")


def statement_children(stmt):

    if not isinstance(stmt, dict):
        return []

    return stmt.get("children", [])

# ---------------------------------------------------------
# Base Statement
# ---------------------------------------------------------

def new_statement(
        stmt_type,
        text="",
        syntax_kind=None,
        node_id=None,
        location=None):

    return {

        #
        # Generic information
        #
        "stmt_type": stmt_type,

        "syntax_kind": syntax_kind,

        "text": text,

        "node_id": node_id,

        "location": location,

        #
        # Generic tree
        #
        "children": [],

        #
        # Future analysis
        #
        "metadata": {}
    }

# --------------------------------------
#  ├── Constructors
# --------------------------------------

def new_assignment_stmt(
        lhs,
        rhs,
        blocking=True,
        **kwargs):

    stmt = new_statement(
        stmt_type="assignment",
        **kwargs
    )

    stmt["lhs"] = lhs

    stmt["rhs"] = rhs

    stmt["blocking"] = blocking

    stmt["children"] = [
        lhs,
        rhs,
    ]

    return stmt


def new_if_stmt(
        condition,
        then_stmt,
        else_stmt=None,
        **kwargs):

    stmt = new_statement(
        stmt_type="if",
        **kwargs
    )

    stmt["condition"] = condition

    stmt["then"] = then_stmt

    stmt["else"] = else_stmt

    stmt["children"] = [
        condition,
        then_stmt,
    ]

    if else_stmt is not None:

        stmt["children"].append(
            else_stmt
        )

    return stmt


def new_case_stmt(
        expression,
        items,
        case_type="case",
        **kwargs):

    stmt = new_statement(
        stmt_type="case",
        **kwargs
    )

    stmt["case_type"] = case_type

    stmt["expression"] = expression

    stmt["items"] = items

    stmt["children"] = [
        expression,
        *items,
    ]

    return stmt



def new_case_item(
        labels,
        statement,
        default=False,
        **kwargs):

    stmt = new_statement(
        stmt_type="case_item",
        **kwargs
    )

    stmt["labels"] = labels

    stmt["statement"] = statement

    stmt["default"] = default

    stmt["children"] = [
        *labels,
        statement,
    ]

    return stmt


def new_block_stmt(
        statements,
        **kwargs):

    stmt = new_statement(
        stmt_type="block",
        **kwargs
    )

    stmt["statements"] = statements

    stmt["children"] = list(statements)

    return stmt


def new_loop_stmt(
        loop_type,
        init=None,
        condition=None,
        step=None,
        body=None,
        **kwargs):

    stmt = new_statement(
        stmt_type="loop",
        **kwargs
    )

    stmt["loop_type"] = loop_type

    stmt["init"] = init

    stmt["condition"] = condition

    stmt["step"] = step

    stmt["body"] = body

    stmt["children"] = []

    for child in (
            init,
            condition,
            step,
            body):

        if child is not None:

            stmt["children"].append(child)

    return stmt


def new_return_stmt(
        expression=None,
        **kwargs):

    stmt = new_statement(
        stmt_type="return",
        **kwargs
    )

    stmt["expression"] = expression

    if expression is not None:

        stmt["children"] = [
            expression
        ]

    return stmt


def new_null_stmt(**kwargs):

    return new_statement(
        stmt_type="null",
        **kwargs
    )


def new_break_stmt(**kwargs):

    return new_statement(
        stmt_type="break",
        **kwargs
    )


def new_continue_stmt(**kwargs):

    return new_statement(
        stmt_type="continue",
        **kwargs
    )


def new_delay_stmt(
        delay,
        statement,
        **kwargs):

    stmt = new_statement(
        stmt_type="delay",
        **kwargs
    )

    stmt["delay"] = delay

    stmt["statement"] = statement

    stmt["children"] = [
        delay,
        statement,
    ]

    return stmt


