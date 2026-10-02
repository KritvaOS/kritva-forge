# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : base.py
# Description : Base implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/base.py

Common helper routines shared by all semantic analysis passes.

This module contains generic IR traversal utilities and helper
functions. It must not contain pass-specific semantic logic.
"""

from __future__ import annotations

from collections.abc import Iterator


# ------------------------------------------------------------
# Generic Dictionary Helpers
# ------------------------------------------------------------

def ensure_list(value):
    """
    Return value as a list.

    None        -> []
    list        -> list
    everything  -> [value]
    """

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


# ------------------------------------------------------------
# Generic IR Walkers
# ------------------------------------------------------------

def walk_modules(project) -> Iterator:
    """
    Iterate over all modules in the project.
    """

    for module in getattr(project, "modules", []):
        yield module


def walk_processes(module) -> Iterator:
    """
    Iterate over all processes in a module.
    """

    for process in getattr(module, "processes", []):
        yield process


def walk_statements(statement):
    """
    Depth-first traversal of statement tree.
    """

    if statement is None:
        return

    yield statement

    for child in ensure_list(getattr(statement, "children", [])):
        yield from walk_statements(child)


def walk_expressions(expr):
    """
    Depth-first traversal of expression tree.
    """

    if expr is None:
        return

    yield expr

    for child in ensure_list(getattr(expr, "children", [])):
        yield from walk_expressions(child)


def is_identifier(expr):

    return (
        isinstance(expr, dict)
        and expr.get("expr_type") == "identifier"
    )


def is_literal(expr):

    return (
        isinstance(expr, dict)
        and expr.get("expr_type") == "literal"
    )


def is_binary(expr):

    return (
        isinstance(expr, dict)
        and expr.get("expr_type") == "binary"
    )
