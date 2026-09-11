import { usePublic } from './api'
import { Badge, Chevron, Empty, Fact, ResourceNotice, SectionBoundary, TextList } from './common'
import { amount, label, money, percent, tone, weight, when } from './format'
import { decisionUrl, Link } from './navigation'
import type { Overview, Positions as PositionData, Scope, ThesisReview } from './types'

function Thesis({ review }: { review: ThesisReview | undefined }) {
  return <div className="thesis-review">
    <div className="section-heading"><h3>Recorded thesis review</h3><Badge value={review?.state ?? 'not_reviewed'} /></div>
    <p>{review?.summary ?? 'No public thesis review is available for this holding.'}</p>
    {review?.reviewed_at && <p className="as-of">Reviewed {when(review.reviewed_at)}{review.author === 'operator' ? ' by the operator' : ''}.</p>}
    {review?.narrative?.conditions && <details className="compact-disclosure"><summary><Chevron /> Management conditions</summary><div className="condition-grid">{(['add', 'trim', 'exit', 'invalidation'] as const).map(key => <div key={key}><h3>{label(key)}</h3><TextList items={review.narrative!.conditions![key]} /></div>)}</div></details>}
  </div>
}

export function Positions({ scope, overview }: { scope: Scope; overview: Overview | null }) {
  const resource = usePublic<PositionData>(`/api/public/v2/portfolios/${scope}/positions`, 'positions')
  const data = resource.data
  let empty = 'No positions were recorded in the latest snapshot.'
  if (data?.status === 'unavailable') empty = "Holdings aren't available yet. This doesn't establish that the account has no positions."
  else if (overview?.portfolio_state === 'all_cash') empty = 'No open positions. The complete recorded balance is cash.'
  else if (overview?.portfolio_state === 'sold_out') empty = 'All observed positions have been closed.'
  else if (['unfunded', 'zero_balance'].includes(overview?.portfolio_state ?? '')) empty = 'The recorded account balance is zero, with no open positions.'
  return <section className="positions" aria-label={`${scope === 'live' ? 'Live' : 'Paper'} positions`}>
    <ResourceNotice resource={resource} name="positions" />
    <SectionBoundary resetKey={data} retry={resource.refresh} name="positions">
      {data && <>
        {data.items.length ? <>
          <div className="position-heading"><span /><span>Position</span><span>Portfolio weight</span><span>Unrealized return</span></div>
          {data.items.map(position => <details className="position" key={position.holding_episode_id ?? position.ticker}>
            <summary><Chevron /><span className="position-name"><strong className="mono">{position.ticker}</strong><span>{position.name ?? label(position.theme)}</span></span><span className="mono">{weight(position.weight)}</span><span className={`mono ${tone(position.unrealized_return_percent)}`}>{percent(position.unrealized_return_percent)}</span></summary>
            <div className="position-detail">
              {position.name && <p className="company-name">{position.name}</p>}
              <dl className="detail-grid"><Fact name="Market value">{money(position.market_value)}</Fact><Fact name="Quantity">{amount(position.shares)}</Fact><Fact name="Current price">{money(position.latest_price)}</Fact><Fact name="Average cost">{money(position.average_cost)}</Fact><Fact name="Quote quality">{label(position.price_quality)}</Fact><Fact name="Quote time">{when(position.quote_at)}</Fact><Fact name="Asset class">{label(position.asset_class)}</Fact><Fact name="Theme">{label(position.theme)}</Fact></dl>
              <Thesis review={position.thesis_review} />
              <h3>Latest published decision</h3>
              <p>{position.latest_public_summary ?? 'No public decision is linked to this position.'}</p>
              {position.latest_decision_id && <Link className="text-button" href={decisionUrl(position.latest_decision_id, scope)}>View decision trace →</Link>}
              <p className="section-note">Current weight is an exposure observation. It isn't a new entry-policy verdict. Thesis health comes from an explicit review.</p>
            </div>
          </details>)}
        </> : <Empty>{empty}</Empty>}
        {data.valuation_status !== 'available' && <p className="section-note">Valuation is {label(data.valuation_status)}{data.reason ? `: ${label(data.reason)}` : ''}. Missing quotes and cash aren't treated as zero.</p>}
        <p className="section-note">Unrealized return uses recorded average cost and price, excluding dividends and fees. {scope === 'paper' ? 'These are paper results, separate from the live portfolio.' : 'Values reflect the recorded live account.'}</p>
      </>}
    </SectionBoundary>
  </section>
}
