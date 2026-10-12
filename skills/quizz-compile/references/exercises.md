# Writing exercises that the checkers can prove

A student submits one line per step. Each line is judged deterministically; only lines no checker can
decide go to an AI grader. Your `reference_solution` is run through the same pipeline at `quizz check`,
so every reference line must pass on its own.

## Pick `steps_mode`

| Mode | Each line must… | Subjects |
|---|---|---|
| `chain` | be **equal** to the previous line (line 1 equal to `start`) | calculus, algebra, transforms, series manipulation |
| `derivation` | be a **true statement** given `givens`, earlier definitions and `relations` | physics, chemistry, any "plug the numbers in" problem |

### `chain` rules

- Equality is checked symbolically, then numerically at 30 random points (assumptions respected).
- Indefinite integrals and constants `C`, `C_1` compare **up to a constant** (derivatives are compared).
- A line `u=x^2` with a new symbol is a **substitution**: later lines are back-substituted. Integrals
  over `u` must be evaluable (`\int e^{u}\,du` is fine).
- Definite integrals with symbolic parameters need assumptions: declare `"s": {"assumptions": ["positive"]}`
  in `context.symbols` so the integral converges for the checker.
- A line may hold a chain `a=b=c`; every `=` is checked.

### `derivation` rules

- `q=mc\Delta T` with a fresh symbol `q` *defines* `q`; its value is compared with the value the
  reference solution gives `q`, which pinpoints the first wrong line.
- Numeric sides are compared in SI base units within 1 %, with dimensions checked. Put units on every
  number: `50.0\,\mathrm{g}`, `4.18\,\mathrm{J/(g\,K)}`, `12\,\mathrm{V}`.
- Purely symbolic lines (`U=\frac{Q^2}{2C}`) are checked against `relations`; declare every symbol
  used in the relations in `context.symbols`.
- `\approx` is allowed and uses the same tolerance.
- The last line's right-hand side goes to `final` (e.g. `numeric_units` with `sig_figs`).

## MathLive LaTeX dialect

Write what the in-browser math editor produces:

| Want | Write |
|---|---|
| fraction | `\frac{a}{b}` |
| multiplication | juxtaposition `2x`, or `\cdot`, `\times` |
| powers / subscripts | `x^{2}`, `v_{0}` |
| e^x | `e^{x}` (a bare `e` is Euler's number unless declared as a symbol) |
| functions | `\sin x`, `\ln\left(x\right)`, `\sin^{-1}x`; `\log` is base 10, `\ln` is natural |
| integrals | `\int f\,dx`, `\int_{0}^{1} f\,dx` — the differential is required |
| sums / limits | `\sum_{n=1}^{\infty}a_n`, `\lim_{x\to0}f` |
| derivative | `\frac{d}{dx}\left(x^2\right)` (no `\frac{dy}{dx}`) |
| piecewise | `\begin{cases}0 & t<0\\ 1 & t\ge0\end{cases}` |
| units | `9.81\,\mathrm{m/s^2}`, `\mathrm{kJ\,mol^{-1}}`, `\mathrm{\mu F}`, `\mathrm{\Omega}` |
| decimal × power | `2.88\times10^{-4}` |

Supported units: m g s A K mol cd N J W Pa C V Ω F H Wb T Hz L M(molar) atm bar torr mmHg eV cal min h,
with prefixes T G M k c m µ(u) n p f. Temperatures must be in K (no °C).

Chemical equations (plain text, `reaction_balance`): `C3H8 + 5O2 -> 3CO2 + 4H2O`, ions `Fe^3+`, `SO4^2-`,
`Na+`, states `(aq)`, arrows `->`, `→`, `=`, `<=>`.

## When a step can't be proven

Prefer rewriting the step so the checker can prove it (split it, add the intermediate expression, use
`derivation` mode). Use `"agent_graded": true` only for genuinely qualitative lines, and add a `rubric`.
