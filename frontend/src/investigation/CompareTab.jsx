import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api.js'
import { Empty, ErrorNote, Icon, SeverityTag } from '../components/ui.jsx'
import { formatDate } from '../components/status.js'
import { useInvestigation } from './context.js'

const KIND = {
  changed: ['Changed', 'var(--uncertain)'],
  added: ['Added', 'var(--supported)'],
  removed: ['Removed', 'var(--contradicted)'],
}

function Side({ side, doc, label }) {
  const { openSource } = useInvestigation()
  if (!side) return <div className="cmp-side empty"><span className="faint">— not in {label} —</span></div>
  return (
    <button className="cmp-side" onClick={() => openSource({
      kind: 'compare', documentId: doc.document_id, chunkId: side.chunk_id, page: side.page, filename: doc.filename,
      section: side.section, quote: side.sentence,
    })}>
      {side.display && <span className="cmp-value mono">{side.display}</span>}
      <span className="cmp-sentence">“{side.sentence}”</span>
      <span className="mono faint">{[side.page && `p. ${side.page}`, side.section?.split(' › ').pop()].filter(Boolean).join(' · ')}</span>
    </button>
  )
}

export default function CompareTab() {
  const { id, documents, compareRequest, setCompareRequest } = useInvestigation()
  const indexed = documents.filter((d) => d.status === 'INDEXED')
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const run = useMutation({ mutationFn: ([x, y]) => api.compare(id, x, y) })

  useEffect(() => {
    if (compareRequest) {
      setA(compareRequest[0])
      setB(compareRequest[1])
      run.mutate(compareRequest)
      setCompareRequest(null)
    }
  }, [compareRequest]) // eslint-disable-line react-hooks/exhaustive-deps

  if (indexed.length < 2) return <Empty title="Compare needs two indexed documents">Upload at least two documents, for example two versions of a policy.</Empty>
  const r = run.data

  return (
    <div className="compare">
      <header className="cmp-head">
        <span className="eyebrow">Compare documents</span>
        <h2 className="serif">What changed — and what it changes.</h2>
        <form className="cmp-form" onSubmit={(e) => { e.preventDefault(); if (a && b && a !== b) run.mutate([a, b]) }}>
          <select className="select" value={a} onChange={(e) => setA(e.target.value)} aria-label="First document">
            <option value="">First document…</option>
            {indexed.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
          </select>
          <Icon name="compare" />
          <select className="select" value={b} onChange={(e) => setB(e.target.value)} aria-label="Second document">
            <option value="">Second document…</option>
            {indexed.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
          </select>
          <button className="btn btn-primary" disabled={!a || !b || a === b || run.isPending}>
            {run.isPending ? <span className="spinner" /> : null} Compare
          </button>
        </form>
        {a && b && a === b && <p className="form-error">Choose two different documents.</p>}
      </header>
      <ErrorNote error={run.error} />

      {r && (
        <section className="cmp-result rise">
          <div className="cmp-docs">
            <div><span className="eyebrow">Before</span><strong>{r.before.filename}</strong><span className="faint mono">{formatDate(r.before.doc_date)}</span></div>
            <Icon name="arrow" />
            <div><span className="eyebrow">After</span><strong>{r.after.filename}</strong><span className="faint mono">{formatDate(r.after.doc_date)}</span></div>
          </div>
          {r.reordered && <p className="faint">Ordered by document date, oldest first.</p>}
          {r.relation && <p className="cmp-relation">{r.relation}</p>}
          <dl className="cmp-summary">
            <div><dt>Changed</dt><dd>{r.summary.changed}</dd></div>
            <div><dt>Added</dt><dd>{r.summary.added}</dd></div>
            <div><dt>Removed</dt><dd>{r.summary.removed}</dd></div>
            <div><dt>Unchanged values</dt><dd>{r.summary.unchanged_values}</dd></div>
          </dl>
          {r.changes.length === 0 && <p className="faint">No differences in values or requirements were found.</p>}
          <ul className="cmp-list">
            {r.changes.map((c, i) => {
              const [label, color] = KIND[c.kind]
              return (
                <li key={i} className="cmp-item panel">
                  <header>
                    <span className="cmp-kind" style={{ color }}>{label}</span>
                    <span className="cmp-cat mono faint">{c.category}</span>
                    <SeverityTag severity={c.significance} />
                    {c.category !== 'requirement' && <span className="cmp-label">{c.label}</span>}
                  </header>
                  <div className="cmp-sides">
                    <Side side={c.before} doc={r.before} label="the earlier document" />
                    <span className="cmp-arrow faint">→</span>
                    <Side side={c.after} doc={r.after} label="the later document" />
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
