import { useState } from 'react'
import { usePublic } from './api'
import { Chevron, Empty, Fact, ResourceNotice, SectionBoundary } from './common'
import { label, ruleValue, thresholdValue, weight, when } from './format'
import { decisionUrl, Link } from './navigation'
import type { PolicyCatalog, PolicyCheck, PolicyEvaluation, Scope } from './types'

// The reference design marks each check rather than badging it, so a column of results
// reads down the page. A result the gate didn't reach is not a pass and not a failure.
const MARKS: Record<string, string> = { passed: '✓', failed: '✗', not_applicable: '–', missing_input: '?' }

function checkTone(result: string) {
  return result === 'passed' ? 'passed' : result === 'failed' ? 'failed' : 'inconclusive'
}

function CheckRow({ check }: { check: PolicyCheck }) {
  return <details className={`policy-check policy-check--${checkTone(check.result)}`}>
    <summary>
      <span className="check-mark" aria-hidden="true">{MARKS[check.result] ?? '·'}</span>
      <span className="check-name"><code className="rule-code">{check.rule_id}</code>{check.name}<span className="sr-only">, {label(check.result)}</span></span>
      <span className="mono">{check.observed === null || check.observed === undefined ? '—' : ruleValue(check.observed, check.unit)}</span>
      <span className="mono threshold">{thresholdValue(check.threshold, check.unit)}</span>
    </summary>
    <div className="check-detail">
      <dl className="detail-grid"><Fact name="Result">{label(check.result)}</Fact><Fact name="Comparator">{check.comparator ? label(check.comparator) : 'Not recorded'}</Fact><Fact name="Headroom">{check.headroom === null || check.headroom === undefined ? 'Not comparable' : ruleValue(check.headroom, check.unit)}</Fact><Fact name="Scope">{label(check.scope)}</Fact></dl>
      {(check.explanation ?? check.failure_explanation) && <p>{check.explanation ?? check.failure_explanation}</p>}
      <p className="section-note">{check.result === 'missing_input' ? 'Required context was not recorded; this is different from a failed check.' : check.result === 'not_applicable' ? 'This rule did not apply to the recorded proposal.' : 'This is the historical evaluation of the proposal and its recorded inputs.'}</p>
    </div>
  </details>
}

export function PolicyChecks({ evaluation }: { evaluation: PolicyEvaluation }) {
  if (evaluation.status !== 'available') return <Empty>{evaluation.reason ? label(evaluation.reason) : 'Historical rule evaluations were not recorded.'}</Empty>
  return <>
    <p className="section-note">Evaluated {when(evaluation.evaluated_at)} · {evaluation.policy_version}</p>
    <div className="policy-checks">
      <div className="check-heading" aria-hidden="true"><span /><span>Rule</span><span>Observed</span><span>Threshold</span></div>
      {evaluation.checks.map(check => <CheckRow check={check} key={check.rule_id} />)}
    </div>
  </>
}

export function Policies({ scope }: { scope: Scope }) {
  const resource = usePublic<PolicyCatalog>(`/api/public/v2/portfolios/${scope}/policy`, 'policy')
  const [category, setCategory] = useState('decision_policy')
  const data = resource.data
  const rules = category === 'decision_policy' ? data?.decision_rules : category === 'posture' ? data?.posture : data?.execution_controls
  return <section className="policies" aria-label="Policy catalog">
    <ResourceNotice resource={resource} name="policies" />
    <SectionBoundary resetKey={data} retry={resource.refresh} name="policy catalog">
      {data && (data.status === 'unavailable' ? <Empty>The policy catalog has not been published.</Empty> : <>
        <div className="policy-meta"><span>Policy set <span className="mono">{data.version ?? 'not recorded'}</span></span><span>{(data.decision_rules?.length ?? 0) + (data.posture?.length ?? 0) + (data.execution_controls?.length ?? 0)} published rules</span>{data.published_at && <span>Published {when(data.published_at)}</span>}</div>
        <div className="category-controls" aria-label="Policy category">{[['decision_policy', 'Decision policy'], ['posture', 'Posture guidance'], ['execution_control', 'Execution controls']].map(([value, name]) => <button key={value} aria-pressed={value === category} onClick={() => setCategory(value)}>{name}</button>)}</div>
        <p className="section-note">{category === 'decision_policy' ? 'Deterministic checks apply to recorded proposals. Approval does not establish execution.' : category === 'posture' ? 'Strategy guidance is distinct from a deterministic approval gate.' : 'Account, quote and execution requirements are checked separately from investment policy.'}</p>
        {rules?.length ? <>
          <div className="check-heading rule-heading" aria-hidden="true"><span /><span>Rule</span><span>Threshold</span></div>
          {rules.map(rule => <details className={`policy-row${rule.category === 'execution_control' ? ' policy-row--automated' : ''}`} key={rule.rule_id}>
            <summary><Chevron />
              <span className="rule-copy">
                <span className="rule-name">{rule.name} <code className="rule-code">{rule.rule_id}</code></span>
                <span className="rule-description">{rule.description ?? rule.failure_explanation ?? 'The configured profile and recorded preflight determine this control.'}</span>
              </span>
              <span className="rule-kind mono">{thresholdValue(rule.threshold, rule.unit)}</span>
            </summary>
            <div className="policy-detail">
              <dl className="detail-grid"><Fact name="Category">{label(rule.category)}</Fact><Fact name="Scope">{label(rule.scope)}</Fact><Fact name="Comparator">{rule.comparator ? label(rule.comparator) : 'Not recorded'}</Fact><Fact name="Version">{rule.version ?? data.version ?? 'Not recorded'}</Fact></dl>
              {rule.last_triggered ? <Link href={decisionUrl(rule.last_triggered.public_id, scope)}>Last triggered {when(rule.last_triggered.created_at)} →</Link> : <p className="quiet">No published trigger for this rule.</p>}
            </div>
          </details>)}
        </> : <Empty>No rules are published in this category.</Empty>}
        <details className="compact-disclosure"><summary><Chevron /> Current exposure observations</summary><div className="disclosure-body">
          {data.current_exposure?.length ? data.current_exposure.map(item => <div className="check-row" key={item.ticker}><span>{item.ticker}</span><span className="mono">{weight(item.weight)}</span></div>) : <Empty>No current holding exposures are available.</Empty>}
          {data.current_theme_exposure?.map(item => <div className="check-row" key={item.theme}><span>{label(item.theme)}</span><span className="mono">{weight(item.weight)}</span></div>)}
          <p className="section-note">Appreciation beyond an entry limit isn't automatically a current violation. These observations don't replace historical entry checks.</p>
        </div></details>
        <details className="compact-disclosure"><summary><Chevron /> Policy version history</summary><div className="disclosure-body">{data.history?.map(version => <div className="version-entry" key={version.version}><strong className="mono">{version.version}</strong><p>{version.change}</p><p className="quiet">{version.effective_from ? `Effective ${when(version.effective_from)}` : 'Historical effective date was not recorded.'}</p></div>)}</div></details>
      </>)}
    </SectionBoundary>
  </section>
}
