# Human Guide to the Audit and Plans

This file is for you, not for an AI executor. It explains what the audit
found, what each plan changes, where your judgment is genuinely needed, and
the technical concepts behind it all in plain language. Edit it freely. The
numbered plan files (001 to 004) are precise instructions for an AI to
execute; this file is the map.

---

## The one thing to do before anything else

~~Your code is not saved in git yet.~~ **Done (2026-07-08):** you committed
the implementation baseline as `01193d1` ("schema and policy added"). The
plans' drift checks now reference that commit. Remaining housekeeping, your
call: `plans/` itself is not committed yet — committing it gives your plan
history the same protection as your code.

---

## The big picture of what was found

Your architecture has a deliberate safety pipeline, and it is a good one:

```
AI reasoning -> Decision Record -> Schema check -> Policy check -> (someday) Order
```

The audit found that both checking layers have **holes in their fences**.
Each hole is small, but this pipeline is the thing standing between an LLM
and your real money, so the fences should be airtight before anything else
gets built on top.

The findings group into three stories:

### Story 1: The schema gate accepts some garbage (Plan 001)

The schema layer is your "is this even a well-formed record?" check. It
currently accepts:

- A ticker made of only spaces, which silently becomes an **empty ticker**.
- Timestamps with no timezone (more on why that matters in the glossary).
- Any random string as a source type, like `"some blog"`, even though your
  spec defines an exact list (SEC, COMPANY_IR, NEWS, X, ...).
- Contradictory X-usage states, like "X was not used" combined with
  "X was the idea source".

None of these can hurt you today because nothing trades yet. But every one
of them is a malformed audit record waiting to happen, and your whole project
thesis is that the audit trail is trustworthy.

### Story 2: The policy gate has scope bugs (Plans 002 and 003)

The policy layer is your rulebook: "this record is well-formed, but is it
*allowed*?" Three rules are mis-scoped:

1. **ADD sneaks past the risk gates.** Your rules block BUY in a RED regime
   and BUY in de-risking mode. But ADD (buying more of something you already
   own) is not blocked. ADD puts new money at risk exactly like BUY does.
   I verified this: an ADD in RED regime, in DE_RISKING mode, is approved
   today. *This one needs your judgment; see the decision points below.*

2. **The weight caps punish winners.** The 20% stock cap applies to every
   decision type. So if NVDA runs up and becomes 25% of your portfolio just
   by appreciating, the policy engine **rejects your HOLD decision**. It
   would even reject a TRIM from 30% down to 25%. The fix: caps only apply
   when you are putting money in (BUY/ADD), not when holding or reducing.

3. **The X rule is too aggressive.** Your written rule is "reject an X-only
   thesis without outside confirmation". Sensible. But the code rejects ANY
   record where X was involved and unconfirmed, including a PASS (where you
   decided to do nothing!) and cases where X argued *against* the trade
   (counter-thesis). A skeptic on X warning you off a trade does not need
   outside confirmation to be safe input.

Plan 003 adds the rules you wrote down but never built: trade quotas,
holdings cap, theme concentration. They were unbuildable before because the
policy function only sees one decision at a time; it has no idea how many
trades happened today. Plan 003 gives it a small "portfolio context" input
carrying that information. The exact limits were decided together on
2026-07-08 (see the resolved decision points below): BUY/ADD 2/day with
TRIM/SELL exempt, 10 holdings hard cap, 60% single-primary-theme cap.

### Story 3: The project has no guardrails for its own development (Plan 004)

Right now the only automated check is the test suite. Plan 004 adds two
standard tools (explained in the glossary) that catch mistakes before tests
even run, and creates a root `AGENTS.md` file. That last one matters more
than it sounds: your coding conventions currently live in
`scratchpad/AGENTS.md`, but `scratchpad/` is in `.gitignore`, so **no AI
agent or collaborator working from a fresh copy of this repo can see your
conventions**. The plan publishes them properly.

---

## Decision points: RESOLVED (2026-07-08)

We went through these together and you made the calls below. The plans now
reflect them. Each is still yours to change later; this section records what
was decided and why, so future-you (or a future agent) knows these numbers
are deliberate, not defaults.

