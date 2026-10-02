#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : diagnose_port_symbol_mismatch.py
# Description : Diagnose Port Symbol Mismatch implementation
#
# Component   : Kritva Forge
# Module      : debug
# Layer       : Development Tools
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
diagnose_port_symbol_mismatch.py

REV-003B.2 Diagnostic
---------------------

Diagnose discrepancies between:

    Parser IR PORT declarations
                vs.
    Semantic SymbolKind.PORT symbols

The diagnostic is intentionally READ-ONLY.

It does NOT:
    - modify parser IR
    - modify semantic scopes
    - modify symbols
    - modify production source files
    - run semantic type enrichment
    - run identifier resolution
    - run quality analysis

The purpose is to determine why, for example:

    Parser ports       = 150
    Semantic ports     = 143

The most important suspected cause is duplicate symbol names being
collapsed by:

    Scope.symbols: dict[str, Symbol]

via:

    self.symbols[symbol.name] = symbol

This script verifies that hypothesis rather than assuming it.

Usage
-----

    .venv/bin/python scripts/diagnose_port_symbol_mismatch.py \
        --ip aes

    .venv/bin/python scripts/diagnose_port_symbol_mismatch.py \
        --ip aes --verbose

    .venv/bin/python scripts/diagnose_port_symbol_mismatch.py \
        --rtl-root data/raw_rtl \
        --ip aes

    .venv/bin/python scripts/diagnose_port_symbol_mismatch.py \
        --rtl-root data/raw_rtl \
        --all

Exit status
-----------

    0   Diagnostic completed successfully.
    1   Invalid arguments / parser / semantic error.
    2   Requested IP was not found.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Repository imports
# ---------------------------------------------------------------------------

from scripts.parser.rtl_parser_slang import parse_ip

