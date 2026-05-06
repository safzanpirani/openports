import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Distinct,
  Instance,
  InstanceQuery,
  Service,
  Stats,
  exportCsvUrl,
  fetchDistinct,
  fetchInstances,
  fetchStats,
  triggerShodanScan,
} from './api'
import {
  PROVIDER_STYLE,
  adminToken,
  copy,
  fmtContext,
  fmtNumber,
  fmtParams,
  fmtRelative,
  fmtVram,
  providerColor,
  providerLabel,
} from './format'

type SortKey =
  | 'last_seen_at'
  | 'first_seen_at'
  | 'vram_total_gb'
  | 'model_count'
  | 'max_model_params'
  | 'max_context'
  | 'node_count'

const PAGE_SIZE = 200

function useDebounce<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function StatsBar({ stats }: { stats: Stats | null }) {
  if (!stats) return null
  return (
    <div className="stats-grid">
      <div className="card stat">
        <div className="label">total</div>
        <div className="value">{fmtNumber(stats.total)}</div>
        <div className="sub">{fmtNumber(stats.alive)} alive</div>
      </div>
      <div className="card stat">
        <div className="label">comfyui</div>
        <div className="value">{fmtNumber(stats.by_service.comfyui?.total ?? 0)}</div>
        <div className="sub">{fmtNumber(stats.by_service.comfyui?.alive ?? 0)} alive</div>
      </div>
      <div className="card stat">
        <div className="label">ollama</div>
        <div className="value">{fmtNumber(stats.by_service.ollama?.total ?? 0)}</div>
        <div className="sub">{fmtNumber(stats.by_service.ollama?.alive ?? 0)} alive</div>
      </div>
      <div className="card stat">
        <div className="label">new (24h / 7d)</div>
        <div className="value">
          {fmtNumber(stats.recent_24h)} <span className="muted" style={{ fontWeight: 400 }}>/ {fmtNumber(stats.recent_7d)}</span>
        </div>
        <div className="sub">
          {stats.last_run
            ? `last scan ${fmtRelative(stats.last_run.started_at)}`
            : 'no scans yet'}
        </div>
      </div>
    </div>
  )
}

