import asyncio
import json
import sys
import time

import pytest

from factories import EXERCISE_CHAIN, package
from quizz import agent_grader as ag
from quizz import db
from quizz.schema import Package

EX = Package.model_validate(package(EXERCISE_CHAIN)).questions[0]


def result_with_undecided():
    return {
        "lines": [
            {"latex": r"\int xe^{x}\,dx", "justification": "", "verdict": {"status": "pass"}},
            {"latex": r"xe^{x}-\int e^{x}\,dx", "justification": "by parts", "verdict": {"status": "undecided"}},
            {"latex": r"xe^{x}-e^{x}+C", "justification": "", "verdict": {"status": "fail", "reason": "nope"}},
            {"latex": r"\text{done}", "justification": "", "verdict": {"status": "undecided"}},
        ],
        "final": {"status": "pass"},
    }


def script(tmp_path, body: str) -> str:
    path = tmp_path / "agent.py"
    path.write_text("import sys, json, time\n" + body)
    return f"{sys.executable} {path}"


def run(result, command, timeout=10):
    config = ag.GraderConfig(command=command, timeout=timeout)
    return asyncio.run(ag.grade_undecided(EX, result, config))


def statuses(result):
    return [line["verdict"]["status"] for line in result["lines"]]


def test_valid_reply_marks_only_requested_lines(tmp_path):
    reply = {"lines": [
        {"index": 1, "verdict": "pass", "comment": "correct use of parts"},
        {"index": 2, "verdict": "pass", "comment": "trying to override"},
        {"index": 3, "verdict": "fail", "comment": "not math"},
    ]}  # fmt: skip
    cmd = script(tmp_path, f"sys.stdin.read()\nprint('thinking...')\nprint({json.dumps(json.dumps(reply))})")
    out = run(result_with_undecided(), cmd)
    assert statuses(out) == ["pass", "agent_pass", "fail", "agent_fail"]
    assert out["lines"][1]["verdict"]["reason"] == "correct use of parts"


def test_prompt_on_stdin_lists_indices_and_rubric(tmp_path):
    cmd = script(
        tmp_path,
        "p = sys.stdin.read()\n"
        "ok = 'Integration by parts with u = x.' in p and '[1]' in p and 'by parts' in p\n"
        "print(json.dumps({'lines': [{'index': 1, 'verdict': 'pass' if ok else 'fail'}, {'index': 3, 'verdict': 'pass'}]}))",
    )
    assert statuses(run(result_with_undecided(), cmd))[1] == "agent_pass"


def test_prompt_file_placeholder(tmp_path):
    cmd = script(
        tmp_path,
        "p = open(sys.argv[1]).read()\n"
        "v = 'pass' if 'Indices to judge: [1, 3]' in p else 'fail'\n"
        "print(json.dumps({'lines': [{'index': 1, 'verdict': v}, {'index': 3, 'verdict': v}]}))",
    ) + " {prompt_file}"
    assert statuses(run(result_with_undecided(), cmd)) == ["pass", "agent_pass", "fail", "agent_pass"]


def test_missing_line_in_reply_becomes_unverified(tmp_path):
    cmd = script(tmp_path, "sys.stdin.read()\nprint(json.dumps({'lines': [{'index': 1, 'verdict': 'pass'}]}))")
    out = run(result_with_undecided(), cmd)
    assert statuses(out) == ["pass", "agent_pass", "fail", "unverified"]


@pytest.mark.parametrize(
    "body, reason",
    [
        ("sys.stdin.read()\nprint('I think it is fine')", "no JSON"),
        ("sys.stdin.read()\nprint(json.dumps({'lines': [{'index': 'x', 'verdict': 'maybe'}]}))", "invalid"),
        ("sys.stdin.read()\nsys.exit(3)", "exit"),
        ("sys.stdin.read()\nsys.stdout.write('x' * 1_100_000)", "too large"),
    ],
)
def test_bad_agent_output_leaves_lines_unverified(tmp_path, body, reason):
    out = run(result_with_undecided(), script(tmp_path, body))
    assert statuses(out) == ["pass", "unverified", "fail", "unverified"]
    assert reason in out["lines"][1]["verdict"]["reason"]


def test_timeout_kills_the_agent(tmp_path):
    start = time.monotonic()
    out = run(result_with_undecided(), script(tmp_path, "time.sleep(30)"), timeout=1)
    assert time.monotonic() - start < 5
    assert "timed out" in out["lines"][1]["verdict"]["reason"]


def test_no_command_configured(tmp_path):
    out = run(result_with_undecided(), None)
    assert statuses(out) == ["pass", "unverified", "fail", "unverified"]
    assert "no grader" in out["lines"][1]["verdict"]["reason"]


def test_nothing_undecided_never_calls_the_agent(tmp_path):
    marker = tmp_path / "called"
    result = result_with_undecided()
    for line in result["lines"]:
        line["verdict"] = {"status": "pass"}
    run(result, script(tmp_path, f"open({str(marker)!r}, 'w').write('x')"))
    assert not marker.exists()


# ------------------------------------------------------------------ DB integration
@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "q.db")
    data = EX.model_dump(mode="json")
    with c:
        db.insert_revision(
            c,
            {"id": "quiz", "title": "T", "course": "C", "source": {"sha256": "0" * 64}},
            [{"id": EX.id, "type": "exercise", "points": EX.points, "data": data}],
            {},
        )
    yield c
    c.close()


def test_complete_answer_updates_db(tmp_path, conn):
    aid = db.create_attempt(conn, "quiz")
    db.save_answer(conn, aid, EX.id, {"steps": []}, result_with_undecided(), "pending_agent", 0)
    cmd = script(tmp_path, "sys.stdin.read()\nprint(json.dumps({'lines': [{'index': 1, 'verdict': 'pass'}, {'index': 3, 'verdict': 'pass'}]}))")
    asyncio.run(ag.complete_answer(conn, aid, EX.id, ag.GraderConfig(cmd, 10)))
    row = db.get_answer(conn, aid, EX.id)
    assert row["status"] == "graded"
    assert statuses(json.loads(row["verdict_json"])) == ["pass", "agent_pass", "fail", "agent_pass"]
    assert row["score"] == 0  # line 2 failed deterministically


def test_recover_stuck_answers_marks_unverified(conn):
    aid = db.create_attempt(conn, "quiz")
    result = result_with_undecided()
    result["lines"][2]["verdict"] = {"status": "pass"}
    db.save_answer(conn, aid, EX.id, {"steps": []}, result, "pending_agent", 0)
    assert ag.recover_stuck(conn) == 1
    row = db.get_answer(conn, aid, EX.id)
    assert row["status"] == "graded"
    assert statuses(json.loads(row["verdict_json"])) == ["pass", "unverified", "pass", "unverified"]
    assert row["score"] == EX.points  # unverified does not count as a failure


def test_config_from_settings(conn):
    assert ag.GraderConfig.from_db(conn).command is None
    db.set_setting(conn, "grader.command", "claude -p")
    db.set_setting(conn, "grader.timeout", "45")
    assert ag.GraderConfig.from_db(conn) == ag.GraderConfig("claude -p", 45.0)
