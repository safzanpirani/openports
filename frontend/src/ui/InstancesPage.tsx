import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchInstances, Instance, Service } from './api'

function fmt(s: string) {
  try {
    return new Date(s).toLocaleString()
  } catch {
    return s
  }
}

const PROVIDER_STYLE: Record<string, { color: string; label: string }> = {
  aws: { color: '#ff9900', label: 'AWS' },
  gcp: { color: '#4285f4', label: 'GCP' },
  azure: { color: '#0078d4', label: 'Azure' },
  digitalocean: { color: '#0080ff', label: 'DO' },
  vultr: { color: '#007bfc', label: 'Vultr' },
  linode: { color: '#00b159', label: 'Linode' },
  hetzner: { color: '#d50c2d', label: 'Hetzner' },
  ovh: { color: '#123e6b', label: 'OVH' },
  oracle_cloud: { color: '#c74634', label: 'Oracle' },
  alibaba_cloud: { color: '#ff6a00', label: 'Alibaba' },
  scaleway: { color: '#4f0599', label: 'Scaleway' },
  residential: { color: '#666', label: 'Home ISP' },
  unknown: { color: '#aaa', label: 'Unknown' },
}

function providerLabel(p: string | null | undefined): string {
  if (!p) return '—'
  return PROVIDER_STYLE[p]?.label ?? p
}

export default function InstancesPage() {
  const [items, setItems] = useState<Instance[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [providerFilter, setProviderFilter] = useState('')

  const load = useCallback(() => {
    const params: { service?: Service; provider?: string } = {}
    if (providerFilter) params.provider = providerFilter
    fetchInstances(params)
      .then(setItems)
      .catch((e) => setErr(String(e)))
  }, [providerFilter])

  useEffect(() => {
    load()
  }, [load])

  if (err) return <div style={{ color: 'crimson' }}>{err}</div>
  if (!items) return <div>Loading…</div>

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Instances</h3>
        <select
          value={providerFilter}
          onChange={(e) => setProviderFilter(e.target.value)}
          style={{ padding: '2px 6px', fontSize: 13 }}
        >
          <option value="">All providers</option>
          <option value="vps">VPS / Cloud only</option>
          <option value="residential">Residential</option>
          <option value="unknown">Unknown</option>
          {Object.entries(PROVIDER_STYLE)
            .filter(([k]) => !['residential', 'unknown'].includes(k))
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
        </select>
        <button onClick={load}>Refresh</button>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table cellPadding={8} style={{ borderCollapse: 'collapse', minWidth: 1000 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
              <th>Service</th>
              <th>Host</th>
              <th>Provider</th>
              <th>Alive</th>
              <th>Version</th>
              <th>GPU</th>
              <th>Models</th>
              <th>VRAM</th>
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
                <td>
                  <span
                    title={it.reverse_dns ?? undefined}
                    style={{
                      color: PROVIDER_STYLE[it.provider ?? '']?.color ?? '#999',
                      fontWeight: 500,
                      fontSize: 12,
                    }}
                  >
                    {providerLabel(it.provider)}
                  </span>
                </td>
                <td>{it.is_alive ? 'yes' : 'no'}</td>
                <td>{it.version ?? '—'}</td>
                <td>{it.gpu_name ?? '—'}</td>
                <td>{it.model_count ?? '—'}</td>
                <td>{it.vram_total_gb ? `${it.vram_total_gb.toFixed(1)} GB` : '—'}</td>
                <td>{fmt(it.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
