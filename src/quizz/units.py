"""Physical units as positive SymPy symbols for the SI base units.

A unit string becomes `scale * Π base**exp`; `split` recovers (magnitude, dimensions)
and raises DimensionError when an expression adds incompatible quantities.
"""

import re

import sympy as sp

BASE_NAMES = ("m", "kg", "s", "A", "K", "mol", "cd")
BASE = {name: sp.Symbol(f"[{name}]", positive=True) for name in BASE_NAMES}
_BY_SYMBOL = {sym: name for name, sym in BASE.items()}


class DimensionError(ValueError):
    pass


def _u(scale, **dims) -> tuple[sp.Rational, dict[str, int]]:
    return sp.Rational(scale), dims


_N = dict(kg=1, m=1, s=-2)
_J = dict(kg=1, m=2, s=-2)
_PA = dict(kg=1, m=-1, s=-2)
_V = dict(kg=1, m=2, s=-3, A=-1)

UNITS: dict[str, tuple[sp.Rational, dict[str, int]]] = {
    "m": _u(1, m=1),
    "g": _u("1/1000", kg=1),
    "kg": _u(1, kg=1),
    "s": _u(1, s=1),
    "A": _u(1, A=1),
    "K": _u(1, K=1),
    "mol": _u(1, mol=1),
    "cd": _u(1, cd=1),
    "N": _u(1, **_N),
    "J": _u(1, **_J),
    "W": _u(1, kg=1, m=2, s=-3),
    "Pa": _u(1, **_PA),
    "C": _u(1, A=1, s=1),
    "V": _u(1, **_V),
    "Ω": _u(1, kg=1, m=2, s=-3, A=-2),
    "F": _u(1, kg=-1, m=-2, s=4, A=2),
    "H": _u(1, kg=1, m=2, s=-2, A=-2),
    "Wb": _u(1, kg=1, m=2, s=-2, A=-1),
    "T": _u(1, kg=1, s=-2, A=-1),
    "Hz": _u(1, s=-1),
    "L": _u("1/1000", m=3),
    "M": _u(1000, mol=1, m=-3),
    "atm": _u(101325, **_PA),
    "bar": _u(100000, **_PA),
    "torr": _u(sp.Rational(101325, 760), **_PA),
    "mmHg": _u(sp.Rational(101325, 760), **_PA),
    "eV": _u("1.602176634e-19", **_J),
    "cal": _u("4.184", **_J),
    "min": _u(60, s=1),
    "h": _u(3600, s=1),
}
PREFIXABLE = {"g", "m", "s", "A", "K", "mol", "N", "J", "W", "Pa", "C", "V", "Ω", "F", "H", "Wb", "T",
              "Hz", "L", "M", "eV", "cal", "bar"}  # fmt: skip
PREFIXES = {"T": 10**12, "G": 10**9, "M": 10**6, "k": 10**3, "c": sp.Rational(1, 10**2),
            "m": sp.Rational(1, 10**3), "µ": sp.Rational(1, 10**6), "u": sp.Rational(1, 10**6),
            "n": sp.Rational(1, 10**9), "p": sp.Rational(1, 10**12), "f": sp.Rational(1, 10**15)}  # fmt: skip

_LATEX_NAMES = {r"\mu": "µ", r"\micro": "µ", "μ": "µ", r"\Omega": "Ω", r"\ohm": "Ω", "Ω": "Ω"}
_TOKEN = re.compile(r"\s*(?:(?P<name>[A-Za-zµΩ]+)|(?P<op>[/()^*·.]|\\cdot)|(?P<exp>\{-?\d+\}|-?\d+))")


def lookup(name: str) -> sp.Expr:
    """A single unit name, optionally prefixed, as an expression in base symbols."""
    if name in UNITS:
        scale, dims = UNITS[name]
    else:
        for prefix, factor in PREFIXES.items():
            rest = name[len(prefix) :]
            if name.startswith(prefix) and rest in UNITS and rest in PREFIXABLE:
                scale, dims = UNITS[rest]
                scale = scale * factor
                break
        else:
            raise ValueError(f"unknown unit {name!r}")
    return scale * sp.Mul(*(BASE[d] ** e for d, e in dims.items()))


def unit_expr(text: str) -> sp.Expr:
    """Parse a unit string such as `kJ/mol`, `J\\,K^{-1}\\,mol^{-1}` or `J/(mol K)`."""
    src = text
    for latex, plain in _LATEX_NAMES.items():
        src = re.sub(re.escape(latex) + r"(?![A-Za-z])\s*", plain, src)
    src = re.sub(r"\\[,;: !]", " ", src).strip()
    if not src:
        raise ValueError("empty unit")
    tokens = _tokenize(src)
    value, pos = _units(tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"unexpected {tokens[pos][1]!r} in unit {text!r}")
    return value


