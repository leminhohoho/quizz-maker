import json

import pytest

from quizz import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "q.db")
    yield c
    c.close()


def add_quiz(conn, quiz_id="q1", points=(1, 2)):
    questions = [
        {"id": f"x{i}", "type": "mcq", "points": p, "data": {"id": f"x{i}", "points": p}} for i, p in enumerate(points)
    ]
    with conn:
        return db.insert_revision(
            conn,
            {"id": quiz_id, "title": "T", "course": "C", "source": {"sha256": "0" * 64}},
            questions,
            assets={"assets/fig.png": ("image/png", b"\x89PNG")},
        )


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "q.db"
    db.connect(path).close()
    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    c.close()


def test_reimport_creates_new_revision_and_attempts_keep_theirs(conn):
    assert add_quiz(conn) == 1
    attempt = db.create_attempt(conn, "q1")
    assert add_quiz(conn, points=(5,)) == 2
    assert db.get_attempt(conn, attempt)["revision"] == 1
    assert [q["question_id"] for q in db.questions(conn, "q1", 1)] == ["x0", "x1"]
    assert db.get_quiz(conn, "q1")["current_revision"] == 2


def test_attempt_max_score_is_sum_of_points(conn):
    add_quiz(conn, points=(1, 2, 3))
    attempt = db.get_attempt(conn, db.create_attempt(conn, "q1"))
    assert attempt["max_score"] == 6


def test_finish_attempt_sums_answer_scores(conn):
    add_quiz(conn)
    aid = db.create_attempt(conn, "q1")
    db.save_answer(conn, aid, "x0", {"choice": "a"}, {"correct": True}, "graded", 1)
    db.save_answer(conn, aid, "x1", {"choice": "b"}, {"correct": False}, "graded", 0.5)
    db.finish_attempt(conn, aid)
    attempt = db.get_attempt(conn, aid)
    assert attempt["score"] == 1.5 and attempt["finished_at"]


def test_answer_is_saved_once(conn):
    add_quiz(conn)
    aid = db.create_attempt(conn, "q1")
    db.save_answer(conn, aid, "x0", {"choice": "a"}, {}, "graded", 1)
    with pytest.raises(db.AlreadyAnswered):
        db.save_answer(conn, aid, "x0", {"choice": "b"}, {}, "graded", 0)


def test_update_answer_changes_verdict_and_status(conn):
    add_quiz(conn)
    aid = db.create_attempt(conn, "q1")
    db.save_answer(conn, aid, "x0", {}, {"v": 1}, "pending_agent", 0)
    db.update_answer(conn, aid, "x0", {"v": 2}, "graded", 1)
    row = db.get_answer(conn, aid, "x0")
    assert json.loads(row["verdict_json"]) == {"v": 2} and row["status"] == "graded" and row["score"] == 1
    assert db.pending_answers(conn) == []


def test_delete_quiz_cascades(conn):
    add_quiz(conn)
    aid = db.create_attempt(conn, "q1")
    db.save_answer(conn, aid, "x0", {}, {}, "graded", 1)
    with conn:
        assert db.delete_quiz(conn, "q1") is True
    assert conn.execute("SELECT count(*) FROM answer").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM asset").fetchone()[0] == 0
    assert db.delete_quiz(conn, "q1") is False


def test_assets_round_trip(conn):
    add_quiz(conn)
    assert db.get_asset(conn, "q1", 1, "assets/fig.png") == ("image/png", b"\x89PNG")
    assert db.get_asset(conn, "q1", 1, "assets/nope.png") is None


def test_settings_round_trip(conn):
    assert db.get_setting(conn, "grader.command") is None
    db.set_setting(conn, "grader.command", "claude -p")
    db.set_setting(conn, "grader.command", "pi -p")
    assert db.get_setting(conn, "grader.command") == "pi -p"


def test_list_quizzes_reports_last_and_best_scores(conn):
    add_quiz(conn, "q1")
    add_quiz(conn, "q2")
    for score in (1, 3, 2):
        aid = db.create_attempt(conn, "q1")
        db.save_answer(conn, aid, "x0", {}, {}, "graded", score)
        db.finish_attempt(conn, aid)
    rows = {r["id"]: r for r in db.list_quizzes(conn)}
    assert rows["q1"]["best_score"] == 3 and rows["q1"]["last_score"] == 2 and rows["q1"]["attempts"] == 3
    assert rows["q2"]["best_score"] is None and rows["q2"]["attempts"] == 0
