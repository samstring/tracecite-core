#!/usr/bin/env python3
"""Deterministic architecture-governance checks for the TraceCite repository.

The checker intentionally uses only the Python standard library.  It scans the
repository's controlled Markdown and source trees (not arbitrary paths outside
the selected repository root) and reports all findings in stable path/line
order.  Run it from the repository root with::

    python scripts/check_architecture.py

``--root`` is provided for fixture tests and for callers that keep a checkout
in a non-current directory.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import html
from pathlib import Path
import re
import sys
from typing import Iterator, Sequence
from urllib.parse import unquote, urlsplit


SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        ".venv-inspect",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)

ADR_FILENAME_RE = re.compile(r"^[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ADR_STATUSES = frozenset({"proposed", "accepted", "superseded", "rejected"})
ADR_REQUIRED_METADATA = ("Date", "Owners", "Supersedes", "Superseded by")
ADR_REQUIRED_SECTIONS = (
    "Context",
    "Decision",
    "Alternatives considered",
    "Consequences",
    "Migration and validation",
    "Documentation updates",
)


@dataclass(frozen=True)
class Finding:
    """One stable, human-readable governance finding."""

    path: str
    message: str
    line: int | None = None

    def format(self) -> str:
        location = self.path
        if self.line is not None:
            location += f":{self.line}"
        return f"{location}: {self.message}"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_files(root: Path, suffix: str | None = None) -> Iterator[Path]:
    """Yield controlled repository files in deterministic order."""

    root = root.resolve()
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        # Do not follow repository symlinks while scanning controlled files;
        # this keeps a fixture or checkout from making the checker read an
        # arbitrary path outside ``root``.
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        if suffix is not None and path.suffix.lower() != suffix.lower():
            continue
        yield path


def _finding(root: Path, path: Path, message: str, line: int | None = None) -> Finding:
    return Finding(_relative(root, path), message, line)


def _strip_inline_code(line: str) -> str:
    """Remove inline code spans so examples are not treated as links."""

    # Markdown permits runs of backticks.  Replacing each complete span keeps
    # line numbers intact while avoiding a parser dependency.
    return re.sub(r"(`+)(?:(?!\1).)*?\1", lambda match: " " * len(match.group(0)), line)


_INLINE_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]*)>|([^\s)\n]*))",
)
_REFERENCE_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]*)>|([^\s]+))",
)
_REFERENCE_LABEL_RE = re.compile(r"^\s{0,3}\[([^\]\n]+)\]:")
_REFERENCE_USE_RE = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
_AUTOLINK_RE = re.compile(
    r"(?<![\w\"'=])<((?:\.{0,2}/|[^:<>\s]+/)[^<>\s]*|[^:<>\s]+\.md(?:#[^<>\s]*)?)>",
)


def _markdown_destinations(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line, destination)`` pairs from ordinary Markdown links.

    This deliberately handles links and reference definitions, while skipping
    fenced code blocks and inline code.  It is not intended to be a full
    Markdown renderer; the accepted syntax is the subset needed for repository
    documentation links and images.
    """

    fenced: str | None = None
    for line_number, original_line in enumerate(text.splitlines(), 1):
        stripped = original_line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)[0]
            if fenced is None:
                fenced = marker
            elif marker == fenced:
                fenced = None
            continue
        if fenced is not None:
            continue

        line = _strip_inline_code(original_line)
        for match in _INLINE_LINK_RE.finditer(line):
            destination = match.group(1) if match.group(1) is not None else match.group(2)
            yield line_number, destination or ""
        definition = _REFERENCE_DEFINITION_RE.match(line)
        if definition:
            destination = definition.group(1) if definition.group(1) is not None else definition.group(2)
            yield line_number, destination or ""
        # Markdown autolinks are only considered when they look like paths.
        # Plain HTML tags (<span>, <a>, ...) therefore remain out of scope.
        for match in _AUTOLINK_RE.finditer(line):
            yield line_number, match.group(1)


