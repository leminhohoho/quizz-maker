"""SQLite storage: numbered migrations, content written only by the importer."""

import json
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from quizz import paths

MIGRATIONS = sorted(
    (p for p in resources.files("quizz.db").joinpath("migrations").iterdir() if p.name.endswith(".sql")),
    key=lambda p: p.name,
)
SCHEMA_VERSION = len(MIGRATIONS)


class AlreadyAnswered(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or paths.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number <= version:
            continue
        with conn:
            conn.executescript(migration.read_text())
            conn.execute(f"PRAGMA user_version = {number}")


# ------------------------------------------------------------------ content (importer only)
def insert_revision(conn, package: dict, questions: list[dict], assets: dict[str, tuple[str, bytes]]) -> int:
    """Insert one package revision. Call inside a transaction (`with conn:`). Returns the revision."""
    quiz_id = package["id"]
    row = conn.execute("SELECT current_revision FROM quiz WHERE id = ?", (quiz_id,)).fetchone()
    revision = 1 if row is None else row["current_revision"] + 1
    if row is None:
        conn.execute(
            "INSERT INTO quiz (id, title, course, current_revision) VALUES (?, ?, ?, ?)",
            (quiz_id, package["title"], package["course"], revision),
        )
    else:
        conn.execute(
            "UPDATE quiz SET title = ?, course = ?, current_revision = ? WHERE id = ?",
            (package["title"], package["course"], revision, quiz_id),
        )
    conn.execute(
        "INSERT INTO quiz_revision (quiz_id, revision, package_json, source_sha256, imported_at) VALUES (?, ?, ?, ?, ?)",
        (quiz_id, revision, json.dumps(package), package["source"]["sha256"], now()),
    )
    conn.executemany(
        "INSERT INTO question (quiz_id, revision, question_id, position, type, points, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(quiz_id, revision, q["id"], i, q["type"], q["points"], json.dumps(q["data"])) for i, q in enumerate(questions)],
    )
    conn.executemany(
        "INSERT INTO asset (quiz_id, revision, path, mime, bytes) VALUES (?, ?, ?, ?, ?)",
        [(quiz_id, revision, path, mime, data) for path, (mime, data) in assets.items()],
    )
    return revision


def delete_quiz(conn, quiz_id: str) -> bool:
    return conn.execute("DELETE FROM quiz WHERE id = ?", (quiz_id,)).rowcount > 0


# ------------------------------------------------------------------ reads
def list_quizzes(conn) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT q.id, q.title, q.course, q.current_revision,
               (SELECT count(*) FROM question WHERE quiz_id = q.id AND revision = q.current_revision) AS questions,
               (SELECT count(*) FROM attempt WHERE quiz_id = q.id) AS attempts,
               (SELECT max(score) FROM attempt WHERE quiz_id = q.id AND finished_at IS NOT NULL) AS best_score,
               (SELECT score FROM attempt WHERE quiz_id = q.id AND finished_at IS NOT NULL
                 ORDER BY finished_at DESC, id DESC LIMIT 1) AS last_score
        FROM quiz q ORDER BY q.course, q.title
        """
    ).fetchall()


def get_quiz(conn, quiz_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM quiz WHERE id = ?", (quiz_id,)).fetchone()


def get_revision(conn, quiz_id: str, revision: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM quiz_revision WHERE quiz_id = ? AND revision = ?", (quiz_id, revision)
    ).fetchone()


def questions(conn, quiz_id: str, revision: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM question WHERE quiz_id = ? AND revision = ? ORDER BY position", (quiz_id, revision)
    ).fetchall()


def get_asset(conn, quiz_id: str, revision: int, path: str) -> tuple[str, bytes] | None:
    row = conn.execute(
        "SELECT mime, bytes FROM asset WHERE quiz_id = ? AND revision = ? AND path = ?", (quiz_id, revision, path)
    ).fetchone()
    return (row["mime"], bytes(row["bytes"])) if row else None


# ------------------------------------------------------------------ attempts and answers
def create_attempt(conn, quiz_id: str) -> int:
    with conn:
        quiz = get_quiz(conn, quiz_id)
        if quiz is None:
            raise KeyError(quiz_id)
        revision = quiz["current_revision"]
        max_score = conn.execute(
            "SELECT coalesce(sum(points), 0) FROM question WHERE quiz_id = ? AND revision = ?", (quiz_id, revision)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO attempt (quiz_id, revision, started_at, max_score) VALUES (?, ?, ?, ?)",
            (quiz_id, revision, now(), max_score),
        )
        return cur.lastrowid


def get_attempt(conn, attempt_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT a.*, (SELECT coalesce(sum(score), 0) FROM answer WHERE attempt_id = a.id) AS live_score,
                  (SELECT count(*) FROM answer WHERE attempt_id = a.id) AS answered
           FROM attempt a WHERE id = ?""",
        (attempt_id,),
    ).fetchone()


def attempts_for(conn, quiz_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, (SELECT coalesce(sum(score), 0) FROM answer WHERE attempt_id = a.id) AS live_score
           FROM attempt a WHERE quiz_id = ? ORDER BY id DESC""",
        (quiz_id,),
    ).fetchall()


def recent_attempts(conn, limit: int = 8) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, q.title, (SELECT coalesce(sum(score), 0) FROM answer WHERE attempt_id = a.id) AS live_score
           FROM attempt a JOIN quiz q ON q.id = a.quiz_id ORDER BY a.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def answers(conn, attempt_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM answer WHERE attempt_id = ?", (attempt_id,)).fetchall()
    return {r["question_id"]: r for r in rows}


def get_answer(conn, attempt_id: int, question_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM answer WHERE attempt_id = ? AND question_id = ?", (attempt_id, question_id)
    ).fetchone()


def save_answer(conn, attempt_id, question_id, response, verdict, status, score) -> None:
    try:
        with conn:
            conn.execute(
                """INSERT INTO answer (attempt_id, question_id, response_json, verdict_json, status, score, graded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (attempt_id, question_id, json.dumps(response), json.dumps(verdict), status, score, now()),
            )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc) or "PRIMARY KEY" in str(exc):
            raise AlreadyAnswered(question_id) from None
        raise


def update_answer(conn, attempt_id, question_id, verdict, status, score) -> None:
    with conn:
        conn.execute(
            "UPDATE answer SET verdict_json = ?, status = ?, score = ?, graded_at = ? WHERE attempt_id = ? AND question_id = ?",
            (json.dumps(verdict), status, score, now(), attempt_id, question_id),
        )


def pending_answers(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM answer WHERE status = 'pending_agent'").fetchall()


def finish_attempt(conn, attempt_id: int) -> None:
    with conn:
        conn.execute(
            """UPDATE attempt SET finished_at = coalesce(finished_at, ?),
                      score = (SELECT coalesce(sum(score), 0) FROM answer WHERE attempt_id = ?)
               WHERE id = ?""",
            (now(), attempt_id, attempt_id),
        )


# ------------------------------------------------------------------ settings
def get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
