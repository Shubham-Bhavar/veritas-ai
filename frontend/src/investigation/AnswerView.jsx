import { useState } from 'react'
import { Confidence } from '../components/Confidence.jsx'
import { Icon, Meter, SeverityTag, StatusPill } from '../components/ui.jsx'
import { location, statusMeta } from '../components/status.js'
import { useInvestigation } from './context.js'

export function evidenceSource(e) {
  return {
    kind: 'evidence', evidenceId: e.id, documentId: e.document_id, chunkId: e.chunk_id, page: e.page, line: e.line,
    filename: e.filename, section: e.section, quote: e.quote, why: e.why, stance: e.stance, relevance: e.relevance,
    quality: e.quality, ocr: e.ocr, flagged: e.flagged, docKind: e.kind, docDate: e.doc_date, title: e.title,
  }
}

export function EvidenceChip({ e }) {
  const { openSource } = useInvestigation()
  if (!e) return null
  const color = e.stance === 'contradicts' ? 'var(--contradicted)' : e.stance === 'context' ? 'var(--paper-3)' : 'var(--supported)'
  return (
    <button className="ev-chip" onClick={() => openSource(evidenceSource(e))} title={e.quote}>
      <span className="ev-id mono" style={{ color }}>{e.id}</span>
      <span className="ev-file">{e.filename}</span>
      {location(e) && <span className="mono faint">{location(e)}</span>}
      {e.ocr && <span className="ev-tag">OCR</span>}
    </button>
  )
}

function Claim({ claim, evidence, conflicts }) {
  const [open, setOpen] = useState(false)
  const { goTab } = useInvestigation()
  const m = statusMeta(claim.status)
  return (
    <li className="claim" style={{ '--claim': m.color }}>
      <span className="claim-mark" style={{ color: m.color, background: m.bg }} aria-label={m.label}>{m.mark}</span>
      <div className="claim-body">
        <div className="claim-top">
          <p className="claim-text">{claim.text}</p>
          <span className="claim-status" style={{ color: m.color }}>{m.short}</span>
        </div>
        <div className="claim-evidence">
          {claim.evidence.map((eid) => <EvidenceChip key={eid} e={evidence[eid]} />)}
          {claim.evidence.length === 0 && <span className="faint">No evidence in the documents</span>}
        </div>
        <div className="claim-foot">
          <button className="link-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? 'Hide reasoning' : 'Why?'}
          </button>
          {claim.conflict_ids.map((cid) => (
            <button key={cid} className="conflict-link" onClick={() => goTab('conflicts')}>
              ⇄ depends on conflict #{conflicts[cid]?.number ?? '?'}
            </button>
          ))}
          <span className="claim-source mono faint">{claim.source === 'llm' ? 'AI claim · verified' : 'engine'} · {claim.id}</span>
        </div>
        {open && <p className="claim-reason rise">{claim.reasoning}</p>}
      </div>
    </li>
  )
}

const CAUTION = { SUPPORTED: 0, PARTIALLY_SUPPORTED: 1, CONTRADICTED: 2, UNCERTAIN: 2, INSUFFICIENT_EVIDENCE: 3 }

