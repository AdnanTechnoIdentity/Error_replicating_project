import type { ServiceState } from '../services/api'

interface Props {
  name: string
  state: ServiceState
}

const STATUS_CONFIG = {
  HEALTHY: { dot: '🟢', bg: '#14532d', border: '#16a34a', text: '#86efac' },
  DEGRADED: { dot: '🟡', bg: '#713f12', border: '#ca8a04', text: '#fde68a' },
  CRITICAL: { dot: '🔴', bg: '#7f1d1d', border: '#dc2626', text: '#fca5a5' },
} as const

export default function ServiceCard({ name, state }: Props) {
  const cfg = STATUS_CONFIG[state.status] ?? STATUS_CONFIG.HEALTHY
  const errPct = Math.round(state.error_rate * 100)

  return (
    <div style={{
      background: cfg.bg,
      border: `2px solid ${cfg.border}`,
      borderRadius: 12,
      padding: '1.25rem',
      flex: 1,
      minWidth: 180,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 14, letterSpacing: 2, color: '#e5e7eb' }}>
          {name.toUpperCase()}
        </span>
        <span>{cfg.dot}</span>
      </div>

      <div style={{ fontSize: 18, fontWeight: 800, color: cfg.text, marginBottom: 12 }}>
        {state.status}
      </div>

      {state.active_scenario && (
        <div style={{ fontSize: 11, color: '#fcd34d', background: 'rgba(0,0,0,0.3)', borderRadius: 6, padding: '2px 8px', marginBottom: 10, display: 'inline-block' }}>
          {state.active_scenario.replace(/_/g, ' ')}
        </div>
      )}

      <div style={{ display: 'grid', gap: 4, fontSize: 12, color: '#d1d5db' }}>
        <div>RT: <strong style={{ color: cfg.text }}>{state.response_time_ms.toLocaleString()}ms</strong></div>
        <div>ERR: <strong style={{ color: cfg.text }}>{errPct}%</strong></div>
        <div>DB: <strong style={{ color: cfg.text }}>{state.db_connections}/{state.db_max}</strong></div>
      </div>
    </div>
  )
}
