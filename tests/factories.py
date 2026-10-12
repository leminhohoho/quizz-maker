"""Hand-written package fixtures shared by schema, importer and grading tests."""

import copy

MCQ = {
    "id": "q-mcq",
    "type": "mcq",
    "prompt": "Which test is most direct for $\\sum n!/n^n$?",
    "choices": [{"id": "a", "text": "Integral test"}, {"id": "b", "text": "Ratio test"}],
    "answer": "b",
    "explanation": "Factorials suggest the ratio test.",
    "source_slides": [3],
}
MULTI = {
    "id": "q-multi",
    "type": "multi_select",
    "prompt": "Select the state functions.",
    "choices": [{"id": "h", "text": "Enthalpy"}, {"id": "q", "text": "Heat"}, {"id": "u", "text": "Internal energy"}],
    "answer": ["h", "u"],
    "scoring": "partial",
    "points": 2,
}
FILL = {
    "id": "q-fill",
    "type": "fill_blank",
    "prompt": "Flux equals enclosed {{b1}} divided by {{b2}}.",
    "blanks": {"b1": {"accept": ["charge"]}, "b2": {"accept": ["epsilon_0", "ε0", "ε₀"], "match": "exact"}},
}
MATH = {
    "id": "q-math",
    "type": "math_answer",
    "prompt": "Energy stored in a 4.0 µF capacitor at 12 V?",
    "check": {"checker": "numeric_units", "params": {"expected": 2.88e-4, "unit": "J", "rel_tol": 0.01, "sig_figs": 3}},
    "points": 1,
}
EXERCISE_CHAIN = {
    "id": "q-ibp",
    "type": "exercise",
    "prompt": "Evaluate $\\int x e^x\\,dx$. Show each step.",
    "steps_mode": "chain",
    "start": "\\int xe^{x}\\,dx",
    "final": {"checker": "antiderivative", "params": {"integrand": "xe^{x}", "var": "x"}},
    "reference_solution": [
        {"latex": "\\int xe^{x}\\,dx"},
        {"latex": "xe^{x}-\\int e^{x}\\,dx", "justification": "parts: u = x, dv = e^x dx"},
        {"latex": "xe^{x}-e^{x}+C"},
    ],
    "rubric": "Integration by parts with u = x.",
    "points": 2,
}
EXERCISE_DERIVATION = {
    "id": "q-heat",
    "type": "exercise",
    "prompt": "How much heat raises 50.0 g of water by 20.0 K? ($c = 4.18$ J/(g K))",
    "steps_mode": "derivation",
    "context": {
        "symbols": {"q": {"unit": "J", "description": "heat absorbed"}},
        "givens": {"m": {"value": 50.0, "unit": "g"}, "c": {"value": 4.18, "unit": "J/(g K)"}, "\\Delta T": {"value": 20.0, "unit": "K"}},
        "relations": ["q=mc\\Delta T"],
    },
    "final": {"checker": "numeric_units", "params": {"expected": 4180, "unit": "J", "rel_tol": 0.01}},
    "reference_solution": [
        {"latex": "q=mc\\Delta T"},
        {"latex": "q=50.0\\,\\mathrm{g}\\cdot4.18\\,\\mathrm{J/(g\\,K)}\\cdot20.0\\,\\mathrm{K}"},
        {"latex": "q=4180\\,\\mathrm{J}"},
    ],
    "rubric": "q = m c ΔT.",
    "points": 2,
}


def package(*questions, **overrides) -> dict:
    pkg = {
        "format_version": 1,
        "id": "test-quiz",
        "title": "Test quiz",
        "course": "Testing 101",
        "source": {"filename": "lecture.pdf", "sha256": "0" * 64},
        "questions": [copy.deepcopy(q) for q in (questions or (MCQ, MULTI, FILL, MATH, EXERCISE_CHAIN, EXERCISE_DERIVATION))],
    }
    pkg.update(overrides)
    return pkg
