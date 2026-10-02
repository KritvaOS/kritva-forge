# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_include_context.py
# Description : Test Include Context implementation
#
# Component   : Kritva Forge
# Module      : tests/parser
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Unit tests for parser.include_context.

These tests intentionally use temporary SystemVerilog files rather than
repository-specific RTL. The objective is to validate the generic include
context behavior independently of a particular IP.
"""

from pathlib import Path

import pytest

from scripts.parser.include_context import (
    IncludeContext,
    IncludeFile,
    IncludeSymbol,
    build_include_context,
    discover_includes,
    extract_header_enums,
    extract_header_parameters,
    resolve_include,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_file(path: Path, content: str) -> Path:
    """Create a text file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Include discovery
# ---------------------------------------------------------------------------


def test_discover_includes(tmp_path):
    """Discover direct include directives in source order."""

    source = write_file(
        tmp_path / "top.sv",
        """
module top;

`include "defs.svh"
`include "types.svh"

endmodule
""",
    )

    assert discover_includes(source) == [
        "defs.svh",
        "types.svh",
    ]


def test_discover_includes_angle_brackets(tmp_path):
    """Support both quoted and angle-bracket include syntax."""

    source = write_file(
        tmp_path / "top.sv",
        """
`include "local.svh"
`include <global.svh>

module top;
endmodule
""",
    )

    assert discover_includes(source) == [
        "local.svh",
        "global.svh",
    ]


def test_discover_includes_ignores_non_include_lines(tmp_path):
    """Only actual include directives should be returned."""

    source = write_file(
        tmp_path / "top.sv",
        """
// `include "commented.svh"

module top;

// Not a preprocessor include:
// include "not_an_include.svh"

endmodule
""",
    )

    assert discover_includes(source) == []


# ---------------------------------------------------------------------------
# Include resolution
# ---------------------------------------------------------------------------


def test_resolve_include_relative_to_source(tmp_path):
    """The including source directory is searched first."""

    source_dir = tmp_path / "rtl"
    source = write_file(
        source_dir / "top.sv",
        """
module top;
endmodule
""",
    )

    header = write_file(
        source_dir / "defs.svh",
        """
parameter WIDTH = 32;
""",
    )

    resolved = resolve_include(
        "defs.svh",
        source,
    )

    assert resolved == header.resolve()


def test_resolve_include_from_include_directory(tmp_path):
    """Explicit include directories are searched."""

    rtl_dir = tmp_path / "rtl"
    include_dir = tmp_path / "includes"

    source = write_file(
        rtl_dir / "top.sv",
        """
`include "defs.svh"

module top;
endmodule
""",
    )

    header = write_file(
        include_dir / "defs.svh",
        """
parameter WIDTH = 32;
""",
    )

    resolved = resolve_include(
        "defs.svh",
        source,
        include_dirs=[include_dir],
    )

    assert resolved == header.resolve()


def test_resolve_include_returns_none_when_missing(tmp_path):
    """An unresolved include should return None."""

    source = write_file(
        tmp_path / "top.sv",
        """
module top;
endmodule
""",
    )

    assert resolve_include(
        "missing.svh",
        source,
    ) is None


# ---------------------------------------------------------------------------
# Header parameter extraction
# ---------------------------------------------------------------------------


def test_extract_parameter(tmp_path):
    """Extract a simple parameter declaration."""

    header = write_file(
        tmp_path / "defs.svh",
        """
parameter WIDTH = 32;
""",
    )

    symbols = extract_header_parameters(header)

    assert len(symbols) == 1

    symbol = symbols[0]

    assert isinstance(symbol, IncludeSymbol)
    assert symbol.name == "WIDTH"
    assert symbol.kind == "parameter"
    assert symbol.default == "32"
    assert symbol.source_file == str(header.resolve())


def test_extract_typed_parameter(tmp_path):
    """Extract typed parameters without evaluating their expressions."""

    header = write_file(
        tmp_path / "defs.svh",
        """
parameter bit [31:0] ADDR_MASK = 'hFC000000;
""",
    )

    symbols = extract_header_parameters(header)

    assert len(symbols) == 1

    symbol = symbols[0]

    assert symbol.name == "ADDR_MASK"
    assert symbol.kind == "parameter"
    assert symbol.default == "'hFC000000"


def test_extract_parameter_expression(tmp_path):
    """
    Preserve a parameter expression as source-level text.

    Semantic evaluation is deliberately outside include_context.
    """

    header = write_file(
        tmp_path / "defs.svh",
        """
parameter WIDTH = 32;
parameter HALF  = WIDTH / 2;
""",
    )

    symbols = extract_header_parameters(header)

    assert [symbol.name for symbol in symbols] == [
        "WIDTH",
        "HALF",
    ]

    assert symbols[0].default == "32"
    assert symbols[1].default == "WIDTH / 2"


def test_extract_multiple_parameter_declarations(tmp_path):
    """Extract multiple declarations from one header."""

    header = write_file(
        tmp_path / "defs.svh",
        """
parameter A = 1;
parameter B = 2;
parameter C = 3;
""",
    )

    symbols = extract_header_parameters(header)

    assert len(symbols) == 3

    assert [symbol.name for symbol in symbols] == [
        "A",
        "B",
        "C",
    ]

    assert [symbol.default for symbol in symbols] == [
        "1",
        "2",
        "3",
    ]


