"""Agent-facing compatibility rewrites layered above canonical Evidence Shell.

These rewrites never execute a host shell.  They only recognize familiar,
read-only query shapes that are mechanically equivalent to canonical TraceCite
Record-pipeline stages, then hand the rewritten program to the existing
Evidence Shell compatibility/parser layer.
"""

from __future__ import annotations

import re
import shlex


def _pipeline_tokens(program: str) -> list[list[str]]:
    lexer = shlex.shlex(program, posix=True, punctuation_chars="|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        raise ValueError("empty evidence shell program")
    stages: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not stages[-1]:
                raise ValueError("empty evidence shell stage")
            stages.append([])
        else:
            stages[-1].append(token)
    if not stages[-1]:
        raise ValueError("empty evidence shell stage")
    return stages


def _head_count(tokens: list[str]) -> int | None:
    if not tokens or tokens[0].lower() not in {"head", "take", "first"}:
        return None
    args = tokens[1:]
    raw: str | None = None
    if len(args) == 1:
        raw = args[0][1:] if args[0].startswith("-") else args[0]
    elif len(args) == 2 and args[0] in {"-n", "--lines"}:
        raw = args[1]
    if raw is None or not raw.isdigit() or int(raw) < 1:
        return None
    return int(raw)


def _jq_projection(tokens: list[str]) -> str | None:
    if not tokens or tokens[0].lower() != "jq":
        return None
    values = list(tokens[1:])
    while values and values[0] in {"-r", "--raw-output", "-c", "--compact-output"}:
        values.pop(0)
    if len(values) != 1:
        return None
    expression = values[0].strip()
    if not re.fullmatch(r"\.[A-Za-z_][A-Za-z0-9_.-]*", expression):
        return None
    return expression[1:]


def _jq_test_filter(tokens: list[str]) -> list[str] | None:
    if not tokens or tokens[0].lower() != "jq":
        return None
    values = list(tokens[1:])
    while values and values[0] in {"-r", "--raw-output", "-c", "--compact-output"}:
        values.pop(0)
    if len(values) != 1:
        return None
    expression = values[0].strip()
    match = re.fullmatch(
        r"select\(\.([A-Za-z_][A-Za-z0-9_.-]*)\s*\|\s*test\((['\"])(.*?)\2\)\)",
        expression,
    )
    if match is None:
        return None
    return ["where", match.group(1), "matches", match.group(3)]


def _sort_for_field(tokens: list[str], field: str) -> list[str] | None:
    if not tokens or tokens[0].lower() != "sort":
        return None
    args = list(tokens[1:])
    if not args:
        return ["sort", field, "asc"]
    if args[0].startswith("-"):
        reverse = False
        numeric = False
        for token in args:
            if not token.startswith("-"):
                return None
            for char in token[1:]:
                if char == "r":
                    reverse = True
                elif char == "n":
                    numeric = True
                else:
                    return None
        result = ["sort", field, "desc" if reverse else "asc"]
        if numeric:
            result.append("numeric")
        return result

    if args[0] != field:
        return None
    direction = args[1].lower() if len(args) > 1 else "asc"
    if direction not in {"asc", "desc"}:
        return None
    result = ["sort", field, direction]
    if len(args) > 2:
        if len(args) != 3 or args[2].lower() != "numeric":
            return None
        result.append("numeric")
    return result


def _is_count_stage(tokens: list[str]) -> bool:
    if not tokens:
        return False
    command = tokens[0].lower()
    if command in {"grep", "rg"}:
        return any(
            token == "--count" or (token.startswith("-") and not token.startswith("--") and "c" in token[1:])
            for token in tokens[1:]
        )
    return command == "wc" and tokens[1:] in (["-l"], ["--lines"])


def normalize_agent_evidence_shell_program(program: str) -> str:
    """Rewrite common Agent-authored pipelines before canonical normalization."""

    stages = _pipeline_tokens(program)

    # jq select(.FIELD | test("REGEX")) is a direct structured regex predicate.
    replaced: list[list[str]] = []
    for stage in stages:
        jq_filter = _jq_test_filter(stage)
        replaced.append(jq_filter if jq_filter is not None else stage)
    stages = replaced

    # Projection followed by sort/selection is mechanically equivalent to
    # sorting/selecting records first and projecting the selected field last.
    # This keeps project terminal without forcing Agents to learn that detail.
    index = 0
    while index + 2 < len(stages):
        field: str | None = None
        if stages[index][0].lower() == "project" and len(stages[index]) == 2:
            field = stages[index][1]
        else:
            field = _jq_projection(stages[index])
        if field is None:
            index += 1
            continue
        sort_stage = _sort_for_field(stages[index + 1], field)
        limit = _head_count(stages[index + 2])
        if sort_stage is None or limit is None:
            index += 1
            continue
        stages[index : index + 3] = [
            sort_stage,
            ["head", str(limit)],
            ["project", field],
        ]
        index += 3

    # A scalar count piped through head/take/first is unchanged by that stage.
    # Accept the familiar spelling instead of returning a terminal-aggregate error.
    index = 0
    while index + 1 < len(stages):
        if _is_count_stage(stages[index]) and _head_count(stages[index + 1]) is not None:
            del stages[index + 1]
            continue
        index += 1

    return " | ".join(shlex.join(stage) for stage in stages)


__all__ = ["normalize_agent_evidence_shell_program"]
