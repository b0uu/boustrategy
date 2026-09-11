export type Scope = 'live' | 'paper'
export type Range = '1M' | '3M' | 'YTD' | 'All'
export type DecimalValue = string | number | null
export interface Metadata { api_version: number; revision: number; server_now: string; published_at: string | null }
export interface DecisionItem {
  public_id: string; public_run_id: string | null; portfolio_id: Scope; mode: Scope
  ticker: string; company_name: string | null; created_at: string; decision: string
  public_summary: string; summary_truncated: boolean; policy_outcome: string
  schema_outcome: string; lifecycle: string; regime: string; theme: string | null
}
export interface FeedPage extends Metadata { items: DecisionItem[]; total: number; next_cursor: string | null }
export interface Conditions { invalidation: string[]; add: string[]; trim: string[]; exit: string[] }
export interface PublicSource { public_id: string; title: string; publisher: string; published_on: string | null; source_type: string; url: string | null; excerpt: string | null }
export interface Claim { public_id: string; claim: string; evidence_confidence: number | null; source_ids: string[] }
// A linked X post: the dashboard publishes its canonical link, handle and the review's own summary, never post text.
export interface XPost { url: string; handle: string; role: string; summary: string | null }
export interface Narrative {
  company_name: string | null
  stages: Array<{ stage: string; summary: string; started_at: string | null; completed_at: string | null; claim_ids: string[] }>
  claims: Claim[]; sources: PublicSource[]
  variant_perception: { consensus: string | null; disagreement: string | null; evidence: string | null; falsification: string | null; claim_ids: string[] } | null
  trigger_summary: string | null; x_summary: string | null; x_posts?: XPost[]; conviction_rationale: string | null
  extraordinary_opportunity_summary: string | null; conditions: Conditions | null
}
export interface ThesisReview { state: string; reviewed_at: string | null; summary: string | null; reason?: string; narrative?: Narrative | null; author?: string }
export interface Position {
  ticker: string; name?: string | null; shares: DecimalValue; average_cost: DecimalValue
  latest_price: DecimalValue; market_value: DecimalValue; weight: number | null
  unrealized_return_percent: DecimalValue; theme: string | null; asset_class?: string
  price_quality?: string; quote_at?: string | null; latest_public_summary: string | null
  latest_decision_id: string | null; holding_episode_id?: string | null; thesis_review?: ThesisReview
}
export interface Episode { episode_id: string; ticker: string; status: string; opened_at: string | null; first_observed_at: string; closed_at: string | null; quantity: string; thesis_review?: ThesisReview }
export interface Overview extends Metadata {
  portfolio_id: Scope; mode: Scope; status: string; reason: string | null; data_as_of: string | null
  equity: DecimalValue; cash: DecimalValue; portfolio_state?: string; decisions_today: number; reviews_today: number
  decision_counts: Record<string, number>; capabilities: { returns: boolean; cash: boolean; quantities: boolean }
  allocation?: Array<{ asset_class: string; market_value: DecimalValue; weight: number | null }>
  daily_pnl?: { status: string; reason: string | null; amount: DecimalValue; net_external_flows?: DecimalValue; baseline_at?: string }
  last_complete_valuation?: { at: string; equity: DecimalValue } | null
  holding_episodes?: { status: string; reason?: string; items: Episode[]; total?: number; truncated?: boolean }
}
export interface Positions extends Metadata { portfolio_id: Scope; mode?: Scope; status: string; valuation_status: string; reason: string | null; data_as_of: string | null; items: Position[] }
export interface ChartPoint { at: string; equity: DecimalValue; return_percent: DecimalValue; quality: string }
export interface Performance extends Metadata {
  portfolio_id: Scope; range: Range; status: string; reason: string | null; return_percent: DecimalValue
  investment_pnl?: DecimalValue; net_external_flows?: DecimalValue; observed_drawdown_percent?: DecimalValue
  start_at?: string; end_at?: string; requested_start_at?: string; range_is_partial?: boolean; period_label?: string
  history: ChartPoint[]; benchmarks?: Array<{ ticker: string; primary: boolean; status: string; reason: string | null; return_percent: DecimalValue; convention: string }>
  chart_sampling?: { status: string; reason: string | null; source_points: number; limit: number }
  methodology?: Record<string, string>
}
export interface PolicyRule { rule_id: string; name: string; category?: string; version?: string; scope?: string; threshold?: string | number | boolean | null; comparator?: string; unit?: string; failure_explanation?: string; description?: string; last_triggered?: { public_id: string; created_at: string } | null }
export interface PolicyCatalog extends Metadata { status?: string; version?: string; decision_rules?: PolicyRule[]; posture?: PolicyRule[]; execution_controls?: PolicyRule[]; history?: Array<{ version: string; change: string; effective_from: string | null }>; current_exposure?: Array<{ ticker: string; weight: number | null; as_of: string | null; interpretation: string }>; current_theme_exposure?: Array<{ theme: string; weight: number }> }
export interface PolicyCheck extends PolicyRule { result: string; observed?: string | number | boolean | null; headroom?: number | null; applicability?: string; explanation?: string | null; exception_applied?: boolean }
export interface PolicyEvaluation { status: string; reason?: string; policy_version: string | null; validator_version: string | null; authored_schema_version?: string | null; validator_schema_sha256?: string; evaluated_at?: string; checks: PolicyCheck[]; regime_evidence?: { raw_state: string; published_state: string; score: number; as_of: string; components: Array<{ name: string; value: number; points: number; unit: string }> } | null; input_provenance?: Record<string, string | null> }
export interface Attempt { public_id: string; attempt_number: number; status: string; stage: string; requested_model: string; observed_model: string | null; started_at: string; heartbeat_at: string; finished_at: string | null; reason: string | null; summary: string | null }
export interface ActivityItem { public_id: string; origin: string; session_date: string; slot?: string; prepared_at?: string; status: string; reason?: string; summary?: string | null; due_at?: string; completed_at?: string; latest_attempt?: Attempt | null; attempt_count: number; attempts_truncated: boolean; attempts?: Attempt[]; lease_expires_at?: string }
export interface ActivityPage extends Metadata { items: ActivityItem[]; next_cursor: string | null; total: number; activity_revision?: number }
export interface Schedule { schedule_mode: string; timezone: string; revision: number; enabled: boolean; paused: boolean; next_due_at: string | null; reason: string | null; observer_as_of: string | null; observer_max_age_seconds: number; grace_seconds: number }
export interface Runtime extends Metadata { status?: string; reason?: string; as_of?: string; latest_run: ActivityItem | null; active_run?: ActivityItem | null; schedules: Schedule[]; schedule_mode?: string }
// summary_truncated is computed for feed rows only; the detail payload carries full prose.
export interface Decision extends Omit<DecisionItem, 'summary_truncated'>, Metadata {
  narrative: Narrative | null; narrative_status: string; proposed_target_weight: number | null
  final_target_weight: number | null; current_weight: number | null; policy_evaluation: PolicyEvaluation
  claims: Array<{ claim: string; source_type: string; source_timestamp: string }>
  x_usage: { used: boolean; usage_type: string; summary: string; confirmed_outside_x: boolean }
  x_posts?: XPost[]
  model_provenance: { status: string; model_label?: string | null; requested_model?: string; observed_model?: string | null }
  execution: { status: string; reason?: string; quantity: DecimalValue; gross_notional: DecimalValue; fees: DecimalValue; total?: number; truncated?: boolean; slippage_reason?: string; items: Array<{ occurred_at: string; side: string; quantity: string; price: string; gross_notional: string; fee: string | null; order_state: string; canceled_quantity: string; settled_at: string | null }> }
  sized_order: { notional: DecimalValue; limit_price: DecimalValue; side: string; order_type: string; sized_at: string; expires_at: string; status: string } | null
  requested_order: { notional: DecimalValue; limit_price: DecimalValue; order_type: string; broker_status: string; submitted_at: string } | null
  milestones: Array<{ stage: string; occurred_at: string; time_precision: string }>; milestones_total?: number; milestones_truncated?: boolean
  extraordinary_opportunity?: { invoked: boolean; scope: string[]; summary: string | null }
}
