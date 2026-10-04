import { useState } from 'react'
import { Meter } from './ui.jsx'

const NAMES = {
  relevance: 'Retrieval relevance',
  corroboration: 'Independent corroboration',
  agreement: 'Agreement between sources',
  completeness: 'Evidence completeness',
  extraction: 'Extraction quality',
}

function colorFor(score) {
  if (score >= 0.8) return 'var(--supported)'
  if (score >= 0.55) return 'var(--uncertain)'
  return 'var(--insufficient)'
}

/** Confidence is a weighted sum of named evidence signals; every number here is explained. */
export function Confidence({ confidence, compact = false }) {
  const [open, setOpen] = useState(false)
  if (!confidence) return null
  const pct = Math.round(confidence.score * 100)
  const color = colorFor(confidence.score)
  return (
    <div className={`confidence ${compact ? 'compact' : ''}`}>
      <div className="confidence-head">
        <span className="eyebrow">Evidence strength</span>
        <span className="confidence-level" style={{ color }}>{confidence.level.toLowerCase()}</span>
      </div>
      <div className="confidence-score">
        <span className="confidence-pct serif" style={{ color }}>{pct}<span className="confidence-sign">%</span></span>
        <div className="confidence-bar">
          <Meter value={confidence.score} color={color} height={8} />
          <p className="confidence-why">{confidence.explanation[0]}</p>
        </div>
      </div>
      {!compact && (
        <>
          <button className="link-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? 'Hide' : 'Show'} how this was calculated
          </button>
          {open && (
            <div className="signals rise">
              {confidence.signals.map((s) => (
                <div className="signal" key={s.name}>
                  <div className="signal-top">
                    <span>{NAMES[s.name] || s.name}</span>
                    <span className="mono faint">
                      {s.value.toFixed(2)} × {s.weight.toFixed(2)}
                    </span>
                  </div>
                  <Meter value={s.value} color="var(--paper-2)" height={4} />
                  <p className="faint signal-text">{s.text}</p>
                </div>
              ))}
              {confidence.explanation.slice(1).map((x) => (
                <p key={x} className="faint signal-text">{x}</p>
              ))}
              <p className="faint signal-text">
                Computed by the evidence engine from these signals. A language model never sets the confidence.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
