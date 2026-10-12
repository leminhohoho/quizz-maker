import copy

import pytest

from factories import EXERCISE_CHAIN, EXERCISE_DERIVATION, package
from quizz.checkers.equiv import Timeout
from quizz.grading import exercise_score, grade
from quizz.schema import Package


def q(raw):
    return Package.model_validate(package(raw)).questions[0]


def run(raw, lines, **kw):
    steps = [{"latex": line} if isinstance(line, str) else line for line in lines]
    return grade(q(raw), {"steps": steps}, seed_key="t", **kw)


def statuses(graded):
    return [line["verdict"]["status"] for line in graded.result["lines"]]


# ------------------------------------------------------------------ chain mode
def test_chain_reference_solution_passes():
    g = run(EXERCISE_CHAIN, [s["latex"] for s in EXERCISE_CHAIN["reference_solution"]])
    assert statuses(g) == ["pass", "pass", "pass"]
    assert g.result["final"]["status"] == "pass"
    assert g.score == 2 and g.pending == []


def test_chain_flags_first_wrong_line_and_carries_error_forward():
    g = run(
        EXERCISE_CHAIN,
        [r"\int xe^{x}\,dx", r"xe^{x}-\int e^{x}\,dx", r"xe^{x}+e^{x}+C", r"\left(x+1\right)e^{x}+C"],
    )
    assert statuses(g) == ["pass", "pass", "fail", "pass"]
    assert g.result["lines"][2]["verdict"]["counterexample"]
    assert g.result["final"]["status"] == "fail"
    assert g.score == 0


def test_chain_first_line_compared_with_start():
    g = run(EXERCISE_CHAIN, [r"\int x^2e^{x}\,dx", r"xe^{x}-e^{x}+C"])
    assert statuses(g)[0] == "fail"


def test_chain_equation_inside_a_line_is_checked():
    g = run(EXERCISE_CHAIN, [r"\int xe^{x}\,dx=xe^{x}-\int e^{x}\,dx=xe^{x}-e^{x}+C"])
    assert statuses(g) == ["pass"]
    assert g.result["final"]["status"] == "pass"


def test_chain_substitution_definition_and_back_substitution():
    raw = copy.deepcopy(EXERCISE_CHAIN)
    raw["start"] = r"\int 2xe^{x^2}\,dx"
    raw["final"] = {"checker": "antiderivative", "params": {"integrand": r"2xe^{x^2}", "var": "x"}}
    raw["reference_solution"] = [{"latex": r"e^{x^2}+C"}]
    g = run(raw, [r"\int 2xe^{x^2}\,dx", r"u=x^2", r"\int e^{u}\,du", r"e^{u}+C"])
    assert statuses(g) == ["pass", "pass", "pass", "pass"]
    assert g.result["lines"][1]["verdict"]["reason"] == "definition"
    assert g.result["final"]["status"] == "pass"


def test_parse_error_line_does_not_stop_grading():
    g = run(EXERCISE_CHAIN, [r"\int xe^{x}\,dx", r"xe^{x}-\int e^{x}\,", r"xe^{x}-e^{x}+C"])
    assert statuses(g) == ["pass", "parse_error", "pass"]


def everything_times_out(fn, *args, timeout):
    raise Timeout


def test_budget_exhaustion_makes_lines_undecided_and_pending():
    g = run(EXERCISE_CHAIN, [r"\int xe^{x}\,dx", r"xe^{x}-e^{x}+C"], runner=everything_times_out)
    assert statuses(g) == ["undecided", "undecided"]
    assert g.pending == [0, 1]


def test_empty_submission_is_rejected():
    with pytest.raises(ValueError):
        run(EXERCISE_CHAIN, [])


# ------------------------------------------------------------------ derivation mode
def test_derivation_reference_solution_passes():
    g = run(EXERCISE_DERIVATION, [s["latex"] for s in EXERCISE_DERIVATION["reference_solution"]])
    assert statuses(g) == ["pass", "pass", "pass"]
    assert g.result["final"]["status"] == "pass"
    assert g.score == 2


def test_derivation_localizes_first_wrong_definition():
    g = run(
        EXERCISE_DERIVATION,
        [r"q=mc", r"q=50.0\,\mathrm{g}\cdot4.18\,\mathrm{J/(g\,K)}", r"q=209\,\mathrm{J/K}"],
    )
    assert statuses(g) == ["fail", "pass", "pass"]
    assert g.result["final"]["status"] == "fail"


def test_derivation_arithmetic_slip_fails():
    g = run(EXERCISE_DERIVATION, [r"q=mc\Delta T", r"q=50.0\,\mathrm{g}\cdot4.18\,\mathrm{J/(g\,K)}\cdot20.0\,\mathrm{K}=4000\,\mathrm{J}"])
    assert statuses(g) == ["pass", "fail"]


def test_derivation_accepts_rounded_intermediate_values():
    g = run(EXERCISE_DERIVATION, [r"q=mc\Delta T", r"q\approx4.2\times10^{3}\,\mathrm{J}"])
    assert statuses(g) == ["pass", "pass"]


def test_derivation_dimension_mismatch_fails():
    g = run(EXERCISE_DERIVATION, [r"q=mc\Delta T", r"q=4180\,\mathrm{W}"])
    assert statuses(g)[1] == "fail"
    assert "dimension" in g.result["lines"][1]["verdict"]["reason"]


SYMBOLIC = {
    "id": "q-newton",
    "type": "exercise",
    "prompt": "Express a in terms of F and m.",
    "steps_mode": "derivation",
    "context": {"symbols": {"a": {}, "F": {}, "m": {"assumptions": ["positive"]}}, "relations": ["F=ma"]},
    "final": {"checker": "expr_equiv", "params": {"expected": r"\frac{F}{m}", "vars": {"m": "positive"}}},
    "reference_solution": [{"latex": r"a=\frac{F}{m}"}],
}


@pytest.mark.parametrize("line, status", [(r"a=\frac{F}{m}", "pass"), (r"a=Fm", "fail"), (r"a=\frac{F}{m}+b", "undecided")])
def test_derivation_symbolic_lines_checked_against_relations(line, status):
    assert statuses(run(SYMBOLIC, [line])) == [status]


# ------------------------------------------------------------------ scoring
@pytest.mark.parametrize(
    "line_statuses, final, score",
    [
        (["pass", "pass_numeric", "agent_pass"], "pass", 2),
        (["pass", "unverified"], "pass", 2),
        (["pass", "undecided"], "pass", 2),
        (["pass", "agent_fail"], "pass", 0),
        (["pass", "parse_error"], "pass", 0),
        (["pass"], "fail", 0),
    ],
)
def test_exercise_score(line_statuses, final, score):
    result = {"lines": [{"verdict": {"status": s}} for s in line_statuses], "final": {"status": final}}
    assert exercise_score(result, 2) == score
