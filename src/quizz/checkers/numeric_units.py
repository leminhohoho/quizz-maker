"""numeric_units: a number with units, within tolerance, optional significant figures."""

import sympy as sp
from pydantic import Field

from quizz import units as U
from quizz.checkers.base import Checker, ParamError, Params
from quizz.checkers.equiv import direct_runner
from quizz.mathparse import parse_expr
from quizz.verdict import Verdict


class NumericUnitsParams(Params):
    expected: float
    unit: str = ""
    rel_tol: float = Field(0.01, ge=0)
    abs_tol: float | None = Field(None, ge=0)
    sig_figs: int | None = Field(None, ge=1)


def _exact(x: float) -> sp.Rational:
    return sp.Rational(repr(x))


def _unit(text: str) -> sp.Expr:
    return U.unit_expr(text) if text.strip() else sp.Integer(1)


def _fmt_dims(dims: dict[str, int]) -> str:
    return " ".join(f"{k}^{v}" if v != 1 else k for k, v in sorted(dims.items())) or "dimensionless"


class NumericUnits(Checker):
    name = "numeric_units"
    widget = "math"
    Params = NumericUnitsParams
    description = (
        "A number with units. Converted to `unit`, it must be within max(rel_tol*|expected|, abs_tol) of `expected`; "
        "if `sig_figs` is set the typed number must have exactly that many significant figures."
    )
    example = {"checker": "numeric_units", "params": {"expected": 2.88e-4, "unit": "J", "rel_tol": 0.01, "sig_figs": 3}}

    def semantic_errors(self, p):
        try:
            _unit(p.unit)
        except ValueError as exc:
            return [ParamError("unit", "unknown_unit", str(exc))]
        return []

    def parse_answer(self, answer, p):
        return parse_expr(answer, units=U.unit_expr)

    def check_value(self, value, p, *, literal=None, seed=0, runner=direct_runner):
        try:
            got, got_dims = U.split(value)
        except U.DimensionError as exc:
            return Verdict("fail", f"inconsistent dimensions: {exc}")
        expected, exp_dims = U.split(_exact(p.expected) * _unit(p.unit))
        if got_dims != exp_dims:
            return Verdict("fail", f"wrong dimension: expected {_fmt_dims(exp_dims)}, got {_fmt_dims(got_dims)}")
        if got.free_symbols or not got.is_number:
            return Verdict("fail", "the answer must be a number")
        scale = U.split(_unit(p.unit))[0]
        tol = _exact(p.rel_tol) * abs(expected)
        if p.abs_tol is not None:
            tol = max(tol, _exact(p.abs_tol) * scale)
        if abs(sp.nsimplify(got) - expected) > tol:
            return Verdict("fail", "value is outside tolerance")
        if p.sig_figs is not None and literal is not None:
            figs = U.sig_figs(literal)
            if figs != p.sig_figs:
                return Verdict("fail", f"expected {p.sig_figs} significant figures, got {figs}")
        return Verdict("pass")

    def mutants(self, p):
        correct = _exact(p.expected) * _unit(p.unit)
        candidates = [correct * sp.Rational(11, 10), -correct, correct * 1000]
        return [m for m in candidates if m != correct]
