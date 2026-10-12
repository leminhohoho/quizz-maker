"""Grading for mcq, multi_select, fill_blank and math_answer."""

import re

from quizz.checkers import get
from quizz.schema import MCQ, FillBlank, MathAnswer, MultiSelect


def _require(response: dict, key: str, kind: type):
    value = response.get(key)
    if not isinstance(value, kind):
        raise ValueError(f"response needs {key!r} of type {kind.__name__}")
    return value


def grade_mcq(q: MCQ, response: dict) -> tuple[float, dict]:
    choice = _require(response, "choice", str)
    if choice not in {c.id for c in q.choices}:
        raise ValueError(f"unknown choice {choice!r}")
    correct = choice == q.answer
    return (q.points if correct else 0), {"chosen": choice, "answer": q.answer, "correct": correct}


def grade_multi(q: MultiSelect, response: dict) -> tuple[float, dict]:
    chosen = _require(response, "choices", list)
    ids = {c.id for c in q.choices}
    if not all(isinstance(c, str) and c in ids for c in chosen):
        raise ValueError("unknown choice in selection")
    picked, answer = set(chosen), set(q.answer)
    if q.scoring == "partial":
        fraction = max(0, (len(picked & answer) - len(picked - answer)) / len(answer))
    else:
        fraction = 1 if picked == answer else 0
    return q.points * fraction, {"chosen": sorted(picked), "answer": sorted(answer), "correct": picked == answer}


def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text.casefold().strip())
    return text.rstrip(".,;:!?").strip()


def _blank_matches(given: str, accept: str, mode: str) -> bool:
    if mode == "exact":
        return given.strip() == accept
    if mode == "regex":
        return re.fullmatch(accept, given.strip()) is not None
    return normalize(given) == normalize(accept)


def grade_fill(q: FillBlank, response: dict) -> tuple[float, dict]:
    given = _require(response, "blanks", dict)
    blanks = {}
    for key, spec in q.blanks.items():
        value = given.get(key, "")
        value = value if isinstance(value, str) else ""
        ok = any(_blank_matches(value, acc, spec.match) for acc in spec.accept)
        blanks[key] = {"given": value, "correct": ok, "accept": spec.accept[0]}
    correct = sum(b["correct"] for b in blanks.values())
    return q.points * correct / len(blanks), {"blanks": blanks}


def grade_math(q: MathAnswer, response: dict, *, seed: int, runner) -> tuple[float, dict]:
    answer = _require(response, "answer", str)
    checker = get(q.check.checker)
    verdict = checker.check(answer, checker.parse_params(q.check.params), seed=seed, runner=runner)
    return (q.points if verdict.passed else 0), {"answer": answer, "verdict": verdict.to_dict()}
