import pytest

from quizz import chem


@pytest.mark.parametrize(
    "formula, atoms, charge",
    [
        ("H2O", {"H": 2, "O": 1}, 0),
        ("C3H8", {"C": 3, "H": 8}, 0),
        ("Ca(OH)2", {"Ca": 1, "O": 2, "H": 2}, 0),
        ("Fe2(SO4)3", {"Fe": 2, "S": 3, "O": 12}, 0),
        ("CuSO4·5H2O", {"Cu": 1, "S": 1, "O": 9, "H": 10}, 0),
        ("CuSO4*5H2O", {"Cu": 1, "S": 1, "O": 9, "H": 10}, 0),
        ("SO4^2-", {"S": 1, "O": 4}, -2),
        ("SO4^{2-}", {"S": 1, "O": 4}, -2),
        ("Fe^3+", {"Fe": 1}, 3),
        ("Na+", {"Na": 1}, 1),
        ("Cl-", {"Cl": 1}, -1),
        ("NH4+", {"N": 1, "H": 4}, 1),
        ("e-", {}, -1),
    ],
)
def test_parse_formula(formula, atoms, charge):
    species = chem.parse_formula(formula)
    assert dict(species.atoms) == atoms
    assert species.charge == charge


@pytest.mark.parametrize("bad", ["Xx2", "h2o", "Ca(OH2", "", "2"])
def test_bad_formulas_raise(bad):
    with pytest.raises(ValueError):
        chem.parse_formula(bad)


def test_parse_reaction_with_states_and_arrow_variants():
    for arrow in ["->", "→", "\\rightarrow", "<=>", "⇌", "="]:
        rx = chem.parse_reaction(f"C3H8(g) + 5O2(g) {arrow} 3CO2(g) + 4H2O(l)")
        assert [(c, s.formula) for c, s in rx.reactants] == [(1, "C3H8"), (5, "O2")]
        assert [(c, s.formula) for c, s in rx.products] == [(3, "CO2"), (4, "H2O")]


def test_parse_reaction_rejects_missing_arrow():
    with pytest.raises(ValueError, match="arrow"):
        chem.parse_reaction("H2 + O2")


def test_parse_reaction_rejects_fractional_coefficients():
    with pytest.raises(ValueError, match="integer"):
        chem.parse_reaction("H2 + 1/2O2 -> H2O")
