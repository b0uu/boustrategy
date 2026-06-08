# BouStrategy Spec

**BouStrategy**: Fully autonomous long-only high risk trading agent operating in a small dedicated live Robinhood account. 

---

## 0. Notes

**Project name:** BouStrategy  

**Spec version:** v0.1  

**Goal:** Build a public investment agent with live autonomous execution, detailed logging, and a sophisticated trading framework based on personal strategy.  

**Initial account capital:** $500  

**Default trading philosophy:**  Long-only, high-risk, concentrated bets, AI ecosystem under deep consideration, thematic investing 

**Human role:** Iterate upon harness, prompts, schemas, source lists, themes, and framework when needed

---

## 1. About

BouStrategy attempts to create an investment agent that revolves around a human-written investment framework. Agents operate under a system that researches, reasons, trades, logs its reasoning, monitors thesis validity. A public dashboard will display performance of the trading run operated by BouStrategy agent.  

The core challenge is building an investment harness that is able to deeply consider and execute upon investment frameworks and constraints. Agents will:

- follow a defined mandate

- differentiate noise from real opportunities,

- avoid spewing consensus takes leading to undifferentiated investment decisions,

- monitor active theses without forcing trades

- act boldly when evidence warrants

- log every serious decision

- obey deterministic risk and execution constraints

- and explain every actionable and non actionable insight

---

## 2. Core principles

- **Trade-level autonomy:** The human does not approve individual trades. The human changes the mandate, prompts, schemas, source graph, evals, and harness logic.
- **Human strategy is the edge:** Decisions should reflect strategy beliefs, curated sources, handpicked X accounts, internal memos, and approved/rejected historical examples.
- **No direct LLM-to-order path:** Serious decisions must pass workflow, schema validation, policy checks, idempotency checks, and broker review before execution.
- **Bold but specific:** The agent may take concentrated risk when evidence supports it, but thesis, sources, invalidation criteria, sizing, and mandate fit must be explicit.
- **Public process where safe:** The dashboard should show P&L, active thesis health, regime state, source claims, rejected decisions, policy failures, and mistake logs.
- **Demo capital can be lost:** Severe drawdowns are acceptable if they occur inside the intended framework.

---

## 3. v0.1 scope and mandate

### In scope

- Live ~$500 dedicated Robinhood account
- Long-only U.S.-listed equities and ETFs
- Autonomous execution through a Robinhood broker adapter
- Utilize robinhood functions (such as fetching price)
- Codex powered reasoning worker where possible
- Investment intelligence MCP for context, schemas, records, source packs, and policy checks
- Daily portfolio management chain
- Full thesis chain when necessary
- Curated X account tracking via X API
- Free, public data for research
- Historical daily price cache from free sources
- Public dashboard

### Objective

Maximize upside capture from an AI-led risk-on equity regime using long-only U.S.-listed equities and ETFs. Cash or cash-like instruments are allowed for de-risking.

### Portfolio style

Concentrated, high beta when regime supports it, aware of narrative, momentum, catalysts, patient once positioned, willing to tolerate severe drawdowns

### Benchmarks

- Primary: QQQ.
- Secondary: SPY, SMH.
- Dashboard must separate portfolio value, benchmark comparison, drawdown, cash/exposure, and operating costs.

---

## 4. Strategy framework

Every serious decision should map to at least one strategy belief and one theme.

### Strategy beliefs

Thesis should map to specific 'strategy beliefs'. 

