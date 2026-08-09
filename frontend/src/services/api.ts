const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:9000'
const CHAOS_SECRET = import.meta.env.VITE_CHAOS_SECRET ?? 'chaos-panel-secret'

function clog(
  level: 'log' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
  ctx?: { component: string; method: string; file: string }
) {
  const entry = {
    ts: new Date().toISOString(),
    source: 'nexusshop-ui',
    event,
    ...(ctx ?? {}),
    ...data,
  }
  const label = ctx ? `[NexusShop:${ctx.component}.${ctx.method}]` : '[NexusShop]'
  console[level](`${label} ${event}`, entry)
}

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
  const t0 = performance.now()
  const SRC = { component: 'ServiceHealthMonitor', method: 'fetchState', file: 'src/services/api.ts:44' }
  try {
    const res = await fetch(`${API_URL}/state`)
    const elapsed = Math.round(performance.now() - t0)
    if (!res.ok) {
      clog('error', 'fetch_state_http_error',
        { url: `${API_URL}/state`, status: res.status, elapsed_ms: elapsed,
          impact: 'Dashboard cannot refresh — all service health cards showing stale data' }, SRC)
      throw new Error('Failed to fetch state')
    }
    const data: AppState = await res.json()
    for (const [name, svc] of Object.entries(data.services)) {
      if (svc.status !== 'HEALTHY') {
        clog('warn', 'service_unhealthy', {
          service: name, status: svc.status, scenario: svc.active_scenario,
          error_rate_pct: Math.round(svc.error_rate * 100),
          response_time_ms: svc.response_time_ms,
          db_connections: `${svc.db_connections}/${svc.db_max}`,
          impact: `${name} is ${svc.status} — ${Math.round(svc.error_rate * 100)}% of user requests are failing`,
        }, SRC)
      }
    }
    return data
  } catch (err) {
    clog('error', 'fetch_state_failed',
      { url: `${API_URL}/state`, error: String(err), elapsed_ms: Math.round(performance.now() - t0),
        impact: 'Backend unreachable — is NexusShop running on :9000?',
        stack: 'fetchState (api.ts:44)\nApp.refresh (App.tsx:20)\nPromise.resolve (native)' }, SRC)
    throw err
  }
}

export async function triggerChaos(service: string, scenario: string): Promise<void> {
  const SRC = { component: 'ChaosController', method: 'triggerChaos', file: 'src/services/api.ts:77' }
  clog('warn', 'chaos_trigger_initiated',
    { service, scenario, payload: { service, scenario }, chaos_key_present: Boolean(CHAOS_SECRET),
      stack: 'triggerChaos (api.ts:77)\nChaosPanel.handleTrigger (ChaosPanel.tsx:51)\nReact.MouseEvent (native)' }, SRC)
  const t0 = performance.now()
  try {
    const res = await fetch(`${API_URL}/chaos/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Chaos-Key': CHAOS_SECRET },
      body: JSON.stringify({ service, scenario }),
    })
    const elapsed = Math.round(performance.now() - t0)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      clog('error', 'chaos_trigger_failed',
        { service, scenario, status: res.status, detail: body.detail, elapsed_ms: elapsed,
          reason: `POST /chaos/trigger returned HTTP ${res.status}` }, SRC)
      throw new Error(body.detail ?? 'Failed to trigger chaos')
    }
    const result = await res.json()
    clog('error', 'chaos_triggered',
      { service, scenario, webhook_sent: result.webhook_sent,
        auto_recovery_in_seconds: result.auto_recovery_in_seconds, elapsed_ms: elapsed,
        nexus_workflow_started: result.webhook_sent,
        note: 'Nexus incident workflow starting — monitor Nexus dashboard for AI investigation' }, SRC)
  } catch (err) {
    if (!(err instanceof Error && err.message !== 'Failed to trigger chaos')) {
      clog('error', 'chaos_trigger_exception', { service, scenario, error: String(err) }, SRC)
    }
    throw err
  }
}

export async function recoverService(service: string): Promise<void> {
  const SRC = { component: 'ChaosController', method: 'recoverService', file: 'src/services/api.ts:110' }
  clog('log', 'recovery_initiated', { service, action: `Cancelling active scenario on ${service}` }, SRC)
  const t0 = performance.now()
  try {
    const res = await fetch(`${API_URL}/chaos/recover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Chaos-Key': CHAOS_SECRET },
      body: JSON.stringify({ service }),
    })
    const elapsed = Math.round(performance.now() - t0)
    if (!res.ok) throw new Error('Failed to recover')
    clog('log', 'recovery_complete',
      { service, elapsed_ms: elapsed, result: `${service} restored to HEALTHY state` }, SRC)
  } catch (err) {
    clog('error', 'recovery_failed',
      { service, error: String(err), impact: `${service} may still be in error state` }, SRC)
    throw err
  }
}
