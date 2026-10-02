# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : include_context.py
# Description : Include Context implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# scripts/parser/include_context.py

"""
Include-aware parser context.

This module provides lightweight SystemVerilog `include handling for the
parser layer.

Responsibilities:
    - Discover `include directives in a source/header file.
    - Resolve include files using deterministic search paths.
    - Recursively walk the include graph.
    - Parse included files with PySlang.
    - Collect top-level parameter/localparam declarations.
    - Collect enum members from typedef enum declarations.
    - Preserve declaration source provenance.

Non-responsibilities:
    - Macro expansion (`define)
    - Conditional preprocessing (`ifdef/`ifndef/...)
    - Parameter evaluation
    - Constant folding
    - Semantic symbol resolution
    - Package/import resolution
    - Hierarchical name resolution

The output of this module is parser-side context. Semantic passes may later
convert IncludeSymbol objects into semantic Symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Sequence

from pyslang import SourceManager
from pyslang.syntax import SyntaxTree


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IncludeSymbol:
    """
    A declaration originating from an included file.

    kind:
        "parameter"
        "localparam"
        "enum"

    `default` contains the source-level initializer expression as text
    when available.
    """

    name: str
    kind: str
    default: object | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class IncludeFile:
    """
    One resolved include edge in the include graph.

    `parent` is the file containing the `include directive.

    `include_name` is the literal name used by the directive.

    `path` is the resolved filesystem path.
    """

    path: str
    parent: str | None = None
    include_name: str | None = None


@dataclass
class IncludeContext:
    """
    Include information associated with one source RTL file.
    """

    source_file: str

    include_files: list[IncludeFile] = field(default_factory=list)

    symbols: list[IncludeSymbol] = field(default_factory=list)

    unresolved_includes: list[str] = field(default_factory=list)

    @property
    def symbol_map(self) -> dict[str, IncludeSymbol]:
        """
        Return collected symbols indexed by name.

        If duplicate declarations exist, the last collected declaration wins
        in this convenience map. The original `symbols` list is preserved so
        semantic code can diagnose duplicates if necessary.
        """
        return {symbol.name: symbol for symbol in self.symbols}


# ---------------------------------------------------------------------------
# Include discovery
# ---------------------------------------------------------------------------


_INCLUDE_RE = re.compile(
    r'^\s*`include\s+[<"]([^">]+)[">]',
    re.MULTILINE,
)


def discover_includes(source_file: str | Path) -> list[str]:
    """
    Discover literal `include directives in a source file.

    This function deliberately performs only preprocessor-directive discovery.
    Verilog/SystemVerilog declarations are parsed by PySlang elsewhere.

    Args:
        source_file:
            RTL/header source file.

    Returns:
        Include names in source-file order.
    """

    source_path = Path(source_file)

    text = source_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    return [
        match.group(1).strip()
        for match in _INCLUDE_RE.finditer(text)
    ]


# ---------------------------------------------------------------------------
# Include resolution
# ---------------------------------------------------------------------------


def _normalize_include_dirs(
    include_dirs: Sequence[str | Path] | None,
) -> list[Path]:
    """
    Normalize include directories to absolute paths.
    """

    if not include_dirs:
        return []

    result: list[Path] = []

    for directory in include_dirs:
        path = Path(directory).expanduser().resolve()

        if path not in result:
            result.append(path)

    return result


def resolve_include(
    include_name: str,
    source_file: str | Path,
    include_dirs: Sequence[str | Path] | None = None,
) -> Path | None:
    """
    Resolve an include name to an existing file.

    Search order:

        1. Directory containing source_file
        2. Explicit include_dirs, in supplied order

    The repository is NOT searched recursively. This prevents an unrelated
    file with the same basename from being selected accidentally.
    """

    include_name = include_name.strip()

    if not include_name:
        return None

    source_path = Path(source_file).expanduser().resolve()

    search_dirs: list[Path] = [
        source_path.parent,
        *_normalize_include_dirs(include_dirs),
    ]

    # Preserve ordering while removing duplicates.
    unique_dirs: list[Path] = []

    for directory in search_dirs:
        if directory not in unique_dirs:
            unique_dirs.append(directory)

    for directory in unique_dirs:
        candidate = (directory / include_name).resolve()

        if candidate.is_file():
            return candidate

    return None


