import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowClockwise, FunnelSimple, MagnifyingGlass, X } from '@phosphor-icons/react'
import { PublicError, readPublic } from './api'
import { Badge, Empty, RequestIssue } from './common'
import { ReviewRow, useReviews } from './Activity'
import { label, when } from './format'
import { dashboardUrl, decisionUrl, Link, navigate } from './navigation'
import type { ActivityItem, DecisionItem, FeedPage, Scope } from './types'

const WINDOW_LIMIT = 500
const PAGE_LIMIT = 25

function useFeed(url: string) {
  const cache = useRef(new Map<string, FeedPage>())
  const active = useRef(url)
  const generation = useRef(0)
  const requests = useRef(new Set<AbortController>())
  const busy = useRef(false)
  const retryAt = useRef(0)
  const current = useRef<FeedPage | null>(null)
  const [state, setState] = useState<{ url: string; page: FeedPage | null; loading: boolean; more: boolean; error: PublicError | null; updates: number; changed: boolean; failedMore?: boolean }>({ url, page: null, loading: true, more: false, error: null, updates: 0, changed: false })

  const request = useCallback(async (mode: 'first' | 'more' | 'probe') => {
    if (Date.now() < retryAt.current || (mode === 'more' && busy.current)) return
    if (mode === 'more' && (!current.current?.next_cursor || current.current.items.length >= WINDOW_LIMIT)) return
    if (mode === 'first') {
      for (const pending of requests.current) pending.abort()
      generation.current += 1
    }
    if (mode !== 'probe') {
      busy.current = true
      setState(previous => ({ ...previous, loading: mode === 'first', more: mode === 'more', error: null }))
    }
    const id = generation.current
    const controller = new AbortController()
    requests.current.add(controller)
    const cursor = mode === 'more' ? `&cursor=${encodeURIComponent(current.current!.next_cursor!)}` : ''
    try {
      const { data } = await readPublic<FeedPage>(url + cursor, 'feed', controller.signal)
      if (controller.signal.aborted || id !== generation.current || active.current !== url) return
      if (mode === 'probe' && current.current) {
        const previous = current.current
        const newItems = data.items.some(item => !previous.items.some(old => old.public_id === item.public_id))
        setState(old => ({ ...old, updates: Math.max(0, data.total - previous.total), changed: data.revision !== previous.revision || newItems }))
      } else {
        const seen = new Set(current.current?.items.map(item => item.public_id))
        const page = mode === 'more' && current.current ? { ...data, items: [...current.current.items, ...data.items.filter(item => !seen.has(item.public_id))].slice(0, WINDOW_LIMIT) } : data
        current.current = page
        cache.current.delete(url)
        cache.current.set(url, page)
        while (cache.current.size > 4) cache.current.delete(cache.current.keys().next().value!)
        setState({ url, page, loading: false, more: false, error: null, updates: 0, changed: false })
      }
    } catch (error) {
      if (controller.signal.aborted || id !== generation.current || active.current !== url) return
      const failure = error instanceof PublicError ? error : new PublicError(502, 'The feed could not be read.')
      retryAt.current = failure.retryAt
      setState(previous => ({ ...previous, loading: false, more: false, error: failure, failedMore: mode === 'more' }))
    } finally {
      requests.current.delete(controller)
      if (mode !== 'probe' && id === generation.current) busy.current = false
    }
  }, [url])

  useEffect(() => {
    active.current = url
    generation.current += 1
    retryAt.current = 0
    busy.current = false
    const restored = cache.current.get(url) ?? null
    current.current = restored
    setState({ url, page: restored, loading: !restored, more: false, error: null, updates: 0, changed: false })
    void request(restored ? 'probe' : 'first')
    const pending = requests.current
    return () => { for (const controller of pending) controller.abort() }
  }, [url, request])
  useEffect(() => {
    const wake = () => { if (document.visibilityState !== 'hidden') void request(current.current ? 'probe' : 'first') }
    const retract = () => {
      cache.current.clear()
      current.current = null
      generation.current += 1
      setState({ url, page: null, loading: true, more: false, error: null, updates: 0, changed: false })
      void request('first')
    }
    const timer = window.setInterval(wake, 30_000)
    window.addEventListener('online', wake)
    window.addEventListener('public-retraction', retract)
    document.addEventListener('visibilitychange', wake)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('online', wake)
      window.removeEventListener('public-retraction', retract)
      document.removeEventListener('visibilitychange', wake)
    }
  }, [request, url])
  return { ...state, page: state.url === url ? state.page : null, request }
}

