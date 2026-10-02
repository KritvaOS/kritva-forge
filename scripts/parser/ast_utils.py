#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : ast_utils.py
# Description : Ast Utils implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
import re
from collections import defaultdict

# ---------------------------------------------------------------------
# SystemVerilog keywords that should never be returned as identifiers
# ---------------------------------------------------------------------

SV_KEYWORDS = {
    "if", "else", "case", "casex", "casez",
    "begin", "end",
    "default",
    "for", "while", "repeat", "forever",
    "always", "always_ff", "always_comb", "always_latch",
    "posedge", "negedge",
    "assign",
    "wire", "logic", "reg",
    "input", "output", "inout",
    "parameter", "localparam",
    "typedef", "enum", "struct",
    "generate", "genvar",
    "function", "task",
    "return",
    "or", "and", "xor", "not"
}

def dump_node_info(node):

    print("=" * 60)
    print(type(node).__name__)

    print(hasattr(node, "location"))
    print(hasattr(node, "sourceRange"))
    print(hasattr(node, "source_range"))


    for attr in dir(node):

        if attr.startswith("_"):
            continue

        try:
            value = getattr(node, attr)

            if callable(value):
                continue

            print(f"{attr:20} : {value}")

        except Exception:
            pass

def inspect_ast_node(node):
    print("=" * 80)
    print(type(node).__name__)
    dump_node_info(node)


def dump_ast(node, depth=0, max_depth=2):
    if node is None or depth > max_depth:
        return

    indent = "  " * depth
    print(f"{indent}{type(node).__name__} ({node.kind})")

    for attr in dir(node):
        if attr.startswith("_"):
            continue

        try:
            value = getattr(node, attr)
        except Exception:
            continue

        if hasattr(value, "kind"):
            print(f"{indent}  {attr} -> {type(value).__name__}")
            dump_ast(value, depth + 1, max_depth)

        elif isinstance(value, list):
            print(f"{indent}  {attr} -> list({len(value)})")
            for item in value[:5]:
                if hasattr(item, "kind"):
                    dump_ast(item, depth + 1, max_depth)



def dump_enum_nodes(module):

    def recurse(node, depth=0):

        if node is None:
            return

        node_type = type(node).__name__

        #
        # Only look at nodes that may contain enums
        #
        if node_type in (
            "TypedefDeclarationSyntax",
            "DataDeclarationSyntax",
            "ParameterDeclarationStatementSyntax",
        ):

            try:
                txt = str(node)
            except Exception:
                txt = ""

            txt_lower = txt.lower()

            #
            # Filter aggressively
            #
            show = False

            #
            # typedef enum ...
            #
            if "typedef enum" in txt_lower:
                show = True

            #
            # enum logic [...] { ... }
            #
            elif re.search(
                r'\benum\s+\w+.*\{',
                txt,
                re.S
            ):
                show = True

            #
            # state-encoding parameters
            #
            elif (
                node_type ==
                "ParameterDeclarationStatementSyntax"
            ):

                if re.search(
                    r"\b(state|fsm)\b",
                    txt_lower
                ):
                    show = True

            if show:

                debug(DEBUG_PARAM, "\n[ENUM NODE]")
                debug(DEBUG_PARAM, "DEPTH:", depth)
                debug(DEBUG_PARAM, "TYPE :", node_type)
                debug(DEBUG_PARAM, txt[:1000])

        #
        # recurse
        #
        for attr in (
            "members",
            "items",
            "statements",
            "body",
            "statement",
        ):

            try:

                child = getattr(
                    node,
                    attr,
                    None
                )

                if isinstance(
                    child,
                    (list, tuple)
                ):

                    for c in child:
                        recurse(
                            c,
                            depth + 1
                        )

                elif child is not None:

                    recurse(
                        child,
                        depth + 1
                    )

            except Exception:
                pass

    recurse(module)

# ------------------------------
#
# ------------------------------

def get_node_location(node):
    """
    Return source location information for a PySlang AST node.

    Returns:
        {
            "file": str | None,
            "line": int | None,
            "column": int | None
        }
    """

    if node is None:
        return None

    try:
        sr = getattr(node, "sourceRange", None)
        if sr is not None:
            start = sr.start

            return {
                "file": str(getattr(start, "buffer", "")),
                "line": getattr(start, "line", None),
                "column": getattr(start, "column", None),
            }
    except Exception:
        pass

    return None

# -------------------------------
#
# -------------------------------

def get_node_text(node):

    text = str(node)

    #
    # Remove // comments
    #
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)

    #
    # Remove /* */ comments
    #
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    return text.strip()

# --------------------------------
#
# --------------------------------

def dump_assignment_ast(node):

    if node is None:
        return

    print("=" * 80)
    print("ASSIGNMENT")
    print(str(node))

    print()

    print("LHS AST")
    dump_node(node.left)

    print()

    print("RHS AST")
    dump_node(node.right)

    print("=" * 80)

# ---------------------------------
#
# ---------------------------------

