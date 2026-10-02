#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : debug_cast_expressions.py
# Description : Debug Cast Expressions implementation
#
# Component   : Kritva Forge
# Module      : debug
# Layer       : Development Tools
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import os
import sys

import parser.expression_parser as expression_parser
from scripts.parser.rtl_parser_slang import parse_ip


original_parse_unknown = expression_parser.parse_unknown

cast_count = 0


def get_node_text(node):
    try:
        return str(node).strip()
    except Exception:
        return "<unavailable>"


def get_location(node):
    try:
        start = node.sourceRange.start

        return {
            "offset": getattr(start, "offset", -1),
            "buffer": str(getattr(start, "buffer", "")),
        }

    except Exception:
        return {
            "offset": -1,
            "buffer": "",
        }


def debug_parse_unknown(node):

    global cast_count

    if getattr(node, "kind", None) == expression_parser.SyntaxKind.CastExpression:

        cast_count += 1

        location = get_location(node)

        print()
        print("=" * 100)
        print(f"CAST #{cast_count}")
        print("=" * 100)

        print(f"NODE TYPE : {type(node).__name__}")
        print(f"KIND      : {node.kind}")
        print(f"TEXT      : {get_node_text(node)!r}")
        print(f"OFFSET    : {location['offset']}")
        print(f"BUFFER    : {location['buffer']}")

        #
        # Inspect the actual CastExpressionSyntax fields.
        #
        print()
        print("FIELDS")
        print("-" * 100)

        for attr in (
            "type",
            "operand",
            "expression",
            "left",
            "right",
            "name",
            "identifier",
        ):
            if not hasattr(node, attr):
                continue

            try:
                value = getattr(node, attr)

                if value is None:
                    print(f"{attr:12}: None")
                    continue

                print(
                    f"{attr:12}: "
                    f"{type(value).__name__} "
                    f"kind={getattr(value, 'kind', None)} "
                    f"text={get_node_text(value)!r}"
                )

            except Exception as exc:
                print(
                    f"{attr:12}: "
                    f"<error: {exc}>"
                )

        #
        # Show the direct public attributes of the cast node.
        # We DO NOT recursively walk them.
        #
        print()
        print("PUBLIC ATTRIBUTES")
        print("-" * 100)

        try:
            for attr in dir(node):

                if attr.startswith("_"):
                    continue

                try:
                    value = getattr(node, attr)
                except Exception:
                    continue

                if callable(value):
                    continue

                print(
                    f"{attr:30}: "
                    f"{type(value).__name__}"
                )

        except Exception as exc:
            print(f"<attribute inspection failed: {exc}>")

        print()

    #
    # Continue using the original parser behavior.
    #
    return original_parse_unknown(node)


def main():

    if len(sys.argv) != 2:
        print(
            "Usage:\n"
            "  PYTHONPATH=scripts .venv/bin/python "
            "scripts/debug_cast_expressions.py "
            "data/raw_rtl"
        )
        sys.exit(1)

    rtl_root = os.path.abspath(sys.argv[1])

    if not os.path.isdir(rtl_root):
        print(
            f"[ERROR] RTL root does not exist: "
            f"{rtl_root}"
        )
        sys.exit(1)

    #
    # Monkey-patch ONLY for this diagnostic process.
    # No source file is modified.
    #
    expression_parser.parse_unknown = debug_parse_unknown

    #
    # Reuse the production parse_ip() flow.
    #
    if os.path.isfile(
        os.path.join(rtl_root, "files.f")
    ):
        ip_dirs = [rtl_root]

    else:
        ip_dirs = []

        for name in sorted(os.listdir(rtl_root)):

            ip_dir = os.path.join(
                rtl_root,
                name,
            )

            if os.path.isdir(ip_dir):
                ip_dirs.append(ip_dir)

    print(f"[INFO] IP directories: {len(ip_dirs)}")

    for ip_dir in ip_dirs:

        print()
        print("#" * 100)
        print(f"IP: {os.path.basename(ip_dir)}")
        print("#" * 100)

        try:
            parse_ip(ip_dir)

        except Exception as exc:
            print(
                f"[ERROR] Failed processing "
                f"{ip_dir}: {exc}"
            )
            raise

    print()
    print("#" * 100)
    print(f"TOTAL CAST EXPRESSIONS: {cast_count}")
    print("#" * 100)


if __name__ == "__main__":
    main()