- **SB-001: Bull markets are reflexive:** In GREEN regimes, price momentum, narrative acceleration, institutional attention, and capital flows can reinforce each other.
- **SB-002: Direct AI infrastructure exposure is preferred:** Favor semiconductors, data centers, power, networking, cloud infrastructure, and bottleneck suppliers over vague "AI-enabled" exposure.
- **SB-003: Momentum needs backing:** Price strength should not be the entire thesis
- **SB-004: Market reaction to news:** In a bullish regime, good news should be rewarded more than bad news is punished.
- **SB-005: X alpha as narrative:** X can detect velocity, disagreement, crowding, and early themes, but X sentiment shouldn't be the entire thesis, double check.
- **SB-006: Few positions with conviction over constant activity:** Once exposure is in range, default to monitoring unless thesis invalidation or extraordinary opportunity appears.
- **SB-007: Losses do not automatically invalidate a thesis:** Review losses against price action, source evidence, regime behavior, and thesis invalidation criteria.
- **SB-008: Wins do not automatically validate a thesis:** Review major winners for process quality.

### Core themes

- `ai_semiconductors`
- `ai_infrastructure`
- `ai_bottlenecks`
- `data_centers`
- `power_grid_electrification`
- `financial_technology`
- `cloud_hyperscalers`
- `networking_interconnect`
- `robotics_automation`
- `cybersecurity`
- `ai_software`
- `broad_risk_on_tech`
- `macro_liquidity`
- `emergent_theme`

### Theme docs

Each theme should eventually have a concise memo with overview, tickers/ETFs, curated X accounts, primary sources, bull cases, bear cases, important metrics, invalidation patterns, and warning signs to watch for.

`emergent_theme` may create a research initiative, but cannot directly create an order until vetted

---

## 5. Operating modes and regime model

### Operating modes

- **Capital Deployment:** Used when exposure is below the regime target band. Run up to 3-5 full thesis chains/day. Goal is 3-6 high-conviction holdings.
- **Portfolio Management.** Used when exposure is within target. Run one portfolio management chain per trading day. New BUY/ADD chains require extraordinary-opportunity classification. Most days should end HOLD / NO ACTION.
- **Derisk** Used in RED or after major invalidation/risk triggers. Focus on TRIM, SELL, HOLD, cash, and re-entry watchlists. Significantly limit new high-beta buys while RED persists.

### Regimes

- **GREEN:** AI risk-on intact. Target exposure 80%-100%. High-beta buys and adds allowed when evidence supports them.
- **YELLOW:** AI risk-on weakening or unclear. Target exposure 40%-70%. New buys need stronger evidence, and smaller sizing, trims, and delayed entries are preferred.
- **RED:** AI risk-on broken or falling apart. Target exposure 0%-20%. No new high-beta buys: prioritize de-risking and re-entry research.

### Regime inputs

QQQ trend, SPY trend, SMH trend and leadership, AI leader relative strength, breadth, volatility/liquidity pressure, reaction to positive and negative AI news, AI capex outlook, hyperscaler commentary, bottlenecks, government AI spend, macro/liquidity, curated X narrative health, portfolio drawdown, and hit rate.

### Regime json output

```json
{
  "regime_state": "GREEN | YELLOW | RED",
  "confidence": 0.0,
  "as_of": "timestamp",
  "scores": {
    "qqq_trend": 0,
    "smh_leadership": 0,
    "ai_leader_relative_strength": 0,
    "breadth": 0,
    "news_reaction": 0,
    "ai_capex_outlook": 0,
    "macro_liquidity": 0,
    "x_narrative_health": 0,
    "portfolio_health": 0
  },
  "summary": "string",
  "state_change": {
    "changed": false,
    "previous_state": "GREEN",
    "reason": "string"
  }
}
```

---

## 6. Data and source policy

v0.1 should utilize free data. The system should reason from curated and/or public sources, curated X signals, portfolio state, historical daily price data, and Robinhood execution data.

### Preferred sources

- Robinhood adapter for portfolio state, positions, quotes, tradability, order review, and execution.
- SEC EDGAR APIs.
- FRED or similar free macro data.
- Company investor relations, press releases, earnings materials, and filings.
- Public news, research posts, ETF issuer pages, and government/regulatory sources.
- Curated X tracking via X API, the only paid source rn

### Reliability rule

Every source used in an Investment Decision Record must be timestamped and classified. If freshness, reliability, or access is insufficient, downgrade the signal to MONITOR/REVIEW or refuse to create an order intent.

