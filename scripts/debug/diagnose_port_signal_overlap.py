#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : diagnose_port_signal_overlap.py
# Description : Diagnose Port Signal Overlap implementation
#
# Component   : Kritva Forge
# Module      : debug
# Layer       : Development Tools
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Diagnose parser PORT/SIGNAL overlaps and semantic symbol collisions.

Purpose
-------
Investigate cases where a parser IR port and signal share the same name,
especially non-ANSI output/reg declarations such as:

    output data_out;
    reg    data_out;

The diagnostic compares:

    Parser IR
        interfaces.*
        signals
            |
            v
    Semantic symbol table
            |
            v
    Final Scope.symbols

This script is READ-ONLY with respect to the RTL parser and semantic
implementation.

It does not:
    - modify parser IR
    - modify SymbolTable implementation
    - run type enrichment
    - run identifier resolution
    - run quality analysis

Usage
-----

    python3 scripts/diagnose_port_signal_overlap.py --ip aes

Verbose:

    python3 scripts/diagnose_port_signal_overlap.py --ip aes --verbose

All IPs:

    python3 scripts/diagnose_port_signal_overlap.py --all

Optional RTL root:

    python3 scripts/diagnose_port_signal_overlap.py \
        --ip aes \
        --rtl-root data/raw_rtl

"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Repository imports
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rtl_parser_slang import parse_ip
from scripts.semantic.analyzer import SemanticAnalyzer
from scripts.semantic.symbol import SymbolKind
from scripts.semantic.symbol_table import build_symbol_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a dictionary key safely."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _port_entries(module: dict) -> list[tuple[str, str, dict]]:
    """
    Return parser port entries as:

        (direction, name, port_dict)
    """
    interfaces = module.get("interfaces", {}) or {}

    result = []

    for direction_key, direction in (
        ("inputs", "input"),
        ("outputs", "output"),
        ("inouts", "inout"),
    ):
        for port in interfaces.get(direction_key, []) or []:
            if not isinstance(port, dict):
                continue

            name = port.get("name")

            if name:
                result.append((direction, name, port))

    return result


def _signal_entries(module: dict) -> list[tuple[str, dict]]:
    """
    Return parser signal entries as:

        (name, signal_dict)
    """
    signals = module.get("signals", []) or []

    result = []

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        name = signal.get("name")

        if name:
            result.append((name, signal))

    return result


def _format_value(value: Any) -> str:
    if value is None:
        return "<none>"

    text = str(value)

    if not text:
        return "<empty>"

    return text


def _port_description(port: dict) -> str:
    datatype = port.get("datatype")
    width = port.get("width")

    return (
        f"datatype={_format_value(datatype)}, "
        f"width={_format_value(width)}"
    )


def _signal_description(signal: dict) -> str:
    datatype = signal.get("type")
    width = signal.get("width")

    return (
        f"type={_format_value(datatype)}, "
        f"width={_format_value(width)}"
    )


def _symbol_description(symbol: Any) -> str:
    if symbol is None:
        return "<none>"

    kind = getattr(symbol, "kind", None)

    if hasattr(kind, "value"):
        kind = kind.value

    datatype = getattr(symbol, "datatype", None)
    width = getattr(symbol, "width", None)
    direction = getattr(symbol, "direction", None)

    return (
        f"kind={_format_value(kind)}, "
        f"datatype={_format_value(datatype)}, "
        f"width={_format_value(width)}, "
        f"direction={_format_value(direction)}"
    )


def _module_name(module: dict) -> str:
    return str(
        module.get("name")
        or module.get("module_name")
        or "<unknown-module>"
    )


def _collect_parser_overlap(module: dict) -> dict[str, dict]:
    """
    Find names appearing both as parser ports and parser signals.

    Returns:

        {
            "data_out": {
                "ports": [...],
                "signals": [...]
            }
        }
    """
    ports_by_name: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    signals_by_name: dict[str, list[dict]] = defaultdict(list)

    for direction, name, port in _port_entries(module):
        ports_by_name[name].append((direction, port))

    for name, signal in _signal_entries(module):
        signals_by_name[name].append(signal)

    overlaps = {}

    for name in sorted(set(ports_by_name) & set(signals_by_name)):
        overlaps[name] = {
            "ports": ports_by_name[name],
            "signals": signals_by_name[name],
        }

    return overlaps


def _find_module_scope(ctx: Any, module_name: str) -> Any:
    """
    Locate the semantic scope using the module name.

    Semantic Context stores module scopes keyed by module name.
    """
    scopes = getattr(ctx, "scopes", {}) or {}
    return scopes.get(module_name)


def _get_symbol(scope: Any, name: str) -> Any:
    if scope is None:
        return None

    symbols = getattr(scope, "symbols", {}) or {}

    return symbols.get(name)