def test_extract_typedef_enum(tmp_path):
    """Extract enum members from a typedef enum declaration."""

    header = write_file(
        tmp_path / "types.svh",
        """
typedef enum logic [2:0] {
    STATE_IDLE,
    STATE_RUN,
    STATE_DONE
} state_t;
""",
    )

    symbols = extract_header_enums(header)

    assert [symbol.name for symbol in symbols] == [
        "STATE_IDLE",
        "STATE_RUN",
        "STATE_DONE",
    ]

    assert all(
        symbol.kind == "enum"
        for symbol in symbols
    )

    assert all(
        symbol.source_file == str(header.resolve())
        for symbol in symbols
    )

# ---------------------------------------------------------------------------
# Recursive include context
# ---------------------------------------------------------------------------


def test_build_include_context_direct_include(tmp_path):
    """Build context for one directly included header."""

    source = write_file(
        tmp_path / "top.sv",
        """
`include "defs.svh"

module top;
endmodule
""",
    )

    write_file(
        tmp_path / "defs.svh",
        """
parameter WIDTH = 32;
""",
    )

    context = build_include_context(source)

    assert isinstance(context, IncludeContext)

    assert context.source_file == str(source.resolve())

    assert len(context.include_files) == 1

    assert context.include_files[0].path == str(
        (tmp_path / "defs.svh").resolve()
    )

    assert context.include_files[0].parent == str(
        source.resolve()
    )

    assert context.include_files[0].include_name == "defs.svh"

    assert [symbol.name for symbol in context.symbols] == [
        "WIDTH"
    ]


def test_build_include_context_nested_include(tmp_path):
    """
    Recursively collect symbols from nested headers.

        top.sv
          |
          +-- a.svh
                |
                +-- b.svh
                      |
                      +-- C
    """

    source = write_file(
        tmp_path / "top.sv",
        """
`include "a.svh"

module top;
endmodule
""",
    )

    a = write_file(
        tmp_path / "a.svh",
        """
`include "b.svh"

parameter A = 1;
""",
    )

    b = write_file(
        tmp_path / "b.svh",
        """
parameter B = 2;
""",
    )

    context = build_include_context(source)

    assert len(context.include_files) == 2

    assert [Path(item.path).name for item in context.include_files] == [
        "a.svh",
        "b.svh",
    ]

    assert [symbol.name for symbol in context.symbols] == [
        "A",
        "B",
    ]

    assert context.include_files[0].parent == str(
        source.resolve()
    )

    assert context.include_files[1].parent == str(
        a.resolve()
    )


def test_build_include_context_include_cycle(tmp_path):
    """
    Include cycles must terminate.

        top.sv
          |
          +-- a.svh
                |
                +-- b.svh
                      |
                      +-- a.svh
    """

    source = write_file(
        tmp_path / "top.sv",
        """
`include "a.svh"

module top;
endmodule
""",
    )

    a = write_file(
        tmp_path / "a.svh",
        """
`include "b.svh"

parameter A = 1;
""",
    )

    b = write_file(
        tmp_path / "b.svh",
        """
`include "a.svh"

parameter B = 2;
""",
    )

    context = build_include_context(source)

    # a.svh and b.svh should each be processed once.
    assert len(context.include_files) == 2

    assert sorted(
        Path(item.path).name
        for item in context.include_files
    ) == [
        "a.svh",
        "b.svh",
    ]

    assert [symbol.name for symbol in context.symbols] == [
        "A",
        "B",
    ]


# ---------------------------------------------------------------------------
# Missing include
# ---------------------------------------------------------------------------


def test_build_include_context_missing_include(tmp_path):
    """Missing headers should be recorded rather than raising."""

    source = write_file(
        tmp_path / "top.sv",
        """
`include "missing.svh"

module top;
endmodule
""",
    )

    context = build_include_context(source)

    assert context.include_files == []

    assert context.symbols == []

    assert context.unresolved_includes == [
        "missing.svh"
    ]


# ---------------------------------------------------------------------------
# Symbol provenance
# ---------------------------------------------------------------------------


def test_symbol_provenance(tmp_path):
    """Every extracted symbol retains its defining header."""

    source = write_file(
        tmp_path / "top.sv",
        """
`include "defs.svh"

module top;
endmodule
""",
    )

    header = write_file(
        tmp_path / "defs.svh",
        """
parameter CSR_WIDTH = 12;
""",
    )

    context = build_include_context(source)

    assert len(context.symbols) == 1

    symbol = context.symbols[0]

    assert symbol.name == "CSR_WIDTH"
    assert symbol.source_file == str(header.resolve())


# ---------------------------------------------------------------------------
# Convenience APIs
# ---------------------------------------------------------------------------


def test_symbol_map(tmp_path):
    """IncludeContext.symbol_map should provide name-based access."""

    source = write_file(
        tmp_path / "top.sv",
        """
`include "defs.svh"

module top;
endmodule
""",
    )

    write_file(
        tmp_path / "defs.svh",
        """
parameter WIDTH = 32;
parameter DEPTH = 64;
""",
    )

    context = build_include_context(source)

    symbol_map = context.symbol_map

    assert set(symbol_map) == {
        "WIDTH",
        "DEPTH",
    }

    assert symbol_map["WIDTH"].default == "32"
    assert symbol_map["DEPTH"].default == "64"


def test_extract_localparam(tmp_path):
    header = write_file(
        tmp_path / "defs.svh",
        """
localparam FOO = 10;
""",
    )

    symbols = extract_header_parameters(header)

    assert len(symbols) == 1
    assert symbols[0].name == "FOO"
    assert symbols[0].kind == "localparam"
    assert symbols[0].default == "10"
