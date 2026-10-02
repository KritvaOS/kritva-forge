# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : fsm_coverage.py
# Description : Report FSM state-encoding coverage from normalized IR
#
# Component   : Kritva Forge
# Module      : fsm
# Layer       : FSM Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from __future__ import annotations

import argparse
import glob
import os

import yaml


def report(root: str) -> tuple[int, int]:
    total = 0
    encoded = 0

    pattern = os.path.join(root, "**", "modules", "*.yaml")
    for filename in glob.glob(pattern, recursive=True):
        try:
            with open(filename, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

            fsm = data.get("fsm", {})
            if not fsm:
                continue

            total += 1
            if fsm.get("state_encoding", {}):
                encoded += 1
        except Exception:
            continue

    return total, encoded


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report FSM state-encoding coverage."
    )
    parser.add_argument(
        "normalized_root",
        nargs="?",
        default="../kritva-forge-data/normalized/ir",
        help="Normalized IR root.",
    )
    args = parser.parse_args()

    total, encoded = report(args.normalized_root)
    print(f"FSMs         : {total}")
    print(f"With Encoding: {encoded}")
    print(f"Coverage     : {100.0 * encoded / max(total, 1):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
