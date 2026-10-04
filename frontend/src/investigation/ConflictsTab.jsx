import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'
import { Empty, ErrorNote, SeverityTag } from '../components/ui.jsx'
import { formatDate } from '../components/status.js'
import { useInvestigation } from './context.js'

const SOURCE_STATUS = {
  active: ['In force', 'var(--paper)'],
  superseded: ['Superseded', 'var(--paper-3)'],
  amended: ['Amended', 'var(--paper-3)'],
}

function Source({ s, conflict }) {
  const { openSource } = useInvestigation()
  const [label, color] = SOURCE_STATUS[s.status] || SOURCE_STATUS.active
  const inactive = s.status !== 'active'
  return (
    <button
      className={`cf-source ${inactive ? 'inactive' : ''}`}
      onClick={() => openSource({
        kind: 'conflict', documentId: s.document_id, chunkId: s.chunk_id, page: s.page, filename: s.filename,
        section: s.section, quote: s.sentence, why: conflict.reason, stance: inactive ? 'context' : 'contradicts',
      })}
    >
      <span className="cf-value" style={{ color: inactive ? 'var(--paper-3)' : undefined }}>
        {conflict.kind === 'statement' ? (s.value === 'negative' ? 'Denies' : 'Affirms') : s.value}
      </span>
      <span className="cf-doc">{s.filename}</span>
      <span className="mono faint">{[formatDate(s.doc_date), s.page && `p. ${s.page}`, s.section?.split(' › ').pop()].filter(Boolean).join(' · ')}</span>
      <span className="cf-sentence">“{s.sentence}”</span>
      <span className="cf-status" style={{ color }}>{label}</span>
      {s.note && <span className="faint cf-note">{s.note}</span>}
    </button>
  )
}

export default function ConflictsTab() {
  const { id, indexed } = useInvestigation()
  const [filter, setFilter] = useState('UNRESOLVED')
  const q = useQuery({ queryKey: ['conflicts', id], queryFn: () => api.conflicts(id), enabled: indexed > 0 })
  if (indexed === 0) return <Empty title="Nothing to compare yet">Conflicts appear once documents are indexed.</Empty>
  if (q.isLoading) return <div className="row faint"><span className="spinner" /> Scanning for conflicts…</div>
  if (q.isError) return <ErrorNote error={q.error} onRetry={q.refetch} />
  const all = q.data.conflicts
  const shown = all.filter((c) => filter === 'ALL' || c.status === filter)
  const sum = q.data.summary

  return (
    <div className="conflicts">
      <header className="radar-head">
        <div>
          <span className="eyebrow">Conflict Radar</span>
          <h2 className="serif">Where the documents disagree.</h2>
          <p className="muted">
            Facts are matched across documents by what they describe. A conflict is resolved only when a document explicitly
            supersedes or amends another — never because it is newer.
          </p>
        </div>
        <dl className="radar-stats">
          <div><dt>Unresolved</dt><dd style={{ color: sum.unresolved ? 'var(--uncertain)' : undefined }}>{sum.unresolved}</dd></div>
          <div><dt>High severity</dt><dd style={{ color: sum.high ? 'var(--contradicted)' : undefined }}>{sum.high}</dd></div>
          <div><dt>Resolved by evidence</dt><dd>{sum.resolved}</dd></div>
        </dl>
      </header>

      <div className="segmented" role="tablist">
        {[['UNRESOLVED', 'Unresolved'], ['RESOLVED', 'Resolved'], ['ALL', 'All']].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? 'active' : ''} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>

      {shown.length === 0 && <p className="faint">{all.length === 0 ? 'The documents agree on every comparable fact.' : 'Nothing in this view.'}</p>}

      <ol className="cf-list">
        {shown.map((c) => (
          <li key={c.id} className={`cf-card panel ${c.status === 'RESOLVED' ? 'resolved' : ''}`}>
            <header className="cf-head">
              <span className="cf-number mono">CONFLICT #{String(c.number).padStart(2, '0')}</span>
              <SeverityTag severity={c.severity} />
              <span className={`resolution ${c.status === 'RESOLVED' ? 'ok' : 'open'}`}>{c.status === 'RESOLVED' ? 'Resolved by evidence' : 'Unresolved'}</span>
              <span className="mono faint cf-id">{c.id}</span>
            </header>
            <h3 className="cf-attr serif">{c.kind === 'statement' ? `Contradictory rules · ${c.attribute}` : c.attribute.charAt(0).toUpperCase() + c.attribute.slice(1)}</h3>
            <div className="cf-sources">
              {c.sources.map((s, i) => (
                <div key={s.fact_id} className="cf-source-wrap">
                  {i > 0 && <span className="cf-vs faint">vs</span>}
                  <Source s={s} conflict={c} />
                </div>
              ))}
            </div>
            <dl className="cf-explain">
              <div><dt>Why it is a conflict</dt><dd>{c.reason}</dd></div>
              <div><dt>Resolution</dt><dd>{c.resolution}</dd></div>
              {c.newer && c.status !== 'RESOLVED' && <div><dt>Most recent</dt><dd>{c.newer.filename} ({formatDate(c.newer.doc_date)}) — reported, not used to decide.</dd></div>}
              <div><dt>Recommendation</dt><dd>{c.recommendation}</dd></div>
            </dl>
          </li>
        ))}
      </ol>
    </div>
  )
}
