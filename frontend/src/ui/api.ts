export type Service = 'comfyui' | 'ollama'

export type Instance = {
  id: number
  service: Service
  ip: string
  port: number
  first_seen_at: string
  last_seen_at: string
  last_checked_at: string
  is_alive: boolean
  title?: string | null
  version?: string | null
  gpu_name?: string | null
  vram_total_gb?: number | null
  vram_free_gb?: number | null
  ram_total_gb?: number | null
  ram_free_gb?: number | null
  model_count?: number | null
  max_model_params?: number | null
  max_context?: number | null
  node_count?: number | null
  provider?: string | null
  reverse_dns?: string | null
  shodan?: any
  service_metadata?: any
  models?: any
  last_error?: string | null
}

export type ScanRun = {
  id: number
  source: string
  query?: string | null
  started_at: string
  finished_at?: string | null
  candidates: number
  verified: number
  new_instances: number
  error?: string | null
}

export type Stats = {
  total: number
  alive: number
  by_service: Record<string, { total: number; alive: number }>
  by_provider: Record<string, number>
  recent_24h: number
  recent_7d: number
  last_run: ScanRun | null
}

export type Distinct = { value: string; count: number }[]

export type InstanceQuery = {
  service?: Service
  alive?: boolean
  provider?: string
  q?: string
  model?: string
  gpu?: string
  country?: string
  since_hours?: number
  min_vram?: number
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

function toSearch(p?: InstanceQuery): string {
  const s = new URLSearchParams()
  if (!p) return ''
  Object.entries(p).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    s.set(k, String(v))
  })
  const qs = s.toString()
  return qs ? `?${qs}` : ''
}

export async function fetchInstances(p?: InstanceQuery): Promise<Instance[]> {
  const r = await fetch('/api/instances' + toSearch(p))
  if (!r.ok) throw new Error('failed to load instances')
  return r.json()
}

export async function fetchInstance(id: string): Promise<Instance> {
  const r = await fetch(`/api/instances/${id}`)
  if (!r.ok) throw new Error('failed to load instance')
  return r.json()
}

export async function fetchRuns(): Promise<ScanRun[]> {
  const r = await fetch('/api/scan/runs')
  if (!r.ok) throw new Error('failed to load runs')
  return r.json()
}

export async function fetchStats(): Promise<Stats> {
  const r = await fetch('/api/stats')
  if (!r.ok) throw new Error('failed to load stats')
  return r.json()
}

export async function fetchDistinct(field: string): Promise<Distinct> {
  const r = await fetch(`/api/instances/distinct/${field}`)
  if (!r.ok) throw new Error('failed to load ' + field)
  return r.json()
}

export function exportCsvUrl(p?: InstanceQuery): string {
  return '/api/instances.csv' + toSearch(p)
}

function adminHeaders(adminToken?: string): Record<string, string> {
  return adminToken ? { Authorization: `Bearer ${adminToken}` } : {}
}

export async function refreshInstance(id: number, adminToken?: string): Promise<Instance> {
  const r = await fetch(`/api/instances/${id}/refresh`, {
    method: 'POST',
    headers: adminHeaders(adminToken),
  })
  if (!r.ok) throw new Error(`refresh failed: ${await r.text()}`)
  return r.json()
}

export async function triggerShodanScan(adminToken?: string): Promise<void> {
  const r = await fetch('/api/scan/shodan', {
    method: 'POST',
    headers: adminHeaders(adminToken),
  })
  if (!r.ok) throw new Error(`scan trigger failed: ${await r.text()}`)
}