export default function InstancesPage() {
  const [items, setItems] = useState<Instance[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)

  const [service, setService] = useState<Service | ''>('')
  const [search, setSearch] = useState('')
  const [model, setModel] = useState('')
  const [providerFilter, setProviderFilter] = useState('')
  const [gpuFilter, setGpuFilter] = useState('')
  const [countryFilter, setCountryFilter] = useState('')
  const [aliveOnly, setAliveOnly] = useState(true)
  const [recent24, setRecent24] = useState(false)
  const [minVram, setMinVram] = useState<string>('')
  const [sortBy, setSortBy] = useState<SortKey>('last_seen_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [autoRefresh, setAutoRefresh] = useState(false)

  const [gpus, setGpus] = useState<Distinct>([])
  const [countries, setCountries] = useState<Distinct>([])

  const debouncedSearch = useDebounce(search, 250)
  const debouncedModel = useDebounce(model, 250)

  const query = useMemo<InstanceQuery>(
    () => ({
      service: service || undefined,
      q: debouncedSearch || undefined,
      model: debouncedModel || undefined,
      provider: providerFilter || undefined,
      gpu: gpuFilter || undefined,
      country: countryFilter || undefined,
      alive: aliveOnly ? true : undefined,
      since_hours: recent24 ? 24 : undefined,
      min_vram: minVram ? Number(minVram) : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      limit: PAGE_SIZE,
    }),
    [service, debouncedSearch, debouncedModel, providerFilter, gpuFilter, countryFilter, aliveOnly, recent24, minVram, sortBy, sortDir],
  )

  const inFlight = useRef(0)
  const load = useCallback(async () => {
    const id = ++inFlight.current
    setLoading(true)
    setErr(null)
    try {
      const [list, st] = await Promise.all([fetchInstances(query), fetchStats()])
      if (id !== inFlight.current) return
      setItems(list)
      setStats(st)
    } catch (e) {
      if (id !== inFlight.current) return
      setErr(String(e))
    } finally {
      if (id === inFlight.current) setLoading(false)
    }
  }, [query])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    fetchDistinct('gpu').then(setGpus).catch(() => {})
    fetchDistinct('country').then(setCountries).catch(() => {})
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(() => load(), 30_000)
    return () => clearInterval(t)
  }, [autoRefresh, load])

  function toggleSort(k: SortKey) {
    if (sortBy === k) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else {
      setSortBy(k)
      setSortDir('desc')
    }
  }

  function arrow(k: SortKey) {
    if (sortBy !== k) return null
    return <span className="arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
  }

  function clearAll() {
    setService('')
    setSearch('')
    setModel('')
    setProviderFilter('')
    setGpuFilter('')
    setCountryFilter('')
    setAliveOnly(true)
    setRecent24(false)
    setMinVram('')
    setSortBy('last_seen_at')
    setSortDir('desc')
  }

  const activeFilterCount =
    (service ? 1 : 0) +
    (debouncedSearch ? 1 : 0) +
    (debouncedModel ? 1 : 0) +
    (providerFilter ? 1 : 0) +
    (gpuFilter ? 1 : 0) +
    (countryFilter ? 1 : 0) +
    (aliveOnly ? 0 : 1) + // showing dead is the non-default
    (recent24 ? 1 : 0) +
    (minVram ? 1 : 0)

  async function onScan() {
    setScanMsg('scheduled…')
    try {
      await triggerShodanScan(adminToken() || undefined)
      setScanMsg('scheduled. results land as the scan finishes.')
      setTimeout(() => setScanMsg(null), 4000)
    } catch (e) {
      setScanMsg(String(e))
    }
  }

  return (
    <div>
      <StatsBar stats={stats} />

      <div className="toolbar">
        <div className="group" role="tablist" aria-label="service">
          <button className={service === '' ? 'active' : ''} onClick={() => setService('')}>
            all
          </button>
          <button className={service === 'comfyui' ? 'active' : ''} onClick={() => setService('comfyui')}>
            comfyui
          </button>
          <button className={service === 'ollama' ? 'active' : ''} onClick={() => setService('ollama')}>
            ollama
          </button>
        </div>

        <input
          className="search"
          placeholder="search ip, gpu, version, host…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <input
          placeholder="model name (e.g. qwen, llama3)"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          style={{ flex: '1 1 180px', minWidth: 160, maxWidth: 240 }}
        />

        <div className="right row">
          {scanMsg && <span className="muted" style={{ fontSize: 12 }}>{scanMsg}</span>}
          {loading && <span className="spinner" />}
          <button onClick={load} title="refresh now">↻</button>
          <button
            className={autoRefresh ? 'primary' : ''}
            onClick={() => setAutoRefresh((v) => !v)}
            title="auto-refresh every 30 seconds"
          >
            auto {autoRefresh ? 'on' : 'off'}
          </button>
          <a
            className="btn plain"
            href={exportCsvUrl(query)}
            target="_blank"
            rel="noreferrer"
            title="download filtered rows as csv"
          >
            ↧ csv
          </a>
          <button onClick={onScan} title="trigger a new shodan scan">
            run scan
          </button>
        </div>
      </div>

      <div className="toolbar" style={{ marginTop: -2 }}>
        <select value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
          <option value="">all providers</option>
          <option value="vps">vps / cloud only</option>
          <option value="residential">residential</option>
          <option value="unknown">unknown</option>
          {Object.entries(PROVIDER_STYLE)
            .filter(([k]) => !['residential', 'unknown'].includes(k))
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
        </select>

        <select value={gpuFilter} onChange={(e) => setGpuFilter(e.target.value)}>
          <option value="">any gpu</option>
          {gpus.map((g) => (
            <option key={g.value} value={g.value}>
              {g.value} ({g.count})
            </option>
          ))}
        </select>

        <select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
          <option value="">any country</option>
          {countries.map((c) => (
            <option key={c.value} value={c.value}>
              {c.value} ({c.count})
            </option>
          ))}
        </select>

        <input
          type="number"
          min={0}
          step={1}
          placeholder="min vram (GB)"
          value={minVram}
          onChange={(e) => setMinVram(e.target.value)}
          style={{ width: 130 }}
        />

        <div className="chips">
          <span className={`chip ${aliveOnly ? 'active' : ''}`} onClick={() => setAliveOnly((v) => !v)}>
            alive only
          </span>
          <span className={`chip ${recent24 ? 'active' : ''}`} onClick={() => setRecent24((v) => !v)}>
            seen ≤ 24h
          </span>
          {activeFilterCount > 0 && (
            <span className="chip" onClick={clearAll} title="clear all filters">
              clear ({activeFilterCount})
            </span>
          )}
        </div>
      </div>

      {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>service</th>
              <th>host</th>
              <th>provider</th>
              <th>country</th>
              <th>state</th>
              <th>version</th>
              <th>gpu</th>
              <th className="sortable" onClick={() => toggleSort('vram_total_gb')}>
                vram {arrow('vram_total_gb')}
              </th>
              <th className="sortable num" onClick={() => toggleSort('model_count')}>
                models {arrow('model_count')}
              </th>
              <th className="sortable num" onClick={() => toggleSort('max_model_params')}>
                max params {arrow('max_model_params')}
              </th>
              <th className="sortable num" onClick={() => toggleSort('max_context')}>
                ctx {arrow('max_context')}
              </th>
              <th className="sortable" onClick={() => toggleSort('last_seen_at')}>
                last seen {arrow('last_seen_at')}
              </th>
              <th>actions</th>
            </tr>
          </thead>
          <tbody>
            {items && items.length === 0 && (
              <tr>
                <td colSpan={13} className="empty">
                  no instances match these filters
                </td>
              </tr>
            )}
            {items?.map((it) => {
              const country = it.shodan?.location?.country_name ?? null
              const url = `http://${it.ip}:${it.port}`
              return (
                <tr key={it.id}>
                  <td>
                    <span className={`badge svc-${it.service}`}>{it.service}</span>
                  </td>
                  <td className="mono">
                    <Link to={`/instances/${it.id}`} className="plain">
                      {it.ip}:{it.port}
                    </Link>
                  </td>
                  <td>
                    <span
                      className="pchip"
                      title={it.reverse_dns ?? undefined}
                      style={{
                        color: providerColor(it.provider),
                        borderColor: 'var(--border)',
                        background: 'var(--tile)',
                      }}
                    >
                      {providerLabel(it.provider)}
                    </span>
                  </td>
                  <td>{country ?? '—'}</td>
                  <td>
                    <span className={`badge ${it.is_alive ? 'alive' : 'dead'}`}>
                      {it.is_alive ? 'alive' : 'down'}
                    </span>
                  </td>
                  <td className="mono">{it.version ?? '—'}</td>
                  <td>{it.gpu_name ?? '—'}</td>
                  <td className="num">{fmtVram(it.vram_total_gb, it.vram_free_gb)}</td>
                  <td className="num">{fmtNumber(it.model_count ?? null)}</td>
                  <td className="num">{fmtParams(it.max_model_params)}</td>
                  <td className="num">{fmtContext(it.max_context)}</td>
                  <td className="muted" title={it.last_seen_at}>{fmtRelative(it.last_seen_at)}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <a className="btn plain icon" href={url} target="_blank" rel="noreferrer" title="open in new tab">
                        ↗
                      </a>
                      <button
                        className="icon"
                        title="copy url"
                        onClick={() => copy(url)}
                      >
                        ⧉
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {!items && (
              <tr>
                <td colSpan={13} className="empty">
                  <span className="spinner" /> loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {items && items.length === PAGE_SIZE && (
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          showing first {PAGE_SIZE}. narrow filters to see more.
        </div>
      )}
    </div>
  )
}
