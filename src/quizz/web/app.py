"""FastAPI + HTMX web app: one question at a time, verdict fragments, live agent grading."""

import itertools
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from quizz import agent_grader as ag
from quizz import db
from quizz.checkers import get as get_checker
from quizz.grading import exercise_score, grade
from quizz.schema import Exercise, MathAnswer, question_from_data
from quizz.web import render

HERE = Path(__file__).parent
TYPE_LABELS = {
    "mcq": "MCQ",
    "multi_select": "Multi-select",
    "fill_blank": "Fill in the blank",
    "math_answer": "Math answer",
    "exercise": "Exercise",
}
BADGES = {
    "pass": "checker",
    "fail": "checker",
    "pass_numeric": "numeric",
    "agent_pass": "agent",
    "agent_fail": "agent",
    "undecided": "agent",
    "unverified": "unverified",
    "parse_error": "parse",
}
MARKS = {"pass": "✓", "pass_numeric": "✓", "agent_pass": "✓", "fail": "✗", "agent_fail": "✗", "parse_error": "!",
         "undecided": "◌", "unverified": "?"}  # fmt: skip


def create_app(*, db_path: Path | None = None, runner=None) -> FastAPI:
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["score"] = render.fmt_score
    templates.env.globals.update(TYPE_LABELS=TYPE_LABELS, BADGES=BADGES, MARKS=MARKS)

    @asynccontextmanager
    async def lifespan(app):
        conn = db.connect(db_path)
        ag.recover_stuck(conn)
        conn.close()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def get_conn():
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ helpers
    def shell(conn) -> dict:
        quizzes = db.list_quizzes(conn)
        courses = [(course, list(rows)) for course, rows in itertools.groupby(quizzes, key=lambda r: r["course"])]
        return {"courses": courses, "recent": db.recent_attempts(conn)}

    def page(request, name, conn, **ctx):
        return templates.TemplateResponse(request, name, {**shell(conn), **ctx})

    def load_attempt(conn, aid: int):
        attempt = db.get_attempt(conn, aid)
        if attempt is None:
            raise HTTPException(404, "no such attempt")
        rows = db.questions(conn, attempt["quiz_id"], attempt["revision"])
        quiz = db.get_quiz(conn, attempt["quiz_id"])
        return attempt, rows, quiz

    def load_question(conn, aid: int, n: int):
        attempt, rows, quiz = load_attempt(conn, aid)
        if not 1 <= n <= len(rows):
            raise HTTPException(404, "no such question")
        row = rows[n - 1]
        question, refs = question_from_data(json.loads(row["data_json"]))
        return attempt, rows, quiz, question, refs

    def asset_base(attempt) -> str:
        return f"/assets/{attempt['quiz_id']}/{attempt['revision']}"

    def widget(question) -> str:
        if isinstance(question, MathAnswer):
            return get_checker(question.check.checker).widget
        return "math"

    def question_ctx(attempt, rows, quiz, question, n) -> dict:
        base = asset_base(attempt)
        prompt = (
            render.fill_prompt(question.prompt, base)
            if question.type == "fill_blank"
            else render.markdown(question.prompt, base)
        )
        choices = [
            {"id": c.id, "html": render.markdown(c.text, base, inline=True)} for c in getattr(question, "choices", []) or []
        ]
        return {
            "attempt": attempt,
            "quiz": quiz,
            "q": question,
            "n": n,
            "total": len(rows),
            "prompt_html": prompt,
            "choices": choices,
            "widget": widget(question),
            "hint": hint(question),
        }

    def hint(question) -> str:
        if isinstance(question, MathAnswer) and question.check.checker == "numeric_units":
            p = question.check.params
            bits = []
            if p.get("unit"):
                bits.append(f"units required ({p['unit']})")
            if p.get("sig_figs"):
                bits.append(f"{p['sig_figs']} significant figures")
            return " · ".join(bits) or "number"
        if isinstance(question, MathAnswer) and question.check.checker == "reaction_balance":
            return "e.g. 2H2 + O2 -> 2H2O"
        if isinstance(question, MathAnswer) and question.check.checker == "transform":
            roc = question.check.params.get("region_of_convergence")
            return "answer, then region of convergence after a comma" if roc else ""
        if isinstance(question, Exercise):
            return "⏎ new step · ⌥⏎ add reason · ⌘⏎ check"
        if question.type == "fill_blank":
            return "Tab between blanks · ⌘⏎ check"
        if question.type in ("mcq", "multi_select"):
            return "number keys select · ⌘⏎ check"
        return "⌘⏎ check"

    def verdict_ctx(conn, aid: int, n: int) -> dict:
        attempt, rows, quiz, question, _ = load_question(conn, aid, n)
        row = db.get_answer(conn, aid, question.id)
        if row is None:
            raise HTTPException(404, "not answered yet")
        result = json.loads(row["verdict_json"])
        base = asset_base(attempt)
        ctx = question_ctx(attempt, rows, quiz, question, n)
        ctx.update(
            result=result,
            response=json.loads(row["response_json"]),
            score=row["score"],
            pending=row["status"] == "pending_agent",
            unverified=any(l["verdict"]["status"] == "unverified" for l in result.get("lines", [])),
            explanation_html=render.markdown(question.explanation, base) if question.explanation else "",
            next_url=f"/attempts/{aid}/q/{n + 1}" if n < len(rows) else f"/attempts/{aid}/summary",
        )
        return ctx

    def verdict(request, conn, aid: int, n: int):
        return templates.TemplateResponse(request, "partials/verdict.html", verdict_ctx(conn, aid, n))

    def error_fragment(request, message: str, status: int):
        return templates.TemplateResponse(request, "partials/error.html", {"message": message}, status_code=status)

    async def finish_agent_grading(aid: int, qid: str):
        conn = db.connect(db_path)
        try:
            await ag.complete_answer(conn, aid, qid, ag.GraderConfig.from_db(conn))
        finally:
            conn.close()

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, conn=Depends(get_conn)):
        return page(request, "home.html", conn)

    @app.get("/quiz/{quiz_id}", response_class=HTMLResponse)
    def quiz_page(request: Request, quiz_id: str, conn=Depends(get_conn)):
        quiz = db.get_quiz(conn, quiz_id)
        if quiz is None:
            raise HTTPException(404, "no such quiz")
        rows = db.questions(conn, quiz_id, quiz["current_revision"])
        counts = {}
        for r in rows:
            counts[r["type"]] = counts.get(r["type"], 0) + 1
        attempts = db.attempts_for(conn, quiz_id)
        flags = {a["id"]: _has_unverified(conn, a["id"]) for a in attempts}
        return page(request, "quiz.html", conn, quiz=quiz, questions=rows, counts=counts, attempts=attempts, flags=flags,
                    points=sum(r["points"] for r in rows))  # fmt: skip

    @app.post("/quiz/{quiz_id}/attempts")
    def new_attempt(quiz_id: str, conn=Depends(get_conn)):
        try:
            aid = db.create_attempt(conn, quiz_id)
        except KeyError:
            raise HTTPException(404, "no such quiz") from None
        return RedirectResponse(f"/attempts/{aid}/q/1", status_code=303)

    @app.get("/attempts/{aid}")
    def resume(aid: int, conn=Depends(get_conn)):
        _, rows, _ = load_attempt(conn, aid)
        answered = db.answers(conn, aid)
        for n, row in enumerate(rows, start=1):
            if row["question_id"] not in answered:
                return RedirectResponse(f"/attempts/{aid}/q/{n}", status_code=303)
        return RedirectResponse(f"/attempts/{aid}/summary", status_code=303)

    @app.get("/attempts/{aid}/q/{n}", response_class=HTMLResponse)
    def question_page(request: Request, aid: int, n: int, conn=Depends(get_conn)):
        attempt, rows, quiz, question, _ = load_question(conn, aid, n)
        if db.get_answer(conn, aid, question.id) is not None:
            return page(request, "question.html", conn, answered=True, **verdict_ctx(conn, aid, n))
        return page(request, "question.html", conn, answered=False,
                    **question_ctx(attempt, rows, quiz, question, n))  # fmt: skip

    @app.post("/attempts/{aid}/q/{n}", response_class=HTMLResponse)
    def submit(
        request: Request,
        aid: int,
        n: int,
        background: BackgroundTasks,
        response: str | None = Form(None),
        conn=Depends(get_conn),
    ):
        attempt, rows, quiz, question, refs = load_question(conn, aid, n)
        if db.get_answer(conn, aid, question.id) is not None:
            return verdict(request, conn, aid, n)
        try:
            payload = json.loads(response or "")
            graded = grade(question, payload, seed_key=f"{attempt['quiz_id']}:{attempt['revision']}",
                           runner=runner, reference_values=refs)  # fmt: skip
        except ValueError as exc:  # includes JSONDecodeError
            return error_fragment(request, f"Could not read your answer: {exc}", 400)
        result, score, status = graded.result, graded.score, "graded"
        if graded.pending:
            if ag.GraderConfig.from_db(conn).command:
                status = "pending_agent"
            else:
                result = ag.mark_unverified(result, graded.pending, "no grader command configured")
                score = exercise_score(result, question.points)
        try:
            db.save_answer(conn, aid, question.id, payload, result, status, score)
        except db.AlreadyAnswered:
            return verdict(request, conn, aid, n)
        if status == "pending_agent":
            background.add_task(finish_agent_grading, aid, question.id)
        return verdict(request, conn, aid, n)

    @app.get("/attempts/{aid}/q/{n}/verdict", response_class=HTMLResponse)
    def verdict_fragment(request: Request, aid: int, n: int, conn=Depends(get_conn)):
        return verdict(request, conn, aid, n)

    @app.post("/attempts/{aid}/q/{n}/regrade", response_class=HTMLResponse)
    def regrade(request: Request, aid: int, n: int, background: BackgroundTasks, conn=Depends(get_conn)):
        _, _, _, question, _ = load_question(conn, aid, n)
        row = db.get_answer(conn, aid, question.id)
        if row is None:
            raise HTTPException(404, "not answered yet")
        result = json.loads(row["verdict_json"])
        indices = [i for i, l in enumerate(result.get("lines", [])) if l["verdict"]["status"] == "unverified"]
        if indices and ag.GraderConfig.from_db(conn).command:
            for i in indices:
                result["lines"][i]["verdict"] = {"status": "undecided"}
            db.update_answer(conn, aid, question.id, result, "pending_agent", row["score"])
            background.add_task(finish_agent_grading, aid, question.id)
        return verdict(request, conn, aid, n)

    @app.get("/attempts/{aid}/summary", response_class=HTMLResponse)
    def summary(request: Request, aid: int, conn=Depends(get_conn)):
        attempt, rows, quiz = load_attempt(conn, aid)
        db.finish_attempt(conn, aid)
        attempt = db.get_attempt(conn, aid)
        answers = db.answers(conn, aid)
        items = []
        for n, row in enumerate(rows, start=1):
            data = json.loads(row["data_json"])
            ans = answers.get(row["question_id"])
            result = json.loads(ans["verdict_json"]) if ans else {}
            items.append({
                "n": n,
                "type": row["type"],
                "snippet": render.plain(data["prompt"]),
                "points": row["points"],
                "score": ans["score"] if ans else None,
                "pending": bool(ans) and ans["status"] == "pending_agent",
                "unverified": any(l["verdict"]["status"] == "unverified" for l in result.get("lines", [])),
            })  # fmt: skip
        return page(request, "summary.html", conn, attempt=attempt, quiz=quiz, items=items)

    @app.get("/assets/{quiz_id}/{revision}/{path:path}")
    def asset(quiz_id: str, revision: int, path: str, conn=Depends(get_conn)):
        found = db.get_asset(conn, quiz_id, revision, path)
        if found is None:
            raise HTTPException(404, "no such asset")
        mime, data = found
        return Response(data, media_type=mime, headers={"Cache-Control": "max-age=86400"})

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, conn=Depends(get_conn)):
        config = ag.GraderConfig.from_db(conn)
        return page(request, "settings.html", conn, config=config)

    @app.post("/settings")
    def save_settings(grader_command: str = Form(""), grader_timeout: str = Form(""), conn=Depends(get_conn)):
        db.set_setting(conn, "grader.command", grader_command.strip())
        try:
            timeout = float(grader_timeout)
        except ValueError:
            timeout = ag.DEFAULT_TIMEOUT
        db.set_setting(conn, "grader.timeout", f"{max(1.0, timeout):g}")
        return RedirectResponse("/settings", status_code=303)

    return app


def _has_unverified(conn, aid: int) -> bool:
    for row in db.answers(conn, aid).values():
        result = json.loads(row["verdict_json"])
        if any(l["verdict"]["status"] == "unverified" for l in result.get("lines", [])):
            return True
    return False
