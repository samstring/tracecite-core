#!/usr/bin/env python3
"""Check the TraceCite persisted-schema compatibility registry.

The command emits a deterministic JSON report so local checks and CI consume
the same result.  It intentionally adds the selected checkout's ``src``
directory to ``sys.path`` rather than requiring an installed package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the TraceCite schema compatibility registry and fixtures"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"repository root does not exist: {root}")
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from tracecite.runtime.schema_compat import compatibility_report

    report = compatibility_report(root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised by CLI tests
    raise SystemExit(main())
