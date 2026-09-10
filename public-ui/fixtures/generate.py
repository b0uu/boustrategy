"""Generate browser fixtures using disposable source and publication stores only.

Run from the repository root: python public-ui/fixtures/generate.py
"""

import json
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from app.performance.storage import ingest
from app.public.publication import publish
from app.public.server import create_public_app
from app.schemas.order_intent import ExecutionMode
from app.schemas.reporting import CoverageObservation
from app.state.pipeline import process_decision
from app.storage.database import connect
from app.storage.public_records import save_public_source
from app.storage.runtime import claim, finish
from tests.fixtures.decision_records import valid_decision_record_data
from tests.performance.test_reporting import ACCOUNT, common, position, valuation
from tests.public.test_explanations import source_record
from tests.reason.test_runtime import NOW, paper_run


def generate() -> dict:
    with tempfile.TemporaryDirectory(prefix="bou-public-fixture-") as folder:
        root = Path(folder)
        source, public = root / "source.db", root / "public.db"
        with closing(connect(source)) as conn:
            save_public_source(
                conn,
                source_record(
                    excerpt="Revenue increased as customers expanded capacity.",
                    excerpt_approved=True,
                ),
            )
            stage_text = {
                "initial_thesis": (
                    "Accelerated computing demand supports another year of revenue growth, but "
                    "the current price already assumes a strong expansion."
                ),
                "counter_thesis": (
                    "Customers could pause orders after the initial buildout. New supply and "
                    "competing chips may also reduce pricing power."
                ),
                "adversarial_refinement": (
                    "The decision depends on repeat demand rather than the headline growth rate. "
                    "Track cash conversion and customer concentration before adding."
                ),
                "what_is_priced_in": (
                    "The valuation assumes continued demand and stable margins. Faster growth "
                    "alone would not establish an attractive entry price."
                ),
                "refined_thesis": (
                    "Maintain a measured position while monitoring customer investment and "
                    "margins. Add only when both the evidence and entry price justify more "
                    "exposure."
                ),
            }
            for mode in ("live", "paper"):
                for index in range(55 if mode == "live" else 4):
                    data = valid_decision_record_data()
                    data.update(
                        decision_id=f"fixture-{mode}-{index}",
                        created_at=NOW - timedelta(minutes=index),
                        public_summary=list(stage_text.values())[index % 5],
                    )
                    data["ticker"] = ["NVDA", "MSFT", "AVGO", "VRT", "AMD"][index % 5]
                    data["decision"] = ["BUY", "HOLD", "BUY", "WATCHLIST", "PASS"][index % 5]
                    if index % 5 == 2:
                        data["proposed_target_weight"] = 0.4
                        data["final_target_weight"] = 0.4
                    if index == 0:
                        data["public_narrative"] = {
                            "approved_for_publication": True,
                            "company_name": "NVIDIA",
                            "required_source_refs": ["internal-source"],
                            "stages": [
                                {"stage": key, "summary": text, "claim_ids": ["growth"]}
                                for key, text in stage_text.items()
                            ],
                            "claims": [
                                {
                                    "claim_id": "growth",
                                    "text": (
                                        "Reported revenue increased as customers expanded "
                                        "computing capacity."
                                    ),
                                    "source_refs": ["internal-source"],
                                    "evidence_confidence": 0.8,
                                    "approved_for_publication": True,
                                }
                            ],
                            "variant_perception": {
                                "consensus": "Demand growth stays strong.",
                                "disagreement": (
                                    "Margins matter more than one quarter of order growth."
                                ),
                                "evidence": (
                                    "Published company results show growth and customer "
                                    "concentration."
                                ),
                                "falsification": (
                                    "Two quarters of weaker demand would undermine the thesis."
                                ),
                                "claim_ids": ["growth"],
                            },
                            "trigger_summary": "Review following the company's quarterly results.",
                            "conviction_rationale": (
                                "Evidence supports the business outlook, while the entry price "
                                "limits the proposed size."
                            ),
                            "conditions": {
                                "add": [
                                    "Demand and cash conversion improve at a reasonable entry "
                                    "price."
                                ],
                                "trim": ["Exposure outgrows the intended portfolio role."],
                                "exit": ["The investment thesis no longer holds."],
                                "invalidation": ["Sustained demand weakness and margin erosion."],
                            },
                        }
                    process_decision(
                        conn,
                        data,
                        received_at=NOW,
                        execution_mode=ExecutionMode.LIVE
                        if mode == "live"
                        else ExecutionMode.PAPER,
                        execution_profile_id="fixture-profile" if mode == "live" else "",
                    )
            for day, equity, price in [
                (10, "10000", "150"),
                (11, "10250", "155"),
                (12, "10400", "158"),
            ]:
                holding = position("20.125", price).model_copy(
                    update={
                        "name": "NVIDIA",
                        "theme": "AI infrastructure",
                        "average_cost": Decimal("145"),
                        "quote_at": datetime(2026, 6, day, 20, tzinfo=UTC),
                    }
                )
                ingest(
                    conn,
                    valuation(
                        f"close-{day}",
                        day,
                        equity,
                        cash=Decimal(equity) - holding.market_value,
                        positions=[holding],
                    ),
                )
            ingest(
                conn,
                CoverageObservation(
                    **common("coverage", 12),
                    start_at=datetime(2026, 6, 10, 20, tzinfo=UTC),
                    end_at=datetime(2026, 6, 12, 20, tzinfo=UTC),
                    external_flows_complete=True,
                    activity_complete=True,
                ),
            )
            conn.commit()
            run = paper_run(conn, root)
            attempt = claim(conn, run.run_id, "fixture-model-a", NOW)
            finish(
                conn,
                attempt.attempt_id,
                attempt.fence,
                NOW + timedelta(seconds=10),
                status="failed",
                reason="runner_failed",
            )
            attempt = claim(
                conn, run.run_id, "fixture-model-b", NOW + timedelta(seconds=12), retry=True
            )
            finish(
                conn,
                attempt.attempt_id,
                attempt.fence,
                NOW + timedelta(seconds=30),
                status="no_action",
                public_summary="Reviewed the portfolio. No investment decision was needed.",
            )
        publish(source, public, live_profiles=("fixture-profile",), live_account_id=ACCOUNT)
        client = TestClient(create_public_app(public))
        result = {}
        for mode in ("live", "paper"):
            for section in (
                "overview",
                "positions",
                "performance",
                "policy",
                "runtime",
                "activity",
            ):
                response = client.get(f"/api/public/v2/portfolios/{mode}/{section}")
                response.raise_for_status()
                result[f"{mode}/{section}"] = response.json()
            response = client.get(
                "/api/public/v2/decisions", params={"portfolio_id": mode, "limit": 100}
            )
            response.raise_for_status()
            result[f"{mode}/feed"] = response.json()
            for item in result[f"{mode}/feed"]["items"]:
                result[item["public_id"]] = client.get(
                    "/api/public/v2/decisions/" + item["public_id"]
                ).json()
            for item in result[f"{mode}/activity"]["items"]:
                result[item["public_id"]] = client.get(
                    f"/api/public/v2/portfolios/{mode}/activity/" + item["public_id"]
                ).json()
        return result


def contract_sample(fixture: dict[str, Any]) -> dict[str, Any]:
    """One payload per stable route name, with list bodies trimmed to one item.

    The browser type checker needs to name every published shape, but the detail
    keys are opaque IDs minted per publication. This gives them stable names and
    keeps the type checker off the full fixture.
    """
    sample: dict[str, Any] = {}
    for name, payload in fixture.items():
        if "/" not in name:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            payload = {**payload, "items": payload["items"][:1]}
        sample[name] = payload
    for alias, section in (("decision/detail", "feed"), ("activity/detail", "activity")):
        # Either scope may be the populated one, so take the first detail that exists.
        for scope in ("live", "paper"):
            items = fixture[f"{scope}/{section}"]["items"]
            if items and items[0]["public_id"] in fixture:
                sample[alias] = fixture[items[0]["public_id"]]
                break
    return sample


if __name__ == "__main__":
    fixture = generate()
    target = Path(__file__).with_name("public-v2.json")
    target.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    sample = Path(__file__).with_name("contract-sample.json")
    sample.write_text(json.dumps(contract_sample(fixture), indent=2) + "\n", encoding="utf-8")
    print(target)
    print(sample)
