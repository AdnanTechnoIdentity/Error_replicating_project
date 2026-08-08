const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:9000'
const CHAOS_SECRET = import.meta.env.VITE_CHAOS_SECRET ?? 'chaos-panel-secret'

export interface ServiceState {
  status: 'HEALTHY' | 'DEGRADED' | 'CRITICAL'
  active_scenario: string | null
  response_time_ms: number
  error_rate: number
  db_connections: number
  db_max: number
}

export interface ErrorEvent {
  id: string
  service: string
  scenario: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  timestamp: string
  message: string
}

export interface AppState {
  services: Record<string, ServiceState>
  recent_errors: ErrorEvent[]
}

export async function fetchState(): Promise<AppState> {
  const res = await fetch(`${API_URL}/state`)
  if (!res.ok) throw new Error('Failed to fetch state')
  return res.json()
}

export async function triggerChaos(service: string, scenario: string): Promise<void> {
  const res = await fetch(`${API_URL}/chaos/trigger`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Chaos-Key': CHAOS_SECRET,
    },
    body: JSON.stringify({ service, scenario }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to trigger chaos')
  }
}

export async function recoverService(service: string): Promise<void> {
  const res = await fetch(`${API_URL}/chaos/recover`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Chaos-Key': CHAOS_SECRET,
    },
    body: JSON.stringify({ service }),
  })
  if (!res.ok) throw new Error('Failed to recover')
}
