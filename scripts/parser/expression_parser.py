# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : expression_parser.py
# Description : Expression Parser implementation
#
# Component   : Kritva Forge
# Module      : parser
# Layer       : Parser
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================
#  parser/expression_parser.py → converts AST to IR

from pyslang.syntax import SyntaxKind
import inspect


from scripts.rtl_ir.expression import (
    new_identifier,
    new_constant,
    new_unknown,
    new_expression,
    new_cast,
)

from scripts.rtl_ir.expression import (
    new_binary,
    new_call,
    new_conditional,
)

from scripts.parser.ast_utils import ( get_node_text , inspect_ast_node , )

from scripts.parser.debug import debug_expression

from scripts.parser.statistics import record_unknown

from scripts.parser.statistics import record_expression

UNARY_OPERATOR_MAP = {

    SyntaxKind.UnaryLogicalNotExpression: "!",

    SyntaxKind.UnaryBitwiseNotExpression: "~",

    SyntaxKind.UnaryMinusExpression: "-",

    SyntaxKind.UnaryBitwiseAndExpression: "&",

    SyntaxKind.UnaryBitwiseOrExpression: "|",

    SyntaxKind.UnaryBitwiseXorExpression: "^",

    SyntaxKind.UnaryBitwiseNandExpression: "~&",

    SyntaxKind.UnaryBitwiseNorExpression: "~|",
}


