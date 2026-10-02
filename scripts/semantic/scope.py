# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : scope.py
# Description : Scope implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/scope.py

Scope definitions used by semantic analysis.

A Scope owns a collection of symbols and forms part of a
hierarchical scope tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from scripts.semantic.symbol import Symbol


# ------------------------------------------------------------
# Scope Kind
# ------------------------------------------------------------

class ScopeKind(str, Enum):

    GLOBAL = "global"

    MODULE = "module"

    GENERATE = "generate"

    PROCESS = "process"

    BLOCK = "block"

    FUNCTION = "function"

    TASK = "task"


# ------------------------------------------------------------
# Scope
# ------------------------------------------------------------

@dataclass
class Scope:

    #
    # Identity
    #
    name: str

    kind: ScopeKind

    #
    # Hierarchy
    #
    parent: "Scope | None" = None

    children: list["Scope"] = field(default_factory=list)

    #
    # Symbols
    #
    symbols: dict[str, Symbol] = field(default_factory=dict)

    #
    # Original IR node
    #
    node: object | None = None

    #
    # User metadata
    #
    metadata: dict = field(default_factory=dict)

    # --------------------------------------------------
    # Child Scope
    # --------------------------------------------------

    def add_child(self, scope: "Scope"):

        scope.parent = self

        self.children.append(scope)

    # --------------------------------------------------
    # Add Symbol
    # --------------------------------------------------

    def add_symbol(self, symbol: Symbol):

        self.symbols[symbol.name] = symbol

        symbol.scope = self

    # --------------------------------------------------
    # Local Lookup
    # --------------------------------------------------

    def lookup_local(self, name: str):

        return self.symbols.get(name)

    # --------------------------------------------------
    # Recursive Lookup
    # --------------------------------------------------

    def lookup(self, name: str):

        symbol = self.lookup_local(name)

        if symbol is not None:
            return symbol

        if self.parent is not None:
            return self.parent.lookup(name)

        return None

    def __contains__(self, name):
        return name in self.symbols

