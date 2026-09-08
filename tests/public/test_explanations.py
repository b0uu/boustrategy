import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.public.explanations import execution_projection, policy_projection
from app.public.publication import publish, revoke
from app.public.server import create_public_app
from app.schemas.policy_reporting import PolicyEvaluationRecord
from app.schemas.public_authoring import PublicSourceRecord
from app.schemas.reporting import FillObservation
from app.state.pipeline import process_decision
from app.storage.database import connect
from app.storage.public_records import save_public_source
from tests.fixtures.decision_records import valid_decision_record_data

NOW = datetime(2026, 6, 10, 15, tzinfo=UTC)


def source_record(**changes: object) -> PublicSourceRecord:
    return PublicSourceRecord.model_validate(
        {
            "revision_id": "revision-private",
            "source_ref": "internal-source",
            "recorded_at": NOW,
            "title": "Quarterly results",
            "publisher": "Company IR",
            "published_on": "2026-06-10",
            "source_type": "COMPANY_IR",
            "url": "https://example.com/results#revenue",
            "access": "public",
            "approved_for_publication": True,
            "excerpt": "PRIVATE_EXCERPT",
            **changes,
        }
    )


def test_public_narrative_feed_exports_and_source_retraction(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    source_id = save_public_source(conn, source_record())
    data = valid_decision_record_data()
    data.update(
        public_summary="=SUM(1,2) " + "public words " * 80,
        initial_thesis="PRIVATE_THESIS",
        internal_notes="PRIVATE_NOTES",
        public_narrative={
            "approved_for_publication": True,
            "company_name": "Example Semiconductor",
            "required_source_refs": ["internal-source"],
            "claims": [
                {
                    "claim_id": "internal-claim",
                    "text": "Revenue grew.",
                    "source_refs": ["internal-source"],
                    "approved_for_publication": True,
                }
            ],
            "stages": [
                {
                    "stage": "what_is_priced_in",
                    "summary": "Public priced-in summary",
                    "claim_ids": ["internal-claim"],
                }
            ],
        },
    )
    process_decision(conn, data, received_at=NOW)
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    feed = client.get(
        "/api/public/v2/decisions", params={"portfolio_id": "paper", "q": "Semiconductor"}
    ).json()
    item = feed["items"][0]
    assert item["summary_truncated"] and len(item["public_summary"]) == 600
    assert "narrative" not in item and "claims" not in item and "execution" not in item
    path = "/api/public/v2/decisions/" + item["public_id"]
    detail = client.get(path).json()
    head = client.head(path + "/export", params={"format": "csv"})
    assert head.status_code == 200 and not head.content
    assert "text/csv" in head.headers["content-type"]
    assert "attachment" in head.headers["content-disposition"]
    assert client.head("/api/public/v2/portfolios/paper/policy").status_code == 200
    assert detail["narrative"]["sources"][0]["public_id"] == source_id
    assert detail["narrative"]["sources"][0]["excerpt"] is None
    assert detail["narrative"]["stages"][0]["stage"] == "what_is_priced_in"
    for secret in (
        "PRIVATE_THESIS",
        "PRIVATE_NOTES",
        "PRIVATE_EXCERPT",
        "internal-source",
        "internal-claim",
    ):
        assert secret not in json.dumps(detail)
        assert secret not in client.get(path + "/export").text
        assert secret not in client.get(path + "/export", params={"format": "csv"}).text
    exported = next(
        csv.DictReader(io.StringIO(client.get(path + "/export", params={"format": "csv"}).text))
    )
    assert exported["public_summary"].startswith("'=SUM")
    assert exported["confirmed_gross_notional"] == ""
    legacy = client.get(
        f"/api/public/v2/legacy-decisions/{item['ticker']}/{item['created_at']}"
    ).json()
    assert legacy["narrative"]["stages"][0]["summary"] == "Public priced-in summary"
    conn = connect(source)
    assert (
        save_public_source(
            conn,
            source_record(
                revision_id="revision-two",
                supersedes="revision-private",
                approved_for_publication=False,
            ),
        )
        == source_id
    )
    conn.commit()
    conn.close()
    publish(source, public)
    assert client.get(path).status_code == 410
    assert client.get(path + "/export").status_code == 410
    assert (
        client.get(
            "/api/public/v2/decisions", params={"portfolio_id": "paper", "q": "Semiconductor"}
        ).json()["total"]
        == 0
    )


def test_x_typed_source_never_publishes_an_excerpt(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    save_public_source(
        conn,
        source_record(
            source_type="X",
            excerpt="PRIVATE_X_TEXT",
            excerpt_approved=True,
            url="https://x.com/someone/status/1",
        ),
    )
    save_public_source(
        conn,
        source_record(
            revision_id="revision-2",
            source_ref="ir-source",
            excerpt="APPROVED_IR_TEXT",
            excerpt_approved=True,
        ),
    )
    data = valid_decision_record_data()
    data["source_claims"] = [
        {
            "claim": "An X post described product demand.",
            "source_ids": ["internal-source"],
            "source_type": "X",
            "source_timestamp": NOW,
            "confidence": 0.7,
            "public_safe": True,
        },
        {
            "claim": "Company materials described product demand.",
            "source_ids": ["ir-source"],
            "source_type": "COMPANY_IR",
            "source_timestamp": NOW,
            "confidence": 0.9,
            "public_safe": True,
        },
    ]
    data["public_narrative"] = {
        "approved_for_publication": True,
        "claims": [
            {
                "claim_id": "x-claim",
                "text": "Demand was discussed publicly.",
                "source_refs": ["internal-source"],
                "approved_for_publication": True,
            },
            {
                "claim_id": "ir-claim",
                "text": "Company materials support the demand claim.",
                "source_refs": ["ir-source"],
                "approved_for_publication": True,
            },
        ],
    }
    process_decision(conn, data, received_at=NOW)
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))

    item = client.get("/api/public/v2/decisions", params={"portfolio_id": "paper"}).json()["items"][
        0
    ]
    detail = client.get("/api/public/v2/decisions/" + item["public_id"]).json()

    excerpts = {
        source["source_type"]: source["excerpt"] for source in detail["narrative"]["sources"]
    }
    assert excerpts["X"] is None
    assert excerpts["COMPANY_IR"] == "APPROVED_IR_TEXT"
    assert b"PRIVATE_X_TEXT" not in public.read_bytes()


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "https://user:pass@example.com",
        "http://127.0.0.1/a",
        "http://host.LOCAL./x",
        "http://10.0.0.1",
        "https://example.com?access_token=secret",
    ],
)
def test_private_source_urls_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        source_record(url=url)