### Historical price data

Daily OHLCV is sufficient for v0.1. Store date, open, high, low, close, adjusted close when available, volume, source, and fetched_at.

Cache prices for QQQ, SPY, SMH, active holdings, watchlist tickers, curated AI leaders, and trigger-generated candidates. Refresh after market close and on demand for new candidates.

Primary source candidate: `yfinance` or equivalent free daily OHLCV source. Fallbacks: Stooq, Alpha Vantage compact daily endpoint, or FMP Basic/free tier. Paid historical data should wait until free data blocks reliability, replay quality, dashboard quality, intraday triggers, or breadth/regime scoring.

---

## 7. Source packs

A Source pack is structured research context sent to the reasoning worker before a serious decision. Look into utilizing Gemini research reports for this (free student plan)

### Inputs

Ticker/ETF metadata, theme memo excerpts, strategy belief IDs, current regime, historical price summary, quote/tradability snapshot, company news, filings, earnings/capex materials, curated X signal summary, influential X posts/handles, opposing signals, prior decision records, portfolio state, and active position thesis.

### Source Pack object

```json
{
  "source_pack_id": "string",
  "created_at": "timestamp",
  "ticker": "string",
  "theme_ids": ["string"],
  "regime_snapshot_id": "string",
  "portfolio_snapshot_id": "string",
  "price_summary_id": "string",
  "sources": [
    {
      "source_id": "string",
      "source_type": "SEC | COMPANY_IR | NEWS | X | PRICE_DATA | MACRO | ETF_ISSUER | INTERNAL_MEMO",
      "title": "string",
      "url": "string",
      "published_at": "timestamp",
      "fetched_at": "timestamp",
      "summary": "string",
      "public_safe": true,
      "reliability_score": 0
    }
  ],
  "open_questions": ["string"],
  "known_risks": ["string"]
}
```

---

## 8. Curated X account graph

The X graph is versioned, categorized by theme, and scored over time. Accounts may belong to multiple categories.

### Account categories

Semiconductor specialist, AI infrastructure specialist, data center/power expert, macro/liquidity commentator, growth/tech equity investor, skeptic/short seller, market structure/flows account, company specific expert, news account, and general high-signal finance account.

### Account record

```json
{
  "handle": "@example",
  "display_name": "string",
  "categories": ["ai_semiconductors", "skeptic"],
  "included_date": "date",
  "included_reason": "string",
  "expected_signal_types": ["narrative_velocity", "counter_thesis", "theme_discovery"],
  "credibility_prior": 0.0,
  "max_signal_weight": 0.0,
  "allowed_uses": ["idea_source", "confirmation", "counter_thesis", "crowding_warning"],
  "not_allowed_uses": ["standalone_trade_authorization"],
  "status": "active | paused | removed"
}
```

### Account quality scoring

Score accounts on early theme detection, specificity, source quality, primary-source alignment, cross-cluster confirmation, counter-evidence handling, early vs late tendency, consensus amplification after price movement, hype/pump behavior, and usefulness for counter-thesis.

### X signal object

```json
{
  "x_signal_id": "string",
  "theme_or_ticker": "string",
  "as_of": "timestamp",
  "narrative_velocity": 0,
  "novelty": 0,
  "cross_cluster_confirmation": 0,
  "skeptic_strength": 0,
  "late_consensus_risk": 0,
  "account_quality_weighted_score": 0,
  "influential_accounts": [
    {
      "handle": "@example",
      "category": "string",
      "signal_type": "idea_source | confirmation | counter_thesis | crowding_warning",
      "weight": 0.0
    }
  ],
  "summary": "string"
}
```

---

## 9. Triggers and opportunity classification

The trigger system decides when the agent should reason more deeply.

### Trigger types

