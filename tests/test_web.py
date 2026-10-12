import json
import re
import sys

import pytest
from fastapi.testclient import TestClient

from factories import EXERCISE_CHAIN, package
from quizz import db, importer
from quizz.checkers.equiv import Timeout
from quizz.web.app import create_app


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def import_pkg(tmp_path, pkg=None, assets=None):
    d = tmp_path / "pkg"
    d.mkdir(exist_ok=True)
    (d / "quiz.json").write_text(json.dumps(pkg or package()))
    for name, data in (assets or {}).items():
        (d / "assets").mkdir(exist_ok=True)
        (d / "assets" / name).write_bytes(data)
    conn = db.connect()
    importer.import_package(d / "quiz.json", conn=conn)
    conn.close()


def client(**kwargs) -> TestClient:
    return TestClient(create_app(**kwargs))


def start(c) -> int:
    r = c.post("/quiz/test-quiz/attempts", follow_redirects=False)
    assert r.status_code == 303
    m = re.match(r"/attempts/(\d+)/q/1$", r.headers["location"])
    assert m
    return int(m.group(1))


def answer(c, aid, n, response):
    return c.post(f"/attempts/{aid}/q/{n}", data={"response": json.dumps(response)})


def stored(aid, qid):
    conn = db.connect()
    row = db.get_answer(conn, aid, qid)
    conn.close()
    return row


# ------------------------------------------------------------------ pages
def test_home_empty_state_points_to_the_skill():
    r = client().get("/")
    assert r.status_code == 200 and "quizz-compile" in r.text


def test_home_and_sidebar_list_quizzes(tmp_path):
    import_pkg(tmp_path)
    r = client().get("/")
    assert "Testing 101" in r.text and "Test quiz" in r.text and 'href="/quiz/test-quiz"' in r.text


def test_quiz_overview_shows_counts_and_history(tmp_path):
    import_pkg(tmp_path)
    c = client()
    r = c.get("/quiz/test-quiz")
    assert r.status_code == 200 and "6 questions" in r.text and "2 exercise" in r.text
    aid = start(c)
    assert f"/attempts/{aid}" in c.get("/quiz/test-quiz").text


def test_unknown_ids_are_404(tmp_path):
    import_pkg(tmp_path)
    c = client()
    assert c.get("/quiz/nope").status_code == 404
    assert c.get("/attempts/99/q/1").status_code == 404
    aid = start(c)
    assert c.get(f"/attempts/{aid}/q/7").status_code == 404
    assert c.get(f"/attempts/{aid}/q/0").status_code == 404


