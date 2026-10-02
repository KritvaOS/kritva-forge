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
from dataclasses import dataclass
from pathlib import Path


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
