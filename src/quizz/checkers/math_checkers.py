"""expr_equiv, antiderivative and transform checkers."""

import re
from typing import Literal

import sympy as sp
from pydantic import Field

from quizz.checkers.base import (
    Checker,
    ParamError,
    Params,
    equiv_verdict,
    expression_mutants,
    latex_error,
    make_symbols,
    parse_symbol,
)
from quizz.checkers.equiv import direct_runner, equivalent
from quizz.mathparse import ParseError, parse_expr
from quizz.verdict import Verdict

VarKind = Literal["real", "positive", "integer", "complex"]


class ExprEquivParams(Params):
    expected: str
    vars: dict[str, VarKind] = Field(default_factory=dict)


class ExprEquiv(Checker):
    name = "expr_equiv"
    widget = "math"
    Params = ExprEquivParams
    description = "Answer must be mathematically equivalent to `expected`."
    example = {"checker": "expr_equiv", "params": {"expected": r"\frac{x^2}{2}", "vars": {"x": "real"}}}

    def _expected(self, p: ExprEquivParams) -> sp.Expr:
        return parse_expr(p.expected, symbols=make_symbols(p.vars))

    def semantic_errors(self, p):
        return latex_error("expected", p.expected, symbols=make_symbols(p.vars))

    def parse_answer(self, answer, p):
        return parse_expr(answer, symbols=make_symbols(p.vars))

    def check_value(self, value, p, *, literal=None, seed=0, runner=direct_runner):
        result = equivalent(value, self._expected(p), seed=seed, runner=runner)
        return equiv_verdict(result, "not equivalent to the expected answer")

    def mutants(self, p):
        return expression_mutants(self._expected(p))


class AntiderivativeParams(Params):
    integrand: str
    var: str


class Antiderivative(Checker):
    name = "antiderivative"
    widget = "math"
    Params = AntiderivativeParams
    description = "Answer differentiated with respect to `var` must equal `integrand`; constants such as C are allowed."
    example = {"checker": "antiderivative", "params": {"integrand": r"xe^{x}", "var": "x"}}

    def semantic_errors(self, p):
        errors = latex_error("integrand", p.integrand)
        try:
            parse_symbol(p.var)
        except ParseError as exc:
            errors.append(ParamError("var", "not_a_symbol", str(exc)))
        return errors

    def parse_answer(self, answer, p):
        return parse_expr(answer)

    def check_value(self, value, p, *, literal=None, seed=0, runner=direct_runner):
        if value.has(sp.Integral):
            return Verdict("fail", "the answer still contains an unevaluated integral")
        var = parse_symbol(p.var)
        result = equivalent(sp.diff(value, var), parse_expr(p.integrand), seed=seed, runner=runner)
        return equiv_verdict(result, "differentiating your answer does not give the integrand")

    def mutants(self, p):
        antiderivative = sp.integrate(parse_expr(p.integrand), parse_symbol(p.var))
        if antiderivative.has(sp.Integral):
            return []
        return expression_mutants(antiderivative)


_ROC = re.compile(
    r"^(?:\\(?:mathrm|operatorname)\{Re\}\((?P<re>[A-Za-z])\)|\|(?P<abs>[A-Za-z])\|)\s*(?P<op>>|<|\\gt|\\lt)\s*(?P<bound>.+)$"
)


def parse_roc(latex: str) -> tuple[str, str, sp.Expr]:
    """`\\mathrm{Re}(s)>-2` or `|z|>0.5` -> (kind, op, bound)."""
    src = re.sub(r"\\left|\\right|\\[,;: !]|\s+", "", latex.strip())
    m = _ROC.match(src)
    if not m:
        raise ParseError(r"region of convergence must look like \mathrm{Re}(s)>a or |z|>a")
    kind = "re" if m.group("re") else "abs"
    op = {"\\gt": ">", "\\lt": "<"}.get(m.group("op"), m.group("op"))
    return kind, op, parse_expr(m.group("bound"))


def _split_top_level_comma(latex: str) -> tuple[str, str | None]:
    depth = 0
    for i, c in enumerate(latex):
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c == "," and depth == 0:
            return latex[:i], latex[i + 1 :]
    return latex, None


class TransformParams(Params):
    kind: Literal["laplace", "fourier", "z"]
    expected: str
    var: str
    region_of_convergence: str | None = None


class Transform(Checker):
    name = "transform"
    widget = "math"
    Params = TransformParams
    description = (
        "Transform answer must be equivalent to `expected`. If `region_of_convergence` is set, the answer is "
        r"`F, ROC`, e.g. `\frac{1}{s+2}, \mathrm{Re}(s)>-2`."
    )
    example = {
        "checker": "transform",
        "params": {"kind": "laplace", "expected": r"\frac{1}{s+2}", "var": "s", "region_of_convergence": r"\mathrm{Re}(s)>-2"},
    }

    def semantic_errors(self, p):
        errors = latex_error("expected", p.expected)
        try:
            parse_symbol(p.var)
        except ParseError as exc:
            errors.append(ParamError("var", "not_a_symbol", str(exc)))
        if p.region_of_convergence is not None:
            try:
                parse_roc(p.region_of_convergence)
            except ParseError as exc:
                errors.append(ParamError("region_of_convergence", "parse_error", str(exc)))
        return errors

    def parse_answer(self, answer, p):
        expr_part, roc_part = _split_top_level_comma(answer)
        roc = parse_roc(roc_part) if roc_part is not None else None
        return parse_expr(expr_part), roc

    def check_value(self, value, p, *, literal=None, seed=0, runner=direct_runner):
        expr, roc = value
        verdict = equiv_verdict(
            equivalent(expr, parse_expr(p.expected), seed=seed, runner=runner), "transform is not equivalent to the expected answer"
        )
        if not verdict.passed or p.region_of_convergence is None:
            return verdict
        if roc is None:
            return Verdict("fail", "missing region of convergence")
        kind, op, bound = parse_roc(p.region_of_convergence)
        if roc[0] != kind or roc[1] != op or sp.simplify(roc[2] - bound) != 0:
            return Verdict("fail", "region of convergence is wrong")
        return verdict

    def mutants(self, p):
        roc = parse_roc(p.region_of_convergence) if p.region_of_convergence else None
        return [(m, roc) for m in expression_mutants(parse_expr(p.expected))]