def test_source_revision_identity_and_immutability() -> None:
    conn = connect(":memory:")
    first = source_record()
    identifier = save_public_source(conn, first)
    assert save_public_source(conn, first) == identifier
    with pytest.raises(ValueError, match="immutable"):
        save_public_source(conn, source_record(title="changed"))
    with pytest.raises(ValueError, match="identity"):
        save_public_source(
            conn,
            source_record(
                revision_id="second", supersedes=first.revision_id, source_ref="different"
            ),
        )
    conn.close()


def test_missing_execution_and_partial_execution_never_use_requested_notional() -> None:
    assert execution_projection([])["gross_notional"] is None
    fill = FillObservation(
        observation_id="f",
        external_event_id="f",
        mode="paper",
        account_id="paper",
        occurred_at=NOW,
        recorded_at=NOW,
        ticker="NVDA",
        side="BUY",
        quantity="2",
        price="10",
        gross_notional="20",
        fee=None,
        origin="agent",
        decision_id="private",
        order_state="canceled",
        canceled_quantity="3",
    )
    detail = execution_projection([fill])
    assert detail["gross_notional"] == "20" and detail["fees"] is None
    assert detail["items"][0]["canceled_quantity"] == "3"
    assert "private" not in json.dumps(detail)


def test_catalog_trigger_links_retract_and_recorded_labels_survive(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    data = valid_decision_record_data()
    data.update(proposed_target_weight=0.3, final_target_weight=0.3)
    process_decision(conn, data, received_at=NOW)
    ledger = PolicyEvaluationRecord.model_validate_json(
        conn.execute("SELECT evaluation_json FROM policy_evaluations").fetchone()[0]
    )
    ledger.checks[0].rule_id = "retired_rule"
    ledger.checks[0].name = "Recorded old label"
    assert policy_projection(ledger)["checks"][0]["name"] == "Recorded old label"
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    catalog = client.get("/api/public/v2/portfolios/paper/policy").json()
    failed = next(rule for rule in catalog["decision_rules"] if rule["last_triggered"])
    assert failed["threshold"] == 0.2
    revoke(public, failed["last_triggered"]["public_id"])
    catalog = client.get("/api/public/v2/portfolios/paper/policy").json()
    assert all(rule["last_triggered"] is None for rule in catalog["decision_rules"])


def test_long_history_keeps_open_episode_review_and_reopened_identity(tmp_path: Path) -> None:
    from datetime import timedelta

    from app.performance.report import holding_episodes
    from app.performance.storage import ingest
    from app.schemas.public_authoring import ThesisReview
    from app.schemas.reporting import ReportingObservation
    from app.storage.public_records import save_thesis_review
    from tests.performance.test_reporting import ACCOUNT, common, coverage, position, valuation

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    start = valuation("start", 10, "1000", cash="990", positions=[position("1", "10")])
    end = valuation("end", 12, "1000", cash="990", positions=[position("1", "10")])
    observations: list[ReportingObservation] = [start, end, coverage()]
    for index in range(202):
        at = datetime(2026, 6, 11, 12, tzinfo=UTC) + timedelta(minutes=index)
        facts = common(f"fill-{index}", 11)
        facts.update(occurred_at=at)
        observations.append(
            FillObservation(
                **facts,
                ticker="AMD",
                side="BUY" if index % 2 == 0 else "SELL",
                quantity="1",
                price="1",
                gross_notional="1",
                fee="0",
                origin="external",
            )
        )
    for observation in observations:
        ingest(conn, observation)
    history = holding_episodes([start, end], observations, [coverage()], limit=None)
    episode_id = history["items"][0]["episode_id"]
    assert len(history["items"]) == 102
    assert len({item["episode_id"] for item in history["items"]}) == 102
    review = ThesisReview(
        review_id="private-review",
        mode="live",
        account_id=ACCOUNT,
        episode_id=episode_id,
        ticker="NVDA",
        reviewed_at=end.occurred_at,
        recorded_at=end.occurred_at,
        author="operator",
        state="intact",
        summary="Demand thesis remains intact.",
        approved_for_publication=True,
        private_notes="PRIVATE_REVIEW",
    )
    save_thesis_review(conn, review)
    save_thesis_review(conn, review)
    with pytest.raises(ValueError, match="episode"):
        save_thesis_review(conn, review.model_copy(update={"review_id": "wrong", "ticker": "AMD"}))
    with pytest.raises(ValueError, match="unavailable"):
        save_thesis_review(
            conn,
            review.model_copy(
                update={"review_id": "wrong-account", "account_id": "fedcba9876543210"}
            ),
        )
    conn.commit()
    publish(source, public, live_account_id=ACCOUNT)
    client = TestClient(create_public_app(public))
    positions = client.get("/api/public/v2/portfolios/live/positions").json()
    assert positions["items"][0]["holding_episode_id"] == episode_id
    assert positions["items"][0]["thesis_review"]["state"] == "intact"
    assert "PRIVATE_REVIEW" not in json.dumps(positions)
    assert "private-review" not in json.dumps(positions)
    overview = client.get("/api/public/v2/portfolios/live/overview").json()
    assert len(overview["holding_episodes"]["items"]) == 100
    save_thesis_review(
        conn,
        review.model_copy(
            update={
                "review_id": "new-private-review",
                "reviewed_at": end.occurred_at + timedelta(minutes=1),
                "recorded_at": end.occurred_at + timedelta(minutes=1),
                "approved_for_publication": False,
            }
        ),
    )
    conn.commit()
    conn.close()
    publish(source, public, live_account_id=ACCOUNT)
    assert (
        client.get("/api/public/v2/portfolios/live/positions").json()["items"][0]["thesis_review"][
            "state"
        ]
        == "not_reviewed"
    )


def test_future_source_is_not_decision_evidence_and_private_drafts_stay_private(
    tmp_path: Path,
) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    save_public_source(conn, source_record(published_on="2026-06-11"))
    data = valid_decision_record_data()
    data["public_narrative"] = {
        "approved_for_publication": True,
        "claims": [
            {
                "claim_id": "later",
                "text": "FUTURE_EVIDENCE",
                "source_refs": ["internal-source"],
                "approved_for_publication": True,
            },
            {"claim_id": "draft", "text": "PRIVATE_DRAFT"},
        ],
        "stages": [{"stage": "refined_thesis", "summary": "FUTURE_STAGE", "claim_ids": ["later"]}],
    }
    process_decision(conn, data, received_at=NOW)
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    item = client.get("/api/public/v2/decisions", params={"portfolio_id": "paper"}).json()["items"][
        0
    ]
    detail = client.get("/api/public/v2/decisions/" + item["public_id"])
    assert detail.json()["narrative"]["claims"] == []
    assert detail.json()["narrative"]["stages"] == []
    assert all(
        text not in detail.text for text in ("FUTURE_EVIDENCE", "PRIVATE_DRAFT", "FUTURE_STAGE")
    )


def test_search_controls_are_client_errors_not_sql_failures(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    process_decision(conn, valid_decision_record_data(), received_at=NOW)
    conn.close()
    publish(source, public)
    client = TestClient(create_public_app(public))
    assert client.get("/api/public/v2/decisions", params={"q": "NVDA\x00"}).status_code == 422
    assert client.get("/api/public/v2/decisions", params={"q": "  NVDA\t "}).status_code == 200


def test_cursor_integer_overflow_is_rejected(tmp_path: Path) -> None:
    import base64

    from tests.public.test_public_v2 import seed

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source)
    publish(source, public)
    client = TestClient(create_public_app(public))
    params = {"portfolio_id": "paper", "limit": 1}
    first = client.get("/api/public/v2/decisions", params=params).json()
    token = json.loads(base64.urlsafe_b64decode(first["next_cursor"]))
    token["high_water"] = 2**100
    forged = base64.urlsafe_b64encode(json.dumps(token).encode()).decode()
    assert (
        client.get("/api/public/v2/decisions", params={**params, "cursor": forged}).status_code
        == 422
    )


def test_prior_public_store_reads_without_get_migration(tmp_path: Path) -> None:
    import sqlite3

    from tests.public.test_public_v2 import seed

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source)
    publish(source, public)
    conn = sqlite3.connect(public)
    conn.execute("ALTER TABLE public_decisions DROP COLUMN feed_content")
    conn.execute("DROP TABLE public_policy")
    conn.execute("DROP TABLE public_rule_triggers")
    conn.commit()
    client = TestClient(create_public_app(public))
    item = client.get("/api/public/v2/decisions", params={"portfolio_id": "paper"}).json()["items"][
        0
    ]
    assert item["public_id"] and item["public_summary"]
    assert "policy_evaluation" not in item and "narrative" not in item
    assert client.get("/api/public/v2/portfolios/paper/policy").json()["status"] == "unavailable"
    assert client.get("/api/public/v2/portfolios/paper/overview").status_code == 200
    assert "feed_content" not in {
        row[1] for row in conn.execute("PRAGMA table_info(public_decisions)")
    }
    conn.close()