Price/volume breakout or breakdown, relative strength shift, regime change, curated X narrative velocity spike, high-quality skeptic/counter-thesis, earnings/capex/filing/news event, active position invalidation, exposure drift, and extraordinary-opportunity candidate.

May place automatic triggers for certain accounts and certain triggers. (Ex. important figures, significant events).

### Escalation

- Underexposed for regime: more BUY/ADD thesis chains are allowed.
- Within target exposure: new BUY/ADD thesis chains require extraordinary-opportunity classification.
- Overexposed: no new BUY chains; focus on TRIM/SELL/risk review.
- RED: no new high-beta BUY chains.

### Trigger object

```json
{
  "trigger_id": "string",
  "created_at": "timestamp",
  "trigger_type": "PRICE | VOLUME | X_SIGNAL | NEWS | FILING | EARNINGS | REGIME_CHANGE | POSITION_INVALIDATION | EXPOSURE_DRIFT",
  "ticker": "string",
  "theme_ids": ["string"],
  "description": "string",
  "raw_signal_refs": ["source_id"],
  "initial_priority": 0,
  "classification": "NOISE | MONITOR | REVIEW | EXTRAORDINARY_OPPORTUNITY",
  "classification_reason": "string",
  "next_action": "IGNORE | WATCHLIST | COMPACT_REVIEW | FULL_THESIS_CHAIN"
}
```

### Classification

- **NOISE:** common hivemind yap, duplicated information, vague hype, or movement with no new evidence.
- **MONITOR:** interesting but incomplete; add to watchlist or backlog.
- **REVIEW:** meaningful enough for compact review or active thesis update.
- **EXTRAORDINARY_OPPORTUNITY:** strong enough to trigger a full thesis chain even when exposure is already in range.

### Score and gates

These are all prone to adjustments

- Score novelty 0-20, magnitude 0-20, causal link 0-20, cross-source confirmation 0-15, market confirmation/mispricing 0-15, framework fit 0-10, actionability 0-10, late-consensus penalty 0 to -20, and weak-source penalty 0 to -20.

- Thresholds: NOISE below 40 or failed hard gate, MONITOR 40-59, REVIEW 60-74, EXTRAORDINARY_OPPORTUNITY 75+ with all gates passed.

- A trigger cannot become extraordinary if it lacks a plausible causal link, has no allowed ticker/ETF expression, cannot map to a strategy belief, relies on stale or unavailable data

Questions before escalation: what is new, why it matters, causal chain, investable expression, whether market has priced it in, contradictory evidence, why it is not late-consensus hype

---

## 10. Research and decision workflows

### Research Prior

Before a full thesis chain, the agent receives human curated context to supplement autonomous research. Handpicked context includes strategy memos, theme memos, curated X accounts, internal examples, and approved/disapproved historical cases. Autonomous research includes public company information, filings, news, earnings materials, macro data, price data, and public web sources.

'Research prior' should score or summarize macro environment, regime fit, recent narrative, curated X signal, high-signal commentary, primary-source validation, price/volume confirmation, what is priced in, portfolio fit, risk, and invalidation. Output candidates, themes, supporting evidence, contradictory evidence, open questions, and initial classification: PASS / WATCHLIST / FULL THESIS CANDIDATE.

### Full Thesis Chain

Used for new BUY/ADD decisions and meaningful TRIM/SELL decisions.

Inputs: portfolio brief, thesis generation history (accepts & rejects), research prior, maybe more

Workflow:

1. Pick: Based on research prior & other factors, determine candidate to develop thesis upon
1. Initial thesis: opportunity, timing, evidence, expression, target weight.
2. Counter-thesis: strongest objection, what is priced in, what could break, contradictory evidence.
3. Refine or reject initial thesis: Improve judgement. If the counter-thesis is strong, reevaluate stance without automatically neutering boldness.
4. Alternative investment review: selected ticker/ETF, other similar investments
5. Refined thesis: thesis, confidence, sizing, invalidation, add/trim/exit triggers.
6. Final decision: BUY / ADD / TRIM / SELL / HOLD / PASS / WATCHLIST.