def _tokenize(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(src):
        if src[i].isspace():
            i += 1
            continue
        m = _TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ValueError(f"unexpected character {src[i]!r} in unit")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


def _units(tokens, pos):
    value, pos = _factor(tokens, pos)
    while pos < len(tokens):
        kind, tok = tokens[pos]
        if kind == "op" and tok == "/":
            rhs, pos = _factor(tokens, pos + 1)
            value = value / rhs
        elif kind == "op" and tok in ("*", "·", ".", r"\cdot"):
            rhs, pos = _factor(tokens, pos + 1)
            value = value * rhs
        elif kind == "name" or (kind == "op" and tok == "("):
            rhs, pos = _factor(tokens, pos)
            value = value * rhs
        else:
            break
    return value, pos


def _factor(tokens, pos):
    if pos >= len(tokens):
        raise ValueError("unit ends unexpectedly")
    kind, tok = tokens[pos]
    if kind == "name":
        value, pos = lookup(tok), pos + 1
    elif kind == "op" and tok == "(":
        value, pos = _units(tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos][1] != ")":
            raise ValueError("unclosed '(' in unit")
        pos += 1
    else:
        raise ValueError(f"unexpected {tok!r} in unit")
    if pos < len(tokens) and tokens[pos][1] == "^":
        if pos + 1 >= len(tokens) or tokens[pos + 1][0] != "exp":
            raise ValueError("unit exponent must be an integer")
        value = value ** int(tokens[pos + 1][1].strip("{}"))
        pos += 2
    elif pos < len(tokens) and tokens[pos][0] == "exp":
        value = value ** int(tokens[pos][1].strip("{}"))
        pos += 1
    return value, pos


def split(expr) -> tuple[sp.Expr, dict[str, int]]:
    """(magnitude in SI base units, dimension exponents). Raises DimensionError."""
    expr = sp.sympify(expr)
    if expr.is_Add:
        parts = [split(a) for a in expr.args]
        dims = parts[0][1]
        if any(p[1] != dims for p in parts[1:]):
            raise DimensionError("cannot add quantities with different dimensions")
        return sp.Add(*(p[0] for p in parts)), dims
    if expr.is_Mul:
        mag, dims = sp.Integer(1), {}
        for a in expr.args:
            m, d = split(a)
            mag *= m
            for k, v in d.items():
                dims[k] = dims.get(k, 0) + v
        return mag, {k: v for k, v in dims.items() if v != 0}
    if expr.is_Pow:
        base_mag, base_dims = split(expr.base)
        if base_dims:
            if not expr.exp.is_number:
                raise DimensionError("exponent of a dimensional quantity must be a number")
            if split(expr.exp)[1]:
                raise DimensionError("exponent must be dimensionless")
            return base_mag**expr.exp, {k: v * expr.exp for k, v in base_dims.items()}
        exp_mag, exp_dims = split(expr.exp)
        if exp_dims:
            raise DimensionError("exponent must be dimensionless")
        return base_mag**exp_mag, {}
    if expr in _BY_SYMBOL:
        return sp.Integer(1), {_BY_SYMBOL[expr]: 1}
    if expr.free_symbols & set(_BY_SYMBOL):
        if expr.is_Function or isinstance(expr, sp.Abs):
            args = [split(a) for a in expr.args]
            if isinstance(expr, sp.Abs):
                return sp.Abs(args[0][0]), args[0][1]
            if any(d for _, d in args):
                raise DimensionError(f"{expr.func.__name__} of a dimensional quantity")
            return expr.func(*(m for m, _ in args)), {}
        raise DimensionError(f"unsupported dimensional expression {expr}")
    return expr, {}


_LEADING_NUMBER = re.compile(r"^\s*[-+]?\s*(\d+\.?\d*|\.\d+)")


def sig_figs(latex: str) -> int | None:
    """Significant figures of the number a LaTeX answer starts with; None if it doesn't."""
    m = _LEADING_NUMBER.match(latex)
    if not m:
        return None
    digits = m.group(1)
    if "." in digits:
        stripped = digits.replace(".", "").lstrip("0")
        return len(stripped) if stripped else 1
    stripped = digits.lstrip("0").rstrip("0")
    return len(stripped) if stripped else 1
