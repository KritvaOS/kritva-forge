# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_symbol_table.py
# Description : Test Symbol Table implementation
#
# Component   : Kritva Forge
# Module      : tests/semantic
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Tests for semantic.symbol_table.

These tests verify that the symbol-table builder:

* creates the global scope
* creates one module scope per parser module
* collects parameters
* collects ports
* collects signals
* records symbols in the correct scope
* updates semantic statistics
"""

from scripts.semantic.context import SemanticContext
from scripts.semantic.scope import ScopeKind
from scripts.semantic.symbol import SymbolKind
from scripts.semantic.symbol_table import build_symbol_table


def make_module(
    name="test_module",
    parameters=None,
    interfaces=None,
    signals=None,
):
    """
    Build a minimal parser-style module IR.

    This intentionally mirrors the dictionary-based parser IR rather
    than introducing semantic model objects.
    """
    return {
        "name": name,
        "parameters": parameters or [],
        "interfaces": interfaces or {
            "inputs": [],
            "outputs": [],
            "inouts": [],
        },
        "signals": signals or [],
    }


def make_context():
    """Create a fresh semantic context."""
    return SemanticContext()


def test_build_symbol_table_creates_global_scope():
    project = {
        "test_module": make_module(),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    assert ctx.global_scope is not None
    assert ctx.global_scope.name == "global"
    assert ctx.global_scope.kind == ScopeKind.GLOBAL


def test_build_symbol_table_creates_module_scope():
    project = {
        "test_module": make_module(),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    assert "test_module" in ctx.scopes

    scope = ctx.scopes["test_module"]

    assert scope.name == "test_module"
    assert scope.kind == ScopeKind.MODULE
    assert scope.parent is ctx.global_scope


def test_build_symbol_table_creates_scope_for_each_module():
    project = {
        "module_a": make_module("module_a"),
        "module_b": make_module("module_b"),
        "module_c": make_module("module_c"),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    assert set(ctx.scopes) == {
        "module_a",
        "module_b",
        "module_c",
    }

    assert len(ctx.global_scope.children) == 3


def test_parameter_is_added_to_module_scope():
    project = {
        "test_module": make_module(
            parameters=[
                {
                    "name": "WIDTH",
                    "default": "32",
                }
            ]
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    symbol = scope.lookup_local("WIDTH")

    assert symbol is not None
    assert symbol.name == "WIDTH"
    assert symbol.kind == SymbolKind.PARAMETER
    assert symbol.value == "32"
    assert symbol.scope is scope


def test_input_port_is_added_to_module_scope():
    project = {
        "test_module": make_module(
            interfaces={
                "inputs": [
                    {
                        "name": "clk",
                    },
                ],
                "outputs": [],
                "inouts": [],
            }
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    symbol = scope.lookup_local("clk")

    assert symbol is not None
    assert symbol.name == "clk"
    assert symbol.kind == SymbolKind.PORT
    assert symbol.scope is scope


def test_output_port_is_added_to_module_scope():
    project = {
        "test_module": make_module(
            interfaces={
                "inputs": [],
                "outputs": [
                    {
                        "name": "data_out",
                    },
                ],
                "inouts": [],
            }
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    symbol = scope.lookup_local("data_out")

    assert symbol is not None
    assert symbol.kind == SymbolKind.PORT


def test_inout_port_is_added_to_module_scope():
    project = {
        "test_module": make_module(
            interfaces={
                "inputs": [],
                "outputs": [],
                "inouts": [
                    {
                        "name": "data",
                    },
                ],
            }
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    symbol = scope.lookup_local("data")

    assert symbol is not None
    assert symbol.kind == SymbolKind.PORT


def test_signal_is_added_to_module_scope():
    project = {
        "test_module": make_module(
            signals=[
                {
                    "name": "state",
                },
                {
                    "name": "counter",
                },
            ]
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    state = scope.lookup_local("state")
    counter = scope.lookup_local("counter")

    assert state is not None
    assert state.kind == SymbolKind.SIGNAL

    assert counter is not None
    assert counter.kind == SymbolKind.SIGNAL


def test_symbols_are_local_to_their_module():
    project = {
        "module_a": make_module(
            name="module_a",
            signals=[
                {"name": "state_a"},
            ]
        ),
        "module_b": make_module(
            name="module_b",
            signals=[
                {"name": "state_b"},
            ]
        ),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope_a = ctx.scopes["module_a"]
    scope_b = ctx.scopes["module_b"]

    assert scope_a.lookup_local("state_a") is not None
    assert scope_a.lookup_local("state_b") is None

    assert scope_b.lookup_local("state_b") is not None
    assert scope_b.lookup_local("state_a") is None


def test_symbol_lookup_returns_correct_symbol():
    project = {
        "test_module": make_module(
            parameters=[
                {
                    "name": "DEPTH",
                    "default": "16",
                }
            ],
            signals=[
                {
                    "name": "count",
                }
            ],
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    depth = scope.lookup("DEPTH")
    count = scope.lookup("count")

    assert depth is not None
    assert depth.kind == SymbolKind.PARAMETER

    assert count is not None
    assert count.kind == SymbolKind.SIGNAL


def test_unknown_symbol_returns_none():
    project = {
        "test_module": make_module(),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    scope = ctx.scopes["test_module"]

    assert scope.lookup("does_not_exist") is None


def test_statistics_count_modules_scopes_and_symbols():
    project = {
        "module_a": make_module(
            parameters=[
                {"name": "WIDTH", "default": "8"},
            ],
            interfaces={
                "inputs": [{"name": "clk"}],
                "outputs": [{"name": "data"}],
                "inouts": [],
            },
            signals=[
                {"name": "state"},
            ],
        ),
        "module_b": make_module(
            signals=[
                {"name": "counter"},
            ]
        ),
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    assert ctx.statistics.counters["modules"] == 2
    assert ctx.statistics.counters["scopes"] == 2
    assert ctx.statistics.counters["symbols"] == 5


def test_statistics_count_symbol_kinds():
    project = {
        "test_module": make_module(
            parameters=[
                {"name": "WIDTH", "default": "8"},
            ],
            interfaces={
                "inputs": [{"name": "clk"}],
                "outputs": [{"name": "data"}],
                "inouts": [],
            },
            signals=[
                {"name": "state"},
                {"name": "counter"},
            ],
        )
    }

    ctx = make_context()

    build_symbol_table(project, ctx)

    symbols = ctx.statistics.categories["symbols"]

    assert symbols["PARAMETER"] == 1
    assert symbols["PORT"] == 2
    assert symbols["SIGNAL"] == 2


def test_empty_project_creates_global_scope():
    project = {}

    ctx = make_context()

    build_symbol_table(project, ctx)

    assert ctx.global_scope is not None
    assert ctx.global_scope.kind == ScopeKind.GLOBAL
    assert ctx.global_scope.children == []
    assert ctx.scopes == {}
