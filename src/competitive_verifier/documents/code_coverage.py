"""Parse code coverage data (gcovr JSON format) for documentation pages."""

import pathlib
from logging import getLogger

from pydantic import BaseModel, ConfigDict, Field

from .render_data import CoverageCount, CoverageMetric, PageCoverage

logger = getLogger(__name__)


class _GcovrBranch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int = 0


class _GcovrLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_number: int
    count: int = 0
    branches: list[_GcovrBranch] = Field(default_factory=list["_GcovrBranch"])
    noncode: bool = Field(default=False, alias="gcovr/noncode")
    excluded: bool = Field(default=False, alias="gcovr/excluded")


class _GcovrFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    execution_count: int = 0
    excluded: bool = Field(default=False, alias="gcovr/excluded")


class _GcovrFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file: pathlib.Path
    lines: list[_GcovrLine]
    functions: list[_GcovrFunction] = Field(default_factory=list["_GcovrFunction"])


class _GcovrReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    files: list[_GcovrFile]


def _metric(covered: int, excluded: int, total: int) -> CoverageMetric:
    return CoverageMetric(
        covered=covered,
        excluded=excluded,
        total=total,
        rate=covered / total if total else 1.0,
    )


def _parse_file(f: _GcovrFile) -> PageCoverage:
    line_counts: dict[int, CoverageCount] = {}
    excluded_lines: set[int] = set()
    branches_covered = branches_excluded = branches_total = 0
    for line in f.lines:
        if line.noncode:
            continue
        n = line.line_number
        if line.excluded:
            excluded_lines.add(n)
            continue
        branch_counts = [b.count for b in line.branches]
        cur = line_counts.get(n)
        if cur is None:
            line_counts[n] = CoverageCount(
                line=n,
                count=line.count,
                branch_counts=branch_counts,
            )
        else:
            cur.count = max(cur.count, line.count)
            cur.branch_counts.extend(branch_counts)
        branches_total += len(branch_counts)
        branches_covered += sum(1 for c in branch_counts if c > 0)

    functions = [fn for fn in f.functions if not fn.excluded]
    functions_excluded = len(f.functions) - len(functions)
    functions_covered = sum(1 for fn in functions if fn.execution_count > 0)

    return PageCoverage(
        lines=_metric(
            covered=sum(1 for c in line_counts.values() if c.count > 0),
            excluded=len(excluded_lines),
            total=len(line_counts),
        ),
        functions=(
            _metric(
                covered=functions_covered,
                excluded=functions_excluded,
                total=len(functions),
            )
            if f.functions
            else None
        ),
        branches=(
            _metric(
                covered=branches_covered,
                excluded=branches_excluded,
                total=branches_total,
            )
            if branches_total
            else None
        ),
        line_counts=[line_counts[n] for n in sorted(line_counts)],
        excluded_lines=sorted(excluded_lines),
    )


def load_coverage_json(path: pathlib.Path) -> dict[pathlib.Path, PageCoverage]:
    """Load a gcovr JSON report into per-file :class:`PageCoverage`."""
    report = _GcovrReport.model_validate_json(path.read_bytes())
    result = {f.file: _parse_file(f) for f in report.files}
    logger.info("Loaded coverage for %s files from %s", len(result), path)
    return result
