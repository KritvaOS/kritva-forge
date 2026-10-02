# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : quality.py
# Description : Quality implementation
#
# Component   : Kritva Forge
# Module      : semantic
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
semantic/quality.py

Semantic quality analysis.

This module measures the completeness of semantic information already
available in the parser IR and semantic symbol table.

Responsibilities
----------------
- Measure semantic information completeness.
- Measure symbol metadata coverage.
- Measure parameter/value coverage.
- Measure port and signal metadata coverage.
- Measure enum coverage.
- Measure instance/module relationship coverage.
- Measure instance connection completeness.
- Measure source provenance coverage.

Non-responsibilities
-------------------
- No semantic inference.
- No datatype normalization.
- No width calculation.
- No constant evaluation.
- No symbol-table mutation.
- No PySlang dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from scripts.semantic.symbol import SymbolKind


# ---------------------------------------------------------------------------
# Generic quality metric
# ---------------------------------------------------------------------------


@dataclass
class QualityMetric:
    """Count and coverage for one semantic property."""

    total: int = 0
    known: int = 0

    @property
    def unknown(self) -> int:
        return self.total - self.known

    @property
    def coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.known / self.total) * 100.0

    def record(self, known: bool) -> None:
        self.total += 1

        if known:
            self.known += 1


# ---------------------------------------------------------------------------
# Parameter quality
# ---------------------------------------------------------------------------


@dataclass
class ParameterQuality:
    """Quality information for parameters and localparams."""

    total: int = 0
    with_value: int = 0
    literal_value: int = 0
    expression_value: int = 0

    def record(self, value: Any) -> None:
        self.total += 1

        if value is None:
            return

        self.with_value += 1

        if _is_literal_value(value):
            self.literal_value += 1
        else:
            self.expression_value += 1

    @property
    def missing_value(self) -> int:
        return self.total - self.with_value

    @property
    def value_coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.with_value / self.total) * 100.0


# ---------------------------------------------------------------------------
# Enum quality
# ---------------------------------------------------------------------------


@dataclass
class EnumQuality:
    """Quality information for enum types and members."""

    enum_types: int = 0
    members: int = 0
    members_with_values: int = 0

    @property
    def valued_member_coverage(self) -> float | None:
        if self.members == 0:
            return None

        return (
            self.members_with_values / self.members
        ) * 100.0


# ---------------------------------------------------------------------------
# Instance quality
# ---------------------------------------------------------------------------


@dataclass
class InstanceQuality:
    """Quality information for module instances."""

    total: int = 0
    module_known: int = 0
    instance_name_known: int = 0
    connections_present: int = 0

    @property
    def module_resolution_coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.module_known / self.total) * 100.0

    @property
    def instance_name_coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.instance_name_known / self.total) * 100.0


# ---------------------------------------------------------------------------
# Connection quality
# ---------------------------------------------------------------------------


@dataclass
class ConnectionQuality:
    """Quality information for instance port connections."""

    total: int = 0
    formal_present: int = 0
    actual_present: int = 0

    @property
    def formal_coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.formal_present / self.total) * 100.0

    @property
    def actual_coverage(self) -> float | None:
        if self.total == 0:
            return None

        return (self.actual_present / self.total) * 100.0


# ---------------------------------------------------------------------------
# Provenance quality
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceQuality:
    """Source provenance coverage for symbols."""

    total: int = 0
    source_file: int = 0
    node_id: int = 0
    offset: int = 0

    @property
    def source_file_coverage(self) -> float | None:
        return _coverage(self.source_file, self.total)

    @property
    def node_id_coverage(self) -> float | None:
        return _coverage(self.node_id, self.total)

    @property
    def offset_coverage(self) -> float | None:
        return _coverage(self.offset, self.total)


# ---------------------------------------------------------------------------
# Semantic type quality
# ---------------------------------------------------------------------------


@dataclass
class TypeQuality:
    """Quality information for semantic TypeInfo attached to symbols."""

    type_info: QualityMetric = field(
        default_factory=QualityMetric
    )

    width: QualityMetric = field(
        default_factory=QualityMetric
    )

    signed: QualityMetric = field(
        default_factory=QualityMetric
    )

    type_ref: QualityMetric = field(
        default_factory=QualityMetric
    )


# ---------------------------------------------------------------------------
# Symbol quality
# ---------------------------------------------------------------------------