Early exit if mandate fails, source quality is insufficient, causal link is missing, no actionable expression exists, idea is late-consensus hype, regime disallows the action, or invalidation criteria cannot be identified.

Should loop until viable stock picks run out, max stocks analyzed in a loop should be like 3, so pick top 3 from research prior output

### Daily Portfolio Management Chain

Purpose: avoid unnecessary overtrading while monitoring invalidation and extraordinary opportunity.

Inputs: portfolio state, exposure vs regime target, active thesis records, regime snapshot, price/volume changes, curated X summary, relevant news/filing/earnings updates, and current triggers.



Outputs: regime status, active position health (INTACT / WEAKENED / INVALIDATED), holding-level action (HOLD / ADD / TRIM / SELL / FULL REVIEW), portfolio-level action (NO ACTION / REBALANCE / DE-RISK / RUN EXTRAORDINARY-OPPORTUNITY CHAIN), and short public summary.

Default expected outcome on most days: no action, continue holding, thesis intact, no full thesis chain required.

---

## 11. Records and schemas

### Position lifecycle

States: WATCHLIST, BUY, ADD, HOLD, TRIM, SELL, POSTMORTEM.

```json
{
  "ticker": "string",
  "theme_ids": ["string"],
  "original_thesis": "string",
  "refined_thesis": "string",
  "entry_date": "date",
  "entry_price": 0.0,
  "current_weight": 0.0,
  "target_weight": 0.0,
  "add_conditions": ["string"],
  "trim_conditions": ["string"],
  "exit_conditions": ["string"],
  "invalidation_criteria": ["string"],
  "next_review_trigger": "string",
  "current_thesis_status": "INTACT | WEAKENED | INVALIDATED",
  "last_review_date": "date",
  "source_ids": ["string"]
}
```

### Investment Decision Record

The Investment Decision Record is the core audit artifact. One record represents one ticker/ETF decision only. Allowed decisions: BUY, ADD, TRIM, SELL, HOLD, PASS, WATCHLIST.

```json
{
  "decision_id": "string",
  "created_at": "timestamp",
  "ticker": "string",
  "asset_type": "EQUITY | ETF",
  "decision": "BUY | ADD | TRIM | SELL | HOLD | PASS | WATCHLIST",
  "theme_ids": ["string"],
  "strategy_belief_ids": ["string"],
  "trigger_id": "string",
  "trigger_type": "string",
  "operating_mode": "CAPITAL_DEPLOYMENT | PORTFOLIO_MANAGEMENT | DE_RISKING",
  "regime_state": "GREEN | YELLOW | RED",
  "regime_scores": {},
  "portfolio_context": {},
  "source_pack_id": "string",
  "initial_thesis": "string",
  "counter_thesis": "string",
  "adversarial_refinement": "string",
  "refined_thesis": "string",
  "variant_perception": "string",
  "what_is_priced_in": "string",
  "thesis_invalidation_criteria": ["string"],
  "add_conditions": ["string"],
  "trim_conditions": ["string"],
  "exit_conditions": ["string"],
  "proposed_target_weight": 0.0,
  "final_target_weight": 0.0,
  "sizing_rationale": "string",
  "x_signal_usage": {
    "used": false,
    "usage_type": "IDEA_SOURCE | CONFIRMATION | COUNTER_THESIS | CROWDING_WARNING | IRRELEVANT",
    "summary": "string",
    "confirmed_outside_x": false
  },
  "source_claims": [
    {
      "claim": "string",
      "source_ids": ["string"],
      "source_type": "string",
      "source_timestamp": "timestamp",
      "confidence": 0.0,
      "public_safe": true
    }
  ],
  "policy_check_results": {},
  "final_decision": "string",
  "public_summary": "string",
  "internal_notes": "string",
  "order_intent_id": "string | null",
  "broker_execution_record_id": "string | null"
}
```

### Order separation

