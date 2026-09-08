import { useEffect, useRef, useState } from 'react'
import { PublicError, readPublic, usePublic } from './api'
import { Badge, Chevron, Empty, Fact, RequestIssue, ResourceNotice, SectionBoundary } from './common'
import { label, when } from './format'
import { dashboardUrl, Link } from './navigation'
import type { ActivityItem, ActivityPage, Metadata, Runtime, Scope } from './types'

function RunDisclosure({ item, scope }: { item: ActivityItem; scope: Scope }) {
  const [open, setOpen] = useState(false)
  const detail = usePublic<ActivityItem & Metadata>(open ? `/api/public/v2/portfolios/${scope}/activity/${item.public_id}` : null, 'run', 0)
  const status = item.status === 'running' && item.lease_expires_at && Date.parse(item.lease_expires_at) <= Date.now() + detail.offset ? 'stale' : item.status
  return <details className="run-row" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><Chevron /><span><strong>{label(status)}</strong><span className="run-date">{item.session_date} · {label(item.origin)}{item.attempt_count > 1 ? ` · ${item.attempt_count} attempts` : ''}</span></span><span className="quiet">{item.slot ? label(item.slot) : ''}</span></summary>
    <div className="disclosure-body">
      <p>{item.latest_attempt?.summary ?? item.summary ?? (item.reason ? label(item.reason) : 'No public session summary was recorded.')}</p>
      <ResourceNotice resource={detail} name="review attempts" />
      <SectionBoundary resetKey={detail.data} retry={detail.refresh} name="review history">
        {detail.data?.attempts?.map(attempt => <div className="attempt" key={attempt.public_id}><div className="section-heading"><h3>Attempt {attempt.attempt_number}</h3><Badge value={attempt.status} /></div><p>{attempt.summary ?? (attempt.reason ? label(attempt.reason) : label(attempt.stage))}</p><dl className="detail-grid"><Fact name="Requested model">{attempt.requested_model}</Fact><Fact name="Observed model">{attempt.observed_model ?? 'Not recorded'}</Fact><Fact name="Started">{when(attempt.started_at)}</Fact><Fact name="Finished">{attempt.finished_at ? when(attempt.finished_at) : 'Not recorded'}</Fact></dl></div>)}
        {detail.data?.attempts_truncated && <p className="section-note">Showing the latest 100 of {detail.data.attempt_count} recorded attempts.</p>}
      </SectionBoundary>
      {item.public_id.startsWith('run_') && <Link className="text-button" href={dashboardUrl({ scope, tab: 'feed', run_id: item.public_id, q: null, action: null, policy: null, lifecycle: null, since: null, until: null })}>View decisions from this review →</Link>}
    </div>
  </details>
}

function ActivityHistory({ scope }: { scope: Scope }) {
  const url = `/api/public/v2/portfolios/${scope}/activity?limit=25`
  const first = usePublic<ActivityPage>(url, 'activity', 0)
  const [snapshot, setSnapshot] = useState<ActivityPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<PublicError | null>(null)
  const ignored = useRef<ActivityPage | null>(null)
  const lock = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => { if (first.data && first.data !== ignored.current && !snapshot) setSnapshot(first.data) }, [first.data, snapshot])
  useEffect(() => () => controller.current?.abort(), [])
  const more = async () => {
    if (!snapshot?.next_cursor || lock.current || (error && error.retryAt > Date.now())) return
    lock.current = true
    setLoading(true)
    setError(null)
    controller.current = new AbortController()
    try {
      const { data } = await readPublic<ActivityPage>(url + '&cursor=' + encodeURIComponent(snapshot.next_cursor), 'activity', controller.current.signal)
      if (controller.current.signal.aborted) return
      const ids = new Set(snapshot.items.map(item => item.public_id))
      setSnapshot({ ...data, items: [...snapshot.items, ...data.items.filter(item => !ids.has(item.public_id))].slice(0, 250) })
    } catch (failure) {
      if (!controller.current.signal.aborted) setError(failure instanceof PublicError ? failure : new PublicError(502, 'Review history could not be read.'))
    } finally { lock.current = false; setLoading(false) }
  }
  const refresh = () => { controller.current?.abort(); ignored.current = first.data; setSnapshot(null); setError(null); first.refresh() }
  return <>
    <ResourceNotice resource={first} name="review history" />
    {first.data && snapshot && first.data.activity_revision !== snapshot.activity_revision && <button className="updates-button" onClick={refresh}>Review history changed · Refresh</button>}
    {error && <RequestIssue error={error} retry={error.status === 409 ? refresh : () => void more()} retained={!!snapshot} />}
    {snapshot?.items.map(item => <RunDisclosure key={item.public_id} item={item} scope={scope} />)}
    {snapshot && !snapshot.items.length && <Empty>No public review sessions have been recorded.</Empty>}
    {snapshot?.next_cursor && snapshot.items.length < 250 && <button className="more-button" disabled={loading} onClick={() => void more()}>{loading ? 'Loading reviews…' : 'Show more reviews'}</button>}
    {snapshot && snapshot.items.length >= 250 && <p className="section-note">The latest 250 sessions are loaded. Private source history retains older sessions.</p>}
  </>
}