export function Feed({ scope, search }: { scope: Scope; search: string }) {
  const params = new URLSearchParams(search)
  const query = params.get('q') ?? ''
  const [draft, setDraft] = useState(query)
  const [toolsOpen, setToolsOpen] = useState(query !== '' || ['action', 'policy', 'lifecycle', 'since', 'until', 'run_id'].some(key => params.has(key)))
  const typing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => { setDraft(query); return () => clearTimeout(typing.current) }, [query, search])
  const apiParams = new URLSearchParams({ portfolio_id: scope, limit: String(PAGE_LIMIT) })
  for (const key of ['q', 'action', 'policy', 'lifecycle', 'since', 'until', 'run_id']) {
    const value = params.get(key)
    if (value) apiParams.set(key, value)
  }
  const feed = useFeed('/api/public/v2/decisions?' + apiParams)
  const filtered = ['q', 'action', 'policy', 'lifecycle', 'since', 'until', 'run_id'].some(key => params.has(key))
  const setFilter = (key: string, value: string) => navigate(dashboardUrl({ [key]: value || null, tab: 'feed' }, search))
  const submitSearch = (value: string, replace = false) => {
    clearTimeout(typing.current)
    navigate(dashboardUrl({ q: value.trim() || null, tab: 'feed' }, search), replace)
  }
  const clear = () => navigate(dashboardUrl(Object.fromEntries(['q', 'action', 'policy', 'lifecycle', 'since', 'until', 'run_id'].map(key => [key, null])), search))
  const reviews = useReviews(scope)
  // A review that concluded no action is still work. Showing only authored decisions makes
  // an agent that reviewed three times today look idle. Filters are decision-scoped, so a
  // filtered view drops back to decisions alone and says so.
  const reviewAt = (item: ActivityItem) => Date.parse(item.completed_at ?? item.prepared_at ?? item.due_at ?? item.session_date + 'T00:00:00Z')
  const entries: Array<{ key: string; at: number; node: ReactNode }> = [
    ...(feed.page?.items ?? []).map((item: DecisionItem) => ({
      key: item.public_id,
      at: Date.parse(item.created_at),
      node: <Link className="stream-row stream-row--decision" href={decisionUrl(item.public_id, scope)} aria-label={item.ticker + ': ' + label(item.decision) + '. View full trace'}>
        <strong className="mono stream-kind">{item.ticker}</strong>
        <span className="stream-body"><span className="stream-headline">{label(item.decision)}<Badge value={item.policy_outcome} /><span className="execution-label">{label(item.lifecycle)}</span></span><span className="stream-summary">{item.public_summary}{item.summary_truncated ? '…' : ''}</span></span>
        <time dateTime={item.created_at} title={when(item.created_at)}>{when(item.created_at, true)}</time>
        <span className="chevron" aria-hidden="true">&rsaquo;</span>
      </Link>,
    })),
    ...(filtered ? [] : reviews.items.map(item => ({
      key: item.public_id,
      at: reviewAt(item),
      node: <ReviewRow item={item} scope={scope} />,
    }))),
  ].sort((a, b) => b.at - a.at)

  return <section aria-label="Agent activity and decisions">
    <button className="feed-tools-toggle" type="button" aria-expanded={toolsOpen} aria-controls="feed-tools" aria-label={toolsOpen ? 'Close search and filters' : 'Search and filter'} onClick={() => setToolsOpen(value => !value)}>{toolsOpen ? <X size={17} /> : <MagnifyingGlass size={17} />}</button>
    <button className={`feed-refresh-toggle${feed.loading ? ' is-refreshing' : ''}`} type="button" aria-label="Refresh activity" onClick={() => { void feed.request('first'); reviews.refresh() }} disabled={feed.loading}><ArrowClockwise size={17} /></button>
    <form className={`feed-tools ${toolsOpen ? 'is-open' : 'is-closed'}`} id="feed-tools" aria-hidden={!toolsOpen} onSubmit={event => { event.preventDefault(); submitSearch(draft) }}>
      <label className="search-label"><span className="sr-only">Search all public decisions</span><MagnifyingGlass size={16} aria-hidden="true" /><input type="search" maxLength={200} placeholder="Search ticker, company or thesis" value={draft} onChange={event => {
        const value = event.target.value
        setDraft(value)
        clearTimeout(typing.current)
        typing.current = setTimeout(() => submitSearch(value, true), 300)
      }} /></label>
      <details className="filter-disclosure"><summary aria-label="Filter decisions"><FunnelSimple size={17} /></summary><div className="filters">
        <label>Action<select value={params.get('action') ?? ''} onChange={event => setFilter('action', event.target.value)}><option value="">All actions</option>{['BUY', 'ADD', 'TRIM', 'SELL', 'HOLD', 'PASS', 'WATCHLIST'].map(action => <option key={action}>{action}</option>)}</select></label>
        <label>Policy outcome<select value={params.get('policy') ?? ''} onChange={event => setFilter('policy', event.target.value)}><option value="">All outcomes</option>{['approved', 'rejected', 'unavailable'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label>Execution<select value={params.get('lifecycle') ?? ''} onChange={event => setFilter('lifecycle', event.target.value)}><option value="">All stages</option>{['broker_filled', 'broker_partially_filled', 'broker_canceled', 'policy_rejected', 'awaiting_paper_price', 'paper_filled'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label>From date (UTC)<input type="date" value={params.get('since')?.slice(0, 10) ?? ''} onChange={event => setFilter('since', event.target.value ? event.target.value + 'T00:00:00Z' : '')} /></label>
        <label>Before date (UTC)<input type="date" value={params.get('until')?.slice(0, 10) ?? ''} onChange={event => setFilter('until', event.target.value ? event.target.value + 'T00:00:00Z' : '')} /></label>
      </div></details>
    </form>
    {filtered && <div className="filter-state"><span>{params.has('run_id') ? 'Decisions from one recorded review' : 'Filtered decisions only, reviews hidden'}</span><button className="text-button" onClick={clear}>Clear filters</button></div>}
    {(feed.updates > 0 || feed.changed || reviews.changed) && <button className="updates-button" onClick={() => { void feed.request('first'); reviews.refresh() }}>{feed.updates > 0 ? feed.updates + ' new update' + (feed.updates === 1 ? '' : 's') : 'Published records changed'} · Refresh</button>}
    {feed.error && <RequestIssue error={feed.error} retained={!!feed.page} retry={() => void feed.request(feed.error?.status !== 409 && feed.failedMore ? 'more' : 'first')} />}
    {!feed.page && feed.loading && <p className="empty" role="status">Loading public decisions...</p>}
    {feed.page && <>
      {!entries.length && <Empty>{filtered ? params.has('run_id') ? 'This review has no published investment decisions.' : 'No public decisions match these filters.' : 'Nothing has been published yet.'}</Empty>}
      {entries.map(entry => <div key={entry.key}>{entry.node}</div>)}
      {feed.page.next_cursor && feed.page.items.length < WINDOW_LIMIT && <button className="more-button" onClick={() => void feed.request('more')} disabled={feed.more || feed.loading}>{feed.more ? 'Loading more...' : 'Show more decisions'} <span aria-hidden="true">&rsaquo;</span></button>}
      {!filtered && reviews.hasMore && <button className="more-button" onClick={reviews.more} disabled={reviews.loading}>{reviews.loading ? 'Loading reviews...' : 'Show more reviews'} <span aria-hidden="true">&rsaquo;</span></button>}
      {feed.page.items.length >= WINDOW_LIMIT && <p className="section-note">{WINDOW_LIMIT} records are loaded in this view. Narrow your search or dates to explore more of the archive.</p>}
      <p className="section-note">Policy approval and confirmed execution are separate. Times are shown in New York time.</p>
    </>}
  </section>
}