### 1. BUY/ADD in RED regime: escalation gate, not a ban (Plan 002)

Your call: do not hardcode a block; your framework celebrates bold action
(SB-007). But a fully advisory gate would quietly delete your own "no direct
LLM-to-order path" principle. The resolution uses your spec's own idea: the
extraordinary-opportunity classification. BUY/ADD in RED (or de-risking
mode) is rejected UNLESS the record explicitly sets a new
`extraordinary_opportunity` flag with a written justification. Boldness
stays possible; it just has to be declared, justified, and auditable. If the
agent ever starts spamming the flag to dodge the gate, that is an eval and
prompt problem first, a policy-tightening problem second.

### 2. De-risking trades are never quota-blocked (Plan 003)

Your call: TRIM/SELL must not be stopped by a trade quota. The 2/day limit
now applies to BUY/ADD only. One addition you accepted: a 10/day circuit
breaker on TRIM/SELL. That is not strategy, it is a malfunction brake — a
buggy loop selling in circles gets stopped, while a legitimate emergency
"sell everything" day (max 10 holdings) still fits.

### 3. Holdings: hard cap 10, goal ~7 (Plan 003)

Your call: raise the cap for diversity. Policy rejects the 11th position and
otherwise stays out of it. The ~7 goal is strategy nuance, so it lives where
strategy lives: your mandate and prompts (write it into `docs/mandate.md`
when you draft it). Policy = rulebook, mandate = judgment.

### 4. Theme concentration: primary theme + 60% cap (Plans 001 + 003)

The problem we had to solve first: your themes overlap. NVDA plausibly maps
to ai_semiconductors AND ai_infrastructure AND ai_bottlenecks — if policy
counted full weight into every listed theme, one stock would triple-count
and the math would be meaningless. The resolution: every decision now names
ONE `primary_theme_id` (the dominant narrative you are actually betting on),
and policy caps any single primary theme at **60% of the portfolio**. You
chose 60 over 50 deliberately: more room for your highest-conviction theme,
accepting that a single-theme blowup can cost most of the book — which your
mandate explicitly tolerates ("severe drawdowns are acceptable inside the
framework").

### 5. The ticker format (Plan 001) — unchanged

The plan enforces tickers like `NVDA`, `BRK.B`, `BF-B`: letters first, up to
12 characters, US-listing shaped. If you ever want non-US listings, this
rule is the thing to revisit.

---

## What was deliberately NOT planned (and why)

- **Writing your mandate/risk/source policy docs** (`docs/mandate.md` etc.
  are empty files): your own spec says "human strategy is the edge". An AI
  drafting your mandate would be exactly the consensus-flavored slop your
  project exists to avoid. These are yours to write.
- **The sizing-adjustment feature** (policy reducing a target weight instead
  of rejecting): it needs inputs that do not exist yet, like thesis-quality
  scores and liquidity data. The dead placeholder field for it gets removed
  in plan 003; it comes back when the feature is real.

## What to build NEXT, after these plans (your pick)

These came out of the audit as the highest-value next moves, in my suggested
order, but this is vision territory and the call is yours:

1. **Order Intent schema + the approval pipeline.** Your core safety
   principle is "no direct LLM-to-order path". The decision record already
   has an `order_intent_id` field pointing at... nothing. Building the
   Order Intent object and the rule "an intent can only be created from an
   approved decision" turns your safety principle from prose into code.
2. **Saving records to disk/database with idempotency.** Right now records
   only exist in memory during tests. Idempotency (glossary below) is what
   prevents the nightmare scenario: a crash mid-workflow, a restart, and the
   same order placed twice.
3. **The daily price cache** (spec section 6 already names the source:
   yfinance, daily OHLCV). This unblocks regime scoring and the dashboard.

A reasonable instinct is to jump to the fun part (the reasoning agent, the
dashboard). The boring order here is deliberate: every layer of deterministic
safety you finish first makes the fun part safer to turn loose.

---

## How to work with the plan files

- Each plan (001 to 004) is written so an AI agent with zero context can
  execute it: exact files, exact steps, a verification command after every
  step, and STOP conditions so it reports back instead of improvising.
- **You can edit them.** They are markdown, not magic. If a decision point
  above changes your mind, edit the relevant step before execution.
- Run them via something like: "execute plans/001-tighten-decision-record-schema.md"
  in a Claude Code session. Recommended order: 001, 002, 003, 004 (002 must
  come before 003; 004 can happen anytime).
- After each plan runs, the status table in `plans/README.md` should be
  updated by whoever ran it. Glance at it to see where things stand.
- Review the diff after each execution like you would review a human's PR.
  The plans constrain the AI hard, but you are the final gate.

---

## Glossary: the technical concepts, simply

**Schema vs. policy (your two-layer design).** The schema layer asks "is
this record shaped correctly?" like a bouncer checking that an ID is a real
ID. The policy layer asks "is this allowed?" like the bouncer then checking
the age on it. Keeping them separate means each stays simple and testable.

**Pydantic.** The Python library your schemas are built on. You declare what
a record should look like (fields, types, allowed values) and pydantic
rejects anything that does not match. Your `InvestmentDecisionRecord` class
is a pydantic model.

**The whitespace-ticker bug, mechanically.** Pydantic runs its built-in
checks (like "minimum length 1") on the *raw input*, and only afterwards
runs your custom cleanup code (strip spaces, uppercase). So `"   "` passes
the length check (3 characters!), then your cleanup turns it into `""`,
empty, and nothing re-checks it. The fix moves the "must not be empty" check
to after the cleanup.

**Timezone-aware vs. naive datetimes.** A naive timestamp says "June 10,
14:30" with no timezone. 14:30 *where*? In an audit trail for trading (where
market open/close in US Eastern time is everything), ambiguous timestamps
are landmines. "Aware" timestamps carry the timezone, so `14:30 UTC` is one
exact moment forever. The fix forces every timestamp to be aware.

