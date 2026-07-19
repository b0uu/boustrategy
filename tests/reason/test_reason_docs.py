from pathlib import Path


def test_prompt_required_guardrails() -> None:
    for path in (
        Path("docs/prompts/thesis_chain.md"),
        Path("docs/prompts/daily_management.md"),
    ):
        text = path.read_text(encoding="utf-8")
        # A DRAFT banner reappearing here without a matching README update
        # (checked below) would mean a prompt reverted to unapproved without
        # anyone recording that the sign-off was revoked.
        assert "PENDING HUMAN CHECKPOINT 5 SIGN-OFF" not in text
        assert "docs/mandate.md" in text
        assert "docs/risk_policy.md" in text
        assert "docs/risk_posture.md" in text
        assert "docs/source_policy.md" in text
        assert "confirmed_outside_x" in text
        assert "submit --in" in text


def test_checkpoint_5_signoff_is_recorded() -> None:
    text = Path("plans/README.md").read_text(encoding="utf-8")
    assert "Checkpoint 5 is CLEARED" in text


def test_runbook_cli_and_exact_prohibitions() -> None:
    text = Path("docs/reasoning/RUNBOOK.md").read_text(encoding="utf-8")

    for command in (
        "python -m app.paper.run settle",
        "python -m app.triggers.run evaluate [--date YYYY-MM-DD]",
        "python -m app.regime.run score [--date YYYY-MM-DD]",
        "python -m app.reason.run intake [--date YYYY-MM-DD] --out <directory>",
        "python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]",
    ):
        assert command in text
    assert (
        "never edit digests/labels/roster/maintainer docs; never write to the db except via "
        "`submit`; never continue into digester work (separate seam, separate session)."
    ) in text
