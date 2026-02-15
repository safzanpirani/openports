import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchInstances, Instance } from './api'

function fmt(s: string) {
  try {
    return new Date(s).toLocaleString()
  } catch {
    return s
  }
}

export default function InstancesPage() {
  const [items, setItems] = useState<Instance[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchInstances()
      .then(setItems)
      .catch((e) => setErr(String(e)))
  }, [])

  if (err) return <div style={{ color: 'crimson' }}>{err}</div>
  if (!items) return <div>Loading…</div>

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Instances</h3>
      <div style={{ overflowX: 'auto' }}>
        <table cellPadding={8} style={{ borderCollapse: 'collapse', minWidth: 900 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
              <th>Service</th>
              <th>Host</th>
              <th>Alive</th>
              <th>Version</th>
              <th>GPU (ComfyUI only)</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <td>{it.service}</td>
                <td>
                  <Link to={`/instances/${it.id}`}>
                    {it.ip}:{it.port}
                  </Link>
                </td>
                <td>{it.is_alive ? 'yes' : 'no'}</td>
                <td>{it.version ?? '—'}</td>
                <td>{it.gpu_name ?? '—'}</td>
                <td>{fmt(it.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
