# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : parameter_parser.py
# Description : Parameter Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# --------------------------------------------------
# PARAMETER EXTRACTION
# --------------------------------------------------

def extract_parameters(module,rtl_path):

    parameters = []

    try:

        param_port_list = getattr(
            module.header,
            "parameters",
            None
        )

        if param_port_list is None:
            return parameters

        raw = str(
            param_port_list
        )

        pattern = (
            r'parameter\s+'
            r'(?:[\w\[\]:]+\s+)*'
            r'(\w+)'
            r'\s*=\s*'
            r'([^,\n\)]+)'
        )
        for match in re.finditer(
                pattern,
                raw):

            parameters.append({

                **node_info(param_port_list, rtl_path),

                "name":
                    match.group(1),

                "default":
                    normalize_param_value(
                        match.group(2)
                    )
            })

    except Exception:
        pass

    return parameters

# --------------------------------------------------
# Enum subroutine
# --------------------------------------------------
def derive_parameter_group(name):

    name = str(name)

    #
    # mdio_idle_st
    #
    m = re.match(
        r'(.+?)_[^_]+_st$',
        name,
        re.I
    )

    if m:
        return m.group(1)

    #
    # YCR_IFU_FSM_IDLE
    #
    m = re.match(
        r'(.+?_FSM_)',
        name,
        re.I
    )

    if m:
        return m.group(1)

    #
    # WAIT_REQ
    #
    return None



def extract_parameter_encoding_ast(node):
    """
    Extract FSM state encodings from parameter/localparam declarations.

    Returns:
        [
            {
                "type": "parameter" | "localparam",
                "group": "YCR_IFU_FSM",
                "width": "[1:0]",
                "members": {
                    "YCR_IFU_FSM_IDLE": {
                        "raw": "2'd0",
                        "value": 0
                    },
                    ...
                }
            }
        ]
    """

    #
    # Determine parameter/localparam
    #
    try:
        raw = str(node).lower().strip()
    except Exception:
        raw = ""

    kind = "localparam" if raw.startswith("localparam") else "parameter"

    #
    # Get declarators
    #
    try:
        declarators = node.declarators
    except Exception:
        return []

    #
    # Collect all parameter members
    #
    members = {}

    for decl in declarators:

        #
        # Parameter name
        #
        try:
            name = str(decl.name).strip()
        except Exception:
            continue

        #
        # Initial value expression
        #
        expr = getattr(decl, "initializer", None)

        value = evaluate_constant_expression(expr)

        members[name] = {

            "raw":
                None if expr is None else str(expr),

            "value":
                value
        }

    if not members:
        return []

    #
    # ----------------------------------------------------
    # Group parameters by FSM prefix
    # ----------------------------------------------------
    #
    groups = {}

    for name, info in members.items():

        group = derive_parameter_group(name)

        #
        # Ignore non-FSM parameters
        #
        if group is None:
            continue

        groups.setdefault(group, {})

        groups[group][name] = info

    #
    # Build enum database
    #
    enum_db = []

    for group_name, group_members in groups.items():

        #
        # Ignore groups containing only one parameter
        #
        if len(group_members) < 2:
            continue

        enum_db.append({

            "type": kind,

            "group": group_name,

            "width":
                infer_width_from_values(
                    group_members
                ),

            "members":
                group_members
        })

    return enum_db
