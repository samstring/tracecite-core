from __future__ import annotations

import pytest

from tracecite import (
    CapabilityError,
    CapabilitySpec,
    execute_capability,
    get_capability,
    list_capabilities,
    register_capability,
)
from tracecite.extension import ExtensionAPI


def test_capability_registration_listing_and_execution() -> None:
    calls: list[dict] = []

    def executor(arguments: dict):
        calls.append(arguments)
        return {"ok": True, "echo": arguments}

    spec = CapabilitySpec(
        name="unit.echo.read",
        kind="query",
        description="Echo deterministic input for tests",
        input_schema={"type": "object"},
        safety="read",
    )
    register_capability(spec, executor)

    assert get_capability("UNIT.ECHO.READ") == spec
    assert spec in list_capabilities()
    assert execute_capability("unit.echo.read", {"value": 1}) == {
        "ok": True,
        "echo": {"value": 1},
    }
    assert calls == [{"value": 1}]


def test_live_source_and_live_action_are_denied_by_default() -> None:
    source_calls: list[dict] = []
    action_calls: list[dict] = []

    register_capability(
        CapabilitySpec(
            name="unit.live.collect",
            kind="action",
            description="Collect from a live source",
            safety="live_source",
        ),
        lambda args: source_calls.append(args) or "source-ok",
    )
    register_capability(
        CapabilitySpec(
            name="unit.live.mutate",
            kind="action",
            description="Perform a live action",
            safety="live_action",
            requires_authorization=True,
        ),
        lambda args: action_calls.append(args) or "action-ok",
    )

    with pytest.raises(CapabilityError, match="allow_live_source"):
        execute_capability("unit.live.collect")
    assert source_calls == []
    assert execute_capability(
        "unit.live.collect", allow_live_source=True
    ) == "source-ok"

    with pytest.raises(CapabilityError, match="allow_live_action"):
        execute_capability("unit.live.mutate", authorized=True)
    with pytest.raises(CapabilityError, match="authorization"):
        execute_capability("unit.live.mutate", allow_live_action=True)
    assert action_calls == []
    assert execute_capability(
        "unit.live.mutate",
        {"confirmed": True},
        allow_live_action=True,
        authorized=True,
    ) == "action-ok"


def test_extension_api_registers_capability_without_domain_import_in_runtime() -> None:
    spec = CapabilitySpec(
        name="unit.extension.inspect",
        kind="query",
        description="Extension-provided inspection capability",
    )
    ExtensionAPI().register_capability(spec, lambda args: {"args": args})

    assert get_capability("unit.extension.inspect") == spec
    assert execute_capability("unit.extension.inspect", {"x": 2}) == {
        "args": {"x": 2}
    }


def test_capability_registration_rejects_invalid_contract_and_collision() -> None:
    with pytest.raises(CapabilityError, match="dotted name"):
        CapabilitySpec(name="invalid", kind="query", description="bad")

    first = lambda args: args
    second = lambda args: args
    spec = CapabilitySpec(
        name="unit.collision.read",
        kind="query",
        description="Collision test",
    )
    register_capability(spec, first)
    with pytest.raises(CapabilityError, match="已注册"):
        register_capability(spec, second)
