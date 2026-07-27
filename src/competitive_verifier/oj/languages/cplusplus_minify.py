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


def _collapse_whitespace(
    line: bytes, *, in_raw_string: bytes | None
) -> tuple[bytes, bytes | None]:
    """Collapse whitespace runs to single spaces outside literals.

    ``in_raw_string`` is the delimiter of the raw string literal the line
    starts inside (or None); the return value carries the same state to
    the next line.
    """
    out = bytearray()
    i = 0
    pending_space = False

    def flush(upto: int) -> None:
        nonlocal pending_space
        if pending_space and out:
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
    packed: list[bytes] = []
    current_file: bytes | None = None
    pending_marker: bytes | None = None
    in_raw_string: bytes | None = None

    def flush_packed() -> None:
        if packed:
            out.append(b" ".join(packed))
            packed.clear()

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
                packed[-1] += b"\n" + collapsed
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

        line, in_raw_string = _collapse_whitespace(raw_line, in_raw_string=None)
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

        if packed and len(b" ".join(packed)) + 1 + len(line) > width:
            flush_packed()
        packed.append(line)
        if in_raw_string is not None:
            flush_packed()

    flush_packed()
    return b"\n".join(out) + b"\n" if out else b""
