import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { useEventStore } from './store/eventStore'

// Dev-only hook so tooling (scripts/snap.mjs) can drive scene/runner
// selection directly instead of clicking fragile canvas coordinates.
// Never included in a production build.
if (import.meta.env.DEV) {
  ;(window as unknown as { __paddockStore: typeof useEventStore }).__paddockStore = useEventStore
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
