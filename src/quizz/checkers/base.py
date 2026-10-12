"""Checker interface: params schema, answer parsing, value checking, mutants."""

from dataclasses import dataclass
from typing import Any, ClassVar

import sympy as sp
from pydantic import BaseModel, ConfigDict, ValidationError

from quizz.checkers.equiv import Equiv, Runner, direct_runner
from quizz.mathparse import ParseError, parse_expr
from quizz.verdict import Verdict

ASSUMPTIONS = {"real": {"real": True}, "positive": {"positive": True}, "integer": {"integer": True}, "complex": {}}


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class ParamError:
    path: str  # slash-separated, relative to the CheckSpec params
    code: str
    message: str


class Checker:
    name: ClassVar[str]
    widget: ClassVar[str]  # "math" or "text"
    Params: ClassVar[type[Params]]
    example: ClassVar[dict[str, Any]]
    description: ClassVar[str]

    # ----- params
    def parse_params(self, raw: dict) -> Params:
        return self.Params.model_validate(raw)

    def validate_params(self, raw: dict) -> list[ParamError]:
        try:
            params = self.parse_params(raw)
        except ValidationError as exc:
            return [
                ParamError("/".join(str(p) for p in err["loc"]), err["type"], err["msg"]) for err in exc.errors()
            ]
        return self.semantic_errors(params)

    def semantic_errors(self, params: Params) -> list[ParamError]:
        return []

    # ----- grading
    def parse_answer(self, answer: str, params: Params) -> Any:
        raise NotImplementedError

    def check(self, answer: str, params: Params, *, seed: int = 0, runner: Runner = direct_runner) -> Verdict:
        try:
            value = self.parse_answer(answer, params)
        except ValueError as exc:  # ParseError is a ValueError
            return Verdict("parse_error", str(exc))
        return self.check_value(value, params, literal=answer, seed=seed, runner=runner)

    def check_value(
        self, value: Any, params: Params, *, literal: str | None = None, seed: int = 0, runner: Runner = direct_runner
    ) -> Verdict:
        raise NotImplementedError

    def mutants(self, params: Params) -> list[Any]:
        """Wrong answers that a non-vacuous CheckSpec must reject."""
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "name": self.name,
            "widget": self.widget,
            "description": self.description,
            "params_schema": self.Params.model_json_schema(),
            "example": self.example,
        }


def make_symbols(vars: dict[str, str]) -> dict[str, sp.Symbol]:
    return {name: sp.Symbol(name, **ASSUMPTIONS[kind]) for name, kind in vars.items()}


def parse_symbol(latex: str) -> sp.Symbol:
    value = parse_expr(latex)
    if not isinstance(value, sp.Symbol):
        raise ParseError(f"{latex!r} is not a single variable")
    return value


def equiv_verdict(result: Equiv, wrong: str) -> Verdict:
    if result.status == "proven":
        return Verdict("pass")
    if result.status == "numeric":
        return Verdict("pass_numeric", "matched at every sample point")
    if result.status == "different":
        return Verdict("fail", wrong, result.counterexample)
    return Verdict("undecided", "could not decide equivalence")


def expression_mutants(expected: sp.Expr) -> list[sp.Expr]:
    out = [2 * expected, -expected]
    expanded = sp.expand(expected)
    if expanded.is_Add and len(expanded.args) >= 2:
        out.append(expanded - expanded.args[0])
    return [m for m in out if m != expected]


def latex_error(path: str, latex: str, **kwargs) -> list[ParamError]:
    try:
        parse_expr(latex, **kwargs)
    except ParseError as exc:
        return [ParamError(path, "parse_error", str(exc))]
    return []
