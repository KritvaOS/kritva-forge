# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : statement_parser.py
# Description : Statement Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
# ----------------------------------  
#  statement_parser.py
#  
#  parse_statement()
#  
#          │
#          ├── parse_assignment()
#          ├── parse_if()
#          ├── parse_case()
#          ├── parse_case_item()
#          ├── parse_block()
#          ├── parse_return()
#          └── parse_null()
# ----------------------------------

from scripts.rtl_ir.statement import (
    new_assignment_stmt,
    new_if_stmt,
    new_case_stmt,
    new_case_item,
    new_block_stmt,
    new_return_stmt,
    new_null_stmt,
)

from scripts.parser.expression_parser import (
    parse_expression,
    is_expression_node,
)

from scripts.parser.ast_utils import (
    get_node_text,
    get_node_location,
    inspect_ast_node,
)

from scripts.parser.debug import debug_assignment

from scripts.parser.statistics import record_statement


STATEMENT_NAMES = {
    "ConditionalStatementSyntax": "If",
    "BlockStatementSyntax": "Block",
    "ExpressionStatementSyntax": "Expression",
    "CaseStatementSyntax": "Case",
    "TimingControlStatementSyntax": "TimingControl",
}

# --------------------------------------
# Helper
# --------------------------------------

def statement_common(node):

    return {

        "text": get_node_text(node),

        "syntax_kind": str(node.kind),

        "location": get_node_location(node),
    }


# ---------------------------------------
#
# ---------------------------------------
def parse_expression_statement(node):

    expr = node.expr

    kind = str(expr.kind)

    if kind in (
        "SyntaxKind.BlockingAssignmentExpression",
        "SyntaxKind.NonblockingAssignmentExpression",
    ):
        return parse_assignment(expr)

    
    return new_null_stmt(
        **statement_common(node)
    )

# ---------------------------------------
# Dispatcher
# ---------------------------------------

def parse_statement(node):


    #debug_statement(
    #    "NODE:",
    #    type(node).__name__,
    #    node.kind,
    #)

    if node is None:
        return None

    record_statement( STATEMENT_NAMES.get( type(node).__name__, type(node).__name__,))

    node_type = type(node).__name__


    if node_type == "ExpressionStatementSyntax":

        return parse_expression_statement(node)

    #
    # Timing Control
    #
    elif node_type == "TimingControlStatementSyntax":
        return parse_statement(node.statement)


    #
    # If
    #
    elif node_type == "ConditionalStatementSyntax":
        return parse_if(node)

    #
    # Case
    #
    elif node_type == "CaseStatementSyntax":
        return parse_case(node)

    #
    # Block
    #
    elif node_type == "BlockStatementSyntax":
        return parse_block(node)

    #
    # Return
    #
    elif node_type == "ReturnStatementSyntax":
        return parse_return(node)

    #
    # Empty
    #
    elif node_type == "EmptyStatementSyntax":
        return new_null_stmt(
            **statement_common(node)
        )

    #
    # Unknown
    #
    else:

        return new_null_stmt(

            **statement_common(node)
        )


def parse_assignment(node):


    #print("LEFT :", type(node.left).__name__, node.left.kind)
    #print("RIGHT:", type(node.right).__name__, node.right.kind)
    
    lhs = parse_expression(node.left)
    rhs = parse_expression(node.right)
   
    debug_assignment( "LEFT:", lhs,)
    debug_assignment( "RIGHT:", rhs,)

    #print(lhs)
    #print(rhs)


    blocking = "BlockingAssignmentExpression" in str(node.kind)

    return new_assignment_stmt(

        lhs=lhs,

        rhs=rhs,

        blocking=blocking,

        **statement_common(node)

    )


def parse_if(node):

    condition = parse_expression( node.predicate)

    then_stmt = parse_statement( node.statement)

    else_stmt = None

    if node.elseClause is not None:

        else_stmt = parse_statement(node.elseClause.clause)

    return new_if_stmt(

        condition=condition,

        then_stmt=then_stmt,

        else_stmt=else_stmt,

        **statement_common(node)

    )


def parse_case(node):

    expr = parse_expression(
        node.expr
    )

    items = []

    for item in node.items:

        items.append(
            parse_case_item(item)
        )

    return new_case_stmt(

        expression=expr,

        items=items,

        case_type=str(node.kind),

        **statement_common(node)

    )


def parse_case_item(node):

    node_type = type(node).__name__

    if node_type == "StandardCaseItemSyntax":
        return parse_standard_case_item(node)

    if node_type == "DefaultCaseItemSyntax":
        return parse_default_case_item(node)

    return new_null_stmt(
        **statement_common(node)
    )

def parse_standard_case_item(node):

    labels = []

    for expr in node.expressions:

        #
        # Skip punctuation tokens such as ','
        #
        if not is_expression_node(expr):
            continue

        ir = parse_expression(expr)

        if ir is not None:
            labels.append(ir)

    stmt = parse_statement(node.clause)

    return new_case_item(

        labels=labels,

        statement=stmt,

        default=False,

        **statement_common(node)
    )


def parse_default_case_item(node):

    stmt = parse_statement(node.clause)

    return new_case_item(

        labels=[],

        statement=stmt,

        default=True,

        **statement_common(node)
    )




def parse_block(node):

    statements = []

    items = getattr(node, "items", [])

    for item in items:

        ir = parse_statement(item)

        if ir is not None:

            statements.append(ir)

    return new_block_stmt(

        statements,

        **statement_common(node)

    )



def parse_return(node):

    expr = None

    if node.expression is not None:

        expr = parse_expression(
            node.expression
        )

    return new_return_stmt(

        expression=expr,

        **statement_common(node)

    )
