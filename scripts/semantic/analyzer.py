# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : analyzer.py
# Description : Analyzer implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/analyzer.py

Semantic analysis pipeline.

The analyzer coordinates all semantic analysis passes.
Each pass enriches the parsed IR but does not modify the parser itself.
"""

from __future__ import annotations

from scripts.semantic.context import SemanticContext


class SemanticAnalyzer:
    """
    Semantic analysis pipeline.
    """

    def __init__(self):

        self._passes = []

    @property
    def passes(self):
        """
        Registered semantic passes (read-only).
        """
        return tuple(self._passes)


    # --------------------------------------------------
    # Register Pass
    # --------------------------------------------------

    def register(self, semantic_pass):

        self._passes.append(semantic_pass)

    # --------------------------------------------------
    # Run
    # --------------------------------------------------

    def analyze(self, project):

        ctx = SemanticContext()

        #
        # Execute passes in registration order
        #
        for semantic_pass in self._passes:

            semantic_pass(project, ctx)

        return ctx