def parse_cast(node):
    """
    Parse SystemVerilog cast expressions.

    PySlang represents CastExpressionSyntax as:

        left  = cast type / size
        right = parenthesized operand

    Examples:
        5'(signal)
        WIDTH'(signal)
        WIDTH'(a + b)
    """

    cast_type = parse_expression(node.left)
    operand = parse_expression(node.right)

    expr = new_cast(
        cast_type=cast_type,
        operand=operand,
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    return expr

def parse_simple_sequence(node):
    """
    Parse SimpleSequenceExprSyntax.

    Forward to the contained expression.
    Ignore repetition for now (currently always None).
    """

    return parse_expression(node.expr)


def parse_simple_property(node):
    """
    Parse SimplePropertyExprSyntax.

    PySlang wraps an expression inside a SimplePropertyExprSyntax.
    Forward directly to the contained expression.
    """

    return parse_expression(node.expr)


def parse_prefix_unary(node):
    """
    Parse PrefixUnaryExpressionSyntax.
    """

    expr = new_expression(
        expr_type="unary",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["operator"] = str(node.operatorToken).strip()

    expr["operand"] = parse_expression(node.operand)

    expr["children"] = [
        expr["operand"]
    ]

    return expr


def parse_conditional(node):
    """
    Parse

        cond ? expr1 : expr2

    into RTL IR.
    """

    #debug_expression( "Expression:", node.kind,)


    #
    # Condition
    #
    condition = None

    for attr in (
        "condition",
        "predicate",
        "cond",
    ):
        if hasattr(node, attr):
            condition = parse_expression(
                getattr(node, attr)
            )
            break

    #
    # True expression
    #
    true_expr = None

    for attr in (
        "left",
        "trueExpr",
        "whenTrue",
    ):
        if hasattr(node, attr):
            true_expr = parse_expression(
                getattr(node, attr)
            )
            break

    #
    # False expression
    #
    false_expr = None

    for attr in (
        "right",
        "falseExpr",
        "whenFalse",
    ):
        if hasattr(node, attr):
            false_expr = parse_expression(
                getattr(node, attr)
            )
            break

    return new_conditional(
        condition=condition,
        true_expr=true_expr,
        false_expr=false_expr,
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )


def is_expression_node(node):

    if node is None:
        return False

    if not hasattr(node, "kind"):
        return False

    return not str(node.kind).startswith("TokenKind")


def parse_parenthesized_expression(node):

    if node is None:
        return None

    if hasattr(node, "expression"):

        #
        # Just return enclosed expression
        #
        return parse_expression(node.expression)

    return None


def parse_bit_select(node):

    expr = new_expression(
        expr_type="bit_select",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["index"] = None

    #
    # inspect with dump_node() once
    #
    #debug_expression( "Expression:", node.kind,)

    if hasattr(node, "expr"):

        expr["index"] = parse_expression(node.expr)

    elif hasattr(node, "expression"):

        expr["index"] = parse_expression(node.expression)

    expr["children"] = [
        expr["index"]
    ]

    return expr


def parse_range_select(node):

    expr = new_expression(
        expr_type="range_select",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["left"] = None

    expr["right"] = None

    #debug_expression( "Expression:", node.kind,)

    if hasattr(node, "left"):

        expr["left"] = parse_expression(node.left)

        expr["right"] = parse_expression(node.right)

    expr["children"] = [
        expr["left"],
        expr["right"]
    ]

    return expr


def parse_element_select(node):

    if node is None:
        return None

    expr = new_expression(
        expr_type="element_select",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["selector"] = None

    #
    # selector is BitSelectSyntax or RangeSelectSyntax
    #
    if hasattr(node, "selector"):

        expr["selector"] = parse_expression(
            node.selector
        )

    expr["children"] = [
        expr["selector"]
    ]

    return expr



def parse_identifier_select(node):

    expr = new_expression(
        expr_type="identifier_select",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    #
    # Base signal
    #
    # expr["base"] = parse_expression(node.identifier)
    expr["base"] = new_identifier(
        name=get_node_text(node.identifier),
        text=get_node_text(node.identifier),
        syntax_kind=str(node.identifier.kind),
    )

    #
    # Selector(s)
    #
    expr["selectors"] = []

    for selector in node.selectors:

        if not is_expression_node(selector):
            continue

        ir = parse_expression(selector)

        if ir is not None:

            expr["selectors"].append(ir)


    expr["children"] = [
    
        expr["base"],
    
        *expr["selectors"]
    ]


    return expr



def parse_concatenation(node):

    expr = new_expression(
        expr_type="concat",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["children"] = []

    for child in node.expressions:

        if not is_expression_node(child):
            continue

        child_ir = parse_expression(child)

        if child_ir is not None:

            expr["children"].append(child_ir)


    return expr



def parse_multiple_concatenation(node):

    expr = new_expression(
        expr_type="multiple_concat",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    expr["count"] = parse_expression(
        node.expression
    )

    expr["concat"] = parse_expression( node.concatenation)

    expr["children"] = [
        expr["count"],
        expr["concat"],
    ]

    return expr


def parse_member_access(node):

    if node is None:
        return None

    expr = new_expression(
        expr_type="member_access",
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

    #
    # Base expression
    #
    expr["base"] = parse_expression(node.left)

    #
    # Member name
    #
    expr["member"] = None

    if hasattr(node, "right"):

        expr["member"] = parse_expression(node.right)


    expr["children"] = [

        expr["base"],
    
        expr["member"],
    ]

    return expr

def parse_conditional_predicate(node):
    """
    Parse ConditionalPredicateSyntax.

    This node is only a wrapper around the real predicate expression.
    """

    if hasattr(node, "conditions"):

        conditions = list(node.conditions)

        if conditions:

            pattern = conditions[0]

            if hasattr(pattern, "expr"):
                return parse_expression(pattern.expr)

    return parse_unknown(node)


def parse_expression(node):
    """
    Convert PySlang expression into RTL Expression IR.
    """

    if node is None:
        return None

    if type(node).__name__ == "Token":

        print("=" * 80)
        print("Unexpected Token")
        print("=" * 80)
        print("Kind :", node.kind)
        print("Text :", get_node_text(node))

        frame = inspect.currentframe().f_back

        print("Called from:", frame.f_code.co_name)
        print("File       :", frame.f_code.co_filename)
        print("Line       :", frame.f_lineno)

        return parse_unknown(node)

    record_expression(type(node).__name__)
    #
    # Ignore punctuation tokens
    #
    if not hasattr(node, "kind"):
        return None

    kind = node.kind

    node_type = type(node).__name__

    #
    # Identifier
    #
    if kind == SyntaxKind.IdentifierName:
        return parse_identifier(node)

    #
    # Literals
    #
    elif kind in (
        SyntaxKind.IntegerLiteralExpression,
        SyntaxKind.IntegerVectorExpression,
        SyntaxKind.StringLiteralExpression,
        SyntaxKind.RealLiteralExpression,
        SyntaxKind.UnbasedUnsizedLiteralExpression,
    ):
        return parse_literal(node)

    #
    # Function call
    #
    elif kind == SyntaxKind.InvocationExpression:
        return parse_call(node)

    #
    # Unary/Binary operators
    #

    elif kind in (
    
        SyntaxKind.AddExpression,
        SyntaxKind.SubtractExpression,
        SyntaxKind.MultiplyExpression,
        SyntaxKind.DivideExpression,
        SyntaxKind.ModExpression,
        SyntaxKind.EqualityExpression,
        SyntaxKind.InequalityExpression,
        SyntaxKind.CaseEqualityExpression,
        SyntaxKind.CaseInequalityExpression,
        SyntaxKind.GreaterThanExpression,
        SyntaxKind.GreaterThanEqualExpression,
        SyntaxKind.LessThanExpression,
        SyntaxKind.LessThanEqualExpression,
        SyntaxKind.LogicalAndExpression,
        SyntaxKind.LogicalOrExpression,
        SyntaxKind.BinaryAndExpression,
        SyntaxKind.BinaryOrExpression,
        SyntaxKind.BinaryXorExpression,
        SyntaxKind.BinaryXnorExpression,
        SyntaxKind.LogicalShiftLeftExpression,
        SyntaxKind.LogicalShiftRightExpression,
        SyntaxKind.ArithmeticShiftLeftExpression,
        SyntaxKind.ArithmeticShiftRightExpression,
        SyntaxKind.PowerExpression,
    
    ):
        return parse_binary(node)

    #
    # Complex expressions
    #
    elif kind in (
        SyntaxKind.MemberAccessExpression,
        SyntaxKind.ScopedName,
    ):
        return parse_member_access(node)
   
    #
    # Concatenation
    #
    elif kind == SyntaxKind.ConcatenationExpression:
        return parse_concatenation(node)
    
    elif kind == SyntaxKind.MultipleConcatenationExpression:
        return parse_multiple_concatenation(node)
    
    elif kind == SyntaxKind.ParenthesizedExpression:
        return parse_parenthesized_expression(node)

    elif kind == SyntaxKind.IdentifierSelectName:
        return parse_identifier_select(node)
    
    elif kind in (
        SyntaxKind.ElementSelect,
        SyntaxKind.ElementSelectExpression,
    ):
        return parse_element_select(node)
    
    elif kind == SyntaxKind.BitSelect:
        return parse_bit_select(node)
    
    elif kind in (
        SyntaxKind.SimpleRangeSelect,
        SyntaxKind.AscendingRangeSelect,
        SyntaxKind.DescendingRangeSelect,
    ):
        return parse_range_select(node)

    elif kind == SyntaxKind.ConditionalPredicate:
        return parse_conditional_predicate(node)

    elif kind == SyntaxKind.ConditionalExpression:
        return parse_conditional(node)

    #print(type(node).__name__, node.kind)

    #
    # AST-class based dispatch
    #
    elif node_type == "PrefixUnaryExpressionSyntax":
        return parse_prefix_unary(node)

    elif node_type == "SimplePropertyExprSyntax":
        return parse_simple_property(node)

    elif node_type == "SimpleSequenceExprSyntax":
        return parse_simple_sequence(node)

    elif kind == SyntaxKind.CastExpression:
        return parse_cast(node)

    #
    # Unknown
    #
    return parse_unknown(node)


def parse_identifier(node):
    """
    Parse IdentifierNameSyntax.
    """

    return new_identifier(
        name=get_node_text(node),
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )

def parse_literal(node):
    """
    Parse literal expression.
    """

    return new_constant(
        value=get_node_text(node),
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )


def parse_unknown(node):
    """
    Unknown expression.
    """
    record_unknown(type(node).__name__)

    return new_unknown(
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )


def parse_binary(node):
    """
    Parse binary expressions.

    Examples:
        scnt + 1
        dcnt - 4'h1
        scnt == 4'hF
        mcnt == 2'h3
    """

    #
    # Parse left operand
    #
    lhs = parse_expression(node.left)

    #
    # Parse right operand
    #
    rhs = parse_expression(node.right)

    #
    # Operator
    #
    operator = str(node.operatorToken).strip()

    #
    # Create IR
    #
    return new_binary(
        operator=operator,
        lhs=lhs,
        rhs=rhs,
        text=get_node_text(node),
        syntax_kind=str(node.kind),
        )


def parse_call(node):
    """
    Parse InvocationExpressionSyntax

    Examples
    --------
        bin2grey(ptr)

        $display(...)

        $clog2(...)
    """

    #
    # Function name
    #
    function_name = get_node_text(node.left)

    #
    # Arguments
    #
    arguments = []

    for arg in node.arguments:

        #
        # Some pyslang versions wrap arguments.
        #
        expr = getattr(arg, "expr", arg)

        if not is_expression_node(expr):
            continue

        arg_ir = parse_expression(expr)

        if arg_ir is not None:
            arguments.append(arg_ir)

    return new_call(
        function=function_name,
        arguments=arguments,
        text=get_node_text(node),
        syntax_kind=str(node.kind),
    )