```text
Investment Decision Record
> Schema Validation
> Policy Checks
> Approved Order Intent
> Broker Execution Record
> Public Ledger Entry
```

---

## 12. Policy engine, limits, execution

The policy engine is deterministic code that will downsize or reject decisions. Shouldn't increase risk beyond the agent's requested exposure.

### Hard rejects

Reject order intent if ticker, asset type, thesis, invalidation criteria, sources, source claims, regime, exposure, position size, dashboard/log write, broker review, quote freshness, or account data fails policy.

### Sizing adjustment

The policy engine may reduce target weight for single-name, ETF, or theme concentration for following reasons:
- If in YELLOW regime: good but not extraordinary thesis quality
- weak liquidity/spread
- portfolio exposure already near target

### Initial limits

- Max stock target weight: 20%
- Max ETF target weight: 50%
- Max holdings: 3-6
- Max executed trades/day: 2
- Max full thesis chains/loops per day in Capital Deployment: ~3-5
- Max full thesis chains/day in Portfolio Management: 0-1 unless invalidation occurs
- No new high-beta buys in RED.

### Order execution

Default to limit orders. Market orders may be allowed only for liquid names with tight spreads, small notional size, normal market conditions, not near open/close

```text
Decision Record
> Policy Checks
> Order Intent
> Broker Quote
> Broker Tradability Check
> Broker Review
> Submit Order
> Store Broker Execution Record
> Update Public Ledger
```

### Broker execution record

```json
{
  "broker_execution_record_id": "string",
  "order_intent_id": "string",
  "ticker": "string",
  "side": "BUY | SELL",
  "order_type": "MARKET | LIMIT",
  "notional_or_quantity": "string",
  "limit_price": 0.0,
  "submitted_at": "timestamp",
  "status": "SUBMITTED | FILLED | PARTIALLY_FILLED | CANCELED | FAILED",
  "broker_order_id": "string",
  "execution_price": 0.0,
  "raw_broker_payload_private": true
}
```

---

## 13. Architecture and state machine

### Components

- **Investment Intelligence MCP/API:** strategy constitution, theme taxonomy, source packs, regime snapshots, schemas, policy checks, and records database.
- **Codex Reasoning Worker:** runs predetermined thesis/management workflows, calls MCP/API tools, writes structured records back through MCP/API.
- **Backend State Machine:** validates schemas, runs policy checks, prevents duplicate orders, manages order intent status, controls broker execution, logs transitions.
- **Robinhood Execution Adapter:** portfolio state, positions, quotes, tradability, order review, order placement, and order status.
- **Public Dashboard:** public portfolio, decision feed (could be cool to make an interactive graph interface to showcase agent workflow), regime color indicator, rejected decisions log, audit log

### High-level flow

```text
Trigger / Schedule
> Source Pack Builder
> Candidate Screen
> Codex Reasoning Worker
> Investment Decision Record
> Schema Validation
> Policy Engine
> Order Intent
> Broker (Robinhood) Execution Adapter
> Public Dashboard / Ledger
```

### Decision statuses

`trigger_detected`, `source_pack_created`, `candidate_screened`, `decision_record_created`, `schema_validated`, `schema_failed`, `policy_approved`, `policy_rejected`, `order_intent_created`, `broker_reviewed`, `submitted`, `filled`, `partially_filled`, `canceled`, `failed`, `published`.

### Idempotency

Every executable workflow must have stable `trigger_id`, `source_pack_id`, `decision_id`, `order_intent_id`, and `broker_execution_record_id`. After a crash, resume from the last safe state rather than creating duplicate orders.

---

## 14. Dashboard

The dashboard should showcase agent process along with nice P&L display (hopefully just P display)

### Core pages

- **Live Portfolio:** holdings, weights, cash, exposure, benchmark comparison, drawdown, regime indicator
- **Decision Feed:** decision type, public summary, timestamp, regime state, policy status, thesis, counter-thesis, refinement, invalidation, sizing, source claims, policy checks.
- **Workflow Graph:** interactive trigger-to-ledger node graph with clickable explanations.

