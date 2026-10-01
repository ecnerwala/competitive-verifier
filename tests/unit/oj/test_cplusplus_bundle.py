import pathlib
import re
import shutil
import textwrap
from collections.abc import Sequence

import pytest

from competitive_verifier.oj.languages.cplusplus_bundle import (
    Bundler,
    _check_compiler,  # pyright: ignore[reportPrivateUsage]
)

_has_gcc = shutil.which("g++") is not None and _check_compiler("g++") == "gcc"

pytestmark = [
    pytest.mark.skipif(not _has_gcc, reason="g++ (GNU) is not installed"),
    pytest.mark.allow_mkdir,
]

_LINE_MARKER = re.compile(rb'^#line \d+ ".*"\n', re.MULTILINE)


def _bundle(
    tmp_path: pathlib.Path,
    code: str,
    *,
    keep_markers: bool = False,
    prelude_includes: Sequence[str] = (),
    hoist_system_includes: bool = False,
) -> str:
    path = tmp_path / "main.cpp"
    path.write_text(textwrap.dedent(code))
    bundler = Bundler(
        compiler="g++",
        prelude_includes=prelude_includes,
        hoist_system_includes=hoist_system_includes,
    )
    bundler.update(path)
    out = bundler.get()
    if not keep_markers:
        out = _LINE_MARKER.sub(b"", out)
    return out.decode()


_CODE = """\
    #include <vector>
    #include <bits/stdc++.h>
    #include <map>
    #include <unistd.h>
    int x = 1;
    #ifdef FOO
    #include <sys/types.h>
    #endif
    int y = 2;
    """


def test_default_keeps_system_includes_in_place(tmp_path: pathlib.Path):
    assert _bundle(tmp_path, _CODE) == (
        "#include <vector>\n"
        "#include <bits/stdc++.h>\n"
        "#include <unistd.h>\n"
        "int x = 1;\n"
        "#ifdef FOO\n"
        "#include <sys/types.h>\n"
        "#endif\n"
        "int y = 2;\n"
    )


def test_prelude_includes_subsume_later_includes(tmp_path: pathlib.Path):
    out = _bundle(
        tmp_path, _CODE, keep_markers=True, prelude_includes=["bits/stdc++.h"]
    )
    assert _LINE_MARKER.sub(b"", out.encode()).decode() == (
        "#include <bits/stdc++.h>\n"
        "#include <unistd.h>\n"
        "int x = 1;\n"
        "#ifdef FOO\n"
        "#include <sys/types.h>\n"
        "#endif\n"
        "int y = 2;\n"
    )
    assert re.search(
        r'^#line 4 ".*"\n#include <unistd.h>\nint x = 1;$', out, re.MULTILINE
    )


def test_hoist_system_includes(tmp_path: pathlib.Path):
    out = _bundle(tmp_path, _CODE, keep_markers=True, hoist_system_includes=True)
    assert _LINE_MARKER.sub(b"", out.encode()).decode() == (
        "#include <vector>\n"
        "#include <bits/stdc++.h>\n"
        "#include <unistd.h>\n"
        "int x = 1;\n"
        "#ifdef FOO\n"
        "#include <sys/types.h>\n"
        "#endif\n"
        "int y = 2;\n"
    )
    assert re.search(r'^#line 5 ".*"\nint x = 1;$', out, re.MULTILINE)


def test_hoist_with_prelude(tmp_path: pathlib.Path):
    out = _bundle(
        tmp_path,
        _CODE,
        prelude_includes=["bits/stdc++.h"],
        hoist_system_includes=True,
    )
    assert out == (
        "#include <bits/stdc++.h>\n"
        "#include <unistd.h>\n"
        "int x = 1;\n"
        "#ifdef FOO\n"
        "#include <sys/types.h>\n"
        "#endif\n"
        "int y = 2;\n"
    )
