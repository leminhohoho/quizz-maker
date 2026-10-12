import pytest
import sympy as sp

from quizz import units as U
from quizz.mathparse import ParseError, parse_expr


def si(latex_or_unit):
    """Magnitude in SI base units and dimension of a unit string."""
    return U.split(U.unit_expr(latex_or_unit))


@pytest.mark.parametrize(
    "text, magnitude, dims",
    [
        ("m", 1, {"m": 1}),
        ("km", 1000, {"m": 1}),
        ("mm", sp.Rational(1, 1000), {"m": 1}),
        ("m/s^2", 1, {"m": 1, "s": -2}),
        ("g", sp.Rational(1, 1000), {"kg": 1}),
        ("kJ/mol", 1000, {"kg": 1, "m": 2, "s": -2, "mol": -1}),
        (r"kJ\,mol^{-1}", 1000, {"kg": 1, "m": 2, "s": -2, "mol": -1}),
        (r"J\,K^{-1}\,mol^{-1}", 1, {"kg": 1, "m": 2, "s": -2, "K": -1, "mol": -1}),
        ("J/(mol K)", 1, {"kg": 1, "m": 2, "s": -2, "K": -1, "mol": -1}),
        (r"\mu F", sp.Rational(1, 10**6), {"kg": -1, "m": -2, "s": 4, "A": 2}),
        ("uF", sp.Rational(1, 10**6), {"kg": -1, "m": -2, "s": 4, "A": 2}),
        (r"\Omega", 1, {"kg": 1, "m": 2, "s": -3, "A": -2}),
        ("L", sp.Rational(1, 1000), {"m": 3}),
        ("mL", sp.Rational(1, 10**6), {"m": 3}),
        ("M", 1000, {"mol": 1, "m": -3}),
        ("atm", 101325, {"kg": 1, "m": -1, "s": -2}),
        ("min", 60, {"s": 1}),
        ("mol", 1, {"mol": 1}),
        ("Pa", 1, {"kg": 1, "m": -1, "s": -2}),
        ("eV", sp.Rational("1.602176634e-19"), {"kg": 1, "m": 2, "s": -2}),
        ("cal", sp.Rational("4.184"), {"kg": 1, "m": 2, "s": -2}),
        (r"N\cdot m", 1, {"kg": 1, "m": 2, "s": -2}),
    ],
)
def test_unit_strings_convert_to_si(text, magnitude, dims):
    assert si(text) == (magnitude, dims)


@pytest.mark.parametrize("text", ["parsec", "°C", "kgg", "m/", ""])
def test_unknown_or_malformed_units_raise(text):
    with pytest.raises(ValueError):
        U.unit_expr(text)


def test_units_inside_math_expressions():
    expr = parse_expr(r"\frac{2.5\,\mathrm{g}}{18\,\mathrm{g/mol}}", units=U.unit_expr)
    assert U.split(expr) == (sp.Rational(5, 36), {"mol": 1})


def test_separate_mathrm_units_with_math_exponents():
    expr = parse_expr(r"9.8\,\mathrm{m}\cdot\mathrm{s}^{-2}", units=U.unit_expr)
    assert U.split(expr) == (sp.Rational(49, 5), {"m": 1, "s": -2})


def test_adding_incompatible_dimensions_is_detected():
    expr = parse_expr(r"2\,\mathrm{m}+3\,\mathrm{s}", units=U.unit_expr)
    with pytest.raises(U.DimensionError):
        U.split(expr)


def test_adding_compatible_units_converts():
    expr = parse_expr(r"1\,\mathrm{km}+500\,\mathrm{m}", units=U.unit_expr)
    assert U.split(expr) == (1500, {"m": 1})


def test_unknown_unit_in_math_is_a_parse_error():
    with pytest.raises(ParseError, match="unknown unit"):
        parse_expr(r"3\,\mathrm{furlong}", units=U.unit_expr)


@pytest.mark.parametrize(
    "literal, figs",
    [
        ("2.88", 3),
        ("0.00288", 3),
        ("2.880", 4),
        ("1200", 2),
        ("1200.", 4),
        ("1.20\\times10^{3}", 3),
        ("-0.050", 2),
        ("7", 1),
        ("0", 1),
    ],
)
def test_sig_figs_of_leading_literal(literal, figs):
    assert U.sig_figs(literal) == figs


def test_sig_figs_none_without_a_number():
    assert U.sig_figs(r"\frac{1}{2}x") is None
