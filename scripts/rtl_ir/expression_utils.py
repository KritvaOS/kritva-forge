# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : expression_utils.py
# Description : Expression Utils implementation
#
# Component   : Kritva Forge
# Module      : rtl_ir
# Layer       : RTL IR
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# -------------------------------------------------
#    expression_utils.py
#    
#    ├── Query
#    │      expression_type()
#    │      expression_name()
#    │      expression_text()
#    │      expression_operator()
#    │      expression_label()
#    │      expression_children() --
#    │
#    ├── Predicate
#    │      is_identifier() --
#    │      is_constant() --
#    │      is_binary() --
#    │      is_call() --
#    │      is_concat() --
#    │
#    ├── Visitor
#    │      walk_expression() --
#    │
#    ├── Search
#    │      collect_identifiers() --
#    │      collect_constants()
#    │      collect_calls()
#    │      find_first()
#    │      find_all()
#    │
#    ├── Clone
#    │      clone_expression()
#    │
#    ├── Replace
#    │      replace_expression()
#    │
#    ├── Statistics
#    │      expression_depth()
#    │      expression_size()
#    │      expression_leaf_count()
#    │
#    └── Pretty Printer
#           pretty_print()
# -----------------------------------------

import re
import copy


# -----------------------------------------
#    ├── Query
# -----------------------------------------

def expression_type(expr):

    if not isinstance(expr, dict):
        return None

    return expr.get("expr_type")


def expression_text(expr):

    if not isinstance(expr, dict):
        return ""

    return expr.get("text", "")


def expression_name(expr):

    if not isinstance(expr, dict):
        return None

    return expr.get("name")

def expression_operator(expr):

    if not isinstance(expr, dict):
        return None

    return expr.get("operator")


def expression_label(expr):

    expr_type = expression_type(expr)

    if expr_type == "identifier":
        return expression_name(expr)

    if expr_type == "constant":
        return expr.get("value", "")

    if expr_type == "binary":
        return expression_operator(expr)

    if expr_type == "call":
        return expr.get("function", "")

    if expr_type == "member_access":
        return "."

    if expr_type == "identifier_select":
        return "select"

    if expr_type == "element_select":
        return "[]"

    if expr_type == "bit_select":
        return "bit"

    if expr_type == "range_select":
        return ":"

    if expr_type == "concat":
        return "{}"

    if expr_type == "multiple_concat":
        return "{{}}"

    return expression_text(expr)


def expression_children(expr):
    """
    Return child expressions.

    Always returns a list.
    """

    if expr is None:
        return []

    if not isinstance(expr, dict):
        return []

    children = expr.get("children")

    if children is None:
        return []

    #
    # Remove invalid entries
    #
    return [

        child
    
        for child in children
    
        if isinstance(child, dict)
    
    ]


# -----------------------------------

def expression_identifier(expr):
    """
    Return identifier name if this expression is
    exactly an identifier.
    """

    if is_identifier(expr):
        return expression_name(expr)

    return None

def expression_is_signal(expr):
    return is_identifier(expr) \
        or is_member_access(expr) \
        or is_identifier_select(expr)


# -------------------------------
#    ├── Predicate
# -------------------------------

def is_identifier(expr):

    return expression_type(expr) == "identifier"


def is_constant(expr):

    return expression_type(expr) == "constant"


def is_binary(expr):

    return expression_type(expr) == "binary"


def is_call(expr):

    return expression_type(expr) == "call"


def is_concat(expr):

    return expression_type(expr) == "concat"


def is_unknown(expr):

    return expression_type(expr) == "unknown"


# -------------------------------------
#    ├── Visitor
# -------------------------------------

def walk_expression(
        expr,
        pre_visit=None,
        post_visit=None,
        parent=None,
        level=0):
    """
    Generic recursive visitor.

    pre_visit(node,parent,level)

    post_visit(node,parent,level)
    """

    if expr is None:
        return

    if not isinstance(expr, dict):
        return

    #
    # Pre-order
    #
    if pre_visit is not None:
        pre_visit(expr, parent, level)

    #
    # Visit children
    #
    for child in expression_children(expr):

        walk_expression(
            child,
            pre_visit=pre_visit,
            post_visit=post_visit,
            parent=expr,
            level=level + 1,
        )

    #
    # Post-order
    #
    if post_visit is not None:
        post_visit(expr, parent, level)

# --------------------------------------
#    ├── Search
# --------------------------------------
def find_first(expr, predicate):
    """
    Return first matching node.
    """

    result = None

    def visitor(node, parent, level):

        nonlocal result

        if result is not None:
            return

        if predicate(node):

            result = node

    walk_expression(
        expr,
        pre_visit=visitor,
    )

    return result



