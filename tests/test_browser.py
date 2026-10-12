"""Browser smoke: typed MathLive steps reach the server as the JSON the grader expects."""

import json
import socket
import threading
import time

import pytest

from factories import package
from quizz import db, importer

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


@pytest.fixture
def server(tmp_path, monkeypatch):
    import uvicorn

    from quizz.web.app import create_app

    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path / "home"))
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "quiz.json").write_text(json.dumps(package()))
    conn = db.connect()
    importer.import_package(pkg / "quiz.json", conn=conn)
    conn.close()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)


@pytest.fixture
def page():
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"chromium unavailable: {exc}")
        yield browser.new_page()
        browser.close()


def test_typed_steps_are_submitted_and_graded(server, page):
    page.goto(f"{server}/quiz/test-quiz")
    page.click("text=Start")
    page.wait_for_url("**/q/1")
    page.goto(page.url.replace("/q/1", "/q/5"))
    page.wait_for_function("customElements.get('math-field') !== undefined")

    first = page.locator("#composer math-field").first
    first.click()
    page.keyboard.type("x+1")
    page.keyboard.press("Enter")  # composer JS: new step
    assert page.locator(".step").count() == 2
    page.wait_for_function("document.activeElement === document.querySelectorAll('#composer math-field')[1]")
    page.keyboard.type("2x")
    page.keyboard.press("Alt+Enter")  # reveal the reason line
    page.keyboard.type("doubling")
    page.keyboard.press("Meta+Enter")

    page.wait_for_selector('[data-state="verdict"]')
    assert page.locator(".line[data-status]").count() == 2
    assert page.locator(".why-text").inner_text().strip() == "↳ doubling"

    conn = db.connect()
    attempt_id = int(page.url.split("/attempts/")[1].split("/")[0])
    response = json.loads(db.get_answer(conn, attempt_id, "q-ibp")["response_json"])
    conn.close()
    assert response == {"steps": [{"latex": "x+1", "justification": ""}, {"latex": "2x", "justification": "doubling"}]}


def test_empty_answer_is_not_submitted(server, page):
    page.goto(f"{server}/quiz/test-quiz")
    page.click("text=Start")
    page.wait_for_selector("#composer")
    page.click("button.send")
    page.wait_for_selector("#composer-error .error-box")
    assert page.locator('[data-state="verdict"]').count() == 0
