"""reaction_balance: same species, conserved atoms and charge, lowest integer coefficients."""

from collections import Counter
from math import gcd

import sympy as sp
from pydantic import Field

from quizz import chem
from quizz.checkers.base import Checker, ParamError, Params
from quizz.checkers.equiv import direct_runner
from quizz.verdict import Verdict


class ReactionParams(Params):
    reactants: list[str] = Field(min_length=1)
    products: list[str] = Field(min_length=1)


def _key(species: chem.Species):
    return frozenset(species.atoms.items()), species.charge


def balance(reactants: list[chem.Species], products: list[chem.Species]) -> list[int] | None:
    """Smallest positive integer coefficients, or None if not uniquely balanceable."""
    species = reactants + products
    elements = sorted({el for s in species for el in s.atoms})
    rows = [[s.atoms.get(el, 0) * (1 if i < len(reactants) else -1) for i, s in enumerate(species)] for el in elements]
    rows.append([s.charge * (1 if i < len(reactants) else -1) for i, s in enumerate(species)])
    null = sp.Matrix(rows).nullspace()
    if len(null) != 1:
        return None
    vec = null[0]
    lcm = sp.ilcm(*(sp.fraction(v)[1] for v in vec))
    ints = [int(v * lcm) for v in vec]
    if all(v < 0 for v in ints):
        ints = [-v for v in ints]
    if any(v <= 0 for v in ints):
        return None
    g = 0
    for v in ints:
        g = gcd(g, v)
    return [v // g for v in ints]


class ReactionBalance(Checker):
    name = "reaction_balance"
    widget = "text"
    Params = ReactionParams
    description = "Balanced chemical equation typed as text, e.g. `C3H8 + 5O2 -> 3CO2 + 4H2O`."
    example = {"checker": "reaction_balance", "params": {"reactants": ["C3H8", "O2"], "products": ["CO2", "H2O"]}}

    def _species(self, p: ReactionParams):
        return [chem.parse_formula(f) for f in p.reactants], [chem.parse_formula(f) for f in p.products]

    def semantic_errors(self, p):
        errors = []
        for side in ("reactants", "products"):
            for i, formula in enumerate(getattr(p, side)):
                try:
                    chem.parse_formula(formula)
                except ValueError as exc:
                    errors.append(ParamError(f"{side}/{i}", "bad_formula", str(exc)))
        if not errors and balance(*self._species(p)) is None:
            errors.append(ParamError("reactants", "unbalanceable", "these species cannot be balanced uniquely"))
        return errors

    def parse_answer(self, answer, p):
        return chem.parse_reaction(answer)

    def check_value(self, value: chem.Reaction, p, *, literal=None, seed=0, runner=direct_runner):
        reactants, products = self._species(p)
        for given, expected in ((value.reactants, reactants), (value.products, products)):
            if Counter(_key(s) for _, s in given) != Counter(_key(s) for s in expected):
                return Verdict("fail", "species do not match the reaction")
        coefs = [c for c, _ in value.reactants + value.products]
        if any(c <= 0 for c in coefs):
            return Verdict("fail", "coefficients must be positive integers")
        left, right = Counter(), Counter()
        for c, s in value.reactants:
            for el, n in s.atoms.items():
                left[el] += c * n
        for c, s in value.products:
            for el, n in s.atoms.items():
                right[el] += c * n
        for el in sorted(set(left) | set(right)):
            if left[el] != right[el]:
                return Verdict("fail", f"{el} is not conserved: {left[el]} on the left, {right[el]} on the right")
        charge_l = sum(c * s.charge for c, s in value.reactants)
        charge_r = sum(c * s.charge for c, s in value.products)
        if charge_l != charge_r:
            return Verdict("fail", f"charge is not conserved: {charge_l} on the left, {charge_r} on the right")
        g = 0
        for c in coefs:
            g = gcd(g, c)
        if g > 1:
            return Verdict("fail", "coefficients are not in lowest terms")
        return Verdict("pass")

    def mutants(self, p):
        reactants, products = self._species(p)
        coefs = balance(reactants, products)
        if coefs is None:
            return []
        species = reactants + products
        out = []
        for bump in (0, len(species) - 1):
            c = list(coefs)
            c[bump] += 1
            out.append(
                chem.Reaction(
                    list(zip(c[: len(reactants)], reactants)),
                    list(zip(c[len(reactants) :], products)),
                )
            )
        return out
