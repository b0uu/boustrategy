// Development-only colour workbench. It is imported behind `import.meta.env.DEV` in main.tsx,
// so it is tree-shaken out of the production bundle and never reaches boustrategy.com.
// Run `npm --prefix public-ui run dev` and open http://localhost:5173/?lab
import { useCallback, useEffect, useState } from 'react'

type Palette = Record<string, string>

const TOKENS = [
  'bg', 'surface', 'surface-2', 'border', 'border-soft', 'text', 'text-2', 'text-3',
  'indigo', 'indigo-bg', 'green', 'green-bg', 'coral', 'coral-bg', 'amber', 'amber-bg',
]

// Ten starting points. Every text and accent colour clears WCAG AA against its own background
// (body text aims for 7:1), so a palette can be judged on looks alone.
const PRESETS: Record<string, Palette> = {
  'Cool slate': {
    scheme: 'dark', bg: '#0a0b0d', surface: '#111315', 'surface-2': '#191b1d', border: '#313336', 'border-soft': '#222427',
    text: '#eaebed', 'text-2': '#b4b7bd', 'text-3': '#8c8f94', indigo: '#8eb5ff', 'indigo-bg': '#1d2842',
    coral: '#ff847d', 'coral-bg': '#47211e', green: '#67d283', 'green-bg': '#0f3118', amber: '#ebbd57', 'amber-bg': '#3c2b02',
  },
  'Mark blue': {
    scheme: 'dark', bg: '#0b0c13', surface: '#12141e', 'surface-2': '#1a1d2b', border: '#333850', 'border-soft': '#242839',
    text: '#ebecf2', 'text-2': '#b6bacb', 'text-3': '#8b90a4', indigo: '#9fa9ff', 'indigo-bg': '#242b63',
    coral: '#ff8a82', 'coral-bg': '#48211f', green: '#6ed08d', 'green-bg': '#123420', amber: '#e8bd63', 'amber-bg': '#3b2c08',
  },
  Ink: {
    scheme: 'dark', bg: '#08080a', surface: '#0f1012', 'surface-2': '#17181b', border: '#2e3033', 'border-soft': '#202225',
    text: '#f2f2f4', 'text-2': '#b9babf', 'text-3': '#8e9095', indigo: '#8ab4ff', 'indigo-bg': '#18243c',
    coral: '#ff8b84', 'coral-bg': '#441f1d', green: '#6bd189', 'green-bg': '#0e3018', amber: '#eebf5e', 'amber-bg': '#3a2a05',
  },
  'Warm slate': {
    scheme: 'dark', bg: '#100f0e', surface: '#181614', 'surface-2': '#211e1b', border: '#3a3531', 'border-soft': '#2a2623',
    text: '#efece8', 'text-2': '#bcb5ad', 'text-3': '#948c83', indigo: '#a9b3ff', 'indigo-bg': '#262a55',
    coral: '#ff8f80', 'coral-bg': '#46231d', green: '#7bcf8c', 'green-bg': '#15301c', amber: '#e9bc6b', 'amber-bg': '#3a2a0d',
  },
  Graphite: {
    scheme: 'dark', bg: '#101214', surface: '#171a1d', 'surface-2': '#1f2327', border: '#363b41', 'border-soft': '#272c31',
    text: '#eef1f3', 'text-2': '#b7bec4', 'text-3': '#8d959c', indigo: '#8fc2f0', 'indigo-bg': '#1b3145',
    coral: '#f79188', 'coral-bg': '#432321', green: '#71cf95', 'green-bg': '#123222', amber: '#e5bd6e', 'amber-bg': '#372a11',
  },
  'Deep teal': {
    scheme: 'dark', bg: '#07100f', surface: '#0d1817', 'surface-2': '#142120', border: '#2a3b39', 'border-soft': '#1e2b2a',
    text: '#e9f1ef', 'text-2': '#aebebb', 'text-3': '#859a97', indigo: '#7fc7ff', 'indigo-bg': '#13303f',
    coral: '#ff8f86', 'coral-bg': '#42221f', green: '#5fd2a6', 'green-bg': '#0c3326', amber: '#e6c06a', 'amber-bg': '#362b0d',
  },
  Paper: {
    scheme: 'light', bg: '#e9e9ea', surface: '#f4f4f5', 'surface-2': '#dcdcde', border: '#bfbfc3', 'border-soft': '#d2d2d6',
    text: '#15161a', 'text-2': '#3d4046', 'text-3': '#5f636b', indigo: '#3434c4', 'indigo-bg': '#dcdcf7',
    coral: '#b3261e', 'coral-bg': '#f7dedc', green: '#15612f', 'green-bg': '#d7efdd', amber: '#6f4a00', 'amber-bg': '#f5e4bf',
  },
  Cream: {
    scheme: 'light', bg: '#f3efe7', surface: '#faf7f1', 'surface-2': '#e8e2d6', border: '#c9c1b2', 'border-soft': '#dbd4c6',
    text: '#1b1813', 'text-2': '#443d33', 'text-3': '#655c4e', indigo: '#31409c', 'indigo-bg': '#dfe2f6',
    coral: '#a33119', 'coral-bg': '#f7e0d8', green: '#1d5a2e', 'green-bg': '#dcebda', amber: '#6b4a05', 'amber-bg': '#f2e4c4',
  },
  Nordic: {
    scheme: 'light', bg: '#f1f4f8', surface: '#ffffff', 'surface-2': '#e3e8ef', border: '#c3cbd6', 'border-soft': '#d7dde5',
    text: '#10151c', 'text-2': '#39424f', 'text-3': '#5b6472', indigo: '#1d4ed8', 'indigo-bg': '#dbe4fb',
    coral: '#b02418', 'coral-bg': '#fadedb', green: '#12603a', 'green-bg': '#d5eee1', amber: '#71491a', 'amber-bg': '#f4e5cb',
  },
  'High contrast': {
    scheme: 'dark', bg: '#000000', surface: '#0c0c0d', 'surface-2': '#161617', border: '#3d3d40', 'border-soft': '#2a2a2c',
    text: '#ffffff', 'text-2': '#d6d6d9', 'text-3': '#a9a9ad', indigo: '#9cc4ff', 'indigo-bg': '#16233b',
    coral: '#ff9a92', 'coral-bg': '#3f1c1a', green: '#78e29a', 'green-bg': '#0b2c15', amber: '#f2c85f', 'amber-bg': '#33250a',
  },
}
const NAMES = Object.keys(PRESETS)
const DEFAULT = 'Warm slate' // What the site ships, so the lab opens on the real theme.

