"""Compatibility normalization for Agent-authored Evidence Shell programs.

This module deliberately does *not* execute a host shell. It accepts a familiar,
read-only subset of grep/head/tail syntax and translates it to TraceCite's
controlled Record pipeline so SourceVersion, provenance and Evidence budgets
remain authoritative.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class _GrepOptions:
    ignore_case: bool = False
    extended: bool = False
    fixed: bool = False
    invert: bool = False
    count: bool = False
    max_count: int | None = None
    patterns: tuple[str, ...] = ()


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


def _bre_to_python(pattern: str) -> str:
    r"""Translate the common GNU-BRE subset Agents naturally type to Python RE.

    The important compatibility case is escaped alternation (``foo\|bar``).
    BRE operators that require a backslash become ordinary Python operators;
    unescaped ERE-only metacharacters stay literal.
    """

    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            nxt = pattern[index + 1]
            if nxt in "|()+?{}":
                out.append(nxt)
            else:
                out.append("\\" + nxt)
            index += 2
            continue
        if char in "|()+?{}":
            out.append("\\" + char)
        else:
            out.append(char)
        index += 1
    return "".join(out)


def _parse_short_option(
    token: str,
    *,
    values: list[str],
    patterns: list[str],
    state: dict[str, object],
) -> None:
    chars = token[1:]
    index = 0
    while index < len(chars):
        char = chars[index]
        if char == "i":
            state["ignore_case"] = True
        elif char == "E":
            state["extended"] = True
        elif char == "F":
            state["fixed"] = True
        elif char == "v":
            state["invert"] = True
        elif char == "c":
            state["count"] = True
        elif char == "n":
            pass
        elif char in {"e", "m"}:
            attached = chars[index + 1 :]
            if attached:
                argument = attached
                index = len(chars)
            else:
                if not values:
                    raise ValueError(f"grep -{char} requires an argument")
                argument = values.pop(0)
                index = len(chars)
            if char == "e":
                patterns.append(argument)
            else:
                count = int(argument)
                if count < 1:
                    raise ValueError("grep -m requires a positive count")
                state["max_count"] = count
            break
        else:
            raise ValueError(
                f"unsupported grep option: -{char}; supported options are -i, -E, -F, -v, -c, -n, -e and -m"
            )
        index += 1


def _parse_grep(tokens: list[str]) -> _GrepOptions:
    values = list(tokens[1:])
    patterns: list[str] = []
    state: dict[str, object] = {
        "ignore_case": False,
        "extended": False,
        "fixed": False,
        "invert": False,
        "count": False,
        "max_count": None,
    }
    while values and values[0].startswith("-") and values[0] != "-":
        token = values.pop(0)
        if token == "--":
            break
        if token.startswith("--"):
            name, eq, attached = token.partition("=")
            if name == "--ignore-case":
                state["ignore_case"] = True
            elif name == "--extended-regexp":
                state["extended"] = True
            elif name == "--fixed-strings":
                state["fixed"] = True
            elif name == "--invert-match":
                state["invert"] = True
            elif name == "--count":
                state["count"] = True
            elif name == "--line-number":
                pass
            elif name in {"--regexp", "--max-count"}:
                if eq:
                    argument = attached
                elif values:
                    argument = values.pop(0)
                else:
                    raise ValueError(f"grep {name} requires an argument")
                if name == "--regexp":
                    patterns.append(argument)
                else:
                    count = int(argument)
                    if count < 1:
                        raise ValueError("grep --max-count requires a positive count")
                    state["max_count"] = count
            else:
                raise ValueError(
                    f"unsupported grep option: {name}; use grep/search/regex plus TraceCite pipeline stages"
                )
            continue
        _parse_short_option(token, values=values, patterns=patterns, state=state)

    if values:
        if patterns:
            raise ValueError("grep Evidence Shell does not accept file operands after -e patterns")
        patterns.append(" ".join(values))
    if not patterns:
        raise ValueError("grep requires a pattern")
    if bool(state["extended"]) and bool(state["fixed"]):
        raise ValueError("grep -E and -F cannot be combined")
    return _GrepOptions(
        ignore_case=bool(state["ignore_case"]),
        extended=bool(state["extended"]),
        fixed=bool(state["fixed"]),
        invert=bool(state["invert"]),
        count=bool(state["count"]),
        max_count=state["max_count"] if isinstance(state["max_count"], int) else None,
        patterns=tuple(patterns),
    )


def _join_regex(patterns: tuple[str, ...], *, extended: bool) -> str:
    converted = [item if extended else _bre_to_python(item) for item in patterns]
    if len(converted) == 1:
        return converted[0]
    return "|".join(f"(?:{item})" for item in converted)


def _normalize_grep(tokens: list[str]) -> tuple[list[list[str]], bool]:
    options = _parse_grep(tokens)
    stages: list[list[str]] = []
    if options.fixed:
        flags: list[str] = []
        if options.ignore_case:
            flags.append("-i")
        if options.invert:
            flags.append("-v")
        flags.append("-F")
        if len(options.patterns) == 1:
            stages.append(["grep", *flags, options.patterns[0]])
        else:
            import re

            pattern = "|".join(f"(?:{re.escape(item)})" for item in options.patterns)
            if options.ignore_case:
                pattern = f"(?i:{pattern})"
            stages.append(["exclude-regex" if options.invert else "regex", pattern])
    else:
        pattern = _join_regex(options.patterns, extended=options.extended)
        if options.ignore_case:
            pattern = f"(?i:{pattern})"
        stages.append(["exclude-regex" if options.invert else "regex", pattern])
    if options.max_count is not None:
        stages.append(["head", str(options.max_count)])
    if options.count:
        stages.append(["count"])
    return stages, options.count


def _normalize_head_tail(tokens: list[str]) -> list[str]:
    command = tokens[0].lower()
    args = list(tokens[1:])
    if len(args) == 1 and args[0].startswith("-") and args[0][1:].isdigit():
        return [command, args[0][1:]]
    if len(args) == 2 and args[0] in {"-n", "--lines"}:
        return [command, args[1]]
    if len(args) == 1 and args[0].startswith("--lines="):
        return [command, args[0].split("=", 1)[1]]
    return tokens


def normalize_evidence_shell_program(program: str) -> str:
    """Normalize familiar read-only shell spelling to canonical TraceCite stages."""

    raw_stages = _pipeline_tokens(program)
    normalized: list[list[str]] = []
    for index, tokens in enumerate(raw_stages):
        command = tokens[0].lower()
        if command == "grep":
            stages, terminal_count = _normalize_grep(tokens)
            if terminal_count and index != len(raw_stages) - 1:
                raise ValueError("grep -c/count must be terminal in Evidence Shell")
            normalized.extend(stages)
            continue
        if command in {"head", "tail"}:
            normalized.append(_normalize_head_tail(tokens))
            continue
        normalized.append(tokens)
    return " | ".join(shlex.join(stage) for stage in normalized)


__all__ = ["normalize_evidence_shell_program"]
