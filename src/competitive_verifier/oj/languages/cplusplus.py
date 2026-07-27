import os
import pathlib
import platform
import shlex
import shutil
import subprocess
from logging import getLogger
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from competitive_verifier.exec import command_stdout, exec_command
from competitive_verifier.log import GitHubMessageParams

from . import special_comments
from .base import Language, LanguageEnvironment, OjVerifyLanguageConfig
from .cplusplus_bundle import Bundler
from .cplusplus_minify import minify

# ruff: noqa: N803

logger = getLogger(__name__)


class OjVerifyCPlusPlusConfigEnv(BaseModel):
    CXX: str
    CXXFLAGS: list[str] | None = None


class OjVerifyCPlusPlusConfig(OjVerifyLanguageConfig):
    read_macros: bool = True
    environments: list[OjVerifyCPlusPlusConfigEnv] | None = None


class CPlusPlusLanguageEnvironment(LanguageEnvironment):
    cxx: pathlib.Path
    cxx_flags: list[str]

    def __init__(self, *, CXX: pathlib.Path, CXXFLAGS: list[str]):
        self.cxx = CXX
        self.cxx_flags = CXXFLAGS

    @property
    def name(self) -> str:
        return self.cxx.name

    def get_compile_command(
        self, path: pathlib.Path, *, basedir: pathlib.Path, tempdir: pathlib.Path
    ) -> list[str]:
        return [
            str(self.cxx),
            *self.cxx_flags,
            "-I",
            str(basedir),
            "-o",
            str(tempdir / "a.out"),
            str(path),
        ]

    def get_execute_command(
        self, path: pathlib.Path, *, basedir: pathlib.Path, tempdir: pathlib.Path
    ) -> str:
        return str(tempdir / "a.out")

    def is_clang(self) -> bool:
        return "clang++" in self.cxx.name

    def is_gcc(self) -> bool:
        return not self.is_clang() and "g++" in self.cxx.name


def _cplusplus_list_depending_files(
    path: pathlib.Path,
    *,
    CXX: pathlib.Path,
    CXXFLAGS: list[str],
) -> list[pathlib.Path]:
    is_windows = platform.uname().system == "Windows"
    command = [str(CXX), *CXXFLAGS, "-MM", str(path)]
    try:
        data = command_stdout(command)
    except Exception:
        logger.exception(
            "failed to analyze dependencies with %s: %s  (hint: Please check #include directives of the file and its dependencies."
            " The paths must exist, must not contain '\\', and must be case-sensitive.)",
            CXX,
            path,
            exc_info=False,
        )
        raise
    logger.debug("dependencies of %s: %r", path, data)
    makefile_rule = shlex.split(
        data.strip().replace("\\\n", "").replace("\\\r\n", ""),
        posix=not is_windows,
    )
    return [pathlib.Path(path).resolve() for path in makefile_rule[1:]]


def _cplusplus_list_defined_macros(
    path: pathlib.Path, *, CXX: pathlib.Path, CXXFLAGS: list[str]
) -> dict[str, str]:
    command = [str(CXX), *CXXFLAGS, "-dM", "-E", str(path)]
    data = command_stdout(command)
    define: dict[str, str] = {}
    for line in data.splitlines():
        assert line.startswith("#define ")
        a, _, b = line[len("#define ") :].partition(" ")
        if (b.startswith('"') and b.endswith('"')) or (
            b.startswith("'") and b.endswith("'")
        ):
            b = b[1:-1]
        define[a] = b
    return define


def _search_dirs(*, CXX: pathlib.Path, CXXFLAGS: list[str]) -> list[str]:
    """Include search directories reported by ``$CXX -E -v``."""
    command = [str(CXX), *CXXFLAGS, "-E", "-x", "c++", "-v", os.devnull]
    result = exec_command(command, text=True, capture_output=True)
    dirs: list[str] = []
    collecting = False
    for line in result.stderr.splitlines():
        if line in (
            '#include "..." search starts here:',
            "#include <...> search starts here:",
        ):
            collecting = True
        elif line == "End of search list.":
            break
        elif collecting and line.startswith(" "):
            dirs.append(line.removeprefix(" "))
    return dirs


def _cplusplus_list_include_directories(
    *, CXX: pathlib.Path, CXXFLAGS: list[str]
) -> list[pathlib.Path]:
    """Include search directories that the configured flags add.

    Asks the preprocessor for its search list with and without the flags and
    takes the difference, so every directory option (``-I``, ``-iquote``,
    ``-isystem``, ``-idirafter``, ...) is interpreted by the compiler itself.
    """
    try:
        with_flags = _search_dirs(CXX=CXX, CXXFLAGS=CXXFLAGS)
        default = set(_search_dirs(CXX=CXX, CXXFLAGS=[]))
    except (OSError, subprocess.SubprocessError):
        logger.warning("Failed to query include directories from %s", CXX)
        return []
    # The compiler echoes each directory as given; resolve them against the
    # process cwd, like the paths returned by _cplusplus_list_depending_files.
    return [pathlib.Path(d).resolve() for d in with_flags if d not in default]


_NOT_SPECIAL_COMMENTS = "*NOT_SPECIAL_COMMENTS*"
_PROBLEM = "PROBLEM"
_IGNORE = "IGNORE"
_IGNORE_IF_CLANG = "IGNORE_IF_CLANG"
_IGNORE_IF_GCC = "IGNORE_IF_GCC"
_ERROR = "ERROR"
_STANDALONE = "STANDALONE"


