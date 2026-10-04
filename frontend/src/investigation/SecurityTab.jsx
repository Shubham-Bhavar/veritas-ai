import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'
import { Empty, ErrorNote, SeverityTag } from '../components/ui.jsx'
import { useInvestigation } from './context.js'

export default function SecurityTab() {
  const { id, indexed, openSource } = useInvestigation()
  const q = useQuery({ queryKey: ['security', id], queryFn: () => api.security(id), enabled: indexed > 0 })

  return (
    <div className="security-tab">
      <header>
        <span className="eyebrow">Security layer</span>
        <h2 className="serif">Documents are evidence. Never instructions.</h2>
        <p className="muted">
          Every passage is scanned for text that tries to instruct an AI system, and every PDF for text a reader cannot see
          (white, microscopic or off-page). Flagged text is never turned into facts, never used as supporting evidence, and is
          redacted before any language-model call. Confidence is computed by the engine, so it cannot be dictated by a document.
        </p>
      </header>
      <ol className="defences">
        <li><strong>Detect</strong><span className="faint">pattern scoring for override, role-play, confidence-dictation and concealment requests</span></li>
        <li><strong>Reveal</strong><span className="faint">hidden-text extraction from the PDF text layer, located on the page</span></li>
        <li><strong>Quarantine</strong><span className="faint">excluded from fact extraction and from evidence</span></li>
        <li><strong>Redact</strong><span className="faint">replaced with a marker in any prompt; passages wrapped as data</span></li>
        <li><strong>Verify</strong><span className="faint">LLM claims need real citations and grounded numbers; the cautious verdict wins</span></li>
      </ol>
      {q.isLoading && <div className="row faint"><span className="spinner" /> Loading…</div>}
      <ErrorNote error={q.error} onRetry={q.refetch} />
      {q.data && q.data.flags.length === 0 && <Empty title="No suspicious content found">No instruction-like or hidden text was detected in this investigation.</Empty>}
      <ul className="flags">
        {q.data?.flags.map((f) => (
          <li key={f.id} className="flag panel">
            <header>
              <span className="eyebrow" style={{ color: 'var(--security)' }}>{f.kind === 'hidden_text' ? 'Hidden text' : 'Instruction-like text'}</span>
              <SeverityTag severity={f.severity} />
              <span className="faint">{f.filename}{f.page ? ` · page ${f.page}` : ''}</span>
            </header>
            <p className="quarantined mono">{f.text}</p>
            <ul className="reasons">{f.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <div className="flag-foot">
              <span className="faint">Action: neutralised — excluded from evidence and facts; redacted from AI prompts.</span>
              {f.page && (
                <button className="btn btn-sm" onClick={() => openSource({ kind: 'security', documentId: f.document_id, page: f.page, filename: f.filename, flags: true, quote: f.text })}>
                  Show on page
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