def _reference_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _markdown_reference_labels(text: str) -> set[str]:
    labels: set[str] = set()
    fenced: str | None = None
    for original_line in text.splitlines():
        stripped = original_line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)[0]
            if fenced is None:
                fenced = marker
            elif marker == fenced:
                fenced = None
            continue
        if fenced is not None:
            continue
        match = _REFERENCE_LABEL_RE.match(_strip_inline_code(original_line))
        if match:
            labels.add(_reference_label(match.group(1)))
    return labels


def _markdown_reference_uses(text: str) -> Iterator[tuple[int, str]]:
    fenced: str | None = None
    for line_number, original_line in enumerate(text.splitlines(), 1):
        stripped = original_line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)[0]
            if fenced is None:
                fenced = marker
            elif marker == fenced:
                fenced = None
            continue
        if fenced is not None:
            continue
        line = _strip_inline_code(original_line)
        for match in _REFERENCE_USE_RE.finditer(line):
            label = match.group(2) or match.group(1)
            yield line_number, _reference_label(label)


def _github_slug(value: str) -> str:
    """Generate the conventional GitHub-style slug for a Markdown heading."""

    value = html.unescape(value)
    value = re.sub(r"!?(?:\[([^\]]+)\]\([^)]*\))", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.strip().rstrip("#").strip().lower()
    value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value)


def _markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            slug = _github_slug(heading.group(1))
            if slug:
                count = seen.get(slug, 0)
                anchors.add(slug if count == 0 else f"{slug}-{count}")
                seen[slug] = count + 1
        for explicit in re.finditer(
            r"<(?:a|h[1-6])\b[^>]*(?:id|name)=[\"']([^\"']+)[\"'][^>]*>",
            line,
            flags=re.IGNORECASE,
        ):
            anchors.add(unquote(explicit.group(1)).lower())
    return anchors


def _is_external_destination(destination: str) -> bool:
    parsed = urlsplit(destination)
    return bool(parsed.scheme) or destination.startswith("//")


def check_markdown_links(root: Path) -> list[Finding]:
    """Check repository Markdown links, targets, and Markdown fragments."""

    root = root.resolve()
    findings: list[Finding] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in _iter_files(root, ".md"):
        text = source.read_text(encoding="utf-8")
        reference_labels = _markdown_reference_labels(text)
        for line, label in _markdown_reference_uses(text):
            if label not in reference_labels:
                findings.append(
                    _finding(root, source, f"reference link definition does not exist: [{label}]", line)
                )
        for line, raw_destination in _markdown_destinations(text):
            destination = raw_destination.strip()
            if not destination:
                findings.append(_finding(root, source, "Markdown link has an empty destination", line))
                continue
            if _is_external_destination(destination):
                continue
            parsed = urlsplit(destination)
            target_text = unquote(parsed.path)
            fragment = unquote(parsed.fragment).lower()
            target = source if not target_text else (source.parent / target_text)
            try:
                resolved = target.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                findings.append(
                    _finding(
                        root,
                        source,
                        f"relative link escapes repository root: {raw_destination}",
                        line,
                    )
                )
                continue
            if not resolved.exists():
                findings.append(
                    _finding(
                        root,
                        source,
                        f"relative link target does not exist: {raw_destination}",
                        line,
                    )
                )
                continue
            if fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
                if resolved not in anchor_cache:
                    try:
                        anchor_cache[resolved] = _markdown_anchors(resolved)
                    except (OSError, UnicodeError) as exc:
                        findings.append(
                            _finding(root, source, f"cannot read link target for fragment: {exc}", line)
                        )
                        continue
                if fragment not in anchor_cache[resolved]:
                    findings.append(
                        _finding(
                            root,
                            source,
                            f"Markdown link fragment does not exist: {raw_destination}",
                            line,
                        )
                    )
    return findings


def _table_rows(lines: Sequence[str], start: int) -> tuple[list[list[str]], int | None]:
    """Parse the first Markdown table after a heading.

    Returns ``([], None)`` when no table is present and otherwise the data rows
    plus the line number of the header (zero-based).
    """

    index = start + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or "|" not in lines[index]:
        return [], None
    header_index = index
    index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or "|" not in lines[index]:
        return [], None
    separator = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
    if not separator or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
        return [], None
    index += 1
    rows: list[list[str]] = []
    while index < len(lines):
        value = lines[index].strip()
        if not value:
            break
        if "|" not in value:
            break
        cells = [cell.strip() for cell in value.strip("|").split("|")]
        if len(cells) != len(separator):
            rows.append(cells)
        else:
            rows.append(cells)
        index += 1
    return rows, header_index


