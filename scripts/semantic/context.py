# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : context.py
# Description : Context implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/context.py

Global semantic analysis context.

This object is shared across all semantic analysis passes and stores
symbols, scopes, semantic metadata, dependency information, and
analysis statistics.

Parser code MUST NOT modify this object.
Only semantic passes update it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from scripts.semantic.statistics import SemanticStatistics
from scripts.semantic.scope import Scope, ScopeKind


@dataclass
class SemanticContext:
    """
    Global semantic analysis context.
    """

    #
    # Current module being analyzed
    #
    current_module: str | None = None

    #
    # Global scope
    #
    global_scope: Scope = field(
        default_factory=lambda: Scope(
            name="<global>",
            kind=ScopeKind.GLOBAL,
        )
    )

    #
    # Current scope
    #
    current_scope: Any = None

    #
    # Project-wide information
    #
    modules: dict[str, Any] = field(default_factory=dict)

    #
    # Symbol tables
    #
    symbol_tables: dict[str, Any] = field(default_factory=dict)

    #
    # Scope hierarchy
    #
    scopes: dict[str, Any] = field(default_factory=dict)

    #
    # Process information
    #
    processes: dict[str, Any] = field(default_factory=dict)

    #
    # FSM information
    #
    fsms: dict[str, Any] = field(default_factory=dict)

    #
    # Module dependency graph
    #
    dependencies: dict[str, set[str]] = field(default_factory=dict)

    #
    # Parameter values
    #
    parameters: dict[str, Any] = field(default_factory=dict)

    #
    # Constant evaluation cache
    #
    constants: dict[str, Any] = field(default_factory=dict)

    #
    # Semantic statistics
    #
    statistics: SemanticStatistics = field(
        default_factory=SemanticStatistics
    )

    #
    # Generic pass cache
    #
    cache: dict[str, Any] = field(default_factory=dict)

    include_contexts: dict[str, Any] = field( default_factory=dict)

