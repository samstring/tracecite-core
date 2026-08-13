from __future__ import annotations

import re

from tracecite.runtime.runtime import ScenarioProfile
from tracecite.runtime.scenario import resolve_pattern


def test_resolve_pattern_combines_preset_and_grep_with_or() -> None:
    profile = ScenarioProfile(
        filter_presets={"system-fault": ("fatal|crash", "fault")}
    )

    pattern, tag = resolve_pattern(
        {"filter": {"preset": "system-fault", "grep": "checkout|payment"}},
        profile=profile,
    )

    matcher = re.compile(pattern)
    assert matcher.search("fatal signal")
    assert matcher.search("checkout failed")
    assert not matcher.search("application started")
    assert tag == "fault"


def test_resolve_pattern_explicit_tag_wins_when_combining() -> None:
    profile = ScenarioProfile(
        filter_presets={"system-fault": ("fatal", "fault")}
    )

    _, tag = resolve_pattern(
        {
            "filter": {
                "preset": "system-fault",
                "grep": "checkout",
                "tag": "checkout-fault",
            }
        },
        profile=profile,
    )

    assert tag == "checkout-fault"
