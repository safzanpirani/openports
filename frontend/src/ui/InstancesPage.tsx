import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Distinct,
  Instance,
  InstanceQuery,
  Service,
  Stats,
  countInstances,
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
  flagOf,
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

const PAGE_SIZES = [50, 100, 200, 500] as const

function useDebounce<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

type FilterState = {
  service: Service | ''
  q: string
  model: string
  provider: string
  gpu: string
  country: string
  aliveOnly: boolean
  recent24: boolean
  minVram: string
  sortBy: SortKey
  sortDir: 'asc' | 'desc'
  page: number
  pageSize: number
}

const DEFAULT_FILTERS: FilterState = {
  service: '',
  q: '',
  model: '',
  provider: '',
  gpu: '',
  country: '',
  aliveOnly: true,
  recent24: false,
  minVram: '',
  sortBy: 'last_seen_at',
  sortDir: 'desc',
  page: 1,
  pageSize: 200,
}

function readFromParams(params: URLSearchParams): FilterState {
  const sortBy = (params.get('sort') as SortKey) || DEFAULT_FILTERS.sortBy
  const sortDir = (params.get('dir') as 'asc' | 'desc') || DEFAULT_FILTERS.sortDir
  return {
    service: (params.get('service') as Service | '') || '',
    q: params.get('q') ?? '',
    model: params.get('model') ?? '',
    provider: params.get('provider') ?? '',
    gpu: params.get('gpu') ?? '',
    country: params.get('country') ?? '',
    aliveOnly: params.get('alive') !== '0',
    recent24: params.get('recent') === '1',
    minVram: params.get('min_vram') ?? '',
    sortBy,
    sortDir,
    page: Math.max(1, Number(params.get('page') ?? '1') || 1),
    pageSize: Math.max(1, Number(params.get('size') ?? String(DEFAULT_FILTERS.pageSize)) || DEFAULT_FILTERS.pageSize),
  }
}

function writeToParams(state: FilterState): URLSearchParams {
  const p = new URLSearchParams()
  if (state.service) p.set('service', state.service)
  if (state.q) p.set('q', state.q)
  if (state.model) p.set('model', state.model)
  if (state.provider) p.set('provider', state.provider)
  if (state.gpu) p.set('gpu', state.gpu)
  if (state.country) p.set('country', state.country)
  if (!state.aliveOnly) p.set('alive', '0')
  if (state.recent24) p.set('recent', '1')
  if (state.minVram) p.set('min_vram', state.minVram)
  if (state.sortBy !== DEFAULT_FILTERS.sortBy) p.set('sort', state.sortBy)
  if (state.sortDir !== DEFAULT_FILTERS.sortDir) p.set('dir', state.sortDir)
  if (state.page !== 1) p.set('page', String(state.page))
  if (state.pageSize !== DEFAULT_FILTERS.pageSize) p.set('size', String(state.pageSize))
  return p
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
          {stats.last_run ? `last scan ${fmtRelative(stats.last_run.started_at)}` : 'no scans yet'}
        </div>
      </div>
    </div>
  )
}

