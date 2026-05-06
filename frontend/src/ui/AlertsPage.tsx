import { useEffect, useState } from 'react'
import { Alert, createAlert, deleteAlert, fetchAlerts, patchAlert } from './api'
import { adminToken, fmtRelative } from './format'

const KINDS: { value: Alert['kind']; label: string; hint: string }[] = [
  { value: 'new_instance', label: 'new instance', hint: 'fires when a brand-new instance is discovered' },
  { value: 'models_added', label: 'models added', hint: 'fires when an existing instance gains a new model' },
  { value: 'alive_changed', label: 'alive flipped', hint: 'fires on alive→down or down→alive transitions' },
]

type FormState = {
  id: number | null
  name: string
  kind: Alert['kind']
  service: '' | 'comfyui' | 'ollama'
  gpu: string
  min_vram: string
  min_max_params: string
  model: string
  country: string
  provider: string
  alive: '' | '1' | '0'
  enabled: boolean
}

const EMPTY: FormState = {
  id: null,
  name: '',
  kind: 'new_instance',
  service: '',
  gpu: '',
  min_vram: '',
  min_max_params: '',
  model: '',
  country: '',
  provider: '',
  alive: '',
  enabled: true,
}

function toFilterJson(f: FormState): Record<string, any> {
  const out: Record<string, any> = {}
  if (f.service) out.service = f.service
  if (f.gpu.trim()) out.gpu = f.gpu.trim()
  if (f.min_vram) out.min_vram = Number(f.min_vram)
  if (f.min_max_params) out.min_max_params = Number(f.min_max_params)
  if (f.model.trim()) out.model = f.model.trim()
  if (f.country.trim()) out.country = f.country.trim()
  if (f.provider) out.provider = f.provider
  if (f.kind === 'alive_changed' && f.alive) out.alive = f.alive === '1'
  return out
}

function fromAlert(a: Alert): FormState {
  const f = a.filter_json || {}
  return {
    id: a.id,
    name: a.name,
    kind: a.kind,
    service: (f.service as FormState['service']) || '',
    gpu: f.gpu ?? '',
    min_vram: f.min_vram?.toString() ?? '',
    min_max_params: f.min_max_params?.toString() ?? '',
    model: f.model ?? '',
    country: f.country ?? '',
    provider: f.provider ?? '',
    alive: f.alive === true ? '1' : f.alive === false ? '0' : '',
    enabled: a.enabled,
  }
}