export function Activity({ scope }: { scope: Scope }) {
  const runtime = usePublic<Runtime>(`/api/public/v2/portfolios/${scope}/runtime`, 'runtime', 30_000)
  const [open, setOpen] = useState(false)
  const [clock, setClock] = useState(Date.now)
  const refreshRuntime = runtime.refresh
  const expired = useRef<string | null>(null)
  useEffect(() => { const timer = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(timer) }, [])
  const now = clock + runtime.offset
  const data = runtime.data
  const active = data?.active_run
  const schedules = data?.schedules ?? []
  const schedule = schedules.filter(item => item.enabled && !item.paused && item.schedule_mode === 'scheduled' && item.next_due_at && (!item.reason || item.reason === 'due') && item.observer_as_of && now >= Date.parse(item.observer_as_of) && now - Date.parse(item.observer_as_of) <= item.observer_max_age_seconds * 1000).sort((a, b) => Date.parse(a.next_due_at!) - Date.parse(b.next_due_at!))[0]
  const due = schedule?.next_due_at ?? null
  const seconds = due ? Math.max(0, Math.ceil((Date.parse(due) - now) / 1000)) : null
  useEffect(() => {
    if (due && seconds === 0 && expired.current !== due) { expired.current = due; refreshRuntime() }
  }, [due, seconds, refreshRuntime])
  const actuallyRunning = active?.status === 'running' && active.lease_expires_at && Date.parse(active.lease_expires_at) > now
  let status = actuallyRunning ? label(active.latest_attempt?.stage ?? 'running') : active ? label(active.reason ?? active.status) : data?.latest_run ? label(data.latest_run.status) : 'No recorded review yet'
  if (!data || data.status === 'unavailable') status = runtime.loading ? 'Loading agent activity…' : 'Agent activity unavailable'
  const authority = data?.status === 'unavailable'
    ? label(data.reason ?? 'runtime_not_published')
    : schedules.length
      ? label(schedules[0].reason ?? 'observer_stale')
      : label(data?.schedule_mode ?? 'manual')
  const countdown = seconds === null ? null : seconds > 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
  return <section className="activity-strip" aria-label="Agent activity">
    <div className="activity-current"><span className={`activity-dot ${actuallyRunning ? 'is-active' : ''}`} aria-hidden="true" /><span>{status}</span>{due ? <time dateTime={due} title={when(due)} aria-label={`Next review scheduled for ${when(due)}`}><span aria-hidden="true">{seconds === 0 ? 'Waiting for the scheduler' : `Next review in ${countdown}`}</span></time> : <span className="quiet">{authority}</span>}</div>
    <ResourceNotice resource={runtime} name="agent activity" />
    <details className="compact-disclosure" onToggle={event => setOpen(event.currentTarget.open)}><summary><Chevron /> Review sessions</summary><div className="activity-history">
      {data?.as_of && <p className="as-of">Activity published {when(data.as_of)}. A prepared intake doesn't mean the agent is running.</p>}
      {schedules.map((item, index) => <p className="section-note" key={index}>{label(item.schedule_mode)} · {item.timezone} · Revision {item.revision}. {item.next_due_at && schedule === item ? `Scheduled ${when(item.next_due_at)}.` : `No countdown: ${label(item.reason ?? 'observer_stale')}.`}</p>)}
      {open && <ActivityHistory key={scope} scope={scope} />}
    </div></details>
  </section>
}
