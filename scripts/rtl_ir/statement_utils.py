# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statement_utils.py
# Description : Statement Utils implementation
#
# Component   : Kritva Forge
# Module      : rtl_ir
# Layer       : RTL IR
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------- 
# statement_utils.py
# 
# Query
# ------
# statement_type()
# statement_text()
# statement_children()
# 
# Predicates
# ----------
# is_assignment()
# is_if()
# is_case()
# is_case_item()
# is_block()
# is_loop()
# is_return()
# is_null()
# 
# Visitor
# --------
# walk_statement()
# 
# Search
# ------
# find_first_statement()
# find_all_statements()
# 
# Collectors
# ----------
# collect_assignments()
# collect_if_statements()
# collect_case_statements()
# collect_loops()
# 
# Pretty Printer
# --------------
# statement_label()
# pretty_print_statement()
# 
# Statistics
# ----------
# statement_depth()
# statement_size()
# statement_leaf_count()
# 
# Utilities
# ----------
# clone_statement()
# contains_statement()
# ---------------------------------------

import copy

# -------------------------------
# Query API
# -------------------------------

def statement_type(stmt):

    if not isinstance(stmt, dict):
        return None

    return stmt.get("stmt_type")


def statement_text(stmt):

    if not isinstance(stmt, dict):
        return ""

    return stmt.get("text", "")


def statement_children(stmt):

    if not isinstance(stmt, dict):
        return []

    children = stmt.get("children", [])

    return [
        child
        for child in children
        if isinstance(child, dict)
    ]


# ----------------------------------------------
# Predicate API
# ----------------------------------------------

def is_assignment(stmt):

    return statement_type(stmt) == "assignment"


def is_if(stmt):

    return statement_type(stmt) == "if"


def is_case(stmt):

    return statement_type(stmt) == "case"


def is_case_item(stmt):

    return statement_type(stmt) == "case_item"


def is_block(stmt):

    return statement_type(stmt) == "block"


def is_loop(stmt):

    return statement_type(stmt) == "loop"


def is_return(stmt):

    return statement_type(stmt) == "return"


def is_null(stmt):

    return statement_type(stmt) == "null"


# -----------------------------------------------
# Visitor API
# -----------------------------------------------
def walk_statement(
        stmt,
        pre_visit=None,
        post_visit=None,
        parent=None,
        level=0):

    if stmt is None:
        return

    if not isinstance(stmt, dict):
        return

    #
    # Pre-order
    #
    if pre_visit is not None:
        pre_visit(stmt, parent, level)

    #
    # Visit children
    #
    for child in statement_children(stmt):

        walk_statement(
            child,
            pre_visit,
            post_visit,
            stmt,
            level + 1,
        )

    #
    # Post-order
    #
    if post_visit is not None:
        post_visit(stmt, parent, level)


# ---------------------------------------
# Search API
# ---------------------------------------

def find_first_statement(stmt, predicate):

    result = None

    def visitor(node, parent, level):

        nonlocal result

        if result is not None:
            return

        if predicate(node):

            result = node

    walk_statement(
        stmt,
        pre_visit=visitor,
    )

    return result

def find_all_statements(stmt, predicate):

    results = []

    def visitor(node, parent, level):

        if predicate(node):

            results.append(node)

    walk_statement(
        stmt,
        pre_visit=visitor,
    )

    return results

# -------------------------------
# Collectors
# -------------------------------
def collect_assignments(stmt):

    return find_all_statements(
        stmt,
        is_assignment,
    )


def collect_if_statements(stmt):

    return find_all_statements(
        stmt,
        is_if,
    )

def collect_case_statements(stmt):

    return find_all_statements(
        stmt,
        is_case,
    )

def collect_loops(stmt):

    return find_all_statements(
        stmt,
        is_loop,
    )


def collect_blocks(stmt):

    return find_all_statements(
        stmt,
        is_block,
    )

# -------------------------
# Pretty Printer
# -------------------------

def statement_label(stmt):

    stmt_type = statement_type(stmt)

    if stmt_type == "assignment":

        return "=" if stmt.get("blocking") else "<="

    if stmt_type == "if":

        return "if"

    if stmt_type == "case":

        return stmt.get("case_type", "case")

    if stmt_type == "block":

        return "begin"

    if stmt_type == "loop":

        return stmt.get("loop_type", "")

    return statement_text(stmt)


#def pretty_print_statement(stmt):
#
#    lines = []
#
#    def visitor(node, parent, level):
#
#        indent = "    " * level
#
#        label = statement_label(node)
#
#        if label:
#
#            lines.append(
#                f"{indent}{statement_type(node)}: {label}"
#            )
#
#        else:
#
#            lines.append(
#                f"{indent}{statement_type(node)}"
#            )
#
#    walk_statement(
#        stmt,
#        pre_visit=visitor,
#    )
#
#    return "\n".join(lines)

# ------------------------------
# Statistics
# ------------------------------

def statement_depth(stmt):

    if stmt is None:
        return 0

    children = statement_children(stmt)

    if not children:
        return 1

    return 1 + max(
        statement_depth(child)
        for child in children
    )


def statement_size(stmt):

    count = 0

    def visitor(node, parent, level):

        nonlocal count

        count += 1

    walk_statement(
        stmt,
        pre_visit=visitor,
    )

    return count


def statement_leaf_count(stmt):

    count = 0

    def visitor(node, parent, level):

        nonlocal count

        if not statement_children(node):
            count += 1

    walk_statement(
        stmt,
        pre_visit=visitor,
    )

    return count


# ------------------------------
# Utilities
# ------------------------------

def clone_statement(stmt):

    return copy.deepcopy(stmt)


def contains_statement(stmt, predicate):

    return (
        find_first_statement(
            stmt,
            predicate,
        )
        is not None
    )