def _status_category(value: str) -> str | None:
    lowered = value.strip().lower()
    if re.search(r"\bpending\b|\bplanned\b|待执行|待实现|计划", lowered):
        return "pending"
    if re.search(
        r"not\s+(?:fully\s+)?implemented|partially\s+implemented|尚未|未实现|部分实现",
        lowered,
    ):
        return "partial"
    if re.search(r"implemented|已实现", lowered):
        return "implemented"
    return None


def _find_status_table(path: Path) -> tuple[list[list[str]], int | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s*#{2,6}\s+", line):
            continue
        heading = re.sub(r"^\s*#{2,6}\s+", "", line).strip().lower()
        if "implementation status" in heading or "当前实现与目标差距" in heading:
            return _table_rows(lines, index)
    return [], None


def check_implementation_status(root: Path) -> list[Finding]:
    """Ensure English/Chinese implementation-status tables have matching shape."""

    root = root.resolve()
    english = root / "docs" / "architecture.md"
    chinese = root / "docs" / "architecture.zh-CN.md"
    findings: list[Finding] = []
    tables: list[tuple[Path, list[list[str]], int | None]] = []
    for path in (english, chinese):
        if not path.is_file():
            findings.append(_finding(root, path, "required architecture document is missing"))
            continue
        rows, header = _find_status_table(path)
        if header is None:
            findings.append(_finding(root, path, "implementation-status table is missing"))
            continue
        if not rows:
            findings.append(_finding(root, path, "implementation-status table has no capability rows", header + 1))
            continue
        for offset, row in enumerate(rows):
            line = header + 3 + offset
            if len(row) < 2 or not row[0] or not row[1]:
                findings.append(_finding(root, path, "implementation-status row must have capability and status", line))
                continue
            if _status_category(row[1]) is None:
                findings.append(_finding(root, path, f"unknown implementation status category: {row[1]!r}", line))
        tables.append((path, rows, header))
    if len(tables) == 2:
        english_rows, chinese_rows = tables[0][1], tables[1][1]
        if len(english_rows) != len(chinese_rows):
            findings.append(
                _finding(
                    root,
                    english,
                    "English and Chinese implementation-status tables have different capability-row counts "
                    f"({len(english_rows)} != {len(chinese_rows)})",
                )
            )
        for index, (english_row, chinese_row) in enumerate(zip(english_rows, chinese_rows), 1):
            if len(english_row) < 2 or len(chinese_row) < 2:
                continue
            english_category = _status_category(english_row[1])
            chinese_category = _status_category(chinese_row[1])
            if english_category != chinese_category:
                findings.append(
                    _finding(
                        root,
                        chinese,
                        "implementation-status category differs from English row "
                        f"{index}: {chinese_category!r} != {english_category!r}",
                    )
                )
    return findings


def _heading_names(text: str) -> list[tuple[int, str]]:
    return [
        (index, match.group(2).strip())
        for index, line in enumerate(text.splitlines(), 1)
        if (match := re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line))
    ]


def _metadata_present(text: str, key: str) -> bool:
    return bool(re.search(rf"(?im)^\s*-\s*{re.escape(key)}\s*:", text))


