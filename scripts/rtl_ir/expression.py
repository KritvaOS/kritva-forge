# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : expression.py
# Description : Expression implementation
#
# Component   : Kritva Forge
# Module      : rtl_ir
# Layer       : RTL IR
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# -----------------------------------------------------------------  
#   rtl_ir/expression.py
#   
#   This file should only construct Expression IR objects.
#   
#   It should:
#   
#       ✅ Have no PySlang dependency
#       ✅ Have no parser logic
#       ✅ Have no FSM logic
#       ✅ Only build standardized expression dictionaries
#   
# ------------------------------------------------------------------- 
#  
#  new_expression()
#  new_identifier()
#  new_constant()
#  new_binary()
#  new_unary()
#  new_call()
#  new_bit_select()
#  new_part_select()
#  new_concat()
#  new_repeat()
#  new_conditional()
#  new_unknown()
#
# --------------------------------------------------------------------

"""
rtl_ir/expression.py

RTL Expression Intermediate Representation (IR)

This module contains only IR constructors.
No PySlang dependency.
No parser logic.
"""

from copy import deepcopy


def new_cast(
    cast_type,
    operand,
    text="",
    syntax_kind="",
    node_id=None,
    location=None,
):
    expr = new_expression(
        expr_type="cast",
        text=text,
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )

    expr["cast_type"] = cast_type
    expr["operand"] = operand
    expr["children"] = [
        cast_type,
        operand,
    ]

    return expr

def new_conditional(
    condition,
    true_expr,
    false_expr,
    **kwargs,
):

    expr = new_expression(
        expr_type="conditional",
        **kwargs,
    )

    expr["condition"] = condition
    expr["true_expr"] = true_expr
    expr["false_expr"] = false_expr

    expr["children"] = [
        condition,
        true_expr,
        false_expr,
    ]

    return expr


def walk_expression(expr, ids):
    """
    Recursively walk Expression IR.

    Parameters
    ----------
    expr : Expression IR

    ids : set
        Output identifier set.
    """

    if expr is None:
        return

    if isinstance(expr, str):
        ids.add(expr)
        return

    if not isinstance(expr, dict):
        return

    expr_type = expr.get("expr_type")

    #
    # Identifier
    #
    if expr_type == "identifier":

        ids.add(expr["name"])
        return

    #
    # Generic recursive walk
    #

    for child in expr.get("children", []):
        walk_expression(child, ids)


def expression_type(expr):

    if expr is None:
        return ""

    return expr.get("expr_type", "")



def new_binary(operator,
               lhs,
               rhs,
               text="",
               syntax_kind="",
               node_id=None,
               location=None):

    expr = new_expression(
        expr_type="binary",
        text=text,
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )

    expr["operator"] = operator
    expr["lhs"] = lhs
    expr["rhs"] = rhs
    expr["children"] = [lhs, rhs]

    return expr

def new_call(function,
             arguments,
             text="",
             syntax_kind="",
             node_id=None,
             location=None):

    expr = new_expression(
        expr_type="call",
        text=text,
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )

    expr["function"] = function
    expr["arguments"] = arguments
    expr["children"] = [function] + arguments

    return expr
# ----------------------------------------------------------------------
# Base Expression
# ----------------------------------------------------------------------

def new_expression(expr_type,
                   text="",
                   syntax_kind="",
                   node_id=None,
                   location=None):
    """
    Create a generic expression object.
    """

    return {

        "expr_type": expr_type,
        "syntax_kind": syntax_kind,
        "text": text,
        "node_id": node_id,
        "location": location,
        "children": [],
        "metadata": {}
    }


# ----------------------------------------------------------------------
# Identifier
# ----------------------------------------------------------------------

def new_identifier(name,
                   text=None,
                   syntax_kind="Identifier",
                   node_id=None,
                   location=None):

    expr = new_expression(
        expr_type="identifier",
        text=text or name,
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )

    expr["name"] = name

    return expr


# ----------------------------------------------------------------------
# Constant
# ----------------------------------------------------------------------

def new_constant(value,
                 text=None,
                 syntax_kind="Constant",
                 node_id=None,
                 location=None):

    expr = new_expression(
        expr_type="constant",
        text=text or str(value),
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )

    expr["value"] = value

    return expr


# ----------------------------------------------------------------------
# Unknown
# ----------------------------------------------------------------------

def new_unknown(text="",
                syntax_kind="",
                node_id=None,
                location=None):

    return new_expression(
        expr_type="unknown",
        text=text,
        syntax_kind=syntax_kind,
        node_id=node_id,
        location=location,
    )


# ----------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------

def clone_expression(expr):
    """
    Deep copy an expression.
    """

    return deepcopy(expr)
