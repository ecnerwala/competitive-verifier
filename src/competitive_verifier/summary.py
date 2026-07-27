# The file is inspired by Tyrrrz/GitHubActionsTestLogger
# https://github.com/Tyrrrz/GitHubActionsTestLogger/blob/04fe7796a047dbd0e3cd6a46339b2a50f5125317/GitHubActionsTestLogger/TestSummary.cs

# ruff: noqa: PLR2004

import html
import os
import pathlib
from collections import Counter
from itertools import chain
from typing import IO

from competitive_verifier.models import (
    FileResult,
    JudgeStatus,
    ResultStatus,
    TestcaseResult,
    VerifyCommandResult,
)

SUCCESS = ResultStatus.SUCCESS
FAILURE = ResultStatus.FAILURE
SKIPPED = ResultStatus.SKIPPED


def to_human_str_seconds(total_seconds: float) -> str:
    hours = int(total_seconds // 3600)
    rm = total_seconds % 3600
    minutes = int(rm // 60)
    rm %= 60
    seconds = rm

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {int(seconds)}s"
    if total_seconds >= 10:
        return f"{int(seconds)}s"
    if total_seconds > 1:
        return f"{total_seconds:.1f}s"
    return f"{int(total_seconds * 1000)}ms"


def to_human_str_mega_bytes(total_mega_bytes: float) -> str:
    if total_mega_bytes < 0.001:
        return "0MB"
    if total_mega_bytes < 100:
        return f"{total_mega_bytes:.3g}MB"
    return f"{int(total_mega_bytes)}MB"


class TableWriter:
    def __init__(self, fp: IO[str], header: list[str]) -> None:
        self.size = len(header)
        self.fp = fp
        self.write_table_line(*header)

    def write_table_line(self, *cells: str) -> None:
        fp = self.fp
        for c in cells:
            fp.write("|")
            fp.write(c)
        fp.write("|\n")

    def write_table_file_result(
        self,
        results: list[tuple[pathlib.Path, FileResult]],
        environments: list[str | None],
    ) -> None:
        for p, fr in results:
            self.write_table_line(*_file_result_cells(p, fr, environments))


def _file_result_cells(
    p: pathlib.Path,
    fr: FileResult,
    environments: list[str | None],
) -> list[str]:
    counter = Counter(r.status for r in fr.verifications)
    if counter.get(FAILURE):
        emoji_status = "❌"
    elif counter.get(SKIPPED):
        emoji_status = "⚠"
    else:
        emoji_status = "✔"
    cells = [
        _with_icon(emoji_status, p.as_posix()),
        str(counter.get(SUCCESS, "-")),
        str(counter.get(FAILURE, "-")),
        str(counter.get(SKIPPED, "-")),
        str(sum(counter.values())),
    ]
    for env in environments:
        vs = [v for v in fr.verifications if v.verification_name == env]
        slowest = max(
            (v.slowest for v in vs if v.slowest is not None),
            default=None,
        )
        heaviest = max(
            (v.heaviest for v in vs if v.heaviest is not None),
            default=None,
        )
        cells += [
            to_human_str_seconds(sum(v.elapsed for v in vs)) if vs else "-",
            "-" if slowest is None else to_human_str_seconds(slowest),
            "-" if heaviest is None else to_human_str_mega_bytes(heaviest),
        ]
    return cells


_COMMON_HEADER = [
    "📝&nbsp;&nbsp;File",
    "✔<br>Passed",
    "❌<br>Failed",
    "⚠<br>Skipped",
    "∑<br>Total",
]


class HtmlTableWriter:
    """Table with one timing column group per environment.

    Raw HTML (rendered by both GitHub step summaries and comments) because
    the per-environment superheadings need colspan/rowspan, which markdown
    tables cannot express.
    """

    def __init__(self, fp: IO[str], environments: list[str | None]) -> None:
        self.fp = fp
        self.environments = environments
        fp.write("<table>\n<thead>\n<tr>")
        for i, h in enumerate(_COMMON_HEADER):
            align = ' align="left"' if i == 0 else ""
            fp.write(f'<th rowspan="2"{align}>{h}</th>')
        for env in environments:
            label = html.escape(env) if env is not None else ""
            fp.write(f'<th colspan="3">{label}</th>')
        fp.write("</tr>\n<tr>")
        for _ in environments:
            fp.write(
                "<th>⏳<br>Elapsed</th><th>🦥<br>Slowest</th><th>🐘<br>Heaviest</th>"
            )
        fp.write("</tr>\n</thead>\n<tbody>\n")

    def write_row(self, *cells: str) -> None:
        fp = self.fp
        fp.write("<tr>")
        for i, c in enumerate(cells):
            align = ' align="left"' if i == 0 else ' align="center"'
            fp.write(f"<td{align}>{c}</td>")
        fp.write("</tr>\n")

    def write_file_results(
        self, results: list[tuple[pathlib.Path, FileResult]]
    ) -> None:
        for p, fr in results:
            self.write_row(*_file_result_cells(p, fr, self.environments))

    def close(self) -> None:
        self.fp.write("</tbody>\n</table>\n\n")


def write_summary(fp: IO[str], result: VerifyCommandResult):
    file_results: list[tuple[pathlib.Path, FileResult]] = []
    past_results: list[tuple[pathlib.Path, FileResult]] = []
    for p, fr in result.files.items():
        if fr.newest:
            file_results.append((p, fr))
        else:
            past_results.append((p, fr))

    file_results.sort(key=lambda t: t[0])
    past_results.sort(key=lambda t: t[0])
    counter = Counter(
        r.status for r in chain.from_iterable(f[1].verifications for f in file_results)
    )

    fp.write("# ")

    if counter.get(FAILURE):
        emoji_status = "❌"
    elif counter.get(SKIPPED):
        emoji_status = "⚠"
    else:
        emoji_status = "✔"

    fp.write(emoji_status)
    fp.write(" ")
    fp.write(os.getenv("COMPETITIVE_VERIFY_SUMMARY_TITLE", "Verification result"))
    fp.write("\n\n")

    fp.write("- ")
    fp.write(_with_icon("✔", "All test case results are `success`"))
    fp.write("\n")
    fp.write("- ")
    fp.write(_with_icon("❌", "Test case results containts `failure`"))
    fp.write("\n")
    fp.write("- ")
    fp.write(_with_icon("⚠", "Test case results containts `skipped`"))
    fp.write("\n\n\n")

    # One Elapsed/Slowest/Heaviest column group per verification environment,
    # so environments with different performance characteristics (e.g. a
    # sanitizer environment vs. a plain benchmark environment) get separate
    # timing columns. Unnamed verifications form their own unlabeled group.
    # A single unnamed group keeps the plain markdown layout; otherwise the
    # table is HTML with an environment superheading over each column group.
    names = {
        v.verification_name
        for _, fr in chain(file_results, past_results)
        for v in fr.verifications
    }
    environments: list[str | None] = [*sorted(n for n in names if n is not None)]
    if None in names or not environments:
        environments.append(None)

    if environments == [None]:
        _write_markdown_tables(fp, result, counter, file_results, past_results)
    else:
        _write_env_tables(fp, counter, file_results, past_results, environments)

    if counter.get(FAILURE):
        first_failure = True
        for p, fr in file_results:
            cases = [
                DisplayTestcaseResult(
                    environment=v.verification_name, **(c.model_dump())
                )
                for v in fr.verifications
                for c in (v.testcases or [])
                if c.status != JudgeStatus.AC
            ]
            if not cases:
                continue
            if first_failure:
                fp.write("## Failed tests\n\n")
                first_failure = False
            fp.write(f"### {p.as_posix()}\n\n")

            etb = TableWriter(fp, ["env", "name", "status", "Elapsed", "Memory"])
            etb.write_table_line(*[":---"] * 2 + [":---:"] * 3)

            for c in cases:
                etb.write_table_line(
                    c.environment or "",
                    c.name,
                    c.status.name,
                    c.elapsed_str,
                    c.memory_str,
                )


def _write_markdown_tables(
    fp: IO[str],
    result: VerifyCommandResult,
    counter: "Counter[ResultStatus]",
    file_results: list[tuple[pathlib.Path, FileResult]],
    past_results: list[tuple[pathlib.Path, FileResult]],
) -> None:
    header = [
        *_COMMON_HEADER,
        "⏳<br>Elapsed",
        "🦥<br>Slowest",
        "🐘<br>Heaviest",
    ]
    alignment = [":---"] + [":---:"] * (len(header) - 1)

    if file_results:
        fp.write("## Results\n")
        tb = TableWriter(fp, header)
        tb.write_table_line(*alignment)
        tb.write_table_line(
            "_**Sum**_",
            str(counter.get(SUCCESS, "-")),
            str(counter.get(FAILURE, "-")),
            str(counter.get(SKIPPED, "-")),
            str(sum(counter.values())),
            to_human_str_seconds(result.total_seconds),
            "-",
            "-",
        )
        tb.write_table_line(*[""] * len(header))
        tb.write_table_file_result(file_results, [None])

    if past_results:
        fp.write("## Past results\n")
        tb = TableWriter(fp, header)
        tb.write_table_line(*alignment)
        tb.write_table_file_result(past_results, [None])


def _write_env_tables(
    fp: IO[str],
    counter: "Counter[ResultStatus]",
    file_results: list[tuple[pathlib.Path, FileResult]],
    past_results: list[tuple[pathlib.Path, FileResult]],
    environments: list[str | None],
) -> None:
    if file_results:
        fp.write("## Results\n\n")
        tb = HtmlTableWriter(fp, environments)
        sum_cells = [
            "<b><i>Sum</i></b>",
            str(counter.get(SUCCESS, "-")),
            str(counter.get(FAILURE, "-")),
            str(counter.get(SKIPPED, "-")),
            str(sum(counter.values())),
        ]
        for env in environments:
            elapsed = sum(
                v.elapsed
                for _, fr in file_results
                for v in fr.verifications
                if v.verification_name == env
            )
            sum_cells += [to_human_str_seconds(elapsed), "-", "-"]
        tb.write_row(*sum_cells)
        tb.write_file_results(file_results)
        tb.close()

    if past_results:
        fp.write("## Past results\n\n")
        tb = HtmlTableWriter(fp, environments)
        tb.write_file_results(past_results)
        tb.close()


def _with_icon(icon: str, text: str) -> str:
    return icon + "&nbsp;&nbsp;" + text


class DisplayTestcaseResult(TestcaseResult):
    environment: str | None

    @property
    def elapsed_str(self):
        return to_human_str_seconds(self.elapsed)

    @property
    def memory_str(self):
        return to_human_str_mega_bytes(self.memory) if self.memory else "-"