def test_question_page_renders_composer_by_type(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    q1 = c.get(f"/attempts/{aid}/q/1").text
    assert 'data-type="mcq"' in q1 and "Ratio test" in q1 and "1 / 6" in q1
    q3 = c.get(f"/attempts/{aid}/q/3").text
    assert 'data-blank="b1"' in q3 and "{{b1}}" not in q3
    q5 = c.get(f"/attempts/{aid}/q/5").text
    assert 'data-type="exercise"' in q5 and "<math-field" in q5


# ------------------------------------------------------------------ grading each type
def test_mcq_answer_saved_and_locked(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    r = answer(c, aid, 1, {"choice": "b"})
    assert r.status_code == 200 and "1 / 1" in r.text
    again = answer(c, aid, 1, {"choice": "a"})
    assert again.status_code == 200 and "1 / 1" in again.text
    assert json.loads(stored(aid, "q-mcq")["response_json"]) == {"choice": "b"}
    assert 'data-state="verdict"' in c.get(f"/attempts/{aid}/q/1").text


def test_each_type_grades(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    assert "1 / 2" in answer(c, aid, 2, {"choices": ["h"]}).text
    assert "0.5 / 1" in answer(c, aid, 3, {"blanks": {"b1": "charge", "b2": "nope"}}).text
    assert "1 / 1" in answer(c, aid, 4, {"answer": r"2.88\times10^{-4}\,\mathrm{J}"}).text
    steps = [{"latex": s["latex"]} for s in EXERCISE_CHAIN["reference_solution"]]
    r = answer(c, aid, 5, {"steps": steps})
    assert "2 / 2" in r.text and r.text.count('data-status="pass"') == 3
    r = answer(c, aid, 6, {"steps": [{"latex": r"q=mc\Delta T"}, {"latex": r"q=4180\,\mathrm{W}"}]})
    assert "0 / 2" in r.text and "dimension" in r.text


def test_malformed_response_is_400(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    assert c.post(f"/attempts/{aid}/q/1", data={"response": "{not json"}).status_code == 400
    assert answer(c, aid, 1, {"choice": "zzz"}).status_code == 400
    assert c.post(f"/attempts/{aid}/q/1", data={}).status_code == 400
    assert stored(aid, "q-mcq") is None


# ------------------------------------------------------------------ live grading
def all_undecided(fn, *args, timeout):
    raise Timeout


def test_undecided_lines_unverified_without_grader(tmp_path):
    import_pkg(tmp_path)
    c = client(runner=all_undecided)
    aid = start(c)
    r = answer(c, aid, 5, {"steps": [{"latex": r"\int xe^{x}\,dx"}]})
    assert 'data-status="unverified"' in r.text
    assert stored(aid, "q-ibp")["status"] == "graded"


def test_undecided_lines_go_to_the_configured_agent(tmp_path):
    import_pkg(tmp_path)
    script = tmp_path / "agent.py"
    script.write_text("import sys, json\nsys.stdin.read()\nprint(json.dumps({'lines': [{'index': 0, 'verdict': 'pass', 'comment': 'fine'}]}))")
    c = client(runner=all_undecided)
    c.post("/settings", data={"grader_command": f"{sys.executable} {script}", "grader_timeout": "20"})
    aid = start(c)
    r = answer(c, aid, 5, {"steps": [{"latex": r"\int xe^{x}\,dx"}]})
    assert 'hx-trigger="every 2s"' in r.text  # polling while pending
    # TestClient runs background tasks before returning, so grading is done now
    v = c.get(f"/attempts/{aid}/q/5/verdict").text
    assert 'data-status="agent_pass"' in v and "every 2s" not in v
    assert stored(aid, "q-ibp")["status"] == "graded"


def test_regrade_retries_unverified_lines(tmp_path):
    import_pkg(tmp_path)
    c = client(runner=all_undecided)
    aid = start(c)
    answer(c, aid, 5, {"steps": [{"latex": r"\int xe^{x}\,dx"}]})
    script = tmp_path / "agent.py"
    script.write_text("import sys, json\nsys.stdin.read()\nprint(json.dumps({'lines': [{'index': 0, 'verdict': 'fail'}]}))")
    c.post("/settings", data={"grader_command": f"{sys.executable} {script}", "grader_timeout": "20"})
    c.post(f"/attempts/{aid}/q/5/regrade")
    assert 'data-status="agent_fail"' in c.get(f"/attempts/{aid}/q/5/verdict").text


def test_startup_recovers_stuck_answers(tmp_path):
    import_pkg(tmp_path)
    conn = db.connect()
    aid = db.create_attempt(conn, "test-quiz")
    result = {"lines": [{"latex": "x", "justification": "", "verdict": {"status": "undecided"}}], "final": {"status": "pass"}}
    db.save_answer(conn, aid, "q-ibp", {"steps": [{"latex": "x"}]}, result, "pending_agent", 0)
    conn.close()
    with client():
        pass
    assert stored(aid, "q-ibp")["status"] == "graded"


# ------------------------------------------------------------------ summary, assets, settings
def test_summary_finishes_attempt(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    answer(c, aid, 1, {"choice": "b"})
    r = c.get(f"/attempts/{aid}/summary")
    assert r.status_code == 200 and "1 / 9" in r.text
    conn = db.connect()
    assert db.get_attempt(conn, aid)["finished_at"]
    conn.close()


def test_resume_goes_to_first_unanswered(tmp_path):
    import_pkg(tmp_path)
    c = client()
    aid = start(c)
    answer(c, aid, 1, {"choice": "b"})
    r = c.get(f"/attempts/{aid}", follow_redirects=False)
    assert r.headers["location"] == f"/attempts/{aid}/q/2"


def test_assets_served(tmp_path):
    pkg = package()
    pkg["questions"][0]["prompt"] += " ![circuit](assets/fig.png)"
    import_pkg(tmp_path, pkg, {"fig.png": b"\x89PNGxx"})
    c = client()
    aid = start(c)
    assert 'src="/assets/test-quiz/1/assets/fig.png"' in c.get(f"/attempts/{aid}/q/1").text
    r = c.get("/assets/test-quiz/1/assets/fig.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == b"\x89PNGxx"
    assert c.get("/assets/test-quiz/1/assets/none.png").status_code == 404


def test_settings_round_trip():
    c = client()
    c.post("/settings", data={"grader_command": "claude -p", "grader_timeout": "60"})
    page = c.get("/settings").text
    assert 'value="claude -p"' in page and 'value="60"' in page


def test_prompt_markdown_keeps_math_and_escapes_html(tmp_path):
    pkg = package()
    pkg["questions"][0]["prompt"] = "Compute $x_1 * y_2$ and **bold** <script>alert(1)</script>"
    import_pkg(tmp_path, pkg)
    c = client()
    aid = start(c)
    text = c.get(f"/attempts/{aid}/q/1").text
    assert "$x_1 * y_2$" in text and "<strong>bold</strong>" in text
    assert "<script>alert(1)</script>" not in text
