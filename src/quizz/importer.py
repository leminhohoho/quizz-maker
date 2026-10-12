"""Compile-time gates (`quizz check`) and transactional import (`quizz import`)."""

import json
import mimetypes
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import ValidationError

from quizz import db, paths
from quizz import units as U
from quizz.checkers import get
from quizz.grading.budget import shared_runner
from quizz.grading.steps import (
    build_env,
    compute_reference_values,
    grade_steps,
    reference_values_to_json,
)
from quizz.mathparse import ParseError
from quizz.schema import MCQ, QUESTION_TYPES, Exercise, FillBlank, MathAnswer, MultiSelect, Package

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}")
ASSET_REF = re.compile(r"!\[[^\]]*\]\((assets/[^)\s]+)\)")
MATH_SPAN = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)  # same rule the web renderer uses


@dataclass
class Issue:
    path: str
    code: str
    message: str
    hint: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}


@dataclass
class CheckReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    package: Package | None = None
    reference_values: dict[str, dict] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class ImportRejected(Exception):
    def __init__(self, report: CheckReport):
        super().__init__(f"{len(report.errors)} error(s)")
        self.report = report


@dataclass
class ImportResult:
    quiz_id: str
    revision: int
    questions: dict[str, int]
    library_path: Path | None
    warnings: list[Issue]


# ------------------------------------------------------------------ check
def check_package(path: Path, *, question_id: str | None = None, runner=None) -> CheckReport:
    path = Path(path)
    report = CheckReport()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        report.errors.append(Issue("", "not_found", f"{path} does not exist"))
        return report
    except json.JSONDecodeError as exc:
        report.errors.append(Issue("", "invalid_json", str(exc)))
        return report
    try:
        pkg = Package.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            report.errors.append(Issue(_pointer(err["loc"]), err["type"], err["msg"]))
        return report
    report.package = pkg
    runner = runner or shared_runner()
    _check_ids(pkg, report)
    _check_slides(pkg, report)
    for i, q in enumerate(pkg.questions):
        if question_id is not None and q.id != question_id:
            continue
        base = f"/questions/{i}"
        _check_assets(q, base, path.parent, report)
        if isinstance(q, MCQ):
            if q.answer not in {c.id for c in q.choices}:
                report.errors.append(Issue(f"{base}/answer", "unknown_choice", f"{q.answer!r} is not a choice id"))
        elif isinstance(q, MultiSelect):
            ids = {c.id for c in q.choices}
            missing = [a for a in q.answer if a not in ids]
            if missing:
                report.errors.append(Issue(f"{base}/answer", "unknown_choice", f"not choice ids: {missing}"))
        elif isinstance(q, FillBlank):
            _check_blanks(q, base, report)
        elif isinstance(q, MathAnswer):
            _check_spec(q.check, f"{base}/check", report)
        elif isinstance(q, Exercise):
            _check_exercise(q, base, report, runner)
    if question_id is not None and all(q.id != question_id for q in pkg.questions):
        report.errors.append(Issue("/questions", "unknown_question", f"no question with id {question_id!r}"))
    return report


def _pointer(loc) -> str:
    parts = list(loc)
    out = []
    for k, part in enumerate(parts):
        # drop the discriminator tag pydantic inserts after a question index
        if k >= 2 and parts[k - 2] == "questions" and isinstance(parts[k - 1], int) and part in QUESTION_TYPES:
            continue
        out.append(str(part))
    return "/" + "/".join(out)


def _check_ids(pkg: Package, report: CheckReport) -> None:
    seen = set()
    for i, q in enumerate(pkg.questions):
        if q.id in seen:
            report.errors.append(Issue(f"/questions/{i}/id", "duplicate_id", f"question id {q.id!r} is used twice"))
        seen.add(q.id)
        choices = getattr(q, "choices", None)
        if choices and len({c.id for c in choices}) != len(choices):
            report.errors.append(Issue(f"/questions/{i}/choices", "duplicate_id", "choice ids must be unique"))


def _check_slides(pkg: Package, report: CheckReport) -> None:
    pages = None
    for manifest in sorted(paths.build_dir().glob("*/manifest.json")):
        try:
            data = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("sha256") == pkg.source.sha256:
            pages = data.get("pages")
            break
    if pages is None:
        report.warnings.append(
            Issue("/source/sha256", "no_manifest", "no ingest manifest matches source.sha256; slide numbers not checked")
        )
        return
    for i, q in enumerate(pkg.questions):
        bad = [s for s in q.source_slides if s > pages]
        if bad:
            report.errors.append(
                Issue(f"/questions/{i}/source_slides", "slide_out_of_range", f"slides {bad} exceed the {pages} pages")
            )


def _texts(q) -> list[tuple[str, str]]:
    out = [("prompt", q.prompt), ("explanation", q.explanation)]
    for k, c in enumerate(getattr(q, "choices", []) or []):
        out.append((f"choices/{k}/text", c.text))
    return out


def _check_assets(q, base: str, pkg_dir: Path, report: CheckReport) -> None:
    for field_path, text in _texts(q):
        for ref in ASSET_REF.findall(text):
            target = (pkg_dir / ref).resolve()
            if pkg_dir.resolve() not in target.parents or not target.is_file():
                report.errors.append(Issue(f"{base}/{field_path}", "missing_asset", f"{ref} not found next to quiz.json"))


