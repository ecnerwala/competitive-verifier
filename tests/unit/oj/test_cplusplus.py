import pathlib
import shutil

import pytest

from competitive_verifier.oj.languages.cplusplus import (
    _cplusplus_list_include_directories,  # pyright: ignore[reportPrivateUsage]
)

_compilers = [cxx for cxx in ("g++", "clang++") if shutil.which(cxx)]


@pytest.mark.allow_mkdir
@pytest.mark.skipif(not _compilers, reason="no C++ compiler is installed")
@pytest.mark.parametrize("cxx", _compilers)
@pytest.mark.parametrize(
    ("cxx_flags", "expected"),
    [
        ([], []),
        (["-O2"], []),
        (["-I", "src"], ["src"]),
        (["-Isrc"], ["src"]),
        (["-iquote", "include"], ["include"]),
        (["-iquoteinclude"], ["include"]),
        (["-isystem", "third_party"], ["third_party"]),
        (["-idirafter", "fallback"], ["fallback"]),
        (
            ["-I", "src", "-Wall", "-Ithird_party", "-iquote", "include"],
            ["include", "src", "third_party"],
        ),
    ],
)
def test_list_include_directories(
    cxx: str,
    cxx_flags: list[str],
    expected: list[str],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    for name in ("src", "include", "third_party", "fallback"):
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path)
    dirs = _cplusplus_list_include_directories(
        CXX=pathlib.Path(cxx),
        CXXFLAGS=cxx_flags,
    )
    assert sorted(dirs) == sorted((tmp_path / p).resolve() for p in expected)


def test_list_include_directories_fallback():
    dirs = _cplusplus_list_include_directories(
        CXX=pathlib.Path("no-such-compiler"),
        CXXFLAGS=["-I", "src"],
    )
    assert dirs == []
