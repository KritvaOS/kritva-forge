# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : paths.py
# Description : Shared paths for the public Forge repository and private data repository
#
# Component   : Kritva Forge
# Module      : core
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# -----------------------------------------------------------------------------
# Canonical normalized IR layout (KF-DQ-001)
#
#   normalized/ir/
#     <ip>/
#       hierarchy.yaml        IP-level metadata
#       summary.yaml          IP-level metadata
#       modules/
#         <module>.yaml       the ONLY canonical module representation
#       rtl/                  RTL copies (location decision deferred to KF-DQ-006)
#
# Any other ``*.yaml`` directly under ``<ip>/`` is non-canonical and must not
# be consumed.  Always enumerate module IR through ``iter_module_yamls()``.
# -----------------------------------------------------------------------------

MODULES_DIRNAME = "modules"
IP_METADATA_FILES = ("hierarchy.yaml", "summary.yaml")


def iter_ip_dirs(normalized_root: str | os.PathLike[str]) -> Iterator[Path]:
    """Yield canonical IP directories (those containing ``modules/``), sorted."""
    root = Path(normalized_root)
    if not root.is_dir():
        return
    for ip_dir in sorted(root.iterdir()):
        if ip_dir.name.startswith("."):
            continue
        if (ip_dir / MODULES_DIRNAME).is_dir():
            yield ip_dir


def iter_module_yamls(
    normalized_root: str | os.PathLike[str],
    ip: str | None = None,
) -> Iterator[Path]:
    """Yield canonical module YAMLs ``<root>/<ip>/modules/<module>.yaml``, sorted.

    Root-level ``<ip>/<module>.yaml`` files, ``hierarchy.yaml`` and
    ``summary.yaml`` are never returned.
    """
    root = Path(normalized_root)
    ip_dirs = [root / ip] if ip else iter_ip_dirs(root)
    for ip_dir in ip_dirs:
        modules_dir = ip_dir / MODULES_DIRNAME
        if not modules_dir.is_dir():
            continue
        for path in sorted(modules_dir.iterdir()):
            if path.is_file() and path.suffix == ".yaml":
                yield path


def find_noncanonical_module_yamls(
    normalized_root: str | os.PathLike[str],
) -> list[Path]:
    """Return YAMLs directly under ``<ip>/`` that are not IP metadata.

    A non-empty result means a duplicate/stale module representation exists.
    """
    root = Path(normalized_root)
    if not root.is_dir():
        return []
    found = []
    for ip_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(ip_dir.glob("*.yaml")):
            if path.name not in IP_METADATA_FILES:
                found.append(path)
    return found


@dataclass(frozen=True)
class ForgeDataPaths:
    """Canonical layout for the external Kritva Forge data repository."""

    root: Path

    @classmethod
    def from_root(cls, root: str | os.PathLike[str]) -> "ForgeDataPaths":
        return cls(Path(root).expanduser().resolve())

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def raw_rtl(self) -> Path:
        return self.raw / "rtl"

    @property
    def normalized(self) -> Path:
        return self.root / "normalized"

    @property
    def normalized_ir(self) -> Path:
        return self.normalized / "ir"

    def module_dir(self, ip: str) -> Path:
        return self.normalized_ir / ip / MODULES_DIRNAME

    def module_yaml(self, ip: str, module: str) -> Path:
        return self.module_dir(ip) / f"{module}.yaml"

    def iter_module_yamls(self, ip: str | None = None) -> Iterator[Path]:
        return iter_module_yamls(self.normalized_ir, ip)

    @property
    def analysis(self) -> Path:
        return self.root / "analysis"

    @property
    def reports(self) -> Path:
        return self.analysis / "reports"

    @property
    def generated(self) -> Path:
        return self.root / "generated"

    @property
    def prompts(self) -> Path:
        return self.generated / "prompts"

    @property
    def metadata(self) -> Path:
        return self.generated / "metadata"

    @property
    def statistics(self) -> Path:
        return self.generated / "statistics"

    @property
    def golden(self) -> Path:
        return self.root / "golden"

    @property
    def datasets(self) -> Path:
        return self.root / "datasets"

    @property
    def pipeline_datasets(self) -> Path:
        return self.datasets / "pipeline"

    @property
    def source_datasets(self) -> Path:
        return self.datasets / "source"

    @property
    def splits(self) -> Path:
        return self.root / "splits"

    @property
    def manifests(self) -> Path:
        return self.root / "manifests"

    def ensure_outputs(self) -> None:
        for path in (
            self.normalized_ir,
            self.reports,
            self.prompts,
            self.metadata,
            self.statistics,
            self.pipeline_datasets,
        ):
            path.mkdir(parents=True, exist_ok=True)


