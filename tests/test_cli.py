import json
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from factories import package
from quizz.cli import app

REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def invoke(*args):
    result = runner.invoke(app, list(args))
    return result.exit_code, (json.loads(result.stdout) if result.stdout.strip() else None)


def pkg_file(tmp_path, pkg):
    p = tmp_path / "quiz.json"
    p.write_text(json.dumps(pkg))
    return str(p)


def test_check_ok(tmp_path):
    code, out = invoke("check", pkg_file(tmp_path, package()))
    assert code == 0 and out["ok"] is True


def test_check_reports_errors_with_exit_1(tmp_path):
    pkg = package()
    pkg["questions"][0]["answer"] = "z"
    code, out = invoke("check", pkg_file(tmp_path, pkg))
    assert code == 1
    assert out["errors"][0]["path"] == "/questions/0/answer"


def test_import_then_list_then_rm(tmp_path):
    code, out = invoke("import", pkg_file(tmp_path, package()))
    assert code == 0
    assert out["quiz_id"] == "test-quiz" and out["revision"] == 1
    assert out["questions"] == {"mcq": 1, "multi_select": 1, "fill_blank": 1, "math_answer": 1, "exercise": 2}
    code, out = invoke("list")
    assert [q["id"] for q in out["quizzes"]] == ["test-quiz"]
    assert invoke("rm", "test-quiz", "--yes")[0] == 0
    assert invoke("list")[1]["quizzes"] == []
    code, out = invoke("rm", "test-quiz", "--yes")
    assert code == 1 and out["errors"][0]["code"] == "not_found"


def test_import_rejects_invalid_package(tmp_path):
    pkg = package()
    pkg["questions"][3]["check"]["params"]["unit"] = "furlong"
    code, out = invoke("import", pkg_file(tmp_path, pkg))
    assert code == 1 and out["ok"] is False


def test_ingest_pdf(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(tmp_path / "deck.pdf")
    code, out = invoke("ingest", str(tmp_path / "deck.pdf"))
    assert code == 0 and out["pages"] == 1


def test_ingest_missing_dependency_exits_2(tmp_path, monkeypatch):
    from quizz import ingest

    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ingest, "SOFFICE_CANDIDATES", [])
    (tmp_path / "deck.pptx").write_bytes(b"PK")
    code, out = invoke("ingest", str(tmp_path / "deck.pptx"))
    assert code == 2 and out["errors"][0]["code"] == "missing_dependency" and out["errors"][0]["hint"]


def test_ingest_missing_file_exits_2(tmp_path):
    code, out = invoke("ingest", str(tmp_path / "nope.pdf"))
    assert code == 2 and out["errors"][0]["code"] == "not_found"


def test_schema_and_checkers():
    code, out = invoke("schema", "--type", "exercise")
    assert code == 0 and "steps_mode" in out["properties"]
    assert invoke("schema", "--type", "essay")[0] == 2
    code, out = invoke("checkers")
    assert [c["name"] for c in out["checkers"]] == ["expr_equiv", "antiderivative", "numeric_units", "reaction_balance", "transform"]


def test_install_skill_symlinks_into_agent_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    code, out = invoke("install-skill")
    assert code == 0
    target = REPO / "skills" / "quizz-compile"
    for d in (".claude/skills", ".agents/skills"):
        link = tmp_path / d / "quizz-compile"
        assert link.is_symlink() and link.resolve() == target.resolve()
    assert invoke("install-skill")[0] == 0  # idempotent


def test_install_skill_refuses_to_replace_a_real_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude" / "skills" / "quizz-compile").mkdir(parents=True)
    code, out = invoke("install-skill")
    assert code == 2 and out["errors"][0]["code"] == "exists"


def test_human_flag_prints_text(tmp_path):
    result = runner.invoke(app, ["check", pkg_file(tmp_path, package()), "--human"])
    assert result.exit_code == 0 and result.stdout.startswith("ok")
