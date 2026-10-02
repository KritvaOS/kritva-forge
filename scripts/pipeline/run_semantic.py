#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : run_semantic.py
# Description : Run Semantic implementation
#
# Component   : Kritva Forge
# Module      : pipeline
# Layer       : Pipeline
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
run_semantic.py

Semantic Analysis Driver

This script executes the semantic analysis pipeline on the parsed RTL IR.

Pipeline

    Parser
        ↓
    Project IR
        ↓
    Semantic Analyzer
        ↓
    Semantic Context
        ↓
    Statistics
"""

from __future__ import annotations

import logging

from scripts.semantic import SemanticAnalyzer
from scripts.semantic.symbol_table import build_symbol_table
from scripts.semantic.resolver import SemanticResolver
from scripts.semantic.quality import analyze_quality, print_quality_report
from scripts.semantic.type_enrichment import enrich_symbol_types

logger = logging.getLogger(__name__)


def register_semantic_passes(analyzer):
    """
    Register semantic analysis passes in dependency order.

    Symbol-table construction must happen before identifier resolution.
    """
    analyzer.register(build_symbol_table)
    analyzer.register(resolve_identifiers)



def run_semantic(project):
    """
    Execute semantic analysis.
    """

    if project is None:
        raise ValueError("project cannot be None")

    analyzer = SemanticAnalyzer()

    # ----------------------------------------------------------
    # Register semantic passes
    # ----------------------------------------------------------
    register_semantic_passes(analyzer)

    # ----------------------------------------------------------
    # Execute semantic analysis
    # ----------------------------------------------------------
    ctx = analyzer.analyze(project)

    # ----------------------------------------------------------
    # REV-003B: Type enrichment
    # ----------------------------------------------------------
    enrich_symbol_types(
        project,
        ctx,
    )

    # ----------------------------------------------------------
    # Print semantic resolution summary
    # ----------------------------------------------------------
    if ctx.statistics is not None:
        ctx.statistics.print_summary()

    # ----------------------------------------------------------
    # REV-003A: Semantic quality analysis
    # ----------------------------------------------------------
    quality_report = analyze_quality(
        project,
        ctx,
    )

    print_quality_report(
        quality_report,
    )

    return ctx

def print_unresolved_reference(result, module_name):
    """Print diagnostic information for one unresolved reference."""

    print(
        "UNRESOLVED_REFERENCE:"
        f" module={module_name}"
        f" name={result.name!r}"
        f" reason={result.reason}"
        f" scope={result.scope_name!r}"
        f" scope_kind={result.scope_kind!r}"
        f" expression_type={result.expression_type!r}"
    )

def resolve_identifiers(project, ctx):
    """
    Resolve identifier references across the parsed project.
    """

    resolver = SemanticResolver(ctx)

    for module_name, module in project.items():

        scope = ctx.scopes.get(module_name)

        if scope is None:
            logger.warning(
                "No semantic scope found for module: %s",
                module_name,
            )
            continue

        assigns = module.get("continuous_assigns", [])
        processes = module.get("processes", [])

        # ----------------------------------------------------------
        # Continuous assignments
        # ----------------------------------------------------------

        for assignment in assigns:

            lhs = assignment.get("lhs")
            rhs = assignment.get("rhs")

            for result in resolver.resolve_expression(
                lhs,
                scope,
            ):
                ctx.statistics.record_reference(
                    result.resolved,
                    result.reason,
                )
                if not result.resolved:
                    print_unresolved_reference(result, module_name)

            for result in resolver.resolve_expression(
                rhs,
                scope,
            ):
                ctx.statistics.record_reference(
                    result.resolved,
                    result.reason,
                )
                if not result.resolved:
                    print_unresolved_reference(result, module_name)


        # ----------------------------------------------------------
        # Procedural processes
        # ----------------------------------------------------------

        for process in processes:

            body = process.get("body")

            for result in resolver.resolve_statement(
                body,
                scope,
            ):
                ctx.statistics.record_reference(
                    result.resolved,
                    result.reason,
                )

                if not result.resolved:
                    print_unresolved_reference(
                        result,
                        module_name,
                    )

