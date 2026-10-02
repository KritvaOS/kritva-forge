# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : resolver.py
# Description : Resolver implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/resolver.py

Identifier resolution for RTL Expression IR.

This module operates exclusively on parser-generated Expression IR
and semantic Scope/Symbol objects.

Responsibilities
----------------
* Resolve identifier expressions against the current scope.
* Recursively resolve identifiers inside compound expressions.
* Resolve call arguments, but not function names.
* Resolve select bases and selector expressions.
* Resolve the base of member access, but defer member resolution.
* Report unresolved identifiers.

The resolver does not:
* parse RTL
* inspect PySlang AST nodes
* modify the parser IR
* perform hierarchy/package/type resolution
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from scripts.semantic.scope import Scope
from scripts.semantic.symbol import Symbol
from scripts.rtl_ir.expression_utils import expression_type

# ----------------------------------------------------------------------
# Resolution Status
# ----------------------------------------------------------------------


class ResolutionStatus(str, Enum):
    """Result status for an identifier lookup."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"

class ResolutionReason(str, Enum):
    NONE = "none"
    RESOLVED = "resolved"
    EMPTY_NAME = "empty_name"
    UNKNOWN_SYMBOL = "unknown_symbol"


# ----------------------------------------------------------------------
# Resolution Result
# ----------------------------------------------------------------------


@dataclass
class ResolutionResult:
    """
    Result of resolving one identifier reference.

    Parameters
    ----------
    name:
        Identifier name being resolved.

    status:
        ResolutionStatus indicating whether the identifier was found.

    symbol:
        Resolved semantic Symbol, or None when unresolved.
    """

    name: str
    status: ResolutionStatus
    symbol: Symbol | None = None

    reason: ResolutionReason = ResolutionReason.NONE
    scope_name: str | None = None
    scope_kind: str | None = None
    expression_type: str | None = None


    @property
    def resolved(self) -> bool:
        """Return True when the identifier was resolved."""
        return self.status == ResolutionStatus.RESOLVED

    @property
    def unresolved(self) -> bool:
        """Return True when the identifier was not resolved."""
        return self.status == ResolutionStatus.UNRESOLVED


# ----------------------------------------------------------------------
# Resolver
# ----------------------------------------------------------------------


class SemanticResolver:
    """
    Resolve identifiers in RTL Expression IR.

    The resolver is intentionally independent of PySlang. It works only
    with the dictionary-based Expression IR produced by the parser and
    the semantic Scope/Symbol model.
    """

    def __init__(self, ctx=None):
        """
        Parameters
        ----------
        ctx:
            Optional SemanticContext.

        The context is not required for basic resolution, but is retained
        so the resolver can later record semantic results/statistics
        without changing its public API.
        """
        self.ctx = ctx

    # ------------------------------------------------------------------
    # Identifier
    # ------------------------------------------------------------------

    def resolve_identifier(
        self,
        name: str,
        scope: Scope,
    ) -> ResolutionResult:
        """
        Resolve one identifier against the supplied scope.
    
        Scope.lookup() performs local lookup followed by parent-scope
        lookup.
        """
    
        if scope is None:
            return ResolutionResult(
                name=name,
                status=ResolutionStatus.UNRESOLVED,
                reason=ResolutionReason.MISSING_SCOPE,
                scope_name=None,
                scope_kind=None,
                expression_type="identifier",
            )
    
        if not name:
            return ResolutionResult(
                name=name,
                status=ResolutionStatus.UNRESOLVED,
                reason=ResolutionReason.EMPTY_NAME,
                scope_name=scope.name,
                scope_kind=scope.kind.value,
                expression_type="identifier",
            )
    
        symbol = scope.lookup(name)
    
        if symbol is None:
            return ResolutionResult(
                name=name,
                status=ResolutionStatus.UNRESOLVED,
                reason=ResolutionReason.UNKNOWN_SYMBOL,
                scope_name=scope.name,
                scope_kind=scope.kind.value,
                expression_type="identifier",
            )
    
        return ResolutionResult(
            name=name,
            status=ResolutionStatus.RESOLVED,
            symbol=symbol,
            reason=ResolutionReason.RESOLVED,
            scope_name=scope.name,
            scope_kind=scope.kind.value,
            expression_type="identifier",
        )

    # ------------------------------------------------------------------
    # Expression
    # ------------------------------------------------------------------

    def resolve_expression(
        self,
        expr: Any,
        scope: Scope,
    ) -> list[ResolutionResult]:
        """
        Resolve all identifier references contained in an Expression IR.

        Returns
        -------
        list[ResolutionResult]
            One result for each identifier reference encountered.
        """

        results: list[ResolutionResult] = []
        
        if expr is None:
            return results
        
        # Legacy string support
        if isinstance(expr, str):
            results.append(
                self.resolve_identifier(expr, scope)
            )
            return results
        
        # Expression IR must be dictionary based.
        if not isinstance(expr, dict):
            results.append(
                ResolutionResult(
                    name="",
                    status=ResolutionStatus.UNRESOLVED,
                    reason=ResolutionReason.INVALID_EXPRESSION,
                    scope_name=scope.name if scope else None,
                    scope_kind=scope.kind.value if scope else None,
                    expression_type=type(expr).__name__,
                )
            )
            return results

        expr_type = expr.get("expr_type")

        # --------------------------------------------------------------
        # Identifier
        # --------------------------------------------------------------

        if expr_type == "identifier":
            name = expr.get("name", "")

            results.append(
                self.resolve_identifier(name, scope)
            )

            return results

        # --------------------------------------------------------------
        # Function call
        #
        # The function name is intentionally NOT resolved as a signal,
        # parameter, etc.
        #
        # Only call arguments are semantic identifier references at
        # this stage.
        # --------------------------------------------------------------

        if expr_type == "call":
            for argument in expr.get("arguments", []):
                results.extend(
                    self.resolve_expression(argument, scope)
                )

            return results

        # --------------------------------------------------------------
        # Member access
        #
        # Resolve the base:
        #
        #     foo.bar
        #     ^^^
        #
        # Defer the member:
        #
        #          ^^^
        #
        # Member resolution belongs to later type/hierarchy/package
        # semantic analysis.
        # --------------------------------------------------------------

        if expr_type == "member_access":
            base = expr.get("base")

            results.extend(
                self.resolve_expression(base, scope)
            )

            return results

        # --------------------------------------------------------------
        # Generic recursive traversal
        #
        # Binary, unary, conditional, concatenation, select, etc.
        # already expose their nested expressions through "children".
        # --------------------------------------------------------------

        for child in expr.get("children", []):
            results.extend(
                self.resolve_expression(child, scope)
            )

        return results

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def resolve(
        self,
        expr: Any,
        scope: Scope,
    ) -> list[ResolutionResult]:
        """
        Convenience alias for resolve_expression().
        """

        return self.resolve_expression(expr, scope)


    def resolve_statement(
        self,
        stmt,
        scope,
    ) -> list[ResolutionResult]:
        """
        Resolve all identifier references contained in a Statement IR tree.
        """
    
        results: list[ResolutionResult] = []
    
        if stmt is None:
            return results
    
        if not isinstance(stmt, dict):
            return results
    
        stmt_type = stmt.get("stmt_type")
    
        # Assignment
        if stmt_type == "assignment":
            results.extend(
                self.resolve_expression(
                    stmt.get("lhs"),
                    scope,
                )
            )
    
            results.extend(
                self.resolve_expression(
                    stmt.get("rhs"),
                    scope,
                )
            )
    
            return results
    
        # If
        if stmt_type == "if":
            results.extend(
                self.resolve_expression(
                    stmt.get("condition"),
                    scope,
                )
            )
    
            results.extend(
                self.resolve_statement(
                    stmt.get("then"),
                    scope,
                )
            )
    
            results.extend(
                self.resolve_statement(
                    stmt.get("else"),
                    scope,
                )
            )
    
            return results
    
        # Case
        if stmt_type == "case":
            results.extend(
                self.resolve_expression(
                    stmt.get("expression"),
                    scope,
                )
            )
    
            for item in stmt.get("items", []):
                results.extend(
                    self.resolve_statement(
                        item,
                        scope,
                    )
                )
    
            return results
    
        # Case item
        if stmt_type == "case_item":
            for label in stmt.get("labels", []):
                results.extend(
                    self.resolve_expression(
                        label,
                        scope,
                    )
                )
    
            results.extend(
                self.resolve_statement(
                    stmt.get("statement"),
                    scope,
                )
            )
    
            return results
    
        # Block
        if stmt_type == "block":
            for child in stmt.get("statements", []):
                results.extend(
                    self.resolve_statement(
                        child,
                        scope,
                    )
                )
    
            return results
    
        # Loop
        if stmt_type == "loop":
            for field in (
                "init",
                "condition",
                "step",
            ):
                value = stmt.get(field)
    
                if isinstance(value, dict):
                    if value.get("stmt_type"):
                        results.extend(
                            self.resolve_statement(
                                value,
                                scope,
                            )
                        )
                    else:
                        results.extend(
                            self.resolve_expression(
                                value,
                                scope,
                            )
                        )
    
            body = stmt.get("body")
    
            if body is not None:
                results.extend(
                    self.resolve_statement(
                        body,
                        scope,
                    )
                )
    
            return results
    
        # Return
        if stmt_type == "return":
            results.extend(
                self.resolve_expression(
                    stmt.get("expression"),
                    scope,
                )
            )
    
            return results
    
        # Delay
        if stmt_type == "delay":
            results.extend(
                self.resolve_expression(
                    stmt.get("delay"),
                    scope,
                )
            )
    
            results.extend(
                self.resolve_statement(
                    stmt.get("statement"),
                    scope,
                )
            )
    
            return results
    
        # Generic fallback for future statement types.
        for child in stmt.get("children", []):
            if isinstance(child, dict):
                if child.get("stmt_type"):
                    results.extend(
                        self.resolve_statement(
                            child,
                            scope,
                        )
                    )
                else:
                    results.extend(
                        self.resolve_expression(
                            child,
                            scope,
                        )
                    )
    
        return results


def resolve_statement(
    self,
    stmt,
    scope,
) -> list[ResolutionResult]:
    """
    Resolve all identifier references contained in a Statement IR tree.
    """

    results: list[ResolutionResult] = []

    if stmt is None:
        return results

    if not isinstance(stmt, dict):
        return results

    stmt_type = stmt.get("stmt_type")

    # Assignment
    if stmt_type == "assignment":
        results.extend(
            self.resolve_expression(
                stmt.get("lhs"),
                scope,
            )
        )

        results.extend(
            self.resolve_expression(
                stmt.get("rhs"),
                scope,
            )
        )

        return results

    # If
    if stmt_type == "if":
        results.extend(
            self.resolve_expression(
                stmt.get("condition"),
                scope,
            )
        )

        results.extend(
            self.resolve_statement(
                stmt.get("then"),
                scope,
            )
        )

        results.extend(
            self.resolve_statement(
                stmt.get("else"),
                scope,
            )
        )

        return results

    # Case
    if stmt_type == "case":
        results.extend(
            self.resolve_expression(
                stmt.get("expression"),
                scope,
            )
        )

        for item in stmt.get("items", []):
            results.extend(
                self.resolve_statement(
                    item,
                    scope,
                )
            )

        return results

    # Case item
    if stmt_type == "case_item":
        for label in stmt.get("labels", []):
            results.extend(
                self.resolve_expression(
                    label,
                    scope,
                )
            )

        results.extend(
            self.resolve_statement(
                stmt.get("statement"),
                scope,
            )
        )

        return results

    # Block
    if stmt_type == "block":
        for child in stmt.get("statements", []):
            results.extend(
                self.resolve_statement(
                    child,
                    scope,
                )
            )

        return results

    # Loop
    if stmt_type == "loop":
        for field in (
            "init",
            "condition",
            "step",
        ):
            value = stmt.get(field)

            if isinstance(value, dict):
                if value.get("stmt_type"):
                    results.extend(
                        self.resolve_statement(
                            value,
                            scope,
                        )
                    )
                else:
                    results.extend(
                        self.resolve_expression(
                            value,
                            scope,
                        )
                    )

        body = stmt.get("body")

        if body is not None:
            results.extend(
                self.resolve_statement(
                    body,
                    scope,
                )
            )

        return results

    # Return
    if stmt_type == "return":
        results.extend(
            self.resolve_expression(
                stmt.get("expression"),
                scope,
            )
        )

        return results

    # Delay
    if stmt_type == "delay":
        results.extend(
            self.resolve_expression(
                stmt.get("delay"),
                scope,
            )
        )

        results.extend(
            self.resolve_statement(
                stmt.get("statement"),
                scope,
            )
        )

        return results

    # Generic fallback for future statement types.
    for child in stmt.get("children", []):
        if isinstance(child, dict):
            if child.get("stmt_type"):
                results.extend(
                    self.resolve_statement(
                        child,
                        scope,
                    )
                )
            else:
                results.extend(
                    self.resolve_expression(
                        child,
                        scope,
                    )
                )

    return results