function filterSummary(a: Alert): string {
  const f = a.filter_json || {}
  const parts: string[] = []
  if (f.service) parts.push(f.service)
  if (f.gpu) parts.push(`gpu~${f.gpu}`)
  if (f.min_vram) parts.push(`vram≥${f.min_vram}GB`)
  if (f.min_max_params) parts.push(`params≥${f.min_max_params}B`)
  if (f.model) parts.push(`model~${f.model}`)
  if (f.country) parts.push(`country=${f.country}`)
  if (f.provider) parts.push(`provider=${f.provider}`)
  if (a.kind === 'alive_changed' && f.alive !== undefined) parts.push(f.alive ? 'on alive' : 'on down')
  return parts.length ? parts.join(' · ') : 'any'
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [saving, setSaving] = useState(false)

  async function load() {
    setErr(null)
    try {
      setAlerts(await fetchAlerts())
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function onSave() {
    setSaving(true)
    setErr(null)
    try {
      const body = {
        name: form.name.trim() || 'untitled',
        kind: form.kind,
        filter_json: toFilterJson(form),
        enabled: form.enabled,
      }
      if (form.id == null) {
        await createAlert(body, adminToken() || undefined)
      } else {
        await patchAlert(form.id, body, adminToken() || undefined)
      }
      setForm(EMPTY)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setSaving(false)
    }
  }

  async function onDelete(id: number) {
    if (!window.confirm('delete this alert?')) return
    try {
      await deleteAlert(id, adminToken() || undefined)
      await load()
    } catch (e) {
      setErr(String(e))
    }
  }

  async function onToggle(a: Alert) {
    try {
      await patchAlert(
        a.id,
        { name: a.name, kind: a.kind, filter_json: a.filter_json, enabled: !a.enabled },
        adminToken() || undefined,
      )
      await load()
    } catch (e) {
      setErr(String(e))
    }
  }

  return (
    <div>
      <div className="section-title">
        <h2>alerts</h2>
        <span className="muted" style={{ fontSize: 12 }}>
          telegram fires when matching events occur during scans/rechecks
        </span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 10 }}>{form.id == null ? 'new alert' : `edit alert #${form.id}`}</h3>
        <div className="row wrap" style={{ gap: 8 }}>
          <input
            placeholder="name (e.g. RTX 5090 in EU)"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            style={{ flex: '2 1 240px' }}
          />
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Alert['kind'] })}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value} title={k.hint}>
                {k.label}
              </option>
            ))}
          </select>
          <select value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value as FormState['service'] })}>
            <option value="">any service</option>
            <option value="comfyui">comfyui</option>
            <option value="ollama">ollama</option>
          </select>
        </div>
        <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
          <input
            placeholder="gpu contains (e.g. 5090)"
            value={form.gpu}
            onChange={(e) => setForm({ ...form, gpu: e.target.value })}
            style={{ flex: '1 1 140px' }}
          />
          <input
            type="number"
            min={0}
            step={1}
            placeholder="min vram (GB)"
            value={form.min_vram}
            onChange={(e) => setForm({ ...form, min_vram: e.target.value })}
            style={{ width: 140 }}
          />
          <input
            type="number"
            min={0}
            step={1}
            placeholder="min max params (B)"
            value={form.min_max_params}
            onChange={(e) => setForm({ ...form, min_max_params: e.target.value })}
            style={{ width: 160 }}
          />
          <input
            placeholder="model contains"
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            style={{ flex: '1 1 140px' }}
          />
          <input
            placeholder="country (exact)"
            value={form.country}
            onChange={(e) => setForm({ ...form, country: e.target.value })}
            style={{ flex: '1 1 140px' }}
          />
          <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
            <option value="">any provider</option>
            <option value="vps">vps / cloud</option>
            <option value="residential">residential</option>
            <option value="unknown">unknown</option>
          </select>
          {form.kind === 'alive_changed' && (
            <select value={form.alive} onChange={(e) => setForm({ ...form, alive: e.target.value as FormState['alive'] })}>
              <option value="">on either flip</option>
              <option value="1">only when going alive</option>
              <option value="0">only when going down</option>
            </select>
          )}
          <label className="row" style={{ gap: 4, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            enabled
          </label>
        </div>
        <div className="row" style={{ marginTop: 10, gap: 8 }}>
          <button className="primary" onClick={onSave} disabled={saving}>
            {saving ? <><span className="spinner" />saving</> : form.id == null ? 'create alert' : 'save changes'}
          </button>
          {form.id != null && (
            <button onClick={() => setForm(EMPTY)}>cancel</button>
          )}
        </div>
      </div>

      {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>id</th>
              <th>enabled</th>
              <th>name</th>
              <th>kind</th>
              <th>filter</th>
              <th className="num">fired</th>
              <th>last fired</th>
              <th>actions</th>
            </tr>
          </thead>
          <tbody>
            {alerts && alerts.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">no alerts yet</td>
              </tr>
            )}
            {alerts?.map((a) => (
              <tr key={a.id}>
                <td className="mono">#{a.id}</td>
                <td>
                  <span
                    className={`badge ${a.enabled ? 'alive' : 'dead'}`}
                    style={{ cursor: 'pointer' }}
                    onClick={() => onToggle(a)}
                    title="click to toggle"
                  >
                    {a.enabled ? 'on' : 'off'}
                  </span>
                </td>
                <td>{a.name}</td>
                <td className="mono">{a.kind}</td>
                <td className="muted" style={{ fontSize: 12 }}>{filterSummary(a)}</td>
                <td className="num">{a.fired_count}</td>
                <td className="muted" title={a.last_fired_at ?? undefined}>
                  {a.last_fired_at ? fmtRelative(a.last_fired_at) : '—'}
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <button className="icon" onClick={() => setForm(fromAlert(a))} title="edit">✎</button>
                    <button className="icon" onClick={() => onDelete(a.id)} title="delete">✕</button>
                  </div>
                </td>
              </tr>
            ))}
            {!alerts && (
              <tr>
                <td colSpan={8} className="empty"><span className="spinner" /> loading…</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
