import { Component, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { PublicError, Resource } from './api'
import { label, when } from './format'

export function Badge({ value }: { value: string }) {
  return <span className={`badge badge--${value.toLowerCase().replaceAll(/[^a-z_]/g, '')}`}>{label(value)}</span>
}
export function Empty({ children }: { children: ReactNode }) { return <p className="empty">{children}</p> }
export function Chevron() { return <span className="chevron" aria-hidden="true">&rsaquo;</span> }
export function RequestIssue({ error, retry, retained = false }: { error: PublicError; retry: () => void; retained?: boolean }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!error.retryAt) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [error.retryAt])
  const waiting = error.retryAt > now
  return <div className="request-issue" role="alert">
    <p>{error.message}{retained && ' Showing the last loaded data; it may be out of date.'}</p>
    {error.status !== 410 && <button className="text-button" onClick={retry} disabled={waiting}>{waiting ? `Try again in ${Math.ceil((error.retryAt - now) / 1000)}s` : error.status === 409 ? 'Refresh this view' : 'Try again'} <span aria-hidden="true">&rsaquo;</span></button>}
  </div>
}
export function ResourceNotice<T>({ resource, name }: { resource: Resource<T>; name: string }) {
  if (resource.error) return <RequestIssue error={resource.error} retry={resource.refresh} retained={resource.data !== null} />
  if (!resource.data && resource.loading) return <p className="empty" role="status">Loading {name}...</p>
  return null
}
export function AsOf({ at, published }: { at: string | null | undefined; published?: string | null }) {
  return <p className="as-of">{at ? <>Data as of <time dateTime={at}>{when(at)}</time></> : 'Data time unavailable'}{published && <span> · Published {when(published)}</span>}</p>
}
export function Fact({ name, children }: { name: string; children: ReactNode }) { return <div><dt>{name}</dt><dd>{children}</dd></div> }
export function TextList({ items, empty = 'None published.' }: { items: string[] | undefined; empty?: string }) {
  return items?.length ? <ul>{items.map((value, index) => <li key={index}>{value}</li>)}</ul> : <Empty>{empty}</Empty>
}


export class SectionBoundary extends Component<{ children: ReactNode; resetKey: unknown; retry: () => void; name: string }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidUpdate(previous: Readonly<{ resetKey: unknown }>) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false })
  }
  render() {
    if (this.state.failed) return <div className="request-issue" role="alert"><p>The {this.props.name} response couldn't be displayed.</p><button className="text-button" onClick={this.props.retry}>Try again</button></div>
    return this.props.children
  }
}