def _symbol_kind(symbol: Any) -> Any:
    if symbol is None:
        return None

    kind = getattr(symbol, "kind", None)

    if hasattr(kind, "value"):
        return kind.value

    return kind


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

def diagnose_project(project: dict, ctx: Any, verbose: bool = False) -> dict:
    """
    Diagnose all parser port/signal overlaps in a parsed project.
    """

    # parse_ip() returns the module database directly:
    #
    #     modules: dict[str, dict]
    #
    # There is no outer {"modules": ...} wrapper.
    modules = project or {}

    total_ports = 0
    total_signals = 0
    total_overlaps = 0

    port_signal_overlaps = []

    for module_name, module in modules.items():
        # Use the module-database key because SemanticContext.scopes
        # is also keyed by module name.
        module_name = str(module_name)

        ports = _port_entries(module)
        signals = _signal_entries(module)

        total_ports += len(ports)
        total_signals += len(signals)

        overlaps = _collect_parser_overlap(module)

        if not overlaps:
            continue

        scope = _find_module_scope(ctx, module_name)

        for name, overlap in overlaps.items():
            total_overlaps += 1

            semantic_symbol = _get_symbol(scope, name)
            semantic_kind = _symbol_kind(semantic_symbol)

            record = {
                "module": module_name,
                "name": name,
                "ports": overlap["ports"],
                "signals": overlap["signals"],
                "semantic_symbol": semantic_symbol,
                "semantic_kind": semantic_kind,
            }

            port_signal_overlaps.append(record)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    print()
    print("=" * 78)
    print("PORT / SIGNAL OVERLAP DIAGNOSTIC")
    print("=" * 78)
    print()

    print(f"Parser modules             : {len(modules)}")
    print(f"Parser PORT declarations   : {total_ports}")
    print(f"Parser SIGNAL declarations : {total_signals}")
    print(f"PORT/SIGNAL overlaps       : {total_overlaps}")
    print()

    if not port_signal_overlaps:
        print("RESULT: No parser PORT/SIGNAL name overlaps found.")
        print()
        return {
            "modules": len(modules),
            "ports": total_ports,
            "signals": total_signals,
            "overlaps": 0,
            "collisions": 0,
        }

    # -----------------------------------------------------------------------
    # Detailed overlap report
    # -----------------------------------------------------------------------

    print("-" * 78)
    print("PARSER PORT/SIGNAL OVERLAPS")
    print("-" * 78)

    semantic_port_count = 0
    semantic_signal_count = 0
    semantic_other_count = 0
    semantic_missing_count = 0

    for record in port_signal_overlaps:
        module_name = record["module"]
        name = record["name"]

        print()
        print(f"MODULE: {module_name}")
        print(f"NAME  : {name}")
        print()

        print("  Parser PORT declaration(s):")

        for direction, port in record["ports"]:
            print(
                f"    {direction:6s} {name:20s} "
                f"{_port_description(port)}"
            )

        print()
        print("  Parser SIGNAL declaration(s):")

        for signal in record["signals"]:
            print(
                f"    signal {name:20s} "
                f"{_signal_description(signal)}"
            )

        print()

        symbol = record["semantic_symbol"]

        if symbol is None:
            semantic_missing_count += 1

            print("  Final semantic symbol:")
            print("    <NOT FOUND>")

        else:
            kind = record["semantic_kind"]

            if kind == SymbolKind.PORT:
                semantic_port_count += 1
            elif kind == SymbolKind.SIGNAL:
                semantic_signal_count += 1
            else:
                semantic_other_count += 1

            print("  Final semantic symbol:")
            print(f"    {_symbol_description(symbol)}")

        if verbose:
            print()
            print("  Interpretation:")

            if symbol is None:
                print("    Parser overlap exists, but no final semantic symbol exists.")

            elif record["semantic_kind"] == SymbolKind.SIGNAL:
                print(
                    "    WARNING: SIGNAL replaced/overwrote the PORT name "
                    "in the final scope."
                )

            elif record["semantic_kind"] == SymbolKind.PORT:
                print(
                    "    PORT survives in the final scope despite the "
                    "parser PORT/SIGNAL overlap."
                )

            else:
                print(
                    "    NOTE: Final symbol has a non-PORT/non-SIGNAL kind."
                )

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------

    print()
    print("=" * 78)
    print("SEMANTIC COLLISION SUMMARY")
    print("=" * 78)
    print()

    print(f"PORT/SIGNAL overlaps              : {total_overlaps}")
    print(f"Final semantic symbol = PORT      : {semantic_port_count}")
    print(f"Final semantic symbol = SIGNAL    : {semantic_signal_count}")
    print(f"Final semantic symbol = other     : {semantic_other_count}")
    print(f"Final semantic symbol missing     : {semantic_missing_count}")
    print()

    if semantic_signal_count:
        print(
            "RESULT: Parser PORT/SIGNAL overlaps are being represented as "
            "SIGNAL symbols in the final semantic scope."
        )
        print(
            "This is consistent with a same-name symbol overwrite during "
            "symbol collection."
        )
    elif total_overlaps:
        print(
            "RESULT: PORT/SIGNAL overlaps exist, but the PORT symbols "
            "survive in the final semantic scope."
        )
    else:
        print("RESULT: No overlaps.")

    print()

    return {
        "modules": len(modules),
        "ports": total_ports,
        "signals": total_signals,
        "overlaps": total_overlaps,
        "semantic_port": semantic_port_count,
        "semantic_signal": semantic_signal_count,
        "semantic_other": semantic_other_count,
        "semantic_missing": semantic_missing_count,
    }


