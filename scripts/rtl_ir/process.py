# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : process.py
# Description : Process implementation
#
# Component   : Kritva Forge
# Module      : rtl_ir
# Layer       : RTL IR
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
def new_process(
        process_type,
        body,
        sensitivity=None,
        clock=None,
        reset=None,
        **kwargs):

    return {

        "process_type": process_type,

        "body": body,

        "clock": clock,

        "reset": reset,

        "sensitivity": sensitivity or [],

        "children": [
            body
        ],

        **kwargs
    }


