import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CatalogEntry, Service, fetchCatalog } from './api'
import { fmtNumber } from './format'

function useDebounce<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function ModelsPage() {
  const [params, setParams] = useSearchParams()
  const service = (params.get('service') as Service | null) || ''
  const aliveOnly = params.get('alive') !== '0'
  const initialQ = params.get('q') ?? ''

  const [searchInput, setSearchInput] = useState(initialQ)
  const debQ = useDebounce(searchInput, 250)

  const [items, setItems] = useState<CatalogEntry[] | null>(null)
  const [total, setTotal] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function setQp(patch: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') p.delete(k)
      else p.set(k, v)
    }
    setParams(p, { replace: true })
  }

  useEffect(() => {
    setQp({ q: debQ || null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debQ])

  useEffect(() => {
    setLoading(true)
    setErr(null)
    fetchCatalog({
      service: service || undefined,
      q: debQ || undefined,
      alive_only: aliveOnly,
      limit: 1000,
    })
      .then((res) => {
        setItems(res.items)
        setTotal(res.total)
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [service, aliveOnly, debQ])

  const totalsByService = useMemo(() => {
    const t: Record<string, number> = { comfyui: 0, ollama: 0 }
    if (!items) return t
    for (const it of items) t[it.service] = (t[it.service] ?? 0) + it.count
    return t
  }, [items])

  return (
    <div>
      <div className="section-title">
        <h2>model catalog</h2>
        <span className="muted" style={{ fontSize: 12 }}>
          unique models across {aliveOnly ? 'alive' : 'all'} instances
        </span>
      </div>

      <div className="toolbar">
        <select
          value={service || ''}
          onChange={(e) => setQp({ service: e.target.value || null })}
        >
          <option value="">all services</option>
          {([
            'comfyui', 'ollama', 'sdwebui', 'openwebui', 'jupyter',
            'vllm', 'tgi', 'ray', 'triton', 'tgwebui', 'lmstudio',
            'sglang', 'llamacpp', 'litellm', 'tensorboard',
          ] as Service[]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <input
          className="search"
          placeholder="search model name…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />

        <span className={`chip ${aliveOnly ? 'active' : ''}`} onClick={() => setQp({ alive: aliveOnly ? '0' : null })}>
          alive only
        </span>

        <div className="right row">
          {loading && <span className="spinner" />}
          <span className="muted" style={{ fontSize: 12 }}>
            {fmtNumber(total)} unique · ollama {fmtNumber(totalsByService.ollama)} · comfyui {fmtNumber(totalsByService.comfyui)}
          </span>
        </div>
      </div>

      {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>service</th>
              <th>model</th>
              <th className="num">instances</th>
              <th>open</th>
            </tr>
          </thead>
          <tbody>
            {items && items.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  no models match
                </td>
              </tr>
            )}
            {items?.map((it) => {
              const filterTo = `/?model=${encodeURIComponent(it.name.split('/').pop() ?? it.name)}&service=${it.service}`
              return (
                <tr key={`${it.service}/${it.name}`}>
                  <td>
                    <span className={`badge svc-${it.service}`}>{it.service}</span>
                  </td>
                  <td className="mono">{it.name}</td>
                  <td className="num">{fmtNumber(it.count)}</td>
                  <td>
                    <Link to={filterTo} className="btn plain icon">
                      ↗ instances
                    </Link>
                  </td>
                </tr>
              )
            })}
            {!items && (
              <tr>
                <td colSpan={4} className="empty">
                  <span className="spinner" /> loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
