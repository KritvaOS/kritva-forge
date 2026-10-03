#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : rtl_parser_slang.py
# Description : Rtl Parser Slang implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#--------------------------------------------
#   
#
#    Parses SystemVerilog
#    Handles files.f
#    Handles common RTL dependencies
#    Detects top modules
#    Captures source_file

#   rtl_parser_slang.py
#   ├── walk_syntax()
#   ├── extract_parameters()
#   ├── extract_ports()
#   ├── extract_signals()
#   ├── extract_instances()
#   ├── extract_assigns()
#   ├── extract_processes()
#   
#   ├── extract_case_statements_ast()
#   ├── extract_fsm_ast()
#   ├── extract_functions_ast()
#   ├── extract_tasks_ast()
#   ├── extract_generate_ast()
#   
#-------------------------------------
# V1 version support added
#------------------------------------
#  [
#      {
#          "instance": "baud",
#          "module": "uart_baudrate",
#          "connections": [
#              {
#                  "port": "clk",
#                  "signal": "clk"
#              },
#              {
#                  "port": "rst",
#                  "signal": "rst"
#              },
#              {
#                  "port": "baud_divisor",
#                  "signal": "baud_div"
#              },
#              {
#                  "port": "baud_tick",
#                  "signal": "baud_tick"
#              }
#          ]
#      }
#  ]

#--------------------------------------
# Pending V2 Version
#--------------------------------------
#   AlwaysBlockSyntax
#   CaseStatementSyntax
#   ConditionalStatementSyntax
#   ProceduralBlockSyntax
#   GenerateBlockSyntax
# ------------------------------------
#  
#                  PySlang AST
#                       │
#           ┌───────────┴───────────┐
#           ▼                       ▼
#  Expression Parser         Statement Parser
#           │                       │
#           ▼                       ▼
#   Expression IR             Statement IR
#           │                       │
#           └───────────┬───────────┘
#                       ▼
#                 Process Parser
#                       │
#                       ▼
#                   Process IR
#                       │
#                       ▼
#                    Module IR
#                       │
#                       ▼
#               Analysis Framework
#          ┌─────────┼─────────┐
#          ▼         ▼         ▼
#     Symbol DB   FSM Graph   FSM Selector
#
# ---------------------------------------------  

import os
import glob
import re
from pyslang.syntax import SyntaxKind
from scripts.semantic_ir.extractor import ModuleExtractor
from pyslang.syntax import SyntaxTree
from scripts.fsm.fsm_extractor import extract_fsm_ast
from scripts.structural.fsm_structural import structural_fsm_analysis
from scripts.parser.ast_utils import walk_ast,derive_parameter_group,evaluate_constant_expression,infer_width_from_values,discover_typedef_enum,discover_inline_enum,dump_node_info,dump_node,dump_expression_info

from pyslang import SourceManager

from scripts.core.identity import SourceIdentity, node_identity
from scripts.core.paths import infer_data_root, to_provenance_path

from scripts.parser.expression_parser import (
    parse_expression,
    parse_identifier,
    parse_literal,
)

from scripts.parser.process_parser import parse_process

from scripts.rtl_ir.statement_utils import (
    collect_assignments,
    collect_case_statements,
)

import networkx as nx
import traceback


KEEP_COMMENTS = False
DEBUG_FSM = False


# -------------------------------------
#
# -------------------------------------

def extract_implicit_signals(module, rtl_path):
    signals = []

    for member in module.members:
        if type(member).__name__ != "ContinuousAssignSyntax":
            continue

        for assignment in member.assignments:
            left = getattr(assignment, "left", None)

            if left is None:
                continue

            if type(left).__name__ != "IdentifierNameSyntax":
                continue

            identifier = getattr(left, "identifier", None)

            if identifier is None:
                continue

            name = identifier.value

            if not name:
                continue

            signals.append({
                **node_info(member, rtl_path),
                "name": name,
                "type": "implicit_net",
                "implicit": True,
            })

    return signals


# --------------------------------------------------
# Stable node identity (KF-DQ-003)
#
# node_id and buffer are content-derived and portable; see
# scripts/core/identity.py for the documented, versioned identity model.
# The active SourceIdentity is installed by parse_file() for the duration of
# one file's extraction.
# --------------------------------------------------

_SOURCE_IDENTITY = None


def _set_source_identity(source_identity):
    global _SOURCE_IDENTITY
    previous = _SOURCE_IDENTITY
    _SOURCE_IDENTITY = source_identity
    return previous


def get_source_location(node):

    try:

        loc = node.sourceRange.start

        if _SOURCE_IDENTITY is not None:
            buffer = _SOURCE_IDENTITY.buffer_file(loc)
        else:
            buffer = ""

        return {
            "offset": getattr(loc, "offset", -1),
            "buffer": buffer
        }

    except Exception:

        return {
            "offset": -1,
            "buffer": ""
        }