def find_all(expr, predicate):
    """
    Return all matching nodes.
    """

    results = []

    def visitor(node, parent, level):

        if predicate(node):

            results.append(node)

    walk_expression(
        expr,
        pre_visit=visitor,
    )

    return results

# ---------------------------------------
# Collectors
# ---------------------------------------

def collect_identifiers(expr):
    """
    Return sorted unique identifiers.
    """

    identifiers = set()

    def visitor(node, parent, level):

        if is_identifier(node):

            name = expression_name(node)

            if name:
                identifiers.add(name)

    walk_expression(
        expr,
        pre_visit=visitor,
    )

    return sorted(identifiers)


def collect_constants(expr):

    return [
        expression_value()
        for node in collect_by_type(expr, "constant")
    ]


def collect_calls(expr):

    return collect_by_type(expr, "call")

def collect_by_type(expr, expr_type):

    return find_all(
        expr,
        lambda node:
            expression_type(node) == expr_type
    )

# -----------------------------
# Semantic
# -----------------------------

# ---------------------------------------------------------
# Return True if identifier exists inside Expression IR
# ---------------------------------------------------------

def contains_identifier(expr, identifier):

    if expr is None:
        return False

    if not identifier:
        return False

    target = str(identifier).strip()

    found = False

    def visitor(node):

        nonlocal found

        if found:
            return

        if not isinstance(node, dict):
            return

        #
        # Identifier node
        #
        if node.get("type") == "identifier":

            if node.get("name") == target:

                found = True

    walk_expression(
        expr,
        pre_visit=visitor
    )

    return found

# ---------------------------------------------------------
#
# ---------------------------------------------------------

def combine_condition(
        current,
        new):

    current = (
        current or ""
    ).strip()

    new = (
        new or ""
    ).strip()

    if not current:
        return new

    if not new:
        return current

    return f"({current}) && ({new})"


# ---------------------------------------------------------
#
# ---------------------------------------------------------

def negate_condition(
        current,
        cond):

    current = (
        current or ""
    ).strip()

    cond = (
        cond or ""
    ).strip()

    if not cond:
        return current

    if not current:

        return f"!({cond})"

    return f"({current}) && !({cond})"


def contains_call(expr):

    return find_first(expr, is_call) is not None


def contains_concat(expr):

    return find_first(
        expr,
        is_concat
    ) is not None

def contains_binary(expr):

    return find_first(
        expr,
        is_binary
    ) is not None


def expression_to_text(expr):

    if expr is None:
        return ""

    if isinstance(expr, str):
        return expr

    if not isinstance(expr, dict):
        return str(expr)

    return expr.get("text", "")


def expression_value(expr):

    if not isinstance(expr, dict):
        return None

    return expr.get("value")

# ---------------------------------
#    ├── Statistics
# ---------------------------------

def expression_depth(expr):

    if expr is None:

        return 0

    children = expression_children(expr)

    if not children:

        return 1

    return 1 + max(

        expression_depth(c)

        for c in children

    )

def expression_size(expr):

    size = 0

    def visitor(node, parent, level):

        nonlocal size

        size += 1

    walk_expression(
        expr,
        pre_visit=visitor,
    )

    return size

# ------------------------
# Utilities
# ------------------------

def clone_expression(expr):

    return copy.deepcopy(expr)

def pretty_print(
        expr,
        show_text=False):
    """
    Pretty-print Expression IR.

    Returns:
        str
    """

    lines = []

    def visitor(node, parent, level):

        indent = "    " * level

        expr_type = expression_type(node)

        label = expression_label(node)

        if label:
            lines.append(f"{indent}{expr_type}: {label}")
        else:
            lines.append(f"{indent}{expr_type}")


    walk_expression(
        expr,
        pre_visit=visitor,
    )

    return "\n".join(lines)

# ---------------------------------
# predicates
# --------------------------------

def is_member_access(expr):
    return expression_type(expr) == "member_access"

def is_identifier_select(expr):
    return expression_type(expr) == "identifier_select"

def is_element_select(expr):
    return expression_type(expr) == "element_select"

def is_bit_select(expr):
    return expression_type(expr) == "bit_select"

def is_range_select(expr):
    return expression_type(expr) == "range_select"

def is_multiple_concat(expr):
    return expression_type(expr) == "multiple_concat"

def is_parenthesized(expr):
    return expression_type(expr) == "parenthesized"

