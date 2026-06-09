export const PROVIDER_STYLE: Record<string, { color: string; label: string }> = {
  aws: { color: 'var(--p-aws)', label: 'AWS' },
  gcp: { color: 'var(--p-gcp)', label: 'GCP' },
  azure: { color: 'var(--p-azure)', label: 'Azure' },
  digitalocean: { color: 'var(--p-do)', label: 'DigitalOcean' },
  vultr: { color: 'var(--p-vultr)', label: 'Vultr' },
  linode: { color: 'var(--p-linode)', label: 'Linode' },
  hetzner: { color: 'var(--p-hetzner)', label: 'Hetzner' },
  ovh: { color: 'var(--p-ovh)', label: 'OVH' },
  oracle_cloud: { color: 'var(--p-oracle)', label: 'Oracle' },
  alibaba_cloud: { color: 'var(--p-alibaba)', label: 'Alibaba' },
  scaleway: { color: 'var(--p-scaleway)', label: 'Scaleway' },
  residential: { color: 'var(--p-residential)', label: 'home isp' },
  unknown: { color: 'var(--p-unknown)', label: 'unknown' },
}

export function providerLabel(p: string | null | undefined): string {
  if (!p) return 'unknown'
  return PROVIDER_STYLE[p]?.label ?? p
}

export function providerColor(p: string | null | undefined): string {
  if (!p) return 'var(--p-unknown)'
  return PROVIDER_STYLE[p]?.color ?? 'var(--p-unknown)'
}

export function fmtTime(s?: string | null): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString()
  } catch {
    return s
  }
}

export function fmtRelative(s?: string | null): string {
  if (!s) return '—'
  try {
    const d = new Date(s).getTime()
    const now = Date.now()
    const diffMs = now - d
    if (diffMs < 0) return new Date(s).toLocaleString()
    const sec = Math.round(diffMs / 1000)
    if (sec < 60) return `${sec}s ago`
    const min = Math.round(sec / 60)
    if (min < 60) return `${min}m ago`
    const hr = Math.round(min / 60)
    if (hr < 48) return `${hr}h ago`
    const day = Math.round(hr / 24)
    if (day < 30) return `${day}d ago`
    return new Date(s).toLocaleDateString()
  } catch {
    return s
  }
}

export function fmtEta(s?: string | null): string {
  if (!s) return '—'
  try {
    const diffMs = new Date(s).getTime() - Date.now()
    if (diffMs <= 0) return 'due'
    const sec = Math.round(diffMs / 1000)
    if (sec < 60) return `in ${sec}s`
    const min = Math.round(sec / 60)
    if (min < 60) return `in ${min}m`
    const hr = Math.round(min / 60)
    if (hr < 48) return `in ${hr}h`
    return `in ${Math.round(hr / 24)}d`
  } catch {
    return s
  }
}

export function fmtNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtVram(total?: number | null, free?: number | null): string {
  if (total === null || total === undefined) return '—'
  if (free !== null && free !== undefined) return `${free.toFixed(1)} / ${total.toFixed(1)} GB`
  return `${total.toFixed(1)} GB`
}

export function fmtParams(b?: number | null): string {
  if (b === null || b === undefined) return '—'
  if (b >= 1) return `${b.toFixed(b >= 10 ? 0 : 1)}B`
  return `${(b * 1000).toFixed(0)}M`
}

export function fmtContext(c?: number | null): string {
  if (c === null || c === undefined) return '—'
  if (c >= 1000) return `${Math.round(c / 1000)}k`
  return String(c)
}

export function adminToken(): string {
  return localStorage.getItem('ADMIN_TOKEN') ?? ''
}

export function setAdminToken(t: string): void {
  if (t) localStorage.setItem('ADMIN_TOKEN', t)
  else localStorage.removeItem('ADMIN_TOKEN')
}

// Map common Shodan country names to ISO-2 → emoji flag.
const COUNTRY_TO_ISO2: Record<string, string> = {
  'United States': 'US',
  'United Kingdom': 'GB',
  Germany: 'DE',
  France: 'FR',
  Netherlands: 'NL',
  Singapore: 'SG',
  Japan: 'JP',
  China: 'CN',
  Korea: 'KR',
  'South Korea': 'KR',
  India: 'IN',
  Canada: 'CA',
  Australia: 'AU',
  Brazil: 'BR',
  Russia: 'RU',
  Italy: 'IT',
  Spain: 'ES',
  Sweden: 'SE',
  Switzerland: 'CH',
  Poland: 'PL',
  Ireland: 'IE',
  Belgium: 'BE',
  Austria: 'AT',
  Norway: 'NO',
  Finland: 'FI',
  Denmark: 'DK',
  Greece: 'GR',
  Portugal: 'PT',
  'Czech Republic': 'CZ',
  Czechia: 'CZ',
  'Hong Kong': 'HK',
  Taiwan: 'TW',
  Indonesia: 'ID',
  Vietnam: 'VN',
  Thailand: 'TH',
  'United Arab Emirates': 'AE',
  Israel: 'IL',
  'South Africa': 'ZA',
  Mexico: 'MX',
  Argentina: 'AR',
  Chile: 'CL',
  Turkey: 'TR',
  Ukraine: 'UA',
  Romania: 'RO',
  Hungary: 'HU',
  Bulgaria: 'BG',
  'New Zealand': 'NZ',
  Malaysia: 'MY',
  Philippines: 'PH',
}

export function flagOf(countryName?: string | null): string {
  if (!countryName) return ''
  const iso = COUNTRY_TO_ISO2[countryName]
  if (!iso || iso.length !== 2) return ''
  const A = 0x1f1e6
  const a = 'A'.charCodeAt(0)
  return String.fromCodePoint(A + (iso.charCodeAt(0) - a)) + String.fromCodePoint(A + (iso.charCodeAt(1) - a))
}

export function copy(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'absolute'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      resolve()
    } catch (e) {
      reject(e)
    }
  })
}
