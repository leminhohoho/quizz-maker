"""Step-by-step exercise grading: `chain` and `derivation` modes."""

import itertools
import re
import zlib
from dataclasses import dataclass, field

import sympy as sp

from quizz import units as U
from quizz.checkers import get
from quizz.checkers.equiv import DEFAULT_TIMEOUT, Timeout, equivalent
from quizz.mathparse import Line, ParseError, parse_expr, parse_line
from quizz.mathparse.tokens import tokenize
from quizz.schema import Exercise
from quizz.verdict import Verdict

CONSTANT = re.compile(r"^C(_.*)?$")
DERIVATION_REL_TOL = sp.Rational(1, 100)
FUNCTIONS = {"heaviside": sp.Heaviside, "dirac": sp.DiracDelta}
MAX_RELATION_COMBOS = 30


def seed_for(key: str, *parts) -> int:
    return zlib.crc32(":".join(map(str, (key, *parts))).encode())


# ------------------------------------------------------------------ parsing context
@dataclass
class Env:
    symbols: dict[str, sp.Symbol] = field(default_factory=dict)
    functions: dict = field(default_factory=dict)
    atoms: list[str] = field(default_factory=list)
    units: object = None

    def parse(self, latex: str) -> Line:
        return parse_line(latex, symbols=self.symbols, functions=self.functions, atoms=self.atoms, units=self.units)

    def expr(self, latex: str) -> sp.Expr:
        return parse_expr(latex, symbols=self.symbols, functions=self.functions, atoms=self.atoms, units=self.units)

    def symbol(self, key: str) -> sp.Symbol:
        return self.symbols[_canonical(key)[0]]


def _canonical(key: str) -> tuple[str, bool]:
    """(symbol name, is_atom) for a context key such as `q`, `v_{0}` or `\\Delta H`."""
    if len(tokenize(key)) > 1:
        try:
            value = parse_expr(key)
            if isinstance(value, sp.Symbol):
                return value.name, False
        except ParseError:
            pass
        return key, True
    value = parse_expr(key) if key != "e" else sp.Symbol("e")
    return (value.name, False) if isinstance(value, sp.Symbol) else (key, True)


def build_env(ex: Exercise, *, units: bool) -> Env:
    env = Env(units=U.unit_expr if units else None)
    decls = {**{k: [] for k in ex.context.givens}, **{k: d.assumptions for k, d in ex.context.symbols.items()}}
    for key, assumptions in decls.items():
        name, is_atom = _canonical(key)
        env.symbols[name] = sp.Symbol(name, **{a: True for a in assumptions})
        if is_atom:
            env.atoms.append(key)
    env.functions = {name: FUNCTIONS[kind] for name, kind in ex.context.functions.items()}
    return env


def last_segment(latex: str) -> str:
    """Text after the last top-level `=` / `\\approx` (the literal the final value was typed as)."""
    depth, cut = 0, 0
    i = 0
    while i < len(latex):
        c = latex[i]
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
        elif depth == 0 and c == "=":
            cut = i + 1
        elif depth == 0 and latex.startswith("\\approx", i):
            cut = i + len("\\approx")
        i += 1
    return latex[cut:].strip()


# ------------------------------------------------------------------ results
@dataclass
class StepsResult:
    lines: list[dict]
    final: Verdict

    @property
    def pending(self) -> list[int]:
        return [i for i, line in enumerate(self.lines) if line["verdict"]["status"] == "undecided"]

    def to_dict(self) -> dict:
        return {"lines": self.lines, "final": self.final.to_dict()}


def _line(step: dict, verdict: Verdict) -> dict:
    return {"latex": step["latex"], "justification": step.get("justification", ""), "verdict": verdict.to_dict()}


def _from_equiv(result, wrong: str) -> Verdict:
    if result.status == "proven":
        return Verdict("pass")
    if result.status == "numeric":
        return Verdict("pass_numeric", "matched at every sample point")
    if result.status == "different":
        return Verdict("fail", wrong, result.counterexample)
    return Verdict("undecided", "could not decide this step")


