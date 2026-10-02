# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_symbol.py
# Description : Test Symbol implementation
#
# Component   : Kritva Forge
# Module      : tests/semantic
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Unit tests for semantic.symbol
"""

from scripts.semantic.symbol import Symbol, SymbolKind


# ------------------------------------------------------------
# Constructor
# ------------------------------------------------------------

def test_create_signal_symbol():

    symbol = Symbol(
        name="count",
        kind=SymbolKind.SIGNAL,
    )

    assert symbol.name == "count"
    assert symbol.kind == SymbolKind.SIGNAL
    assert symbol.scope is None
    assert symbol.node is None
    assert symbol.datatype is None
    assert symbol.width is None
    assert symbol.signed is False
    assert symbol.direction is None
    assert symbol.value is None


# ------------------------------------------------------------
# Parameter
# ------------------------------------------------------------

def test_create_parameter_symbol():

    symbol = Symbol(
        name="WIDTH",
        kind=SymbolKind.PARAMETER,
        value=32,
    )

    assert symbol.name == "WIDTH"
    assert symbol.kind == SymbolKind.PARAMETER
    assert symbol.value == 32


# ------------------------------------------------------------
# Port
# ------------------------------------------------------------

def test_create_port_symbol():

    symbol = Symbol(
        name="clk",
        kind=SymbolKind.PORT,
        datatype="logic",
        direction="input",
    )

    assert symbol.kind == SymbolKind.PORT
    assert symbol.direction == "input"
    assert symbol.datatype == "logic"


# ------------------------------------------------------------
# Width
# ------------------------------------------------------------

def test_symbol_width():

    symbol = Symbol(
        name="addr",
        kind=SymbolKind.SIGNAL,
        width=32,
    )

    assert symbol.width == 32


# ------------------------------------------------------------
# Signed
# ------------------------------------------------------------

def test_symbol_signed():

    symbol = Symbol(
        name="data",
        kind=SymbolKind.SIGNAL,
        signed=True,
    )

    assert symbol.signed is True


# ------------------------------------------------------------
# Metadata
# ------------------------------------------------------------

def test_symbol_metadata():

    symbol = Symbol(
        name="state",
        kind=SymbolKind.SIGNAL,
    )

    symbol.metadata["clock"] = "clk"

    assert symbol.metadata["clock"] == "clk"


# ------------------------------------------------------------
# Attributes
# ------------------------------------------------------------

def test_symbol_attributes():

    symbol = Symbol(
        name="cnt",
        kind=SymbolKind.SIGNAL,
    )

    symbol.attributes["keep"] = True

    assert symbol.attributes["keep"] is True


# ------------------------------------------------------------
# Node
# ------------------------------------------------------------

def test_symbol_node():

    node = object()

    symbol = Symbol(
        name="cnt",
        kind=SymbolKind.SIGNAL,
        node=node,
    )

    assert symbol.node is node


def test_is_parameter():

    symbol = Symbol(
        name="WIDTH",
        kind=SymbolKind.PARAMETER,
    )

    assert symbol.is_parameter()
    assert not symbol.is_signal()
    assert not symbol.is_port()


def test_is_signal():

    symbol = Symbol(
        name="count",
        kind=SymbolKind.SIGNAL,
    )

    assert symbol.is_signal()
    assert not symbol.is_parameter()


def test_is_port():

    symbol = Symbol(
        name="clk",
        kind=SymbolKind.PORT,
    )

    assert symbol.is_port()
    assert not symbol.is_signal()
