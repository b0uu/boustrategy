from pathlib import Path


def test_prompt_banners_and_required_guardrails() -> None:
    banner = (
        "> **DRAFT — PENDING HUMAN CHECKPOINT 5 SIGN-OFF. No decision-generating\n"
        "> session may load this prompt until the maintainer approves it and\n"
        "> records the approval in plans/README.md.**"
    )
    for path in (
        Path("docs/prompts/thesis_chain.md"),
        Path("docs/prompts/daily_management.md"),
    ):
        text = path.read_text(encoding="utf-8")
        assert text.startswith(banner)
        assert "docs/mandate.md" in text
        assert "docs/risk_policy.md" in text
        assert "docs/risk_posture.md" in text
        assert "docs/source_policy.md" in text
        assert "confirmed_outside_x" in text
        assert "submit --in" in text


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