def _worst(a: Verdict, b: Verdict) -> Verdict:
    rank = {"pass": 0, "pass_numeric": 1, "undecided": 2, "fail": 3}
    return b if rank[b.status] > rank[a.status] else a


def _doit(expr):
    return expr.doit()


def _solve(equations, unknowns):
    return sp.solve(equations, list(unknowns), dict=True)


class _Grader:
    def __init__(self, ex: Exercise, seed_key: str, runner):
        self.ex = ex
        self.seed_key = seed_key
        self.runner = runner
        checker = get(ex.final.checker)
        self.final_checker = checker
        self.final_params = checker.parse_params(ex.final.params)

    def run(self, fn, *args):
        return self.runner(fn, *args, timeout=DEFAULT_TIMEOUT)

    def equiv(self, a, b, *where):
        return equivalent(a, b, seed=seed_for(self.seed_key, *where), runner=self.runner, timeout=DEFAULT_TIMEOUT)

    def final_verdict(self, value, literal: str, raw_latex: str, *where) -> Verdict:
        seed = seed_for(self.seed_key, "final", *where)
        if self.final_checker.widget == "text":
            return self.final_checker.check(raw_latex, self.final_params, seed=seed, runner=self.runner)
        return self.final_checker.check_value(value, self.final_params, literal=literal, seed=seed, runner=self.runner)


# ------------------------------------------------------------------ chain mode
class ChainGrader(_Grader):
    def __init__(self, ex, seed_key, runner):
        super().__init__(ex, seed_key, runner)
        self.env = build_env(ex, units=False)
        self.start = self.env.expr(ex.start)
        self.var = self._integration_var(self.start)
        self.defs: dict[sp.Symbol, sp.Expr] = {}

    @staticmethod
    def _integration_var(expr):
        for integral in expr.atoms(sp.Integral):
            return integral.limits[0][0]
        free = [s for s in expr.free_symbols if not CONSTANT.match(s.name)]
        return free[0] if len(free) == 1 else None

    def prepare(self, expr):
        if any(lim[0] in self.defs for i in expr.atoms(sp.Integral) for lim in i.limits):
            expr = self.run(_doit, expr)
            if expr.has(sp.Integral):
                raise Timeout("could not evaluate the integral after substitution")
        for _ in range(len(self.defs) + 1):
            expr = expr.subs(self.defs)
        return expr

    def compare(self, a, b, *where) -> Verdict:
        try:
            a, b = self.prepare(a), self.prepare(b)
        except Timeout:
            return Verdict("undecided", "could not evaluate this step")
        indefinite = any(len(lim) == 1 for e in (a, b) for i in e.atoms(sp.Integral) for lim in i.limits)
        constants = any(CONSTANT.match(s.name) for s in a.free_symbols | b.free_symbols)
        if indefinite or constants:
            if self.var is None:
                return Verdict("undecided", "cannot tell the integration variable")
            a, b = sp.diff(a, self.var), sp.diff(b, self.var)
        return _from_equiv(self.equiv(a, b, *where), "not equal to the previous line")

    def is_definition(self, line: Line, prev) -> bool:
        if len(line.parts) != 2 or not isinstance(line.parts[0], sp.Symbol):
            return False
        sym = line.parts[0]
        return sym not in self.start.free_symbols and sym not in self.defs and sym not in prev.free_symbols

    def grade(self, steps: list[dict]) -> StepsResult:
        lines, prev, last = [], self.start, None
        for i, step in enumerate(steps):
            try:
                line = self.env.parse(step["latex"])
            except ParseError as exc:
                lines.append(_line(step, Verdict("parse_error", str(exc))))
                last = None
                continue
            if self.is_definition(line, prev):
                self.defs[line.parts[0]] = line.parts[1]
                lines.append(_line(step, Verdict("pass", "definition")))
                continue
            verdict, before = Verdict("pass"), prev
            for k, part in enumerate(line.parts):
                verdict = _worst(verdict, self.compare(before, part, i, k))
                before = part
            lines.append(_line(step, verdict))
            prev = line.parts[-1]
            last = (prev, step["latex"], i)
        if last is None:
            return StepsResult(lines, Verdict("fail", "the last line could not be parsed"))
        value, latex, i = last
        try:
            value = self.prepare(value)
        except Timeout:
            return StepsResult(lines, Verdict("undecided", "could not evaluate the final answer"))
        return StepsResult(lines, self.final_verdict(value, last_segment(latex), latex, i))