def _check_blanks(q: FillBlank, base: str, report: CheckReport) -> None:
    placeholders = set(PLACEHOLDER.findall(q.prompt))
    for span in MATH_SPAN.findall(q.prompt):
        if PLACEHOLDER.search(span):
            report.errors.append(
                Issue(f"{base}/prompt", "blank_in_math", f"blank inside math {span!r}", hint="put {{key}} outside $...$")
            )
    if placeholders != set(q.blanks):
        report.errors.append(
            Issue(
                f"{base}/blanks",
                "blank_mismatch",
                f"prompt placeholders {sorted(placeholders)} do not match blanks {sorted(q.blanks)}",
            )
        )
    for key, blank in q.blanks.items():
        if blank.match != "regex":
            continue
        for k, pattern in enumerate(blank.accept):
            try:
                re.compile(pattern)
            except re.error as exc:
                report.errors.append(Issue(f"{base}/blanks/{key}/accept/{k}", "bad_regex", str(exc)))


def _check_spec(spec, base: str, report: CheckReport) -> bool:
    checker = get(spec.checker)
    param_errors = checker.validate_params(spec.params)
    for err in param_errors:
        report.errors.append(Issue(f"{base}/params/{err.path}", err.code, err.message))
    if param_errors:
        return False
    params = checker.parse_params(spec.params)
    mutants = checker.mutants(params)
    if not mutants:
        report.warnings.append(Issue(f"{base}/params", "no_mutants", "no wrong answers could be generated to test this check"))
    for mutant in mutants:
        if checker.check_value(mutant, params).passed:
            report.errors.append(
                Issue(
                    f"{base}/params",
                    "vacuous_check",
                    f"a wrong answer ({mutant}) passes this check",
                    hint="tighten the tolerance or make `expected` more specific",
                )
            )
            break
    return True


def _check_exercise(q: Exercise, base: str, report: CheckReport, runner) -> None:
    ok = _check_spec(q.final, f"{base}/final", report)
    env = build_env(q, units=q.steps_mode == "derivation")
    for name, given in q.context.givens.items():
        ok &= _unit_ok(given.unit, f"{base}/context/givens/{name}/unit", report)
    for name, decl in q.context.symbols.items():
        if decl.unit:
            ok &= _unit_ok(decl.unit, f"{base}/context/symbols/{name}/unit", report)
    for k, rel in enumerate(q.context.relations):
        try:
            if len(env.parse(rel).parts) != 2:
                raise ParseError("a relation must be one equation lhs = rhs")
        except ParseError as exc:
            report.errors.append(Issue(f"{base}/context/relations/{k}", "parse_error", str(exc)))
            ok = False
    if q.steps_mode == "chain":
        try:
            env.expr(q.start)
        except ParseError as exc:
            report.errors.append(Issue(f"{base}/start", "parse_error", str(exc)))
            ok = False
    if any(s.agent_graded for s in q.reference_solution) and not q.rubric.strip():
        report.errors.append(Issue(f"{base}/rubric", "rubric_required", "agent-graded reference lines need a rubric"))
    if not ok:
        return
    steps = [{"latex": s.latex, "justification": s.justification} for s in q.reference_solution]
    result = grade_steps(q, steps, seed_key=f"reference:{q.id}", runner=runner)
    for k, (line, ref) in enumerate(zip(result.lines, q.reference_solution, strict=True)):
        status = line["verdict"]["status"]
        if ref.agent_graded or status in ("pass", "pass_numeric"):
            continue
        report.errors.append(
            Issue(
                f"{base}/reference_solution/{k}",
                "reference_step_failed",
                f"reference line is {status}: {line['verdict'].get('reason', '')}".strip(),
                hint="every reference line must be provable by the checkers, or flagged agent_graded",
            )
        )
    if not result.final.passed:
        report.errors.append(
            Issue(f"{base}/final", "reference_final_failed", f"reference answer is {result.final.status}: {result.final.reason}")
        )
    if q.steps_mode == "derivation":
        values = compute_reference_values(q, seed_key=f"reference:{q.id}", runner=runner)
        report.reference_values[q.id] = reference_values_to_json(values)


def _unit_ok(unit: str, path: str, report: CheckReport) -> bool:
    if not unit:
        return True
    try:
        U.unit_expr(unit)
    except ValueError as exc:
        report.errors.append(Issue(path, "unknown_unit", str(exc)))
        return False
    return True


# ------------------------------------------------------------------ import
def import_package(path: Path, *, conn, runner=None) -> ImportResult:
    path = Path(path)
    report = check_package(path, runner=runner)
    if not report.ok:
        raise ImportRejected(report)
    pkg = report.package
    raw = json.loads(path.read_text())
    rows, counts = [], {}
    for q in pkg.questions:
        data = q.model_dump(mode="json")
        if q.id in report.reference_values:
            data["reference_values"] = report.reference_values[q.id]
        rows.append({"id": q.id, "type": q.type, "points": q.points, "data": data})
        counts[q.type] = counts.get(q.type, 0) + 1
    assets = {}
    asset_dir = path.parent / "assets"
    if asset_dir.is_dir():
        for f in sorted(asset_dir.rglob("*")):
            if f.is_file():
                mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                assets[f.relative_to(path.parent).as_posix()] = (mime, f.read_bytes())
    with conn:
        revision = db.insert_revision(conn, raw, rows, assets)
    library_path = paths.library_dir() / pkg.id / f"r{revision}"
    warnings = list(report.warnings)
    try:
        if library_path.exists():
            shutil.rmtree(library_path)
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.mkdir()
        shutil.copy2(path, library_path / "quiz.json")
        if asset_dir.is_dir():
            shutil.copytree(asset_dir, library_path / "assets")
    except OSError as exc:
        warnings.append(Issue("", "library_copy_failed", f"imported, but copying to {library_path} failed: {exc}"))
        library_path = None
    return ImportResult(pkg.id, revision, counts, library_path, warnings)
