# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : type_info.py
# Description : Semantic RTL type and width model
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TYPE_UNKNOWN = "unknown"
TYPE_BUILTIN = "builtin"
TYPE_VECTOR = "vector"
TYPE_TYPEDEF = "typedef"
TYPE_ENUM = "enum"

WIDTH_UNKNOWN = "unknown"
WIDTH_SCALAR = "scalar"
WIDTH_LITERAL = "literal"
WIDTH_EXPRESSION = "expression"


@dataclass(frozen=True)
class DimensionInfo:
    msb: Any = None
    lsb: Any = None
    kind: str = WIDTH_UNKNOWN
    expression: str | None = None


@dataclass(frozen=True)
class WidthInfo:
    width: int | None = None
    msb: Any = None
    lsb: Any = None
    kind: str = WIDTH_UNKNOWN
    expression: str | None = None


@dataclass(frozen=True)
class TypeInfo:
    kind: str = TYPE_UNKNOWN
    name: str | None = None
    base_type: str | None = None
    type_ref: str | None = None
    signed: bool | None = None
    width: WidthInfo = WidthInfo()
    packed_dimensions: tuple[DimensionInfo, ...] = ()
    unpacked_dimensions: tuple[DimensionInfo, ...] = ()
    raw: str | None = None
