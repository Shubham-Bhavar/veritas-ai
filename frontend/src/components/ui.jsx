import { statusMeta, SEVERITY } from './status.js'

export function Logo({ size = 22, withWord = true }) {
  return (
    <span className="logo" style={{ '--logo': `${size}px` }}>
      <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
        <rect x="1" y="1" width="30" height="30" rx="7" fill="none" stroke="var(--line-strong)" />
        <path d="M8.5 9 16 23 23.5 9" fill="none" stroke="var(--paper)" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="16" cy="23" r="2.5" fill="var(--supported)" />
      </svg>
      {withWord && (
        <span className="logo-word">
          VERITAS<span className="logo-ai">AI</span>
        </span>
      )}
    </span>
  )
}

export function StatusPill({ status, size = 'md', label }) {
  const m = statusMeta(status)
  return (
    <span className={`status-pill status-${size}`} style={{ color: m.color, background: m.bg, borderColor: m.color }}>
      <span className="status-mark" aria-hidden="true">{m.mark}</span>
      {label || m.label}
    </span>
  )
}

export function SeverityTag({ severity }) {
  const s = SEVERITY[severity] || SEVERITY.LOW
  return (
    <span className="severity" style={{ color: s.color, background: s.bg }}>
      {severity}
    </span>
  )
}

export function Meter({ value, color = 'var(--paper)', height = 6 }) {
  return (
    <span className="meter" style={{ height }}>
      <span className="meter-fill" style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`, background: color }} />
    </span>
  )
}

export function Empty({ title, children, action }) {
  return (
    <div className="empty">
      <div className="empty-mark" aria-hidden="true">
        <svg viewBox="0 0 48 48" width="40" height="40">
          <rect x="9" y="6" width="24" height="31" rx="3" fill="none" stroke="var(--line-strong)" />
          <rect x="15" y="11" width="24" height="31" rx="3" fill="var(--ink-1)" stroke="var(--paper-4)" />
          <path d="M20 21h13M20 26h13M20 31h8" stroke="var(--paper-4)" strokeLinecap="round" />
        </svg>
      </div>
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  )
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="error-note" role="alert">
      <span>{error.message || String(error)}</span>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

const ICONS = {
  investigate: 'M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13Zm4.6-1.9L20 20',
  documents: 'M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V4a.5.5 0 0 1 .5-.5ZM14 3.5V8h4',
  conflicts: 'M4 7h9m-3-3 3 3-3 3M20 17h-9m3-3-3 3 3 3',
  graph: 'M6 6.5a2 2 0 1 0 0-.01M18 6.5a2 2 0 1 0 0-.01M12 18a2 2 0 1 0 0-.01M7.5 7.8l3.4 8.4M16.5 7.8l-3.4 8.4M8 6.5h8',
  compare: 'M4.5 4.5h6v15h-6zM13.5 4.5h6v15h-6zM7.5 9h0M16.5 9h0',
  security: 'M12 3.5 19 6v5.5c0 4.3-2.9 7.6-7 9-4.1-1.4-7-4.7-7-9V6l7-2.5Zm-2.5 8.5 2 2 3.5-4',
  timeline: 'M12 7v5l3 2M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z',
  judge: 'M5 20h14M8 20V9.5M16 20V9.5M4 9.5h16L12 4 4 9.5Z',
  upload: 'M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4.5 15v4.5h15V15',
  close: 'M6 6l12 12M18 6 6 18',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  back: 'M19 12H5m5 5-5-5 5-5',
  page: 'M7 3.5h10a.5.5 0 0 1 .5.5v16a.5.5 0 0 1-.5.5H7a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5ZM9.5 8h5M9.5 11.5h5M9.5 15h3',
  retry: 'M4.5 12a7.5 7.5 0 0 1 13-5.1L19.5 9M19.5 4.5V9H15M19.5 12a7.5 7.5 0 0 1-13 5.1L4.5 15M4.5 19.5V15H9',
  trash: 'M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13',
  plus: 'M12 5v14M5 12h14',
  spark: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6',
  logout: 'M15 4.5h3.5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H15M10 16l4-4-4-4M14 12H4',
}

export function Icon({ name, size = 18 }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="icon">
      <path d={ICONS[name]} />
    </svg>
  )
}
