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

export async function fetchInstances(params?: {
  service?: Service
  provider?: string
  alive?: boolean
}): Promise<Instance[]> {
  const search = new URLSearchParams()
  if (params?.service) search.set('service', params.service)
  if (params?.provider) search.set('provider', params.provider)
  if (params?.alive !== undefined) search.set('alive', String(params.alive))
  const qs = search.toString()
  const r = await fetch('/api/instances' + (qs ? `?${qs}` : ''))
  if (!r.ok) throw new Error('Failed to load instances')
  return r.json()
}

export async function fetchInstance(id: string): Promise<Instance> {
  const r = await fetch(`/api/instances/${id}`)
  if (!r.ok) throw new Error('Failed to load instance')
  return r.json()
}

export async function fetchRuns(): Promise<ScanRun[]> {
  const r = await fetch('/api/scan/runs')
  if (!r.ok) throw new Error('Failed to load runs')
  return r.json()
}

export async function triggerShodanScan(adminToken?: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (adminToken) headers['Authorization'] = `Bearer ${adminToken}`

  const r = await fetch('/api/scan/shodan', {
    method: 'POST',
    headers,
  })
  if (!r.ok) {
    const txt = await r.text()
    throw new Error(`Scan trigger failed: ${txt}`)
  }
}
