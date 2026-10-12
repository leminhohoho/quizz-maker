"""The skill's example packages are the agent's templates: each must pass every compile-time gate."""

from pathlib import Path

import pytest

from quizz import importer

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "skills" / "quizz-compile" / "examples").glob("*/quiz.json"))


def test_one_example_per_subject():
    assert [p.parent.name for p in EXAMPLES] == ["calc2", "chem2", "physics2", "signals"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_passes_all_gates(path, tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path))
    report = importer.check_package(path)
    assert report.errors == [], [e.to_dict() for e in report.errors]
