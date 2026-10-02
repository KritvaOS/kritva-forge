# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : debug.py
# Description : Debug implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
"""
Parser debugging options.
"""

DEBUG = False

#
# High-level traversal
#
DEBUG_STATEMENT = True
DEBUG_EXPRESSION = True
DEBUG_PROCESS = False

#
# AST inspection
#
DEBUG_AST = True
DEBUG_AST_ONCE = True

#
# IR generation
#
DEBUG_ASSIGNMENT = False
DEBUG_BINARY = False
DEBUG_CONDITIONAL = False
DEBUG_CASE = False

#
# Statistics
#
DEBUG_SUMMARY = True


def debug_statement(*args):
    if DEBUG_STATEMENT:
        print(*args)


def debug_expression(*args):
    if DEBUG_EXPRESSION:
        print(*args)


def debug_assignment(*args):
    if DEBUG_ASSIGNMENT:
        print(*args)


def debug_ast(*args):
    if DEBUG_AST:
        print(*args)
