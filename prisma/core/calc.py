"""Sicherer Taschenrechner für den Kompass (wertet nur einen geprüften AST aus)."""

from __future__ import annotations

import ast
import math
import operator
import re

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt, "wurzel": math.sqrt,
    "sin": lambda x: math.sin(math.radians(x)),
    "cos": lambda x: math.cos(math.radians(x)),
    "tan": lambda x: math.tan(math.radians(x)),
    "asin": lambda x: math.degrees(math.asin(x)),
    "acos": lambda x: math.degrees(math.acos(x)),
    "atan": lambda x: math.degrees(math.atan(x)),
    "ln": math.log, "log": math.log10, "log2": math.log2,
    "abs": abs, "round": round, "runden": round,
    "floor": math.floor, "ceil": math.ceil, "exp": math.exp,
    "fak": math.factorial, "fact": math.factorial,
}
_CONSTS = {"pi": math.pi, "π": math.pi, "e": math.e, "tau": math.tau, "phi": (1 + 5**0.5) / 2}
_LOOKS_MATHY = re.compile(r"^[\s0-9.,+\-*/%^()πa-z×÷²³]+$", re.IGNORECASE)


class CalcError(ValueError):
    pass


def _prepare(expr: str) -> str:
    expr = expr.strip().lstrip("=").strip()
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**").replace("²", "**2").replace("³", "**3")
    if "," in expr:
        expr = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", expr)  # 1.234,5 → 1234,5
    expr = re.sub(r"(?<=\d),(?=\d)", ".", expr)  # deutsches Dezimalkomma
    # Prozent: "20% von 150" / "20% of 150" → (20/100)*150 ; "50%" → 0.5
    expr = re.sub(r"([\d.]+)\s*%\s*(?:von|of)\s*", r"(\1/100)*", expr, flags=re.IGNORECASE)
    expr = re.sub(r"([\d.]+)\s*%(?!\s*[\d(])", r"(\1/100)", expr)
    expr = re.sub(r"(\d)\s*([a-zπ(])", r"\1*\2", expr)  # 2pi, 3(4+1)
    expr = re.sub(r"\)\s*\(", ")*(", expr)
    return expr


def _compute(node):
    if isinstance(node, ast.Expression):
        return _compute(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _compute(node.left), _compute(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 1000 or abs(left) > 1e12):
            raise CalcError("Zahl zu groß")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_compute(node.operand))
    if isinstance(node, ast.Name) and node.id.lower() in _CONSTS:
        return _CONSTS[node.id.lower()]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.lower() in _FUNCS:
        if node.keywords or not 1 <= len(node.args) <= 2:
            raise CalcError("Ungültiger Funktionsaufruf")
        args = [_compute(a) for a in node.args]
        if node.func.id.lower() in ("fak", "fact") and args[0] > 170:
            raise CalcError("Zahl zu groß")
        return _FUNCS[node.func.id.lower()](*args)
    raise CalcError("Kein gültiger Ausdruck")


def calculate(expr: str) -> float:
    prepared = _prepare(expr)
    if not prepared or len(prepared) > 200:
        raise CalcError("Leerer Ausdruck")
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError as exc:
        raise CalcError("Syntaxfehler") from exc
    try:
        value = _compute(tree)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError) as exc:
        raise CalcError(str(exc) or "Rechenfehler") from exc
    if isinstance(value, complex):
        raise CalcError("Komplexe Zahl")
    return value


def looks_like_math(query: str) -> bool:
    """Heuristik: nur dann rechnen, wenn die Eingabe nach einer Rechnung aussieht."""
    q = query.strip()
    if q.startswith("="):
        return True
    if not _LOOKS_MATHY.match(q) or not re.search(r"\d|π|pi", q):
        return False
    has_operator = re.search(r"[+\-*/%^×÷²³]|\b(?:sqrt|wurzel|sin|cos|tan|ln|log|abs|fak)\s*\(", q)
    return bool(has_operator) and not re.fullmatch(r"[\d.,]+", q)


def format_number(value: float, decimal_comma: bool = True) -> str:
    """Formatiert ohne Rundungsrauschen, mit Tausenderpunkten (deutsch)."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if isinstance(value, int):
        text = f"{value:,}"
        return text.replace(",", ".") if decimal_comma else text
    if abs(value) >= 1e15 or (abs(value) < 1e-6 and value != 0):
        text = f"{value:.6g}"
        return text.replace(".", ",") if decimal_comma else text
    text = f"{value:,.10f}".rstrip("0").rstrip(".")
    if decimal_comma:
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text
