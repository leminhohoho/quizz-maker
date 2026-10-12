"""Live grading of undecided exercise lines by a headless coding agent.

The app runs `grader.command` (shell template). If it contains `{prompt_file}` that placeholder becomes
the quoted path of a file holding the prompt; otherwise the prompt goes to stdin. The reply must end with
`{"lines": [{"index": N, "verdict": "pass"|"fail", "comment": "..."}]}`. Agent verdicts only ever
replace `undecided` lines; deterministic verdicts are never overridden.
"""

import asyncio
import copy
import json
import os
import shlex
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from quizz import db
from quizz.grading import exercise_score
from quizz.schema import Exercise, question_from_data

MAX_OUTPUT = 1_000_000
DEFAULT_TIMEOUT = 120.0


class GraderError(Exception):
    pass


@dataclass
class GraderConfig:
    command: str | None
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_db(cls, conn) -> "GraderConfig":
        command = (db.get_setting(conn, "grader.command") or "").strip() or None
        timeout = db.get_setting(conn, "grader.timeout")
        return cls(command, float(timeout) if timeout else DEFAULT_TIMEOUT)


class _ReplyLine(BaseModel):
    index: int
    verdict: Literal["pass", "fail"]
    comment: str = ""


class _Reply(BaseModel):
    lines: list[_ReplyLine]


def undecided_indices(result: dict) -> list[int]:
    return [i for i, line in enumerate(result["lines"]) if line["verdict"]["status"] == "undecided"]


def build_prompt(ex: Exercise, result: dict, indices: list[int]) -> str:
    ctx = ex.context
    parts = [
        "You are grading lines of a student's step-by-step solution. Deterministic checkers already judged",
        "the other lines; judge ONLY the lines listed under 'Indices to judge'. A line passes when it is a",
        "mathematically valid step from the previous line (or a correct statement in context) and its",
        "justification, if any, is sound.",
        "",
        "## Exercise",
        ex.prompt,
    ]
    if ctx.symbols or ctx.givens or ctx.relations:
        parts += ["", "## Context"]
        parts += [f"- symbol {name}: {d.description or ''} {('[' + d.unit + ']') if d.unit else ''}".rstrip() for name, d in ctx.symbols.items()]
        parts += [f"- given {name} = {g.value} {g.unit}".rstrip() for name, g in ctx.givens.items()]
        parts += [f"- relation: {r}" for r in ctx.relations]
    if ex.start:
        parts += ["", f"Starting expression: {ex.start}"]
    parts += ["", "## Reference solution"]
    parts += [f"- {s.latex}" + (f"  ({s.justification})" if s.justification else "") for s in ex.reference_solution]
    if ex.rubric:
        parts += ["", "## Rubric", ex.rubric]
    parts += ["", "## Student lines (LaTeX) with checker verdicts"]
    for i, line in enumerate(result["lines"]):
        why = f"  — justification: {line['justification']}" if line.get("justification") else ""
        parts.append(f"[{i}] {line['latex']}{why}   <{line['verdict']['status']}>")
    parts += [
        "",
        f"Indices to judge: {indices}",
        "",
        "End your reply with exactly one JSON object and nothing after it:",
        '{"lines": [{"index": <int>, "verdict": "pass" or "fail", "comment": "<one sentence>"}]}',
    ]
    return "\n".join(parts)


def parse_reply(stdout: str) -> _Reply:
    decoder = json.JSONDecoder()
    found = None
    for pos in range(len(stdout) - 1, -1, -1):
        if stdout[pos] != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout, pos)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "lines" in value:
            found = value
            break
    if found is None:
        raise GraderError("agent reply contained no JSON verdict object")
    try:
        return _Reply.model_validate(found)
    except ValidationError as exc:
        raise GraderError(f"agent reply JSON is invalid: {exc.errors()[0]['msg']}") from None


