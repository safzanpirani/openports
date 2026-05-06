import { useEffect, useState } from 'react'
import { ScanRun, fetchRuns, triggerShodanScan } from './api'
import { adminToken, fmtRelative, fmtTime, setAdminToken } from './format'

export default function RunsPage() {
  const [runs, setRuns] = useState<ScanRun[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [token, setToken] = useState<string>(() => adminToken())
  const [scanning, setScanning] = useState(false)

  async function refresh() {
    setErr(null)
    try {
      setRuns(await fetchRuns())
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function onTrigger() {
    setScanning(true)
    setErr(null)
    try {
      await triggerShodanScan(token || undefined)
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

  return (
    <div>
      <div className="section-title">
        <h2>scans</h2>
        <div className="row">
          <button className="primary" onClick={onTrigger} disabled={scanning}>
            {scanning ? <><span className="spinner" />triggering</> : 'trigger shodan scan'}
          </button>
          <button onClick={refresh}>↻ refresh</button>
        </div>
      </div>

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
