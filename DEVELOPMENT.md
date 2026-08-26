# Building an Investment Agent That Can Be Told No

The hard part of an investment agent isn't getting a model to produce an opinion. Models
produce opinions easily. The hard part is building a system that can distinguish a researched
decision from fluent improvisation, reject the latter, and preserve enough evidence to explain
the difference months later.

BouStrategy is being built around that boundary. An LLM can research, challenge a thesis, and
propose a portfolio action. It can't create an order directly. Every actionable proposal must
first become a structured Investment Decision Record, pass schema validation, and clear a
deterministic policy engine. Only then can the system create an order intent. Paper execution is
the next boundary, and a live broker remains disconnected.

This document is the public view of how that system is being developed: the choices that shaped
it, the mistakes that changed those choices, and the evidence required before more autonomy is
earned.

## Records before autonomy

The first version began with a record format, not a trading loop. A decision record has to name
the thesis, counter-thesis, evidence, invalidation criteria, market expectations, target weight,
regime, and the role X played in the idea. That structure doesn't make the reasoning correct, but
it makes missing reasoning visible.

Validation and policy are deliberately separate. The schema answers whether a record is
well-formed and internally consistent. Policy answers whether the action is allowed. A valid
record can still be rejected for excessive concentration, missing outside confirmation, too many
positions, a daily trade limit, or an attempted risk increase in a RED regime without an explicit
extraordinary-opportunity case.

That separation matters because models shouldn't grade their own exceptions. The reasoning
layer can argue that an opportunity is unusual. Maintainer-owned policy decides what that claim
must contain and which hard limits still apply. The state machine stores each transition so a
crash can be resumed without inventing or duplicating an order.

## Learning what a useful X feed looks like

The X pipeline started with full collection from a small human-curated account list. During the
trial, 1,761 posts received human `significant` or `skip` labels. The labels weren't treated as
perfect ground truth. They became material for a blind agreement experiment in which the model
saw the post and rubric but never the human answer.

Initial agreement was 72.6 percent. Reviewing the disagreements showed a more useful result than
a single score: some errors belonged to the model, and many belonged to the labeling process.
Fatigue created blocks of false negatives. Non-English posts were sometimes skipped despite
substantive claims. Familiar accounts occasionally received generous labels for weak posts.
After an audited correction pass, agreement reached 85.2 percent, with 0.907 precision and 0.860
recall on the positive class.

The trial also changed the product. Roughly 64 percent of the curated feed was useful, which made
a binary relevance gate less valuable for this roster than expected. The real need was ranking:
which items deserve a headline, which belong in supporting context, and which should wait in an
article queue. Link-only X articles were especially important because their contents aren't
available through the normal API response. They now route to a queue instead of being discarded
as empty posts.

Account curation remains human-owned. The system can report usefulness rates and recommend an
audit, but it can't add an account merely because that account agrees with an active thesis.

## What the July interruption exposed

The first scheduled reasoning sessions on July 19 and July 20 were valuable even though neither
produced a trade. No action is a valid outcome when the evidence doesn't justify changing the
portfolio. The July 20 run also exposed a formatting mismatch between the generated digest and
the reasoning intake parser, which caused actionable headlines to disappear at the seam between
the two workers.

A separate Windows failure was quieter. Task Scheduler kept launching the digester, and the
process kept exiting successfully, but a multiline prompt was truncated when it crossed a batch
file boundary. The agent received no specific task, so weeks of apparently healthy runs did no
work.

Both failures changed the restart design. Scheduled prompts now travel over standard input, and a
successful process exit isn't accepted as proof of completion. A deterministic post-run check
must find the expected routed or digested record in SQLite. If it doesn't, the task fails loudly.

Recovery is also bounded. A stale account requests only the most recent four days rather than
paying to reconstruct an old feed that the reasoning worker can no longer act on. The local X
Post-read ceiling is $25 per month, backed by the provider's own spending limit. Historical data
already collected is kept for evaluation, while new ingestion resumes from the present.

## Replaying the old data without pretending it knew the future

Historical evaluation is easy to contaminate. A post can be old while its human label, route, or
interpretation was created after the market moved. If the later judgment is placed back at the
post timestamp, the backtest gets knowledge the live system didn't have.

BouStrategy's first X replay therefore uses the latest of three timestamps: when the post was
published, when it was fetched, and when it was routed or captured. A same-day opening price is
allowed only if the system had the item before 09:30 New York time. Otherwise the replay moves to
the next market session. The 1,761 trial labels are excluded from this market study because the
current schema doesn't record when each label was assigned.

The old records also lack bullish or bearish direction. That means the replay can measure the
forward movement of mentioned tickers and their excess return against QQQ, but it can't honestly
call those returns strategy performance. It is an event study and a data-quality test. Going
forward, direction, decision time, evidence available at that time, and the resulting record will
be sealed together. Those forward capsules can support real process and outcome evaluation.

## Manual first, then visible, then autonomous

The current version is operated manually. That is a development constraint, not a permanent
architecture choice. Manual runs make it possible to inspect what the system saw, where judgment
entered, how much data cost, why policy accepted or rejected a record, and whether paper state
changed correctly before those steps disappear behind a schedule.

The first local dashboard now reads from those same append-only records. Its operator page turns
the manual paper cycle into three visible steps: copy a digester prompt, prepare the session, then
copy a reasoning prompt. It doesn't start model runs in the background. That pause keeps X spend
and model activity visible while the process is still being tested. Preparation is the only state
changing dashboard action, and it still requires a completed same-day digest before it can refresh
market context or settle paper intents.

The dashboard still needs deeper session history, source evidence, performance, and failure views
before it can supervise unattended operation. It shouldn't become a second source of portfolio
truth or a shortcut around the policy gate.

Only after the manual process is repeatable and the dashboard makes failures visible will
scheduled ingestion and reasoning return, first in paper mode. Unattended live execution is a
separate promotion. It shouldn't begin on the same day as the first unattended reasoning run.

## Paper first, then proof

The paper account starts at $5,000. That amount keeps position sizing tangible without confusing
simulated scale with available live capital. Approved order intents fill at the next recorded
market open, positions and cash are rebuilt from the fill ledger, and the dashboard reads from
the same append-only stores.

Paper trading isn't a waiting room for live trading. It is where the system has to demonstrate
that it can run unattended, remain inactive when no edge exists, produce records that survive
review, respect risk policy, recover from failures, and report performance without selecting only
favorable examples. Slippage, fees, data reliability, and broker-specific behavior still need to
be modeled before paper results can resemble execution results.

Live trading requires a separate broker adapter and an explicit human activation checkpoint. The
reasoning worker will still have no direct broker access. Its output must pass through the same
record, policy, intent, and execution boundaries proven in paper.

## Where human judgment stays

The goal isn't to remove the maintainer from every decision. It is to place human judgment where
it has the most leverage and leave repetitive enforcement to code.

The maintainer owns the mandate, source policy, risk rules, account roster, prompt approval,
historical preference labels, API spending limits, and any activation of live money. The system
owns repeatable ingestion, validation, policy enforcement, ledgers, replay, and monitoring. Model
judgment operates between those layers, where research and adversarial reasoning are useful but
where a persuasive sentence still can't override a hard constraint.

The next useful evidence won't be a dramatic trade. It will be a sequence of supervised sessions
in which ingestion completes, reasoning leaves auditable records, the $5,000 paper portfolio
behaves exactly as policy allows, and failures are caught while the surrounding context is still
available. Deeper dashboard visibility and the unattended paper phase can follow once that process
is repeatable.
