import json

import pytest

from factories import package
from quizz import db, importer


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def conn(home):
    c = db.connect()
    yield c
    c.close()


def write_pkg(tmp_path, pkg, assets=None):
    d = tmp_path / "pkg"
    d.mkdir(exist_ok=True)
    (d / "quiz.json").write_text(json.dumps(pkg))
    for name, data in (assets or {}).items():
        (d / "assets").mkdir(exist_ok=True)
        (d / "assets" / name).write_bytes(data)
    return d / "quiz.json"


def error_paths(report):
    return {e.path: e.code for e in report.errors}


def test_valid_package_passes_all_gates(tmp_path):
    report = importer.check_package(write_pkg(tmp_path, package()))
    assert report.errors == []
    assert report.ok


def test_import_inserts_and_copies_to_library(tmp_path, conn, home):
    result = importer.import_package(write_pkg(tmp_path, package()), conn=conn)
    assert (result.quiz_id, result.revision) == ("test-quiz", 1)
    assert (home / "library" / "test-quiz" / "r1" / "quiz.json").exists()
    rows = {r["question_id"]: json.loads(r["data_json"]) for r in db.questions(conn, "test-quiz", 1)}
    assert rows["q-heat"]["reference_values"]["q"]["dims"] == {"kg": 1, "m": 2, "s": -2}
    assert float(rows["q-heat"]["reference_values"]["q"]["magnitude"]) == pytest.approx(4180)
    assert "reference_values" not in rows["q-ibp"]


def test_reimport_creates_revision_and_keeps_attempts(tmp_path, conn):
    path = write_pkg(tmp_path, package())
    importer.import_package(path, conn=conn)
    attempt = db.create_attempt(conn, "test-quiz")
    assert importer.import_package(path, conn=conn).revision == 2
    assert db.get_attempt(conn, attempt)["revision"] == 1


def test_assets_are_stored(tmp_path, conn):
    pkg = package()
    pkg["questions"][0]["prompt"] += " ![circuit](assets/fig1.png)"
    importer.import_package(write_pkg(tmp_path, pkg, {"fig1.png": b"\x89PNGdata"}), conn=conn)
    assert db.get_asset(conn, "test-quiz", 1, "assets/fig1.png") == ("image/png", b"\x89PNGdata")


def mutate(fn):
    pkg = package()
    fn(pkg)
    return pkg


@pytest.mark.parametrize(
    "pkg, path, code",
    [
        (mutate(lambda p: p["questions"][3]["check"]["params"].update(unit="furlong")), "/questions/3/check/params/unit", "unknown_unit"),
        (mutate(lambda p: p["questions"][3]["check"]["params"].update(rel_tol=0.5)), "/questions/3/check/params", "vacuous_check"),
        (mutate(lambda p: p["questions"][0].update(answer="z")), "/questions/0/answer", "unknown_choice"),
        (mutate(lambda p: p["questions"][1].update(answer=["h", "z"])), "/questions/1/answer", "unknown_choice"),
        (mutate(lambda p: p["questions"][2].update(prompt="Only {{b1}} and {{b3}}.")), "/questions/2/blanks", "blank_mismatch"),
        (mutate(lambda p: p["questions"][2].update(prompt="Flux {{b1}} over $\\varepsilon_{ {{b2}} }$.")), "/questions/2/prompt", "blank_in_math"),
        (mutate(lambda p: p["questions"][2]["blanks"]["b1"].update(accept=["(unclosed"], match="regex")), "/questions/2/blanks/b1/accept/0", "bad_regex"),
        (mutate(lambda p: p["questions"][4]["reference_solution"][2].update(latex="xe^{x}+e^{x}+C")), "/questions/4/reference_solution/2", "reference_step_failed"),
        (mutate(lambda p: p["questions"][4]["final"]["params"].update(integrand="x")), "/questions/4/final", "reference_final_failed"),
        (mutate(lambda p: p["questions"][5]["context"]["givens"]["m"].update(unit="stone")), "/questions/5/context/givens/m/unit", "unknown_unit"),
        (mutate(lambda p: p["questions"][4].update(start="\\int x e^{x}")), "/questions/4/start", "parse_error"),
        (mutate(lambda p: p["questions"][0].update(choices=[{"id": "a", "text": "x"}])), "/questions/0/choices", "too_short"),
        (mutate(lambda p: p["questions"][1].update(id="q-mcq")), "/questions/1/id", "duplicate_id"),
        (mutate(lambda p: p["questions"][0].update(prompt="See ![](assets/missing.png)")), "/questions/0/prompt", "missing_asset"),
    ],
)
def test_broken_packages_fail_at_the_exact_path(tmp_path, pkg, path, code):
    report = importer.check_package(write_pkg(tmp_path, pkg))
    assert not report.ok
    assert error_paths(report).get(path) == code, error_paths(report)


def test_invalid_json_is_reported(tmp_path):
    p = tmp_path / "quiz.json"
    p.write_text("{nope")
    report = importer.check_package(p)
    assert [e.code for e in report.errors] == ["invalid_json"]


def test_agent_graded_reference_line_needs_a_rubric(tmp_path):
    pkg = package()
    ex = pkg["questions"][4]
    ex["reference_solution"].insert(2, {"latex": "\\text{by parts}", "agent_graded": True})
    ex["rubric"] = ""
    assert error_paths(importer.check_package(write_pkg(tmp_path, pkg))).get("/questions/4/rubric") == "rubric_required"
    ex["rubric"] = "Integration by parts."
    assert importer.check_package(write_pkg(tmp_path, pkg)).ok


def test_source_slides_checked_against_matching_manifest(tmp_path, home):
    manifest = home / "build" / "lecture" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"sha256": "0" * 64, "pages": 2, "filename": "lecture.pdf"}))
    report = importer.check_package(write_pkg(tmp_path, package()))
    assert error_paths(report).get("/questions/0/source_slides") == "slide_out_of_range"


def test_missing_manifest_is_only_a_warning(tmp_path):
    report = importer.check_package(write_pkg(tmp_path, package()))
    assert report.ok
    assert any(w.code == "no_manifest" for w in report.warnings)


def test_question_filter_only_checks_that_question(tmp_path):
    pkg = mutate(lambda p: p["questions"][0].update(answer="z"))
    assert importer.check_package(write_pkg(tmp_path, pkg), question_id="q-math").ok


def test_failed_check_imports_nothing(tmp_path, conn):
    pkg = mutate(lambda p: p["questions"][0].update(answer="z"))
    with pytest.raises(importer.ImportRejected) as err:
        importer.import_package(write_pkg(tmp_path, pkg), conn=conn)
    assert err.value.report.errors
    assert conn.execute("SELECT count(*) FROM quiz").fetchone()[0] == 0


def test_crash_mid_insert_rolls_back(tmp_path, conn, monkeypatch):
    real = db.insert_revision

    def explode(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(db, "insert_revision", explode)
    with pytest.raises(RuntimeError):
        importer.import_package(write_pkg(tmp_path, package()), conn=conn)
    assert conn.execute("SELECT count(*) FROM quiz").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM question").fetchone()[0] == 0
