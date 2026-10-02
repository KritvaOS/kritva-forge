# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : symbol_table.py
# Description : Symbol Table implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/symbol_table.py

Build semantic symbol table from parser IR.
"""

from scripts.semantic.scope import Scope, ScopeKind
from scripts.semantic.symbol import Symbol, SymbolKind


# ---------------------------------------
# Helper
# ---------------------------------------


def get_module_scope(ctx, module_name):
    return ctx.scopes.get(module_name)


# ---------------------------------------
# Symbol table construction
# ---------------------------------------


def build_symbol_table(project, ctx):
    """
    Build symbol table for entire project.

    project:
        Dictionary returned by parse_ip()

    ctx:
        SemanticContext
    """

    # ---------------------------------------
    # Create global scope
    # ---------------------------------------

    ctx.global_scope = Scope(
        name="global",
        kind=ScopeKind.GLOBAL,
    )

    ctx.current_scope = ctx.global_scope

    # ---------------------------------------
    # Walk every parsed module
    # ---------------------------------------

    for module_name, module in project.items():
        build_module_scope(module, ctx)


def collect_compilation_declarations(
    module,
    scope,
    ctx,
):
    """
    Collect semantic declarations from the actual PySlang
    compilation-unit AST.

    These declarations have already passed through the same
    include and preprocessor context used to parse the RTL.

    Supported declarations:
        - parameter
        - localparam
        - typedef enum members
    """

    for declaration in module.get(
        "compilation_declarations",
        [],
    ):

        kind = declaration.get("kind")

        # --------------------------------------------------
        # Parameter / localparam
        # --------------------------------------------------

        if kind in (
            "parameter",
            "localparam",
        ):

            symbol_kind = (
                SymbolKind.PARAMETER
                if kind == "parameter"
                else SymbolKind.LOCALPARAM
            )

            name = declaration.get(
                "name",
                "",
            ).strip()

            if not name:
                continue

            symbol = Symbol(
                name=name,
                kind=symbol_kind,
                value=declaration.get(
                    "default"
                ),
                node=None,
                scope=scope,
                metadata={
                    "source":
                        "compilation_unit",
                    "kind":
                        kind,
                },
            )

            scope.add_symbol(symbol)

            ctx.statistics.record_symbol(
                symbol_kind
            )

            continue

        # --------------------------------------------------
        # typedef enum
        # --------------------------------------------------

        if kind == "enum":

            enum = declaration.get(
                "enum"
            )

            if not enum:
                continue

            enum_name = enum.get(
                "name",
                "",
            ).strip()

            for member_name, member in enum.get(
                "members",
                {},
            ).items():

                name = member_name.strip()

                if not name:
                    continue

                symbol = Symbol(
                    name=name,
                    kind=SymbolKind.ENUM,
                    value=member.get(
                        "value"
                    ),
                    node=None,
                    scope=scope,
                    metadata={
                        "source":
                            "compilation_unit_enum",
                        "enum_type":
                            enum_name,
                    },
                )

                scope.add_symbol(symbol)

                ctx.statistics.record_symbol(
                    SymbolKind.ENUM
                )


def build_module_scope(module, ctx):

    scope = Scope(
        name=module["name"],
        kind=ScopeKind.MODULE,
        parent=ctx.global_scope,
    )

    ctx.global_scope.add_child(scope)

    ctx.scopes[module["name"]] = scope

    ctx.current_scope = scope

    # ---------------------------------------
    # Statistics
    # ---------------------------------------

    ctx.statistics.record_module(module["name"])
    ctx.statistics.record_scope(ScopeKind.MODULE)

    # ---------------------------------------
    # Module-local declarations
    # ---------------------------------------

    collect_parameters(
        module,
        scope,
        ctx,
    )
    # ---------------------------------------
    # enums declarations
    # ---------------------------------------
    collect_enums(
        module,
        scope,
        ctx,
    )

    # ---------------------------------------
    # Include-derived declarations
    # ---------------------------------------

    collect_compilation_declarations(
        module,
        scope,
        ctx,
    )

    # ---------------------------------------
    # Ports and signals
    # ---------------------------------------

    collect_ports(
        module,
        scope,
        ctx,
    )

    collect_signals(
        module,
        scope,
        ctx,
    )

    return scope


# ---------------------------------------
# Module parameters
# ---------------------------------------


def collect_parameters(module, scope, ctx):

    for parameter in module.get("parameters", []):

        symbol = Symbol(
            name=parameter["name"],
            kind=SymbolKind.PARAMETER,
            value=parameter.get("default"),
            node=parameter,
        )

        scope.add_symbol(symbol)

        ctx.statistics.record_symbol(
            SymbolKind.PARAMETER
        )


# ---------------------------------------
# Ports
# ---------------------------------------


def collect_ports(module, scope, ctx):

    interfaces = module.get(
        "interfaces",
        {},
    )

    mapping = {
        "inputs": "input",
        "outputs": "output",
        "inouts": "inout",
    }

    for key, direction in mapping.items():

        for port in interfaces.get(
            key,
            [],
        ):

            symbol = Symbol(
                name=port["name"],
                kind=SymbolKind.PORT,
                datatype=port.get("datatype"),
                direction=direction,
                node=port,
            )

            scope.add_symbol(symbol)

            ctx.statistics.record_symbol(
                SymbolKind.PORT
            )


# ---------------------------------------
# Signals
# ---------------------------------------


def _merge_signal_into_port(
    signal,
    port_symbol,
):
    """
    Merge a parser signal declaration into an existing PORT symbol.

    This handles non-ANSI port declarations where the parser represents
    the same RTL object both as a PORT and as a SIGNAL, for example:

        output data_out;
        reg    data_out;

    The PORT remains the semantic identity because it carries the
    interface direction. Signal declaration information is preserved
    in metadata rather than replacing the PORT symbol.
    """

    # Preserve signal declaration provenance/details.
    port_symbol.metadata.setdefault(
        "signal_declaration",
        signal,
    )

    # A signal declaration can provide datatype information that is
    # absent from the parser PORT declaration.
    signal_datatype = signal.get("type")

    if (
        port_symbol.datatype is None
        and signal_datatype is not None
    ):
        port_symbol.datatype = signal_datatype

    # Preserve width when it is available only on the signal declaration.
    signal_width = signal.get("width")

    if (
        port_symbol.width is None
        and signal_width is not None
    ):
        port_symbol.width = signal_width

    # Record the fact that the PORT also has a signal declaration.
    port_symbol.metadata["has_signal_declaration"] = True


def collect_signals(module, scope, ctx):

    for signal in module.get(
        "signals",
        [],
    ):

        name = signal["name"]

        # --------------------------------------------------
        # Non-ANSI port + signal declaration
        # --------------------------------------------------
        #
        # Example:
        #
        #     output data_out;
        #     reg    data_out;
        #
        # The parser represents both declarations. They refer
        # to the same semantic object, so preserve the PORT symbol
        # and merge the signal declaration into it.
        #
        existing = scope.symbols.get(name)

        if (
            existing is not None
            and existing.kind == SymbolKind.PORT
        ):
            _merge_signal_into_port(
                signal,
                existing,
            )

            continue

        symbol = Symbol(
            name=name,
            kind=SymbolKind.SIGNAL,
            datatype=signal.get("type"),
            width=signal.get("width"),
            node=signal,
        )

        scope.add_symbol(symbol)

        ctx.statistics.record_symbol(
            SymbolKind.SIGNAL
        )
# ---------------------------------------
# enums
# ---------------------------------------
def collect_enums(module, scope, ctx):
    for enum in module.get("enum_db", []):

        enum_type = enum.get("type")

        if enum_type not in (
            "typedef_enum",
            "inline_enum",
        ):
            continue

        enum_name = enum.get(
            "name",
            "",
        ).strip()

        for member_name, member in enum.get(
            "members",
            {},
        ).items():

            name = member_name.strip()

            if not name:
                continue

            symbol = Symbol(
                name=name,
                kind=SymbolKind.ENUM,
                value=member.get("value"),
                node=enum,
                metadata={
                    "source": "module_enum",
                    "enum_type": enum_name,
                    "enum_kind": enum_type,
                },
            )

            scope.add_symbol(symbol)
            ctx.statistics.record_symbol(
                SymbolKind.ENUM
            )