---

## 15. Documentation, cost, and evals

### Static docs to develop

- `investment_mandate_v0.1.md`
- `strategy_beliefs_v0.1.md`
- `theme_taxonomy_v0.1.yaml`
- `thesis_chain_prompt_v0.1.md`
- `daily_portfolio_management_prompt_v0.1.md`
- `source_policy_v0.1.md`
- `risk_policy_v0.1.md`
- `order_execution_policy_v0.1.md`
- `eval_rubric_v0.1.md`
- Theme files such as `themes/ai_semiconductors.md`, `themes/power_grid_electrification.md`, and `themes/data_centers.md` (shoudl cover all the themes)

The human may add strategy memos, resonant memos, approved/disapproved historical trades, and market taste/framework notes as aligning context.

### Cost policy

Assume a $500 live account, Codex subscription powered reasoning for LLM-heavy workflows, one daily portfolio management chain in steady state, rare full thesis chains, backend-owned retrieval/validation/policy/order/dashboard work, and minimal paid API spend.

Expected monthly operating cost excluding capital:

- Practical demonstration v0.1: $30-$100/month.

Cost buckets: Codex/ChatGPT subscription ~$20/month if limits suffice, could use multiple chatGPT accounts if necessary, hosting/API $0-$25, database/storage $0-$25, dashboard/domain/logging $0-$30, historical price data $0 target, market/fundamental data $0 initially, X/Grok/social tracking ~$10-$30

Dashboard should separate portfolio P&L, benchmark-relative P&L, operating costs, and all-in experiment cost.

### Evals

Test historical and synthetic cases for:

- Preference alignment: approves trades the human would approve, rejects trades the human would hate, avoids generic consensus.
- Policy compliance: obeys mandate/risk/source constraints, disallowed-asset rules, invalidation requirements, and regime restrictions.
- Signal testing: X vs no X, skeptics included vs removed, technical/price context vs none, extra validation vs none.
- Counter-thesis quality: improves thesis, identifies real risk, avoids neutering good ideas or being ignored.
- Historical replay: uses only information available at the time, avoids lookahead bias, versions account lists to reduce survivorship bias.
- Dashboard/audit quality: explains actions, traces sources, shows policy failures, explains no-action days.

---

## 16. MVP build plan

### Phase 0: Spec and schemas

Finalize this spec and create JSON schemas for Regime Snapshot, Source Pack, Trigger, X Signal, Investment Decision Record, Active Position Record, Order Intent, and Broker Execution Record.

### Phase 1: Local simulation with live-like records

Build local MCP/API, source pack builder, daily price cache, and decision record storage. Use Codex worker to generate mock decision records. No broker execution yet.

### Phase 2: Live $500 account with strict policy

Connect broker execution adapter, start live with tiny account, enforce strict order limits, publish dashboard, and log all decisions and rejections.

### Phase 3: Better triggers and evals

Add curated X tracking, trigger classification, daily portfolio management, historical/synthetic evals, and ablation tests.

### Phase 4: Hardening

Improve state machine, retries/fallbacks, monitoring, dashboard, and paid data decisions if needed.

---

## 17. Open questions

- Exact curated X accounts (I have a good idea)
- Daily portfolio management timing
- GREEN/YELLOW/RED thresholds.
- Initial max position sizes
- Exact Daily Portfolio Management and Full Thesis Chain prompts.
- Exact backend state machine details.

---

## 18. Immediate next steps

1. Finalize Investment Decision Record schema
2. Finalize Daily Portfolio Management Chain prompt
3. Define initial position/order limits for the $500 account.
4. Create initial theme files.
5. Create initial curated X account list
6. Decide free historical price source and cache format
7. Build local MCP/API skeleton.
8. Build dashboard skeleton with fake records
9. Run first mock Codex generated decision records
