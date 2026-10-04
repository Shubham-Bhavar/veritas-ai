import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'
import { ErrorNote, Icon, Meter } from '../components/ui.jsx'
import { formatDate } from '../components/status.js'
import { useInvestigation } from './context.js'

function PageImage({ documentId, page, chunk, sentence, flags }) {
  const { id } = useInvestigation()
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let alive = true
    let made = null
    setUrl(null)
    setError(null)
    api.pageImage(id, documentId, page, { chunk, sentence, flags })
      .then((u) => { made = u; if (alive) setUrl(u) })
      .catch((e) => alive && setError(e))
    return () => {
      alive = false
      if (made) URL.revokeObjectURL(made)
    }
  }, [id, documentId, page, chunk, sentence, flags])
  if (error) return <ErrorNote error={error} />
  if (!url) return <div className="page-loading"><span className="spinner" /> Rendering page {page}…</div>
  return <img className="page-image" src={url} alt={`Page ${page} with the cited passage highlighted`} />
}

function Highlighted({ text, quote }) {
  const i = quote ? text.indexOf(quote) : -1
  if (i < 0) return <p className="source-text">{text}</p>
  return (
    <p className="source-text">
      {text.slice(0, i)}<mark>{quote}</mark>{text.slice(i + quote.length)}
    </p>
  )
}

export default function Inspector({ source, onClose }) {
  const { id, documents } = useInvestigation()
  const ref = useRef(null)
  const doc = documents.find((d) => d.id === source.documentId)
  const chunk = useQuery({
    queryKey: ['chunk', id, source.chunkId],
    queryFn: () => api.chunk(id, source.chunkId),
    enabled: !!source.chunkId,
  })
  const kind = source.docKind || doc?.kind
  const renderable = kind === 'pdf' || kind === 'image'
  const page = source.page || chunk.data?.chunk?.page

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const stanceText = { supports: 'Supports the claim', contradicts: 'Contradicts the claim', context: 'Context only' }[source.stance]

  return (
    <aside className="inspector" role="dialog" aria-label="Source inspector" tabIndex={-1} ref={ref}>
      <header className="inspector-head">
        <div>
          <span className="eyebrow">Source inspector{source.evidenceId ? ` · ${source.evidenceId}` : ''}</span>
          <h2>{source.filename || doc?.filename}</h2>
          <p className="faint mono">
            {[page && `page ${page}`, source.section || chunk.data?.chunk?.section, doc?.docDate && formatDate(doc.docDate)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close inspector"><Icon name="close" size={16} /></button>
      </header>

      {source.why && (
        <section className="why">
          <span className="eyebrow">Why this evidence matters</span>
          <p>{source.why}</p>
          <div className="why-meta">
            {stanceText && <span className={`ev-stance ${source.stance}`}>{stanceText}</span>}
            {source.relevance != null && (
              <span className="why-rel"><span className="faint">relevance</span> <Meter value={source.relevance} color="var(--paper-2)" height={4} /> <span className="mono">{source.relevance.toFixed(2)}</span></span>
            )}
            {source.ocr && <span className="chip">OCR · quality {(source.quality ?? 0).toFixed(2)}</span>}
            {source.flagged && <span className="chip" style={{ color: 'var(--security)' }}>contains flagged text</span>}
          </div>
        </section>
      )}

      {source.quote && source.kind !== 'security' && (
        <blockquote className="inspector-quote">“{source.quote}”</blockquote>
      )}

      <section className="inspector-view">
        {renderable && page ? (
          <PageImage documentId={source.documentId} page={page} chunk={source.chunkId} sentence={source.quote} flags={source.flags} />
        ) : chunk.data ? (
          <div className="text-view">
            {chunk.data.previous && <p className="source-text faint">{chunk.data.previous.text}</p>}
            <Highlighted text={chunk.data.chunk.text} quote={source.quote} />
            {chunk.data.next && <p className="source-text faint">{chunk.data.next.text}</p>}
          </div>
        ) : chunk.isLoading ? (
          <div className="page-loading"><span className="spinner" /> Loading passage…</div>
        ) : (
          <ErrorNote error={chunk.error} />
        )}
        {source.kind === 'security' && (
          <p className="faint inspector-note">The dashed red box marks text that is invisible on the page but present in the file's text layer.</p>
        )}
      </section>
    </aside>
  )
}
