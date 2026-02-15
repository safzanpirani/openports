import { useEffect, useState } from 'react'
import { fetchRuns, triggerShodanScan, ScanRun } from './api'

function fmt(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString()
  } catch {
    return s
  }
}

export default function RunsPage() {
  const [runs, setRuns] = useState<ScanRun[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [adminToken, setAdminToken] = useState<string>(() => localStorage.getItem('ADMIN_TOKEN') ?? '')

  async function refresh() {
    setRuns(null)
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
    try {
      await triggerShodanScan(adminToken || undefined)
      await refresh()
    } catch (e) {
      setErr(String(e))
    }
  }

  function onSaveToken() {
    localStorage.setItem('ADMIN_TOKEN', adminToken)
  }

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Scan runs</h3>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <button onClick={onTrigger}>Trigger Shodan scan</button>
        <button onClick={refresh}>Refresh</button>
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 12, opacity: 0.8 }}>ADMIN_TOKEN (optional; only needed if backend sets it)</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="password"
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
            style={{ width: 320 }}
          />
          <button onClick={onSaveToken}>Save</button>
        </div>
      </div>

      {err && <div style={{ color: 'crimson', marginBottom: 12 }}>{err}</div>}
      {!runs ? (
        <div>Loading…</div>
      ) : (
        <table cellPadding={8} style={{ borderCollapse: 'collapse', minWidth: 900 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
              <th>ID</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Candidates</th>
              <th>Verified</th>
              <th>New</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <td>{r.id}</td>
                <td>{fmt(r.started_at)}</td>
                <td>{fmt(r.finished_at)}</td>
                <td>{r.candidates}</td>
                <td>{r.verified}</td>
                <td>{r.new_instances}</td>
                <td>{r.error ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