def stable_node_id(node, rtl_path):
    """Deterministic content identity of ``node`` (KF-DQ-003)."""

    if _SOURCE_IDENTITY is None:
        start_key = end_key = ""
        try:
            start_key = str(node.sourceRange.start.offset)
            end_key = str(node.sourceRange.end.offset)
        except Exception:
            pass
    else:
        try:
            source_range = node.sourceRange
            start_key = _SOURCE_IDENTITY.location_key(source_range.start)
            end_key = _SOURCE_IDENTITY.location_key(source_range.end)
        except Exception:
            start_key = end_key = ""

    return node_identity(
        str(rtl_path),
        type(node).__name__,
        start_key,
        end_key,
    )


def node_info(node, rtl_path):

    if node is None:
        return {
            "node_id": None,
            "syntax_type": type(node).__name__ ,
            "source_file": rtl_path,
            "line": 0,
            "column": 0
        }


    info = {

        "node_id": stable_node_id(node, rtl_path),
        "syntax_type": type(node).__name__ ,
        "source_file": rtl_path,

         **get_source_location(node)

    }

    return info

# ------------------------------------------
#
# ------------------------------------------
def extract_typedef_enum_ast(node):
    """
    Extract a typedef enum directly from the PySlang AST.

    PySlang represents:

        typedef enum logic [W-1:0] {
            STATE_A,
            STATE_B = 3,
            STATE_C
        } state_t;

    as:

        TypedefDeclarationSyntax
            └── type: EnumTypeSyntax
                    └── members: DeclaratorSyntax / comma tokens

    Using EnumTypeSyntax.members avoids the incomplete enum-member
    discovery currently observed through discover_typedef_enum().
    """

    enum_type = getattr(node, "type", None)

    if enum_type is None:
        return None

    if type(enum_type).__name__ != "EnumTypeSyntax":
        return None

    # Typedef name: "} state_t;"
    name_node = getattr(node, "name", None)

    if name_node is None:
        return None

    name = getattr(name_node, "value", None)

    if not name:
        name = str(name_node).strip()

    name = str(name).strip()

    if not name:
        return None

    # Preserve the existing enum database format.
    enum_info = {
        "name": name,
        "width": "",
        "members": [],
    }

    # Extract packed width from the enum type.
    #
    # Example:
    #   enum logic [YCR_IALU_CMD_WIDTH_E-1:0] {
    #
    enum_text = str(enum_type)

    width_match = re.search(
        r"\[([^\]]+)\]",
        enum_text,
    )

    if width_match:
        enum_info["width"] = (
            "[" + width_match.group(1).strip() + "]"
        )

    # Enum members are DeclaratorSyntax nodes interleaved
    # with comma Token nodes.
    for member in getattr(enum_type, "members", []):

        if type(member).__name__ != "DeclaratorSyntax":
            continue

        member_name_node = getattr(
            member,
            "name",
            None,
        )

        if member_name_node is None:
            continue

        member_name = getattr(
            member_name_node,
            "value",
            None,
        )

        if not member_name:
            member_name = str(
                member_name_node
            ).strip()

        member_name = str(member_name).strip()

        if not member_name:
            continue

        initializer = getattr(
            member,
            "initializer",
            None,
        )

        expr = None

        if initializer is not None:

            expr_node = getattr(
                initializer,
                "expr",
                None,
            )

            if expr_node is not None:
                expr = str(expr_node).strip()

        enum_info["members"].append({
            "name": member_name,
            "expr": expr,
        })

    if not enum_info["members"]:
        return None

    return build_enum_entry(enum_info)


def build_enum_entry(info):

    enum = {

        "type": "typedef_enum",

        "name": info["name"],

        "width_expr": info.get("width", ""),

        "members": {}
    }

    next_value = 0

    for m in info["members"]:

        name = m["name"]

        if m["expr"] is None:

            value = next_value

        else:

            value = evaluate_constant_expression(
                m["expr"]
            )

        enum["members"][name] = {

            "raw": None if m["expr"] is None else str(m["expr"]),

            "value": value
        }

        #
        # advance only when integer
        #
        if isinstance(value, int):

            next_value = value + 1

        else:

            next_value += 1

    return enum


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


def extract_inline_enum_ast(node):

    info = discover_inline_enum(node)

    if not info:
        return None

    enum = build_enum_entry(info)

    enum["type"] = "inline_enum"

    return enum

def extract_enum_database(module):

    db = []

    for member in getattr(module, "members", []):

        typ = type(member).__name__

        if is_typedef_enum(typ):

            info = extract_typedef_enum_ast(member)

        elif is_parameter_decl(typ):

            info = extract_parameter_encoding_ast(member)

        elif is_inline_enum(typ): 

            info = extract_inline_enum_ast(member)

        else:

            continue

        if not info:
            continue

        #
        # parameter/localparam can return multiple groups
        #
        if isinstance(info, list):

            db.extend(info)

        else:

            db.append(info)


    return db


