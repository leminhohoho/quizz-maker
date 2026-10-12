"""Golden table: MathLive-dialect LaTeX -> SymPy."""

import pytest
import sympy as sp

from quizz.mathparse import ParseError, parse_expr, parse_line

x, y, n, s, t, a, b, C, F, m, r = sp.symbols("x y n s t a b C F m r")
u = sp.Symbol("u")


@pytest.mark.parametrize(
    "latex, expected",
    [
        # arithmetic and implicit multiplication
        (r"2x^2+3", 2 * x**2 + 3),
        (r"x e^{x}", x * sp.exp(x)),
        (r"xe^{x}", x * sp.exp(x)),
        (r"\mathrm{e}^{-st}", sp.exp(-s * t)),
        (r"\exponentialE^{x}", sp.exp(x)),
        (r"2\cdot 3x", 6 * x),
        (r"a\times b", a * b),
        (r"a\div b", a / b),
        (r"-x^2", -(x**2)),
        (r"2^{-1}", sp.Rational(1, 2)),
        (r"x^{2}y", x**2 * y),
        # fractions and roots
        (r"\frac{x^2}{2}", x**2 / 2),
        (r"\dfrac{1}{s+a}", 1 / (s + a)),
        (r"\frac12", sp.Rational(1, 2)),
        (r"\sqrt{x}", sp.sqrt(x)),
        (r"\sqrt[3]{x}", x ** sp.Rational(1, 3)),
        # brackets
        (r"\left(x+1\right)^2", (x + 1) ** 2),
        (r"\left[x+1\right]y", (x + 1) * y),
        (r"\left|x\right|", sp.Abs(x)),
        (r"|x-1|", sp.Abs(x - 1)),
        # functions
        (r"\sin\left(x\right)", sp.sin(x)),
        (r"\sin x", sp.sin(x)),
        (r"\sin 2x", sp.sin(2 * x)),
        (r"\cos^2x", sp.cos(x) ** 2),
        (r"\sin^{-1}x", sp.asin(x)),
        (r"\arctan\left(x\right)", sp.atan(x)),
        (r"\ln x", sp.log(x)),
        (r"\ln\left|x\right|", sp.log(sp.Abs(x))),
        (r"\log_{2}x", sp.log(x, 2)),
        (r"\exp\left(x\right)", sp.exp(x)),
        (r"\sinh x", sp.sinh(x)),
        # constants and Greek
        (r"\pi r^2", sp.pi * r**2),
        (r"\alpha+\beta", sp.Symbol("alpha") + sp.Symbol("beta")),
        (r"\infty", sp.oo),
        (r"\imaginaryI", sp.I),
        # subscripts
        (r"x_{1}+y_1", sp.Symbol("x_1") + sp.Symbol("y_1")),
        (r"v_{0}t", sp.Symbol("v_0") * t),
        # factorial
        (r"n!", sp.factorial(n)),
        # numbers
        (r"2.88\times10^{-4}", sp.Rational(288, 10**6)),
        (r"0.5x", x / 2),
        # calculus
        (r"\int x e^{x}\,dx", sp.Integral(x * sp.exp(x), x)),
        (r"\int xe^{x}\mathrm{d}x", sp.Integral(x * sp.exp(x), x)),
        (r"\int e^{x}\differentialD x", sp.Integral(sp.exp(x), x)),
        (r"xe^{x}-\int e^{x}\,dx", x * sp.exp(x) - sp.Integral(sp.exp(x), x)),
        (r"\int_{0}^{1}x\,dx", sp.Integral(x, (x, 0, 1))),
        (r"\int_0^\infty e^{-st}\,dt", sp.Integral(sp.exp(-s * t), (t, 0, sp.oo))),
        (r"\int\frac{1}{x}dx", sp.Integral(1 / x, x)),
        (r"\sum_{n=1}^{\infty}\frac{1}{n^2}", sp.Sum(1 / n**2, (n, 1, sp.oo))),
        (r"\lim_{x\to0}\frac{\sin x}{x}", sp.Limit(sp.sin(x) / x, x, 0)),
        (r"\frac{d}{dx}x^2", sp.Derivative(x**2, x)),
        (r"\frac{\mathrm{d}}{\mathrm{d}x}\left(x^2\right)", sp.Derivative(x**2, x)),
        # spacing is ignored
        (r"x\,+\;y\quad", x + y),
        # piecewise
        (
            r"\begin{cases}0 & t<0\\ 1 & t\ge0\end{cases}",
            sp.Piecewise((0, t < 0), (1, t >= 0)),
        ),
    ],
)
def test_golden(latex, expected):
    assert parse_expr(latex) == expected


def test_symbol_e_overrides_euler_when_declared():
    e = sp.Symbol("e")
    assert parse_expr(r"e^{2}", symbols={"e": e}) == e**2


def test_declared_symbols_carry_assumptions():
    xp = sp.Symbol("x", positive=True)
    assert parse_expr(r"\sqrt{x^2}", symbols={"x": xp}) == xp


def test_declared_functions_apply_instead_of_multiplying():
    assert parse_expr(r"u(t)", functions={"u": sp.Heaviside}) == sp.Heaviside(t)
    assert parse_expr(r"u(t)") == u * t
    assert parse_expr(r"\delta\left(t-1\right)", functions={"delta": sp.DiracDelta}) == sp.DiracDelta(t - 1)


def test_atoms_are_single_symbols():
    dh = sp.Symbol(r"\Delta H")
    assert parse_expr(r"\Delta H+2", atoms=[r"\Delta H"]) == dh + 2


@pytest.mark.parametrize(
    "atom, written",
    [
        (r"\Delta H_1", r"\Delta H_{1}"),
        (r"\Delta H_{1}", r"\Delta H_1"),
        (r"\Delta S_{sys}", r"\Delta S_{\mathrm{sys}}"),
        (r"\Delta S_{sys}", r"\Delta S_{sys}"),
        (r"\Delta H^\circ_f", r"\Delta H^{\circ}_{f}"),
    ],
)
def test_atoms_match_equivalent_spellings(atom, written):
    assert parse_expr(written + "+1", atoms=[atom]) == sp.Symbol(atom) + 1


def test_d_is_a_plain_symbol_outside_integrals():
    d = sp.Symbol("d")
    assert parse_expr(r"dx") == d * x


@pytest.mark.parametrize(
    "latex, parts",
    [
        (r"x", [x]),
        (r"a=\frac{F}{m}", [a, F / m]),
        (r"y=2x=4", [y, 2 * x, 4]),
        (r"y\approx 2", [y, 2]),
    ],
)
def test_parse_line_splits_equation_chains(latex, parts):
    assert parse_line(latex).parts == parts


@pytest.mark.parametrize(
    "latex, token",
    [
        (r"\frac{1}{", "end of input"),
        (r"x+", "end of input"),
        (r"\foo x", r"\foo"),
        (r"\placeholder{}", r"\placeholder"),
        (r"\int x", "differential"),
        (r"\text{hello}", r"\text"),
        (r"(x+1", "end of input"),
        (r"\frac{dy}{dx}", "derivative"),
        (r"", "empty"),
    ],
)
def test_bad_input_raises_parse_error_naming_the_problem(latex, token):
    with pytest.raises(ParseError) as err:
        parse_expr(latex)
    assert token in str(err.value)


def test_parse_expr_rejects_equations():
    with pytest.raises(ParseError, match="equation"):
        parse_expr(r"a=b")
