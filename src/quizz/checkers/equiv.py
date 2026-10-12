"""Expression equivalence: symbolic proof first, seeded numeric sampling second."""

import cmath
import math
import random
from collections.abc import Callable
from dataclasses import dataclass

import sympy as sp

SAMPLES = 30
MIN_VALID = 20
REL_TOL = 1e-9
DEFAULT_TIMEOUT = 3.0


class Timeout(Exception):
    """Raised by a runner when a budgeted computation exceeds its time limit."""


Runner = Callable[..., object]


def direct_runner(fn, *args, timeout: float):
    return fn(*args)


@dataclass
class Equiv:
    status: str  # proven | numeric | different | unknown
    counterexample: dict[str, str] | None = None


def _symbolic_zero(a: sp.Expr, b: sp.Expr) -> bool:
    diff = sp.simplify((a - b).doit())
    return diff == 0


def _sample_value(sym: sp.Symbol, rng: random.Random) -> sp.Expr:
    if sym.is_integer:
        return sp.Integer(rng.randint(1, 6))
    if sym.is_positive or sym.is_nonnegative:
        return sp.Float(rng.uniform(0.2, 3.0), 30)
    return sp.Float(rng.uniform(-3.0, 3.0), 30)


def _as_complex(expr: sp.Expr) -> complex | None:
    try:
        value = complex(sp.N(expr, 30))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not (math.isfinite(value.real) and math.isfinite(value.imag)):
        return None
    return value


def _numeric_compare(a: sp.Expr, b: sp.Expr, seed: int) -> tuple[int, dict[str, str] | None]:
    """Returns (valid_points, counterexample or None)."""
    a, b = a.doit(), b.doit()
    symbols = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
    rng = random.Random(seed)
    valid = 0
    for _ in range(SAMPLES):
        point = {s: _sample_value(s, rng) for s in symbols}
        va, vb = _as_complex(a.subs(point)), _as_complex(b.subs(point))
        if va is None or vb is None:
            continue
        valid += 1
        scale = max(1.0, abs(va), abs(vb))
        if not cmath.isclose(va, vb, rel_tol=0, abs_tol=REL_TOL * scale):
            return valid, {s.name: f"{float(v):.4g}" for s, v in point.items()}
    return valid, None


def equivalent(
    a: sp.Expr,
    b: sp.Expr,
    *,
    seed: int,
    runner: Runner = direct_runner,
    timeout: float = DEFAULT_TIMEOUT,
) -> Equiv:
    try:
        if runner(_symbolic_zero, a, b, timeout=timeout):
            return Equiv("proven")
    except Timeout:
        pass
    try:
        valid, counterexample = runner(_numeric_compare, a, b, seed, timeout=timeout)
    except Timeout:
        return Equiv("unknown")
    if counterexample is not None:
        return Equiv("different", counterexample)
    return Equiv("numeric" if valid >= MIN_VALID else "unknown")
