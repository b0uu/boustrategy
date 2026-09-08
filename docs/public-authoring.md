# Public decision records

Public prose is an explicit publication choice. Keep private research in the existing
private fields. `public_summary` remains the public feed summary. The optional
`public_narrative` adds approved detail without making elaborate prose mandatory for
HOLD, PASS, WATCHLIST, or no-action runs.

Set `public_narrative.approved_for_publication` only after checking its content.
The typed schema in `app/schemas/public_authoring.py` supports five stage summaries,
claim associations, variant perception, conditions, trigger and X summaries,
conviction rationale, an extraordinary-opportunity explanation, and a supplied
company name. Stages have optional actual start/completion timestamps. Don't infer
timing from prose. A stage can't finish before it starts or occur after decision
creation, and a live stage can't start before its recorded run.

Each new public claim has its own approval flag. Its optional evidence confidence
is a model assessment of that claim's evidence, never a decision score or policy
gate. Missing confidence stays null. Claim IDs and source references are local
input references and become opaque public IDs during publication.

## Sources

Register sources through the trusted local command:

```powershell
python -m app.reason.public_records --db data/boustrategy.db --kind source --input source.json
```

A source record contains `revision_id`, `source_ref`, `recorded_at`, `title`,
`publisher`, `published_on` (or null), `source_type`, and an optional safe HTTP(S)
`url`. Set `access` to `public` and `approved_for_publication` to true to publish.
Private/authenticated sources aren't eligible. An excerpt has a separate
`excerpt_approved` flag. The registry doesn't fetch URLs or validate their public
access over the network. The trusted author must check eligibility.

Corrections and retractions are new revisions with `supersedes` set to the current
revision ID. They retain the source's opaque public ID. Revisions can't change
source identity, fork the revision chain, or overwrite an earlier record. A later
registration can describe a genuinely earlier publication date. Known publication
dates after a decision aren't available as evidence for that decision. Unknown
dates remain null.

Claims only link eligible sources. Stages depending on an omitted claim are omitted
too. Add a reference to `required_source_refs` when the decision's public narrative
must be withdrawn if that evidence becomes unavailable. Republish after ingestion
or retraction. Retraction doesn't rewrite previously downloaded exports.

## Thesis reviews

```powershell
python -m app.reason.public_records --db data/boustrategy.db --kind thesis-review --input review.json
```

A review names `review_id`, `mode`, `account_id`, `episode_id`, `ticker`,
`reviewed_at`, `recorded_at`, `author`, and `state`. States are `not_reviewed`,
`intact`, `under_review`, and `invalidated`. Agent reviews require the recorded
`reasoning_run_id`, whose snapshot must bind the same live account. Operator
reviews can omit the run. Public summary/narrative require explicit approval.
`private_notes` never cross the public boundary.

Storage verifies the holding episode against complete observed activity and
quantities. Missing history isn't permission to attach a guessed ticker review.
Closed and reopened holdings have different IDs. A newer unpublished review means
there's no current public review, rather than silently retaining an old intact
verdict. Review records are immutable. Record a new review at a later time to
change the assessment. Public episode history is capped at 100; current holdings
retain their episode and review even when older than that history window.

## Recorded policy and execution

New evaluations preserve rule results, neutral names, failure explanations,
thresholds, units, versions, evaluation time, exact context inputs, and bound
snapshots. The ledger and outcome commit together. Historical decisions without a
ledger have unavailable provenance. Public historical checks don't rerun today's
policy. Current exposure is an observation, not an entry-policy violation caused by
price appreciation. Extraordinary opportunity only affects the existing RED,
de-risking, and ordinary buy/add quota exceptions; entry caps and hard circuit
breakers still apply. Public explanation doesn't change those rules.

Broker milestones use recorded status timestamps. Conflicting statuses at the same
latest timestamp are explicitly ambiguous. Prepared execution-packet sizing is
separate from a submitted request. Requested notional is separate
from confirmed executed quantity/notional. Confirmed fills use reporting
observations; a broker FILLED label alone doesn't establish quantity or fees.
Unknown fees and slippage remain null. No fill-level fee assumption is needed for
returns based on complete observed equity.

## Public contracts

- `GET`/`HEAD /api/public/v2/decisions/{public_id}` returns approved detail.
- `GET`/`HEAD /api/public/v2/decisions/{public_id}/export?format=json` returns the
  same detail with `export_version=public-decision-2`.
- `format=csv` returns one summary row, version `public-decision-csv-1`, with public
  identity/scope/time/ticker/company/action/summary, policy/lifecycle, proposed and
  final target weights, current weight, sized/requested notional, and confirmed
  quantity/gross notional/fees.
  Empty numeric cells mean unknown. Text formula prefixes are escaped for spreadsheets.
- `GET`/`HEAD /api/public/v2/portfolios/{portfolio_id}/policy` returns the current
  catalog, separately labeled exposure, and eligible last-triggered links.

The feed summary is capped at 600 characters and includes `summary_truncated`.
It excludes stages, claims, and execution details. Search still uses the full public
summary plus ticker/theme/company. Detail bounds milestone and fill event lists at
100, with totals and truncation markers. Execution totals include all confirmed
fills. V1 adapters never fall back to private thesis text. Public requests only read
the published database. Trusted publication must run after source changes.
