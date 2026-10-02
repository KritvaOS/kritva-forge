#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : test_source_headers.py
# Description : Unit tests for the Kritva Forge source header checker
#
# Component   : Kritva Forge
# Module      : tests/lint
# Layer       : Test
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CHECKER=ROOT/'scripts/lint/check_source_headers.py'
spec=importlib.util.spec_from_file_location('check_source_headers',CHECKER);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def test_parser():assert not mod.validate(ROOT/'scripts/parser/rtl_parser_slang.py',ROOT)
def test_checker():assert not mod.validate(CHECKER,ROOT)
if __name__=='__main__':test_parser();test_checker();print('2 header tests passed')