def default_data_root() -> Path:
    """Return the sibling private data repository used by local development."""
    configured = os.environ.get("KRITVA_FORGE_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "kritva-forge-data").resolve()


def default_normalized_root() -> Path:
    """Return ``<data-root>/normalized/ir`` for the default data repository."""
    return ForgeDataPaths.from_root(default_data_root()).normalized_ir


def normalized_root_from_argv(argv: list[str] | None = None) -> Path:
    """Resolve the normalized IR root for simple CLI report scripts.

    ``argv[1]`` overrides the default ``<data-root>/normalized/ir``.
    """
    import sys

    argv = sys.argv if argv is None else argv
    if len(argv) > 1 and argv[1]:
        return Path(argv[1]).expanduser().resolve()
    return default_normalized_root()


# -----------------------------------------------------------------------------
# Portable provenance paths (KF-DQ-002)
#
# Persisted provenance (``source_file`` and every nested equivalent) is always
# a POSIX path relative to the data-repository root, e.g.
#
#     raw/rtl/original/common/pulse_gen_type2.sv
#
# Absolute host paths are runtime-only and are never written to artifacts.
# -----------------------------------------------------------------------------

RAW_RTL_PARTS = ("raw", "rtl")

# Absolute host-path roots that must never appear in persisted artifacts.
FORBIDDEN_ABSOLUTE_ROOTS = ("home", "tmp", "mnt", "Users", "workspace")

# An absolute path begins at the start of a line/string or after whitespace,
# a quote, or a YAML/JSON/assignment delimiter.  A relative path that merely
# contains ``/tmp/`` (e.g. ``raw/rtl/original/tmp/x.v``) does not match.
ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|(?<=[\s\"'=:(\[,]))/(?:"
    + "|".join(FORBIDDEN_ABSOLUTE_ROOTS)
    + r")/",
    re.MULTILINE,
)


def infer_data_root(path: str | os.PathLike[str]) -> Path | None:
    """Return the data-repository root containing ``path``, if any.

    The data root is the nearest ancestor (or ``path`` itself) that contains a
    ``raw/rtl/`` directory.  Works for RTL inputs
    (``<root>/raw/rtl/original/<ip>``) and outputs
    (``<root>/normalized/ir/<ip>``).  Independent of the current directory.
    """
    current = Path(path).expanduser().resolve()
    for candidate in (current, *current.parents):
        if candidate.joinpath(*RAW_RTL_PARTS).is_dir():
            return candidate
    return None


def to_provenance_path(
    path: str | os.PathLike[str],
    data_root: str | os.PathLike[str],
) -> str:
    """Convert a runtime RTL path into portable persisted provenance.

    Returns a POSIX path relative to ``data_root``.  Raises ``ValueError`` if
    ``path`` lies outside ``data_root`` (an absolute path must never be
    persisted as a fallback).
    """
    root = Path(data_root).expanduser().resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"RTL path {target} is outside the data root {root}; "
            "cannot record portable provenance"
        ) from exc
    return relative.as_posix()


def resolve_provenance_path(
    provenance: str | os.PathLike[str],
    data_root: str | os.PathLike[str] | None,
) -> Path:
    """Resolve persisted provenance back to a runtime filesystem path.

    Legacy absolute provenance is returned unchanged.
    """
    candidate = Path(provenance)
    if candidate.is_absolute():
        return candidate
    if data_root is None:
        raise ValueError(
            f"relative provenance {provenance!r} needs a data root to resolve"
        )
    return Path(data_root).expanduser().resolve() / candidate


def find_absolute_paths(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, line)`` for lines containing a forbidden absolute path."""
    return [
        (line_no, line)
        for line_no, line in enumerate(text.splitlines(), start=1)
        if ABSOLUTE_PATH_RE.search(line)
    ]


def scan_absolute_paths(
    roots: list[str | os.PathLike[str]],
    suffixes: tuple[str, ...] = (".yaml", ".yml", ".json", ".jsonl", ".txt"),
) -> list[tuple[Path, int, str]]:
    """Scan artifact trees for forbidden absolute host paths.

    Returns ``(file, line_number, line)`` for every offending line.
    Non-existent roots are skipped.
    """
    findings = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if not path.is_file() or path.suffix not in suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in find_absolute_paths(text):
                findings.append((path, line_no, line))
    return findings
