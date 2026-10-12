# quizz-maker

Turn lecture slides into browser quizzes. Your coding agent (Claude Code, Codex, pi, …) is the
*compiler*: it reads the slides and writes a quiz package; the `quizz` CLI verifies every question with
deterministic checkers before anything reaches the app. The web app (FastAPI + HTMX + SQLite) serves one
question at a time and grades answers — including step-by-step math solutions — with the same checkers.

Supported question types: MCQ, multi-select, fill-in-the-blank, math/numeric answers (with units and
significant figures), chemical equation balancing, Laplace/Fourier/z transforms, and step-by-step
exercises where every line you write is checked.

## Setup

```sh
uv sync
uv tool install -e .        # puts `quizz` on PATH for every agent
quizz install-skill         # links skills/quizz-compile into ~/.claude/skills and ~/.agents/skills (Codex, pi)
```

PPTX slides need LibreOffice (`brew install --cask libreoffice`); PDFs work out of the box.

Data lives in `$QUIZZ_HOME` (default: this checkout): `build/` (ingested slides), `library/` (imported
packages), `quizz.db`. All three are gitignored — the repository stays lecture-agnostic.

## Compile a lecture

In your agent, from any directory:

> compile ~/lectures/chem2/lecture_1.pdf into a quiz

The `quizz-compile` skill drives the CLI:

```sh
quizz ingest lecture_1.pdf            # PDF/PPTX -> per-page text + images under build/
quizz checkers                        # what each checker accepts
quizz schema --type exercise          # exact package format
quizz check build/<deck>/package/quiz.json    # schema + reference solutions + mutation tests
quizz import build/<deck>/package/quiz.json   # one transaction; re-import = new revision
```

Every command prints JSON; exit `0` ok, `1` the package has errors (each with a JSON-pointer `path`),
`2` environment/usage problem. `quizz list` and `quizz rm <id>` manage imported quizzes.

## Take quizzes

```sh
quizz serve            # http://127.0.0.1:8000
```

Keyboard: `1`–`6` pick choices, `⌘⏎` checks, `⏎` goes to the next question. In exercises `⏎` adds a
step and `⌥⏎` adds a reason line. Each line of a step-by-step answer gets a badge saying who judged it:
`checker` (proven), `numeric` (matched at 30 random points), `agent`, or `unverified`.

### Live agent grading

Lines no checker can decide (prose reasoning, unknown symbols) can be graded by your agent. Set the
command in **Settings**:

| Agent | Grader command |
|---|---|
| Claude Code | `claude -p` |
| Codex | `codex exec` |
| pi | `pi -p "$(cat {prompt_file})"` |

The prompt goes to stdin, or to a temp file when the command contains `{prompt_file}`. Agent verdicts
only ever fill in undecided lines; they never override a checker. Leave the command empty to mark such
lines unverified instead.

## Development

```sh
uv run pytest                          # full suite
uv run playwright install chromium     # once, for tests/test_browser.py
```

Design: `docs/superpowers/specs/2026-10-12-quizz-maker-design.md`.