def extract_compilation_declarations(tree):
    """
    Extract semantic declarations from the compilation-unit AST.

    These declarations are obtained from the same PySlang AST that parsed
    the RTL source, so SystemVerilog include / conditional-preprocessing
    state has already been applied.

    Returns
    -------
    list[dict]
        Compilation-unit declarations:

        {
            "kind": "parameter" | "localparam",
            "name": "...",
            "default": "..."
        }

        or:

        {
            "kind": "enum",
            "enum": {...}
        }

    Notes
    -----
    Only declarations directly present in tree.root.members are considered.
    Module-local declarations are handled separately by the existing
    Module IR extraction.
    """

    declarations = []

    for member in getattr(tree.root, "members", []):

        member_type = type(member).__name__

        # --------------------------------------------------
        # Compilation-unit parameter / localparam
        # --------------------------------------------------

        if member_type == "ParameterDeclarationStatementSyntax":

            parameter = getattr(
                member,
                "parameter",
                None,
            )

            if parameter is None:
                continue

            raw = str(parameter).strip()

            if re.search(r"\blocalparam\b", raw):
                kind = "localparam"
            elif re.search(r"\bparameter\b", raw):
                kind = "parameter"
            else:
                continue

            for declarator in getattr(
                parameter,
                "declarators",
                [],
            ):

                name_node = getattr(
                    declarator,
                    "name",
                    None,
                )

                if name_node is None:
                    continue

                name = getattr(
                    name_node,
                    "value",
                    None,
                )

                if not name:
                    continue

                initializer = getattr(
                    declarator,
                    "initializer",
                    None,
                )

                expr = None

                if initializer is not None:
                    expr_node = getattr(
                        initializer,
                        "expr",
                        None,
                    )

                    if expr_node is not None:
                        expr = str(expr_node).strip()

                declarations.append({
                    "kind": kind,
                    "name": str(name).strip(),
                    "default": expr,
                })

            continue

        # --------------------------------------------------
        # Compilation-unit typedef enum
        # --------------------------------------------------

        if member_type == "TypedefDeclarationSyntax":

            enum = extract_typedef_enum_ast(member)

            if enum is None:
                continue

            declarations.append({
                "kind": "enum",
                "enum": enum,
            })

    return declarations

# ------------------------------------------
#
# ------------------------------------------
#def extract_enum_database(module,rtl_path):
#    """
#    Build a reusable symbolic-state database.
#
#    Returns
#    -------
#    [
#        {
#            "type":"typedef_enum",
#            "name":"state_t",
#            "width":"[2:0]",
#            "members":{
#                "IDLE":"0",
#                "WAIT":"1"
#            }
#        },
#
#        {
#            "type":"localparam",
#            "members":{
#                "IDLE":"3'b000"
#            }
#        }
#
#    ]
#    """
#
#    enum_db = []
#
#    #
#    # ----------------------------------------
#    # Walk every module member
#    # ----------------------------------------
#    #
#
#    for member in module.members:
#
#        raw = str(member)
#
#        #
#        # ----------------------------------------
#        # typedef enum
#        # ----------------------------------------
#        #
#
#        if "typedef enum" in raw:
#
#            entry = {
#
#                **node_info(member,rtl_path),
#
#                "type":
#                    "typedef_enum",
#
#                "name":
#                    "",
#
#                "width":
#                    "",
#
#                "members":
#                    {}
#            }
#
#            #
#            # typedef enum logic [2:0]
#            #
#
#            m = re.search(
#
#                r'typedef\s+enum'
#                r'(?:\s+\w+)?'
#                r'\s*(\[[^\]]+\])?',
#
#                raw,
#
#                flags=re.S
#            )
#
#            if m:
#
#                entry["width"] = (
#                    m.group(1) or ""
#                )
#
#            #
#            # typedef name
#            #
#
#            m = re.search(
#
#                r'}\s*(\w+)\s*;',
#
#                raw
#
#            )
#
#            if m:
#
#                entry["name"] = m.group(1)
#
#            #
#            # body
#            #
#
#            body = re.search(
#
#                r'{(.*?)}',
#
#                raw,
#
#                flags=re.S
#
#            )
#
#            if body:
#
#                items = body.group(1)
#
#                value = 0
#
#                for item in items.split(","):
#
#                    item = item.strip()
#
#                    if not item:
#                        continue
#
#                    if "=" in item:
#
#                        name, val = item.split("=", 1)
#
#                        name = name.strip()
#
#                        val = val.strip()
#
#                        entry["members"][name] = val
#
#                        #
#                        # update auto counter if integer
#                        #
#
#                        try:
#
#                            value = int(val, 0) + 1
#
#                        except Exception:
#
#                            pass
#
#                    else:
#
#                        entry["members"][item] = str(value)
#
#                        value += 1
#
#            enum_db.append(entry)
#
#            continue
#
#        #
#        # ----------------------------------------
#        # localparam
#        # ----------------------------------------
#        #
#
#        if raw.strip().startswith("localparam"):
#
#            members = {}
#
#            for m in re.finditer(
#
#                r'(\w+)\s*=\s*([^,;]+)',
#
#                raw
#
#            ):
#
#                members[
#                    m.group(1)
#                ] = m.group(2).strip()
#
#            if members:
#
#                enum_db.append({
#                
#                    **node_info(member,rtl_path),
#
#                    "type":
#                        "localparam",
#
#                    "members":
#                        members
#                })
#
#            continue
#
#        #
#        # ----------------------------------------
#        # parameter
#        # ----------------------------------------
#        #
#
#        if raw.strip().startswith("parameter"):
#
#            members = {}
#
#            for m in re.finditer(
#
#                r'(\w+)\s*=\s*([^,;]+)',
#
#                raw
#
#            ):
#
#                members[
#                    m.group(1)
#                ] = m.group(2).strip()
#
#            if members:
#
#                enum_db.append({
#                    **node_info(member,rtl_path),
#
#                    "type":
#                        "parameter",
#
#                    "members":
#                        members
#                })
#
#    return enum_db