@dataclass
class SymbolQuality:
    """Semantic metadata coverage for symbols."""

    total: int = 0

    datatype: QualityMetric = field(
        default_factory=QualityMetric
    )

    width: QualityMetric = field(
        default_factory=QualityMetric
    )

    direction: QualityMetric = field(
        default_factory=QualityMetric
    )

    value: QualityMetric = field(
        default_factory=QualityMetric
    )

    provenance: ProvenanceQuality = field(
        default_factory=ProvenanceQuality
    )


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


@dataclass
class SemanticQualityReport:
    """Complete semantic quality report."""

    modules: int = 0
    scopes: int = 0
    symbols: int = 0

    symbol_quality: SymbolQuality = field(
        default_factory=SymbolQuality
    )

    parameters: ParameterQuality = field(
        default_factory=ParameterQuality
    )

    ports: QualityMetric = field(
        default_factory=QualityMetric
    )

    signals: QualityMetric = field(
        default_factory=QualityMetric
    )

    signal_datatype: QualityMetric = field(
        default_factory=QualityMetric
    )

    signal_width: QualityMetric = field(
        default_factory=QualityMetric
    )

    port_datatype: QualityMetric = field(
        default_factory=QualityMetric
    )

    port_width: QualityMetric = field(
        default_factory=QualityMetric
    )

    port_direction: QualityMetric = field(
        default_factory=QualityMetric
    )

    port_type: TypeQuality = field(
        default_factory=TypeQuality
    )

    signal_type: TypeQuality = field(
        default_factory=TypeQuality
    )

    implicit_signals: int = 0
    explicit_signals: int = 0

    enums: EnumQuality = field(
        default_factory=EnumQuality
    )

    instances: InstanceQuality = field(
        default_factory=InstanceQuality
    )

    connections: ConnectionQuality = field(
        default_factory=ConnectionQuality
    )

    provenance: ProvenanceQuality = field(
        default_factory=ProvenanceQuality
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_quality(
    project: dict,
    ctx,
) -> SemanticQualityReport:
    """
    Analyze semantic information completeness.

    Parameters
    ----------
    project:
        Parsed RTL project IR.

    ctx:
        SemanticContext containing the current symbol table.

    Returns
    -------
    SemanticQualityReport
        Read-only quality report.

    Notes
    -----
    This function does not modify project or ctx.
    """

    if project is None:
        raise ValueError("project cannot be None")

    if ctx is None:
        raise ValueError("ctx cannot be None")

    report = SemanticQualityReport()

    # ------------------------------------------------------------------
    # Project / scope counts
    # ------------------------------------------------------------------

    report.modules = len(project)
    report.scopes = len(getattr(ctx, "scopes", {}))

    # ------------------------------------------------------------------
    # Symbol quality
    # ------------------------------------------------------------------

    for scope in getattr(ctx, "scopes", {}).values():
        for symbol in scope.symbols.values():
            _record_symbol_quality(report, symbol)

    # ------------------------------------------------------------------
    # Parser IR quality
    # ------------------------------------------------------------------

    for module in project.values():
        _record_module_quality(
            report,
            module,
            project,
        )

    return report


# ---------------------------------------------------------------------------
# Symbol analysis
# ---------------------------------------------------------------------------


def _record_symbol_quality(
    report: SemanticQualityReport,
    symbol,
) -> None:
    report.symbols += 1

    quality = report.symbol_quality

    quality.total += 1

    # Datatype
    quality.datatype.record(
        _has_value(symbol.datatype)
    )

    # Width
    quality.width.record(
        symbol.width is not None
    )

    # Direction
    quality.direction.record(
        _has_value(symbol.direction)
    )

    # Value
    quality.value.record(
        symbol.value is not None
    )

    # Provenance
    _record_provenance(
        quality.provenance,
        symbol.node,
    )

    # Semantic TypeInfo quality for ports/signals
    if symbol.kind == SymbolKind.PORT:
        _record_type_quality(
            report.port_type,
            symbol,
        )
    elif symbol.kind == SymbolKind.SIGNAL:
        _record_type_quality(
            report.signal_type,
            symbol,
        )

    # Parameter-specific information
    if symbol.kind in (
        SymbolKind.PARAMETER,
        SymbolKind.LOCALPARAM,
    ):
        report.parameters.record(
            symbol.value
        )


# ---------------------------------------------------------------------------
# Semantic type analysis
# ---------------------------------------------------------------------------


def _record_type_quality(
    quality: TypeQuality,
    symbol,
) -> None:
    """Measure TypeInfo completeness without inferring or mutating it."""

    type_info = getattr(symbol, "metadata", {}).get(
        "type_info"
    )

    quality.type_info.record(
        type_info is not None
    )

    if type_info is None:
        quality.width.record(False)
        quality.signed.record(False)
        quality.type_ref.record(False)
        return

    width = getattr(
        getattr(type_info, "width", None),
        "width",
        None,
    )

    quality.width.record(
        width is not None
    )

    quality.signed.record(
        getattr(type_info, "signed", None) is not None
    )

    quality.type_ref.record(
        _has_value(
            getattr(type_info, "type_ref", None)
        )
    )


# ---------------------------------------------------------------------------
# Module analysis
# ---------------------------------------------------------------------------


def _record_module_quality(
    report: SemanticQualityReport,
    module: dict,
    project: dict,
) -> None:

    # --------------------------------------------------------------
    # Ports
    # --------------------------------------------------------------

    interfaces = module.get(
        "interfaces",
        {},
    )

    for direction in (
        "inputs",
        "outputs",
        "inouts",
    ):
        for port in interfaces.get(
            direction,
            [],
        ):
            report.ports.record(True)

            report.port_direction.record(
                _has_value(direction)
            )

            report.port_datatype.record(
                _has_value(
                    port.get("datatype")
                )
            )

            report.port_width.record(
                port.get("width") is not None
            )

    # --------------------------------------------------------------
    # Signals
    # --------------------------------------------------------------

    for signal in module.get(
        "signals",
        [],
    ):
        report.signals.record(True)

        report.signal_datatype.record(
            _has_value(
                signal.get("type")
            )
        )

        report.signal_width.record(
            signal.get("width") is not None
        )

        if signal.get("implicit"):
            report.implicit_signals += 1
        else:
            report.explicit_signals += 1

    # --------------------------------------------------------------
    # Enums
    # --------------------------------------------------------------

    for enum in module.get(
        "enum_db",
        [],
    ):
        enum_type = enum.get("type")

        if enum_type not in (
            "typedef_enum",
            "inline_enum",
        ):
            continue

        report.enums.enum_types += 1

        members = enum.get(
            "members",
            {},
        )

        for member in members.values():
            report.enums.members += 1

            if member.get("value") is not None:
                report.enums.members_with_values += 1

    # --------------------------------------------------------------
    # Instances
    # --------------------------------------------------------------

    for instance in module.get(
        "instances",
        [],
    ):
        _record_instance_quality(
            report,
            instance,
            project,
        )


# ---------------------------------------------------------------------------
# Instance analysis
# ---------------------------------------------------------------------------


def _record_instance_quality(
    report: SemanticQualityReport,
    instance: dict,
    project: dict,
) -> None:

    report.instances.total += 1

    child_module_name = instance.get(
        "module"
    )

    if (
        _has_value(child_module_name)
        and child_module_name in project
    ):
        report.instances.module_known += 1

    instance_name = instance.get(
        "instance"
    )

    if not _has_value(instance_name):
        instance_name = instance.get(
            "name"
        )

    if _has_value(instance_name):
        report.instances.instance_name_known += 1

    connections = instance.get(
        "connections",
        [],
    )

    if connections:
        report.instances.connections_present += 1

    for connection in connections:
        _record_connection_quality(
            report,
            connection,
        )


# ---------------------------------------------------------------------------
# Connection analysis
# ---------------------------------------------------------------------------


def _record_connection_quality(
    report: SemanticQualityReport,
    connection: dict,
) -> None:

    report.connections.total += 1

    if _has_value(
        connection.get("port")
    ):
        report.connections.formal_present += 1

    if _has_value(
        connection.get("signal")
    ):
        report.connections.actual_present += 1


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _record_provenance(
    provenance: ProvenanceQuality,
    node: Any,
) -> None:

    provenance.total += 1

    if not isinstance(node, dict):
        return

    if _has_value(
        node.get("source_file")
    ):
        provenance.source_file += 1

    if node.get("node_id") is not None:
        provenance.node_id += 1

    if node.get("offset") is not None:
        provenance.offset += 1


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_quality_report(
    report: SemanticQualityReport,
) -> None:
    """Print a human-readable semantic quality report."""

    print()
    print("=" * 72)
    print("Semantic Quality Report")
    print("=" * 72)

    print()
    print("Project")
    print("-" * 72)
    print(f"{'Modules':35} {report.modules:8}")
    print(f"{'Scopes':35} {report.scopes:8}")
    print(f"{'Symbols':35} {report.symbols:8}")

    print()
    print("Symbol Information")
    print("-" * 72)

    _print_metric(
        "Datatype",
        report.symbol_quality.datatype,
    )

    _print_metric(
        "Width",
        report.symbol_quality.width,
    )

    _print_metric(
        "Direction",
        report.symbol_quality.direction,
    )

    _print_metric(
        "Value",
        report.symbol_quality.value,
    )

    print()
    print("Parameters")
    print("-" * 72)
    print(
        f"{'Total':35} "
        f"{report.parameters.total:8}"
    )
    print(
        f"{'With Value':35} "
        f"{report.parameters.with_value:8}"
    )
    print(
        f"{'Missing Value':35} "
        f"{report.parameters.missing_value:8}"
    )
    print(
        f"{'Literal Value':35} "
        f"{report.parameters.literal_value:8}"
    )
    print(
        f"{'Expression Value':35} "
        f"{report.parameters.expression_value:8}"
    )
    print(
        f"{'Value Coverage':35} "
        f"{('N/A' if report.parameters.value_coverage is None else f'{report.parameters.value_coverage:.2f}%'):>8}"
    )

    print()
    print("Ports")
    print("-" * 72)
    _print_metric(
        "Total",
        report.ports,
    )
    _print_metric(
        "Datatype",
        report.port_datatype,
    )
    _print_metric(
        "Width",
        report.port_width,
    )
    _print_metric(
        "Direction",
        report.port_direction,
    )

    print()
    print("Semantic Port Type")
    print("-" * 72)
    _print_type_quality(
        report.port_type,
    )

    print()
    print("Signals")
    print("-" * 72)
    _print_metric(
        "Total",
        report.signals,
    )
    _print_metric(
        "Datatype",
        report.signal_datatype,
    )
    _print_metric(
        "Width",
        report.signal_width,
    )
    print(
        f"{'Explicit':35} "
        f"{report.explicit_signals:8}"
    )
    print(
        f"{'Implicit':35} "
        f"{report.implicit_signals:8}"
    )

    print()
    print("Semantic Signal Type")
    print("-" * 72)
    _print_type_quality(
        report.signal_type,
    )

    print()
    print("Enums")
    print("-" * 72)
    print(
        f"{'Enum Types':35} "
        f"{report.enums.enum_types:8}"
    )
    print(
        f"{'Members':35} "
        f"{report.enums.members:8}"
    )
    print(
        f"{'Members With Values':35} "
        f"{report.enums.members_with_values:8}"
    )
    print(
        f"{'Value Coverage':35} "
        f"{('N/A' if report.enums.valued_member_coverage is None else f'{report.enums.valued_member_coverage:.2f}%'):>8}"
    )

    print()
    print("Instances")
    print("-" * 72)
    print(
        f"{'Total':35} "
        f"{report.instances.total:8}"
    )
    print(
        f"{'Child Module Known':35} "
        f"{report.instances.module_known:8}"
    )
    print(
        f"{'Child Module Unknown':35} "
        f"{report.instances.total - report.instances.module_known:8}"
    )
    print(
        f"{'Instance Name Known':35} "
        f"{report.instances.instance_name_known:8}"
    )
    print(
        f"{'Connections Present':35} "
        f"{report.instances.connections_present:8}"
    )
    print(
        f"{'Module Resolution':35} "
        f"{('N/A' if report.instances.module_resolution_coverage is None else f'{report.instances.module_resolution_coverage:.2f}%'):>8}"
    )

    print()
    print("Connections")
    print("-" * 72)
    print(
        f"{'Total':35} "
        f"{report.connections.total:8}"
    )
    print(
        f"{'Formal Present':35} "
        f"{report.connections.formal_present:8}"
    )
    print(
        f"{'Actual Present':35} "
        f"{report.connections.actual_present:8}"
    )
    print(
        f"{'Formal Coverage':35} "
        f"{('N/A' if report.connections.formal_coverage is None else f'{report.connections.formal_coverage:.2f}%'):>8}"
    )
    print(
        f"{'Actual Coverage':35} "
        f"{('N/A' if report.connections.actual_coverage is None else f'{report.connections.actual_coverage:.2f}%'):>8}"
    )

    print()
    print("Provenance")
    print("-" * 72)
    print(
        f"{'Symbols':35} "
        f"{report.provenance.total:8}"
    )
    print(
        f"{'Source File':35} "
        f"{report.provenance.source_file:8}"
    )
    print(
        f"{'Node ID':35} "
        f"{report.provenance.node_id:8}"
    )
    print(
        f"{'Offset':35} "
        f"{report.provenance.offset:8}"
    )


    source_file_coverage = (
        "N/A"
        if report.provenance.source_file_coverage is None
        else f"{report.provenance.source_file_coverage:.2f}%"
    )
    node_id_coverage = (
        "N/A"
        if report.provenance.node_id_coverage is None
        else f"{report.provenance.node_id_coverage:.2f}%"
    )
    offset_coverage = (
        "N/A"
        if report.provenance.offset_coverage is None
        else f"{report.provenance.offset_coverage:.2f}%"
    )

    print(
        f"{'Source File Coverage':35} "
        f"{source_file_coverage:>8}"
    )
    print(
        f"{'Node ID Coverage':35} "
        f"{node_id_coverage:>8}"
    )
    print(
        f"{'Offset Coverage':35} "
        f"{offset_coverage:>8}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_metric(
    name: str,
    metric: QualityMetric,
) -> None:
    print(
        f"{name + ' Total':35} "
        f"{metric.total:8}"
    )
    print(
        f"{name + ' Known':35} "
        f"{metric.known:8}"
    )
    print(
        f"{name + ' Unknown':35} "
        f"{metric.unknown:8}"
    )
    coverage = (
        "N/A"
        if metric.coverage is None
        else f"{metric.coverage:.2f}%"
    )

    print(
        f"{name + ' Coverage':35} "
        f"{coverage:>8}"
    )


def _print_type_quality(
    quality: TypeQuality,
) -> None:
    _print_metric(
        "TypeInfo",
        quality.type_info,
    )
    _print_metric(
        "Width",
        quality.width,
    )
    _print_metric(
        "Signed",
        quality.signed,
    )
    _print_metric(
        "Type Reference",
        quality.type_ref,
    )


def _coverage(
    known: int,
    total: int,
) -> float | None:
    if total == 0:
        return None

    return (known / total) * 100.0


def _has_value(value: Any) -> bool:
    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    return True


def _is_literal_value(value: Any) -> bool:
    """
    Determine whether a parameter value is already a literal.

    This is intentionally conservative.

    The function does not evaluate expressions. It only recognizes
    scalar literal representations already present in the IR.
    """

    if isinstance(value, (int, float, bool)):
        return True

    if not isinstance(value, str):
        return False

    value = value.strip()

    if not value:
        return False

    # Common Verilog/SystemVerilog literal forms:
    #
    #   0
    #   32
    #   '0
    #   '1
    #   4'd3
    #   8'hff
    #   16'b1010
    #
    # This deliberately does not attempt expression parsing.

    if value in (
        "'0",
        "'1",
    ):
        return True

    if value.isdigit():
        return True

    if "'" in value:
        return _looks_like_verilog_literal(value)

    return False


def _looks_like_verilog_literal(
    value: str,
) -> bool:
    """
    Conservative check for a Verilog numeric literal.

    Examples accepted:
        1'b0
        4'd3
        8'hff
        32'hFFFF_FFFF
    """

    if "'" not in value:
        return False

    size, literal = value.split(
        "'",
        1,
    )

    if size and not size.isdigit():
        return False

    literal = literal.lower()

    if literal.startswith(("s",)):
        literal = literal[1:]

    if not literal:
        return False

    if literal[0] not in (
        "b",
        "o",
        "d",
        "h",
    ):
        return False

    digits = literal[1:]

    if not digits:
        return False

    valid_digits = {
        "b": "01_xz",
        "o": "01234567_xz",
        "d": "0123456789_xz",
        "h": "0123456789abcdef_xz",
    }

    base = literal[0]

    return all(
        char in valid_digits[base]
        for char in digits
    )
