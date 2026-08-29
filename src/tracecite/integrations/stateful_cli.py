"""Stateful public CLI boundary over the canonical TraceCite Runtime.

The lower-level :mod:`tracecite.integrations.cli` parser/renderer remains the
compatibility command implementation. This boundary owns the public ``tracecite``
console entrypoint and routes Agent-facing ``search`` / ``expand`` acquisition
through the typed Runtime ``retrieve()`` contract before any CLI projection.

``search --output-path`` remains an explicit legacy fallback because writing a
filtered artifact is not part of ``QueryTarget`` yet. The fallback is kept
visible and narrow instead of silently dropping the requested side effect.

The optional ``--context-id`` search argument applies Context Engine seen-state
after the Runtime-owned canonical Result has been stored in the Evidence Ledger
but before compact transport rendering. Context optimization is selected only
when it is strictly smaller than the ordinary compact view.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget, retrieve

from . import cli
from .agent_projection import prefer_smaller_agent_view
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


def _prefer_for_transport(
    candidate: dict,
    fallback: dict,
    *,
    profile_name: str,
) -> dict:
    if profile_name == "frame":
        if len(cli.render_frame(candidate)) < len(cli.render_frame(fallback)):
            return candidate
        return fallback
    return prefer_smaller_agent_view(candidate, fallback)


def _canonical_payload(result: Any) -> dict[str, Any]:
    """Return Runtime-owned canonical evidence before transport projection."""

    canonical = getattr(result, "canonical_result", None)
    if not isinstance(canonical, Mapping):
        raise TypeError("retrieve() must return a RetrievalResult with canonical_result")
    return dict(canonical)


def _runtime_adapters(original_search, original_expand):
    """Build CLI-compatible adapters over typed ``retrieve()`` targets."""

    def runtime_search(
        source,
        query,
        *,
        regex=False,
        output_path=None,
        snapshot=True,
        segmenter="auto",
        last=None,
        since=None,
        until=None,
        fold=False,
        max_evidence=None,
        max_line_chars=None,
        investigation_path=None,
        hypothesis_id=None,
        test_id=None,
        cache=True,
    ):
        if output_path is not None:
            # Compatibility-only side effect. QueryTarget intentionally models
            # evidence acquisition, not writing a filtered output artifact.
            return original_search(
                source,
                query,
                regex=regex,
                output_path=output_path,
                snapshot=snapshot,
                segmenter=segmenter,
                last=last,
                since=since,
                until=until,
                fold=fold,
                max_evidence=max_evidence,
                max_line_chars=max_line_chars,
                investigation_path=investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                cache=cache,
            )
        request = EvidenceRequest(
            QueryTarget(
                source,
                query,
                regex=regex,
                snapshot=snapshot,
                segmenter=segmenter,
                last=last,
                since=since,
                until=until,
                fold=fold,
                max_evidence=max_evidence,
                max_line_chars=max_line_chars,
            ),
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            cache=cache,
        )
        return _canonical_payload(retrieve(request))

    def runtime_expand(
        source,
        start_line,
        *,
        end_line=None,
        before=3,
        after=3,
        expected_sha256=None,
        max_chars=20_000,
        investigation_path=None,
        hypothesis_id=None,
        test_id=None,
        cache=True,
    ):
        request = EvidenceRequest(
            RangeTarget(
                source,
                start_line,
                end_line=end_line,
                before=before,
                after=after,
                expected_sha256=expected_sha256,
                max_chars=max_chars,
            ),
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            cache=cache,
        )
        return _canonical_payload(retrieve(request))

    return runtime_search, runtime_expand


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str = "tracecite",
) -> int:
    """Run the public CLI through canonical Runtime retrieval semantics."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    operation = arguments[0] if arguments else "unknown"
    original_search = cli.search
    original_expand = cli.expand
    original_compact = cli._compact_search_result
    runtime_search, runtime_expand = _runtime_adapters(original_search, original_expand)

    try:
        context_id, forwarded = _take_option(arguments, "--context-id")
        cli.search = runtime_search
        cli.expand = runtime_expand

        if context_id is None:
            return cli.main(forwarded, prog=prog)
        if not _search_command(forwarded):
            raise ValueError("--context-id is only valid for search")
        ledger_dir = _read_option(forwarded, "--ledger-dir")
        if not ledger_dir:
            raise ValueError("--context-id requires --ledger-dir")
        profile_name = _read_option(forwarded, "--agent-profile") or "agent"

        def context_compact(payload, *, max_output_chars=None):
            # Compute the ordinary view first so Context optimization has a
            # same-budget baseline. The Runtime-owned canonical Result has
            # already been stored in the private Ledger at this point.
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
            return _prefer_for_transport(
                delta,
                baseline,
                profile_name=profile_name,
            )

        cli._compact_search_result = context_compact
        return cli.main(forwarded, prog=prog)
    except Exception as exc:
        payload = cli._error_payload(operation, exc)
        cli._print_payload(payload)
        return 1
    finally:
        cli.search = original_search
        cli.expand = original_expand
        cli._compact_search_result = original_compact


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
