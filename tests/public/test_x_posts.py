import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.public.database import open_readonly
from app.public.publication import publish
from app.schemas.order_intent import ExecutionMode
from app.schemas.public_authoring import PublicXPost, canonical_x_post
from app.state.pipeline import process_decision
from app.storage.database import connect
from tests.fixtures.decision_records import valid_decision_record_data

NOW = datetime(2026, 9, 11, 19, 0, tzinfo=UTC)
POST = "https://x.com/examplefeed/status/1000000000000000000"


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/examplefeed",
        "http://x.com/examplefeed/status/1",
        "https://x.com.evil.example/examplefeed/status/1",
        "https://evil.example/x.com/examplefeed/status/1",
        "https://x.com/examplefeed/status/1?ref=private",
        "javascript:alert(1)",
    ],
)
def test_only_canonical_public_status_urls_are_accepted(url: str) -> None:
    assert canonical_x_post(url) is None
    with pytest.raises(ValidationError):
        PublicXPost(url=url, role="supporting", summary="A summary.")


def test_twitter_links_normalize_to_x() -> None:
    post = PublicXPost(
        url="https://twitter.com/examplefeed/status/42", role="context", summary="Background."
    )
    assert post.url == "https://x.com/examplefeed/status/42"


def _decision(conn: object, **changes: object) -> None:
    data = valid_decision_record_data()
    data.update(decision_id="x-decision", created_at=NOW, **changes)
    process_decision(
        conn,  # type: ignore[arg-type]
        data,
        received_at=NOW,
        execution_mode=ExecutionMode.PAPER,
    )


def _published(public: Path) -> dict[str, object]:
    with open_readonly(public) as reader:
        content: dict[str, object] = json.loads(
            reader.execute("SELECT content FROM public_decisions").fetchone()[0]
        )
    return content


def test_the_triggering_post_is_linked_without_its_text(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    trigger = "digest_headline:1000000000000000000:2026-09-10"
    conn.execute(
        "INSERT INTO trigger_events (trigger_id, trigger_type, subject, fired_at, details_json, "
        "status) VALUES (?, 'digest_headline', '1', '2026-09-10', ?, 'pending')",
        (
            trigger,
            json.dumps(
                {"handle": "examplefeed", "reason": "PRIVATE-SENTINEL headline", "url": POST}
            ),
        ),
    )
    conn.commit()
    _decision(conn, trigger_id=trigger)
    conn.close()

    publish(source, public)
    content = _published(public)

    assert content["x_posts"] == [
        {"url": POST, "handle": "examplefeed", "role": "trigger", "summary": None}
    ]
    assert "PRIVATE-SENTINEL" not in public.read_bytes().decode("utf-8", "ignore")


def test_a_malformed_trigger_link_is_not_published(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    trigger = "digest_headline:2:2026-09-10"
    conn.execute(
        "INSERT INTO trigger_events (trigger_id, trigger_type, subject, fired_at, details_json, "
        "status) VALUES (?, 'digest_headline', '2', '2026-09-10', ?, 'pending')",
        (trigger, json.dumps({"url": "https://evil.example/status/2"})),
    )
    conn.commit()
    _decision(conn, trigger_id=trigger)
    conn.close()

    publish(source, public)

    assert _published(public)["x_posts"] == []