#--------------------------------------------------
# Heleter : normalize the parameter
#-------------------------------------------------

def normalize_param_value(v):

    v = v.strip()

    #
    # Remove comments
    #
    if "//" in v:
        v = v.split("//", 1)[0].strip()

    if "/*" in v:
        v = v.split("/*", 1)[0].strip()

    #
    # Remove trailing parameter-list close
    #
    #while v.endswith(")"):
    #    v = v[:-1].rstrip()

    return v

#--------------------------------------------------
# Heleter : normalize the width
#-------------------------------------------------

def normalize_width(width):

    width = width.strip()

    width = " ".join(
        width.split()
    )

    width = width.replace(
        " :",
        ":"
    )

    width = width.replace(
        ": ",
        ":"
    )

    return width

# --------------------------------------------------
# FILE DISCOVERY
# --------------------------------------------------

def collect_filelist_info(ip_dir):
    """
    Read files.f and collect:
      - RTL source files
      - +incdir+ include directories

    Paths in files.f are resolved relative to the
    directory containing files.f.
    """

    filelist = os.path.join(ip_dir, "files.f")

    if os.path.isfile(filelist):
        files = []
        include_dirs = []

        # files.f paths are relative to the files.f directory
        filelist_dir = os.path.dirname(
            os.path.abspath(filelist)
        )

        with open(filelist) as f:
            for line in f:
                line = line.strip()

                if not line:
                    continue

                # ------------------------------------------
                # Nested file list
                # ------------------------------------------
                if line.startswith("-f"):
                    print(
                        f"[WARN] Nested filelist "
                        f"not supported: {line}"
                    )
                    continue

                # ------------------------------------------
                # Include directories
                #
                # Example:
                #   +incdir+./includes
                #
                # Also support:
                #   +incdir+dir1+dir2
                # ------------------------------------------
                if line.startswith("+incdir+"):
                    raw_dirs = line[len("+incdir+"):]

                    for raw_dir in raw_dirs.split("+"):
                        raw_dir = raw_dir.strip()

                        if not raw_dir:
                            continue

                        if os.path.isabs(raw_dir):
                            include_dir = raw_dir
                        else:
                            include_dir = os.path.join(
                                filelist_dir,
                                raw_dir
                            )

                        include_dir = os.path.abspath(
                            os.path.normpath(include_dir)
                        )

                        if not os.path.isdir(include_dir):
                            print(
                                f"[WARN] Missing include "
                                f"directory: {include_dir}"
                            )
                            continue

                        if include_dir not in include_dirs:
                            include_dirs.append(
                                include_dir
                            )

                    continue

                # ------------------------------------------
                # Other + directives
                # ------------------------------------------
                if line.startswith("+"):
                    continue

                # ------------------------------------------
                # Other command-line options
                # ------------------------------------------
                if line.startswith("-"):
                    continue

                # ------------------------------------------
                # Comments
                # ------------------------------------------
                if line.startswith("//"):
                    continue

                if line.startswith("#"):
                    continue

                # ------------------------------------------
                # RTL source file
                # ------------------------------------------
                if os.path.isabs(line):
                    path = line
                else:
                    path = os.path.join(
                        filelist_dir,
                        line
                    )

                path = os.path.abspath(path)

                if not os.path.exists(path):
                    print(
                        f"[WARN] Missing RTL file: {path}"
                    )
                    continue

                files.append(path)

        return (
            sorted(set(files)),
            sorted(set(include_dirs)),
        )

    # ----------------------------------------------
    # No files.f: recursive RTL discovery
    # ----------------------------------------------
    files = []

    files.extend(
        glob.glob(
            os.path.join(
                ip_dir,
                "**/*.v"
            ),
            recursive=True
        )
    )

    files.extend(
        glob.glob(
            os.path.join(
                ip_dir,
                "**/*.sv"
            ),
            recursive=True
        )
    )

    return sorted(set(files)), []


def collect_rtl_files(ip_dir):
    """
    Backward-compatible RTL-only file discovery.

    Existing callers continue to receive only the RTL
    file list.
    """
    files, _ = collect_filelist_info(ip_dir)
    return files

