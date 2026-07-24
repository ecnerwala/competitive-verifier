import pathlib
import subprocess
import textwrap

import pytest
from pytest_mock import MockerFixture

from competitive_verifier.oj.problem import (
    LibraryCheckerProblem,
    _normpath,  # pyright: ignore[reportPrivateUsage]
    problem_from_url,
)

test_normpath_params: list[tuple[str, str]] = [
    ("hoge/foo/bar", "hoge/foo/bar"),
    ("/foo/bar", "/foo/bar"),
    ("//foo/bar", "/foo/bar"),
]


@pytest.mark.parametrize(
    ("path", "expected"),
    test_normpath_params,
    ids=[t[0] for t in test_normpath_params],
)
def test_normpath(path: str, expected: str):
    assert _normpath(path) == expected


test_problem_repr_params = [
    (
        "https://onlinejudge.u-aizu.ac.jp/courses/lesson/2/ITP1/1/ITP1_1_A",
        "AOJProblem.from_url('http://judge.u-aizu.ac.jp/onlinejudge/description.jsp?id=ITP1_1_A')",
    ),
    (
        "https://onlinejudge.u-aizu.ac.jp/problems/ITP1_1_A",
        "AOJProblem.from_url('http://judge.u-aizu.ac.jp/onlinejudge/description.jsp?id=ITP1_1_A')",
    ),
    (
        "https://judge.u-aizu.ac.jp/onlinejudge/description.jsp?id=ITP1_1_A&lang=jp",
        "AOJProblem.from_url('http://judge.u-aizu.ac.jp/onlinejudge/description.jsp?id=ITP1_1_A')",
    ),
    (
        "https://onlinejudge.u-aizu.ac.jp/services/room.html#RitsCamp19Day2/problems/A",
        "AOJArenaProblem.from_url('https://onlinejudge.u-aizu.ac.jp/services/room.html#RitsCamp19Day2/problems/A')",
    ),
    (
        "https://old.yosupo.jp/problem/aplusb",
        "LibraryCheckerProblem.from_url('https://judge.yosupo.jp/problem/aplusb')",
    ),
    (
        "https://judge.yosupo.jp/problem/aplusb",
        "LibraryCheckerProblem.from_url('https://judge.yosupo.jp/problem/aplusb')",
    ),
    (
        "http://old.yosupo.jp/problem/aplusb",
        "LibraryCheckerProblem.from_url('https://judge.yosupo.jp/problem/aplusb')",
    ),
    (
        "http://judge.yosupo.jp/problem/aplusb",
        "LibraryCheckerProblem.from_url('https://judge.yosupo.jp/problem/aplusb')",
    ),
    (
        "https://yukicoder.me/problems/4573",
        "YukicoderProblem.from_url('https://yukicoder.me/problems/4573')",
    ),
    (
        "https://yukicoder.me/problems/no/1088",
        "YukicoderProblem.from_url('https://yukicoder.me/problems/no/1088')",
    ),
    (
        "http://yukicoder.me/problems/4573",
        "YukicoderProblem.from_url('https://yukicoder.me/problems/4573')",
    ),
    (
        "http://yukicoder.me/problems/no/1088",
        "YukicoderProblem.from_url('https://yukicoder.me/problems/no/1088')",
    ),
    (
        "http://yukicoder.me/4573",
        "None",
    ),
]


@pytest.mark.parametrize(
    ("url", "expected"),
    test_problem_repr_params,
    ids=[t[0] for t in test_problem_repr_params],
)
def test_problem_repr(url: str, expected: str):
    assert repr(problem_from_url(url)) == expected


@pytest.fixture
def library_checker_repo(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pathlib.Path:
    monkeypatch.setenv("COMPETITIVE_VERIFY_CONFIG_PATH", str(tmp_path))
    repo_path = tmp_path / "cache" / "library-checker-problems"
    (repo_path / "sample" / "aplusb").mkdir(parents=True)
    (repo_path / "sample" / "aplusb" / "info.toml").write_text("")
    (repo_path / "generate.py").write_text(
        textwrap.dedent(
            """\
            import pathlib


            class Problem:
                def __init__(self, rootdir: pathlib.Path, basedir: pathlib.Path):
                    self.rootdir = rootdir
                    self.basedir = basedir

                def problem_version(self) -> str:
                    return "version-of-" + self.basedir.name
            """
        )
    )
    return repo_path


@pytest.mark.allow_mkdir
def test_library_checker_testdata_hash(
    library_checker_repo: pathlib.Path,
    mocker: MockerFixture,
):
    update = mocker.patch.object(LibraryCheckerProblem, "update_cloned_repository")
    problem = LibraryCheckerProblem(problem_id="aplusb")
    assert problem.testdata_hash() == "version-of-aplusb"
    update.assert_called_once_with()


@pytest.mark.allow_mkdir
def test_library_checker_testdata_hash_update_failure(
    library_checker_repo: pathlib.Path,
    mocker: MockerFixture,
):
    mocker.patch.object(
        LibraryCheckerProblem,
        "update_cloned_repository",
        side_effect=subprocess.CalledProcessError(128, "git"),
    )
    problem = LibraryCheckerProblem(problem_id="aplusb")
    assert problem.testdata_hash() is None


@pytest.mark.allow_mkdir
def test_library_checker_testdata_hash_script_failure(
    library_checker_repo: pathlib.Path,
    mocker: MockerFixture,
):
    mocker.patch.object(LibraryCheckerProblem, "update_cloned_repository")
    (library_checker_repo / "generate.py").unlink()
    problem = LibraryCheckerProblem(problem_id="aplusb")
    assert problem.testdata_hash() is None