/** One-glance brief built only from the answer's own data: asked, found, evidence, conflict, uncertainty, why. */
function Brief({ answer, evidence }) {
  const v = answer.verdict
  const used = answer.evidence.filter((e) => e.stance !== 'context')
  const docs = new Set(used.map((e) => e.document_id))
  const decidingIds = new Set(answer.claims.flatMap((c) => c.conflict_ids))
  const material = answer.conflicts.filter((c) => decidingIds.has(c.id))
  const present = answer.conflicts.filter((c) => c.status === 'UNRESOLVED' && !decidingIds.has(c.id))
  const resolved = answer.conflicts.filter((c) => c.status === 'RESOLVED').length
  // The claim that decides the verdict: the most cautious one, preferring an exact status match.
  const decisive = [...answer.claims].sort((a, b) =>
    (b.status === v.status) - (a.status === v.status) || CAUTION[b.status] - CAUTION[a.status])[0]
  const top = used.slice(0, 3)
  return (
    <section className="brief panel" aria-label="Answer brief">
      <div className="brief-row"><dt>Asked</dt><dd>“{answer.question}”</dd></div>
      <div className="brief-row"><dt>Found</dt><dd><strong>{v.headline}</strong>{v.summary ? ` — ${v.summary}` : ''}</dd></div>
      <div className="brief-row">
        <dt>Evidence</dt>
        <dd>
          {used.length ? `${used.length} passage${used.length > 1 ? 's' : ''} from ${docs.size} document${docs.size > 1 ? 's' : ''}` : 'No passage answers the question'}
          {top.length > 0 && <span className="brief-chips">{top.map((e) => <EvidenceChip key={e.id} e={evidence[e.id]} />)}</span>}
        </dd>
      </div>
      <div className="brief-row">
        <dt>Conflict</dt>
        <dd>
          {material.length > 0
            ? <span className="warn-text">Decides the outcome: {material.map((c) => c.summary).join(' · ')}</span>
            : <span>None changes this outcome.</span>}
          {present.length > 0 && (
            <span className="faint"> Present but not decisive: {present.map((c) => c.summary).join(' · ')}.</span>
          )}
          {resolved > 0 && <span className="faint"> {resolved} resolved by explicit supersession or amendment.</span>}
        </dd>
      </div>
      <div className="brief-row">
        <dt>Uncertain</dt>
        <dd>{answer.missing.length ? answer.missing.join(' · ') : 'Nothing the answer depends on is missing'}</dd>
      </div>
      {decisive && (
        <div className="brief-row"><dt>Why</dt><dd>{decisive.reasoning || decisive.text}</dd></div>
      )}
    </section>
  )
}