# --------------------------------------------------
# File parsing
# --------------------------------------------------
from pyslang.syntax import SyntaxTree


def parse_file(path, include_dirs=None, source_file=None, data_root=None):
    """Parse one RTL file.

    ``path`` is the runtime filesystem path used to read the file.
    ``source_file`` is the provenance recorded in every IR node
    (KF-DQ-002: repository-relative, e.g. ``raw/rtl/original/uart/uart_tx.v``).
    Defaults to ``path`` for ad-hoc/debug use.
    ``data_root`` makes buffer identities repository-relative (KF-DQ-003).
    """

    provenance = source_file if source_file is not None else path

    if include_dirs:
        source_manager = SourceManager()

        for include_dir in include_dirs:
            source_manager.addUserDirectories(
                str(include_dir)
            )

        tree = SyntaxTree.fromFile(
            path,
            source_manager
        )
    else:
        tree = SyntaxTree.fromFile(path)

    previous_identity = _set_source_identity(
        SourceIdentity(
            tree.sourceManager,
            lambda p: _portable_path(p, data_root),
        )
    )
    try:
        return _extract_file_modules(tree, path, provenance)
    finally:
        _set_source_identity(previous_identity)


def _portable_path(path, data_root):
    """Repository-relative form of ``path`` for identity (absolute if no data root)."""
    if data_root is None:
        return path
    try:
        return to_provenance_path(path, data_root)
    except ValueError:
        return os.path.basename(path)