const GROUPS: Array<[string, string[]]> = [
  ['Surfaces', ['bg', 'surface', 'surface-2', 'border', 'border-soft']],
  ['Text', ['text', 'text-2', 'text-3']],
  ['Accents', ['indigo', 'indigo-bg', 'green', 'green-bg', 'coral', 'coral-bg', 'amber', 'amber-bg']],
]
const STORAGE = 'boustrategy-theme-lab'

function channel(hex: string) {
  const value = parseInt(hex.slice(1), 16)
  return [value >> 16, (value >> 8) & 255, value & 255].map(part => {
    const srgb = part / 255
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
}
// WCAG contrast, so a palette is judged for readability and not only taste.
function contrast(a: string, b: string) {
  const [x, y] = [a, b].map(hex => {
    const [r, g, bl] = channel(hex)
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  })
  return ((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2)
}

function apply(palette: Palette) {
  for (const token of TOKENS) document.documentElement.style.setProperty(`--${token}`, palette[token])
  // Form controls and scrollbars follow the palette instead of staying dark on a light theme.
  document.documentElement.style.colorScheme = palette.scheme ?? 'dark'
}

export default function ThemeLab() {
  const [name, setName] = useState<string>(() => localStorage.getItem(`${STORAGE}-name`) ?? DEFAULT)
  const [palette, setPalette] = useState<Palette>(() => {
    try {
      const saved = localStorage.getItem(STORAGE)
      return saved ? { ...PRESETS[DEFAULT], ...JSON.parse(saved) } : PRESETS[DEFAULT]
    } catch { return PRESETS[DEFAULT] }
  })
  // Collapsed by default: the preset grid stays visible, and the page behind it is not covered
  // by the token editor while you click through themes.
  const [open, setOpen] = useState(false)
  const choose = useCallback((next: string) => {
    setName(next)
    setPalette(PRESETS[next])
  }, [])
  const step = useCallback((delta: number) => {
    choose(NAMES[(NAMES.indexOf(name) + delta + NAMES.length) % NAMES.length])
  }, [choose, name])

  useEffect(() => {
    apply(palette)
    try {
      localStorage.setItem(STORAGE, JSON.stringify(palette))
      localStorage.setItem(`${STORAGE}-name`, name)
    } catch { /* private window */ }
  }, [palette, name])
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)
      if (typing) return
      if (event.key === 'ArrowRight') step(1)
      if (event.key === 'ArrowLeft') step(-1)
    }
    window.addEventListener('keydown', keys)
    return () => window.removeEventListener('keydown', keys)
  }, [step])

  const css = `:root {\n${TOKENS.map(token => `  --${token}: ${palette[token]};`).join('\n')}\n  color-scheme: ${palette.scheme ?? 'dark'};\n}`
  return <aside className="theme-lab" data-open={open}>
    <header>
      <strong>Theme lab</strong>
      <span className="quiet">{NAMES.indexOf(name) + 1}/{NAMES.length} · ← →</span>
      <button className="text-button" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'}</button>
    </header>
    <div className="theme-lab-presets">
      {NAMES.map(preset => <button key={preset} className="preset-chip" aria-pressed={preset === name} onClick={() => choose(preset)}>
        <span className="preset-swatch" style={{ background: PRESETS[preset].bg, borderColor: PRESETS[preset].border }}>
          <i style={{ background: PRESETS[preset].indigo }} /><i style={{ background: PRESETS[preset].green }} /><i style={{ background: PRESETS[preset].text }} />
        </span>
        {preset}
      </button>)}
    </div>
    {open && <div className="theme-lab-body">
      {GROUPS.map(([group, tokens]) => <section key={group}>
        <h3>{group}</h3>
        {tokens.map(token => <label key={token}>
          <input type="color" value={palette[token]} onChange={event => setPalette({ ...palette, [token]: event.target.value })} />
          <span>{token}</span>
          <code>{palette[token]}</code>
          {group === 'Text' && <em data-weak={Number(contrast(palette[token], palette.bg)) < 4.5 ? 'true' : 'false'}>{contrast(palette[token], palette.bg)}:1</em>}
        </label>)}
      </section>)}
      <div className="theme-lab-actions">
        <button className="text-button" onClick={() => void navigator.clipboard?.writeText(css)}>Copy CSS</button>
        <button className="text-button" onClick={() => choose(name)}>Reset preset</button>
      </div>
      <p className="quiet">Arrow keys step through presets. Contrast is text against the page background; 4.5:1 is the readable floor. Changes stay in this browser.</p>
    </div>}
  </aside>
}
