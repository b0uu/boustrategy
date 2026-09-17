import { usePublic } from './api'
import { Chevron, Empty, Fact, ResourceNotice, SectionBoundary } from './common'
import { label, money, percent, sessionDay, tone } from './format'
import type { Scope, ShortCalls } from './types'

export function Shorts({ scope }: { scope: Scope }) {
  const resource = usePublic<ShortCalls>(`/api/public/v2/portfolios/${scope}/shorts`, 'shorts')
  const data = resource.data
  return <section className="positions" aria-label={`${scope === 'live' ? 'Live' : 'Paper'} short calls`}>
    <ResourceNotice resource={resource} name="short calls" />
    <SectionBoundary resetKey={data} retry={resource.refresh} name="short calls">
      {data && <>
        <p className="section-note">The account is long-only and never holds a short. A short call is a recorded recommendation: what the agent would short if it could, scored from the price it read as if the trade had been taken.</p>
        {data.items.length ? <>
          <div className="position-heading"><span /><span>Short call</span><span>Declared</span><span>Call return</span></div>
          {data.items.map(call => <details className="position" key={`${call.ticker}-${call.declared_at}`}>
            <summary><Chevron /><span className="position-name"><strong className="mono">{call.ticker}</strong><span>{call.status === 'open' ? 'Open call' : 'Removed'}</span></span><span className="mono">{sessionDay(call.declared_at)}</span><span className={`mono ${tone(call.short_return_percent)}`}>{percent(call.short_return_percent)}</span></summary>
            <div className="position-detail">
              <dl className="detail-grid">
                <Fact name="Declared price">{money(call.declared_price)}</Fact>
                <Fact name={call.status === 'open' ? 'Latest close' : 'Price at removal'}>{money(call.end_price)}</Fact>
                <Fact name="Priced through">{sessionDay(call.ended_at)}</Fact>
                <Fact name="Days listed">{call.days_listed}</Fact>
                <Fact name="Times declared">{call.declarations.length}</Fact>
                <Fact name="Removed">{call.removed_at ? sessionDay(call.removed_at) : 'Still listed'}</Fact>
              </dl>
              {call.removal_conditions && <>
                <h3>Recorded removal conditions</h3>
                <dl className="detail-grid">
                  <Fact name="Cover below">{money(call.removal_conditions.cover_below)}</Fact>
                  <Fact name="Stop above">{money(call.removal_conditions.stop_above)}</Fact>
                  <Fact name="Review by">{sessionDay(call.removal_conditions.review_by)}</Fact>
                </dl>
              </>}
              {call.due.length > 0 && <p className="section-note">Removal is due: {call.due.map(value => label(value)).join(', ')}. The next review must remove this call or re-underwrite it with conditions the current price doesn't already meet.</p>}
              <p className="section-note">A call's return is measured as a short: it gains when the price falls. Conditions are judged on completed daily closes, not intraday prices.</p>
            </div>
          </details>)}
        </> : <Empty>No short has been recommended. The bar is the highest conviction the agent can record, so an empty list is the expected state.</Empty>}
        {data.status !== 'available' && <p className="section-note">Short calls are {label(data.status)}{data.reason ? `: ${label(data.reason)}` : ''}.</p>}
      </>}
    </SectionBoundary>
  </section>
}
