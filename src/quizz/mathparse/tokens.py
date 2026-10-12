"""Tokenizer for the MathLive LaTeX dialect."""

from dataclasses import dataclass

from quizz.mathparse.errors import ParseError

# Commands that only affect spacing; dropped during tokenization.
SPACING = {",", ";", ":", "!", " ", "quad", "qquad", "enspace", "thinspace", "medspace", "thickspace"}
# Commands whose braced argument is raw text rather than math.
TEXT_COMMANDS = {"mathrm", "text", "textrm", "operatorname", "mathit", "mathbf"}


@dataclass(frozen=True)
class Token:
    kind: str  # NUM, LETTER, CMD, TEXT, SYM, ATOM, BEGIN, END, ROWSEP
    value: str
    pos: int
    arg: str = ""  # TEXT: the command name (mathrm, text, ...)


def tokenize(src: str, atoms: tuple[str, ...] = ()) -> list[Token]:
    tokens = _scan(src)
    if atoms:
        tokens = _merge_atoms(tokens, atoms)
    return tokens


def _scan(src: str) -> list[Token]:
    out: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace() or c == "~":
            i += 1
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and src[j].isdigit():
                j += 1
            if j < n and src[j] == "." and j + 1 < n and src[j + 1].isdigit():
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
            out.append(Token("NUM", src[i:j], i))
            i = j
        elif c.isalpha():
            out.append(Token("LETTER", c, i))
            i += 1
        elif c == "\\":
            i = _scan_command(src, i, out)
        elif c in "+-=^_{}()[]|!,&<>/*":
            out.append(Token("SYM", c, i))
            i += 1
        else:
            raise ParseError(f"unexpected character {c!r}", i)
    return out


def _scan_command(src: str, i: int, out: list[Token]) -> int:
    n = len(src)
    if i + 1 >= n:
        raise ParseError("dangling backslash at end of input", i)
    nxt = src[i + 1]
    if nxt == "\\":
        out.append(Token("ROWSEP", "\\\\", i))
        return i + 2
    if not nxt.isalpha():
        if nxt in SPACING:
            return i + 2
        if nxt in "{}":
            out.append(Token("SYM", nxt, i))  # \{ \} as literal braces
            return i + 2
        raise ParseError(f"unknown command \\{nxt}", i)
    j = i + 1
    while j < n and src[j].isalpha():
        j += 1
    name = src[i + 1 : j]
    if name in SPACING:
        return j
    if name in TEXT_COMMANDS or name in ("begin", "end"):
        content, j = _read_raw_group(src, j, name)
        if name == "begin":
            out.append(Token("BEGIN", content, i))
        elif name == "end":
            out.append(Token("END", content, i))
        else:
            out.append(Token("TEXT", content, i, arg=name))
        return j
    out.append(Token("CMD", name, i))
    return j


def _read_raw_group(src: str, j: int, name: str) -> tuple[str, int]:
    n = len(src)
    while j < n and src[j].isspace():
        j += 1
    if j >= n or src[j] != "{":
        raise ParseError(f"\\{name} expects a braced argument", j)
    depth, k = 0, j
    while k < n:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[j + 1 : k], k + 1
        k += 1
    raise ParseError(f"unclosed \\{name}{{ before end of input", j)


def _units(tokens: list[Token]) -> list[tuple[str, str, int]]:
    """Spelling-insensitive view of tokens for atom matching: braces dropped, \\mathrm{abc} -> letters.

    Each unit is (kind, value, index of the source token)."""
    units = []
    for idx, tok in enumerate(tokens):
        if tok.kind == "SYM" and tok.value in "{}":
            continue
        if tok.kind == "TEXT" and tok.arg in ("mathrm", "text", "textrm", "mathit") and tok.value.strip().isalnum():
            units.extend(("LETTER", c, idx) for c in tok.value.strip())
            continue
        units.append((tok.kind, tok.value, idx))
    return units


def _merge_atoms(tokens: list[Token], atoms: tuple[str, ...]) -> list[Token]:
    patterns = sorted(
        ((a, [(k, v) for k, v, _ in _units(_scan(a))]) for a in atoms),
        key=lambda p: -len(p[1]),
    )
    units = _units(tokens)
    first_unit = {}
    for u, (_, _, idx) in enumerate(units):
        first_unit.setdefault(idx, u)
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        u = first_unit.get(i)
        for atom, pat in patterns if u is not None else ():
            window = [(k, v) for k, v, _ in units[u : u + len(pat)]]
            if pat and window == pat:
                end = units[u + len(pat) - 1][2] + 1
                depth = sum(1 if t.value == "{" else -1 for t in tokens[i:end] if t.kind == "SYM" and t.value in "{}")
                while depth > 0 and end < len(tokens) and tokens[end].kind == "SYM" and tokens[end].value == "}":
                    end, depth = end + 1, depth - 1
                out.append(Token("ATOM", atom, tokens[i].pos))
                i = end
                break
        else:
            out.append(tokens[i])
            i += 1
    return out
