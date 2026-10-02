# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : symbol.py
# Description : Symbol implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/symbol.py

Symbol definitions used by semantic analysis.

A Symbol represents any named object declared within a scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ------------------------------------------------------------
# Symbol Kind
# ------------------------------------------------------------

class SymbolKind(str, Enum):

    MODULE = "module"

    PORT = "port"

    SIGNAL = "signal"

    PARAMETER = "parameter"

    LOCALPARAM = "localparam"

    VARIABLE = "variable"

    GENVAR = "genvar"

    TYPEDEF = "typedef"

    ENUM = "enum"

    INSTANCE = "instance"


# ------------------------------------------------------------
# Symbol
# ------------------------------------------------------------

@dataclass
class Symbol:
    """
    Generic semantic symbol.
    """

    #
    # Identity
    #
    name: str

    kind: SymbolKind

    #
    # Original IR node
    #
    node: Any = None

    #
    # Declaration scope
    #
    scope: Any = None

    #
    # Type information
    #
    datatype: str | None = None

    width: int | None = None

    signed: bool = False

    #
    # Port information
    #
    direction: str | None = None

    #
    # Constant value
    #
    value: Any = None

    #
    # User metadata
    #
    attributes: dict[str, Any] = field(default_factory=dict)

    #
    # Analysis metadata
    #
    metadata: dict[str, Any] = field(default_factory=dict)

    #
    #
    #
    def is_module(self) -> bool:
        return self.kind == SymbolKind.MODULE

    def is_port(self) -> bool:
        return self.kind == SymbolKind.PORT

    def is_signal(self) -> bool:
        return self.kind == SymbolKind.SIGNAL

    def is_parameter(self) -> bool:
        return self.kind == SymbolKind.PARAMETER

    def is_localparam(self) -> bool:
        return self.kind == SymbolKind.LOCALPARAM

    def is_variable(self) -> bool:
        return self.kind == SymbolKind.VARIABLE

    def is_instance(self) -> bool:
        return self.kind == SymbolKind.INSTANCE

