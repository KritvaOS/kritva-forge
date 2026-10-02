# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : module_parser.py
# Description : Module Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# --------------------------------------------------
# Module extraction
# --------------------------------------------------

def extract_module(
        module,
        rtl_path):

    #
    # Extract all module information first
    #
    parameters = extract_parameters(module,rtl_path)

    ports = extract_ports(module,rtl_path)

    signals = extract_signals(module,rtl_path)

    assigns = extract_assigns(module,rtl_path)

    always_blocks = extract_always_blocks(module,rtl_path)

    #case_statements = extract_case_statements_ast(module,rtl_path)

    instances = extract_instances(module,rtl_path)

    clocks, resets = extract_clock_reset(
        always_blocks
    )

    #
    # Build module_info BEFORE FSM extraction
    #
    module_info = {

        **node_info(module, rtl_path),

        "parameters": parameters,
        "signals": signals,
        "assigns": assigns,
        "always_blocks": always_blocks,
        "instances": instances,
        "name": str(module.header.name).strip(),
        "parser": "pyslang",
        "parser_version": "v1",
        "type": "module",
        "interfaces": ports,
        "clock_signals": sorted(clocks),
        "reset_signals": sorted(resets),
        "enum_db": extract_enum_database(module)
    }


    try:
        structural  = structural_fsm_analysis( module_info)
        module_info["structural"] = structural.to_dict()

    except Exception:

        print("\n[STRUCTURAL FAILED]")
        print("Module :", module_info["name"])
        traceback.print_exc()
        raise


    #
    # FSM extraction
    #
    try:
        fsm = extract_fsm_ast(
            module,
            module_info
        )
    except Exception:

        print("\n[FSM FAILED]")
        print("Module :", module_info["name"])
        traceback.print_exc()
        raise

    module_info["fsm"] = fsm


    return module_info
