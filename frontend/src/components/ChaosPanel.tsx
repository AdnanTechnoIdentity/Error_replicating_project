import { useState } from 'react'
import { triggerChaos, recoverService } from '../services/api'

const SERVICES = ['payments', 'orders', 'users'] as const
type Service = typeof SERVICES[number]

const SCENARIOS = [
  { value: 'db_timeout', label: 'DB Timeout' },
  { value: 'db_pool_exhausted', label: 'DB Pool Exhausted' },
  { value: 'api_gateway_timeout', label: 'API Gateway Timeout' },
  { value: 'auth_failure', label: 'Auth Failure' },
  { value: 'memory_spike', label: 'Memory Spike' },
  { value: 'payment_failure', label: 'Payment Failure' },
  { value: 'deadlock', label: 'Deadlock' },
  { value: 'rate_limit', label: 'Rate Limit' },
  { value: 'cpu_spike', label: 'CPU Spike' },
  { value: 'cascade_failure', label: '⚡ Cascade Failure (All Services)' },
  { value: 'disk_full', label: 'Disk Full (ENOSPC)' },
]

const SELECT_STYLE: React.CSSProperties = {
  background: '#1c1917',
  color: '#f5f5f4',
  border: '1px solid #57534e',
  borderRadius: 8,
  padding: '0.5rem 0.75rem',
  fontSize: 13,
  cursor: 'pointer',
  flex: 1,
}

interface Props {
  onAction: () => void
}

export default function ChaosPanel({ onAction }: Props) {
  const [service, setService] = useState<Service>('payments')
  const [scenario, setScenario] = useState('db_timeout')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  async function handleTrigger() {
    setLoading(true)
    setMessage('')
    console.warn('[NexusShop:ChaosPanel.handleTrigger] chaos_trigger_initiated', {
      ts: new Date().toISOString(), source: 'nexusshop-ui',
      component: 'ChaosPanel', method: 'handleTrigger', file: 'src/components/ChaosPanel.tsx:51',
      service, scenario,
      user_intent: `Manually injecting ${scenario.replace(/_/g, ' ')} failure into ${service} service`,
      stack: 'handleTrigger (ChaosPanel.tsx:51)\nReact.MouseEvent.onClick (native)',
    })
    try {
      await triggerChaos(service, scenario)
      console.error('[NexusShop:ChaosPanel.handleTrigger] chaos_trigger_success', {
        ts: new Date().toISOString(), source: 'nexusshop-ui',
        component: 'ChaosPanel', method: 'handleTrigger', file: 'src/components/ChaosPanel.tsx:61',
        service, scenario,
        result: `${scenario} injected into ${service} — Nexus incident workflow starting`,
        next: 'Check Nexus dashboard for AI investigation progress',
      })
      setMessage(`✓ Triggered ${scenario} on ${service}`)
      onAction()
    } catch (e: unknown) {
      setMessage(`✗ ${e instanceof Error ? e.message : 'Error'}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleRecoverAll() {
    setLoading(true)
    setMessage('')
    console.log('[NexusShop:ChaosPanel.handleRecoverAll] recover_all_initiated', {
      ts: new Date().toISOString(), source: 'nexusshop-ui',
      component: 'ChaosPanel', method: 'handleRecoverAll', file: 'src/components/ChaosPanel.tsx:71',
      services: [...SERVICES],
      action: 'Cancelling all active chaos scenarios and restoring healthy state',
    })
    try {
      for (const svc of SERVICES) await recoverService(svc)
      setMessage('✓ All services recovered')
      onAction()
    } catch (e: unknown) {
      setMessage(`✗ ${e instanceof Error ? e.message : 'Error'}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ background: '#1c1917', border: '1px solid #44403c', borderRadius: 12, padding: '1rem' }}>
      <h3 style={{ margin: '0 0 0.75rem', fontSize: 13, letterSpacing: 2, color: '#a8a29e' }}>CHAOS PANEL</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={service} onChange={e => setService(e.target.value as Service)} style={SELECT_STYLE}>
          {SERVICES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
        </select>

        <select value={scenario} onChange={e => setScenario(e.target.value)} style={SELECT_STYLE}>
          {SCENARIOS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>

        <button
          onClick={handleTrigger}
          disabled={loading}
          style={{
            background: loading ? '#7f1d1d' : '#dc2626',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '0.5rem 1.2rem',
            fontWeight: 700,
            fontSize: 13,
            cursor: loading ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          🔴 TRIGGER ERROR
        </button>

        <button
          onClick={handleRecoverAll}
          disabled={loading}
          style={{
            background: loading ? '#14532d' : '#16a34a',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '0.5rem 1.2rem',
            fontWeight: 700,
            fontSize: 13,
            cursor: loading ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          ✅ Recover All
        </button>
      </div>

      {message && (
        <p style={{ margin: '0.6rem 0 0', fontSize: 12, color: message.startsWith('✓') ? '#86efac' : '#fca5a5' }}>
          {message}
        </p>
      )}
    </div>
  )
}