async def run_command(config: GraderConfig, prompt: str) -> str:
    with tempfile.TemporaryDirectory(prefix="quizz-grader-") as tmp:
        command = config.command
        stdin_data = prompt.encode()
        if "{prompt_file}" in command:
            prompt_file = Path(tmp) / "prompt.md"
            prompt_file.write_text(prompt)
            command = command.replace("{prompt_file}", shlex.quote(str(prompt_file)))
            stdin_data = b""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp,
            start_new_session=True,
        )

        stderr_task = asyncio.create_task(proc.stderr.read())

        async def communicate() -> bytes:
            if stdin_data:
                proc.stdin.write(stdin_data)
                try:
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            proc.stdin.close()
            out = bytearray()
            while chunk := await proc.stdout.read(65536):
                out += chunk
                if len(out) > MAX_OUTPUT:
                    raise GraderError(f"agent output too large (> {MAX_OUTPUT} bytes)")
            await proc.wait()
            return bytes(out)

        try:
            stdout = await asyncio.wait_for(communicate(), config.timeout)
        except (TimeoutError, GraderError) as exc:
            _kill(proc)
            await proc.wait()
            await stderr_task
            if isinstance(exc, TimeoutError):
                raise GraderError(f"agent timed out after {config.timeout:g}s") from None
            raise
        err = (await stderr_task).decode(errors="replace").strip()[-300:]
        if proc.returncode != 0:
            raise GraderError(f"agent exited with status {proc.returncode}" + (f": {err}" if err else ""))
        return stdout.decode(errors="replace")


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def mark_unverified(result: dict, indices: list[int], reason: str) -> dict:
    result = copy.deepcopy(result)
    for i in indices:
        result["lines"][i]["verdict"] = {"status": "unverified", "reason": reason}
    return result


async def grade_undecided(ex: Exercise, result: dict, config: GraderConfig) -> dict:
    """Return a copy of `result` with every `undecided` line judged by the agent or marked unverified."""
    indices = undecided_indices(result)
    if not indices:
        return result
    if not config.command:
        return mark_unverified(result, indices, "no grader command configured")
    try:
        reply = parse_reply(await run_command(config, build_prompt(ex, result, indices)))
    except GraderError as exc:
        return mark_unverified(result, indices, str(exc))
    result = copy.deepcopy(result)
    judged = {line.index: line for line in reply.lines if line.index in indices}
    for i in indices:
        line = judged.get(i)
        if line is None:
            result["lines"][i]["verdict"] = {"status": "unverified", "reason": "the agent did not judge this line"}
        else:
            verdict = {"status": f"agent_{line.verdict}"}
            if line.comment:
                verdict["reason"] = line.comment
            result["lines"][i]["verdict"] = verdict
    return result


def _question(conn, attempt_id: int, question_id: str) -> Exercise:
    attempt = db.get_attempt(conn, attempt_id)
    row = conn.execute(
        "SELECT data_json FROM question WHERE quiz_id = ? AND revision = ? AND question_id = ?",
        (attempt["quiz_id"], attempt["revision"], question_id),
    ).fetchone()
    question, _ = question_from_data(json.loads(row["data_json"]))
    return question


async def complete_answer(conn, attempt_id: int, question_id: str, config: GraderConfig) -> None:
    """Grade the undecided lines of a stored `pending_agent` answer and mark it graded."""
    ex = _question(conn, attempt_id, question_id)
    row = db.get_answer(conn, attempt_id, question_id)
    result = await grade_undecided(ex, json.loads(row["verdict_json"]), config)
    db.update_answer(conn, attempt_id, question_id, result, "graded", exercise_score(result, ex.points))


def recover_stuck(conn) -> int:
    """At startup: answers left `pending_agent` by a crash or restart become unverified."""
    rows = db.pending_answers(conn)
    for row in rows:
        ex = _question(conn, row["attempt_id"], row["question_id"])
        result = json.loads(row["verdict_json"])
        result = mark_unverified(result, undecided_indices(result), "grading was interrupted by an app restart")
        db.update_answer(conn, row["attempt_id"], row["question_id"], result, "graded", exercise_score(result, ex.points))
    return len(rows)
