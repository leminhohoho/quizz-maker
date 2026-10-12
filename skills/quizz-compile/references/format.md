# Quiz package format v1 — field guide

`quizz schema` prints the authoritative JSON Schema; this page explains intent. Unknown fields are errors.

## Envelope

| Field | Notes |
|---|---|
| `format_version` | always `1` |
| `id` | lowercase slug `[a-z0-9-]+`, stable across re-compiles |
| `title`, `course` | shown in the app; `course` groups quizzes in the sidebar |
| `source` | `{filename, sha256}` — use the sha256 printed by `quizz ingest` |
| `questions` | at least one |

## Every question

| Field | Notes |
|---|---|
| `id` | slug, unique within the quiz |
| `type` | `mcq`, `multi_select`, `fill_blank`, `math_answer`, `exercise` |
| `prompt` | Markdown; inline math `$...$`, display `$$...$$`; images `![alt](assets/fig.png)` |
| `source_slides` | 1-based page numbers of the ingested PDF |
| `explanation` | Markdown shown after answering |
| `points` | integer ≥ 1 (default 1); exercises usually 2 |

## Types

**`mcq`** — `choices: [{id, text}]` (2–6, ids are slugs), `answer: <choice id>`.

**`multi_select`** — `choices` (2–8), `answer: [ids]`, `scoring: all_or_nothing | partial`.
`partial` = `max(0, (right − wrong) / |answer|) × points`.

**`fill_blank`** — put `{{key}}` placeholders in `prompt`; `blanks: {key: {accept: [...], match}}`.
`match`: `normalized` (default: case-insensitive, whitespace collapsed, trailing punctuation ignored),
`exact`, or `regex` (full match). List common spellings in `accept`. Each blank is worth an equal share.

**`math_answer`** — `check: {checker, params}`. The checker decides the input widget (math editor or plain
text). Checkers (run `quizz checkers` for params):

| Checker | Use for | Answer looks like |
|---|---|---|
| `expr_equiv` | an expression equal to `expected` | `\frac{x^2}{2}` |
| `antiderivative` | indefinite integrals (`+C` optional) | `x\sin x+\cos x+C` |
| `numeric_units` | numbers with units, tolerance, sig figs | `2.9\times10^{-4}\,\mathrm{J}` |
| `reaction_balance` | balanced equations (plain text) | `C3H8 + 5O2 -> 3CO2 + 4H2O` |
| `transform` | Laplace / Fourier / z transforms, optional ROC | `\frac{1}{s+2}, \mathrm{Re}(s)>-2` |

**`exercise`** — step-by-step. See `exercises.md`.

| Field | Notes |
|---|---|
| `steps_mode` | `chain` or `derivation` |
| `start` | `chain` only: the expression line 1 must equal |
| `context.symbols` | `{name: {assumptions, unit, description}}` — shown to the student |
| `context.givens` | `{name: {value, unit}}` — known quantities (derivation) |
| `context.relations` | governing equations, e.g. `F=ma` (derivation, symbolic lines) |
| `context.functions` | `{"u": "heaviside", "\\delta": "dirac"}` — names written `u(t)` that are function calls |
| `final` | CheckSpec applied to the last line's value |
| `reference_solution` | `[{latex, justification?, agent_graded?}]` — every line must be provable |
| `rubric` | text for the agent grader when a student's line can't be decided |

Names are LaTeX: `q`, `v_0`, `\Delta H`. Multi-token names such as `\Delta H` are treated as one symbol.