def _extract_file_modules(tree, path, provenance):

    modules = {}

    compilation_declarations = (
        extract_compilation_declarations(tree)
    )

    for member in tree.root.members:

        if type(member).__name__ != \
           "ModuleDeclarationSyntax":
            continue

        mod = extract_module(
            member,
            provenance
        )

        # KF-DQ-008: Semantic IR v2 (runtime only; written by yaml_generator)
        mod["_semantic"] = ModuleExtractor(
            _SOURCE_IDENTITY,
            tree.sourceManager,
            provenance,
            unit_members=list(tree.root.members),
        ).extract(member)

        # Runtime-only absolute location (never persisted); used to read or
        # copy the RTL file during this pipeline run.
        mod["source_path"] = os.path.abspath(path)

        mod["compilation_declarations"] = (
            compilation_declarations
        )

        modules[mod["name"]] = mod

    return modules


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

    signals = extract_signals(module, rtl_path)
    
    implicit_signals = extract_implicit_signals(module, rtl_path)
    
    existing_names = {
        port["name"]
        for direction in ports.values()
        for port in direction
    }
    
    existing_names.update(
        signal["name"]
        for signal in signals
    )
    
    for signal in implicit_signals:
        if signal["name"] not in existing_names:
            signals.append(signal)
            existing_names.add(signal["name"])


    assigns = extract_assigns(module,rtl_path)

    processes = extract_processes(module,rtl_path)

    #case_statements = extract_case_statements_ast(module,rtl_path)

    instances = extract_instances(module,rtl_path)

    clocks, resets = extract_clock_reset(
        processes
    )

    #
    # Build module_info BEFORE FSM extraction
    #
    module_info = {

        **node_info(module, rtl_path),

        "parameters": parameters,
        "signals": signals,
        "continuous_assigns": assigns,
        "processes": processes,
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

# --------------------------------------------------
# PORT EXTRACTION
# --------------------------------------------------
def extract_ports(module, rtl_path):
    """
    Extract module ports.

    Supports:
      1. ANSI ports:
           module foo (
               input  wire clk,
               output wire data
           );

      2. Non-ANSI ports:
           module foo (
               clk,
               data
           );

           input  wire clk;
           output data;
    """

    interfaces = {
        "inputs": [],
        "outputs": [],
        "inouts": [],
    }

    portlist = getattr(
        module.header,
        "ports",
        None,
    )

    if portlist is None:
        return interfaces

    # --------------------------------------------------
    # ANSI PORT LIST
    # --------------------------------------------------

    for p in getattr(portlist, "ports", []):

        ptype = type(p).__name__

        if ptype == "ImplicitAnsiPortSyntax":

            name = str(
                p.declarator
            ).strip()

            direction = str(
                p.header.direction.kind
            )

            entry = {
                **node_info(p, rtl_path),
                "name": name,
            }

            dtype = getattr(
                p.header,
                "dataType",
                None,
            )

            if dtype:
                dtype_str = str(
                    dtype
                ).strip()

                if "[-1:0]" in dtype_str:
                    dtype_str = ""

                if dtype_str:
                    entry["datatype"] = dtype_str

            if "InputKeyword" in direction:
                interfaces["inputs"].append(entry)

            elif "OutputKeyword" in direction:
                interfaces["outputs"].append(entry)

            elif "InOutKeyword" in direction:
                interfaces["inouts"].append(entry)

    # --------------------------------------------------
    # NON-ANSI PORT LIST
    # --------------------------------------------------

    for p in getattr(portlist, "ports", []):

        if type(p).__name__ != \
                "ImplicitNonAnsiPortSyntax":
            continue

        expr = getattr(
            p,
            "expr",
            None,
        )

        if expr is None:
            continue

        name_node = getattr(
            expr,
            "name",
            None,
        )

        if name_node is None:
            continue

        name = str(
            name_node.value
        ).strip()

        if not name:
            continue

        # --------------------------------------------------
        # Find corresponding body declaration
        # --------------------------------------------------

        declaration = None

        for member in getattr(
            module,
            "members",
            [],
        ):

            if type(member).__name__ != \
                    "PortDeclarationSyntax":
                continue

            for declarator in getattr(
                member,
                "declarators",
                [],
            ):

                declarator_name = str(
                    getattr(
                        declarator,
                        "name",
                        "",
                    )
                ).strip()

                if declarator_name == name:
                    declaration = member
                    break

            if declaration is not None:
                break

        # --------------------------------------------------
        # Build port entry
        # --------------------------------------------------

        entry = {
            **node_info(p, rtl_path),
            "name": name,
        }

        if declaration is not None:

            header = getattr(
                declaration,
                "header",
                None,
            )

            direction = ""

            if header is not None:

                direction_node = getattr(
                    header,
                    "direction",
                    None,
                )

                if direction_node is not None:
                    direction = str(
                        direction_node.kind
                    )

                dtype = getattr(
                    header,
                    "dataType",
                    None,
                )

                if dtype:
                    dtype_str = str(
                        dtype
                    ).strip()

                    if "[-1:0]" not in dtype_str:
                        if dtype_str:
                            entry["datatype"] = (
                                dtype_str
                            )

                net_type = getattr(
                    header,
                    "netType",
                    None,
                )

                if net_type is not None:
                    entry["net_type"] = str(
                        net_type.kind
                    )

            if "InputKeyword" in direction:
                interfaces["inputs"].append(entry)

            elif "OutputKeyword" in direction:
                interfaces["outputs"].append(entry)

            elif "InOutKeyword" in direction:
                interfaces["inouts"].append(entry)

    return interfaces

# --------------------------------------------------
#   AST Infrastructure
# --------------------------------------------------


def extract_functions(module):

    functions = []

    for node in walk_ast(module):

        if type(node).__name__ == "FunctionDeclarationSyntax":

            functions.append({
                "name": extract_function_name(node)
            })

    return functions

# --------------------------------------------------
# PARAMETER EXTRACTION
# --------------------------------------------------

def extract_parameters(module, rtl_path):
    """
    Extract module parameters from both:

      1. Module header:
           module foo #(parameter WIDTH = 32)

      2. Module body:
           parameter IDLE = 2'b00;
           parameter DONE = 2'b01;

    Returns the existing Module IR parameter format.
    """

    parameters = []

    # --------------------------------------------------
    # 1. Module-header parameters
    # --------------------------------------------------

    try:
        param_port_list = getattr(
            module.header,
            "parameters",
            None,
        )

        if param_port_list is not None:

            raw = str(param_port_list)

            pattern = (
                r'parameter\s+'
                r'(?:[\w\[\]:]+\s+)*'
                r'(\w+)'
                r'\s*=\s*'
                r'([^,\n\)]+)'
            )

            for match in re.finditer(
                pattern,
                raw,
            ):
                parameters.append({
                    **node_info(
                        param_port_list,
                        rtl_path,
                    ),
                    "name": match.group(1),
                    "default": normalize_param_value(
                        match.group(2)
                    ),
                })

    except Exception:
        pass

    # --------------------------------------------------
    # 2. Module-body parameters
    # --------------------------------------------------

    for member in getattr(
        module,
        "members",
        [],
    ):

        if type(member).__name__ != \
                "ParameterDeclarationStatementSyntax":
            continue

        parameter_decl = getattr(
            member,
            "parameter",
            None,
        )

        if parameter_decl is None:
            continue

        for declarator in getattr(
            parameter_decl,
            "declarators",
            [],
        ):

            name_node = getattr(
                declarator,
                "name",
                None,
            )

            if name_node is None:
                continue

            name = str(name_node.value).strip()

            if not name:
                continue

            initializer = getattr(
                declarator,
                "initializer",
                None,
            )

            expr = None

            if initializer is not None:
                expr = getattr(
                    initializer,
                    "expr",
                    None,
                )

            parameters.append({
                **node_info(
                    member,
                    rtl_path,
                ),
                "name": name,
                "default":
                    None
                    if expr is None
                    else str(expr).strip(),
            })

    return parameters


# -------------------------------------------------
# CLOCK AND RESET EXTRACTION
#--------------------------------------------------

def extract_clock_reset(processes):

    clocks = {
        p["clock"]
        for p in processes
        if p["clock"]
    }

    resets = {
        p["reset"]
        for p in processes
        if p["reset"]
    }

    return sorted(clocks), sorted(resets)

# --------------------------------------------------
# SIGNAL EXTRACTION
# --------------------------------------------------

def is_typedef_enum(node_type):
    return node_type == "TypedefDeclarationSyntax"

def is_parameter_decl(node_type):
    return node_type == "ParameterDeclarationStatementSyntax"

def is_inline_enum(node_type):
    return  node_type == "DataDeclarationSyntax"



def extract_signals(module, rtl_path):
    signals = []
    seen = set()

    for member in module.members:
        member_type = type(member).__name__

        if member_type not in (
            "DataDeclarationSyntax",
            "NetDeclarationSyntax",
        ):
            continue

        type_node = getattr(member, "type", None)

        if type_node is None:
            continue

        sig_type = str(type_node).strip()

        for declarator in getattr(member, "declarators", []):
            name_node = getattr(declarator, "name", None)

            if name_node is None:
                continue

            name = str(name_node.value).strip()

            if not name:
                continue

            if name in seen:
                continue

            seen.add(name)

            entry = {
                **node_info(member, rtl_path),
                "name": name,
                "type": sig_type,
            }

            signals.append(entry)

    return signals

# --------------------------------------------------
# INSTANCE EXTRACTION
# --------------------------------------------------
def extract_instances(module,rtl_path):

    instances = []

    for member in module.members:

        if type(member).__name__ != \
           "HierarchyInstantiationSyntax":
            continue

        module_type = str(
            member.type
        )
        
        lines = []
        
        for l in module_type.splitlines():
        
            l = l.strip()
        
            if not l:
                continue
        
            if l.startswith("//"):
                continue
        
            lines.append(l)
        
        if not lines:
            continue
        
        module_type = lines[-1]


        for inst in member.instances:

            inst_entry = {
                **node_info(inst,rtl_path),
                "instance":
                    str(inst.decl).strip(),

                "module":
                    module_type,

                "connections":
                    []
            }

            for conn in inst.connections:

                if type(conn).__name__ == "Token":
                    continue

                if type(conn).__name__ != \
                   "NamedPortConnectionSyntax":
                    continue

                signal = ""

                if conn.expr is not None:
                
                    signal = str(
                        conn.expr
                    ).strip()
                
                inst_entry[
                    "connections"
                ].append({

                    **node_info(conn, rtl_path),
                
                    "port":
                        str(
                            conn.name
                        ).strip(),
                
                    "signal":
                        signal
                })

            instances.append(
                inst_entry
            )

    return instances


def enrich_implicit_instance_nets(modules):
    """
    Add implicit nets for undeclared actual signals connected
    to output/inout formal ports of instantiated modules.

    This supports legacy Verilog implicit-net semantics.

    The child module must be present in the parsed module database.
    Only output/inout formal ports can introduce an implicit net
    in the parent module.
    """

    for parent_module in modules.values():

        # Existing declared names in the parent
        existing_names = {
            port["name"]
            for direction in parent_module.get("interfaces", {}).values()
            for port in direction
        }

        existing_names.update(
            signal["name"]
            for signal in parent_module.get("signals", [])
        )

        for instance in parent_module.get("instances", []):

            child_name = instance.get("module")
            child_module = modules.get(child_name)

            if child_module is None:
                continue

            # Build formal-port direction lookup
            formal_directions = {}

            interfaces = child_module.get(
                "interfaces",
                {}
            )

            for direction in (
                "inputs",
                "outputs",
                "inouts",
            ):
                for port in interfaces.get(direction, []):
                    formal_name = port.get("name")

                    if formal_name:
                        formal_directions[
                            formal_name
                        ] = direction

            # Examine actual connections
            for connection in instance.get(
                "connections",
                []
            ):

                formal_name = connection.get("port")
                actual_name = connection.get("signal")

                if not formal_name or not actual_name:
                    continue

                direction = formal_directions.get(
                    formal_name
                )

                if direction not in (
                    "outputs",
                    "inouts",
                ):
                    continue

                # Only simple identifier actuals are eligible.
                if not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_$]*",
                    actual_name,
                ):
                    continue

                if actual_name in existing_names:
                    continue

                parent_module.setdefault(
                    "signals",
                    []
                ).append({
                    "name": actual_name,
                    "type": "implicit_net",
                    "implicit": True,
                    "source": "instance_output",
                    "instance": instance.get(
                        "instance"
                    ),
                    "port": formal_name,
                    "module": child_name,
                })

                existing_names.add(actual_name)

