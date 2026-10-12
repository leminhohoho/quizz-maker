---
name: quizz-compile
description: Compile lecture slides (PDF or PPTX) into a quizz quiz package and import it into the local quizz app. Use when the user asks to turn slides, a lecture, a deck or course notes into a quiz, practice questions or exercises.
---

# Compile lecture slides into a quiz

You are a compiler: slides in, a verified quiz package out. The `quizz` CLI is the only gate into the
app. It validates the package and proves every exercise with deterministic checkers. Never write to the
database directly and never hand-edit `$QUIZZ_HOME`. Every command prints JSON; exit code `0` = ok,
`1` = the package has errors (fix them), `2` = usage/environment problem (report it to the user).

## Workflow

1. **Ingest.** `quizz ingest <slides.pdf|slides.pptx>` → prints `{pdf, pages, sha256, dir}`.
   Read every `dir/pages/NNN.txt`; look at `dir/pages/NNN.png` for slides with equations, diagrams or
   tables (text extraction loses math). If ingest exits 2 with `missing_dependency`, tell the user the
   hint (e.g. install LibreOffice or export the deck to PDF) and stop.
2. **Outline.** List the concepts, definitions, formulas and worked examples per slide range. Note the
   1-based page numbers; every question carries `source_slides`.
3. **Choose a mix.** Default per lecture unless the user says otherwise:
   - 8–15 `mcq` / `multi_select` / `fill_blank` for concepts and definitions,
   - 3–6 `math_answer` for quick computations,
   - 2–4 `exercise` (step-by-step) for the core techniques.
   Skip types the material doesn't support (a purely conceptual lecture gets no exercises).
4. **Write the package** to `<dir>/package/quiz.json` (figures you crop go in `<dir>/package/assets/`).
   - `source`: `{"filename": <original file name>, "sha256": <sha256 printed by ingest>}`.
   - `id`: stable lowercase slug, e.g. `chem2-l01-thermochemistry`. Re-compiling the same lecture must
     reuse the same id (the app keeps old attempts on the old revision).
   - Exercises are **new problems modeled on the slides' worked examples** — change the numbers or the
     function — never copies of a worked example.
   - Run `quizz schema` (or `quizz schema --type exercise`) for the exact format and `quizz checkers`
     for every checker's params and an example. Read `references/format.md` and
     `references/exercises.md` before writing exercises. Copy patterns from `examples/`.
5. **Check and fix.** `quizz check <dir>/package/quiz.json`. Every error has a JSON-pointer `path`, a
   `code` and often a `hint`. Fix and re-run until it exits 0. Typical fixes:
   - `reference_step_failed`: your reference line doesn't follow from the previous one (or isn't true
     under the givens) — fix the math, split the step, or switch `steps_mode` (see exercises guide).
   - `vacuous_check`: a wrong answer passes your check — tighten `rel_tol`, make `expected` specific.
   - `parse_error`: write the LaTeX in the MathLive dialect (see exercises guide).
   - `slide_out_of_range`: page numbers are 1-based pages of the ingested PDF.
   Only mark a reference line `"agent_graded": true` when it is genuinely prose (a convergence argument,
   a qualitative justification) and give the exercise a `rubric`.
6. **Import.** `quizz import <dir>/package/quiz.json`. Report to the user: quiz id, revision, question
   counts by type, and that they can open it with `quizz serve` (http://127.0.0.1:8000).

## Quality bar

- One idea per question; prompts self-contained (define symbols, give units and constants).
- Distractors in MCQs are real misconceptions from the lecture, not filler.
- `explanation` on every question: one or two sentences with the key reasoning.
- Numeric answers: say how many significant figures you expect when you set `sig_figs`, and keep
  `rel_tol` ≤ 0.05.
- Math in prompts uses `$...$`; math in answers, `start`, `expected` and reference lines is LaTeX
  **without** dollar signs.
- Never invent content that isn't in the slides; if the slides are thin on a topic, ask fewer questions.
