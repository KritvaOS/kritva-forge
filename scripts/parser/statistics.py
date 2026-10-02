# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statistics.py
# Description : Statistics implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
statistics.py

Parser statistics collection and reporting.

This module collects parser statistics during RTL parsing and prints
a summary at the end of the run.

Author : BigEndian Semiconductor
"""

from collections import Counter


class ParserStatistics:
    """Collect parser statistics."""

    def __init__(self):

        self.reset()

    ####################################################################
    # Reset
    ####################################################################

    def reset(self):

        self.statement_counter = Counter()

        self.expression_counter = Counter()

        self.unknown_counter = Counter()

    ####################################################################
    # Record APIs
    ####################################################################

    def record_statement(self, name):

        self.statement_counter[name] += 1

    def record_expression(self, name):

        self.expression_counter[name] += 1

    def record_unknown(self, name):

        self.unknown_counter[name] += 1


    ####################################################################
    # Generic Counter Printer
    ####################################################################

    def _print_counter(self, title, counter):

        print()

        print("=" * 72)
        print(title)
        print("=" * 72)

        if not counter:
            print("None")
            return

        total = 0

        for name, count in counter.most_common():

            print(f"{name:<48}{count:>10}")

            total += count

        print("-" * 72)
        print(f"{'TOTAL':<48}{total:>10}")

    ####################################################################
    # Coverage
    ####################################################################

    def print_coverage(self):

        known = (
            sum(self.statement_counter.values())
            + sum(self.expression_counter.values())
        )

        unknown = sum(self.unknown_counter.values())

        total = known + unknown

        coverage = (
            100.0
            if total == 0
            else (known * 100.0) / total
        )

        print()

        print("=" * 72)
        print("Parser Coverage")
        print("=" * 72)

        print(f"{'Known Syntax':<32}: {known}")
        print(f"{'Unknown Syntax':<32}: {unknown}")
        print(f"{'Coverage':<32}: {coverage:.2f}%")

    ####################################################################
    # Summary
    ####################################################################

    def print_summary(self):

        print()

        print("#" * 72)
        print("RTL PARSER SUMMARY")
        print("#" * 72)

        self._print_counter(
            "Statement Summary",
            self.statement_counter,
        )

        self._print_counter(
            "Expression Summary",
            self.expression_counter,
        )

        self._print_counter(
            "Unknown Syntax",
            self.unknown_counter,
        )

        self.print_coverage()


########################################################################
# Singleton
########################################################################

stats = ParserStatistics()


########################################################################
# Convenience Wrapper APIs
########################################################################

def record_statement(name):
    stats.record_statement(name)


def record_expression(name):
    stats.record_expression(name)


def record_unknown(name):
    stats.record_unknown(name)


def reset_statistics():
    stats.reset()


def print_summary():
    stats.print_summary()
