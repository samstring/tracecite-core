"""Compatibility normalization for Agent-authored Evidence Shell programs.

This module deliberately does *not* execute a host shell. It accepts familiar,
read-only Unix data-query spelling and translates it to TraceCite's controlled
Record pipeline so SourceVersion, provenance and Evidence budgets remain
authoritative.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class _SearchOptions:
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
    r"""Translate the common GNU-BRE subset Agents naturally type to Python RE."""

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
    command: str,
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
        elif char == "E" and command == "grep":
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
                    raise ValueError(f"{command} -{char} requires an argument")
                argument = values.pop(0)
                index = len(chars)
            if char == "e":
                patterns.append(argument)
            else:
                count = int(argument)
                if count < 1:
                    raise ValueError(f"{command} -m requires a positive count")
                state["max_count"] = count
            break
        else:
            supported = "-i, -E, -F, -v, -c, -n, -e and -m" if command == "grep" else "-i, -F, -v, -c, -n, -e and -m"
            raise ValueError(
                f"unsupported {command} option: -{char}; supported options are {supported}"
            )
        index += 1


def _parse_search(tokens: list[str], *, command: str) -> _SearchOptions:
    values = list(tokens[1:])
    patterns: list[str] = []
    state: dict[str, object] = {
        "ignore_case": False,
        "extended": command == "rg",
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
            elif name == "--extended-regexp" and command == "grep":
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
                    raise ValueError(f"{command} {name} requires an argument")
                if name == "--regexp":
                    patterns.append(argument)
                else:
                    count = int(argument)
                    if count < 1:
                        raise ValueError(f"{command} --max-count requires a positive count")
                    state["max_count"] = count
            else:
                raise ValueError(
                    f"unsupported {command} option: {name}; use grep/rg/search/regex plus TraceCite pipeline stages"
                )
            continue
        _parse_short_option(
            token,
            command=command,
            values=values,
            patterns=patterns,
            state=state,
        )

    if values:
        if patterns:
            raise ValueError(
                f"{command} Evidence Shell does not accept file operands after -e patterns"
            )
        patterns.append(" ".join(values))
    if not patterns:
        raise ValueError(f"{command} requires a pattern")
    if bool(state["extended"]) and bool(state["fixed"]):
        state["extended"] = False
    return _SearchOptions(
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


def _normalize_search(tokens: list[str], *, command: str) -> tuple[list[list[str]], bool]:
    options = _parse_search(tokens, command=command)
    stages: list[list[str]] = []
    if options.fixed:
        if len(options.patterns) == 1:
            flags: list[str] = ["-F"]
            if options.ignore_case:
                flags.insert(0, "-i")
            if options.invert:
                flags.insert(0, "-v")
            stages.append(["grep", *flags, options.patterns[0]])
        else:
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


def _normalize_wc(tokens: list[str]) -> list[str]:
    if tokens[1:] not in (["-l"], ["--lines"]):
        raise ValueError("Evidence Shell supports only wc -l / wc --lines")
    return ["count"]


def _normalize_sort(tokens: list[str]) -> list[str]:
    args = list(tokens[1:])
    if not args:
        return ["sort", "text", "asc"]
    if not args[0].startswith("-"):
        return tokens
    reverse = False
    numeric = False
    for token in args:
        if not token.startswith("-"):
            raise ValueError("Unix-style sort in Evidence Shell does not accept file operands")
        for char in token[1:]:
            if char == "r":
                reverse = True
            elif char == "n":
                numeric = True
            else:
                raise ValueError("supported Unix sort flags are -r, -n, -rn and -nr")
    result = ["sort", "text", "desc" if reverse else "asc"]
    if numeric:
        result.append("numeric")
    return result


def _normalize_uniq(tokens: list[str]) -> list[str]:
    args = tokens[1:]
    if not args:
        return ["distinct", "text"]
    if args == ["-c"] or args == ["--count"]:
        return ["group", "text"]
    raise ValueError("Evidence Shell supports uniq and uniq -c / uniq --count")


def _normalize_sed(tokens: list[str]) -> list[str]:
    args = list(tokens[1:])
    if len(args) != 2 or args[0] != "-n":
        raise ValueError("Evidence Shell supports sed -n 'START[,END]p'")
    match = re.fullmatch(r"([1-9][0-9]*)(?:,([1-9][0-9]*))?p", args[1])
    if match is None:
        raise ValueError("Evidence Shell supports sed -n 'START[,END]p'")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if end < start:
        raise ValueError("sed line range end must not precede start")
    return ["lines", str(start), str(end)] if end != start else ["lines", str(start)]


def _jq_field(value: str) -> str:
    text = value.strip()
    if not text.startswith(".") or not re.fullmatch(r"\.[A-Za-z_][A-Za-z0-9_.-]*", text):
        raise ValueError("simple jq projection must be a dotted field such as .statusCode")
    return text[1:]


def _jq_value(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'\"', "'"}:
        return text[1:-1]
    return text


def _normalize_jq(tokens: list[str]) -> tuple[list[list[str]], bool]:
    values = list(tokens[1:])
    while values and values[0] in {"-r", "--raw-output", "-c", "--compact-output"}:
        values.pop(0)
    if not values:
        raise ValueError("jq requires a simple select or field projection")
    expression = " ".join(values).strip()
    pieces = [piece.strip() for piece in expression.split("|") if piece.strip()]
    stages: list[list[str]] = []
    projected = False
    for piece in pieces:
        if piece.startswith("select(") and piece.endswith(")"):
            inner = piece[len("select(") : -1].strip()
            match = re.fullmatch(
                r"(\.[A-Za-z_][A-Za-z0-9_.-]*)\s*(==|!=|>=|<=|>|<)\s*(.+)",
                inner,
            )
            if match is None:
                raise ValueError("simple jq select supports .FIELD ==/!=/>/>=/</<= VALUE")
            stages.append(
                ["where", _jq_field(match.group(1)), match.group(2), _jq_value(match.group(3))]
            )
            continue
        stages.append(["project", _jq_field(piece)])
        projected = True
    return stages, projected


def normalize_evidence_shell_program(program: str) -> str:
    """Normalize familiar read-only shell spelling to canonical TraceCite stages."""

    raw_stages = _pipeline_tokens(program)
    normalized: list[list[str]] = []
    for index, tokens in enumerate(raw_stages):
        command = tokens[0].lower()
        if command in {"grep", "rg"}:
            stages, terminal_count = _normalize_search(tokens, command=command)
            if terminal_count and index != len(raw_stages) - 1:
                raise ValueError(f"{command} -c/count must be terminal in Evidence Shell")
            normalized.extend(stages)
            continue
        if command in {"head", "tail"}:
            normalized.append(_normalize_head_tail(tokens))
            continue
        if command == "wc":
            if index != len(raw_stages) - 1:
                raise ValueError("wc -l/count must be terminal in Evidence Shell")
            normalized.append(_normalize_wc(tokens))
            continue
        if command == "sort":
            normalized.append(_normalize_sort(tokens))
            continue
        if command == "uniq":
            if index != len(raw_stages) - 1:
                raise ValueError("uniq/uniq -c must be terminal in Evidence Shell")
            normalized.append(_normalize_uniq(tokens))
            continue
        if command == "sed":
            normalized.append(_normalize_sed(tokens))
            continue
        if command == "jq":
            stages, projected = _normalize_jq(tokens)
            if projected and index != len(raw_stages) - 1:
                raise ValueError("jq field projection/project must be terminal in Evidence Shell")
            normalized.extend(stages)
            continue
        normalized.append(tokens)
    return " | ".join(shlex.join(stage) for stage in normalized)


__all__ = ["normalize_evidence_shell_program"]
