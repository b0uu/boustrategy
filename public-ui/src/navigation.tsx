import { useSyncExternalStore } from 'react'
import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import type { Scope } from './types'

const readingPositions = new Map<string, number>()

export function navigate(href: string, replace = false) {
  const target = new URL(href, location.href)
  if (target.origin !== location.origin) return
  const current = location.pathname + location.search
  if (!replace) {
    readingPositions.delete(current)
    readingPositions.set(current, window.scrollY)
    while (readingPositions.size > 20) readingPositions.delete(readingPositions.keys().next().value!)
    history.replaceState({ ...history.state, scrollY: window.scrollY }, '')
  }
  history[replace ? 'replaceState' : 'pushState'](replace ? history.state : { bou: true, scrollY: readingPositions.get(target.pathname + target.search) ?? 0 }, '', target.pathname + target.search + target.hash)
  window.dispatchEvent(new Event('bou-navigation'))
}

export function useLocation() {
  return useSyncExternalStore(listener => {
    window.addEventListener('popstate', listener)
    window.addEventListener('bou-navigation', listener)
    return () => {
      window.removeEventListener('popstate', listener)
      window.removeEventListener('bou-navigation', listener)
    }
  }, () => location.pathname + location.search, () => '/')
}

export function Link({ href = '/', onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const click = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || props.target || props.download) return
    if (new URL(href, location.href).origin !== location.origin) return
    event.preventDefault()
    navigate(href)
  }
  return <a {...props} href={href} onClick={click} />
}

export function dashboardUrl(changes: Record<string, string | null>, base = location.search) {
  const params = new URLSearchParams(base)
  for (const [name, value] of Object.entries(changes)) {
    if (value === null || value === '') params.delete(name)
    else params.set(name, value)
  }
  return '/' + (params.size ? '?' + params.toString() : '')
}

export const decisionUrl = (publicId: string, scope: Scope) => `/decisions/${encodeURIComponent(publicId)}?scope=${scope}`
