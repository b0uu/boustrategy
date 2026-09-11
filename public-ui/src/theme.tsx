import { useEffect, useState } from 'react'
import { Moon, Sun } from '@phosphor-icons/react'

// Dark is the default; only an explicit choice of light is stored, and /assets/theme-v1.js reads
// the same key before first paint so the page never flashes the wrong theme.
const STORAGE = 'boustrategy-theme'
type Theme = 'dark' | 'light'

function saved(): Theme {
  try {
    return localStorage.getItem(STORAGE) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark' // Site data is blocked; the reader gets the default each visit.
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(saved)
  useEffect(() => {
    if (theme === 'light') document.documentElement.dataset.theme = 'light'
    else delete document.documentElement.dataset.theme
    try {
      localStorage.setItem(STORAGE, theme)
    } catch { /* nothing to remember the choice with */ }
  }, [theme])
  const next = theme === 'dark' ? 'light' : 'dark'
  const label = `Switch to ${next} theme`
  return <button type="button" className="theme-toggle" title={label} aria-label={label} onClick={() => setTheme(next)}>
    {theme === 'dark' ? <Sun size={17} weight="regular" /> : <Moon size={17} weight="regular" />}
  </button>
}
