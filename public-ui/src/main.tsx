import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)

// Colour workbench for local design work only: the branch is dropped from production builds,
// so it never ships to the public site. `npm run dev`, then open /?lab
if (import.meta.env.DEV && new URLSearchParams(location.search).has('lab')) {
  void import('./ThemeLab').then(({ default: ThemeLab }) => {
    const host = document.body.appendChild(document.createElement('div'))
    createRoot(host).render(<ThemeLab />)
  })
}
