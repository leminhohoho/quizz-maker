import pytest
import sympy as sp

from quizz.checkers import REGISTRY, get
from quizz.checkers.equiv import Timeout, equivalent


def check(name, answer, **params):
    checker = get(name)
    return checker.check(answer, checker.parse_params(params))


def timeout_symbolic(fn, *args, timeout):
    """Runner that pretends symbolic simplification blew its budget."""
    if fn.__name__ == "_symbolic_zero":
        raise Timeout
    return fn(*args)


# ---------------------------------------------------------------- equivalence engine
x = sp.Symbol("x")


def test_equivalent_proves_symbolically():
    assert equivalent(sp.sin(x) ** 2 + sp.cos(x) ** 2, sp.Integer(1), seed=1).status == "proven"


def test_equivalent_falls_back_to_numeric_when_symbolic_times_out():
    result = equivalent((x + 1) ** 2, x**2 + 2 * x + 1, seed=1, runner=timeout_symbolic)
    assert result.status == "numeric"


def test_equivalent_reports_counterexample():
    result = equivalent((x + 1) ** 2, x**2 + 1, seed=1)
    assert result.status == "different"
    (sym, value), = result.counterexample.items()
    assert sym == "x" and value != 0


def test_equivalent_is_unknown_with_too_few_valid_points():
    n = sp.Symbol("n", integer=True)
    expr = 1 / sp.sin(sp.pi * n)
    assert equivalent(expr, expr, seed=1, runner=timeout_symbolic).status == "unknown"


def test_equivalent_is_deterministic_for_a_seed():
    a = equivalent((x + 1) ** 2, x**2 + 1, seed=7).counterexample
    b = equivalent((x + 1) ** 2, x**2 + 1, seed=7).counterexample
    assert a == b


# ---------------------------------------------------------------- expr_equiv
@pytest.mark.parametrize(
    "answer, status",
    [
        (r"0.5x^2", "pass"),
        (r"\frac{x\cdot x}{2}", "pass"),
        (r"\frac{x^2}{3}", "fail"),
        (r"\frac{x^{2}}{", "parse_error"),
    ],
)
def test_expr_equiv(answer, status):
    assert check("expr_equiv", answer, expected=r"\frac{x^2}{2}", vars={"x": "real"}).status == status


def test_expr_equiv_failure_carries_counterexample():
    v = check("expr_equiv", r"x^2+1", expected=r"\left(x+1\right)^2")
    assert v.status == "fail" and "x" in v.counterexample


def test_expr_equiv_uses_variable_assumptions():
    assert check("expr_equiv", r"x", expected=r"\sqrt{x^2}", vars={"x": "positive"}).status == "pass"
    assert check("expr_equiv", r"x", expected=r"\sqrt{x^2}", vars={"x": "real"}).status == "fail"


# ---------------------------------------------------------------- antiderivative
@pytest.mark.parametrize(
    "answer, status",
    [
        (r"xe^{x}-e^{x}+C", "pass"),
        (r"xe^{x}-e^{x}", "pass"),
        (r"\left(x-1\right)e^{x}+C_{1}", "pass"),
        (r"xe^{x}+e^{x}+C", "fail"),
    ],
)
def test_antiderivative(answer, status):
    assert check("antiderivative", answer, integrand=r"xe^{x}", var="x").status == status


# ---------------------------------------------------------------- numeric_units
CAP = dict(expected=2.88e-4, unit="J", rel_tol=0.01, sig_figs=3)


@pytest.mark.parametrize(
    "answer, status, reason",
    [
        (r"2.88\times10^{-4}\,\mathrm{J}", "pass", ""),
        (r"0.288\,\mathrm{mJ}", "pass", ""),
        (r"2.9\times10^{-4}\,\mathrm{J}", "fail", "significant figures"),
        (r"2.88\times10^{-4}", "fail", "dimension"),
        (r"2.88\times10^{-4}\,\mathrm{N}", "fail", "dimension"),
        (r"3.00\times10^{-4}\,\mathrm{J}", "fail", "tolerance"),
        (r"2.88\times10^{-4}\,\mathrm{furlong}", "parse_error", "furlong"),
    ],
)
def test_numeric_units(answer, status, reason):
    v = check("numeric_units", answer, **CAP)
    assert v.status == status
    assert reason in v.reason


@pytest.mark.parametrize("answer, status", [("101", "pass"), ("99", "pass"), ("101.1", "fail"), ("98.9", "fail")])
def test_numeric_units_tolerance_edges(answer, status):
    assert check("numeric_units", answer, expected=100, unit="", rel_tol=0.01).status == status


def test_numeric_units_abs_tol():
    assert check("numeric_units", "0.004", expected=0, unit="", rel_tol=0.01, abs_tol=0.005).status == "pass"
    assert check("numeric_units", "0.006", expected=0, unit="", rel_tol=0.01, abs_tol=0.005).status == "fail"


def test_numeric_units_rejects_symbolic_answers():
    assert check("numeric_units", r"x\,\mathrm{J}", **CAP).status == "fail"


# ---------------------------------------------------------------- reaction_balance
PROPANE = dict(reactants=["C3H8", "O2"], products=["CO2", "H2O"])


