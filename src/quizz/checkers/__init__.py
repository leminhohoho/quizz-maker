"""Checker registry. Add a checker by subclassing `Checker` and listing it here."""

from quizz.checkers.base import Checker, ParamError
from quizz.checkers.math_checkers import Antiderivative, ExprEquiv, Transform
from quizz.checkers.numeric_units import NumericUnits
from quizz.checkers.reaction import ReactionBalance

REGISTRY: dict[str, Checker] = {
    c.name: c for c in (ExprEquiv(), Antiderivative(), NumericUnits(), ReactionBalance(), Transform())
}


def get(name: str) -> Checker:
    try:
        return REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown checker {name!r}; available: {', '.join(REGISTRY)}") from None


__all__ = ["REGISTRY", "Checker", "ParamError", "get"]
