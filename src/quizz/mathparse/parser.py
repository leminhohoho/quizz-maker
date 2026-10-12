"""Recursive-descent parser: tokens -> SymPy. Never evaluates strings."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import sympy as sp

from quizz.mathparse.errors import ParseError
from quizz.mathparse.tokens import Token, tokenize

__all__ = ["Line", "ParseError", "parse_expr", "parse_line"]

GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "rho", "varrho", "sigma", "varsigma", "tau",
    "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
}  # fmt: skip

FUNCS: dict[str, Callable] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
    "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "ln": sp.log, "exp": sp.exp,
    "log": lambda z: sp.log(z, 10),
}  # fmt: skip
INVERSE = {"sin": sp.asin, "cos": sp.acos, "tan": sp.atan, "sinh": sp.asinh, "cosh": sp.acosh, "tanh": sp.atanh}

CHAIN_RELATIONS = {"=": "=", "approx": "~"}
COMPARISONS = {"<": sp.StrictLessThan, ">": sp.StrictGreaterThan, "lt": sp.StrictLessThan,
               "gt": sp.StrictGreaterThan, "le": sp.LessThan, "leq": sp.LessThan,
               "ge": sp.GreaterThan, "geq": sp.GreaterThan, "ne": sp.Unequality}  # fmt: skip
OPEN = {"(": ")", "[": "]", "lbrack": "rbrack", "{": "}", "|": "|", "vert": "vert", "lvert": "rvert"}
EOF = Token("EOF", "", -1)


@dataclass
class Line:
    """A parsed solution line: one expression, or an equation chain `parts[0] = parts[1] = ...`."""

    parts: list[sp.Expr]
    relations: list[str] = field(default_factory=list)  # "=" or "~" (approx), len(parts) - 1
    text: str = ""

    @property
    def is_chain(self) -> bool:
        return len(self.parts) > 1


def parse_line(
    latex: str,
    *,
    symbols: Mapping[str, sp.Symbol] | None = None,
    functions: Mapping[str, Callable] | None = None,
    atoms: Iterable[str] = (),
    units: Callable[[str], sp.Expr] | None = None,
) -> Line:
    p = _Parser(latex, symbols or {}, functions or {}, tuple(atoms), units)
    return p.parse_line()


def parse_expr(latex: str, **kwargs) -> sp.Expr:
    line = parse_line(latex, **kwargs)
    if line.is_chain:
        raise ParseError("expected a single expression, got an equation", 0)
    return line.parts[0]


class _Parser:
    def __init__(self, src, symbols, functions, atoms, units):
        self.src = src
        self.toks = tokenize(src, atoms)
        self.i = 0
        self.symbols = symbols
        self.functions = functions
        self.units = units
        self.integral_depth = 0
        self.abs_depth = 0

    # ----- token helpers -------------------------------------------------
    def peek(self, k: int = 0) -> Token:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else EOF

    def next(self) -> Token:
        tok = self.peek()
        if tok is EOF:
            raise ParseError("unexpected end of input", len(self.src))
        self.i += 1
        return tok

    def at(self, kind: str, value: str | None = None, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == kind and (value is None or tok.value == value)

    def expect(self, kind: str, value: str) -> Token:
        if not self.at(kind, value):
            tok = self.peek()
            where = "end of input" if tok is EOF else repr(tok.value)
            raise ParseError(f"expected {value!r} but found {where}", tok.pos)
        return self.next()

    def fail(self, message: str, tok: Token | None = None):
        tok = tok or self.peek()
        raise ParseError(message, tok.pos if tok is not EOF else len(self.src))

    # ----- entry points ----------------------------------------------------
    def parse_line(self) -> Line:
        if not self.toks:
            raise ParseError("empty input", 0)
        parts = [self.expr()]
        relations = []
        while True:
            rel = self._chain_relation()
            if rel is None:
                break
            relations.append(rel)
            parts.append(self.expr())
        if self.peek() is not EOF:
            tok = self.peek()
            self.fail(f"unexpected {tok.value!r}", tok)
        return Line(parts=parts, relations=relations, text=self.src)

    def _chain_relation(self) -> str | None:
        tok = self.peek()
        if tok.kind == "SYM" and tok.value == "=":
            self.next()
            return "="
        if tok.kind == "CMD" and tok.value in CHAIN_RELATIONS:
            self.next()
            return CHAIN_RELATIONS[tok.value]
        return None

    # ----- grammar ---------------------------------------------------------
    def expr(self) -> sp.Expr:
        left = self.term()
        while self.at("SYM", "+") or self.at("SYM", "-"):
            op = self.next().value
            right = self.term()
            left = left + right if op == "+" else left - right
        return left

    def term(self) -> sp.Expr:
        left = self.unary()
        while True:
            tok = self.peek()
            if tok.kind == "CMD" and tok.value in ("cdot", "times"):
                self.next()
                left = left * self.unary()
            elif (tok.kind == "CMD" and tok.value == "div") or (tok.kind == "SYM" and tok.value == "/"):
                self.next()
                left = left / self.unary()
            elif tok.kind == "SYM" and tok.value == "*":
                self.next()
                left = left * self.unary()
            elif self.starts_factor():
                left = left * self.postfix()
            else:
                return left

    def unary(self) -> sp.Expr:
        if self.at("SYM", "-"):
            self.next()
            return -self.unary()
        if self.at("SYM", "+"):
            self.next()
            return self.unary()
        return self.postfix()

    def postfix(self) -> sp.Expr:
        base = self.primary()
        while True:
            if self.at("SYM", "^"):
                self.next()
                base = base ** self.script()
            elif self.at("SYM", "!"):
                self.next()
                base = sp.factorial(base)
            else:
                return base

    def starts_factor(self) -> bool:
        if self.is_differential():
            return False
        tok = self.peek()
        if tok.kind in ("NUM", "LETTER", "ATOM", "TEXT", "BEGIN"):
            return True
        if tok.kind == "SYM":
            if tok.value == "|":
                return self.abs_depth == 0
            return tok.value in "(["
        if tok.kind == "CMD":
            return tok.value not in ("cdot", "times", "div", "right", "to", "rightarrow", "rbrack",
                                     "rvert", "approx", *COMPARISONS)  # fmt: skip
        return False

    def is_differential(self) -> bool:
        if self.integral_depth == 0:
            return False
        tok = self.peek()
        is_d = (
            (tok.kind == "LETTER" and tok.value == "d")
            or (tok.kind == "TEXT" and tok.arg == "mathrm" and tok.value.strip() == "d")
            or (tok.kind == "CMD" and tok.value == "differentialD")
        )
        return is_d and self.peek(1).kind in ("LETTER", "ATOM", "CMD") and not self.at("CMD", "right", 1)

    # ----- scripts and groups ---------------------------------------------
    def group(self) -> sp.Expr:
        self.expect("SYM", "{")
        saved_abs, self.abs_depth = self.abs_depth, 0
        value = self.expr()
        self.abs_depth = saved_abs
        self.expect("SYM", "}")
        return value

    def script(self) -> sp.Expr:
        """Argument of ^ or _ : a braced group or a single token."""
        tok = self.peek()
        if tok.kind == "SYM" and tok.value == "{":
            return self.group()
        if tok.kind == "NUM":
            self.next()
            return self._split_number(tok)
        if tok.kind == "SYM" and tok.value == "-":
            self.next()
            return -self.script()
        if tok.kind in ("LETTER", "CMD", "ATOM", "TEXT"):
            return self.primary(allow_subscript=False)
        self.fail("expected an exponent but found " + ("end of input" if tok is EOF else repr(tok.value)), tok)

    def _split_number(self, tok: Token) -> sp.Expr:
        """In scripts and \\frac12, an unbraced number contributes only its first digit."""
        if len(tok.value) > 1 and "." not in tok.value:
            rest = Token("NUM", tok.value[1:], tok.pos + 1)
            self.toks.insert(self.i, rest)
            return sp.Integer(tok.value[0])
        return _number(tok.value)

    def raw_arg_tokens(self) -> list[Token]:
        """Tokens of a braced argument (or a single token), without parsing."""
        if not self.at("SYM", "{"):
            return [self.next()]
        start = self.next()
        depth, out = 1, []
        while True:
            tok = self.peek()
            if tok is EOF:
                self.fail("unclosed '{' before end of input", start)
            self.next()
            if tok.kind == "SYM" and tok.value == "{":
                depth += 1
            elif tok.kind == "SYM" and tok.value == "}":
                depth -= 1
                if depth == 0:
                    return out
            out.append(tok)

    def frac_arg(self) -> sp.Expr:
        if self.at("SYM", "{"):
            return self.group()
        tok = self.next()
        if tok.kind == "NUM":
            return self._split_number(tok)
        self.i -= 1
        return self.primary(allow_subscript=False)

    # ----- primaries -------------------------------------------------------
    def primary(self, allow_subscript: bool = True) -> sp.Expr:
        tok = self.peek()
        if tok is EOF:
            self.fail("unexpected end of input")
        kind, value = tok.kind, tok.value
        if kind == "NUM":
            self.next()
            return _number(value)
        if kind in ("LETTER", "ATOM"):
            self.next()
            name = self._with_subscript(value) if (allow_subscript and kind == "LETTER") else value
            return self._name(name, tok)
        if kind == "TEXT":
            return self._text(tok)
        if kind == "SYM":
            if value in "([":
                self.next()
                saved_abs, self.abs_depth = self.abs_depth, 0
                inner = self.expr()
                self.abs_depth = saved_abs
                self.expect("SYM", OPEN[value])
                return inner
            if value == "|":
                self.next()
                self.abs_depth += 1
                inner = self.expr()
                self.abs_depth -= 1
                self.expect("SYM", "|")
                return sp.Abs(inner)
            self.fail(f"unexpected {value!r}", tok)
        if kind == "BEGIN":
            return self._environment(tok)
        if kind == "CMD":
            return self._command(tok, allow_subscript)
        self.fail(f"unexpected {value!r}", tok)

    def _with_subscript(self, name: str) -> str:
        if not self.at("SYM", "_"):
            return name
        self.next()
        sub = "".join(t.value for t in self.raw_arg_tokens())
        return f"{name}_{sub}"

    def _name(self, name: str, tok: Token) -> sp.Expr:
        if name in self.functions and self._at_open_paren():
            return self.functions[name](self._paren_arg())
        if name in self.symbols:
            return self.symbols[name]
        if name == "e":
            return sp.E
        return sp.Symbol(name)

    def _at_open_paren(self) -> bool:
        return self.at("SYM", "(") or (self.at("CMD", "left") and self.at("SYM", "(", 1))

    def _paren_arg(self) -> sp.Expr:
        if self.at("CMD", "left"):
            return self._left_right()
        self.expect("SYM", "(")
        inner = self.expr()
        self.expect("SYM", ")")
        return inner

    def _text(self, tok: Token) -> sp.Expr:
        self.next()
        content = tok.value.strip()
        if tok.arg == "operatorname":
            if content in FUNCS:
                return self._apply_function(content, tok)
            self.fail(f"unknown function \\operatorname{{{content}}}", tok)
        if self.units is not None and tok.arg in ("mathrm", "text", "textrm"):
            if content == "e" and tok.arg == "mathrm":
                return sp.E
            try:
                return self.units(content)
            except ValueError as exc:
                self.fail(f"unknown unit {content!r}: {exc}", tok)
        if tok.arg == "mathrm" and content == "e":
            return sp.E
        if tok.arg in ("mathrm", "mathit", "mathbf") and content.isalnum():
            return self._name(self._with_subscript(content), tok)
        self.fail(f"\\{tok.arg}{{{content}}} is not math", tok)

    def _command(self, tok: Token, allow_subscript: bool) -> sp.Expr:
        name = tok.value
        if name == "placeholder":
            self.fail(r"empty \placeholder: fill in every box", tok)
        if name in ("frac", "dfrac", "tfrac"):
            self.next()
            return self._frac(tok)
        if name == "sqrt":
            self.next()
            index = None
            if self.at("SYM", "["):
                self.next()
                index = self.expr()
                self.expect("SYM", "]")
            radicand = self.frac_arg()
            return sp.sqrt(radicand) if index is None else radicand ** (1 / sp.sympify(index))
        if name == "left":
            return self._left_right()
        if name in FUNCS:
            self.next()
            return self._apply_function(name, tok)
        if name == "int":
            self.next()
            return self._integral(tok)
        if name in ("sum", "prod"):
            self.next()
            return self._big_operator(name, tok)
        if name == "lim":
            self.next()
            return self._limit(tok)
        if name == "pi":
            self.next()
            return self.symbols.get("pi", sp.pi)
        if name == "infty":
            self.next()
            return sp.oo
        if name == "exponentialE":
            self.next()
            return sp.E
        if name == "imaginaryI":
            self.next()
            return sp.I
        if name in GREEK:
            self.next()
            symname = self._with_subscript(name) if allow_subscript else name
            return self._name(symname, tok)
        if name in ("lbrack", "lvert", "vert"):
            self.next()
            inner = self.expr()
            self.expect("CMD", OPEN[name])
            return sp.Abs(inner) if name != "lbrack" else inner
        self.fail(f"unknown command \\{name}", tok)

    def _frac(self, tok: Token) -> sp.Expr:
        start = self.i
        if self.at("SYM", "{") or _is_d([self.peek()]):
            num_toks = self.raw_arg_tokens()
            den_toks = self.raw_arg_tokens() if self.peek() is not EOF else []
            if _is_d(num_toks[:1]) and _is_d(den_toks[:1]) and len(den_toks) >= 2:
                if len(num_toks) != 1:
                    self.fail("derivative notation dy/dx is not supported; write d/dx applied to an expression", tok)
                var = self._sub_parser(den_toks[1:]).primary()
                return sp.Derivative(self._operand(), var)
            self.i = start
        return self.frac_arg() / self.frac_arg()

    def _sub_parser(self, toks: list[Token]) -> "_Parser":
        sub = _Parser.__new__(_Parser)
        sub.__dict__.update(self.__dict__)
        sub.toks, sub.i = list(toks), 0
        return sub

    def _operand(self) -> sp.Expr:
        """Argument of an operator written without parentheses: an implicit product."""
        if self._at_open_paren():
            value = self._paren_arg()
            while self.at("SYM", "^"):
                self.next()
                value = value ** self.script()
            return value
        value = self.postfix()
        while self.starts_factor() and not self._at_operator_command():
            value = value * self.postfix()
        return value

    def _at_operator_command(self) -> bool:
        tok = self.peek()
        return tok.kind == "CMD" and tok.value in (*FUNCS, "int", "sum", "prod", "lim")

    def _apply_function(self, name: str, tok: Token) -> sp.Expr:
        power = None
        base = None
        if self.at("SYM", "_") and name == "log":
            self.next()
            base = self.script()
        if self.at("SYM", "^"):
            self.next()
            power = self.script()
        if not self.starts_factor():
            self.fail(f"\\{name} needs an argument", tok)
        arg = self._operand()
        if power == -1 and name in INVERSE:
            return INVERSE[name](arg)
        value = sp.log(arg, base) if base is not None else FUNCS[name](arg)
        return value**power if power is not None else value

    def _left_right(self) -> sp.Expr:
        left = self.expect("CMD", "left")
        delim = self.next()
        if delim.value not in OPEN:
            self.fail(f"unsupported delimiter after \\left: {delim.value!r}", delim)
        closer = OPEN[delim.value]
        saved_abs, self.abs_depth = self.abs_depth, 0
        inner = self.expr()
        self.abs_depth = saved_abs
        if not self.at("CMD", "right"):
            self.fail("missing \\right before end of input" if self.peek() is EOF else "expected \\right", left)
        self.next()
        close = self.next()
        if close.value != closer:
            self.fail(f"mismatched \\right{close.value}", close)
        return sp.Abs(inner) if delim.value in ("|", "vert", "lvert") else inner

    def _bounds(self) -> tuple[sp.Expr | None, sp.Expr | None]:
        lower = upper = None
        for _ in range(2):
            if self.at("SYM", "_"):
                self.next()
                lower = self.script()
            elif self.at("SYM", "^"):
                self.next()
                upper = self.script()
        return lower, upper

    def _integral(self, tok: Token) -> sp.Expr:
        lower, upper = self._bounds()
        self.integral_depth += 1
        integrand = self.expr()
        self.integral_depth -= 1
        if not self._consume_differential():
            self.fail("integral is missing its differential (e.g. dx)", tok)
        var = self.primary()
        if not isinstance(var, sp.Symbol):
            self.fail("integration variable must be a symbol", tok)
        if (lower is None) != (upper is None):
            self.fail("definite integral needs both bounds", tok)
        if lower is None:
            return sp.Integral(integrand, var)
        return sp.Integral(integrand, (var, lower, upper))

    def _consume_differential(self) -> bool:
        self.integral_depth += 1
        ok = self.is_differential()
        self.integral_depth -= 1
        if ok:
            self.next()
        return ok

    def _big_operator(self, name: str, tok: Token) -> sp.Expr:
        if not self.at("SYM", "_"):
            self.fail(f"\\{name} needs a lower bound like _{{n=1}}", tok)
        self.next()
        sub = self._sub_parser(self.raw_arg_tokens())
        var = sub.primary()
        sub.expect("SYM", "=")
        lower = sub.expr()
        if not self.at("SYM", "^"):
            self.fail(f"\\{name} needs an upper bound", tok)
        self.next()
        upper = self.script()
        body = self._operand()
        cls = sp.Sum if name == "sum" else sp.Product
        return cls(body, (var, lower, upper))

    def _limit(self, tok: Token) -> sp.Expr:
        if not self.at("SYM", "_"):
            self.fail(r"\lim needs a subscript like _{x\to 0}", tok)
        self.next()
        sub = self._sub_parser(self.raw_arg_tokens())
        var = sub.primary()
        if not (sub.at("CMD", "to") or sub.at("CMD", "rightarrow")):
            self.fail(r"\lim subscript must look like x\to a", tok)
        sub.next()
        point = sub.expr()
        return sp.Limit(self._operand(), var, point)

    def _environment(self, tok: Token) -> sp.Expr:
        self.next()
        if tok.value != "cases":
            self.fail(f"unsupported environment {tok.value!r}", tok)
        pieces = []
        while True:
            value = self.expr()
            self.expect("SYM", "&")
            cond = self._condition()
            pieces.append((value, cond))
            if self.at("ROWSEP"):
                self.next()
                if self.at("END"):
                    break
                continue
            break
        end = self.next()
        if end.kind != "END" or end.value != "cases":
            self.fail("expected \\end{cases}", end)
        return sp.Piecewise(*pieces)

    def _condition(self):
        if self.at("TEXT") and self.peek().value.strip() in ("otherwise", "else"):
            self.next()
            return sp.true
        left = self.expr()
        conds = []
        while True:
            tok = self.peek()
            rel = None
            if tok.kind == "SYM" and tok.value in "<>":
                rel = COMPARISONS[tok.value]
            elif tok.kind == "CMD" and tok.value in COMPARISONS:
                rel = COMPARISONS[tok.value]
            if rel is None:
                break
            self.next()
            right = self.expr()
            conds.append(rel(left, right))
            left = right
        if not conds:
            self.fail("piecewise condition needs a comparison", tok)
        return sp.And(*conds) if len(conds) > 1 else conds[0]


def _is_d(toks: list[Token]) -> bool:
    if len(toks) != 1:
        return False
    t = toks[0]
    return (
        (t.kind == "LETTER" and t.value == "d")
        or (t.kind == "TEXT" and t.arg == "mathrm" and t.value.strip() == "d")
        or (t.kind == "CMD" and t.value == "differentialD")
    )


def _number(text: str) -> sp.Expr:
    if "." in text:
        whole, frac = text.split(".")
        return sp.Rational(int((whole or "0") + frac), 10 ** len(frac))
    return sp.Integer(text)
