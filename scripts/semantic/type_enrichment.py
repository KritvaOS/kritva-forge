# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : type_enrichment.py
# Description : Type Enrichment implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Semantic type enrichment for REV-003B.

Consumes information already present in parser IR/Symbols and attaches
TypeInfo to Symbol.metadata["type_info"].

Rules:
- no PySlang dependency
- no symbol creation
- no reference resolution
- no constant evaluation
- no parser-IR mutation
- do not overwrite existing parser-derived Symbol fields
"""
from __future__ import annotations

import re

from scripts.semantic.symbol import SymbolKind
from scripts.semantic.type_info import (
    TYPE_BUILTIN,
    TYPE_ENUM,
    TYPE_TYPEDEF,
    TYPE_UNKNOWN,
    TYPE_VECTOR,
    DimensionInfo,
    WIDTH_EXPRESSION,
    WIDTH_LITERAL,
    WIDTH_SCALAR,
    WIDTH_UNKNOWN,
    TypeInfo,
    WidthInfo,
)


_SUPPORTED_KINDS = {
    SymbolKind.PORT,
    SymbolKind.SIGNAL,
    SymbolKind.PARAMETER,
    SymbolKind.LOCALPARAM,
    SymbolKind.VARIABLE,
    SymbolKind.TYPEDEF,
    SymbolKind.ENUM,
}

_BUILTIN_TYPES = {
    "bit", "logic", "reg", "wire", "tri", "wand", "wor",
    "integer", "int", "shortint", "longint", "byte", "time",
}


def enrich_symbol_types(project: dict, ctx) -> None:
    """Enrich all supported semantic symbols in-place."""
    if project is None:
        raise ValueError("project cannot be None")
    if ctx is None:
        raise ValueError("ctx cannot be None")

    for scope in getattr(ctx, "scopes", {}).values():
        for symbol in scope.symbols.values():
            _enrich_symbol(symbol)


def _enrich_symbol(symbol) -> None:
    if symbol.kind not in _SUPPORTED_KINDS:
        return

    type_info = _extract_type_info(symbol)
    if type_info is None:
        return

    symbol.metadata["type_info"] = type_info
    _update_legacy_fields(symbol, type_info)


def _extract_type_info(symbol) -> TypeInfo | None:
    raw = _get_raw_type(symbol)

    if symbol.kind == SymbolKind.ENUM:
        enum_type = symbol.metadata.get("enum_type")
        return TypeInfo(
            kind=TYPE_ENUM,
            name=enum_type or symbol.name,
            type_ref=enum_type or None,
            raw=raw,
        )

    if symbol.kind == SymbolKind.TYPEDEF:
        type_ref = (
            symbol.metadata.get("type_ref")
            or symbol.metadata.get("typedef")
            or symbol.name
        )
        return TypeInfo(
            kind=TYPE_TYPEDEF,
            name=symbol.name,
            type_ref=type_ref,
            width=_width_from_symbol(symbol),
            raw=raw,
        )

    # Untyped parameter/localparam is valid and should still get a
    # TypeInfo object so downstream code can distinguish "known untyped"
    # from "enrichment was not attempted".
    if raw is None and symbol.width is None:
        if symbol.kind in (SymbolKind.PARAMETER, SymbolKind.LOCALPARAM):
            return TypeInfo()

        # A port/signal with no parser type text and no explicit width is a
        # scalar declaration in the supported Verilog/SystemVerilog subset.
        # Do not invent a datatype such as ``logic``: preserve the fact that
        # the source did not specify a base datatype, while recording the
        # semantically known one-bit width.
        if symbol.kind in (SymbolKind.PORT, SymbolKind.SIGNAL):
            return TypeInfo(
                kind=TYPE_BUILTIN,
                width=WidthInfo(width=1, kind=WIDTH_SCALAR),
            )

        return None

    (
        base_type,
        kind,
        type_ref,
        signed,
        width,
        packed_dimensions,
        unpacked_dimensions,
    ) = _parse_type_text(
        raw,
        symbol.width,
    )

    return TypeInfo(
        kind=kind,
        name=base_type,
        base_type=base_type,
        type_ref=type_ref,
        signed=signed,
        width=width,
        packed_dimensions=packed_dimensions,
        unpacked_dimensions=unpacked_dimensions,
        raw=raw,
    )


def _get_raw_type(symbol) -> str | None:
    for value in (
        symbol.datatype,
        symbol.metadata.get("datatype"),
        symbol.metadata.get("type"),
        symbol.metadata.get("raw_type"),
    ):
        if value is not None:
            text = str(value).strip()
            if text:
                return text

    if isinstance(symbol.node, dict):
        for key in ("datatype", "type", "data_type"):
            value = symbol.node.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text

    return None


def _parse_type_text(
    raw: str | None,
    symbol_width: int | None,
):
    if not raw:
        return (
            None,
            TYPE_UNKNOWN,
            None,
            None,
            _width_from_existing_value(symbol_width),
            (),
            (),
        )

    # Keep ``raw`` untouched for provenance, but normalize comments and
    # whitespace before semantic parsing.  Parser-generated type strings can
    # contain source comments around the actual declaration.
    text = _clean_type_text(raw)
    signed = _parse_signedness(text)
    packed_dimensions, unpacked_dimensions = _parse_dimensions(text)
    width = _parse_width_from_dimensions(packed_dimensions)

    if width.kind == WIDTH_UNKNOWN and symbol_width is not None:
        width = _width_from_existing_value(symbol_width)

    # A bare builtin scalar has a known one-bit packed width.  Do not apply
    # language-default widths to integer-like types here; that remains outside
    # the scope of this enrichment pass.
    if width.kind == WIDTH_UNKNOWN and _is_scalar_builtin(text):
        width = WidthInfo(width=1, kind=WIDTH_SCALAR)

    base = _remove_dimensions(text)
    base = re.sub(
        r"\b(?:signed|unsigned|wire|tri|wand|wor|var)\b",
        " ",
        base,
        flags=re.IGNORECASE,
    )
    base = " ".join(base.split()).strip() or None

    if base and base.lower() in _BUILTIN_TYPES:
        kind = TYPE_BUILTIN
        type_ref = None
    elif base and (packed_dimensions or width.kind != WIDTH_UNKNOWN):
        # This is a typed vector whose base type is not one of the supported
        # builtins.  No typedef resolution is attempted here.
        kind = TYPE_VECTOR
        type_ref = base
    elif base:
        # This is deliberately only classification; no typedef resolution.
        kind = TYPE_TYPEDEF
        type_ref = base
    else:
        kind = TYPE_UNKNOWN
        type_ref = None

    return (
        base,
        kind,
        type_ref,
        signed,
        width,
        packed_dimensions,
        unpacked_dimensions,
    )


def _clean_type_text(raw: str) -> str:
    """Remove source comments from a parser type string."""
    text = re.sub(r"/\*.*?\*/", " ", str(raw), flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return " ".join(text.split())


def _parse_dimensions(text: str):
    """Extract range dimensions without evaluating expressions.

    SystemVerilog packed dimensions use ``[msb:lsb]``.  A bracket without
    a colon is retained as an unpacked/index dimension because it does not
    provide a packed bit range.
    """
    packed = []
    unpacked = []

    for match in re.finditer(r"\[([^\]]+)\]", text):
        content = match.group(1).strip()
        if ":" in content:
            msb_text, lsb_text = (part.strip() for part in content.split(":", 1))
            msb = _parse_integer(msb_text)
            lsb = _parse_integer(lsb_text)
            if msb is not None and lsb is not None:
                dimension = DimensionInfo(
                    msb=msb,
                    lsb=lsb,
                    kind=WIDTH_LITERAL,
                )
            else:
                dimension = DimensionInfo(
                    msb=msb if msb is not None else msb_text,
                    lsb=lsb if lsb is not None else lsb_text,
                    kind=WIDTH_EXPRESSION,
                    expression=f"[{msb_text}:{lsb_text}]",
                )
            packed.append(dimension)
        else:
            unpacked.append(
                DimensionInfo(
                    expression=content,
                    kind=WIDTH_EXPRESSION,
                )
            )

    return tuple(packed), tuple(unpacked)


def _parse_width_from_dimensions(dimensions) -> WidthInfo:
    """Build WidthInfo from the first packed dimension."""
    if not dimensions:
        return WidthInfo()

    dimension = dimensions[0]
    if dimension.kind == WIDTH_LITERAL:
        return WidthInfo(
            width=abs(dimension.msb - dimension.lsb) + 1,
            msb=dimension.msb,
            lsb=dimension.lsb,
            kind=WIDTH_LITERAL,
        )

    return WidthInfo(
        msb=dimension.msb,
        lsb=dimension.lsb,
        kind=WIDTH_EXPRESSION,
        expression=dimension.expression,
    )


def _remove_dimensions(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", " ", text)


def _is_scalar_builtin(text: str) -> bool:
    base = _remove_dimensions(text)
    base = re.sub(
        r"\b(?:signed|unsigned|wire|tri|wand|wor|var)\b",
        " ",
        base,
        flags=re.IGNORECASE,
    )
    base = " ".join(base.split()).strip().lower()
    return base in {"bit", "logic", "reg", "wire", "tri", "wand", "wor"}


def _parse_signedness(text: str) -> bool | None:
    if re.search(r"\bsigned\b", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\bunsigned\b", text, flags=re.IGNORECASE):
        return False
    # Do not infer Verilog/SystemVerilog defaults in REV-003B.1.
    return None


def _width_from_symbol(symbol) -> WidthInfo:
    return _width_from_existing_value(symbol.width)


def _width_from_existing_value(width) -> WidthInfo:
    if width is None:
        return WidthInfo()

    try:
        value = int(width)
    except (TypeError, ValueError):
        return WidthInfo(
            kind=WIDTH_EXPRESSION,
            expression=str(width),
        )

    if value <= 0:
        return WidthInfo()

    return WidthInfo(width=value, kind=WIDTH_LITERAL)


def _parse_integer(text: str) -> int | None:
    value = text.strip().replace("_", "")
    if re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value, 10)
        except ValueError:
            pass
    # Sized Verilog literals/expressions are preserved, not evaluated.
    return None


def _update_legacy_fields(symbol, type_info: TypeInfo) -> None:
    """Populate existing Symbol fields only when they are missing."""
    if symbol.datatype is None:
        symbol.datatype = type_info.base_type

    if symbol.width is None:
        symbol.width = type_info.width.width

    if type_info.signed is not None:
        symbol.signed = type_info.signed
