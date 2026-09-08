import { useState } from 'react'
import { usePublic } from './api'
import { Badge, Chevron, Empty, Fact, ResourceNotice, SectionBoundary } from './common'
import { label, ruleValue, weight, when } from './format'
import { decisionUrl, Link } from './navigation'
import type { PolicyCatalog, PolicyEvaluation, Scope } from './types'

export function PolicyChecks({ evaluation }: { evaluation: PolicyEvaluation }) {
  if (evaluation.status !== 'available') return <Empty>{evaluation.reason ? label(evaluation.reason) : 'Historical rule evaluations were not recorded.'}</Empty>
  return <>
    <p className="section-note">Evaluated {when(evaluation.evaluated_at)} · {evaluation.policy_version}</p>
    <div className="policy-checks">{evaluation.checks.map(check => <details className="policy-row" key={check.rule_id}><summary><Chevron /><span>{check.name}</span><Badge value={check.result} /></summary><div className="policy-detail">
      <dl className="detail-grid"><Fact name="Observed">{ruleValue(check.observed, check.unit)}</Fact><Fact name="Threshold">{ruleValue(check.threshold, check.unit)}{check.comparator ? ` (${check.comparator})` : ''}</Fact><Fact name="Headroom">{check.headroom === null || check.headroom === undefined ? 'Not comparable' : ruleValue(check.headroom, check.unit)}</Fact><Fact name="Scope">{label(check.scope)}</Fact></dl>
      {check.explanation && <p>{check.explanation}</p>}
      <p className="section-note">{check.result === 'missing_input' ? 'Required context was not recorded; this is different from a failed check.' : check.result === 'not_applicable' ? 'This rule did not apply to the recorded proposal.' : 'This is the historical evaluation of the proposal and its recorded inputs.'}</p>
    </div></details>)}</div>
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
        <div className="category-controls" aria-label="Policy category">{[['decision_policy', 'Decision policy'], ['posture', 'Posture guidance'], ['execution_control', 'Execution controls']].map(([value, name]) => <button key={value} aria-pressed={value === category} onClick={() => setCategory(value)}>{name}</button>)}</div>
        <p className="section-note">{category === 'decision_policy' ? 'Deterministic checks apply to recorded proposals. Approval does not establish execution.' : category === 'posture' ? 'Strategy guidance is distinct from a deterministic approval gate.' : 'Account, quote and execution requirements are checked separately from investment policy.'}</p>
        {rules?.map(rule => <details className="policy-row" key={rule.rule_id}><summary><Chevron /><span>{rule.name}</span><span className="mono quiet">{rule.threshold === null || rule.threshold === undefined ? 'Contextual' : ruleValue(rule.threshold, rule.unit)}</span></summary><div className="policy-detail">
          <p>{rule.description ?? rule.failure_explanation ?? 'The configured profile and recorded preflight determine this control.'}</p>
          <dl className="detail-grid"><Fact name="Category">{label(rule.category)}</Fact><Fact name="Scope">{label(rule.scope)}</Fact><Fact name="Version">{rule.version ?? data.version ?? 'Not recorded'}</Fact></dl>
          {rule.last_triggered ? <Link href={decisionUrl(rule.last_triggered.public_id, scope)}>Last triggered {when(rule.last_triggered.created_at)} →</Link> : <p className="quiet">No published trigger for this rule.</p>}
        </div></details>)}
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
