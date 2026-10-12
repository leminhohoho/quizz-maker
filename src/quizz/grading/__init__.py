"""Grade one response to one question. Same code path for `quizz check` and the web app."""

from dataclasses import dataclass, field

from quizz.grading.budget import shared_runner
from quizz.grading.simple import grade_fill, grade_math, grade_mcq, grade_multi
from quizz.grading.steps import grade_steps, reference_values_from_json, seed_for
from quizz.schema import MCQ, Exercise, FillBlank, MathAnswer, MultiSelect
from quizz.verdict import FAILING, PASSING


@dataclass
class Graded:
    score: float
    max_score: int
    result: dict
    pending: list[int] = field(default_factory=list)


def exercise_score(result: dict, points: int) -> float:
    if result["final"]["status"] not in PASSING:
        return 0
    if any(line["verdict"]["status"] in FAILING for line in result["lines"]):
        return 0
    return points


def _steps(response: dict) -> list[dict]:
    steps = response.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("response needs a non-empty 'steps' list")
    out = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("latex"), str) or not step["latex"].strip():
            raise ValueError("each step needs non-empty 'latex'")
        justification = step.get("justification", "")
        out.append({"latex": step["latex"], "justification": justification if isinstance(justification, str) else ""})
    return out


def grade(question, response: dict, *, seed_key: str, runner=None, reference_values: dict | None = None) -> Graded:
    """`reference_values` is the stored JSON form (derivation exercises); computed when absent."""
    if not isinstance(response, dict):
        raise ValueError("response must be an object")
    runner = runner or shared_runner()
    key = f"{seed_key}:{question.id}"
    if isinstance(question, MCQ):
        score, result = grade_mcq(question, response)
    elif isinstance(question, MultiSelect):
        score, result = grade_multi(question, response)
    elif isinstance(question, FillBlank):
        score, result = grade_fill(question, response)
    elif isinstance(question, MathAnswer):
        score, result = grade_math(question, response, seed=seed_for(key), runner=runner)
    elif isinstance(question, Exercise):
        refs = reference_values_from_json(reference_values, question) if reference_values is not None else None
        steps = grade_steps(question, _steps(response), seed_key=key, runner=runner, reference_values=refs)
        result = steps.to_dict()
        return Graded(exercise_score(result, question.points), question.points, result, steps.pending)
    else:
        raise TypeError(f"unsupported question {type(question).__name__}")
    return Graded(score, question.points, result)
