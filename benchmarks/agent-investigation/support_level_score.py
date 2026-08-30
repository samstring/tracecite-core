from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tracecite.support_scoring import apply_support_levels, self_test


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compatibility helper only. Canonical root-cause scoring now applies support levels inside tracecite.root_cause_benchmarking."
    )
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--answer", type=Path)
    parser.add_argument("--score", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print(json.dumps({"status": "ok"}))
        return 0
    if args.gold is None or args.answer is None or args.score is None:
        parser.error("--gold, --answer and --score are required unless --self-test is used")
    updated = apply_support_levels(
        _read_json(args.score),
        _read_json(args.gold),
        args.answer.read_text(encoding="utf-8", errors="replace"),
    )
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
