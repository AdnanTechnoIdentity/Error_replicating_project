import { useEffect, useState, useCallback } from 'react'
import ServiceCard from './components/ServiceCard'
import ErrorFeed from './components/ErrorFeed'
import ChaosPanel from './components/ChaosPanel'
import { fetchState, type AppState } from './services/api'

const OVERALL_STATUS = (services: AppState['services']) => {
  const statuses = Object.values(services).map(s => s.status)
  if (statuses.includes('CRITICAL')) return { label: 'CRITICAL', color: '#ef4444' }
  if (statuses.includes('DEGRADED')) return { label: 'DEGRADED', color: '#f59e0b' }
  return { label: 'HEALTHY', color: '#22c55e' }
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const s = await fetchState()
      setState(s)
      setError('')
    } catch {
      setError('Cannot reach NexusShop backend — is it running on :9000?')
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [refresh])

  const overall = state ? OVERALL_STATUS(state.services) : { label: 'CONNECTING…', color: '#78716c' }

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0c0a09',
      color: '#f5f5f4',
      fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
      padding: '1.5rem',
    }}>
      {/* Header */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '1.5rem',
        borderBottom: '1px solid #292524',
        paddingBottom: '1rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 28 }}>🛒</span>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: '#fb923c' }}>NexusShop</h1>
            <p style={{ margin: 0, fontSize: 12, color: '#78716c' }}>Live System Status</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: overall.color, display: 'inline-block' }} />
          <span style={{ fontWeight: 700, color: overall.color, fontSize: 14 }}>{overall.label}</span>
        </div>
      </header>

      {error && (
        <div style={{ background: '#7f1d1d', border: '1px solid #dc2626', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: 13, color: '#fca5a5' }}>
          {error}
        </div>
      )}

      {/* Service cards */}
      <div style={{ display: 'flex', gap: 16, marginBottom: '1.25rem', flexWrap: 'wrap' }}>
        {state
          ? Object.entries(state.services).map(([name, svc]) => (
              <ServiceCard key={name} name={name} state={svc} />
            ))
          : ['payments', 'orders', 'users'].map(n => (
              <div key={n} style={{ flex: 1, minWidth: 180, height: 140, background: '#1c1917', borderRadius: 12, border: '1px solid #292524' }} />
            ))}
      </div>

      {/* Chaos panel */}
      <div style={{ marginBottom: '1.25rem' }}>
        <ChaosPanel onAction={refresh} />
      </div>

      {/* Error feed */}
      <ErrorFeed errors={state?.recent_errors ?? []} />
    </div>
  )
}