# --------------------------------------------------
# ASSIGN EXTRACTION
# --------------------------------------------------

def extract_assigns(module, rtl_path):
    """Extract continuous assignments as Expression IR."""

    assigns = []

    for member in module.members:

        if type(member).__name__ != "ContinuousAssignSyntax":
            continue

        for assignment in member.assignments:

            lhs = parse_expression(assignment.left)
            rhs = parse_expression(assignment.right)

            assigns.append({
                **node_info(member, rtl_path),
                "lhs": lhs,
                "rhs": rhs,
            })

    return assigns


# --------------------------------------------------
# ALWAYS EXTRACTION
# --------------------------------------------------

def extract_processes(module,rtl_path):

    processes = []

    for member in module.members:

        if type(member).__name__ != "ProceduralBlockSyntax":
            continue

        raw = str(member)

        if not KEEP_COMMENTS:
        
            raw = re.sub(
                r'^\s*/\*.*?\*/\s*',
                '',
                raw,
                flags=re.S
            )
        
            raw = re.sub(
                r'^(?:\s*//.*\n)+',
                '',
                raw,
                flags=re.MULTILINE
            )

        if not raw.strip():
            continue

        process = parse_process(member)
        
        processes.append({
            **process,

            **node_info(member, rtl_path),
        
            "assignments": collect_assignments(process["body"]),
        
            "case_statements": collect_case_statements(process["body"]),
        
            "raw": raw.strip(),
        })



    return processes

