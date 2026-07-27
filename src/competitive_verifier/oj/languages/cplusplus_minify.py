"""Compiler-directed minification of bundled C++ code.

The compiler (``g++ -fpreprocessed -dD -E``) strips comments, so no
hand-rolled comment parser can disagree with the real tokenizer.
The remaining passes are whitespace-only:

- runs of whitespace collapse to a single space (never inside string,
  character, or raw string literals),
- blank lines are dropped,
- consecutive statement lines are packed onto shared lines up to a width
  limit,
- preprocessor directives keep their own lines,
- ``#line`` markers emitted by the bundler are kept at file transitions
  (and dropped in between), so the output still records which header
  each region came from and compiler diagnostics point at real files.
"""

import os
import pathlib
import re
import tempfile

from competitive_verifier.exec import command_stdout

DEFAULT_WIDTH = 120

_LINEMARKER_RE = re.compile(rb'# (\d+) ".*"')
_LINE_DIRECTIVE_RE = re.compile(rb'\s*#\s*line\s+(\d+)\s+(".*")\s*')
_RAW_STRING_START_RE = re.compile(rb'(?:u8|[uUL])?R"([^ ()\\\t\v\f\n"]*)\(')


def _uncomment(code: bytes, *, compiler: str) -> bytes:
    """Strip comments with the compiler, preserving line structure.

    ``#line`` directives pass through ``-fpreprocessed`` untouched; the
    linemarkers in the output all refer to the input file and are used to
    restore the original line numbering.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpfile = pathlib.Path(tmpdir) / "bundled.cpp"
        tmpfile.write_bytes(code)
        out = command_stdout(
            [compiler, "-x", "c++", "-fpreprocessed", "-dD", "-E", str(tmpfile)],
            text=False,
        )
    lines: list[bytes] = []
    for line in out.splitlines():
        m = _LINEMARKER_RE.match(line.rstrip())
        if m:
            while len(lines) + 1 < int(m.group(1)):
                lines.append(b"")
        else:
            lines.append(line)
    return b"\n".join(lines) + b"\n"


# A space between tokens can be dropped unless the adjacent characters would
# lex as one longer token (maximal munch): identifier/number characters and
# string prefixes/suffixes on both sides, or a two-character sequence that
# forms (or extends) an operator, comment, or digraph.
_WORDLIKE = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$\"'"
)
_MERGING_PAIRS = frozenset(
    b"++ -- += -= *= /= %= ^= &= |= == != <= >= << >> && || -> :: .. .* <: :> <% %> %: ## /* */ //".split()
)
_DIGITS = frozenset(b"0123456789")


def _needs_space(left: int, right: int) -> bool:
    if left in _WORDLIKE and right in _WORDLIKE:
        return True
    # A dot next to a digit would be absorbed into a pp-number.
    if (left in _DIGITS and right == ord(".")) or (
        left == ord(".") and right in _DIGITS
    ):
        return True
    return bytes((left, right)) in _MERGING_PAIRS


def _collapse_whitespace(
    line: bytes, *, in_raw_string: bytes | None, squeeze: bool = True
) -> tuple[bytes, bytes | None]:
    """Collapse whitespace runs outside literals.

    A run becomes a single space, or nothing when ``squeeze`` is set and
    dropping it cannot merge the neighboring tokens.
    ``in_raw_string`` is the delimiter of the raw string literal the line
    starts inside (or None); the return value carries the same state to
    the next line.
    """
    out = bytearray()
    i = 0
    pending_space = False

    def flush(upto: int) -> None:
        nonlocal pending_space
        if pending_space and out and (not squeeze or _needs_space(out[-1], line[i])):
            out.append(ord(" "))
        pending_space = False
        out.extend(line[i:upto])

    while i < len(line):
        if in_raw_string is not None:
            end = line.find(b")" + in_raw_string + b'"', i)
            if end < 0:
                out.extend(line[i:])
                return bytes(out), in_raw_string
            end += len(in_raw_string) + 2
            out.extend(line[i:end])
            i = end
            in_raw_string = None
            continue
        c = line[i : i + 1]
        if c in (b" ", b"\t", b"\v", b"\f"):
            if out:
                pending_space = True
            i += 1
            continue
        m = _RAW_STRING_START_RE.match(line, i)
        if m:
            flush(m.end())
            i = m.end()
            in_raw_string = m.group(1)
            continue
        if c in (b'"', b"'"):
            j = i + 1
            while j < len(line):
                if line[j : j + 1] == b"\\":
                    j += 2
                elif line[j : j + 1] == c:
                    j += 1
                    break
                else:
                    j += 1
            flush(j)
            i = j
            continue
        flush(i + 1)
        i += 1
    return bytes(out), None


def minify(
    code: bytes,
    *,
    compiler: str = os.environ.get("CXX", "g++"),
    width: int = DEFAULT_WIDTH,
) -> bytes:
    uncommented = _uncomment(code, compiler=compiler)

    out: list[bytes] = []
    packed = bytearray()
    current_file: bytes | None = None
    pending_marker: bytes | None = None
    in_raw_string: bytes | None = None

    def flush_packed() -> None:
        if packed:
            out.append(bytes(packed))
            packed.clear()

    def pack(line: bytes) -> None:
        if packed and _needs_space(packed[-1], line[0]):
            packed.append(ord(" "))
        packed.extend(line)

    def emit_marker() -> None:
        nonlocal pending_marker
        if pending_marker is not None:
            flush_packed()
            out.append(pending_marker)
            pending_marker = None

    for raw_line in uncommented.split(b"\n"):
        if in_raw_string is not None:
            # Inside a multi-line raw string literal: preserve verbatim.
            collapsed, in_raw_string = _collapse_whitespace(
                raw_line, in_raw_string=in_raw_string
            )
            if packed:
                packed.extend(b"\n" + collapsed)
            else:
                out[-1] += b"\n" + collapsed
            continue

        m = _LINE_DIRECTIVE_RE.match(raw_line)
        if m:
            path = m.group(2)
            if path != current_file:
                current_file = path
                pending_marker = b"#line " + m.group(1) + b" " + path
            continue

        # Directives keep single spaces: in `#define FOO (x)` the space
        # before `(` distinguishes an object-like from a function-like macro.
        is_directive = raw_line.lstrip(b" \t\v\f").startswith(b"#")
        line, in_raw_string = _collapse_whitespace(
            raw_line, in_raw_string=None, squeeze=not is_directive
        )
        if not line:
            continue
        emit_marker()

        if line.startswith(b"#"):
            # Directives (and their backslash continuations) keep their own
            # lines.
            flush_packed()
            out.append(line)
            continue

        if raw_line.endswith(b"\\") or (out and out[-1].endswith(b"\\")):
            # Backslash continuation (e.g. inside a #define): keep line
            # structure so the directive stays intact.
            flush_packed()
            out.append(line)
            continue

        if packed and len(packed) + 1 + len(line) > width:
            flush_packed()
        pack(line)
        if in_raw_string is not None:
            flush_packed()

    flush_packed()
    if not out:
        return b""
    # Packing many statements per line makes indentation meaningless, so
    # silence the warnings that key off it (push/pop so nothing appended
    # after the minified region is affected). -Wpragmas (GCC) and
    # -Wunknown-warning-option (clang) keep each compiler quiet about the
    # other's warning names.
    prologue = [
        b"#pragma GCC diagnostic push",
        b'#pragma GCC diagnostic ignored "-Wpragmas"',
        b'#pragma GCC diagnostic ignored "-Wunknown-warning-option"',
        b'#pragma GCC diagnostic ignored "-Wmisleading-indentation"',
        b'#pragma GCC diagnostic ignored "-Wmultistatement-macros"',
    ]
    return b"\n".join(prologue + out + [b"#pragma GCC diagnostic pop"]) + b"\n"