# ------------------------------------------------------------------ derivation mode
class DerivationGrader(_Grader):
    def __init__(self, ex, seed_key, runner, reference_values: dict | None):
        super().__init__(ex, seed_key, runner)
        self.env = build_env(ex, units=True)
        self.givens = {
            self.env.symbol(name): sp.Rational(repr(g.value)) * (U.unit_expr(g.unit) if g.unit else 1)
            for name, g in ex.context.givens.items()
        }
        self.relations = []
        for rel in ex.context.relations:
            parts = self.env.parse(rel).parts
            self.relations.append(sp.Eq(parts[0], parts[1], evaluate=False))
        self.reference = reference_values
        self.defined: dict[sp.Symbol, sp.Expr] = {}
        self.tainted: set[sp.Symbol] = set()  # defined from a value that was already wrong

    def subst(self, expr):
        return expr.subs(self.givens).subs(self.defined)

    @staticmethod
    def numeric(value) -> bool:
        try:
            magnitude, _ = U.split(value)
        except U.DimensionError:
            return True  # numeric enough to report the dimension problem
        return not magnitude.free_symbols

    @staticmethod
    def all_equal(values) -> Verdict:
        try:
            split = [U.split(v) for v in values]
        except U.DimensionError as exc:
            return Verdict("fail", f"inconsistent dimensions: {exc}")
        dims = split[0][1]
        if any(d != dims for _, d in split[1:]):
            return Verdict("fail", "dimensions differ between the sides")
        mags = [complex(sp.N(m)) for m, _ in split]
        for a, b in itertools.pairwise(mags):
            if abs(a - b) > float(DERIVATION_REL_TOL) * max(abs(a), abs(b)) + 1e-12:
                return Verdict("fail", "the sides are not equal")
        return Verdict("pass")

    def against_reference(self, sym: sp.Symbol, value, sources: set) -> Verdict:
        if sources & self.tainted:
            self.tainted.add(sym)
            return Verdict("pass", "consistent with your earlier values")
        expected = (self.reference or {}).get(sym)
        if expected is None:
            return Verdict("pass", "definition")
        verdict = self.all_equal([value, expected])
        if verdict.passed:
            return verdict
        self.tainted.add(sym)
        if "dimension" in verdict.reason:
            return Verdict("fail", f"\\({sym.name}\\) has the wrong dimension")
        return Verdict("fail", f"\\({sym.name}\\) does not match the expected value")

    def by_relations(self, lhs, rhs, *where) -> Verdict:
        diff = lhs - rhs
        rel_syms = sorted(set().union(*(r.free_symbols for r in self.relations)) if self.relations else set(), key=str)
        unknown = diff.free_symbols - set(rel_syms) - set(U.BASE.values())
        if not self.relations or unknown:
            names = ", ".join(sorted(s.name for s in unknown))
            return Verdict("undecided", f"uses symbols outside the given relations: {names}" if unknown else "no relations to check against")
        prefer = diff.free_symbols
        combos = sorted(itertools.combinations(rel_syms, len(self.relations)), key=lambda c: -len(prefer & set(c)))
        for combo in combos[:MAX_RELATION_COMBOS]:
            try:
                solutions = self.run(_solve, self.relations, combo)
            except Timeout:
                continue
            if len(solutions) != 1 or len(solutions[0]) != len(combo):
                continue
            verdict = _from_equiv(self.equiv(diff.subs(solutions[0]), sp.Integer(0), *where), "does not follow from the relations")
            if verdict.status != "undecided":
                return verdict
        return Verdict("undecided", "could not derive this line from the relations")

    def check_line(self, line: Line, i: int, is_last: bool) -> Verdict:
        parts = line.parts
        if len(parts) == 1:
            return Verdict("undecided", "an expression on its own makes no claim") if not is_last else Verdict("pass")
        lhs = parts[0]
        fresh = isinstance(lhs, sp.Symbol) and lhs not in self.givens and lhs not in self.defined
        rest = parts[1:] if fresh else parts
        values = [self.subst(p) for p in rest]
        if all(self.numeric(v) for v in values):
            verdict = self.all_equal(values) if len(values) > 1 else Verdict("pass")
            if not verdict.passed or not fresh:
                return verdict
            self.defined[lhs] = values[-1]
            sources = set().union(*(p.free_symbols for p in rest))
            return self.against_reference(lhs, values[-1], sources)
        verdict = Verdict("pass")
        for k, (a, b) in enumerate(itertools.pairwise(parts)):
            verdict = _worst(verdict, self.by_relations(a, b, i, k))
        return verdict

    def grade(self, steps: list[dict]) -> StepsResult:
        lines, last = [], None
        for i, step in enumerate(steps):
            try:
                line = self.env.parse(step["latex"])
            except ParseError as exc:
                lines.append(_line(step, Verdict("parse_error", str(exc))))
                last = None
                continue
            lines.append(_line(step, self.check_line(line, i, is_last=i == len(steps) - 1)))
            last = (line.parts[-1], step["latex"], i)
        if last is None:
            return StepsResult(lines, Verdict("fail", "the last line could not be parsed"))
        value, latex, i = last
        return StepsResult(lines, self.final_verdict(self.subst(value), last_segment(latex), latex, i))

    def collect_definitions(self, steps: list[dict]) -> dict[sp.Symbol, sp.Expr]:
        self.grade(steps)
        return dict(self.defined)