from scripts.semantic import SemanticAnalyzer
from scripts.semantic.symbol import SymbolKind
from scripts.semantic.symbol_table import build_symbol_table


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORT_DIRECTIONS = (
    ("inputs", "input"),
    ("outputs", "output"),
    ("inouts", "inout"),
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ParserPort:
    """One PORT declaration as represented by parser IR."""

    module: str
    name: str
    direction: str
    datatype: Any = None
    width: Any = None
    raw: Any = None
    index: int = 0


@dataclass
class SemanticPort:
    """One PORT symbol retained by the semantic symbol table."""

    module: str
    name: str
    direction: Any = None
    datatype: Any = None
    width: Any = None
    symbol: Any = None


@dataclass
class ModuleDiagnostic:
    """Diagnostic result for one module."""

    module: str

    parser_count: int = 0
    semantic_count: int = 0

    duplicate_names: int = 0
    duplicate_declarations: int = 0

    missing_from_semantic: int = 0
    semantic_not_in_parser: int = 0

    collisions_with_non_port: int = 0


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _safe_text(value: Any) -> str:
    """
    Convert a value to a compact printable representation.

    Avoids dumping large parser/AST objects.
    """
    if value is None:
        return "<none>"

    text = str(value)

    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")

    if len(text) > 160:
        text = text[:157] + "..."

    return text


def _get_port_name(port: dict) -> str:
    """
    Return the parser PORT name.

    Parser IR is expected to contain 'name'. The fallback is intentionally
    defensive so that the diagnostic itself does not crash on malformed IR.
    """
    value = port.get("name")

    if value is None:
        return ""

    return str(value)


def _get_module_name(module_name: str, module: dict) -> str:
    """
    Return the most useful module name for diagnostics.
    """
    value = module.get("name")

    if value:
        return str(value)

    return str(module_name)


# ---------------------------------------------------------------------------
# Parser PORT collection
# ---------------------------------------------------------------------------


def collect_parser_ports(project: dict) -> dict[str, list[ParserPort]]:
    """
    Collect every PORT entry directly from parser IR.

    Important:
        This intentionally does NOT deduplicate names.

    If parser IR contains:

        input a;
        output a;

    both entries remain in this collection.

    Returns
    -------
    dict[str, list[ParserPort]]
        Module name -> parser PORT declarations.
    """
    result: dict[str, list[ParserPort]] = {}

    for project_key, module in project.items():

        module_name = _get_module_name(
            project_key,
            module,
        )

        ports: list[ParserPort] = []

        interfaces = module.get(
            "interfaces",
            {},
        )

        for key, direction in PORT_DIRECTIONS:

            entries = interfaces.get(
                key,
                [],
            )

            if entries is None:
                continue

            for index, port in enumerate(entries):

                if not isinstance(port, dict):
                    continue

                ports.append(
                    ParserPort(
                        module=module_name,
                        name=_get_port_name(port),
                        direction=direction,
                        datatype=port.get("datatype"),
                        width=port.get("width"),
                        raw=port,
                        index=index,
                    )
                )

        result[module_name] = ports

    return result


# ---------------------------------------------------------------------------
# Semantic PORT collection
# ---------------------------------------------------------------------------


def collect_semantic_ports(ctx) -> dict[str, list[SemanticPort]]:
    """
    Collect PORT symbols retained by semantic scopes.

    This walks Scope.symbols exactly as the quality framework currently does.

    Returns
    -------
    dict[str, list[SemanticPort]]
        Module name -> semantic PORT symbols.
    """
    result: dict[str, list[SemanticPort]] = {}

    for scope_name, scope in getattr(
        ctx,
        "scopes",
        {},
    ).items():

        module_name = str(
            getattr(
                scope,
                "name",
                scope_name,
            )
        )

        ports: list[SemanticPort] = []

        for symbol in getattr(
            scope,
            "symbols",
            {},
        ).values():

            if getattr(
                symbol,
                "kind",
                None,
            ) != SymbolKind.PORT:
                continue

            ports.append(
                SemanticPort(
                    module=module_name,
                    name=str(
                        getattr(
                            symbol,
                            "name",
                            "",
                        )
                    ),
                    direction=getattr(
                        symbol,
                        "direction",
                        None,
                    ),
                    datatype=getattr(
                        symbol,
                        "datatype",
                        None,
                    ),
                    width=getattr(
                        symbol,
                        "width",
                        None,
                    ),
                    symbol=symbol,
                )
            )

        result[module_name] = ports

    return result


# ---------------------------------------------------------------------------
# Symbol collision analysis
# ---------------------------------------------------------------------------


def collect_symbol_collisions(ctx) -> dict[str, dict[str, list[Any]]]:
    """
    Find names that exist in semantic scopes but are not PORT symbols.

    Example:

        Parser IR:
            input foo;

        Semantic symbol table:
            foo -> SIGNAL

    This is important because Scope.add_symbol() uses the same dictionary
    for all symbol kinds. A later SIGNAL declaration can overwrite a PORT.
    """
    result: dict[str, dict[str, list[Any]]] = {}

    for scope_name, scope in getattr(
        ctx,
        "scopes",
        {},
    ).items():

        module_name = str(
            getattr(
                scope,
                "name",
                scope_name,
            )
        )

        by_name: dict[str, list[Any]] = defaultdict(list)

        for symbol in getattr(
            scope,
            "symbols",
            {},
        ).values():

            name = str(
                getattr(
                    symbol,
                    "name",
                    "",
                )
            )

            by_name[name].append(symbol)

        result[module_name] = dict(by_name)

    return result


# ---------------------------------------------------------------------------
# Duplicate parser PORT analysis
# ---------------------------------------------------------------------------


def find_duplicate_parser_ports(
    parser_ports: list[ParserPort],
) -> dict[str, list[ParserPort]]:
    """
    Find duplicate parser PORT names.

    Duplicate detection is intentionally by name only because the semantic
    Scope.symbols dictionary is keyed only by symbol.name.
    """
    grouped: dict[str, list[ParserPort]] = defaultdict(list)

    for port in parser_ports:

        grouped[
            port.name
        ].append(port)

    return {
        name: entries
        for name, entries in grouped.items()
        if name and len(entries) > 1
    }


# ---------------------------------------------------------------------------
# Module diagnosis
# ---------------------------------------------------------------------------


def diagnose_module(
    module_name: str,
    parser_ports: list[ParserPort],
    semantic_ports: list[SemanticPort],
    symbol_map: dict[str, list[Any]],
) -> ModuleDiagnostic:
    """
    Diagnose one module.
    """
    diagnostic = ModuleDiagnostic(
        module=module_name,
        parser_count=len(parser_ports),
        semantic_count=len(semantic_ports),
    )

    duplicate_ports = find_duplicate_parser_ports(
        parser_ports
    )

    diagnostic.duplicate_names = len(
        duplicate_ports
    )

    diagnostic.duplicate_declarations = sum(
        len(entries) - 1
        for entries in duplicate_ports.values()
    )

    parser_names = [
        port.name
        for port in parser_ports
        if port.name
    ]

    semantic_names = [
        port.name
        for port in semantic_ports
        if port.name
    ]

    parser_name_set = set(
        parser_names
    )

    semantic_name_set = set(
        semantic_names
    )

    diagnostic.missing_from_semantic = len(
        parser_name_set - semantic_name_set
    )

    diagnostic.semantic_not_in_parser = len(
        semantic_name_set - parser_name_set
    )

    # Detect parser PORT names that ended up as another semantic symbol kind.
    for name in parser_name_set - semantic_name_set:

        for symbol in symbol_map.get(
            name,
            [],
        ):

            kind = getattr(
                symbol,
                "kind",
                None,
            )

            if kind != SymbolKind.PORT:
                diagnostic.collisions_with_non_port += 1

    return diagnostic


# ---------------------------------------------------------------------------
# Detailed module report
# ---------------------------------------------------------------------------


def print_module_report(
    module_name: str,
    parser_ports: list[ParserPort],
    semantic_ports: list[SemanticPort],
    symbol_map: dict[str, list[Any]],
    verbose: bool = False,
) -> None:
    """
    Print detailed diagnostics for one module.
    """
    duplicate_ports = find_duplicate_parser_ports(
        parser_ports
    )

    parser_names = {
        port.name
        for port in parser_ports
        if port.name
    }

    semantic_names = {
        port.name
        for port in semantic_ports
        if port.name
    }

    missing_names = sorted(
        parser_names - semantic_names
    )

    extra_names = sorted(
        semantic_names - parser_names
    )

    has_problem = (
        len(parser_ports)
        != len(semantic_ports)
        or duplicate_ports
        or missing_names
        or extra_names
    )

    if not has_problem and not verbose:
        return

    print()
    print("-" * 72)
    print(f"MODULE: {module_name}")
    print("-" * 72)

    print(
        f"Parser PORTs                    : "
        f"{len(parser_ports)}"
    )

    print(
        f"Semantic PORT symbols           : "
        f"{len(semantic_ports)}"
    )

    print(
        f"Difference                      : "
        f"{len(parser_ports) - len(semantic_ports)}"
    )

    print(
        f"Duplicate parser names          : "
        f"{len(duplicate_ports)}"
    )

    print(
        f"Duplicate declarations          : "
        f"{sum(len(v) - 1 for v in duplicate_ports.values())}"
    )

    print(
        f"Parser names missing semantic   : "
        f"{len(missing_names)}"
    )

    print(
        f"Semantic names not in parser    : "
        f"{len(extra_names)}"
    )

    # ------------------------------------------------------------------
    # Duplicate PORT names
    # ------------------------------------------------------------------

    if duplicate_ports:

        print()
        print("DUPLICATE PARSER PORT NAMES")
        print("---------------------------")

        for name in sorted(
            duplicate_ports
        ):

            entries = duplicate_ports[name]

            print()
            print(
                f"  {name!r} "
                f"({len(entries)} parser declarations)"
            )

            for entry in entries:

                print(
                    f"    direction={entry.direction!r} "
                    f"datatype={_safe_text(entry.datatype)!r} "
                    f"width={_safe_text(entry.width)!r}"
                )

            matching_semantic = [
                port
                for port in semantic_ports
                if port.name == name
            ]

            if matching_semantic:

                for port in matching_semantic:

                    print(
                        "    semantic: "
                        f"direction={port.direction!r} "
                        f"datatype={_safe_text(port.datatype)!r} "
                        f"width={_safe_text(port.width)!r}"
                    )

            else:

                print(
                    "    semantic: <NOT PRESENT>"
                )

    # ------------------------------------------------------------------
    # Missing semantic names
    # ------------------------------------------------------------------

    if missing_names:

        print()
        print("PARSER PORTS MISSING FROM SEMANTIC TABLE")
        print("----------------------------------------")

        for name in missing_names:

            print(
                f"  {name!r}"
            )

            symbols = symbol_map.get(
                name,
                [],
            )

            if not symbols:

                print(
                    "    semantic symbol: <NONE>"
                )
                continue

            for symbol in symbols:

                kind = getattr(
                    symbol,
                    "kind",
                    None,
                )

                direction = getattr(
                    symbol,
                    "direction",
                    None,
                )

                datatype = getattr(
                    symbol,
                    "datatype",
                    None,
                )

                width = getattr(
                    symbol,
                    "width",
                    None,
                )

                print(
                    "    semantic symbol: "
                    f"kind={kind!r} "
                    f"direction={direction!r} "
                    f"datatype={_safe_text(datatype)!r} "
                    f"width={_safe_text(width)!r}"
                )

    # ------------------------------------------------------------------
    # Semantic-only names
    # ------------------------------------------------------------------

    if extra_names:

        print()
        print("SEMANTIC PORTS NOT PRESENT IN PARSER")
        print("-----------------------------------")

        for name in extra_names:

            print(
                f"  {name!r}"
            )

    # ------------------------------------------------------------------
    # Full port listing
    # ------------------------------------------------------------------

    if verbose:

        print()
        print("PARSER PORT LIST")
        print("----------------")

        for index, port in enumerate(
            parser_ports,
            start=1,
        ):

            print(
                f"  [{index:3d}] "
                f"{port.name!r:<30} "
                f"direction={port.direction!r:<7} "
                f"datatype={_safe_text(port.datatype)!r:<30} "
                f"width={_safe_text(port.width)!r}"
            )

        print()
        print("SEMANTIC PORT LIST")
        print("------------------")

        for index, port in enumerate(
            semantic_ports,
            start=1,
        ):

            print(
                f"  [{index:3d}] "
                f"{port.name!r:<30} "
                f"direction={port.direction!r:<7} "
                f"datatype={_safe_text(port.datatype)!r:<30} "
                f"width={_safe_text(port.width)!r}"
            )


# ---------------------------------------------------------------------------
# Project diagnosis
# ---------------------------------------------------------------------------


def diagnose_project(
    project: dict,
    ctx,
    verbose: bool = False,
) -> int:
    """
    Run the complete PORT mismatch diagnostic.

    Returns
    -------
    int
        Number of parser-vs-semantic PORT count differences.
    """

    parser_ports_by_module = collect_parser_ports(
        project
    )

    semantic_ports_by_module = collect_semantic_ports(
        ctx
    )

    symbol_maps = collect_symbol_collisions(
        ctx
    )

    module_names = sorted(
        set(parser_ports_by_module)
        | set(semantic_ports_by_module)
    )

    diagnostics: list[ModuleDiagnostic] = []

    print()
    print("=" * 72)
    print("REV-003B.2 PORT SYMBOL DIAGNOSTIC")
    print("=" * 72)

    print()
    print(
        "Purpose: compare parser PORT declarations against "
        "semantic PORT symbols."
    )

    print(
        "Mode   : READ-ONLY"
    )

    for module_name in module_names:

        parser_ports = parser_ports_by_module.get(
            module_name,
            [],
        )

        semantic_ports = semantic_ports_by_module.get(
            module_name,
            [],
        )

        symbol_map = symbol_maps.get(
            module_name,
            {},
        )

        diagnostic = diagnose_module(
            module_name,
            parser_ports,
            semantic_ports,
            symbol_map,
        )

        diagnostics.append(
            diagnostic
        )

        print_module_report(
            module_name,
            parser_ports,
            semantic_ports,
            symbol_map,
            verbose=verbose,
        )

    # ------------------------------------------------------------------
    # Project totals
    # ------------------------------------------------------------------

    parser_total = sum(
        diagnostic.parser_count
        for diagnostic in diagnostics
    )

    semantic_total = sum(
        diagnostic.semantic_count
        for diagnostic in diagnostics
    )

    duplicate_module_count = sum(
        1
        for diagnostic in diagnostics
        if diagnostic.duplicate_names
    )

    duplicate_name_count = sum(
        diagnostic.duplicate_names
        for diagnostic in diagnostics
    )

    duplicate_declaration_count = sum(
        diagnostic.duplicate_declarations
        for diagnostic in diagnostics
    )

    missing_total = sum(
        diagnostic.missing_from_semantic
        for diagnostic in diagnostics
    )

    extra_total = sum(
        diagnostic.semantic_not_in_parser
        for diagnostic in diagnostics
    )

    collision_total = sum(
        diagnostic.collisions_with_non_port
        for diagnostic in diagnostics
    )

    print()
    print("=" * 72)
    print("PROJECT SUMMARY")
    print("=" * 72)

    print()
    print(
        f"Modules checked                 : "
        f"{len(diagnostics)}"
    )

    print(
        f"Parser PORT declarations        : "
        f"{parser_total}"
    )

    print(
        f"Semantic PORT symbols           : "
        f"{semantic_total}"
    )

    print(
        f"Difference                      : "
        f"{parser_total - semantic_total}"
    )

    print(
        f"Modules with duplicate names    : "
        f"{duplicate_module_count}"
    )

    print(
        f"Duplicate parser names           : "
        f"{duplicate_name_count}"
    )

    print(
        f"Duplicate declarations           : "
        f"{duplicate_declaration_count}"
    )

    print(
        f"Parser names missing semantic    : "
        f"{missing_total}"
    )

    print(
        f"Semantic names not in parser     : "
        f"{extra_total}"
    )

    print(
        f"Non-PORT symbol collisions       : "
        f"{collision_total}"
    )

    # ------------------------------------------------------------------
    # Interpretation
    # ------------------------------------------------------------------

    print()
    print("=" * 72)
    print("DIAGNOSTIC INTERPRETATION")
    print("=" * 72)

    if parser_total == semantic_total:

        print()
        print(
            "RESULT: Parser and semantic PORT counts match."
        )

        if duplicate_name_count:

            print(
                "NOTE  : Duplicate parser PORT names were found, "
                "but they did not reduce the final semantic PORT count."
            )

    else:

        print()
        print(
            "RESULT: Parser and semantic PORT counts differ."
        )

        if duplicate_declaration_count:

            print(
                "EVIDENCE: Duplicate parser PORT declarations "
                "may explain part or all of the difference."
            )

        if collision_total:

            print(
                "EVIDENCE: Some parser PORT names collide with "
                "non-PORT semantic symbols."
            )

        if missing_total and not duplicate_declaration_count:

            print(
                "EVIDENCE: Parser PORT names are missing from the "
                "semantic symbol table without a duplicate-name explanation."
            )

        if not duplicate_declaration_count and not collision_total:

            print(
                "NEXT STEP: Inspect the parser-to-symbol-table "
                "collection path; duplicate-name overwrite is not "
                "sufficient to explain the discrepancy."
            )

    print()
    print("=" * 72)

    return parser_total - semantic_total


# ---------------------------------------------------------------------------
# Semantic context construction
# ---------------------------------------------------------------------------


def build_semantic_context(project):
    """
    Build only the semantic symbol table required by this diagnostic.

    Deliberately does NOT run:
        - identifier resolution
        - type enrichment
        - quality analysis

    This isolates the symbol-table construction step.
    """
    analyzer = SemanticAnalyzer()

    analyzer.register(
        build_symbol_table
    )

    ctx = analyzer.analyze(
        project
    )

    return ctx


# ---------------------------------------------------------------------------
# IP discovery
# ---------------------------------------------------------------------------


def discover_ip_dirs(rtl_root: str) -> dict[str, str]:
    """
    Discover IP directories below rtl_root.

    The current pipeline treats each child directory as an IP.
    """
    if not os.path.isdir(
        rtl_root
    ):
        raise FileNotFoundError(
            f"RTL root does not exist: {rtl_root}"
        )

    result: dict[str, str] = {}

    for name in sorted(
        os.listdir(rtl_root)
    ):

        path = os.path.join(
            rtl_root,
            name,
        )

        if not os.path.isdir(
            path
        ):
            continue

        result[name] = path

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose parser PORT vs semantic PORT symbol "
            "count mismatches."
        )
    )

    parser.add_argument(
        "--rtl-root",
        default="../kritva-forge-data/raw/rtl",
        help=(
            "RTL root containing IP directories "
            "(default: ../kritva-forge-data/raw/rtl)"
        ),
    )

    group = parser.add_mutually_exclusive_group(
        required=True
    )

    group.add_argument(
        "--ip",
        help=(
            "Run diagnostic for one IP, for example: aes"
        ),
    )

    group.add_argument(
        "--all",
        action="store_true",
        help=(
            "Run diagnostic for every IP under --rtl-root"
        ),
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Print complete parser and semantic PORT lists "
            "for affected modules."
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_ip(
    ip_name: str,
    ip_dir: str,
    verbose: bool,
) -> int:
    """
    Parse one IP, build semantic symbol table, and diagnose.
    """

    print()
    print("#" * 72)
    print(f"# IP: {ip_name}")
    print(f"# RTL: {ip_dir}")
    print("#" * 72)

    try:

        # --------------------------------------------------------------
        # Parser
        # --------------------------------------------------------------

        modules, top = parse_ip(
            ip_dir
        )

        if modules is None:
            raise RuntimeError(
                f"Parser returned None for IP: {ip_name}"
            )

        if not modules:
            raise RuntimeError(
                f"No modules found for IP: {ip_name}"
            )

        print()
        print(
            f"[INFO] Parsed modules: {len(modules)}"
        )

        print(
            f"[INFO] Top module: {top}"
        )

        # --------------------------------------------------------------
        # Semantic symbol table only
        # --------------------------------------------------------------

        ctx = build_semantic_context(
            modules
        )

        print(
            f"[INFO] Semantic scopes: "
            f"{len(getattr(ctx, 'scopes', {}))}"
        )

        # --------------------------------------------------------------
        # Diagnostic
        # --------------------------------------------------------------

        return diagnose_project(
            modules,
            ctx,
            verbose=verbose,
        )

    except Exception as exc:

        print()
        print(
            "[ERROR] Diagnostic failed:"
        )

        print(
            f"        {type(exc).__name__}: {exc}"
        )

        return 1


def main() -> int:
    """
    CLI entry point.
    """
    args = parse_args()

    try:

        ip_dirs = discover_ip_dirs(
            args.rtl_root
        )

    except Exception as exc:

        print(
            f"[ERROR] {exc}",
            file=sys.stderr,
        )

        return 1

    # ------------------------------------------------------------------
    # Single IP
    # ------------------------------------------------------------------

    if args.ip:

        ip_name = args.ip

        if ip_name not in ip_dirs:

            print(
                f"[ERROR] IP not found: {ip_name}",
                file=sys.stderr,
            )

            print(
                "[INFO] Available IPs:",
                file=sys.stderr,
            )

            for name in sorted(
                ip_dirs
            ):

                print(
                    f"        {name}",
                    file=sys.stderr,
                )

            return 2

        result = run_ip(
            ip_name,
            ip_dirs[ip_name],
            args.verbose,
        )

        # A mismatch is a diagnostic finding, not a script failure.
        if result == 0:
            return 0

        if result == 1:
            return 1

        return 0

    # ------------------------------------------------------------------
    # All IPs
    # ------------------------------------------------------------------

    overall_difference = 0
    failed = 0

    for ip_name in sorted(
        ip_dirs
    ):

        result = run_ip(
            ip_name,
            ip_dirs[ip_name],
            args.verbose,
        )

        if result == 1:
            failed += 1
            continue

        overall_difference += result

    print()
    print("=" * 72)
    print("ALL-IP DIAGNOSTIC SUMMARY")
    print("=" * 72)

    print(
        f"IP directories processed        : "
        f"{len(ip_dirs)}"
    )

    print(
        f"IPs with diagnostic errors      : "
        f"{failed}"
    )

    print(
        f"Aggregate PORT difference        : "
        f"{overall_difference}"
    )

    print("=" * 72)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