def dump_expression_info(node):

    if node is None:
        return

    print("=" * 80)
    print("TYPE :", type(node).__name__)
    print("KIND :", getattr(node, "kind", None))
    print("TEXT :", str(node))
    print("FIELDS:")

    for name in dir(node):
        if name.startswith("_"):
            continue
        print("   ", name)

# ----------------------------------
#
# ----------------------------------

def dump_node(node):

    if node is None:
        return

    print("=" * 80)
    print("TYPE :", type(node).__name__)
    print("KIND :", getattr(node, "kind", None))
    print("TEXT :", str(node))

    for attr in dir(node):

        if attr.startswith("_"):
            continue

        if attr in (
            "kind",
            "sourceRange",
            "parent",
        ):
            continue

        try:
            value = getattr(node, attr)

            if callable(value):
                continue

            print(f"{attr:20} : {type(value).__name__}")

        except Exception:
            pass
        


def discover_inline_enum(node):
    """
    Discover an inline enum declaration.

    Expected PySlang structure:

        DataDeclarationSyntax
            ├── type: EnumTypeSyntax
            │       └── members: DeclaratorSyntax / comma tokens
            └── declarators: DeclaratorSyntax / comma tokens

    Example:

        enum logic [3:0] {
            IDLE = 4'h0,
            RUN  = 4'h1
        } state;

    Returns
    -------
    dict | None
        {
            "name": str,
            "width": str,
            "members": [
                {
                    "name": str,
                    "expr": AST | None
                }
            ]
        }
    """

    if node is None:
        return None

    enum_type = getattr(node, "type", None)

    if enum_type is None:
        return None

    if type(enum_type).__name__ != "EnumTypeSyntax":
        return None

    info = {
        "name": "",
        "width": "",
        "members": [],
    }

    # --------------------------------------------------
    # Enum width
    # --------------------------------------------------

    base_type = getattr(enum_type, "baseType", None)

    if base_type is not None:
        info["width"] = str(base_type).strip()

    # --------------------------------------------------
    # Enum declaration variable name
    #
    # Example:
    #     } state,next_state;
    #
    # Keep the first actual declarator as the name.
    # The enum members themselves are what semantic
    # analysis needs.
    # --------------------------------------------------

    for declarator in getattr(node, "declarators", []):

        if type(declarator).__name__ != "DeclaratorSyntax":
            continue

        name_node = getattr(declarator, "name", None)

        if name_node is None:
            continue

        name = getattr(name_node, "value", None)

        if not name:
            name = str(name_node).strip()

        name = str(name).strip()

        if name:
            info["name"] = name
            break

    # --------------------------------------------------
    # Enum members
    # --------------------------------------------------

    for member in getattr(enum_type, "members", []):

        if type(member).__name__ != "DeclaratorSyntax":
            continue

        name_node = getattr(member, "name", None)

        if name_node is None:
            continue

        name = getattr(name_node, "value", None)

        if not name:
            name = str(name_node).strip()

        name = str(name).strip()

        if not name:
            continue

        initializer = getattr(member, "initializer", None)

        expr = None

        if initializer is not None:
            expr_node = getattr(initializer, "expr", None)

            if expr_node is not None:
                expr = str(expr_node).strip()

        info["members"].append({
            "name": name,
            "expr": expr,
        })

    if not info["members"]:
        return None

    return info


def discover_typedef_enum(node):

    return {

        "name":
            discover_typedef_name(node),

        "width":
            discover_enum_width(node),

        "members":
            discover_enum_members(node)
    }

def discover_enum_members(node):

    members = []

    for n in walk_ast(node):

        if not hasattr(n, "initializer") and \
            not hasattr(n, "value"):
            continue

        entry = {

            "name": None,

            "expr": None

        }

        try:

            entry["name"] = str(
                n.name
            )

        except Exception:

            continue

        for attr in (

            "value",

            "initializer",

            "expression",

            "expr"

        ):

            if hasattr(n, attr):

                entry["expr"] = getattr(
                    n,
                    attr
                )

                break

        members.append(entry)

    return members

def discover_enum_width(node):

    for n in walk_ast(node):

        if type(n).__name__ != "EnumTypeSyntax":
            continue

        try:

            return str(
                n.baseType
            )

        except Exception:

            return ""

    return ""

def discover_typedef_name(node):

    for n in walk_ast(node):

        if type(n).__name__ == "TypedefDeclarationSyntax":

            try:
                return str(n.name)
            except Exception:
                pass

    return ""

# --------------------------------------------------
# Enum subroutine
# --------------------------------------------------

def evaluate_constant_expression(expr):

    if expr is None:
        return None

    try:

        txt = str(expr).strip()

    except Exception:

        return None

    #
    # decimal
    #
    try:
        return int(txt, 0)
    except Exception:
        pass

    #
    # 3'b101
    #
    m = re.match(
        r"(\d+)?'([bBoOdDhH])([0-9a-fA-F_xXzZ]+)",
        txt
    )

    if m:

        base = {

            "b":2,
            "o":8,
            "d":10,
            "h":16

        }[m.group(2).lower()]

        digits = (
            m.group(3)
             .replace("_","")
             .replace("x","0")
             .replace("X","0")
             .replace("z","0")
             .replace("Z","0")
        )

        return int(digits, base)

    return txt

