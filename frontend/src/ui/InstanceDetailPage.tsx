import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Instance,
  InstanceChange,
  InstanceCheck,
  fetchChanges,
  fetchHistory,
  fetchInstance,
  refreshInstance,
} from './api'
import {
  adminToken,
  copy,
  fmtContext,
  fmtNumber,
  fmtParams,
  fmtRelative,
  fmtTime,
  fmtVram,
  providerColor,
  providerLabel,
} from './format'

type ComfyModels = {
  types?: string[]
  checkpoints?: string[]
  loras?: string[]
  vae?: string[]
  controlnet?: string[]
}

type OllamaShow = {
  name: string
  show?: {
    details?: { parameter_size?: string; family?: string; quantization_level?: string }
    model_info?: Record<string, any>
  }
}

type OllamaModels = {
  tags?: { models?: { name: string; size?: number }[] }
  show?: OllamaShow[]
}

function ComfyModelList({ models }: { models: ComfyModels | null | undefined }) {
  if (!models) return <div className="muted">no models metadata</div>
  const sections: { label: string; items: string[] }[] = [
    { label: 'checkpoints', items: models.checkpoints ?? [] },
    { label: 'loras', items: models.loras ?? [] },
    { label: 'vae', items: models.vae ?? [] },
    { label: 'controlnet', items: models.controlnet ?? [] },
  ].filter((s) => s.items.length > 0)
  if (sections.length === 0) {
    if (models.types?.length) {
      return <div className="muted">types reported: {models.types.join(', ')}</div>
    }
    return <div className="muted">no model details exposed</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {sections.map((s) => (
        <div key={s.label} className="tile">
          <div className="row" style={{ marginBottom: 6 }}>
            <strong style={{ textTransform: 'lowercase' }}>{s.label}</strong>
            <span className="muted">({s.items.length})</span>
          </div>
          <div className="mono" style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
            {s.items.map((m) => (
              <span key={m} title={m}>
                {m}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function parseParamSize(s?: string): number | null {
  if (!s) return null
  const m = s.match(/^([\d.]+)\s*([BMK])/i)
  if (!m) return null
  const n = parseFloat(m[1])
  const unit = m[2].toUpperCase()
  if (unit === 'B') return n
  if (unit === 'M') return n / 1000
  return null
}

function OllamaModelTable({ models }: { models: OllamaModels | null | undefined }) {
  if (!models) return <div className="muted">no models metadata</div>

  const tagsList = models.tags?.models ?? []
  const showByName = new Map<string, OllamaShow['show']>()
  for (const s of models.show ?? []) showByName.set(s.name, s.show)

  if (tagsList.length === 0) return <div className="muted">no model details exposed</div>

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>name</th>
            <th>family</th>
            <th className="num">params</th>
            <th>quant</th>
            <th className="num">size</th>
            <th className="num">context</th>
          </tr>
        </thead>
        <tbody>
          {tagsList.map((m) => {
            const sd = showByName.get(m.name)
            const params = parseParamSize(sd?.details?.parameter_size)
            let ctx: number | null = null
            const mi = sd?.model_info ?? {}
            for (const k of Object.keys(mi)) {
              if (k.includes('context_length') && typeof mi[k] === 'number') {
                if (ctx === null || mi[k] > ctx) ctx = mi[k]
              }
            }
            const sizeGb = m.size ? m.size / 1024 ** 3 : null
            return (
              <tr key={m.name}>
                <td className="mono">{m.name}</td>
                <td>{sd?.details?.family ?? '—'}</td>
                <td className="num">{fmtParams(params)}</td>
                <td className="mono">{sd?.details?.quantization_level ?? '—'}</td>
                <td className="num">{sizeGb ? `${sizeGb.toFixed(2)} GB` : '—'}</td>
                <td className="num">{fmtContext(ctx)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function fmtAfter(c: InstanceChange): string {
  const k = c.kind
  if (k === 'first_seen') return 'first seen'
  if (k === 'alive_changed') return c.after?.alive ? 'came back alive' : 'went down'
  if (k === 'version_changed') return `version: ${c.before?.version ?? '—'} → ${c.after?.version ?? '—'}`
  if (k === 'gpu_changed') return `gpu: ${c.before?.gpu ?? '—'} → ${c.after?.gpu ?? '—'}`
  if (k === 'models_changed') {
    const a = c.after?.added?.length ?? 0
    const r = c.after?.removed?.length ?? 0
    return `models changed: +${a} / −${r}`
  }
  return k
}

function HistorySpark({ rows }: { rows: InstanceCheck[] | null }) {
  if (!rows || rows.length === 0) return <div className="muted">no history yet — appears after the next re-check</div>
  // rows are newest-first; reverse for left-to-right time
  const ordered = [...rows].reverse()
  const w = Math.max(180, ordered.length * 6)
  const h = 18
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      {ordered.map((r, i) => (
        <rect
          key={r.id}
          x={i * 6}
          y={0}
          width={5}
          height={h}
          rx={1.5}
          fill={r.is_alive ? 'var(--accent)' : 'var(--danger)'}
          opacity={r.is_alive ? 0.9 : 0.7}
        >
          <title>{`${r.checked_at} · ${r.is_alive ? 'alive' : 'down'}`}</title>
        </rect>
      ))}
    </svg>
  )
}

export default function InstanceDetailPage() {
  const { id } = useParams()
  const [item, setItem] = useState<Instance | null>(null)
  const [history, setHistory] = useState<InstanceCheck[] | null>(null)
  const [changes, setChanges] = useState<InstanceChange[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function load() {
    if (!id) return
    setErr(null)
    try {
      const [inst, hist, ch] = await Promise.all([
        fetchInstance(id),
        fetchHistory(Number(id), 200).catch(() => [] as InstanceCheck[]),
        fetchChanges(Number(id), 50).catch(() => [] as InstanceChange[]),
      ])
      setItem(inst)
      setHistory(hist)
      setChanges(ch)
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    load()
  }, [id])

  async function onRefresh() {
    if (!item) return
    setRefreshing(true)
    setErr(null)
    try {
      const updated = await refreshInstance(item.id, adminToken() || undefined)
      setItem(updated)
    } catch (e) {
      setErr(String(e))
    } finally {
      setRefreshing(false)
    }
  }

  if (err) return <div className="error">{err}</div>
  if (!item) return <div className="muted"><span className="spinner" /> loading…</div>

  const url = `http://${item.ip}:${item.port}`
  const country = item.shodan?.location?.country_name ?? null
  const city = item.shodan?.location?.city ?? null
  const org = item.shodan?.org ?? null
  const isp = item.shodan?.isp ?? null
  const asn = item.shodan?.asn ?? null

  return (
    <div>
      <div style={{ marginBottom: 14 }}>
        <Link to="/" className="plain muted">
          ← back to instances
        </Link>
      </div>

      <div className="row wrap" style={{ marginBottom: 16, gap: 12 }}>
        <span className={`badge svc-${item.service}`}>{item.service}</span>
        <h2 className="mono" style={{ textTransform: 'none' }}>{item.ip}:{item.port}</h2>
        <span className={`badge ${item.is_alive ? 'alive' : 'dead'}`}>{item.is_alive ? 'alive' : 'down'}</span>
        <span className="pchip" style={{ color: providerColor(item.provider), background: 'var(--tile)' }}>
          {providerLabel(item.provider)}
        </span>
        <div className="right row" style={{ gap: 6 }}>
          <a className="btn plain" href={url} target="_blank" rel="noreferrer">
            ↗ open
          </a>
          <button onClick={() => copy(url)}>⧉ copy url</button>
          <button onClick={onRefresh} disabled={refreshing}>
            {refreshing ? <><span className="spinner" />refreshing</> : '↻ refresh'}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="kv">
          <div className="k">last seen</div>
          <div className="v" title={item.last_seen_at}>{fmtRelative(item.last_seen_at)}</div>

          <div className="k">first seen</div>
          <div className="v">{fmtTime(item.first_seen_at)}</div>

          <div className="k">last checked</div>
          <div className="v" title={item.last_checked_at}>{fmtRelative(item.last_checked_at)}</div>

          <div className="k">version</div>
          <div className="v mono">{item.version ?? '—'}</div>

          <div className="k">gpu</div>
          <div className="v">{item.gpu_name ?? '—'}</div>

          <div className="k">vram</div>
          <div className="v">{fmtVram(item.vram_total_gb, item.vram_free_gb)}</div>

          <div className="k">ram</div>
          <div className="v">{fmtVram(item.ram_total_gb, item.ram_free_gb)}</div>

          <div className="k">models</div>
          <div className="v">{fmtNumber(item.model_count ?? null)}</div>

          <div className="k">max params</div>
          <div className="v">{fmtParams(item.max_model_params)}</div>

          <div className="k">max context</div>
          <div className="v">{fmtContext(item.max_context)}</div>

          <div className="k">node count</div>
          <div className="v">{fmtNumber(item.node_count ?? null)}</div>

          <div className="k">reverse dns</div>
          <div className="v mono" style={{ wordBreak: 'break-all' }}>{item.reverse_dns ?? '—'}</div>

          <div className="k">country / city</div>
          <div className="v">{[country, city].filter(Boolean).join(' / ') || '—'}</div>

          <div className="k">org / isp</div>
          <div className="v">{[org, isp].filter(Boolean).join(' / ') || '—'}</div>

          <div className="k">asn</div>
          <div className="v mono">{asn ?? '—'}</div>

          <div className="k">discovered via</div>
          <div className="v">
            {item.discovery_sources && item.discovery_sources.length > 0
              ? item.discovery_sources.map((s) => (
                  <span key={s} className="badge" style={{ marginRight: 4 }}>{s}</span>
                ))
              : '—'}
          </div>

          {item.last_error && (
            <>
              <div className="k">last error</div>
              <div className="v" style={{ color: 'var(--danger)' }}>{item.last_error}</div>
            </>
          )}
        </div>
      </div>

      <div className="section-title">
        <h3>history</h3>
        <span className="muted" style={{ fontSize: 12 }}>
          {history?.length ?? 0} checks recorded
        </span>
      </div>
      <div className="card" style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <HistorySpark rows={history} />
        <div className="muted" style={{ fontSize: 11 }}>
          oldest <span className="kbd">·</span> newest — green = alive, red = down. hover for timestamp.
        </div>
      </div>

      {changes && changes.length > 0 && (
        <>
          <div className="section-title">
            <h3>changes</h3>
            <span className="muted" style={{ fontSize: 12 }}>
              last {changes.length}
            </span>
          </div>
          <div className="card" style={{ marginBottom: 16 }}>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
              {changes.map((c) => (
                <li key={c.id} style={{ marginBottom: 4 }}>
                  <span className="muted mono" style={{ marginRight: 6 }}>
                    {fmtRelative(c.at)}
                  </span>
                  {fmtAfter(c)}
                  {c.kind === 'models_changed' &&
                    (c.after?.added?.length || c.after?.removed?.length) && (
                      <details style={{ display: 'inline-block', marginLeft: 6 }}>
                        <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>
                          show diff
                        </summary>
                        <div className="mono" style={{ fontSize: 11, marginTop: 4 }}>
                          {(c.after?.added ?? []).map((m: string) => (
                            <div key={'+' + m} style={{ color: 'var(--accent)' }}>
                              + {m}
                            </div>
                          ))}
                          {(c.after?.removed ?? []).map((m: string) => (
                            <div key={'-' + m} style={{ color: 'var(--danger)' }}>
                              − {m}
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      <div className="section-title">
        <h3>models</h3>
      </div>
      {item.service === 'comfyui' ? (
        <ComfyModelList models={item.models as ComfyModels | null} />
      ) : (
        <OllamaModelTable models={item.models as OllamaModels | null} />
      )}

      <details style={{ marginTop: 18 }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>raw service metadata</summary>
        <pre className="tile" style={{ marginTop: 8, overflow: 'auto', fontSize: 12 }}>
          {JSON.stringify(item.service_metadata, null, 2)}
        </pre>
      </details>

      <details style={{ marginTop: 8 }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>raw shodan record</summary>
        <pre className="tile" style={{ marginTop: 8, overflow: 'auto', fontSize: 12 }}>
          {JSON.stringify(item.shodan, null, 2)}
        </pre>
      </details>
    </div>
  )
}
