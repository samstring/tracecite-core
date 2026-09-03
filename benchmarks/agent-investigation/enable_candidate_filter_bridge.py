from __future__ import annotations

from pathlib import Path


BRIDGE = Path("benchmarks/agent-investigation/pi_tracecite_bridge.py")
MARKER = "from tracecite.runtime.repeated_evidence import attach_matched_existing_evidence\n"
PATCH = r'''
from tracecite.runtime import tools as _runtime_tools
from tracecite.runtime.candidate_filter import CandidateFilterUnsupported, filter_literal_single_line
import os as _candidate_os
import time as _candidate_time
import json as _candidate_json

_LEGACY_FILTER_TEXT = _runtime_tools.filter_text


def _candidate_filter_text(*args, **kwargs):
    started = _candidate_time.perf_counter()
    mode = "candidate"
    reason = ""
    try:
        result = filter_literal_single_line(*args, **kwargs)
    except CandidateFilterUnsupported as exc:
        mode = "legacy_fallback"
        reason = str(exc)
        result = _LEGACY_FILTER_TEXT(*args, **kwargs)
    activity = _candidate_os.environ.get("TRACECITE_CANDIDATE_FILTER_ACTIVITY")
    if activity:
        row = {
            "mode": mode,
            "reason": reason,
            "seconds": round(_candidate_time.perf_counter() - started, 6),
            "source": str(args[0] if args else kwargs.get("input_path") or ""),
            "pattern": str(kwargs.get("pattern") or "")[:200],
            "match_records": int(getattr(result, "match_records", 0) or 0),
        }
        with open(activity, "a", encoding="utf-8") as handle:
            handle.write(_candidate_json.dumps(row, ensure_ascii=False) + "\n")
    return result


_runtime_tools.filter_text = _candidate_filter_text
'''


def main() -> int:
    text = BRIDGE.read_text(encoding="utf-8")
    if "_runtime_tools.filter_text = _candidate_filter_text" in text:
        print("candidate filter bridge patch already enabled")
        return 0
    if MARKER not in text:
        raise SystemExit("bridge import marker not found")
    BRIDGE.write_text(text.replace(MARKER, MARKER + PATCH, 1), encoding="utf-8")
    print("enabled candidate filter bridge patch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