@pytest.mark.parametrize(
    "answer, status, reason",
    [
        ("C3H8 + 5O2 -> 3CO2 + 4H2O", "pass", ""),
        ("C3H8(g) + 5 O2(g) → 3 CO2(g) + 4 H2O(l)", "pass", ""),
        ("5O2 + C3H8 -> 4H2O + 3CO2", "pass", ""),
        ("C3H8 + 4O2 -> 3CO2 + 4H2O", "fail", "O"),
        ("2C3H8 + 10O2 -> 6CO2 + 8H2O", "fail", "lowest"),
        ("C3H8 + 5O2 -> 3CO + 4H2O", "fail", "species"),
        ("C3H8 + 5O2", "parse_error", "arrow"),
    ],
)
def test_reaction_balance(answer, status, reason):
    v = check("reaction_balance", answer, **PROPANE)
    assert v.status == status
    assert reason in v.reason


def test_reaction_balance_checks_charge():
    params = dict(reactants=["Cu", "Ag+"], products=["Cu^2+", "Ag"])
    assert check("reaction_balance", "Cu + 2Ag+ -> Cu^2+ + 2Ag", **params).status == "pass"
    v = check("reaction_balance", "Cu + Ag+ -> Cu^2+ + Ag", **params)
    assert v.status == "fail" and "charge" in v.reason


# ---------------------------------------------------------------- transform
LAPLACE = dict(kind="laplace", expected=r"\frac{1}{s+2}", var="s")


@pytest.mark.parametrize("answer, status", [(r"\frac{1}{2+s}", "pass"), (r"\frac{1}{s-2}", "fail")])
def test_transform(answer, status):
    assert check("transform", answer, **LAPLACE).status == status


@pytest.mark.parametrize(
    "answer, status",
    [
        (r"\frac{1}{s+2},\ \mathrm{Re}\left(s\right)>-2", "pass"),
        (r"\frac{1}{s+2}, \operatorname{Re}(s)>-2", "pass"),
        (r"\frac{1}{s+2}, \mathrm{Re}(s)<-2", "fail"),
        (r"\frac{1}{s+2}, \mathrm{Re}(s)>2", "fail"),
        (r"\frac{1}{s+2}", "fail"),
    ],
)
def test_transform_region_of_convergence(answer, status):
    assert check("transform", answer, **LAPLACE, region_of_convergence=r"\mathrm{Re}(s)>-2").status == status


def test_z_transform_roc_uses_magnitude():
    params = dict(kind="z", expected=r"\frac{z}{z-0.5}", var="z", region_of_convergence=r"|z|>0.5")
    assert check("transform", r"\frac{z}{z-\frac{1}{2}}, \left|z\right|>\frac{1}{2}", **params).status == "pass"


# ---------------------------------------------------------------- mutants
MUTANT_CASES = [
    ("expr_equiv", dict(expected=r"x^2+3x")),
    ("antiderivative", dict(integrand=r"xe^{x}", var="x")),
    ("numeric_units", dict(expected=9.81, unit="m/s^2", rel_tol=0.01)),
    ("reaction_balance", PROPANE),
    ("transform", LAPLACE),
]


@pytest.mark.parametrize("name, params", MUTANT_CASES)
def test_mutants_fail_a_strict_check(name, params):
    checker = get(name)
    p = checker.parse_params(params)
    mutants = checker.mutants(p)
    assert len(mutants) >= 2
    for mutant in mutants:
        assert checker.check_value(mutant, p).status == "fail", mutant


def test_vacuous_tolerance_lets_a_mutant_pass():
    checker = get("numeric_units")
    p = checker.parse_params(dict(expected=9.81, unit="m/s^2", rel_tol=100))
    assert any(checker.check_value(m, p).status == "pass" for m in checker.mutants(p))


def test_expr_equiv_mutants_skip_terms_when_single_term():
    checker = get("expr_equiv")
    p = checker.parse_params(dict(expected=r"x^2"))
    assert sp.Integer(0) not in checker.mutants(p)


# ---------------------------------------------------------------- params validation
@pytest.mark.parametrize(
    "name, params, path",
    [
        ("expr_equiv", dict(expected=r"\frac{1}{"), "expected"),
        ("numeric_units", dict(expected=1, unit="furlong", rel_tol=0.01), "unit"),
        ("numeric_units", dict(expected=1, unit="m", rel_tol=-1), "rel_tol"),
        ("reaction_balance", dict(reactants=["Xx"], products=["H2O"]), "reactants"),
        ("antiderivative", dict(integrand="x", var="x y"), "var"),
        ("transform", dict(kind="mellin", expected="1", var="s"), "kind"),
    ],
)
def test_invalid_params_report_the_field(name, params, path):
    errors = get(name).validate_params(params)
    assert errors and errors[0].path.startswith(path)


def test_registry_lists_widgets():
    assert {n: c.widget for n, c in REGISTRY.items()} == {
        "expr_equiv": "math",
        "antiderivative": "math",
        "numeric_units": "math",
        "reaction_balance": "text",
        "transform": "math",
    }
