# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : __init__.py
# Description : semantic package initialization
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/__init__.py

Semantic analysis framework.

This package performs semantic analysis on the RTL Intermediate
Representation (IR) produced by the parser.

Responsibilities
----------------
* Symbol table construction
* Scope management
* Identifier resolution
* Parameter evaluation
* Signal classification
* Process analysis
* FSM analysis
* Module dependency analysis

The semantic package does NOT parse RTL.
It operates exclusively on the parser IR.
"""

from .analyzer import SemanticAnalyzer
from .context import SemanticContext
from .scope import Scope, ScopeKind
from .symbol import Symbol, SymbolKind
from .statistics import SemanticStatistics

__all__ = [
    "SemanticAnalyzer",
    "SemanticContext",
    "SemanticStatistics",
    "Scope",
    "ScopeKind",
    "Symbol",
    "SymbolKind",
]