# ---------------------------------------------------------------------------
# Header declaration extraction
# ---------------------------------------------------------------------------


def _parse_header(source_path: Path):
    """
    Parse one header without expanding local includes.

    Recursive include traversal is owned by _walk_includes().
    """

    source_manager = SourceManager()

    # Prevent PySlang from independently expanding local includes.
    #
    # This is important because _walk_includes() already owns include
    # traversal and cycle protection.
    source_manager.setDisableLocalIncludes(True)

    return SyntaxTree.fromFile(
        str(source_path),
        source_manager,
    )

def _parameter_kind(parameter) -> str:
    """Return the Verilog parameter declaration kind."""

    text = str(parameter).strip()

    if re.search(r"\blocalparam\b", text):
        return "localparam"

    if re.search(r"\bparameter\b", text):
        return "parameter"

    return "parameter"

def _extract_initializer(declarator) -> object | None:
    """
    Extract the source-level initializer expression.

    We intentionally preserve the expression rather than evaluating it.
    """

    initializer = getattr(
        declarator,
        "initializer",
        None,
    )

    if initializer is None:
        return None

    expr = getattr(
        initializer,
        "expr",
        None,
    )

    if expr is None:
        return None

    return str(expr).strip()


def extract_header_parameters(
    source_file: str | Path,
) -> list[IncludeSymbol]:
    """
    Extract top-level parameter/localparam declarations physically belonging
    to the specified source file.

    Include traversal is intentionally disabled here because the surrounding
    include-context walker owns recursive include handling.
    """

    source_path = Path(source_file).expanduser().resolve()

    tree = _parse_header(source_path)

    symbols: list[IncludeSymbol] = []

    for member in tree.root.members:

        if type(member).__name__ != "ParameterDeclarationStatementSyntax":
            continue

        parameter = getattr(member, "parameter", None)

        if parameter is None:
            continue

        kind = _parameter_kind(parameter)

        declarators = getattr(
            parameter,
            "declarators",
            [],
        )

        for declarator in declarators:

            name_node = getattr(
                declarator,
                "name",
                None,
            )

            if name_node is None:
                continue

            name = getattr(
                name_node,
                "value",
                None,
            )

            if not name:
                continue

            symbols.append(
                IncludeSymbol(
                    name=str(name),
                    kind=kind,
                    default=_extract_initializer(declarator),
                    source_file=str(source_path),
                )
            )

    return symbols


# ---------------------------------------------------------------------------
# Enum extraction
# ---------------------------------------------------------------------------


def _walk_ast(node):
    """
    Generic AST traversal.

    Keep this local to include_context.py so enum extraction does not create
    a dependency from parser context into the broader ast_utils module.
    """

    if node is None:
        return

    yield node

    # PySlang syntax nodes expose their children through various attributes.
    # These are the same broad structural relationships used by the existing
    # parser AST utilities.
    child_attributes = (
        "members",
        "items",
        "declarators",
        "statement",
        "body",
        "clauses",
        "blocks",
        "branches",
        "expression",
        "expressions",
        "initializer",
        "value",
        "baseType",
        "type",
        "predicate",
        "condition",
        "elseClause",
        "clause",
        "expr",
    )

    seen = set()

    for attribute in child_attributes:

        try:
            child = getattr(node, attribute, None)
        except Exception:
            continue

        if child is None:
            continue

        children = child if isinstance(child, (list, tuple)) else [child]

        for item in children:

            if item is None:
                continue

            identity = id(item)

            if identity in seen:
                continue

            seen.add(identity)

            yield from _walk_ast(item)


def _find_enum_type(typedef_node):
    """
    Find EnumTypeSyntax within a typedef declaration.

    This deliberately verifies that the typedef really contains an enum.
    That prevents ordinary typedef structs/records from being classified
    as enums.
    """

    for node in _walk_ast(typedef_node):

        if type(node).__name__ == "EnumTypeSyntax":
            return node

    return None


def _enum_member_name(node):
    """
    Extract an identifier name from a possible enum-member declaration.
    """

    name_node = getattr(
        node,
        "name",
        None,
    )

    if name_node is None:
        return None

    name = getattr(
        name_node,
        "value",
        None,
    )

    if not name:
        return None

    return str(name)


