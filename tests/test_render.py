from quizz.web.render import fmt_score, plain


def test_plain_snippet_keeps_blanks_visible():
    assert plain("Flux equals enclosed {{b1}} divided by {{b_2}}.") == "Flux equals enclosed ___ divided by ___."


def test_plain_snippet_strips_markdown_and_images_and_truncates():
    assert plain("**Bold** and ![fig](assets/a.png) `code`") == "Bold and  code"
    assert plain("x" * 200, limit=10) == "x" * 9 + "…"


def test_fmt_score():
    assert [fmt_score(v) for v in (1, 1.0, 0.5, None, 2.25)] == ["1", "1", "0.5", "0", "2.25"]