# ---------------------------------------------------------------------------
# Project loading
# ---------------------------------------------------------------------------

def load_project(ip_name: str, rtl_root: Path):
    """
    Parse one IP and build only the semantic symbol table.

    No identifier resolution, type enrichment, or quality analysis.
    """

    print(f"Parsing IP: {ip_name}")
    print(f"RTL root : {rtl_root}")
    print()

    ip_dir = rtl_root / ip_name

    if not ip_dir.is_dir():
        raise FileNotFoundError(
            f"IP directory not found: {ip_dir}"
        )

    modules, top = parse_ip(str(ip_dir))

    analyzer = SemanticAnalyzer()

    # Only build the symbol table.
    analyzer.register(build_symbol_table)

    ctx = analyzer.analyze(modules)

    return modules, ctx


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose parser PORT/SIGNAL overlaps and semantic "
            "symbol collisions."
        )
    )

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--ip",
        help="IP name to diagnose, e.g. aes",
    )

    group.add_argument(
        "--all",
        action="store_true",
        help="Diagnose all discovered IPs.",
    )

    parser.add_argument(
        "--rtl-root",
        default="data/raw_rtl",
        help="RTL root directory (default: data/raw_rtl)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print interpretation for every overlap.",
    )

    args = parser.parse_args()

    rtl_root = Path(args.rtl_root)

    if args.ip:
        modules, ctx = load_project(args.ip, rtl_root)

        result = diagnose_project(
            modules,
            ctx,
            verbose=args.verbose,
        )

        print("STATUS: COMPLETE")
        print()

        # A diagnostic finding is not a failure.
        return 0

    # -----------------------------------------------------------------------
    # All IPs
    # -----------------------------------------------------------------------

    # Keep discovery aligned with the parser's RTL organization.
    if not rtl_root.exists():
        print(f"ERROR: RTL root does not exist: {rtl_root}")
        return 1

    ip_dirs = sorted(
        path for path in rtl_root.iterdir()
        if path.is_dir()
    )

    if not ip_dirs:
        print(f"ERROR: No IP directories found under {rtl_root}")
        return 1

    print(f"Found {len(ip_dirs)} IP directories.")
    print()

    aggregate = {
        "ips": 0,
        "modules": 0,
        "ports": 0,
        "signals": 0,
        "overlaps": 0,
        "semantic_port": 0,
        "semantic_signal": 0,
        "semantic_other": 0,
        "semantic_missing": 0,
    }

    for ip_dir in ip_dirs:
        ip_name = ip_dir.name

        print()
        print("#" * 78)
        print(f"# IP: {ip_name}")
        print("#" * 78)

        try:
            modules, ctx = load_project(
                ip_name,
                rtl_root,
            )

            result = diagnose_project(
                modules,
                ctx,
                verbose=args.verbose,
            )

        except Exception as exc:
            print(f"ERROR: Failed to diagnose {ip_name}: {exc}")
            continue

        aggregate["ips"] += 1

        for key in (
            "modules",
            "ports",
            "signals",
            "overlaps",
            "semantic_port",
            "semantic_signal",
            "semantic_other",
            "semantic_missing",
        ):
            aggregate[key] += result.get(key, 0)

    print()
    print("=" * 78)
    print("ALL-IP SUMMARY")
    print("=" * 78)
    print()

    print(f"IPs processed                    : {aggregate['ips']}")
    print(f"Modules                          : {aggregate['modules']}")
    print(f"Parser PORT declarations         : {aggregate['ports']}")
    print(f"Parser SIGNAL declarations       : {aggregate['signals']}")
    print(f"PORT/SIGNAL overlaps              : {aggregate['overlaps']}")
    print(f"Final semantic symbol = PORT     : {aggregate['semantic_port']}")
    print(f"Final semantic symbol = SIGNAL   : {aggregate['semantic_signal']}")
    print(f"Final semantic symbol = other    : {aggregate['semantic_other']}")
    print(f"Final semantic symbol missing    : {aggregate['semantic_missing']}")
    print()

    print("STATUS: COMPLETE")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