class CPlusPlusLanguage(Language):
    config: OjVerifyCPlusPlusConfig = Field(default_factory=OjVerifyCPlusPlusConfig)
    _include_directories_cache: dict[pathlib.Path, list[pathlib.Path]] = PrivateAttr(
        default_factory=dict[pathlib.Path, list[pathlib.Path]]
    )

    def _list_environments(self) -> list[CPlusPlusLanguageEnvironment]:
        default_CXXFLAGS = ["--std=c++17", "-O2", "-Wall", "-g"]  # noqa: N806
        if platform.system() == "Windows" or "CYGWIN" in platform.system():
            default_CXXFLAGS.append("-Wl,-stack,0x10000000")
        if platform.system() == "Darwin":
            default_CXXFLAGS.append("-Wl,-stack_size,0x10000000")
        if (
            platform.uname().system == "Linux"
            and "Microsoft" in platform.uname().release
        ):
            default_CXXFLAGS.append("-fsplit-stack")

        if "CXXFLAGS" in os.environ and not self.config.environments:
            logger.warning(
                "Usage of $CXXFLAGS envvar to specify options is deprecated and will be removed soon",
                extra={"github": GitHubMessageParams()},
            )
            default_CXXFLAGS = shlex.split(os.environ["CXXFLAGS"])  # noqa: N806

        envs: list[CPlusPlusLanguageEnvironment] = []
        if self.config.environments:
            # configured: use specified CXX & CXXFLAGS
            envs.extend(
                CPlusPlusLanguageEnvironment(
                    CXX=pathlib.Path(env.CXX),
                    CXXFLAGS=env.CXXFLAGS or default_CXXFLAGS,
                )
                for env in self.config.environments
            )

        elif "CXX" in os.environ:
            # old-style: 以前は $CXX を使ってたけど設定ファイルに移行したい
            logger.warning(
                "Usage of $CXX envvar to restrict compilers is deprecated and will be removed soon",
                extra={"github": GitHubMessageParams()},
            )
            envs.append(
                CPlusPlusLanguageEnvironment(
                    CXX=pathlib.Path(os.environ["CXX"]), CXXFLAGS=default_CXXFLAGS
                )
            )

        else:
            # default: use found compilers
            for name in ("g++", "clang++"):
                path = shutil.which(name)
                if path is not None:
                    envs.append(
                        CPlusPlusLanguageEnvironment(
                            CXX=pathlib.Path(path), CXXFLAGS=default_CXXFLAGS
                        )
                    )

        if not envs:
            raise RuntimeError("No C++ compilers found")
        return envs

    def list_attributes(
        self, path: pathlib.Path, *, basedir: pathlib.Path
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {}

        comments = special_comments.list_special_comments(path.resolve())
        if comments:
            attributes.update(comments)
        elif self.config.read_macros:
            # use old-style if special comments not found
            # #define PROBLEM "https://..." の形式は複数 environments との相性がよくない。あと遅い
            attributes[_NOT_SPECIAL_COMMENTS] = ""
            all_ignored = True
            for env in self._list_environments():
                macros = _cplusplus_list_defined_macros(
                    path.resolve(),
                    CXX=env.cxx,
                    CXXFLAGS=[*env.cxx_flags, "-I", str(basedir)],
                )

                # convert macros to attributes
                if _IGNORE not in macros:
                    if _STANDALONE in macros:
                        attributes[_STANDALONE] = ""

                    for key in [_PROBLEM, _ERROR]:
                        if all_ignored:
                            # the first non-ignored environment
                            if key in macros:
                                attributes[key] = macros[key]
                        else:
                            assert attributes.get(key) == macros.get(key)
                    all_ignored = False
                elif env.is_gcc():
                    attributes[_IGNORE_IF_GCC] = ""
                elif env.is_clang():
                    attributes[_IGNORE_IF_CLANG] = ""
                else:
                    attributes[_IGNORE] = ""
            if all_ignored:
                attributes[_IGNORE] = ""

        attributes.setdefault("links", [])
        attributes["links"].extend(special_comments.list_embedded_urls(path))
        return attributes

    def list_dependencies(
        self, path: pathlib.Path, *, basedir: pathlib.Path
    ) -> list[pathlib.Path]:
        env = self._list_environments()[0]
        return _cplusplus_list_depending_files(
            path.resolve(),
            CXX=env.cxx,
            CXXFLAGS=[*env.cxx_flags, "-I", str(basedir)],
        )

    def _include_directories(self, basedir: pathlib.Path) -> list[pathlib.Path]:
        cached = self._include_directories_cache.get(basedir)
        if cached is None:
            env = self._list_environments()[0]
            # Mirror the verification compile command, which appends -I basedir.
            cached = _cplusplus_list_include_directories(
                CXX=env.cxx,
                CXXFLAGS=[*env.cxx_flags, "-I", str(basedir)],
            ) or [basedir]
            self._include_directories_cache[basedir] = cached
        return cached

    def bundle(self, path: pathlib.Path, *, basedir: pathlib.Path) -> bytes | None:
        bundler = Bundler(iquotes=self._include_directories(basedir))
        bundler.update(path)
        return bundler.get()

    def minify_bundled(self, bundled_code: bytes) -> bytes | None:
        return minify(bundled_code)

    def list_environments(
        self, path: pathlib.Path, *, basedir: pathlib.Path
    ) -> list[CPlusPlusLanguageEnvironment]:
        attributes = self.list_attributes(path, basedir=basedir)
        envs: list[CPlusPlusLanguageEnvironment] = []
        for env in self._list_environments():
            if env.is_gcc() and _IGNORE_IF_GCC in attributes:
                continue
            if env.is_clang() and _IGNORE_IF_CLANG in attributes:
                continue
            envs.append(env)
        return envs
