"""Small arithmetic language evaluated with physical units, never Python eval."""

import ast
import operator

import numpy as np
import pint

from .common import StantonError, require

UNITS = pint.UnitRegistry()
UNITS.define("USD = [currency]")
UNITS.define("person = [population]")
UNITS.define("count = []")
UNITS.define("dozen = 12 * count")
FUNCTIONS = {"abs": np.abs, "sqrt": np.sqrt, "log": np.log, "exp": np.exp,
             "minimum": np.minimum, "maximum": np.maximum}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow}


def unit(value):
    try:
        require(isinstance(value, str) and bool(value.strip()), "Units must not be blank.")
        return UNITS.Unit(value)
    except (pint.errors.PintError, ValueError, TypeError) as exc:
        raise StantonError(f"Unknown or invalid unit {value!r}: {exc}", "invalid_unit") from exc


def parse(expression):
    require(isinstance(expression, str) and 0 < len(expression) <= 4096, "Expression must have 1–4096 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise StantonError(f"Invalid expression: {exc}", "invalid_expression") from exc
    require(len(list(ast.walk(tree))) <= 256, "Expression is too complex.")
    dependencies = set()

    def visit(node):
        if isinstance(node, ast.Constant):
            require(type(node.value) in (int, float) and np.isfinite(node.value), "Only finite numeric literals are allowed.")
        elif isinstance(node, ast.Name):
            require(node.id not in FUNCTIONS, "Function names must be called.")
            dependencies.add(node.id)
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            visit(node.left)
            visit(node.right)
            if isinstance(node.op, ast.Pow):
                exponent = node.right
                if isinstance(exponent, ast.UnaryOp) and isinstance(exponent.op, (ast.UAdd, ast.USub)):
                    exponent = exponent.operand
                require(isinstance(exponent, ast.Constant) and abs(exponent.value) <= 100,
                        "Powers require a constant exponent with magnitude at most 100.")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            visit(node.operand)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            require(not node.keywords and len(node.args) == (2 if node.func.id in {"minimum", "maximum"} else 1),
                    "Incorrect expression function arguments.")
            for arg in node.args:
                visit(arg)
        else:
            raise StantonError("Expressions allow arithmetic and abs/sqrt/log/exp/minimum/maximum only.", "invalid_expression")

    visit(tree.body)
    return tree.body, dependencies


def evaluate(tree, values):
    def walk(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp):
            return BINARY[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp):
            return -walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand)
        return FUNCTIONS[node.func.id](*(walk(arg) for arg in node.args))

    try:
        with np.errstate(all="ignore"):
            return walk(tree)
    except pint.errors.DimensionalityError as exc:
        raise StantonError(str(exc), "unit_mismatch") from exc
    except (ValueError, TypeError, ZeroDivisionError, OverflowError, pint.errors.PintError) as exc:
        raise StantonError(f"Expression evaluation failed: {exc}", "invalid_arithmetic") from exc


def magnitude(value, units, n):
    try:
        if not isinstance(value, UNITS.Quantity):
            value = UNITS.Quantity(value, "dimensionless")
        result = np.broadcast_to(np.asarray(value.to(unit(units)).magnitude, dtype=float), (n,)).copy()
    except pint.errors.DimensionalityError as exc:
        raise StantonError(str(exc), "unit_mismatch") from exc
    require(np.all(np.isfinite(result)), "Expression produced nonfinite samples; no draws were discarded.", "invalid_arithmetic")
    return result
