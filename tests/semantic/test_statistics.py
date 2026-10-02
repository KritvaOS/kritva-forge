# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_statistics.py
# Description : Test Statistics implementation
#
# Component   : Kritva Forge
# Module      : tests/semantic
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
from scripts.semantic.statistics import SemanticStatistics
import pytest


def test_record_reference_resolved():
    stats = SemanticStatistics()

    stats.record_reference(True)

    assert stats.references == 1
    assert stats.resolved_references == 1
    assert stats.unresolved_references == 0


def test_record_reference_unresolved():
    stats = SemanticStatistics()

    stats.record_reference(False)

    assert stats.references == 1
    assert stats.resolved_references == 0
    assert stats.unresolved_references == 1


def test_resolution_rate():
    stats = SemanticStatistics()

    stats.record_reference(True)
    stats.record_reference(True)
    stats.record_reference(False)

    assert stats.references == 3
    assert stats.resolved_references == 2
    assert stats.unresolved_references == 1
    assert stats.resolution_rate == pytest.approx(66.66666666666666)


def test_resolution_rate_with_no_references():
    stats = SemanticStatistics()

    assert stats.resolution_rate == 100.0
