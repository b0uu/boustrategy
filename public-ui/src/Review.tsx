import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowUpRight } from '@phosphor-icons/react'
import { usePublic } from './api'
import { Badge, Empty, Fact, ResourceNotice, SectionBoundary } from './common'
import { clock, label, money, publicUrl, sessionDay } from './format'
import { Link, reviewUrl } from './navigation'
import type { ActivityItem, Metadata, Scope, Weighed } from './types'

function host(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

function External({ url, children }: { url: string; children: React.ReactNode }) {
  const href = publicUrl(url)
  return href ? <a className="external-link" href={href} target="_blank" rel="noopener noreferrer">{children}<ArrowUpRight size={10} weight="bold" aria-hidden="true" /></a> : <>{children}</>
}

function SourceLinks({ urls }: { urls: string[] }) {
  // Two filings on sec.gov would read as the same link, so a repeated site is numbered.
  const hosts = urls.map(host)
  return <>{urls.map((url, index) => {
    const repeats = hosts.filter(name => name === hosts[index]).length
    const seen = hosts.slice(0, index + 1).filter(name => name === hosts[index]).length
    return <External key={url} url={url}>{repeats > 1 ? `${hosts[index]} ${seen}` : hosts[index]}</External>
  })}</>
}

const RANKS = [['headline', 'Headline'], ['notable', 'Notable'], ['context', 'Context']] as const

/** How much X the review read, and which accounts and posts it actually leaned on. */
function XSignals({ weighed }: { weighed: Weighed }) {
  const digest = weighed.x_digest
  const cited = weighed.x_cited ?? []
  const triage = weighed.x_triage ?? []
  if (!digest && !cited.length && !triage.length) return null
  const read = digest ? RANKS.reduce((sum, [rank]) => sum + (digest[rank] ?? 0), 0) : 0
  const accounts = Object.entries(cited.reduce<Record<string, number>>((tally, post) => ({ ...tally, [post.handle]: (tally[post.handle] ?? 0) + 1 }), {})).sort((a, b) => b[1] - a[1])
  const most = accounts[0]?.[1] ?? 1
  // Posts cited for the same judgment read as one row, not one row each.
  const groups = Object.entries(cited.reduce<Record<string, typeof cited>>((byJudgment, post) => {
    const key = `${post.ticker}/${post.subject}`
    return { ...byJudgment, [key]: [...(byJudgment[key] ?? []), post] }
  }, {})).sort(([a], [b]) => Number(a.endsWith('/thesis_review')) - Number(b.endsWith('/thesis_review')))
  return <section className="x-signals"><div className="section-heading"><h2>X signals</h2><span>{cited.length} post{cited.length === 1 ? '' : 's'} cited</span></div>
    {digest && read > 0 && <div className="x-read">
      <p>The review read the {sessionDay(digest.date)} digest: {read} ranked post{read === 1 ? '' : 's'}.</p>
      <div className="allocation-bar" role="img" aria-label={RANKS.map(([rank, name]) => `${name} ${digest[rank] ?? 0}`).join(', ')}>{RANKS.map(([rank], index) => <span key={rank} className={`allocation-color-${index}`} style={{ width: `${(digest[rank] ?? 0) / read * 100}%` }} />)}</div>
      <div className="allocation-legend">{RANKS.map(([rank, name], index) => <span key={rank}><i className={`allocation-color-${index}`} />{name} <span className="mono">{digest[rank] ?? 0}</span></span>)}</div>
    </div>}
    {accounts.length > 0 && <div className="x-accounts"><h3>Cited by account</h3>{accounts.map(([handle, count]) => <div className="x-account" key={handle}>
      <span>@{handle}</span><span className="bar"><span className="allocation-color-0" style={{ width: `${count / most * 100}%` }} /></span><span className="mono">{count}</span>
    </div>)}</div>}
    {groups.length > 0 && <ul className="review-items x-cited">{groups.map(([key, posts]) => <li key={key}>
      <div className="review-item-head"><strong className="mono">{posts[0].ticker}</strong><span>{posts[0].subject === 'thesis_review' ? 'Thesis review' : label(posts[0].subject)}</span></div>
      <p className="review-item-meta review-item-links">{posts.map(post => <External key={post.url} url={post.url}>@{post.handle} · {label('x_' + post.role)}</External>)}</p>
    </li>)}</ul>}
    {triage.length > 0 && <><div className="section-heading x-triage-heading"><h3>Headlines triaged for holdings</h3><span>{triage.filter(item => item.changes_thesis).length} changed a thesis</span></div>
      <ul className="x-posts">{triage.map(item => <li key={item.url + item.ticker}>
        <strong><External url={item.url}>@{item.handle} on X</External></strong>
        <span className={`x-post-role${item.changes_thesis ? ' x-post-role--changes' : ''}`}>{item.ticker} · {item.changes_thesis ? 'Changes the thesis' : "Doesn't change the thesis"}</span>
        <span className="x-post-summary">{item.note}</span>
      </li>)}</ul></>}
  </section>
}

export function ReviewPage({ publicId, scope, back }: { publicId: string; scope: Scope; back: string }) {
  const resource = usePublic<ActivityItem & Metadata>(`/api/public/v2/portfolios/${scope}/activity/${encodeURIComponent(publicId)}`, 'run', 0)
  const [copy, setCopy] = useState<'idle' | 'copied' | 'manual'>('idle')
  const copyInput = useRef<HTMLInputElement>(null)
  useEffect(() => { if (copy === 'manual') { copyInput.current?.focus(); copyInput.current?.select() } }, [copy])
  const data = resource.data
  if (!data) return <div className="trace request-state"><h1 tabIndex={-1}>{resource.error?.status === 404 ? 'Review not found' : 'Review reasoning'}</h1><ResourceNotice resource={resource} name="review" /><Link href={back}>Back to feed</Link></div>
  const attempt = data.attempts?.find(item => item.weighed) ?? data.attempts?.[0]
  const weighed = attempt?.weighed ?? {}
  const { candidates = [], holdings = [], challengers = [], earnings = [] } = weighed
  const shareUrl = location.origin + reviewUrl(data.public_id, scope)
  const copyLink = async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(shareUrl)
      setCopy('copied')
    } catch { setCopy('manual') }
  }
  return <div className="trace review-trace">
    <Link className="back" href={back}><ArrowLeft size={11} weight="bold" aria-hidden="true" />Feed</Link>
    <ResourceNotice resource={resource} name="review" />
    <SectionBoundary resetKey={data} retry={resource.refresh} name="review reasoning">
      <header className="trace-head"><div className="trace-title"><h1 tabIndex={-1}>{data.slot ? `${label(data.slot)} review` : 'Portfolio review'}</h1><Badge value={data.status} /><time dateTime={data.session_date}>{sessionDay(data.session_date)}</time></div>
        <p>{attempt?.summary ?? data.summary ?? 'No public session summary was recorded.'}</p>
        <dl className="trace-meta"><Fact name="Review">{data.public_id}</Fact>{attempt && <><Fact name="Model">{attempt.observed_model ?? attempt.requested_model}</Fact><Fact name="Started">{clock(attempt.started_at) ? `${clock(attempt.started_at)} ET` : 'Not recorded'}</Fact><Fact name="Finished">{clock(attempt.finished_at) ? `${clock(attempt.finished_at)} ET` : 'Not recorded'}</Fact></>}</dl>
        <div className="trace-actions"><button className="text-button" onClick={() => void copyLink()}>{copy === 'copied' ? 'Link copied' : 'Copy link'}</button></div>
        <span className="sr-only" role="status">{copy === 'copied' ? 'Link copied to clipboard.' : ''}</span>
        {copy === 'manual' && <label className="copy-fallback">Copy this public link<input ref={copyInput} value={shareUrl} readOnly onFocus={event => event.target.select()} /></label>}
      </header>
      <section><div className="section-heading"><h2>Candidates researched</h2><span>{candidates.length}</span></div>
        {candidates.length ? <ul className="review-items">{candidates.map(item => <li key={item.ticker}>
          <div className="review-item-head"><strong className="mono">{item.ticker}</strong><Badge value={item.outcome} />{item.clears_entry_bar && <span className="x-post-role">Clears the entry bar</span>}</div>
          <p>{item.reason}</p>
          <p className="review-item-meta">Idea: {item.idea_source}</p>
          {(item.sources.length > 0 || item.x_posts.length > 0) && <p className="review-item-meta review-item-links"><SourceLinks urls={item.sources} />{item.x_posts.map(post => <External key={post.url} url={post.url}>@{post.url.split('/')[3]} · {label('x_' + post.role)}</External>)}</p>}
        </li>)}</ul> : <Empty>This review researched no new candidates; only the morning and midday reviews must hunt.</Empty>}
      </section>
      <section><div className="section-heading"><h2>Holdings reviewed</h2><span>{holdings.length}</span></div>
        {holdings.length ? <ul className="review-items">{holdings.map(item => <li key={item.ticker}>
          <div className="review-item-head"><strong className="mono">{item.ticker}</strong><Badge value={item.state} /></div>
          {item.summary && <p>{item.summary}</p>}
          {item.realization_price_low != null && <dl className="trace-meta review-item-facts">
            <Fact name="Fully priced">{money(item.realization_price_low)}{item.realization_price_high != null ? `–${money(item.realization_price_high)}` : ''}</Fact>
            {item.invalidation_price != null && <Fact name="Invalidation">{money(item.invalidation_price)}</Fact>}
          </dl>}
          {item.review_reasons?.length ? <p className="review-item-meta">Why reviewed: {item.review_reasons.map(label).join(', ')}</p> : null}
        </li>)}</ul> : <Empty>No holding was due for a thesis review.</Empty>}
      </section>
      {challengers.length > 0 && <section><div className="section-heading"><h2>Challengers</h2><span>{challengers.length}</span></div><ul className="review-items">{challengers.map(item => <li key={item.candidate + item.incumbent}>
        <div className="review-item-head"><strong className="mono">{item.candidate} vs {item.incumbent}</strong><Badge value={item.verdict} /></div>
        <p>{item.reasoning}</p>
        <p className="review-item-meta">Why {item.incumbent} was the weakest holding: {item.why_weakest}</p>
      </li>)}</ul></section>}
      <XSignals weighed={weighed} />
      {weighed.exposure && <section><div className="section-heading"><h2>Exposure</h2><Badge value={weighed.exposure.action} /></div><p>{weighed.exposure.reasoning}</p></section>}
      {earnings.length > 0 && <section><div className="section-heading"><h2>Earnings dates read</h2><span>{earnings.length}</span></div><ul className="review-items">{earnings.map(item => <li key={item.ticker + item.event_date}>
        <div className="review-item-head"><strong className="mono">{item.ticker}</strong><span>{sessionDay(item.event_date)}</span><span className="x-post-role">{item.confirmed ? 'Confirmed' : 'Estimated'}</span><External url={item.source_url}>{host(item.source_url)}</External></div>
      </li>)}</ul></section>}
    </SectionBoundary>
  </div>
}
