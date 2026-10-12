"""`quizz` command line. JSON on stdout; exit 0 ok, 1 content invalid, 2 usage/environment error."""

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from quizz import db, importer, ingest, paths, schema
from quizz.checkers import REGISTRY

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Compile lecture slides into quizzes.")

Human = Annotated[bool, typer.Option("--human", help="Readable output instead of JSON.")]
SKILL_DIRS = (".claude/skills", ".agents/skills")  # Claude Code; Codex and pi
SKILL_SOURCE = Path(__file__).resolve().parents[2] / "skills" / "quizz-compile"


def _emit(payload: dict, human: bool, code: int = 0) -> None:
    if human:
        typer.echo(_human(payload))
    else:
        typer.echo(json.dumps(payload, indent=2, default=str))
    raise typer.Exit(code)


def _human(payload: dict) -> str:
    if "ok" in payload or "errors" in payload:
        lines = ["ok" if payload.get("ok", not payload.get("errors")) else "failed"]
        for kind in ("errors", "warnings"):
            for item in payload.get(kind, []):
                hint = f"  (hint: {item['hint']})" if item.get("hint") else ""
                lines.append(f"{kind[:-1]}: {item.get('path') or '-'}: {item['code']}: {item['message']}{hint}")
        extra = {k: v for k, v in payload.items() if k not in ("ok", "errors", "warnings")}
        if extra:
            lines.append(json.dumps(extra, indent=2, default=str))
        return "\n".join(lines)
    return json.dumps(payload, indent=2, default=str)


def _error(code: str, message: str, hint: str = "", path: str = "") -> dict:
    return {"ok": False, "errors": [{k: v for k, v in dict(path=path, code=code, message=message, hint=hint).items() if v}]}


@app.command("ingest")
def ingest_cmd(file: Path, human: Human = False):
    """Convert slides (PDF/PPTX) to per-page text and images under $QUIZZ_HOME/build/."""
    if not file.is_file():
        _emit(_error("not_found", f"{file} does not exist"), human, 2)
    try:
        info = ingest.ingest(file)
    except ingest.MissingDependency as exc:
        _emit(_error("missing_dependency", str(exc), exc.hint), human, 2)
    except ValueError as exc:
        _emit(_error("unsupported_file", str(exc)), human, 2)
    except RuntimeError as exc:
        _emit(_error("conversion_failed", str(exc)), human, 2)
    _emit(info, human)


@app.command("schema")
def schema_cmd(
    type: Annotated[str | None, typer.Option("--type", help="Only one question type.")] = None, human: Human = False
):
    """JSON Schema of the quiz package (or one question type)."""
    try:
        _emit(schema.json_schema(type), human)
    except ValueError as exc:
        _emit(_error("unknown_type", str(exc)), human, 2)


@app.command("checkers")
def checkers_cmd(human: Human = False):
    """Available checkers: params schema, input widget, example."""
    _emit({"checkers": [c.describe() for c in REGISTRY.values()]}, human)


@app.command("check")
def check_cmd(
    package: Path,
    question: Annotated[str | None, typer.Option("--question", help="Only check this question id.")] = None,
    human: Human = False,
):
    """Validate a package and verify every reference solution. Writes nothing."""
    report = importer.check_package(package, question_id=question)
    _emit(report.to_dict(), human, 0 if report.ok else 1)


@app.command("import")
def import_cmd(package: Path, human: Human = False):
    """Check, then insert the package into the database as a new revision."""
    conn = db.connect()
    try:
        result = importer.import_package(package, conn=conn)
    except importer.ImportRejected as exc:
        _emit(exc.report.to_dict(), human, 1)
    finally:
        conn.close()
    _emit(
        {
            "ok": True,
            "quiz_id": result.quiz_id,
            "revision": result.revision,
            "questions": result.questions,
            "library_path": str(result.library_path) if result.library_path else None,
            "warnings": [w.to_dict() for w in result.warnings],
        },
        human,
    )


@app.command("list")
def list_cmd(human: Human = False):
    """Imported quizzes."""
    conn = db.connect()
    rows = [dict(r) for r in db.list_quizzes(conn)]
    conn.close()
    _emit({"quizzes": rows}, human)


@app.command("rm")
def rm_cmd(
    quiz_id: str,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
    human: Human = False,
):
    """Remove a quiz, all its revisions and attempts."""
    conn = db.connect()
    try:
        if db.get_quiz(conn, quiz_id) is None:
            _emit(_error("not_found", f"no quiz {quiz_id!r}"), human, 1)
        if not yes and not typer.confirm(f"Delete {quiz_id} and all its attempts?", err=True):
            _emit(_error("aborted", "not deleted"), human, 1)
        with conn:
            db.delete_quiz(conn, quiz_id)
    finally:
        conn.close()
    _emit({"ok": True, "removed": quiz_id}, human)


@app.command("install-skill")
def install_skill_cmd(human: Human = False):
    """Symlink skills/quizz-compile into the Claude Code, Codex and pi skill directories."""
    home = Path(os.environ.get("HOME", Path.home()))
    links = []
    for d in SKILL_DIRS:
        link = home / d / "quizz-compile"
        if link.is_symlink():
            if link.resolve() == SKILL_SOURCE.resolve():
                links.append(str(link))
                continue
            link.unlink()
        elif link.exists():
            _emit(_error("exists", f"{link} exists and is not a symlink; remove it first"), human, 2)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(SKILL_SOURCE, target_is_directory=True)
        links.append(str(link))
    _emit({"ok": True, "skill": str(SKILL_SOURCE), "links": links}, human)


@app.command("serve")
def serve_cmd(port: int = 8000, host: str = "127.0.0.1"):
    """Start the web app."""
    import uvicorn

    typer.echo(f"quizz on http://{host}:{port}  (data: {paths.home()})", err=True)
    uvicorn.run("quizz.web.app:create_app", factory=True, host=host, port=port)
