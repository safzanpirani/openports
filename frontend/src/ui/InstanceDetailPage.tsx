import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchInstance, Instance } from './api'

export default function InstanceDetailPage() {
  const { id } = useParams()
  const [item, setItem] = useState<Instance | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    fetchInstance(id)
      .then(setItem)
      .catch((e) => setErr(String(e)))
  }, [id])

  if (err) return <div style={{ color: 'crimson' }}>{err}</div>
  if (!item) return <div>Loading…</div>

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link to="/">← back</Link>
      </div>

      <h3 style={{ marginTop: 0 }}>
        {item.service} @ {item.ip}:{item.port}
      </h3>

      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 8, maxWidth: 900 }}>
        <div>Alive</div>
        <div>{item.is_alive ? 'yes' : 'no'}</div>

        <div>Version</div>
        <div>{item.version ?? '—'}</div>

        <div>GPU</div>
        <div>{item.gpu_name ?? '— (Ollama typically does not expose GPU via HTTP API)'}</div>

        <div>Last error</div>
        <div>{item.last_error ?? '—'}</div>
      </div>

      <h4>Models</h4>
      <pre style={{ background: '#f7f7f7', padding: 12, overflow: 'auto' }}>{JSON.stringify(item.models, null, 2)}</pre>

      <h4>Metadata</h4>
      <pre style={{ background: '#f7f7f7', padding: 12, overflow: 'auto' }}>{JSON.stringify(item.metadata, null, 2)}</pre>
    </div>
  )
}
