import type { DecimalValue } from './types'

export function numeric(value: DecimalValue | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
export function money(value: DecimalValue | undefined, compact = false) {
  const number = numeric(value)
  return number === null ? 'Unavailable' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: compact ? 'compact' : 'standard', maximumFractionDigits: 2 }).format(Math.abs(number) < .005 ? 0 : number)
}
export function amount(value: DecimalValue | undefined) {
  const number = numeric(value)
  if (number === null) return 'Unavailable'
  if (typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value)) {
    const [whole, fraction = ''] = value.split('.')
    const digits = fraction.replace(/0+$/, '')
    return (whole.startsWith('-') && BigInt(whole) === 0n && digits ? '-' : '') + BigInt(whole).toLocaleString('en-US') + (digits ? '.' + digits : '')
  }
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 18 }).format(number)
}
export function percent(value: DecimalValue | undefined, signed = true) {
  const number = numeric(value)
  if (number === null) return 'Unavailable'
  const rounded = Math.abs(number) < .005 ? 0 : number
  return `${signed && rounded > 0 ? '+' : ''}${rounded.toFixed(2)}%`
}
export const tone = (value: DecimalValue | undefined) => {
  const number = numeric(value)
  return number === null || Math.abs(number) < .005 ? '' : number > 0 ? 'positive' : 'negative'
}
export const weight = (value: number | null | undefined) => value === null || value === undefined ? 'Unavailable' : percent(value * 100, false)
export function when(value: string | null | undefined, short = false) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Time unavailable'
  return new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', dateStyle: short ? 'medium' : 'medium', ...(short ? {} : { timeStyle: 'short' as const }) }).format(new Date(value)) + (short ? '' : ' ET')
}
// A dense right-hand column wants the clock alone; the full timestamp stays in the body.
export function clock(value: string | null | undefined) {
  if (!value || !Number.isFinite(Date.parse(value))) return null
  return new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}
const labels: Record<string, string> = {
  no_action: 'No action', not_reviewed: 'Not reviewed', prepared: 'Intake prepared', running: 'Review in progress',
  snapshot_stale: 'The account snapshot needs refreshing', regime_missing: 'Completed-session regime data is missing',
  dependency_missing: 'Waiting for completed inputs', observer_stale: 'Scheduler observation is out of date',
  runtime_not_published: "Runtime status hasn't been published",
  observer_disabled: 'Scheduler is disabled', observer_missing: 'Scheduler has not been observed', manual: 'Manual reviews',
  grace_expired: 'Review window was missed', insufficient_research: "Review stopped: the research wasn't thorough enough", overlap: 'Another review was already running', lease_expired: 'Worker heartbeat expired',
  heartbeat_expired_unreconciled: 'Worker heartbeat expired; outcome has not been reconciled',
  not_applicable: 'Not applicable', missing_input: 'Missing input', paper_filled: 'Paper fill recorded',
  passed: 'Passed', failed: 'Failed', approved: 'Approved', rejected: 'Rejected',
  awaiting_paper_price: 'Waiting for paper price', broker_filled: 'Broker fill reported', partial: 'Partially available',
}
export const label = (value: string | null | undefined) => value ? labels[value.toLowerCase()] ?? value.replaceAll('_', ' ').toLowerCase() : 'Unavailable'
export function ruleValue(value: string | number | boolean | null | undefined, unit?: string) {
  if (value === null || value === undefined) return 'Unavailable'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return unit === 'fraction' && typeof value === 'number' ? weight(value) : String(value)
}
// A boolean threshold is a requirement, not an answer: "Yes" reads as an observation.
export function thresholdValue(value: string | number | boolean | null | undefined, unit?: string) {
  if (value === null || value === undefined) return 'Contextual'
  if (typeof value === 'boolean') return value ? 'Required' : 'Not required'
  return ruleValue(value, unit)
}
export function publicUrl(value: string | null | undefined) {
  if (!value) return null
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch { return null }
}
