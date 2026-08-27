"""Stateful CLI boundary over the stable TraceCite Agent CLI.

The underlying :mod:`tracecite.integrations.cli` remains the canonical command
implementation. This wrapper recognizes the optional ``--context-id`` search
argument and applies Context Engine seen-state after the canonical Result has
been stored in the Evidence Ledger but before compact transport rendering.

Context state is always advanced, but the Agent-facing delta is used only when
its serialized compact view is strictly smaller than the ordinary compact view.
This keeps Context optimization monotonic: remembering Evidence must not make a
turn more expensive merely because delta metadata outweighs a tiny omission.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from . import cli
from .context_engine import ContextEngine


def _take_option(argv: list[str], name: str) -> tuple[str | None, list[str]]:
    """Remove one long option while supporting ``--name x`` and ``--name=x``."""

    result: list[str] = []
    value: str | None = None
    index = 0
    prefix = name + "="
    while index < len(argv):
        item = argv[index]
        if item.startswith(prefix):
            if value is not None:
                raise ValueError(f"{name} may only be provided once")
            value = item[len(prefix) :]
            if not value:
                raise ValueError(f"{name} requires a non-empty value")
            index += 1
            continue
        if item == name:
            if value is not None:
                raise ValueError(f"{name} may only be provided once")
            if index + 1 >= len(argv):
                raise ValueError(f"{name} requires a value")
            value = argv[index + 1]
            if not value or value.startswith("--"):
                raise ValueError(f"{name} requires a non-empty value")
            index += 2
            continue
        result.append(item)
        index += 1
    return value, result


def _read_option(argv: Sequence[str], name: str) -> str | None:
    prefix = name + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :] or None
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _search_command(argv: Sequence[str]) -> bool:
    return bool(argv) and argv[0] == "search"


def _smaller_agent_view(delta: dict, baseline: dict) -> dict:
    """Choose delta only when it really reduces serialized Agent context."""

    if len(cli.encoded_json(delta)) < len(cli.encoded_json(baseline)):
        return delta
    return baseline


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str = "tracecite",
) -> int:
    """Run the public CLI with optional persistent per-context Evidence deltas."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        context_id, forwarded = _take_option(arguments, "--context-id")
        if context_id is None:
            return cli.main(forwarded, prog=prog)
        if not _search_command(forwarded):
            raise ValueError("--context-id is only valid for search")
        ledger_dir = _read_option(forwarded, "--ledger-dir")
        if not ledger_dir:
            raise ValueError("--context-id requires --ledger-dir")

        original_compact = cli._compact_search_result

        def context_compact(payload, *, max_output_chars=None):
            # Compute the ordinary view first so Context optimization has a
            # same-budget baseline.  The canonical Result has already been
            # stored in the private Ledger at this point.
            baseline = original_compact(
                payload,
                max_output_chars=max_output_chars,
            )
            data = dict(payload.get("data") or {})
            result_id = str(data.get("result_id") or "")
            if not result_id:
                raise ValueError("context projection requires a stored result_id")
            projected = ContextEngine(Path(ledger_dir), context_id).project_search(
                payload,
                result_id=result_id,
            )
            delta = original_compact(
                projected,
                max_output_chars=max_output_chars,
            )
            return _smaller_agent_view(delta, baseline)

        cli._compact_search_result = context_compact
        try:
            return cli.main(forwarded, prog=prog)
        finally:
            cli._compact_search_result = original_compact
    except Exception as exc:
        payload = cli._error_payload("search", exc)
        cli._print_payload(payload)
        return 1


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
