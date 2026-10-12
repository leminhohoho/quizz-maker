import copy

import pytest
from pydantic import ValidationError

from factories import EXERCISE_CHAIN, MCQ, package
from quizz.schema import Package, json_schema


def test_full_package_parses_every_question_type():
    pkg = Package.model_validate(package())
    assert [q.type for q in pkg.questions] == ["mcq", "multi_select", "fill_blank", "math_answer", "exercise", "exercise"]
    assert pkg.questions[0].points == 1


def locs(exc: ValidationError) -> set[str]:
    return {"/".join(str(p) for p in e["loc"]) for e in exc.errors()}


@pytest.mark.parametrize(
    "mutate, loc_fragment",
    [
        (lambda p: p.update(id="Bad Id"), "id"),
        (lambda p: p.update(format_version=2), "format_version"),
        (lambda p: p["questions"][0].update(type="essay"), "questions/0"),
        (lambda p: p["questions"][0].update(choices=[{"id": "a", "text": "only"}]), "questions/0/mcq/choices"),
        (lambda p: p["questions"][0].update(points=0), "questions/0/mcq/points"),
        (lambda p: p["questions"][0].update(surprise=1), "questions/0/mcq/surprise"),
        (lambda p: p["questions"][1].update(answer=[]), "questions/1/multi_select/answer"),
        (lambda p: p["questions"][2]["blanks"]["b1"].update(match="fuzzy"), "questions/2/fill_blank/blanks/b1/match"),
        (lambda p: p["questions"][4].update(steps_mode="freeform"), "questions/4/exercise/steps_mode"),
        (lambda p: p["questions"][4].update(reference_solution=[]), "questions/4/exercise/reference_solution"),
        (lambda p: p["source"].update(sha256="xyz"), "source/sha256"),
        (lambda p: p.update(questions=[]), "questions"),
    ],
)
def test_invalid_packages_are_rejected_at_the_right_path(mutate, loc_fragment):
    pkg = package()
    mutate(pkg)
    with pytest.raises(ValidationError) as err:
        Package.model_validate(pkg)
    assert any(loc.startswith(loc_fragment) for loc in locs(err.value)), locs(err.value)


def test_chain_exercise_requires_start():
    q = copy.deepcopy(EXERCISE_CHAIN)
    del q["start"]
    with pytest.raises(ValidationError, match="start"):
        Package.model_validate(package(q))


def test_unknown_checker_rejected():
    q = copy.deepcopy(MCQ)
    q.update(type="math_answer", check={"checker": "vibes", "params": {}})
    del q["choices"], q["answer"]
    with pytest.raises(ValidationError, match="unknown checker"):
        Package.model_validate(package(q))


def test_json_schema_covers_each_question_type():
    full = json_schema()
    assert full["properties"]["format_version"]["const"] == 1
    exercise = json_schema("exercise")
    assert "steps_mode" in exercise["properties"]
    with pytest.raises(ValueError):
        json_schema("essay")
