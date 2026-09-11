import { useEffect, useRef, useState } from 'react'
import { PublicError, usePublic } from './api'
import { Badge, Chevron, Empty, Fact, RequestIssue, ResourceNotice, SectionBoundary, TextList } from './common'
import { amount, clock, label, money, publicUrl, ruleValue, weight, when } from './format'
import { dashboardUrl, decisionUrl, Link } from './navigation'
import { PolicyChecks } from './Policies'
import type { Decision as DecisionData, Scope } from './types'

const stageNames: Record<string, string> = { initial_thesis: 'Initial thesis', counter_thesis: 'Counter-thesis', adversarial_refinement: 'Adversarial refinement', refined_thesis: 'Refined thesis', what_is_priced_in: 'What is priced in' }
const stageColors: Record<string, string> = { initial_thesis: 'indigo', counter_thesis: 'coral', adversarial_refinement: 'amber', refined_thesis: 'green', what_is_priced_in: 'text-2' }

export function DecisionPage({ publicId, legacy, scope, back }: { publicId?: string; legacy?: [string, string]; scope: Scope; back: string }) {
  const url = legacy ? `/api/public/v2/legacy-decisions/${encodeURIComponent(legacy[0])}/${encodeURIComponent(legacy[1])}` : `/api/public/v2/decisions/${encodeURIComponent(publicId!)}`
  const resource = usePublic<DecisionData>(url, 'decision', 30_000)
  const [copy, setCopy] = useState<'idle' | 'copied' | 'manual'>('idle')
  const [exportError, setExportError] = useState<PublicError | null>(null)
  const [exporting, setExporting] = useState(false)
  const download = useRef<AbortController | null>(null)
  const copyInput = useRef<HTMLInputElement>(null)
  useEffect(() => () => download.current?.abort(), [])
  useEffect(() => { if (copy === 'manual') { copyInput.current?.focus(); copyInput.current?.select() } }, [copy])
  const data = resource.data
  const withdrawn = resource.error?.status === 410 || exportError?.status === 410
  if (withdrawn) return <div className="request-state" role="alert"><h1 tabIndex={-1}>This record has been withdrawn</h1><p>Its previous content and downloads are no longer shown.</p><Link href={back}>Back to feed</Link></div>
  if (!data) return <div className="trace request-state"><h1 tabIndex={-1}>{resource.error?.status === 404 ? 'Public decision not found' : 'Decision trace'}</h1><ResourceNotice resource={resource} name="decision trace" /><Link href={back}>Back to feed</Link></div>
  const shareUrl = location.origin + decisionUrl(data.public_id, data.mode)
  const copyLink = async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(shareUrl)
      setCopy('copied')
    } catch { setCopy('manual') }
  }
  const exportRecord = async (format: 'json' | 'csv') => {
    if (exporting || (exportError && exportError.retryAt > Date.now())) return
    setExporting(true)
    setExportError(null)
    download.current = new AbortController()
    const endpoint = `/api/public/v2/decisions/${data.public_id}/export?format=${format}`
    try {
      const response = await fetch(endpoint, { signal: download.current.signal, cache: 'no-store' })
      if (!response.ok) {
        if (response.status === 410) {
          window.dispatchEvent(new CustomEvent('public-retraction', { detail: endpoint }))
          throw new PublicError(410, 'This record has been withdrawn from publication.')
        }
        const retry = response.headers.get('Retry-After')
        const retryAt = retry && /^\d+$/.test(retry) ? Date.now() + Number(retry) * 1000 : retry ? Date.parse(retry) : 0
        throw new PublicError(response.status, 'The download is unavailable. Please try again.', Number.isFinite(retryAt) ? retryAt : 0)
      }
      const blob = await response.blob()
      if (blob.size > 2_000_000) throw new PublicError(502, 'The download exceeded the expected public record size.')
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = `${data.public_id}.${format}`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (failure) {
      if (!download.current.signal.aborted) setExportError(failure instanceof PublicError ? failure : new PublicError(0, 'The download could not be completed.'))
    } finally { setExporting(false) }
  }
  const narrative = data.narrative
  const regime = data.policy_evaluation.regime_evidence
  return <div className="trace">
    <Link className="back" href={back}>← Feed</Link>
    <ResourceNotice resource={resource} name="decision trace" />
    <SectionBoundary resetKey={data} retry={resource.refresh} name="decision trace">
      <header className="trace-head"><div className="trace-title"><h1 className="mono" tabIndex={-1}>{data.ticker}</h1><span className="action">{label(data.decision)}</span><Badge value={data.lifecycle} /><time dateTime={data.created_at}>{when(data.created_at)}</time></div>
        <p>{data.public_summary}</p>
        <dl className="trace-meta"><Fact name="Decision">{data.public_id}</Fact><Fact name="Review">{data.public_run_id ?? 'Not recorded'}</Fact><Fact name="Portfolio">{data.mode === 'paper' ? 'Paper simulation' : 'Live account'}</Fact><Fact name="Model">{data.model_provenance.observed_model ?? data.model_provenance.requested_model ?? data.model_provenance.model_label ?? "Not recorded"}</Fact><Fact name="Schema">{label(data.schema_outcome)}</Fact><Fact name="Policy">{label(data.policy_outcome)}</Fact></dl>
        <div className="trace-actions"><button className="text-button" onClick={() => void copyLink()}>{copy === 'copied' ? 'Link copied' : 'Copy link'}</button><button className="text-button" disabled={exporting} onClick={() => void exportRecord('json')}>Download JSON</button><button className="text-button" disabled={exporting} onClick={() => void exportRecord('csv')}>Download CSV</button></div>
        <span className="sr-only" role="status">{copy === 'copied' ? 'Link copied to clipboard.' : ''}</span>
        {copy === 'manual' && <label className="copy-fallback">Copy this public link<input ref={copyInput} value={shareUrl} readOnly onFocus={event => event.target.select()} /></label>}
        {exportError && <RequestIssue error={exportError} retry={() => void exportRecord('json')} />}
      </header>
      <section className="refined"><div><h2>Refined thesis</h2><p>{narrative?.stages.find(stage => stage.stage === 'refined_thesis')?.summary ?? 'No dedicated public refined thesis was recorded.'}</p></div></section>
      <section aria-labelledby="trace-heading"><div className="section-heading"><h2 id="trace-heading">Decision trace</h2><span>{narrative?.stages.length ?? 0} published stages</span></div>
        {narrative?.stages.length ? <div className="reasoning-chain">{narrative.stages.map((stage, index) => <details className="reasoning-stage" key={stage.stage} open={index === 0}><summary className="stage-toggle"><Chevron /><span><strong style={{ color: `var(--${stageColors[stage.stage] ?? 'text-2'})` }}>{stageNames[stage.stage] ?? label(stage.stage)}</strong><span className="stage-preview">{stage.summary}</span></span><span className="stage-time">{clock(stage.completed_at ?? stage.started_at)}</span></summary><div className="stage-body"><p>{stage.summary}</p>{stage.started_at && <p className="as-of">Started {when(stage.started_at)}{stage.completed_at ? ` · Completed ${when(stage.completed_at)}` : ''}</p>}{stage.claim_ids.length > 0 && <div className="evidence-links">{stage.claim_ids.map((id, i) => <a key={id} href={`#${id}`}>Evidence {i + 1}</a>)}</div>}</div></details>)}</div> : <Empty>This historical record has a public summary, with no dedicated stage summaries.</Empty>}
      </section>
      <section><h2>Conviction and sizing</h2><p>{narrative?.conviction_rationale ?? 'No public conviction rationale was recorded.'}</p><dl className="detail-grid sizing"><Fact name="Decision-time weight">{weight(data.current_weight)}</Fact><Fact name="Proposed target">{weight(data.proposed_target_weight)}</Fact><Fact name="Final target">{weight(data.final_target_weight)}</Fact></dl><p className="section-note">Target weight is the intended position size, not the amount of an order.</p></section>
      {narrative?.variant_perception && <section><details className="compact-disclosure"><summary><Chevron /> Variant perception</summary><div className="disclosure-body">{(['consensus', 'disagreement', 'evidence', 'falsification'] as const).map(key => <div className="prose-fact" key={key}><h3>{label(key)}</h3><p>{narrative.variant_perception![key] ?? 'Not recorded.'}</p></div>)}</div></details></section>}
      <section><h2>Trigger</h2><p>{narrative?.trigger_summary ?? 'No dedicated public trigger narrative was recorded.'}</p>{data.public_run_id && <Link className="text-button" href={dashboardUrl({ scope: data.mode, tab: 'feed', run_id: data.public_run_id }, '')}>View related decisions →</Link>}</section>
      <section><div className="section-heading"><h2>Sources &amp; claims</h2><span>{narrative?.claims.length ?? data.claims.length} published claims</span></div>
        {narrative?.claims.map(claim => <details className="claim" key={claim.public_id} id={claim.public_id}><summary><Chevron /><span className="source-type">Evidence</span><span>{claim.claim}</span></summary><div className="claim-detail">
          {claim.source_ids.map(id => { const source = narrative.sources.find(item => item.public_id === id); const href = publicUrl(source?.url); return source ? <div className="source-entry" key={id}><strong>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{source.title} ↗</a> : source.title}</strong><p>{source.publisher} · {label(source.source_type)}{source.published_on ? ` · ${source.published_on}` : ''}</p>{source.excerpt && <blockquote>{source.excerpt}</blockquote>}</div> : <p key={id}>Source metadata unavailable.</p> })}
          {claim.evidence_confidence !== null && <p className="section-note">Model-assessed evidence support: {weight(claim.evidence_confidence)}. This isn't the probability of a profitable trade.</p>}
        </div></details>)}
        {!narrative && data.claims.map((claim, index) => <details className="claim" key={index}><summary><Chevron /><span className="source-type">{label(claim.source_type)}</span><span>{claim.claim}</span></summary><div className="claim-detail">Source timestamp {when(claim.source_timestamp)}. No approved source link was recorded.</div></details>)}
        {!narrative?.claims.length && !data.claims.length && <Empty>No public claims were recorded.</Empty>}
      </section>
      {narrative?.sources.length ? <section><div className="section-heading"><h2>Source pack</h2><span>{narrative.sources.length} published source{narrative.sources.length === 1 ? '' : 's'}</span></div>
        <div className="source-pack">{narrative.sources.map(source => { const href = publicUrl(source.url); return <div key={source.public_id}>
          <span className="source-type">{label(source.source_type)}</span>
          <span className="source-title">{href ? <a href={href} target="_blank" rel="noopener noreferrer">{source.title} ↗</a> : source.title}{source.publisher && <span className="quiet"> · {source.publisher}</span>}</span>
          <span className="source-published">{source.published_on ?? 'Undated'}</span>
        </div> })}</div>
        <p className="section-note">Every source the published record cites, whether or not a claim quotes it.</p>
      </section> : null}
      <section><h2>Invalidation criteria</h2><TextList items={narrative?.conditions?.invalidation} empty="No public invalidation criteria were recorded." /></section>
      {data.theme && <section><h2>Strategy &amp; themes</h2><div className="tags mono">{[data.theme, data.regime && `regime_${data.regime.toLowerCase()}`].filter(Boolean).map(tag => <span key={tag as string}>{tag}</span>)}</div></section>}
      <section><details className="regime"><summary><Chevron /> Regime {label(regime?.published_state ?? data.regime)}{regime ? `, composite score ${regime.score}` : ''}</summary><div className="regime-detail">{regime ? <><p>Raw {label(regime.raw_state)} · Published {label(regime.published_state)} · {when(regime.as_of)}</p><dl className="regime-values">{regime.components.map(component => <div key={component.name}><dt>{label(component.name)}</dt><dd>{ruleValue(component.value, component.unit)} · {component.points} points</dd></div>)}</dl><p className="section-note">Component values and points are recorded observations. The composite isn't model confidence.</p></> : <Empty>Bound historical regime evidence wasn't recorded.</Empty>}</div></details></section>
      <section><h2>Policy checks</h2><PolicyChecks evaluation={data.policy_evaluation} />{data.extraordinary_opportunity?.invoked && <p className="section-note">Extraordinary opportunity invoked. {data.extraordinary_opportunity.summary ?? 'A dedicated public exception summary was not recorded.'}</p>}</section>
      <section><h2>{data.mode === 'paper' ? 'Paper execution' : 'Live execution'}</h2><div className="check-row"><span>Recorded lifecycle</span><Badge value={data.lifecycle} /></div><dl className="detail-grid sizing"><Fact name="Sized order">{money(data.sized_order?.notional)}</Fact><Fact name="Broker-requested notional">{money(data.requested_order?.notional)}</Fact><Fact name="Confirmed gross notional">{money(data.execution.gross_notional)}</Fact><Fact name="Confirmed quantity">{amount(data.execution.quantity)}</Fact><Fact name="Recorded fees">{money(data.execution.fees)}</Fact></dl>
        {data.execution.items.length ? <details className="compact-disclosure"><summary><Chevron /> Confirmed fills</summary><div className="table-scroll" tabIndex={0} role="region" aria-label="Confirmed fills"><table><thead><tr><th>Time (ET)</th><th>Quantity</th><th>Price</th><th>Order state</th></tr></thead><tbody>{data.execution.items.map((fill, index) => <tr key={index}><td>{when(fill.occurred_at)}</td><td>{amount(fill.quantity)}</td><td>{money(fill.price)}</td><td>{label(fill.order_state)}{Number(fill.canceled_quantity) > 0 ? ` · ${amount(fill.canceled_quantity)} canceled` : ''}</td></tr>)}</tbody></table></div></details> : <Empty>Confirmed fills have not been published for this decision.</Empty>}
        <p className="section-note">Approval, submitted orders and confirmed fills are separate. Slippage is unavailable without a recorded reference price.</p>
      </section>
      <section><details className="compact-disclosure"><summary><Chevron /> Recorded milestones ({data.milestones.length})</summary><ol className="timeline">{data.milestones.map((milestone, index) => <li key={index}><span>{label(milestone.stage)}</span><time dateTime={milestone.occurred_at}>{milestone.time_precision === 'timestamp' ? when(milestone.occurred_at) : milestone.occurred_at}</time></li>)}</ol>{!data.milestones.length && <Empty>No milestone timestamps were recorded.</Empty>}{data.milestones_truncated && <p className="section-note">Showing {data.milestones.length} of {data.milestones_total} milestones.</p>}</details></section>
      <section><h2>X signal usage</h2><p>{data.x_usage.used ? narrative?.x_summary ?? data.x_usage.summary ?? label(data.x_usage.usage_type) : "X wasn't used for this decision."}</p>{data.x_usage.used && <p className="quiet">{data.x_usage.confirmed_outside_x ? 'Confirmation outside X was recorded.' : 'Confirmation outside X was not recorded.'}</p>}</section>
      <section><details className="conditions"><summary><Chevron /> Portfolio management conditions</summary><div className="condition-grid">{(['add', 'trim', 'exit'] as const).map(key => <div key={key}><h3>{label(key)}</h3><TextList items={narrative?.conditions?.[key]} /></div>)}</div></details></section>
      <section><details className="compact-disclosure"><summary><Chevron /> Record provenance</summary><dl className="detail-grid disclosure-body"><Fact name="Public decision">{data.public_id}</Fact><Fact name="Requested model">{data.model_provenance.requested_model ?? data.model_provenance.model_label ?? 'Not recorded'}</Fact><Fact name="Observed model">{data.model_provenance.observed_model ?? 'Not recorded'}</Fact><Fact name="Policy version">{data.policy_evaluation.policy_version ?? 'Not recorded'}</Fact><Fact name="Validator version">{data.policy_evaluation.validator_version ?? 'Not recorded'}</Fact><Fact name="Authored schema">{data.policy_evaluation.authored_schema_version ?? 'Not recorded'}</Fact></dl><p className="section-note">Model changes annotate one account's continuous history. They aren't separate competing portfolios.</p></details></section>
      <footer className="site-foot"><span>Public {data.mode === 'paper' ? 'paper' : 'live'} decision record</span><Link href={back}>Back to feed ↑</Link></footer>
    </SectionBoundary>
    {scope !== data.mode && <p className="sr-only">This record belongs to the {data.mode} portfolio.</p>}
  </div>
}