# --------------------------------------------------
# TOP DETECTION
# --------------------------------------------------

def find_top_module(modules, ip_dir=None):

    instantiated = set()

    for mod in modules.values():

        for inst in mod["instances"]:

            instantiated.add(
                inst["module"]
            )

    candidates = []

    for name in modules:

        if name not in instantiated:

            candidates.append( name)



    if candidates:
        if ip_dir:
            ip_name = os.path.basename(
                ip_dir
            ).lower()

            for c in candidates:
                if c.lower() == ip_name:
                    return c

        top_candidates = []
        
        for c in candidates:
        
            score = 0
        
            if "_top" in c.lower():
                score += 100
        
            score += len(
                modules[c]["instances"]
            )
        
            top_candidates.append(
                (score, c)
            )
        
        top_candidates.sort(
            reverse=True
        )
        
        return top_candidates[0][1]


    return list(
        modules.keys()
    )[0]


# --------------------------------------------------
# GRAPH
# --------------------------------------------------

def build_graph(modules):

    graph = nx.DiGraph()

    for module in modules.values():
        graph.add_node(
            module["name"]
        )
        for inst in module["instances"]:
            graph.add_edge( module["name"], inst["module"])

    return graph


# --------------------------------------------------
# PARSE IP
# --------------------------------------------------

def parse_ip(ip_dir, data_root=None):
    """Parse all RTL of one IP.

    KF-DQ-002: node/module ``source_file`` provenance is recorded relative to
    the data-repository root (``raw/rtl/original/...``).  ``data_root`` is
    inferred from ``ip_dir`` when not given; if it cannot be determined
    (ad-hoc debug runs outside a data repository) absolute paths are kept and
    the writers refuse to persist them.
    """

    if data_root is None:
        data_root = infer_data_root(ip_dir)

    rtl_files, include_dirs = collect_filelist_info(ip_dir)

    print(
        f"[INFO] Parsing "
        f"{len(rtl_files)} RTL files"
    )
    if include_dirs:
        print(
            f"[INFO] Include directories: "
            f"{len(include_dirs)}"
        )
    
        for include_dir in include_dirs:
            print(
                f"       {include_dir}"
            )

    modules = {}

    for rtl in rtl_files:
    
        print("   ", rtl)
    
        try:
    
            file_modules = parse_file(
                rtl,
                include_dirs,
                source_file=(
                    to_provenance_path(rtl, data_root)
                    if data_root is not None
                    else None
                ),
                data_root=data_root,
            )
    
            #
            # Detect duplicate module names
            #
            for name, mod in file_modules.items():

                # ------------------------------------------
                # Propagate files.f include directories
                # into Module IR.
                # ------------------------------------------
                mod["include_dirs"] = include_dirs
            
                #
                # Detect duplicate module names
                #
                if name in modules:
                    print(
                        f"[WARN] Duplicate module "
                        f"'{name}'"
                    )
            
                    print(
                        f"       Existing : "
                        f"{modules[name]['source_file']}"
                    )
            
                    print(
                        f"       New      : "
                        f"{mod['source_file']}"
                    )
            
                modules[name] = mod
    
        except Exception as e:

            print("\n" + "=" * 80)
            print("[RTL PARSE ERROR]")
            print("IP        :", os.path.basename(ip_dir))
            print("RTL File  :", rtl)
            print("Exception :", type(e).__name__)
            print("Message   :", e)
            print("-" * 80)

            traceback.print_exc()

            print("=" * 80)

            raise



    if not modules:

        raise RuntimeError(
            f"No modules found in {ip_dir}"
        )


    # --------------------------------------------------
    # Cross-module implicit-net enrichment
    # --------------------------------------------------
    enrich_implicit_instance_nets(modules)

    #
    # Make module order deterministic
    #
    modules = dict(
        sorted(
            modules.items()
        )
    )
    
    top = find_top_module(
        modules,
        ip_dir
    )
    
    return modules, top
        
# --------------------------------------------------
# DEBUG
# --------------------------------------------------

if __name__ == "__main__":

    import sys

    if len(sys.argv) != 2:
        print( f"Usage: " f"{sys.argv[0]} <ip_dir>")
        raise SystemExit(1)

    modules, top = parse_ip(
        sys.argv[1]
    )

    print( "\nTop Module:", top)

    for m in modules:

        print( "\nMODULE:", m)
