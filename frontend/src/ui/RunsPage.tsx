import { useEffect, useState } from 'react'
import { ScanRun, Stats, fetchRuns, fetchStats, triggerMultiScan, triggerShodanScan } from './api'
import { adminToken, fmtEta, fmtRelative, fmtTime, setAdminToken } from './format'

function sourcesLabel(s?: string | string[]): string {
  if (!s) return 'all enabled'
  if (Array.isArray(s)) return s.length ? s.join(', ') : 'all enabled'
  return s === 'all-enabled' ? 'all enabled' : s
}

function intervalLabel(min?: number): string {
  if (!min || min <= 0) return 'off'
  if (min % 60 === 0) return `every ${min / 60}h`
  return `every ${min}m`
}

export default function RunsPage() {
  const [runs, setRuns] = useState<ScanRun[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [token, setToken] = useState<string>(() => adminToken())
  const [scanning, setScanning] = useState(false)

  async function refresh() {
    setErr(null)
    try {
      const [r, s] = await Promise.all([fetchRuns(), fetchStats()])
      setRuns(r)
      setStats(s)
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  // While a scan is in-flight (background task, finished_at still null), poll so
  // the table and next-run countdown stay live without a manual refresh.
  const hasRunning = runs?.some((r) => !r.finished_at) ?? false
  useEffect(() => {
    if (!hasRunning) return
    // Scans can run for many minutes; /api/stats scans the whole table, so keep
    // this gentle. 10s is responsive enough for a background job.
    const id = setInterval(refresh, 10000)
    return () => clearInterval(id)
  }, [hasRunning])

  async function onTrigger(kind: 'multi' | 'shodan') {
    setScanning(true)
    setErr(null)
    try {
      if (kind === 'multi') await triggerMultiScan({}, token || undefined)
      else await triggerShodanScan(token || undefined)
      // The scan runs as a background task; give it a beat to insert its ScanRun
      // row, then refresh (polling takes over while it's still running).
      await new Promise((r) => setTimeout(r, 800))
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setScanning(false)
    }
  }

  function onSaveToken() {
    setAdminToken(token)
  }

  function durationOf(r: ScanRun): string {
    if (!r.finished_at) return '—'
    const ms = new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()
    if (ms < 1000) return `${ms} ms`
    const s = Math.round(ms / 1000)
    if (s < 60) return `${s}s`
    const m = Math.floor(s / 60)
    return `${m}m ${s % 60}s`
  }

  const sched = stats?.scheduler
  const lastRun = stats?.last_run
  const lastRunErr = lastRun?.error
  let healthCls = 'idle'
  let healthLabel = 'idle'
  if (sched?.running) {
    healthCls = 'ok'
    healthLabel = 'running'
  }
  if (lastRunErr) {
    healthCls = 'err'
    healthLabel = 'last run errored'
  }

  return (
    <div>
      <div className="section-title">
        <h2>scans</h2>
        <div className="row">
          <button className="primary" onClick={() => onTrigger('multi')} disabled={scanning}>
            {scanning ? (
              <>
                <span className="spinner" />
                scanning…
              </>
            ) : (
              'scan now'
            )}
          </button>
          <button onClick={() => onTrigger('shodan')} disabled={scanning} title="query Shodan only">
            shodan only
          </button>
          <button onClick={refresh}>↻ refresh</button>
        </div>
      </div>

      {sched && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="stats-grid" style={{ marginBottom: 0 }}>
            <div className="stat">
              <div className="label">scheduler</div>
              <div className="value">
                <span className="health-dot-row">
                  <span className={`health-dot ${healthCls}`} />
                  {healthLabel}
                </span>
              </div>
            </div>
            <div className="stat">
              <div className="label">scan loop</div>
              <div className="value">{intervalLabel(sched.scan_interval_minutes)}</div>
              <div className="sub">
                {sched.scan_interval_minutes > 0
                  ? sched.next_scan_at
                    ? `next ${fmtEta(sched.next_scan_at)}`
                    : '—'
                  : 'set SCAN_INTERVAL_MINUTES to enable'}
              </div>
            </div>
            <div className="stat">
              <div className="label">recheck loop</div>
              <div className="value">{intervalLabel(sched.recheck_interval_minutes)}</div>
              <div className="sub">
                {sched.recheck_interval_minutes > 0
                  ? sched.next_recheck_at
                    ? `next ${fmtEta(sched.next_recheck_at)}`
                    : '—'
                  : 'set RECHECK_INTERVAL_MINUTES to enable'}
              </div>
            </div>
            <div className="stat">
              <div className="label">scan sources</div>
              <div className="value" style={{ fontSize: 15 }}>
                {sourcesLabel(sched.scan_sources)}
              </div>
              <div className="sub">
                {lastRun ? (
                  <>
                    last {lastRunErr ? 'errored' : lastRun.finished_at ? 'ok' : 'running…'} ·{' '}
                    {fmtRelative(lastRun.started_at)}
                  </>
                ) : (
                  'no runs yet'
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
              admin token
            </div>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="only required if backend sets ADMIN_TOKEN"
              style={{ width: '100%', maxWidth: 480 }}
            />
          </div>
          <button onClick={onSaveToken}>save</button>
        </div>
      </div>

      {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

      {!runs ? (
        <div className="muted"><span className="spinner" /> loading…</div>
      ) : runs.length === 0 ? (
        <div className="empty">no scans yet — trigger one above</div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>id</th>
                <th>source</th>
                <th>started</th>
                <th>finished</th>
                <th>duration</th>
                <th className="num">candidates</th>
                <th className="num">verified</th>
                <th className="num">new</th>
                <th>error</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td>{r.source}</td>
                  <td title={r.started_at}>{fmtRelative(r.started_at)}</td>
                  <td title={r.finished_at ?? undefined}>
                    {r.finished_at ? fmtTime(r.finished_at) : <span className="muted">running…</span>}
                  </td>
                  <td className="num">{durationOf(r)}</td>
                  <td className="num">{r.candidates}</td>
                  <td className="num">{r.verified}</td>
                  <td className="num">{r.new_instances}</td>
                  <td className="muted">{r.error ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
