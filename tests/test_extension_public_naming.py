from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CURRENT_EXTENSION_SURFACES = (
    "src/tracecite/extension/__init__.py",
    "docs/extension-contract.md",
    "docs/architecture.md",
    "docs/architecture.zh-CN.md",
)


@pytest.mark.parametrize("relative_path", CURRENT_EXTENSION_SURFACES)
def test_current_extension_surfaces_do_not_present_v2_as_an_integration_mode(relative_path: str) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "Extension Protocol v2" not in text
    assert "Extension Contract v2" not in text


def test_machine_protocol_version_remains_an_internal_compatibility_field() -> None:
    from tracecite.extension import EXTENSION_PROTOCOL_VERSION, ExtensionManifest

    assert EXTENSION_PROTOCOL_VERSION == "2"
    assert ExtensionManifest(id="test", version="1", domain="test").protocol_version == "2"
