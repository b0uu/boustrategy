// Development-only colour workbench. It is imported behind `import.meta.env.DEV` in main.tsx,
// so it is tree-shaken out of the production bundle and never reaches boustrategy.com.
// Run `npm --prefix public-ui run dev` and open http://localhost:5173/?lab
import { useEffect, useState } from 'react'

type Palette = Record<string, string>

// Today's tokens, converted from the OKLCH values in styles.css.
const CURRENT: Palette = {
  bg: '#0a0b0d', surface: '#111315', 'surface-2': '#191b1d', border: '#313336', 'border-soft': '#222427',
  text: '#eaebed', 'text-2': '#b4b7bd', 'text-3': '#8c8f94',
  indigo: '#8eb5ff', 'indigo-bg': '#1d2842', coral: '#ff847d', 'coral-bg': '#47211e',
  green: '#67d283', 'green-bg': '#0f3118', amber: '#ebbd57', 'amber-bg': '#3c2b02',
}

// Starting points built around the agent mark: blue #3838cd on gray #e5e5e5.
const PRESETS: Record<string, Palette> = {
  'Current dark': CURRENT,
  'Mark blue, dark': {
    ...CURRENT, bg: '#0b0c12', surface: '#12141d', 'surface-2': '#1a1d29', border: '#2f3345', 'border-soft': '#232739',
    indigo: '#9aa4ff', 'indigo-bg': '#232a5c',
  },
  'Paper light': {
    bg: '#e9e9ea', surface: '#f4f4f5', 'surface-2': '#dededf', border: '#c4c4c7', 'border-soft': '#d5d5d8',
    text: '#16171a', 'text-2': '#3f4147', 'text-3': '#65686f',
    indigo: '#3838cd', 'indigo-bg': '#dcdcf7', coral: '#b3261e', 'coral-bg': '#f7dedc',
    green: '#166534', 'green-bg': '#d8efdf', amber: '#7a5200', 'amber-bg': '#f6e6c2',
  },
  'Warm slate': {
    ...CURRENT, bg: '#100f0e', surface: '#181614', 'surface-2': '#211e1b', border: '#3a3531', 'border-soft': '#2a2623',
    text: '#efece8', 'text-2': '#bcb5ad', 'text-3': '#928a82', indigo: '#a5b4ff', amber: '#e8b866',
  },
}

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
// WCAG contrast so a palette can be judged for readability, not only taste.
function contrast(a: string, b: string) {
  const [x, y] = [a, b].map(hex => {
    const [r, g, bl] = channel(hex)
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  })
  return ((Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)).toFixed(2)
}

function apply(palette: Palette) {
  for (const [token, value] of Object.entries(palette)) document.documentElement.style.setProperty(`--${token}`, value)
}

export default function ThemeLab() {
  const [palette, setPalette] = useState<Palette>(() => {
    try {
      const saved = localStorage.getItem(STORAGE)
      return saved ? { ...CURRENT, ...JSON.parse(saved) } : CURRENT
    } catch { return CURRENT }
  })
  const [open, setOpen] = useState(true)
  useEffect(() => {
    apply(palette)
    try { localStorage.setItem(STORAGE, JSON.stringify(palette)) } catch { /* private window */ }
  }, [palette])

  const css = `:root {\n${Object.entries(palette).map(([token, value]) => `  --${token}: ${value};`).join('\n')}\n}`
  return <aside className="theme-lab" data-open={open}>
    <header>
      <strong>Theme lab</strong>
      <button className="text-button" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'}</button>
    </header>
    {open && <div className="theme-lab-body">
      <div className="theme-lab-presets">
        {Object.entries(PRESETS).map(([name, preset]) => <button key={name} className="text-button" onClick={() => setPalette(preset)}>{name}</button>)}
      </div>
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
        <button className="text-button" onClick={() => setPalette(CURRENT)}>Reset</button>
      </div>
      <p className="quiet">Contrast is text against the page background; 4.5:1 is the readable floor. Changes stay in this browser.</p>
    </div>}
  </aside>
}
