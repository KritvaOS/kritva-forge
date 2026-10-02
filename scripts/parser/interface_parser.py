# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : interface_parser.py
# Description : Interface Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# --------------------------------------------------
# PORT EXTRACTION
# --------------------------------------------------
def extract_ports(module,rtl_path):

    interfaces = {
        "inputs": [],
        "outputs": [],
        "inouts": []
    }

    portlist = module.header.ports

    if portlist is None:
        return interfaces

    for p in portlist.ports:

        if type(p).__name__ != "ImplicitAnsiPortSyntax":
            continue

        name = str(p.declarator).strip()

        direction = str(
            p.header.direction.kind
        )

        entry = {
            **node_info(p,rtl_path),
            "name": name
        }

        dtype = getattr(
            p.header,
            "dataType",
            None
        )

        if dtype:
            dtype_str = str(
                dtype
            ).strip()

            #
            # Filter invalid widths
            #
            if "[-1:0]" in dtype_str:

                dtype_str = ""

            if dtype_str:

                entry["datatype"] = (
                    dtype_str
                )


        if "InputKeyword" in direction:
            interfaces["inputs"].append(entry)

        elif "OutputKeyword" in direction:
            interfaces["outputs"].append(entry)

        elif "InOutKeyword" in direction:
            interfaces["inouts"].append(entry)

    return interfaces