# ------------------------------------------------------------------ entry points
def grade_steps(ex: Exercise, steps: list[dict], *, seed_key: str, runner, reference_values=None) -> StepsResult:
    if ex.steps_mode == "chain":
        return ChainGrader(ex, seed_key, runner).grade(steps)
    if reference_values is None:
        reference_values = compute_reference_values(ex, seed_key=seed_key, runner=runner)
    return DerivationGrader(ex, seed_key, runner, reference_values).grade(steps)


def compute_reference_values(ex: Exercise, *, seed_key: str, runner) -> dict[sp.Symbol, sp.Expr]:
    """Quantities defined by the reference solution (derivation mode only)."""
    if ex.steps_mode != "derivation":
        return {}
    steps = [{"latex": s.latex} for s in ex.reference_solution]
    return DerivationGrader(ex, seed_key, runner, {}).collect_definitions(steps)


def reference_values_to_json(values: dict[sp.Symbol, sp.Expr]) -> dict[str, dict]:
    out = {}
    for sym, value in values.items():
        magnitude, dims = U.split(value)
        out[sym.name] = {"magnitude": repr(float(sp.N(magnitude))), "dims": dims}
    return out


def reference_values_from_json(data: dict[str, dict], ex: Exercise) -> dict[sp.Symbol, sp.Expr]:
    env = build_env(ex, units=True)
    out = {}
    for name, item in data.items():
        sym = env.symbols.get(name, sp.Symbol(name))
        base = sp.Mul(*(U.BASE[d] ** e for d, e in item["dims"].items()))
        out[sym] = sp.Rational(item["magnitude"]) * base
    return out
