import type { ErrorEvent } from '../services/api'

interface Props {
  errors: ErrorEvent[]
}

const SEV_COLOR: Record<string, string> = {
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#22c55e',
}

export default function ErrorFeed({ errors }: Props) {
  return (
    <div style={{ background: '#1c1917', border: '1px solid #44403c', borderRadius: 12, padding: '1rem' }}>
      <h3 style={{ margin: '0 0 0.75rem', fontSize: 13, letterSpacing: 2, color: '#a8a29e' }}>RECENT ERRORS</h3>
      {errors.length === 0 && (
        <p style={{ color: '#57534e', fontSize: 13, margin: 0 }}>No errors — all systems nominal.</p>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
        {errors.map(ev => (
          <div key={ev.id} style={{
            display: 'grid',
            gridTemplateColumns: '70px 90px 60px 1fr',
            gap: 8,
            fontSize: 12,
            alignItems: 'center',
            color: '#d6d3d1',
            borderBottom: '1px solid #292524',
            paddingBottom: 6,
          }}>
            <span style={{ color: '#78716c', fontVariantNumeric: 'tabular-nums' }}>
              {ev.timestamp.slice(11, 19)}
            </span>
            <span style={{ color: '#fb923c', fontWeight: 600 }}>{ev.service}</span>
            <span style={{
              color: SEV_COLOR[ev.severity] ?? '#d6d3d1',
              fontWeight: 700,
              fontSize: 10,
              background: 'rgba(0,0,0,0.3)',
              borderRadius: 4,
              padding: '1px 5px',
              textAlign: 'center',
            }}>{ev.severity}</span>
            <span style={{ color: '#a8a29e' }}>{ev.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