**Enum.** A field that only accepts values from a fixed list. Your
`Decision` enum accepts BUY/ADD/TRIM/SELL/HOLD/PASS/WATCHLIST and nothing
else. Plan 001 turns `source_type` from "any string" into an enum matching
your spec's list.

**Idempotency.** An operation is idempotent if doing it twice has the same
effect as doing it once. Crucial for trading systems: if the system crashes
after sending an order but before recording it, the restart logic must
recognize "this order already went out" instead of sending it again. Stable
IDs (`decision_id`, `order_intent_id`) are what make that recognition
possible.

**Linter (ruff).** A tool that reads your code without running it and flags
mistakes and style drift: unused imports, suspicious patterns, messy
formatting. Like spellcheck for code. Runs in milliseconds.

**Type checker (mypy).** Python normally only discovers type mistakes when
the broken line actually runs. A type checker proves things ahead of time,
like "this function returns a PolicyResult, and everyone using it treats it
as one". Since your code is built on pydantic models with declared types,
mypy catches a whole class of AI-coding mistakes for free.

**Dead field.** `adjusted_final_target_weight` exists on `PolicyResult` but
no code ever sets it, so it is always `None`. Dangerous because a future
caller might read it believing it is computed. Rule of thumb: interface
surface should not promise what the code does not deliver.

**Escalation gate.** A rule that rejects by default but has a declared
escape valve. Instead of "BUY in RED is banned", the rule becomes "BUY in
RED is rejected unless the record explicitly claims extraordinary
opportunity and justifies it in writing". The power of this over a soft
warning: the escape is visible in the audit record forever, so you can
later judge every time the agent chose to be bold.

**Primary theme.** Your themes overlap, so a stock can belong to three of
them at once. The primary theme is the ONE narrative a decision is actually
a bet on, picked per decision. Concentration math runs on primary themes
only, which keeps "60% max in one theme" meaningful.

**Worktree / drift check.** When an AI executor runs a plan, it may work in
a separate copy of the repo (a worktree) and first checks whether the code
still matches what the plan was written against (drift). This is why
committing your code to git matters: both mechanisms rely on git knowing
about your files.

---

*Generated alongside the 2026-06-12 audit. Iterate on it; it is yours.*