export default function AnswerView({ answer }) {
  const { goTab, openSource } = useInvestigation()
  const evidence = Object.fromEntries(answer.evidence.map((e) => [e.id, e]))
  const conflicts = Object.fromEntries(answer.conflicts.map((c) => [c.id, c]))
  const v = answer.verdict
  const m = statusMeta(v.status)
  const engineLabel = answer.engine === 'llm-verified' ? 'Claude synthesis · verified' : 'Extractive evidence engine'

  return (
    <article className="answer rise">
      <section className="verdict-card panel" style={{ '--verdict': m.color }}>
        <div className="verdict-main">
          <div className="verdict-meta">
            <span className="eyebrow">Verdict</span>
            <span className="chip">{engineLabel}</span>
            {answer.latency_ms != null && <span className="mono faint">{(answer.latency_ms / 1000).toFixed(1)} s</span>}
          </div>
          <h2 className="verdict-headline serif">{v.headline}</h2>
          <div className="verdict-sub">
            <StatusPill status={v.status} />
            {answer.subject && <span className="chip">Subject · {answer.subject.name} · {answer.subject.document_ids.length} records</span>}
          </div>
          {v.summary && <p className="verdict-summary">{v.summary}</p>}
          <p className="verdict-question faint">“{answer.question}”</p>
        </div>
        <div className="verdict-side">
          <Confidence confidence={answer.confidence} />
        </div>
      </section>

      <Brief answer={answer} evidence={evidence} />

      {answer.notes?.length > 0 && (
        <div className="notes">{answer.notes.map((n) => <p key={n}>{n}</p>)}</div>
      )}

      {answer.security?.length > 0 && (
        <section className="security-strip">
          <div className="security-strip-head">
            <Icon name="security" size={18} />
            <strong>Prompt-injection attempt neutralised</strong>
          </div>
          {answer.security.map((s, i) => (
            <div key={i} className="security-strip-item">
              <p className="mono">“{s.text.length > 220 ? `${s.text.slice(0, 220)}…` : s.text}”</p>
              <p className="faint">
                {s.kind === 'hidden_text' ? 'Invisible text' : 'Instruction-like text'} in {s.filename}
                {s.page ? `, page ${s.page}` : ''}. {s.action}
              </p>
              {s.page && (
                <button className="link-btn" onClick={() => openSource({ kind: 'security', documentId: s.document_id, page: s.page, filename: s.filename, flags: true, quote: s.text })}>
                  Show where it hides on the page
                </button>
              )}
            </div>
          ))}
        </section>
      )}

      <section className="claims-section">
        <div className="section-title">
          <h3 className="eyebrow">Claims · evidence · sources</h3>
          <span className="faint">{answer.claims.length} claims from {answer.evidence.length} evidence items</span>
        </div>
        <ul className="claims">
          {answer.claims.map((c) => <Claim key={c.id} claim={c} evidence={evidence} conflicts={conflicts} />)}
        </ul>
      </section>

      <div className="answer-grid">
        <section className="card">
          <h3 className="eyebrow">Conflicts in play</h3>
          {answer.conflicts.length === 0 && <p className="faint">No document disagrees with the evidence used here.</p>}
          {answer.conflicts.map((c) => (
            <button key={c.id} className="mini-conflict" onClick={() => goTab('conflicts')}>
              <span className="mini-conflict-top">
                <span className="mono">#{String(c.number).padStart(2, '0')}</span>
                <SeverityTag severity={c.severity} />
                <span className={`resolution ${c.status === 'RESOLVED' ? 'ok' : 'open'}`}>{c.status === 'RESOLVED' ? 'Resolved by evidence' : 'Unresolved'}</span>
              </span>
              <span className="mini-conflict-summary">{c.summary}</span>
            </button>
          ))}
        </section>
        <section className="card">
          <h3 className="eyebrow">Uncertainty</h3>
          {answer.missing.length > 0 ? (
            <ul className="missing">{answer.missing.map((x) => <li key={x}>Missing: {x}</li>)}</ul>
          ) : (
            <p className="faint">Nothing the question depends on is missing from the evidence.</p>
          )}
          <h3 className="eyebrow" style={{ marginTop: 16 }}>Recommendation</h3>
          <p>{answer.recommendation}</p>
        </section>
      </div>

      {answer.review?.length > 0 && (
        <section className="card review">
          <h3 className="eyebrow">Conditions for human review</h3>
          <p className="faint">Stated in words, not numbers, so the extractive engine does not decide them. The closest record is shown.</p>
          <ul>
            {answer.review.map((r) => (
              <li key={r.condition}>
                <p>“{r.condition}” <span className="faint">— {r.filename}</span></p>
                {r.related_record && <p className="faint">Closest record: <span className="mono">{r.related_record.quote}</span> ({r.related_record.filename})</p>}
                {r.conflict_id && <p className="conflict-note">⇄ Another document states the opposite (conflict #{conflicts[r.conflict_id]?.number ?? '?'}).</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="evidence-table">
        <div className="section-title">
          <h3 className="eyebrow">Evidence</h3>
          <button className="btn btn-sm" onClick={() => goTab('graph')}><Icon name="graph" size={15} /> Open evidence graph</button>
        </div>
        <ul>
          {answer.evidence.map((e) => (
            <li key={e.id}>
              <button className="evidence-row" onClick={() => openSource(evidenceSource(e))}>
                <span className={`ev-stance ${e.stance}`}>{e.id}</span>
                <span className="evidence-quote">
                  <span>“{e.quote.length > 260 ? `${e.quote.slice(0, 260)}…` : e.quote}”</span>
                  <span className="faint evidence-why">{e.why}</span>
                </span>
                <span className="evidence-src">
                  <span>{e.filename}</span>
                  <span className="mono faint">{[location(e), e.section?.split(' › ').pop()].filter(Boolean).join(' · ')}</span>
                  <Meter value={e.relevance} color="var(--paper-3)" height={3} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="trace">
        <h3 className="eyebrow">Reasoning trace</h3>
        <ol>
          {answer.timeline.map((s, i) => (
            <li key={i}><span className="mono faint">{String(s.ms).padStart(4, ' ')} ms</span> <strong>{s.step}</strong> <span className="muted">{s.detail}</span></li>
          ))}
        </ol>
      </section>
    </article>
  )
}