def _extract_enum_members(enum_type):
    """
    Extract enum member names and source-level initializer expressions.

    The traversal is scoped to the EnumTypeSyntax node so identifiers from
    the typedef name or enum base type are not collected.
    """

    members = []

    for node in _walk_ast(enum_type):

        # The EnumTypeSyntax itself is not an enum member.
        if node is enum_type:
            continue

        name = _enum_member_name(node)

        if not name:
            continue

        initializer = getattr(
            node,
            "initializer",
            None,
        )

        expr = None

        if initializer is not None:

            expr_node = getattr(
                initializer,
                "expr",
                None,
            )

            if expr_node is not None:
                expr = str(expr_node).strip()

        members.append(
            {
                "name": name,
                "expr": expr,
            }
        )

    # Preserve source order but avoid accidentally returning the same AST
    # declaration more than once.
    result = []
    seen_names = set()

    for member in members:

        name = member["name"]

        if name in seen_names:
            continue

        seen_names.add(name)
        result.append(member)

    return result


def extract_header_enums(
    source_file: str | Path,
) -> list[IncludeSymbol]:
    """
    Extract enum members from typedef enum declarations physically belonging
    to the specified source file.

    Each enum member becomes an IncludeSymbol with:

        kind="enum"

    The enum typedef name itself is NOT added as a symbol.

    Include traversal is intentionally disabled here because the surrounding
    include-context walker owns recursive include handling.
    """

    source_path = Path(source_file).expanduser().resolve()

    tree = _parse_header(source_path)

    symbols: list[IncludeSymbol] = []

    for member in tree.root.members:

        if type(member).__name__ != "TypedefDeclarationSyntax":
            continue

        enum_type = _find_enum_type(member)

        if enum_type is None:
            continue

        for enum_member in _extract_enum_members(enum_type):

            symbols.append(
                IncludeSymbol(
                    name=enum_member["name"],
                    kind="enum",
                    default=enum_member["expr"],
                    source_file=str(source_path),
                )
            )

    return symbols


# ---------------------------------------------------------------------------
# Recursive include traversal
# ---------------------------------------------------------------------------


def _walk_includes(
    source_file: Path,
    include_dirs: list[Path],
    context: IncludeContext,
    visited: set[Path],
) -> None:
    """
    Recursively walk includes starting from source_file.

    `visited` is keyed by resolved filesystem path, preventing duplicate
    parsing and protecting against include cycles.
    """

    source_file = source_file.resolve()

    for include_name in discover_includes(source_file):

        include_path = resolve_include(
            include_name,
            source_file,
            include_dirs,
        )

        if include_path is None:
            context.unresolved_includes.append(include_name)
            continue

        include_path = include_path.resolve()

        if include_path in visited:
            continue

        visited.add(include_path)

        context.include_files.append(
            IncludeFile(
                path=str(include_path),
                parent=str(source_file),
                include_name=include_name,
            )
        )

        # Collect parameters/localparams from this header.
        context.symbols.extend(
            extract_header_parameters(include_path)
        )

        # Collect enum members from this header.
        context.symbols.extend(
            extract_header_enums(include_path)
        )

        # Continue recursively through its includes.
        _walk_includes(
            include_path,
            include_dirs,
            context,
            visited,
        )


# ---------------------------------------------------------------------------
# Public context builder
# ---------------------------------------------------------------------------


def build_include_context(
    source_file,
    include_dirs=None,
) -> IncludeContext:
    """
    Build recursive include context for a source RTL file.

    The source file itself is NOT treated as an include file. Its direct and
    recursive includes are traversed.
    """

    source_path = Path(source_file).expanduser().resolve()

    context = IncludeContext(
        source_file=str(source_path)
    )

    # Seed visited with the root source file. This prevents a cycle from
    # returning to the root.
    visited = {source_path}

    _walk_includes(
        source_path,
        _normalize_include_dirs(include_dirs),
        context,
        visited,
    )

    return context


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def collect_include_symbols(
    source_file: str | Path,
    include_dirs: Sequence[str | Path] | None = None,
) -> list[IncludeSymbol]:
    """
    Convenience API returning only collected include symbols.
    """

    return build_include_context(
        source_file=source_file,
        include_dirs=include_dirs,
    ).symbols


__all__ = [
    "IncludeSymbol",
    "IncludeFile",
    "IncludeContext",
    "discover_includes",
    "resolve_include",
    "extract_header_parameters",
    "extract_header_enums",
    "build_include_context",
    "collect_include_symbols",
]
