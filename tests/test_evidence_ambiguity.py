from tracecite.runtime.evidence_ambiguity import scoped_identity_fanout_hints


def test_reports_sibling_scope_fanout_without_causal_claim() -> None:
    text = "\n".join(
        [
            "resource.example/widget-1001 ready",
            "resource.example/widget-1002 ready",
            "resource.example/widget-1003 failed",
        ]
    )

    hints = scoped_identity_fanout_hints(text)

    fanout = next(item for item in hints if item["kind"] == "sibling_scope_fanout")
    assert fanout["scope"] == "resource.example/"
    assert fanout["family"] == "widget-*"
    assert fanout["member_count"] == 3
    assert fanout["navigation_query"] == "resource.example/widget-"


def test_reports_unverified_local_identifier_near_scoped_entity() -> None:
    text = "\n".join(
        [
            "- name: test.device/device-plugin-failures-3083",
            "  health: Healthy",
            "  resourceID: testdevice",
            "- name: test.device/device-plugin-failures-3083",
            "  health: Unhealthy",
            "  resourceID: testdevice",
        ]
    )

    hints = scoped_identity_fanout_hints(text)

    gap = next(item for item in hints if item["kind"] == "scope_uniqueness_unverified")
    assert gap["identifier_key"] == "resourceID"
    assert gap["identifier_value"] == "testdevice"
    assert gap["recommended_search"] == "testdevice"
    assert gap["recommended_action"] == {
        "operation": "search",
        "query": "testdevice",
        "purpose": "verify_identifier_uniqueness_across_scopes",
    }
    assert gap["scopes"] == ["test.device/"]
    assert "test.device/device-plugin-failures-3083" in gap["scoped_entities"]
    assert "root cause" not in gap["verification"].lower()


def test_uuid_like_identifier_does_not_trigger_scope_uniqueness_gap() -> None:
    text = "\n".join(
        [
            "worker.example/worker-1001",
            "requestID: 123e4567-e89b-12d3-a456-426614174000",
        ]
    )

    hints = scoped_identity_fanout_hints(text)

    assert not any(item["kind"] == "scope_uniqueness_unverified" for item in hints)


def test_identifier_without_nearby_scope_does_not_trigger_gap() -> None:
    text = "\n".join(
        [
            "requestID: local-17",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "worker.example/worker-1001",
        ]
    )

    hints = scoped_identity_fanout_hints(text)

    assert not any(item["kind"] == "scope_uniqueness_unverified" for item in hints)


def test_actionable_identity_gap_precedes_broader_fanout() -> None:
    text = "\n".join(
        [
            "resource.example/widget-1001",
            "resourceID: local-device",
            "resource.example/widget-1002",
            "resource.example/widget-1003",
        ]
    )

    hints = scoped_identity_fanout_hints(text, limit=1)

    assert hints[0]["kind"] == "scope_uniqueness_unverified"
