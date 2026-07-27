import re
import shutil
import textwrap

import pytest

from competitive_verifier.oj.languages.cplusplus_bundle import (
    _check_compiler,  # pyright: ignore[reportPrivateUsage]
)
from competitive_verifier.oj.languages.cplusplus_minify import (
    minify,
    raw_token_stream,
)

_has_gcc = shutil.which("g++") is not None and _check_compiler("g++") == "gcc"

pytestmark = pytest.mark.skipif(not _has_gcc, reason="g++ (GNU) is not installed")


_PROLOGUE = (
    "#pragma GCC diagnostic push\n"
    '#pragma GCC diagnostic ignored "-Wpragmas"\n'
    '#pragma GCC diagnostic ignored "-Wunknown-warning-option"\n'
    '#pragma GCC diagnostic ignored "-Wmisleading-indentation"\n'
    '#pragma GCC diagnostic ignored "-Wmultistatement-macros"\n'
)
_EPILOGUE = "#pragma GCC diagnostic pop\n"


def _minify_str(code: str) -> str:
    out = minify(textwrap.dedent(code).encode(), compiler="g++").decode()
    assert out.startswith(_PROLOGUE)
    assert out.endswith(_EPILOGUE)
    return out[len(_PROLOGUE) : -len(_EPILOGUE)]


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
    assert out == "int x=1;int y=2;int z=3;int w=4;\n"


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
        // src/a.hpp
        int a;int a2;
        // src/b.hpp
        int b;
        // src/a.hpp
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
        ((a)+1)
        int x=FOO(1);int y=FOO(2);
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
        == 'const char*a="two  spaces /* not a comment */";const char*b="\\"  \\\\";char c=\' \';\n'
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
        const char*r=R"x(keep  //  this
        and  this)x";
        int y=0;
        """
    )


def test_squeeze_keeps_token_separating_spaces():
    out = _minify_str(
        """\
        int q = a + +b - -c;
        bool r = x < y && y > z;
        const char* s = u8"a" "b";
        auto t = 1 . nothing;
        """
    )
    assert out == (
        'int q=a+ +b- -c;bool r=x<y&&y>z;const char*s=u8"a" "b";auto t=1 .nothing;\n'
    )


def test_width_limit():
    code = "".join(f"int x{i} = {i};\n" for i in range(100))
    out = _minify_str(code)
    lines = out.splitlines()
    assert len(lines) > 1
    assert all(len(line) <= 120 for line in lines)
    assert re.sub(r"\s+", "", out) == re.sub(r"\s+", "", code)


def test_warning_pragmas_wrap_output():
    out = minify(b"int x = 1;\n", compiler="g++").decode()
    assert out.startswith(_PROLOGUE)
    assert out.endswith(_EPILOGUE)
    assert minify(b"", compiler="g++") == b""


def test_target_pragma_macro_dump_is_dropped():
    # -dD dumps the macro state changed by #pragma GCC target; none of it
    # may leak into the output, while user directives survive.
    out = _minify_str(
        """\
        #pragma GCC target("avx2")
        #define FOO 1
        int x = FOO;
        #undef FOO
        """
    )
    assert "__AVX" not in out
    assert "__code_model_small__" not in out
    assert "#define FOO 1" in out
    assert "#undef FOO" in out


_GNARLY = textwrap.dedent(
    """\
    #line 1 "src/a.hpp"
    #pragma GCC target("avx2")
    #define MAX(a, b) ((a) > (b) ? (a) : (b))
    template <typename T> T f(T a, T b) { return a + +b; /* c */ }
    #line 1 "src/b.hpp"
    const char* s = u8"a" "b";  // string juxtaposition
    const char* r = R"x(raw
      string)x";
    bool g(int x, int y) { return x < y && y > x; }
    """
).encode()


@pytest.mark.skipif(shutil.which("clang++") is None, reason="clang++ not installed")
def test_token_stream_is_preserved():
    minified = minify(_GNARLY, compiler="g++")
    assert raw_token_stream(_GNARLY) == raw_token_stream(minified)


def test_light_keeps_line_structure_and_markers():
    code = textwrap.dedent(
        """\
        #line 1 "src/a.hpp"
        int a = 1;  // trailing comment

        /* a
           very
           long
           comment
           block
           spanning
           many
           lines
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding
           padding */
        int b = 2;
        int c = 3;
        """
    ).encode()
    out = minify(code, compiler="g++", level="light").decode()
    assert out == textwrap.dedent(
        """\
        #line 1 "src/a.hpp"
        int a = 1;
        #line 36 "src/a.hpp"
        int b = 2;
        int c = 3;
        """
    )


def test_light_keeps_short_blank_runs():
    code = b'#line 1 "src/a.hpp"\nint a = 1;\n\nint b = 2;\n'
    out = minify(code, compiler="g++", level="light")
    assert out == b'#line 1 "src/a.hpp"\nint a = 1;\n\nint b = 2;\n'
