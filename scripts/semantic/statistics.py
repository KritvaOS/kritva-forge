# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statistics.py
# Description : Statistics implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Statistics collection for semantic analysis.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class SemanticStatistics:
    """
    Semantic analysis statistics.
    """

    counters: Counter = field(default_factory=Counter)
    categories: dict[str, Counter] = field(default_factory=dict)

    references: int = 0
    resolved_references: int = 0
    unresolved_references: int = 0

    @property
    def resolution_rate(self) -> float:
        """Return identifier resolution rate as a percentage."""
    
        if self.references == 0:
            return 100.0
    
        return (
            self.resolved_references / self.references
        ) * 100.0


    # ------------------------------------------------------------
    # Generic counter
    # ------------------------------------------------------------

    def increment(self, name: str, count: int = 1):
        self.counters[name] += count

    # ------------------------------------------------------------
    # Categorized counter
    # ------------------------------------------------------------

    def record(self, category: str, name: str):
        if category not in self.categories:
            self.categories[category] = Counter()

        self.categories[category][name] += 1

    # ------------------------------------------------------------
    # Semantic-specific counters
    # ------------------------------------------------------------

    def record_module(self, name: str):
        self.increment("modules")

    def record_scope(self, scope_kind):
        self.increment("scopes")

        self.record(
            "scopes",
            self._enum_name(scope_kind),
        )

    def record_symbol(self, symbol_kind):
        self.increment("symbols")

        self.record(
            "symbols",
            self._enum_name(symbol_kind),
        )

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    @staticmethod
    def _enum_name(value) -> str:
        if isinstance(value, Enum):
            return value.name

        return str(value)

    # ------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------

    def merge(self, other: "SemanticStatistics"):
        """Merge another statistics object into this one."""
    
        self.counters.update(other.counters)
    
        for category, counter in other.categories.items():
            if category not in self.categories:
                self.categories[category] = Counter()
    
            self.categories[category].update(counter)
    
        self.references += other.references
        self.resolved_references += other.resolved_references
        self.unresolved_references += other.unresolved_references


    def record_reference(
        self,
        resolved: bool,
        reason=None,
    ) -> None:
        """Record one identifier reference resolution attempt."""
    
        self.references += 1
    
        if resolved:
            self.resolved_references += 1
        else:
            self.unresolved_references += 1
    
            if reason is not None:
                self.record(
                    "resolution",
                    self._enum_name(reason),
                )


    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------

    def print_summary(self):

        print()
        print("References")
        print("-" * 32)
        print(f"{'TOTAL':30} {self.references:8}")
        print(f"{'RESOLVED':30} {self.resolved_references:8}")
        print(f"{'UNRESOLVED':30} {self.unresolved_references:8}")
        print(f"{'COVERAGE':30} {self.resolution_rate:7.2f}%")


        print()
        print("=" * 72)
        print("Semantic Summary")
        print("=" * 72)

        for name in sorted(self.counters):
            print(f"{name:30} {self.counters[name]:8}")

        for category in sorted(self.categories):

            print()
            print(category.title())
            print("-" * 32)

            counter = self.categories[category]

            for item in sorted(counter):
                print(f"{item:30} {counter[item]:8}")