def test_broker_milestones_and_requested_size_do_not_fabricate_fills(tmp_path: Path) -> None:
    from datetime import timedelta

    from app.schemas.broker_execution import BrokerExecutionRecord
    from app.schemas.live_execution import LiveExecutionPacket
    from app.schemas.order_intent import ExecutionMode

    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    data = valid_decision_record_data()
    outcome = process_decision(
        conn,
        data,
        received_at=NOW,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="private-profile",
    )
    packet = LiveExecutionPacket(
        execution_packet_id="private-packet",
        order_intent_id=outcome.order_intent_id,
        decision_id=data["decision_id"],
        execution_profile_id="private-profile",
        agent_provider="CODEX",
        account_alias="PRIVATE_ACCOUNT",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
        ticker="NVDA",
        side="BUY",
        order_type="LIMIT",
        target_weight=0.1,
        account_equity=1000,
        current_position_value=0,
        notional=20,
        limit_price=10,
        quote_at=NOW,
        spread_bps=0,
        require_human_approval=True,
    )
    conn.execute(
        "INSERT INTO live_execution_packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            packet.execution_packet_id,
            packet.order_intent_id,
            packet.execution_profile_id,
            NOW.isoformat(),
            packet.expires_at.isoformat(),
            "NVDA",
            "BUY",
            20,
            10,
            packet.model_dump_json(),
        ),
    )
    broker = BrokerExecutionRecord(
        broker_execution_record_id="private-broker",
        order_intent_id=packet.order_intent_id,
        execution_packet_id=packet.execution_packet_id,
        execution_profile_id="private-profile",
        account_alias="PRIVATE_ACCOUNT",
        ticker="NVDA",
        side="BUY",
        order_type="LIMIT",
        requested_notional=20,
        limit_price=10,
        submitted_at=NOW,
        status="SUBMITTED",
        broker_order_id="private-order",
        execution_price=0,
    )
    conn.execute(
        "INSERT INTO broker_execution_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            broker.broker_execution_record_id,
            broker.order_intent_id,
            broker.execution_packet_id,
            broker.execution_profile_id,
            broker.account_alias,
            NOW.isoformat(),
            "NVDA",
            "BUY",
            "SUBMITTED",
            broker.broker_order_id,
            broker.model_dump_json(),
        ),
    )
    conn.execute(
        "INSERT INTO broker_execution_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "private-event",
            "private-broker",
            packet.order_intent_id,
            "private-packet",
            "private-profile",
            "CANCELED",
            (NOW + timedelta(minutes=1)).isoformat(),
            "PRIVATE_DETAIL",
            "{}",
        ),
    )
    conn.commit()
    conn.close()
    publish(source, public, live_profiles=("private-profile",))
    client = TestClient(create_public_app(public))
    item = client.get("/api/public/v2/decisions").json()["items"][0]
    detail = client.get("/api/public/v2/decisions/" + item["public_id"]).json()
    assert detail["lifecycle"] == "broker_canceled"
    assert detail["requested_order"]["notional"] == 20
    assert detail["sized_order"]["notional"] == 20
    assert detail["execution"]["quantity"] is None and detail["execution"]["gross_notional"] is None
    assert detail["milestones"][-1]["stage"] == "broker_canceled"
    assert "PRIVATE" not in json.dumps(detail) and "private-" not in json.dumps(detail)
