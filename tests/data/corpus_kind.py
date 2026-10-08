# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : corpus_kind.py
# Description : Private-corpus-only marker for corpus tests (KF-DQ-012.2)
#
# Component   : Kritva Forge
# Module      : tests/data
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Corpus tests that assert private kritva-forge-data constants skip on the
open-source reference corpus (KF-DQ-012.2 AC-031).

A reference root is identified only by the explicit marker
``<data root>/../CORPUS_KIND`` containing ``reference``, written by
``scripts/reference/materialize.py``.
"""

import os

import pytest

from scripts.reference.materialize import is_reference_root

DATA_ROOT = os.environ.get("KRITVA_FORGE_DATA_ROOT")
REFERENCE = bool(DATA_ROOT) and is_reference_root(DATA_ROOT)

private_corpus_only = pytest.mark.skipif(
    REFERENCE, reason="asserts a private kritva-forge-data constant; DATA_ROOT is the open-source reference corpus")
