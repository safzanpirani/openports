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
  triggerMultiScan,
  triggerRecheck,
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

function useLocalStorage<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(v))
    } catch {}
  }, [key, v])
  return [v, setV]
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
  staleOnly: boolean
  starredOnly: boolean
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
  staleOnly: false,
  starredOnly: false,
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
    staleOnly: params.get('stale') === '1',
    starredOnly: params.get('starred') === '1',
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
  if (state.staleOnly) p.set('stale', '1')
  if (state.starredOnly) p.set('starred', '1')
  if (state.minVram) p.set('min_vram', state.minVram)
  if (state.sortBy !== DEFAULT_FILTERS.sortBy) p.set('sort', state.sortBy)
  if (state.sortDir !== DEFAULT_FILTERS.sortDir) p.set('dir', state.sortDir)
  if (state.page !== 1) p.set('page', String(state.page))
  if (state.pageSize !== DEFAULT_FILTERS.pageSize) p.set('size', String(state.pageSize))
  return p
}

type Saved = { name: string; search: string }

function StatsBar({ stats, onServiceClick }: { stats: Stats | null; onServiceClick: (svc: Service | '') => void }) {
  if (!stats) return null
  const sched = stats.scheduler
  const schedLine =
    sched && (sched.scan_interval_minutes > 0 || sched.recheck_interval_minutes > 0)
      ? `cron: scan/${sched.scan_interval_minutes || '–'}m · recheck/${sched.recheck_interval_minutes || '–'}m`
      : 'cron: off'

  const services = Object.entries(stats.by_service)
    .filter(([, v]) => v.total > 0)
    .sort((a, b) => b[1].total - a[1].total)

  return (
    <div className="stats-grid">
      <div className="card stat">
        <div className="label">total</div>
        <div className="value">{fmtNumber(stats.total)}</div>
        <div className="sub">{fmtNumber(stats.alive)} alive</div>
      </div>
      <div className="card stat" style={{ minWidth: 220 }} title="click a service to filter">
        <div className="label">by service</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
          {services.length === 0 && <span className="muted">none yet</span>}
          {services.map(([svc, v]) => (
            <span
              key={svc}
              className={`badge svc-${svc}`}
              onClick={() => onServiceClick(svc as Service)}
              style={{ cursor: 'pointer' }}
              title={`${v.alive} alive of ${v.total}`}
            >
              {svc} {v.total}
            </span>
          ))}
        </div>
      </div>
      <div className="card stat">
        <div className="label">new (24h / 7d)</div>
        <div className="value">
          {fmtNumber(stats.recent_24h)} <span className="muted" style={{ fontWeight: 400 }}>/ {fmtNumber(stats.recent_7d)}</span>
        </div>
        <div className="sub">
          {stats.last_run ? `last scan ${fmtRelative(stats.last_run.started_at)}` : 'no scans yet'} · {schedLine}
        </div>
      </div>
      <div className="card stat" title="instances whose last_checked_at is older than 24h">
        <div className="label">stale &gt; 24h</div>
        <div className="value">{fmtNumber(stats.stale_24h ?? 0)}</div>
        <div className="sub muted">re-check from below</div>
      </div>
    </div>
  )
}

function ShortcutHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="shortcut-help" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <h3>keyboard shortcuts</h3>
        <dl>
          <dt><span className="kbd">/</span></dt>
          <dd>focus search</dd>
          <dt><span className="kbd">m</span></dt>
          <dd>focus model search</dd>
          <dt><span className="kbd">r</span></dt>
          <dd>reload</dd>
          <dt><span className="kbd">Esc</span></dt>
          <dd>clear search · close help</dd>
          <dt><span className="kbd">a</span></dt>
          <dd>toggle alive-only</dd>
          <dt><span className="kbd">c</span></dt>
          <dd>toggle compact rows</dd>
          <dt><span className="kbd">?</span></dt>
          <dd>show this help</dd>
        </dl>
        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <button onClick={onClose}>close</button>
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

  const [searchInput, setSearchInput] = useState(filters.q)
  const [modelInput, setModelInput] = useState(filters.model)
  const [minVramInput, setMinVramInput] = useState(filters.minVram)
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
  const [helpOpen, setHelpOpen] = useState(false)

  const [starred, setStarred] = useLocalStorage<number[]>('openports.starred', [])
  const starredSet = useMemo(() => new Set(starred), [starred])
  function toggleStar(id: number) {
    setStarred((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const [compact, setCompact] = useLocalStorage<boolean>('openports.compact', false)
  const [saved, setSaved] = useLocalStorage<Saved[]>('openports.saved', [])
  function saveCurrent() {
    const name = window.prompt('name this view', 'untitled')
    if (!name) return
    const search = '?' + writeToParams(filters).toString()
    setSaved((prev) => [...prev.filter((s) => s.name !== name), { name, search }])
  }
  function loadSaved(s: Saved) {
    setParams(new URLSearchParams(s.search.replace(/^\?/, '')), { replace: true })
  }
  function deleteSaved(name: string) {
    setSaved((prev) => prev.filter((s) => s.name !== name))
  }

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
      stale_hours: filters.staleOnly ? 24 : undefined,
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

  // keyboard shortcuts
  const searchRef = useRef<HTMLInputElement | null>(null)
  const modelRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    function isTypingTarget(t: EventTarget | null) {
      const el = t as HTMLElement | null
      if (!el) return false
      const tag = el.tagName
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
    }
    function onKey(e: KeyboardEvent) {
      if (helpOpen && e.key === 'Escape') {
        setHelpOpen(false)
        return
      }
      if (isTypingTarget(e.target)) {
        if (e.key === 'Escape' && (e.target as HTMLElement).tagName === 'INPUT') {
          ;(e.target as HTMLInputElement).blur()
        }
        return
      }
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (e.key === 'm') {
        e.preventDefault()
        modelRef.current?.focus()
      } else if (e.key === 'r') {
        e.preventDefault()
        load()
      } else if (e.key === 'a') {
        e.preventDefault()
        setFilters({ aliveOnly: !filters.aliveOnly })
      } else if (e.key === 'c') {
        e.preventDefault()
        setCompact((v) => !v)
      } else if (e.key === '?') {
        e.preventDefault()
        setHelpOpen(true)
      } else if (e.key === 'Escape') {
        if (filters.q || filters.model) {
          setSearchInput('')
          setModelInput('')
          setFilters({ q: '', model: '' })
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, helpOpen, load])

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
    (filters.staleOnly ? 1 : 0) +
    (filters.starredOnly ? 1 : 0) +
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

  async function onMultiScan() {
    setScanMsg('multi-source scan scheduled…')
    try {
      await triggerMultiScan({}, adminToken() || undefined)
      setScanMsg('multi-source scan scheduled.')
      setTimeout(() => setScanMsg(null), 4000)
    } catch (e) {
      setScanMsg(String(e))
    }
  }

  async function onRecheck() {
    setScanMsg('rechecking stored instances…')
    try {
      await triggerRecheck({ only_stale: true }, adminToken() || undefined)
      setScanMsg('recheck scheduled.')
      setTimeout(() => setScanMsg(null), 4000)
    } catch (e) {
      setScanMsg(String(e))
    }
  }

  // client-side starred filter
  const visibleItems = useMemo(() => {
    if (!items) return null
    if (filters.starredOnly) return items.filter((it) => starredSet.has(it.id))
    return items
  }, [items, filters.starredOnly, starredSet])

  const totalPages = filteredCount ? Math.max(1, Math.ceil(filteredCount / filters.pageSize)) : 1
  const showingFrom = filteredCount === 0 ? 0 : offset + 1
  const showingTo = Math.min(offset + (visibleItems?.length ?? 0), filteredCount ?? 0)

  return (
    <div>
      <StatsBar stats={stats} onServiceClick={(s) => setFilters({ service: s })} />

      <div className="toolbar">
        <select
          value={filters.service}
          onChange={(e) => setFilters({ service: e.target.value as Service | '' })}
          title="service filter"
        >
          <option value="">all services</option>
          {([
            'comfyui', 'ollama', 'sdwebui', 'openwebui', 'jupyter',
            'vllm', 'tgi', 'ray', 'triton', 'tgwebui', 'lmstudio',
            'sglang', 'llamacpp', 'litellm', 'tensorboard',
          ] as Service[]).map((svc) => {
            const c = stats?.by_service[svc]
            return (
              <option key={svc} value={svc}>
                {svc}{c ? ` (${c.total})` : ''}
              </option>
            )
          })}
        </select>

        <input
          ref={searchRef}
          className="search"
          placeholder="search ip, gpu, version, host… [/]"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />

        <input
          ref={modelRef}
          placeholder="model name [m]"
          value={modelInput}
          onChange={(e) => setModelInput(e.target.value)}
          style={{ flex: '1 1 180px', minWidth: 140, maxWidth: 220 }}
        />

        <div className="right row">
          {scanMsg && <span className="muted" style={{ fontSize: 12 }}>{scanMsg}</span>}
          {loading && <span className="spinner" />}
          <button onClick={load} title="refresh now [r]">↻</button>
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
          <button onClick={onRecheck} title="re-fingerprint stored instances (skips fresh ones)">
            recheck
          </button>
          <button onClick={onScan} title="shodan only">
            shodan
          </button>
          <button onClick={onMultiScan} title="every configured source (shodan, censys, zoomeye)">
            multi-scan
          </button>
          <button className="ghost icon" title="keyboard shortcuts [?]" onClick={() => setHelpOpen(true)}>
            ?
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
          <span className={`chip ${filters.aliveOnly ? 'active' : ''}`} onClick={() => setFilters({ aliveOnly: !filters.aliveOnly })} title="[a]">
            alive only
          </span>
          <span className={`chip ${filters.recent24 ? 'active' : ''}`} onClick={() => setFilters({ recent24: !filters.recent24 })}>
            seen ≤ 24h
          </span>
          <span className={`chip ${filters.staleOnly ? 'active' : ''}`} onClick={() => setFilters({ staleOnly: !filters.staleOnly })}>
            stale &gt; 24h
          </span>
          <span className={`chip ${filters.starredOnly ? 'active' : ''}`} onClick={() => setFilters({ starredOnly: !filters.starredOnly })}>
            ★ starred ({starred.length})
          </span>
          {activeFilterCount > 0 && (
            <span className="chip" onClick={clearAll} title="clear all filters">
              clear ({activeFilterCount})
            </span>
          )}
        </div>

        <div className="right row" style={{ gap: 6 }}>
          <button onClick={() => setCompact((v) => !v)} title="density [c]">
            {compact ? 'compact ✓' : 'compact'}
          </button>
          <button onClick={saveCurrent} title="save current filters as a named view">
            save view
          </button>
        </div>
      </div>

      {saved.length > 0 && (
        <div className="chips" style={{ marginBottom: 12 }}>
          <span className="muted" style={{ fontSize: 11, alignSelf: 'center', marginRight: 4 }}>
            saved:
          </span>
          {saved.map((s) => (
            <span
              key={s.name}
              className="chip"
              onClick={() => loadSaved(s)}
              title={`load: ${s.search}`}
            >
              {s.name}
              <span
                className="x"
                title="delete"
                onClick={(e) => {
                  e.stopPropagation()
                  deleteSaved(s.name)
                }}
              >
                ×
              </span>
            </span>
          ))}
        </div>
      )}

      {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="row" style={{ marginBottom: 8, color: 'var(--muted)', fontSize: 12 }}>
        <span>
          {filteredCount === null
            ? 'counting…'
            : filteredCount === 0
            ? 'no matches'
            : filters.starredOnly
            ? `showing ${fmtNumber(visibleItems?.length ?? 0)} starred`
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
        <table className={`data ${compact ? 'compact' : ''}`}>
          <thead>
            <tr>
              <th>★</th>
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
            {visibleItems && visibleItems.length === 0 && (
              <tr>
                <td colSpan={14} className="empty">
                  no instances match these filters
                </td>
              </tr>
            )}
            {visibleItems?.map((it) => {
              const country = it.shodan?.location?.country_name ?? null
              const url = `http://${it.ip}:${it.port}`
              const on = starredSet.has(it.id)
              return (
                <tr key={it.id}>
                  <td>
                    <button
                      className={`star ${on ? 'on' : ''}`}
                      onClick={() => toggleStar(it.id)}
                      title={on ? 'unstar' : 'star (saved locally)'}
                    >
                      {on ? '★' : '☆'}
                    </button>
                  </td>
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
                    {it.discovery_sources && it.discovery_sources.length > 0 && (
                      <div style={{ marginTop: 2 }}>
                        {it.discovery_sources.map((s) => (
                          <span key={s} className="badge" style={{ fontSize: 10, marginRight: 3 }} title={`source: ${s}`}>
                            {s}
                          </span>
                        ))}
                      </div>
                    )}
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
                <td colSpan={14} className="empty">
                  <span className="spinner" /> loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {!filters.starredOnly && filteredCount !== null && filteredCount > filters.pageSize && (
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
            url updates with filters — copy address to share · press <span className="kbd">?</span> for shortcuts
          </span>
        </div>
      )}

      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
    </div>
  )
}