export default function InstancesPage() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => readFromParams(params), [params])

  function setFilters(patch: Partial<FilterState>, opts?: { resetPage?: boolean }) {
    const next: FilterState = { ...filters, ...patch }
    if (opts?.resetPage !== false) next.page = 1
    setParams(writeToParams(next), { replace: true })
  }

  // local state for inputs we want debounced (so the URL doesn't churn per keystroke)
  const [searchInput, setSearchInput] = useState(filters.q)
  const [modelInput, setModelInput] = useState(filters.model)
  const [minVramInput, setMinVramInput] = useState(filters.minVram)

  // sync local input when external (URL) state changes (e.g. quick-filter, clear)
  useEffect(() => setSearchInput(filters.q), [filters.q])
  useEffect(() => setModelInput(filters.model), [filters.model])
  useEffect(() => setMinVramInput(filters.minVram), [filters.minVram])

  const debSearch = useDebounce(searchInput, 250)
  const debModel = useDebounce(modelInput, 250)
  const debMinVram = useDebounce(minVramInput, 250)

  useEffect(() => {
    if (debSearch !== filters.q) setFilters({ q: debSearch })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debSearch])
  useEffect(() => {
    if (debModel !== filters.model) setFilters({ model: debModel })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debModel])
  useEffect(() => {
    if (debMinVram !== filters.minVram) setFilters({ minVram: debMinVram })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debMinVram])

  const [items, setItems] = useState<Instance[] | null>(null)
  const [filteredCount, setFilteredCount] = useState<number | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [gpus, setGpus] = useState<Distinct>([])
  const [countries, setCountries] = useState<Distinct>([])

  const offset = (filters.page - 1) * filters.pageSize
  const query = useMemo<InstanceQuery>(
    () => ({
      service: filters.service || undefined,
      q: filters.q || undefined,
      model: filters.model || undefined,
      provider: filters.provider || undefined,
      gpu: filters.gpu || undefined,
      country: filters.country || undefined,
      alive: filters.aliveOnly ? true : undefined,
      since_hours: filters.recent24 ? 24 : undefined,
      min_vram: filters.minVram ? Number(filters.minVram) : undefined,
      sort_by: filters.sortBy,
      sort_dir: filters.sortDir,
      limit: filters.pageSize,
      offset,
    }),
    [filters, offset],
  )

  const inFlight = useRef(0)
  const load = useCallback(async () => {
    const id = ++inFlight.current
    setLoading(true)
    setErr(null)
    try {
      const [list, c, st] = await Promise.all([
        fetchInstances(query),
        countInstances(query),
        fetchStats(),
      ])
      if (id !== inFlight.current) return
      setItems(list)
      setFilteredCount(c)
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
    if (filters.sortBy === k) setFilters({ sortDir: filters.sortDir === 'asc' ? 'desc' : 'asc' })
    else setFilters({ sortBy: k, sortDir: 'desc' })
  }

  function arrow(k: SortKey) {
    if (filters.sortBy !== k) return null
    return <span className="arrow">{filters.sortDir === 'desc' ? '↓' : '↑'}</span>
  }

  function clearAll() {
    setSearchInput('')
    setModelInput('')
    setMinVramInput('')
    setParams(new URLSearchParams(), { replace: true })
  }

  const activeFilterCount =
    (filters.service ? 1 : 0) +
    (filters.q ? 1 : 0) +
    (filters.model ? 1 : 0) +
    (filters.provider ? 1 : 0) +
    (filters.gpu ? 1 : 0) +
    (filters.country ? 1 : 0) +
    (filters.aliveOnly ? 0 : 1) +
    (filters.recent24 ? 1 : 0) +
    (filters.minVram ? 1 : 0)

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

  const totalPages = filteredCount ? Math.max(1, Math.ceil(filteredCount / filters.pageSize)) : 1
  const showingFrom = filteredCount === 0 ? 0 : offset + 1
  const showingTo = Math.min(offset + (items?.length ?? 0), filteredCount ?? 0)

  return (
    <div>
      <StatsBar stats={stats} />

      <div className="toolbar">
        <div className="group" role="tablist" aria-label="service">
          <button className={filters.service === '' ? 'active' : ''} onClick={() => setFilters({ service: '' })}>
            all
          </button>
          <button className={filters.service === 'comfyui' ? 'active' : ''} onClick={() => setFilters({ service: 'comfyui' })}>
            comfyui
          </button>
          <button className={filters.service === 'ollama' ? 'active' : ''} onClick={() => setFilters({ service: 'ollama' })}>
            ollama
          </button>
        </div>

        <input
          className="search"
          placeholder="search ip, gpu, version, host…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />

        <input
          placeholder="model name (e.g. qwen, llama3)"
          value={modelInput}
          onChange={(e) => setModelInput(e.target.value)}
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
          <a className="btn plain" href={exportCsvUrl(query)} target="_blank" rel="noreferrer" title="download filtered rows as csv">
            ↧ csv
          </a>
          <button onClick={onScan} title="trigger a new shodan scan">
            run scan
          </button>
        </div>
      </div>

      <div className="toolbar" style={{ marginTop: -2 }}>
        <select value={filters.provider} onChange={(e) => setFilters({ provider: e.target.value })}>
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

        <select value={filters.gpu} onChange={(e) => setFilters({ gpu: e.target.value })}>
          <option value="">any gpu</option>
          {gpus.map((g) => (
            <option key={g.value} value={g.value}>
              {g.value} ({g.count})
            </option>
          ))}
        </select>

        <select value={filters.country} onChange={(e) => setFilters({ country: e.target.value })}>
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
          value={minVramInput}
          onChange={(e) => setMinVramInput(e.target.value)}
          style={{ width: 130 }}
        />

        <div className="chips">
          <span className={`chip ${filters.aliveOnly ? 'active' : ''}`} onClick={() => setFilters({ aliveOnly: !filters.aliveOnly })}>
            alive only
          </span>
          <span className={`chip ${filters.recent24 ? 'active' : ''}`} onClick={() => setFilters({ recent24: !filters.recent24 })}>
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

      <div className="row" style={{ marginBottom: 8, color: 'var(--muted)', fontSize: 12 }}>
        <span>
          {filteredCount === null
            ? 'counting…'
            : filteredCount === 0
            ? 'no matches'
            : `showing ${fmtNumber(showingFrom)}–${fmtNumber(showingTo)} of ${fmtNumber(filteredCount)}`}
        </span>
        <span className="right row" style={{ gap: 4 }}>
          <span>per page</span>
          <select
            value={filters.pageSize}
            onChange={(e) => setFilters({ pageSize: Number(e.target.value), page: 1 })}
            style={{ padding: '2px 6px', fontSize: 12 }}
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </span>
      </div>

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
                    <span
                      className={`badge svc-${it.service}`}
                      onClick={() => setFilters({ service: it.service })}
                      style={{ cursor: 'pointer' }}
                      title="filter by this service"
                    >
                      {it.service}
                    </span>
                  </td>
                  <td className="mono">
                    <Link to={`/instances/${it.id}`} className="plain">
                      {it.ip}:{it.port}
                    </Link>
                  </td>
                  <td>
                    <span
                      className="pchip"
                      title={`${it.reverse_dns ?? ''} — click to filter`.trim()}
                      onClick={() => setFilters({ provider: it.provider || 'unknown' })}
                      style={{
                        color: providerColor(it.provider),
                        borderColor: 'var(--border)',
                        background: 'var(--tile)',
                        cursor: 'pointer',
                      }}
                    >
                      {providerLabel(it.provider)}
                    </span>
                  </td>
                  <td
                    title={country ? 'click to filter' : undefined}
                    onClick={() => country && setFilters({ country })}
                    style={{ cursor: country ? 'pointer' : undefined }}
                  >
                    {country ? (
                      <>
                        <span style={{ marginRight: 4 }}>{flagOf(country)}</span>
                        {country}
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <span className={`badge ${it.is_alive ? 'alive' : 'dead'}`}>
                      {it.is_alive ? 'alive' : 'down'}
                    </span>
                  </td>
                  <td className="mono">{it.version ?? '—'}</td>
                  <td
                    onClick={() => it.gpu_name && setFilters({ gpu: it.gpu_name })}
                    style={{ cursor: it.gpu_name ? 'pointer' : undefined }}
                    title={it.gpu_name ? 'click to filter' : undefined}
                  >
                    {it.gpu_name ?? '—'}
                  </td>
                  <td className="num">{fmtVram(it.vram_total_gb, it.vram_free_gb)}</td>
                  <td className="num">{fmtNumber(it.model_count ?? null)}</td>
                  <td className="num">{fmtParams(it.max_model_params)}</td>
                  <td className="num">{fmtContext(it.max_context)}</td>
                  <td className="muted" title={it.last_seen_at}>
                    {fmtRelative(it.last_seen_at)}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <a className="btn plain icon" href={url} target="_blank" rel="noreferrer" title="open in new tab">
                        ↗
                      </a>
                      <button className="icon" title="copy url" onClick={() => copy(url)}>
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

      {filteredCount !== null && filteredCount > filters.pageSize && (
        <div className="row" style={{ marginTop: 10, gap: 6 }}>
          <button
            disabled={filters.page <= 1}
            onClick={() => setFilters({ page: Math.max(1, filters.page - 1) }, { resetPage: false })}
          >
            ← prev
          </button>
          <span className="muted" style={{ fontSize: 12 }}>
            page {filters.page} / {totalPages}
          </span>
          <button
            disabled={filters.page >= totalPages}
            onClick={() => setFilters({ page: Math.min(totalPages, filters.page + 1) }, { resetPage: false })}
          >
            next →
          </button>
          <span className="right muted" style={{ fontSize: 12 }}>
            url updates with filters — copy address to share
          </span>
        </div>
      )}
    </div>
  )
}
