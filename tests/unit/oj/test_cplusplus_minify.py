import shutil
import textwrap

import pytest

from competitive_verifier.oj.languages.cplusplus_bundle import (
    _check_compiler,  # pyright: ignore[reportPrivateUsage]
)
from competitive_verifier.oj.languages.cplusplus_minify import minify

_has_gcc = shutil.which("g++") is not None and _check_compiler("g++") == "gcc"

pytestmark = pytest.mark.skipif(not _has_gcc, reason="g++ (GNU) is not installed")


def _minify_str(code: str) -> str:
    return minify(textwrap.dedent(code).encode(), compiler="g++").decode()


def test_strips_comments_and_packs_lines():
    out = _minify_str(
        """\
        // a line comment
        int x = 1; /* inline */ int y = 2;
        /* multi
           line */ int z = 3;

        int w = 4;
        """
    )
    assert out == "int x = 1; int y = 2; int z = 3; int w = 4;\n"


def test_keeps_source_markers_at_file_transitions():
    out = _minify_str(
        """\
        #line 1 "src/a.hpp"
        int a;
        #line 3 "src/a.hpp"
        int a2;
        #line 1 "src/b.hpp"
        int b;
        #line 10 "src/a.hpp"
        int a3;
        """
    )
    assert out == textwrap.dedent(
        """\
        #line 1 "src/a.hpp"
        int a; int a2;
        #line 1 "src/b.hpp"
        int b;
        #line 10 "src/a.hpp"
        int a3;
        """
    )


def test_directives_keep_their_own_lines():
    out = _minify_str(
        """\
        #include <vector>
        #define FOO(a) \\
            ((a) + 1)
        int x = FOO(1);
        int y = FOO(2);
        """
    )
    assert out == textwrap.dedent(
        """\
        #include <vector>
        #define FOO(a) \\
        ((a) + 1)
        int x = FOO(1); int y = FOO(2);
        """
    )


def test_string_literals_are_preserved():
    out = _minify_str(
        """\
        const char* a = "two  spaces /* not a comment */";
        const char* b = "\\"  \\\\";
        char c = ' ';
        """
    )
    assert (
        out
        == 'const char* a = "two  spaces /* not a comment */"; const char* b = "\\"  \\\\"; char c = \' \';\n'
    )


def test_raw_strings_are_preserved():
    out = _minify_str(
        """\
        const char* r = R"x(keep  //  this
        and  this)x";
        int y = 0;
        """
    )
    assert out == textwrap.dedent(
        """\
        const char* r = R"x(keep  //  this
        and  this)x";
        int y = 0;
        """
    )


def test_width_limit():
    code = "".join(f"int x{i} = {i};\n" for i in range(100))
    out = _minify_str(code)
    lines = out.splitlines()
    assert len(lines) > 1
    assert all(len(line) <= 120 for line in lines)
    assert out.replace("\n", " ").split() == code.replace("\n", " ").split()
