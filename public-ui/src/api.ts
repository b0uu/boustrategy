import { useCallback, useEffect, useRef, useState } from 'react'
import type { Metadata } from './types'

export class PublicError extends Error {
  status: number
  retryAt: number
  constructor(status: number, message: string, retryAt = 0) {
    super(message)
    this.status = status
    this.retryAt = retryAt
  }
}

export type ResourceKind = 'overview' | 'positions' | 'performance' | 'policy' | 'runtime' | 'activity' | 'run' | 'feed' | 'decision'
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const array = (value: unknown): value is unknown[] => Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string'
const item = (value: unknown) => object(value) && text(value.public_id) && text(value.ticker) && text(value.public_summary) && text(value.created_at)

function valid(value: unknown, kind: ResourceKind): value is Metadata {
  if (!object(value) || value.api_version !== 2 || !text(value.server_now) || !Number.isFinite(Date.parse(value.server_now))) return false
  if (kind === 'feed') return array(value.items) && value.items.every(item) && typeof value.total === 'number' && (value.next_cursor === null || text(value.next_cursor))
  if (kind === 'positions') return array(value.items) && value.items.every(p => object(p) && text(p.ticker)) && text(value.status)
  if (kind === 'overview') return text(value.status) && typeof value.decisions_today === 'number' && object(value.decision_counts) && object(value.capabilities)
  if (kind === 'performance') return array(value.history) && value.history.every(p => object(p) && text(p.at) && Number.isFinite(Date.parse(p.at))) && text(value.status)
  if (kind === 'policy') return value.status === 'unavailable' || (array(value.decision_rules) && value.decision_rules.every(p => object(p) && text(p.rule_id) && text(p.name)))
  if (kind === 'runtime') return array(value.schedules) && value.schedules.every(s => object(s) && text(s.schedule_mode))
  if (kind === 'activity') return array(value.items) && value.items.every(r => object(r) && text(r.public_id) && text(r.status)) && typeof value.total === 'number'
  if (kind === 'run') return text(value.public_id) && text(value.status) && array(value.attempts)
  if (!item(value) || !object(value.policy_evaluation) || !array(value.policy_evaluation.checks) || !array(value.milestones) || !object(value.execution) || !array(value.execution.items)) return false
  if (value.narrative !== null && (!object(value.narrative) || !array(value.narrative.stages) || !array(value.narrative.claims) || !array(value.narrative.sources))) return false
  return object(value.model_provenance) && object(value.x_usage) && array(value.claims)
}

export async function readPublic<T>(url: string, kind: ResourceKind, signal: AbortSignal): Promise<{ data: T; offset: number }> {
  const started = Date.now()
  let response: Response
  try {
    response = await fetch(url, { signal, headers: { Accept: 'application/json' }, cache: 'no-store' })
  } catch (error) {
    if (signal.aborted) throw error
    throw new PublicError(0, navigator.onLine ? "Couldn't reach the public record." : "You're offline. The last loaded record may be out of date.")
  }
  if (!response.ok) {
    const retry = response.headers.get('Retry-After')
    const seconds = retry && /^\d+$/.test(retry) ? Number(retry) * 1000 : 0
    const retryAt = retry ? seconds ? Date.now() + seconds : Date.parse(retry) : 0
    const messages: Record<number, string> = {
      404: "This public record wasn't found.", 410: 'This record has been withdrawn from publication.',
      409: 'Published records changed. Refresh to restart this view.', 422: 'This link or filter is invalid.',
      429: 'Too many requests. Please wait before trying again.',
    }
    throw new PublicError(response.status, messages[response.status] ?? "The public record is temporarily unavailable.", Number.isFinite(retryAt) ? retryAt : 0)
  }
  let value: unknown
  try {
    const body = await response.text()
    if (body.length > 2_000_000) throw new Error('Response too large')
    value = JSON.parse(body)
  } catch {
    throw new PublicError(502, "The server returned an unreadable public record.")
  }
  if (!valid(value, kind)) throw new PublicError(502, "The public record has an unexpected format.")
  return { data: value as T, offset: Date.parse(value.server_now) - (started + Date.now()) / 2 }
}

export interface Resource<T> { data: T | null; loading: boolean; stale: boolean; error: PublicError | null; offset: number; refresh: () => void }

export function usePublic<T>(url: string | null, kind: ResourceKind, poll = 60_000): Resource<T> {
  const [state, setState] = useState<{ url: string | null; data: T | null; loading: boolean; error: PublicError | null; offset: number }>({ url, data: null, loading: !!url, error: null, offset: 0 })
  const [revision, setRevision] = useState(0)
  const generation = useRef(0)
  const retryGate = useRef({ url: "", until: 0 })
  const refresh = useCallback(() => setRevision(n => n + 1), [])
  useEffect(() => {
    if (!url) return
    const wait = retryGate.current.url === url ? retryGate.current.until - Date.now() : 0
    if (wait > 0) {
      const timer = window.setTimeout(refresh, Math.min(wait, 60_000))
      return () => window.clearTimeout(timer)
    }
    const controller = new AbortController()
    const request = ++generation.current
    setState(previous => ({ ...previous, url, data: previous.data, loading: true, error: null }))
    readPublic<T>(url, kind, controller.signal).then(result => {
      if (!controller.signal.aborted && request === generation.current) setState({ url, data: result.data, offset: result.offset, loading: false, error: null })
    }).catch((error: unknown) => {
      if (controller.signal.aborted || request !== generation.current) return
      const failure = error instanceof PublicError ? error : new PublicError(502, 'The public record could not be read.')
      retryGate.current = { url, until: failure.retryAt }
      setState(previous => ({ ...previous, url, data: failure.status === 410 ? null : previous.data, loading: false, error: failure }))
      if (failure.status === 410) window.dispatchEvent(new CustomEvent('public-retraction', { detail: url }))
    })
    return () => controller.abort()
  }, [url, kind, revision, refresh])
  useEffect(() => {
    if (!url) return
    const wake = () => { if (document.visibilityState !== 'hidden') refresh() }
    const retract = (event: Event) => {
      if ((event as CustomEvent<string>).detail === url) return
      generation.current += 1
      setState({ url, data: null, loading: true, error: null, offset: 0 })
      refresh()
    }
    const timer = poll ? window.setInterval(wake, poll) : undefined
    window.addEventListener('online', wake)
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('public-retraction', retract)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('online', wake)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('public-retraction', retract)
    }
  }, [url, poll, refresh])
  return { ...state, stale: state.url !== url, error: state.url === url ? state.error : null, refresh }
}
