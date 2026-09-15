import { useEffect, useState } from 'react'
import { Moon, Sun } from '@phosphor-icons/react'

// Light is the default. Only a reader's explicit click is stored, so a visit alone never pins a
// theme, and /assets/theme-v2.js reads the same key before first paint so the page never flashes
// the wrong one. The key moved to v2 when light became the default: the v1 key held the old dark
// default for every visitor, not just readers who chose it.
const STORAGE = 'boustrategy-theme-v2'
type Theme = 'dark' | 'light'

function saved(): Theme {
  try {
    return localStorage.getItem(STORAGE) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light' // Site data is blocked; the reader gets the default each visit.
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(saved)
  useEffect(() => {
    if (theme === 'light') document.documentElement.dataset.theme = 'light'
    else delete document.documentElement.dataset.theme
  }, [theme])
  const next = theme === 'dark' ? 'light' : 'dark'
  const choose = () => {
    setTheme(next)
    try {
      localStorage.setItem(STORAGE, next)
    } catch { /* nothing to remember the choice with */ }
  }
  const label = `Switch to ${next} theme`
  return <button type="button" className="theme-toggle" title={label} aria-label={label} onClick={choose}>
    {theme === 'dark' ? <Sun size={17} weight="regular" /> : <Moon size={17} weight="regular" />}
  </button>
}
