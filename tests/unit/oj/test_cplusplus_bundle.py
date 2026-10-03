import pathlib
import re
import shutil
import textwrap

import pytest

from competitive_verifier.oj.languages.cplusplus_bundle import (
    Bundler,
    _check_compiler,  # pyright: ignore[reportPrivateUsage]
    get_uncommented_code,
    pair_source_lines,
)

_has_gcc = shutil.which("g++") is not None and _check_compiler("g++") == "gcc"

pytestmark = [
    pytest.mark.skipif(not _has_gcc, reason="g++ (GNU) is not installed"),
    pytest.mark.allow_mkdir,
]


def _uncommented(tmp_path: pathlib.Path, code: str) -> list[list[str]]:
    path = tmp_path / "main.cpp"
    path.write_text(textwrap.dedent(code))
    groups = get_uncommented_code(path, iquotes=[], compiler="g++")
    return [[line.decode().rstrip("\n") for line in group] for group in groups]


# The compiler attributes a comment-only line either to a blank output line
# or to nothing (a linemarker instead). g++ >= 14 also dumps the macro state
# changed by #pragma GCC target (#define __AVX2__ 1, ...) attributed to the
# line after the pragma.
def _source_lines(groups: list[list[str]]) -> list[list[str]]:
    return [
        [
            line
            for line in group
            if line.strip() and not re.match(r"#(define|undef) __\w+__", line)
        ]
        for group in groups
    ]


def test_uncommented_code_groups_lines_after_target_pragma(tmp_path: pathlib.Path):
    out = _uncommented(
        tmp_path,
        """\
        #pragma GCC target("avx2")
        // comment
        #define FOO 1
        int x = FOO; /* c */
        #undef FOO
        int y = 2;
        """,
    )
    assert _source_lines(out) == [
        ['#pragma GCC target("avx2")'],
        [],
        ["#define FOO 1"],
        ["int x = FOO;"],
        ["#undef FOO"],
        ["int y = 2;"],
    ]


def test_uncommented_code_keeps_trailing_target_pragma(tmp_path: pathlib.Path):
    out = _uncommented(tmp_path, 'int a;\n#pragma GCC target("avx2")\n')
    assert _source_lines(out) == [["int a;"], ['#pragma GCC target("avx2")']]


def test_uncommented_code_keeps_line_after_target_pragma(tmp_path: pathlib.Path):
    out = _uncommented(tmp_path, '#pragma GCC target("avx2")\nint x = 1;\nint y = 2;\n')
    assert _source_lines(out) == [
        ['#pragma GCC target("avx2")'],
        ["int x = 1;"],
        ["int y = 2;"],
    ]


def test_uncommented_code_groups_around_pragmas_mid_file(tmp_path: pathlib.Path):
    out = _uncommented(
        tmp_path,
        """\
        int a;

        /* multi
         line */
        #pragma GCC target("avx2")

        // c
        int b; /* d */
        #pragma GCC optimize("O3")
        int c;
        """,
    )
    assert _source_lines(out) == [
        ["int a;"],
        [],
        [],
        [],
        ['#pragma GCC target("avx2")'],
        [],
        [],
        ["int b;"],
        ['#pragma GCC optimize("O3")'],
        ["int c;"],
    ]


def test_bundle_inlines_include_after_target_pragma(tmp_path: pathlib.Path):
    (tmp_path / "x.hpp").write_text("#pragma once\nint x_from_header = 1;\n")
    (tmp_path / "main.cpp").write_text(
        '#pragma GCC target("avx2")\n#include "x.hpp"\nint y = x_from_header;\n'
    )
    bundler = Bundler(iquotes=[tmp_path], compiler="g++")
    bundler.update(tmp_path / "main.cpp")
    assert bundler.get().decode() == textwrap.dedent(
        f"""\
        #line 1 "{tmp_path / "main.cpp"}"
        #pragma GCC target("avx2")
        #line 2 "{tmp_path / "x.hpp"}"
        int x_from_header = 1;
        #line 3 "{tmp_path / "main.cpp"}"
        int y = x_from_header;
        """
    )


def test_pair_source_lines():
    source = (
        b'int /* c */ x; // d\n#pragma GCC target("avx2")\n// e\nint y;\n#define X 1\n'
    )
    groups = [
        [b"int x;\n"],
        [b'#pragma GCC target("avx2")\n', b"#undef __code_model_small__\n"],
        [b"#define __AVX2__ 1\n"],
        [b"#define __SSE3__ 1\n", b"int y;\n"],
        [b"#define X 1\n", b"#define X 1\n"],
    ]
    assert pair_source_lines(source, groups) == [
        ((0, b"int /* c */ x; // d\n"), b"int x;\n"),
        ((1, b'#pragma GCC target("avx2")\n'), b'#pragma GCC target("avx2")\n'),
        (None, b"#undef __code_model_small__\n"),
        (None, b"#define __AVX2__ 1\n"),
        ((2, b"// e\n"), b""),
        (None, b"#define __SSE3__ 1\n"),
        ((3, b"int y;\n"), b"int y;\n"),
        (None, b"#define X 1\n"),
        ((4, b"#define X 1\n"), b"#define X 1\n"),
    ]
