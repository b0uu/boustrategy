"""Guard the contract between the published API and the browser bundle.

The browser fixture is generated from a real publication, and the UI's tests and
its TypeScript types are both written against it. Nothing regenerated it
automatically, so a change to a public payload could leave the fixture stale, the
UI tests passing against a shape the API no longer returns, and the divergence
only visible in production. These tests make the fixture's staleness a build
failure instead.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

from app.public.server import create_public_app

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "public-ui" / "fixtures" / "public-v2.json"
GENERATOR = ROOT / "public-ui" / "fixtures" / "generate.py"
SAMPLE = ROOT / "public-ui" / "fixtures" / "contract-sample.json"
REGENERATE = "python public-ui/fixtures/generate.py"

# Routes the browser bundle reaches but that carry no JSON body worth pinning:
# an export is a file download and the legacy route redirects onto a decision.
UNFIXTURED_ROUTES = {
    "/api/public/v2/portfolios",
    "/api/public/v2/decisions/{public_id}/export",
    "/api/public/v2/legacy-decisions/{ticker}/{created_at}",
}
SCOPES = ("live", "paper")
SECTIONS = ("overview", "positions", "performance", "policy", "runtime", "activity", "feed")


def generator() -> Any:
    """Import the fixture generator by path; its directory name isn't a Python package."""
    spec = importlib.util.spec_from_file_location("public_v2_fixtures", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate() -> dict[str, Any]:
    result: dict[str, Any] = generator().generate()
    return result


def payload_shape(value: Any, path: str, into: set[str]) -> None:
    """Collect ``path:type`` pairs so shape is compared and volatile values aren't."""
    if isinstance(value, dict):
        for key in value:
            payload_shape(value[key], f"{path}.{key}" if path else key, into)
        if not value:
            into.add(f"{path}:empty_object")
    elif isinstance(value, list):
        for item in value:
            payload_shape(item, f"{path}[]", into)
        if not value:
            into.add(f"{path}:empty_array")
    else:
        into.add(f"{path}:{'null' if value is None else type(value).__name__}")


def contract(fixture: dict[str, Any]) -> set[str]:
    """Shape every route, folding the opaque-ID entries into two stable groups.

    Decision and activity detail keys are minted per publication, so they are
    merged rather than compared by name.
    """
    shape: set[str] = set()
    for key, payload in fixture.items():
        if "/" in key:
            group = key
        elif key.startswith("dec_"):
            group = "decision_detail"
        elif key.startswith("run_") or key.startswith("occ_"):
            group = "activity_detail"
        else:
            group = "unclassified:" + key
        payload_shape(payload, group, shape)
    return shape


def test_committed_browser_fixture_matches_the_current_public_api() -> None:
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))

    current = contract(generate())
    stored = contract(committed)

    missing = sorted(stored - current)
    added = sorted(current - stored)
    assert not missing and not added, (
        "The published API no longer matches the committed browser fixture, so the UI "
        f"is typed and tested against a stale shape. Run `{REGENERATE}`, review the diff, "
        "and update public-ui/src/types.ts and contract.check.ts to match.\n"
        f"no longer returned: {missing}\nnewly returned: {added}"
    )


def test_every_public_route_appears_in_the_browser_fixture() -> None:
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    app = create_public_app(":memory:")

    sections = {
        path.rsplit("/", 1)[-1]
        for route in app.routes
        if (path := str(getattr(route, "path", ""))).startswith("/api/public/v2/portfolios/{")
        and not path.endswith("}")
    }
    expected = {f"{scope}/{section}" for scope in SCOPES for section in sections}
    expected |= {f"{scope}/feed" for scope in SCOPES}

    assert expected <= set(committed), (
        "A public route has no browser fixture coverage, so the UI is untested against it. "
        f"Add it to public-ui/fixtures/generate.py and run `{REGENERATE}`.\n"
        f"uncovered: {sorted(expected - set(committed))}"
    )
    assert any(key.startswith("dec_") for key in committed)
    assert any(key.startswith(("run_", "occ_")) for key in committed)


def test_unfixtured_routes_are_named_deliberately() -> None:
    app = create_public_app(":memory:")

    routes = {
        path
        for route in app.routes
        if (path := str(getattr(route, "path", ""))).startswith("/api/public/")
    }

    unexpected = UNFIXTURED_ROUTES - routes
    assert not unexpected, (
        "The unfixtured-route allowlist names routes that no longer exist; remove them so it "
        f"cannot hide a real gap: {sorted(unexpected)}"
    )


def test_contract_sample_is_derived_from_the_committed_fixture() -> None:
    """The browser type checker reads the sample, so a stale one would type against fiction."""
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

    assert sample == generator().contract_sample(committed), (
        "public-ui/fixtures/contract-sample.json no longer matches the committed fixture, so "
        "public-ui/src/contract.check.ts is type-checking a stale payload. Run "
        f"`{REGENERATE}`."
    )


def test_contract_sample_names_every_shape_the_browser_types() -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))

    expected = {f"{scope}/{section}" for scope in SCOPES for section in SECTIONS}
    expected |= {"decision/detail", "activity/detail"}

    assert expected <= set(sample), (
        "A published shape has no entry in the contract sample, so the browser's declared types "
        f"are unchecked against it: {sorted(expected - set(sample))}"
    )