def infer_width_from_values(members):

    vals = []

    for m in members.values():

        v = m.get("value")

        if isinstance(v, int):

            vals.append(v)

    if not vals:

        return ""
    
    max_val = max( abs(v) for v in vals)

    bits = max(
        1,
        max_val.bit_length()
    )

    return f"[{bits-1}:0]"


# --------------------------------------------------
#
# --------------------------------------------------
def normalize_state_value(value):

    value = str(value).strip()

    m = re.match(
        r"\d+'([hdb])([0-9a-fA-F_xzXZ]+)$",
        value,
        re.I
    )

    if m:
        base = m.group(1).lower()
        digits = m.group(2)

        if base == "h":
            return "h" + digits
        if base == "d":
            return "d" + digits
        if base == "b":
            return "b" + digits

    return value
# ------------------------------------------------------------------
#
# ------------------------------------------------------------------
def get_primary_role(always_roles, signal):

    roles = always_roles.get(signal, [])

    if not roles:
        return None

    if isinstance(roles, dict):
        return roles

    if isinstance(roles, list):
        return roles[0]

    return None
# -------------------------------------------------------------------
#
# -------------------------------------------------------------------

def debug(flag, *args):
    if flag:
        print(*args)

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


def derive_fsm_prefix(name):

    name = str(name).upper()

    if "_FSM_" in name:

        idx = name.find("_FSM_")

        return name[:idx + 5]

    if name.startswith("FSM_"):
        return "FSM_"

    return None

# ---------------------------------------------------------------------
# Verilog literal detector
# ---------------------------------------------------------------------

_LITERAL_RE = re.compile(
    r"""
    ^
    \d+
    '
    [bBdDhHoO]
    [0-9a-fA-FxXzZ?_]+
    $
    """,
    re.VERBOSE
)

# ---------------------------------------------------------------------
# Identifier token regex
# ---------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*"
)


def extract_identifiers(expr, keep_state_literals=False):
    """
    Extract identifiers from a SystemVerilog expression.

    Returns only real RTL signals.

    Filters:
        - numeric literals
        - binary/hex/octal literals
        - keywords
        - x/z literals
        - 1'b0 -> b0 problem
    """

    if not expr:
        return []

    #
    # Remove Verilog literals first.
    #
    # Example:
    #
    #     3'b101
    #     8'hFF
    #     16'd255
    #
    expr = re.sub(
        r"\d+'[bBdDhHoO][0-9a-fA-FxXzZ?_]+",
        " ",
        expr
    )

    #
    # Remove decimal numbers.
    #
    expr = re.sub(
        r"\b\d+\b",
        " ",
        expr
    )

    #
    # Extract identifier-like tokens.
    #
    tokens = _IDENTIFIER_RE.findall(expr)

    ids = []

    for tok in tokens:

        #
        # Skip keywords
        #
        if tok in SV_KEYWORDS:
            continue

        #
        # Skip constants
        #
        if tok.lower() in (
            "true",
            "false",
            "null"
        ):
            continue

        #
        # Skip x/z literals
        #
        if tok.lower() in (
            "x",
            "z",
            "bx",
            "bz"
        ):
            continue

        #
        # Skip malformed literal fragments
        #
        if re.match(
            r"^[bBdDhHoO][0-9a-fA-FxXzZ_]+$",
            tok
        ):
            continue

        #
        # Skip duplicates
        #
        if tok not in ids:
            ids.append(tok)

    return ids


# -------------------------------------------------------
# Generic AST walker
# -------------------------------------------------------
AST_CHILDREN = (

    # procedural
    "statement",
    "body",
    "items",
    "members",
    "clauses",
    "blocks",
    "branches",

    # expressions
    "expression",
    "expressions",
    "initializer",
    "value",

    # declarations
    "declarators",
    "baseType",
    "type",

    # conditionals
    "predicate",
    "condition",
    "elseClause",
    "clause",

    # case
    "expr"
)

def walk_ast(node):
    if node is None:
        return

    yield node

    for attr in AST_CHILDREN :

        try:
            value = getattr(node, attr)
        except Exception:
            continue

        if callable(value):
            continue

        if hasattr(value, "__class__") and \
           value.__class__.__name__.endswith("Syntax"):
            yield from walk_ast(value)

        elif isinstance(value, (list, tuple)):
            for child in value:
                if hasattr(child, "__class__") and \
                   child.__class__.__name__.endswith("Syntax"):
                    yield from walk_ast(child)



def walk_stmt(node):

    if node is None:
        return

    yield node

    for attr in (
        "statement",
        "body",
        "elseClause",
        "clause",
    ):
        if hasattr(node, attr):
            try:
                child = getattr(node, attr)

                if child is not None:
                    yield from walk_ast(child)

            except Exception:
                pass

    for attr in (
        "items",
        "members",
        "clauses",
        "blocks",
    ):
        if hasattr(node, attr):
            try:
                for child in getattr(node, attr):
                    yield from walk_ast(child)
            except Exception:
                pass
