"""Chemical formulas and reactions (plain text, as typed by the user)."""

import re
from collections import Counter
from dataclasses import dataclass

ELEMENTS = frozenset(
    """H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr
    Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb
    Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf
    Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og""".split()
)
ARROWS = ("\\rightleftharpoons", "\\longrightarrow", "\\rightarrow", "<=>", "<->", "⇌", "->", "→", "\\to", "=")
_STATE = re.compile(r"\((?:aq|s|l|g)\)\s*$")
_COEF = re.compile(r"^(\d+(?:[/.]\d+)?)\s*")
_CHARGE = re.compile(r"(?:\^\{?(\d*)([+-])\}?|([+-]+))$")


@dataclass(frozen=True)
class Species:
    formula: str
    atoms: Counter
    charge: int


@dataclass(frozen=True)
class Reaction:
    reactants: list[tuple[int, Species]]
    products: list[tuple[int, Species]]


def parse_formula(text: str) -> Species:
    formula = _STATE.sub("", text.strip()).strip()
    if not formula:
        raise ValueError("empty formula")
    if formula in ("e-", "e^-", "e^{-}"):
        return Species(formula, Counter(), -1)
    body, charge = formula, 0
    m = _CHARGE.search(body)
    if m:
        if m.group(3):
            charge = len(m.group(3)) * (1 if m.group(3)[0] == "+" else -1)
        else:
            charge = int(m.group(1) or 1) * (1 if m.group(2) == "+" else -1)
        body = body[: m.start()]
    atoms: Counter = Counter()
    for part in re.split(r"[·*•]", body):
        mult = 1
        cm = re.match(r"^(\d+)", part)
        if cm:
            mult, part = int(cm.group(1)), part[cm.end() :]
        group, pos = _group(part, 0)
        if pos != len(part):
            raise ValueError(f"unexpected {part[pos]!r} in formula {text!r}")
        for el, n in group.items():
            atoms[el] += n * mult
    if not atoms:
        raise ValueError(f"no elements in formula {text!r}")
    return Species(formula, atoms, charge)


def _group(s: str, pos: int) -> tuple[Counter, int]:
    out: Counter = Counter()
    while pos < len(s):
        c = s[pos]
        if c in "([":
            inner, pos = _group(s, pos + 1)
            if pos >= len(s) or s[pos] not in ")]":
                raise ValueError("unclosed parenthesis in formula")
            pos += 1
            n, pos = _count(s, pos)
            for el, k in inner.items():
                out[el] += k * n
        elif c in ")]":
            return out, pos
        elif c.isupper():
            end = pos + 1
            while end < len(s) and s[end].islower():
                end += 1
            symbol = s[pos:end]
            if symbol not in ELEMENTS:
                raise ValueError(f"unknown element {symbol!r}")
            n, pos = _count(s, end)
            out[symbol] += n
        else:
            raise ValueError(f"unexpected {c!r} in formula")
    return out, pos


def _count(s: str, pos: int) -> tuple[int, int]:
    end = pos
    while end < len(s) and s[end].isdigit():
        end += 1
    return (int(s[pos:end]) if end > pos else 1), end


def parse_reaction(text: str) -> Reaction:
    for arrow in ARROWS:
        if arrow in text:
            left, right = text.split(arrow, 1)
            break
    else:
        raise ValueError("reaction needs an arrow such as -> or =")
    return Reaction(_side(left), _side(right))


def _side(text: str) -> list[tuple[int, Species]]:
    text = text.strip()
    if not text:
        raise ValueError("empty side of reaction")
    terms = re.split(r"\s+\+\s+", text)
    if len(terms) == 1:
        terms = re.split(r"\+(?=[A-Z0-9(\[])", text)
    out = []
    for term in terms:
        term = term.strip()
        coef = 1
        m = _COEF.match(term)
        if m:
            if not m.group(1).isdigit():
                raise ValueError("coefficients must be integers")
            coef, term = int(m.group(1)), term[m.end() :]
        out.append((coef, parse_formula(term)))
    return out
