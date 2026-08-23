import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyPresentMode } from './lib/present'

// Before the first render, so the projector never sees the small layout flash.
applyPresentMode(document, window.location.search)

const root = document.getElementById('root')
if (!root) throw new Error('ProofPay could not find its root element.')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
