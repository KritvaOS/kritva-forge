# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_resolver.py
# Description : Test Resolver implementation
#
# Component   : Kritva Forge
# Module      : tests/semantic
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Tests for semantic.resolver.

These tests verify that the semantic resolver:

* resolves signals
* resolves ports
* resolves parameters
* reports unresolved identifiers
* resolves identifiers inside binary expressions
* resolves identifiers inside unary expressions
* resolves identifiers inside conditional expressions
* resolves identifiers inside selects
* resolves identifiers inside call arguments
* does not resolve function names as RTL symbols
* resolves the base of member access but defers the member
"""

from scripts.semantic.scope import Scope, ScopeKind
from scripts.semantic.symbol import Symbol, SymbolKind
from scripts.semantic.context import SemanticContext

from scripts.semantic.resolver import (
    ResolutionReason,
    ResolutionStatus,
    SemanticResolver,
)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def make_context():
    """Create a fresh semantic context."""
    return SemanticContext()


def make_resolver(ctx=None):
    """Create a resolver and representative scope."""

    if ctx is None:
        ctx = make_context()

    return SemanticResolver(ctx), make_scope()


def make_scope():
    """Create a module scope with representative symbols."""

    scope = Scope(
        name="test_module",
        kind=ScopeKind.MODULE,
    )

    scope.add_symbol(
        Symbol(
            name="state",
            kind=SymbolKind.SIGNAL,
        )
    )

    scope.add_symbol(
        Symbol(
            name="next_state",
            kind=SymbolKind.SIGNAL,
        )
    )

    scope.add_symbol(
        Symbol(
            name="clk",
            kind=SymbolKind.PORT,
        )
    )

    scope.add_symbol(
        Symbol(
            name="WIDTH",
            kind=SymbolKind.PARAMETER,
            value="32",
        )
    )

    return scope


def make_resolver():
    """Create a resolver and representative scope."""

    return SemanticResolver(), make_scope()


# ----------------------------------------------------------------------
# Basic identifier resolution
# ----------------------------------------------------------------------


def test_resolve_signal():
    resolver, scope = make_resolver()

    result = resolver.resolve_identifier(
        "state",
        scope,
    )

    assert result.status == ResolutionStatus.RESOLVED
    assert result.resolved
    assert result.symbol is not None
    assert result.symbol.name == "state"
    assert result.symbol.kind == SymbolKind.SIGNAL


def test_resolve_port():
    resolver, scope = make_resolver()

    result = resolver.resolve_identifier(
        "clk",
        scope,
    )

    assert result.status == ResolutionStatus.RESOLVED
    assert result.resolved
    assert result.symbol is not None
    assert result.symbol.name == "clk"
    assert result.symbol.kind == SymbolKind.PORT


def test_resolve_parameter():
    resolver, scope = make_resolver()

    result = resolver.resolve_identifier(
        "WIDTH",
        scope,
    )

    assert result.status == ResolutionStatus.RESOLVED
    assert result.resolved
    assert result.symbol is not None
    assert result.symbol.name == "WIDTH"
    assert result.symbol.kind == SymbolKind.PARAMETER


def test_unresolved_identifier():
    resolver, scope = make_resolver()

    result = resolver.resolve_identifier(
        "does_not_exist",
        scope,
    )

    assert result.status == ResolutionStatus.UNRESOLVED
    assert result.unresolved
    assert result.symbol is None
    assert result.name == "does_not_exist"


# ----------------------------------------------------------------------
# Binary expression
# ----------------------------------------------------------------------


def test_resolve_binary_expression():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "binary",
        "operator": "+",
        "lhs": {
            "expr_type": "identifier",
            "name": "state",
        },
        "rhs": {
            "expr_type": "identifier",
            "name": "next_state",
        },
        "children": [
            {
                "expr_type": "identifier",
                "name": "state",
            },
            {
                "expr_type": "identifier",
                "name": "next_state",
            },
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 2

    assert results[0].name == "state"
    assert results[0].resolved
    assert results[0].symbol.kind == SymbolKind.SIGNAL

    assert results[1].name == "next_state"
    assert results[1].resolved
    assert results[1].symbol.kind == SymbolKind.SIGNAL


# ----------------------------------------------------------------------
# Unary expression
# ----------------------------------------------------------------------


def test_resolve_unary_expression():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "unary",
        "operator": "!",
        "operand": {
            "expr_type": "identifier",
            "name": "state",
        },
        "children": [
            {
                "expr_type": "identifier",
                "name": "state",
            }
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 1
    assert results[0].name == "state"
    assert results[0].resolved
    assert results[0].symbol.kind == SymbolKind.SIGNAL


# ----------------------------------------------------------------------
# Conditional expression
# ----------------------------------------------------------------------


def test_resolve_conditional_expression():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "conditional",
        "condition": {
            "expr_type": "identifier",
            "name": "state",
        },
        "true_expr": {
            "expr_type": "identifier",
            "name": "next_state",
        },
        "false_expr": {
            "expr_type": "identifier",
            "name": "clk",
        },
        "children": [
            {
                "expr_type": "identifier",
                "name": "state",
            },
            {
                "expr_type": "identifier",
                "name": "next_state",
            },
            {
                "expr_type": "identifier",
                "name": "clk",
            },
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 3

    assert [result.name for result in results] == [
        "state",
        "next_state",
        "clk",
    ]

    assert all(result.resolved for result in results)

    assert results[0].symbol.kind == SymbolKind.SIGNAL
    assert results[1].symbol.kind == SymbolKind.SIGNAL
    assert results[2].symbol.kind == SymbolKind.PORT


# ----------------------------------------------------------------------
# Select
# ----------------------------------------------------------------------


def test_resolve_identifier_select():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "identifier_select",
        "base": {
            "expr_type": "identifier",
            "name": "state",
        },
        "selectors": [
            {
                "expr_type": "identifier",
                "name": "WIDTH",
            }
        ],
        "children": [
            {
                "expr_type": "identifier",
                "name": "state",
            },
            {
                "expr_type": "identifier",
                "name": "WIDTH",
            },
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 2

    assert results[0].name == "state"
    assert results[0].symbol.kind == SymbolKind.SIGNAL

    assert results[1].name == "WIDTH"
    assert results[1].symbol.kind == SymbolKind.PARAMETER


# ----------------------------------------------------------------------
# Function call
# ----------------------------------------------------------------------


def test_resolve_call_arguments():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "call",
        "function": "$clog2",
        "arguments": [
            {
                "expr_type": "identifier",
                "name": "WIDTH",
            }
        ],
        "children": [
            {
                "expr_type": "identifier",
                "name": "WIDTH",
            }
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 1
    assert results[0].name == "WIDTH"
    assert results[0].resolved
    assert results[0].symbol.kind == SymbolKind.PARAMETER


def test_function_name_is_not_resolved():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "call",
        "function": "$clog2",
        "arguments": [],
        "children": [],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert results == []


# ----------------------------------------------------------------------
# Member access
# ----------------------------------------------------------------------


def test_member_access_resolves_base_only():
    resolver, scope = make_resolver()

    expr = {
        "expr_type": "member_access",
        "base": {
            "expr_type": "identifier",
            "name": "state",
        },
        "member": {
            "expr_type": "identifier",
            "name": "value",
        },
        "children": [
            {
                "expr_type": "identifier",
                "name": "state",
            },
            {
                "expr_type": "identifier",
                "name": "value",
            },
        ],
    }

    results = resolver.resolve_expression(
        expr,
        scope,
    )

    assert len(results) == 1
    assert results[0].name == "state"
    assert results[0].resolved
    assert results[0].symbol.kind == SymbolKind.SIGNAL


# ----------------------------------------------------------------------
# Empty / invalid expressions
# ----------------------------------------------------------------------


def test_none_expression_returns_no_results():
    resolver, scope = make_resolver()

    results = resolver.resolve_expression(
        None,
        scope,
    )

    assert results == []


def test_empty_expression_returns_no_results():
    resolver, scope = make_resolver()

    results = resolver.resolve_expression(
        {},
        scope,
    )

    assert results == []


def test_resolver_returns_resolution_reasons():
    ctx = make_context()
    resolver = SemanticResolver(ctx)

    scope = make_scope()

    resolved = resolver.resolve_identifier("state", scope)
    unresolved = resolver.resolve_identifier("missing", scope)
    
    assert resolved.resolved
    assert unresolved.unresolved
    
    assert resolved.reason == ResolutionReason.RESOLVED
    assert unresolved.reason == ResolutionReason.UNKNOWN_SYMBOL
    assert ctx.statistics.resolved_references == 1
    assert ctx.statistics.unresolved_references == 1


def test_resolver_returns_resolution_reasons():
    ctx = make_context()
    resolver = SemanticResolver(ctx)

    scope = make_scope()

    resolved = resolver.resolve_identifier("state", scope)
    unresolved = resolver.resolve_identifier("missing", scope)

    assert resolved.resolved
    assert unresolved.unresolved

    assert resolved.reason == ResolutionReason.RESOLVED
    assert unresolved.reason == ResolutionReason.UNKNOWN_SYMBOL
