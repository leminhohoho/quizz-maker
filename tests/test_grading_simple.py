import copy

import pytest

from factories import FILL, MATH, MCQ, MULTI
from quizz.grading import grade
from quizz.schema import Package
from factories import package


def q(raw):
    return Package.model_validate(package(raw)).questions[0]


@pytest.mark.parametrize("choice, score", [("b", 1), ("a", 0)])
def test_mcq(choice, score):
    graded = grade(q(MCQ), {"choice": choice}, seed_key="t")
    assert graded.score == score
    assert graded.result["correct"] is bool(score)


def test_mcq_rejects_unknown_choice():
    with pytest.raises(ValueError):
        grade(q(MCQ), {"choice": "zzz"}, seed_key="t")


@pytest.mark.parametrize(
    "scoring, chosen, score",
    [
        ("partial", ["h", "u"], 2),
        ("partial", ["h"], 1),
        ("partial", ["h", "q"], 0),
        ("partial", ["h", "u", "q"], 1),
        ("partial", ["q"], 0),
        ("all_or_nothing", ["h", "u"], 2),
        ("all_or_nothing", ["u", "h"], 2),
        ("all_or_nothing", ["h"], 0),
    ],
)
def test_multi_select(scoring, chosen, score):
    raw = copy.deepcopy(MULTI)
    raw["scoring"] = scoring
    assert grade(q(raw), {"choices": chosen}, seed_key="t").score == score


@pytest.mark.parametrize(
    "b1, b2, score",
    [
        ("charge", "ε₀", 1),
        ("  Charge. ", "epsilon_0", 1),
        ("CHARGE", "ε0", 1),
        ("charge", "epsilon 0", 0.5),
        ("mass", "Epsilon_0", 0),
        ("", "", 0),
    ],
)
def test_fill_blank(b1, b2, score):
    graded = grade(q(FILL), {"blanks": {"b1": b1, "b2": b2}}, seed_key="t")
    assert graded.score == score


def test_fill_blank_regex():
    raw = copy.deepcopy(FILL)
    raw["blanks"]["b1"] = {"accept": [r"(electric )?charge"], "match": "regex"}
    assert grade(q(raw), {"blanks": {"b1": "electric charge", "b2": "ε0"}}, seed_key="t").score == 1
    assert grade(q(raw), {"blanks": {"b1": "electric charges", "b2": "ε0"}}, seed_key="t").score == 0.5


def test_fill_blank_missing_key_counts_as_empty():
    assert grade(q(FILL), {"blanks": {"b1": "charge"}}, seed_key="t").score == 0.5


@pytest.mark.parametrize(
    "answer, score, status",
    [(r"2.88\times10^{-4}\,\mathrm{J}", 1, "pass"), (r"2.88\,\mathrm{J}", 0, "fail"), (r"\frac{", 0, "parse_error")],
)
def test_math_answer(answer, score, status):
    graded = grade(q(MATH), {"answer": answer}, seed_key="t")
    assert graded.score == score
    assert graded.result["verdict"]["status"] == status


def test_malformed_response_raises():
    with pytest.raises(ValueError):
        grade(q(MATH), {"wrong": "x"}, seed_key="t")