def check_adrs(root: Path) -> list[Finding]:
    """Validate ADR names, metadata/status, and required template sections."""

    root = root.resolve()
    adr_dir = root / "docs" / "adr"
    if not adr_dir.exists():
        return []
    findings: list[Finding] = []
    for path in sorted(adr_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        if not ADR_FILENAME_RE.fullmatch(path.name):
            findings.append(_finding(root, path, "ADR filename must match NNNN-short-title.md"))
        text = path.read_text(encoding="utf-8")
        heading = next(((line, value) for line, value in _heading_names(text) if line == 1), None)
        if heading is None:
            findings.append(_finding(root, path, "ADR must start with a level-one title heading", 1))
        else:
            number = path.name[:4]
            if not heading[1].startswith(f"{number}:"):
                findings.append(_finding(root, path, f"ADR title must start with '{number}:'", heading[0]))
        statuses = re.findall(r"(?im)^\s*-\s*Status\s*:\s*([^\s]+)\s*$", text)
        if len(statuses) != 1:
            findings.append(_finding(root, path, "ADR must contain exactly one '- Status: ...' metadata line"))
        elif statuses[0].lower() not in ADR_STATUSES:
            findings.append(_finding(root, path, f"unknown ADR status: {statuses[0]!r}"))
        for key in ADR_REQUIRED_METADATA:
            if not _metadata_present(text, key):
                findings.append(_finding(root, path, f"ADR metadata field is missing: {key}"))
        sections = {value.casefold() for _, value in _heading_names(text) if value}
        for required in ADR_REQUIRED_SECTIONS:
            if required.casefold() not in sections:
                findings.append(_finding(root, path, f"ADR section is missing: {required}"))
    return findings


def _local_package_names(root: Path) -> set[str]:
    source_root = root / "src"
    if not source_root.is_dir():
        return set()
    names: set[str] = set()
    for path in source_root.iterdir():
        if path.is_dir() and (path / "__init__.py").is_file():
            names.add(path.name)
        elif path.is_file() and path.suffix == ".py":
            names.add(path.stem)
    return names


def _imports(path: Path) -> Iterator[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        yield 1, f"<parse error: {exc}>"
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def _is_module_or_child(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def check_dependency_direction(root: Path) -> list[Finding]:
    """Enforce Core/Runtime import direction using AST and local package layout."""

    root = root.resolve()
    core = root / "src" / "tracecite_core"
    runtime = root / "src" / "tracecite" / "runtime"
    local_packages = _local_package_names(root)
    findings: list[Finding] = []

    if core.is_dir():
        for path in _iter_files(core, ".py"):
            for line, module in _imports(path):
                if module.startswith("<parse error:"):
                    findings.append(_finding(root, path, module, line))
                    continue
                top_level = module.split(".", 1)[0]
                # Core may import itself, but never the aggregate TraceCite
                # package or any concrete package using the tracecite_* naming
                # convention.  Local source packages are also concrete by
                # definition, so they are rejected without a domain word list.
                forbidden = (
                    module == "tracecite"
                    or module.startswith("tracecite.")
                    or (module.startswith("tracecite_") and top_level != "tracecite_core")
                    or (top_level in local_packages and top_level != "tracecite_core")
                )
                if forbidden:
                    findings.append(_finding(root, path, f"Core must not import '{module}'", line))

    if runtime.is_dir():
        for path in _iter_files(runtime, ".py"):
            for line, module in _imports(path):
                if module.startswith("<parse error:"):
                    findings.append(_finding(root, path, module, line))
                    continue
                top_level = module.split(".", 1)[0]
                # Runtime can use Core and its own TraceCite layers.  Any
                # sibling source package, or any tracecite_* package, is a
                # concrete domain dependency and is prohibited.
                forbidden = (
                    (module.startswith("tracecite_") and top_level != "tracecite_core")
                    or (top_level in local_packages and top_level not in {"tracecite", "tracecite_core"})
                    or (
                        module.startswith("tracecite.")
                        and not any(
                            _is_module_or_child(module, package)
                            for package in (
                                "tracecite.runtime",
                                "tracecite.extension",
                                "tracecite.integrations",
                                "tracecite.knowledge",
                            )
                        )
                    )
                )
                if forbidden:
                    findings.append(_finding(root, path, f"Runtime must not import concrete domain '{module}'", line))
    return findings


def run_checks(root: Path | str) -> list[Finding]:
    """Run all governance checks and return findings in deterministic order."""

    root = Path(root).resolve()
    findings = [
        *check_markdown_links(root),
        *check_implementation_status(root),
        *check_adrs(root),
        *check_dependency_direction(root),
    ]
    return sorted(findings, key=lambda finding: (finding.path, finding.line or 0, finding.message))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root to inspect (default: current directory)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"error: repository root does not exist: {root}", file=sys.stderr)
        return 2
    findings = run_checks(root)
    for finding in findings:
        print(f"ERROR: {finding.format()}")
    if findings:
        print(f"architecture governance failed: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("architecture governance checks passed")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
