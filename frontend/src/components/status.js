// The five evidence states. Colour is used for these and nothing else.
export const STATUS = {
  SUPPORTED: { label: 'Supported', short: 'Supported', mark: '✓', color: 'var(--supported)', bg: 'var(--supported-bg)' },
  PARTIALLY_SUPPORTED: { label: 'Partially supported', short: 'Partial', mark: '◐', color: 'var(--partial)', bg: 'var(--partial-bg)' },
  CONTRADICTED: { label: 'Contradicted', short: 'Contradicted', mark: '✕', color: 'var(--contradicted)', bg: 'var(--contradicted-bg)' },
  UNCERTAIN: { label: 'Uncertain', short: 'Uncertain', mark: '!', color: 'var(--uncertain)', bg: 'var(--uncertain-bg)' },
  INSUFFICIENT_EVIDENCE: { label: 'Insufficient evidence', short: 'Insufficient', mark: '?', color: 'var(--insufficient)', bg: 'var(--insufficient-bg)' },
}

export const SEVERITY = {
  HIGH: { color: 'var(--contradicted)', bg: 'var(--contradicted-bg)' },
  MEDIUM: { color: 'var(--uncertain)', bg: 'var(--uncertain-bg)' },
  LOW: { color: 'var(--insufficient)', bg: 'var(--insufficient-bg)' },
}

export function statusMeta(s) {
  return STATUS[s] || STATUS.UNCERTAIN
}

export function formatDate(iso) {
  if (!iso) return 'undated'
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatTime(iso) {
  const d = new Date(iso)
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function location(e) {
  if (e.page) return `p. ${e.page}`
  if (e.line) return `¶ ${e.line}`
  return ''
}
