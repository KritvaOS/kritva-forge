# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : __init__.py
# Description : Behavioral Semantics v1 package (KF-DQ-009)
#
# Component   : Kritva Forge
# Module      : behavior
# Layer       : Semantic Analysis
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""Behavioral Semantics v1 (KF-DQ-009).

``model``      schema name/version, enumerations, identity helpers
``analyzer``   Semantic IR v2 documents -> Behavioral Semantics v1 documents
``validator``  fail-closed schema / reference / consistency validation and CLI

The analyzer consumes only persisted Semantic IR v2 JSON
(``normalized/semantic_ir/v2``); it never parses RTL.
"""
